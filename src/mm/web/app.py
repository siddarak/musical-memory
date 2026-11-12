"""The web page for parents.

Server-rendered pages and plain forms. No page carries a script and nothing is loaded from
another site, so a family's data goes nowhere else and the pages work with scripts off.

This layer never decides whether a song may go forward. It asks the pipeline, which owns both
human approvals and every limit. The participant code in the address is the only key to a
household's songs, so every song is looked up through it.
"""

import logging
from collections import defaultdict
from importlib import resources
from typing import Annotated, Any
from urllib.parse import parse_qs

import jinja2
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint

from mm.domain import Song, SongStatus
from mm.pipeline import Blocked, LimitReached, LyricsNotAccepted, Pipeline, WrongState
from mm.presets import STYLE_PRESETS
from mm.safety import rules
from mm.web import studio, views
from mm.web.access import Participants
from mm.web.events import EventLog
from mm.web.runner import Runner, ThreadRunner

log = logging.getLogger("mm.web")

MAX_BODY = 20_000  # bytes; the longest honest form is far smaller
MAX_FIELDS = 60
AUTO_KICKS = 3  # times a page view may restart stalled work before asking the parent

CSP = (
    "default-src 'none'; style-src 'self'; font-src 'self'; media-src 'self'; img-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,  # no scripts at all, nothing from other sites
    "Referrer-Policy": "no-referrer",  # the participant code in the address never leaks
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Robots-Tag": "noindex, nofollow",
    "Strict-Transport-Security": "max-age=31536000",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

_STATIC = {
    "app.css": "text/css; charset=utf-8",
    "icon.svg": "image/svg+xml",
    "fonts/atkinson-hyperlegible-latin-400-normal.woff2": "font/woff2",
    "fonts/atkinson-hyperlegible-latin-700-normal.woff2": "font/woff2",
}

_PROBLEMS = {
    400: "We could not read that form. Go back and try again.",
    403: "That request came from another site, so we ignored it.",
    404: "We can't find that page. Check the link the team sent you.",
    409: "That step is already done. Go back to the song to see where it is.",
    411: "We could not read that form. Go back and try again.",
    413: "That is more text than this form takes.",
    415: "We could not read that form. Go back and try again.",
}
_OUR_FAULT = "Something went wrong on our side. Nothing was lost. Please try again."


async def form_fields(request: Request) -> views.Fields:
    """The fields of a posted form. The size was already checked before the body was read."""
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413)
    try:
        return parse_qs(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=MAX_FIELDS)
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400) from None


Form = Annotated[views.Fields, Depends(form_fields)]


def _post_problem(request: Request) -> int | None:
    """Why a POST is refused before anything reads it, as a status code. None means go on."""
    # A browser says where a form was sent from. Only our own pages may post to us.
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return 403
    kind = request.headers.get("content-type", "")
    if not kind.startswith("application/x-www-form-urlencoded"):
        return 415
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        return 411
    if int(length) > MAX_BODY:
        return 413
    return None


def create_app(
    *,
    pipeline: Pipeline,
    participants: Participants,
    events: EventLog,
    runner: Runner | None = None,
    team: Participants | None = None,
) -> FastAPI:
    """The web app.

    `participants` holds the codes families use. `team` holds the separate codes that open the
    team view, which is read-only and shows every household's songs; with none, there is no
    team view at all and its addresses are simply not found.
    """
    store = pipeline.store
    work: Runner = runner or ThreadRunner(pipeline)
    kicks: defaultdict[str, int] = defaultdict(int)
    shown: set[tuple[str, str]] = set()

    templates = jinja2.Environment(
        loader=jinja2.PackageLoader("mm.web", "templates"),
        autoescape=True,  # everything a page prints is escaped
        undefined=jinja2.StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    static = {
        name: resources.files("mm.web").joinpath("static", name).read_bytes() for name in _STATIC
    }

    # No API pages: the forms are the whole surface.
    app = FastAPI(title="Musical Memory", docs_url=None, redoc_url=None, openapi_url=None)

    def team_knows(code: str) -> bool:
        return team is not None and team.knows(code)

    def page(name: str, status: int = 200, **context: Any) -> HTMLResponse:
        context.setdefault("refresh", None)
        context.setdefault("step", None)
        context.setdefault("step_name", "")
        context.setdefault("home_url", None)
        context.setdefault("journey", views.JOURNEY)
        return HTMLResponse(templates.get_template(name).render(**context), status_code=status)

    def problem_page(status: int, message: str | None = None) -> HTMLResponse:
        text = message or _PROBLEMS.get(status, _OUR_FAULT)
        heading = "Page not found" if status == 404 else "That did not work"
        return page("message.html", status, title=heading, heading=heading, message=text)

    def song_url(code: str, song_id: str) -> str:
        return f"/h/{code}/songs/{song_id}"

    def find(code: str, song_id: str) -> Song:
        """The song, but only for the household that owns it. Anything else is 'not found'."""
        if not participants.knows(code):
            raise HTTPException(404)
        try:
            song = store.get(song_id)
        except (KeyError, ValueError):
            raise HTTPException(404) from None
        if song.household_id != code:
            raise HTTPException(404)
        return song

    def once(code: str, song_id: str, name: str) -> None:
        """Record that a page was first shown, without logging every refresh."""
        if (song_id, name) not in shown:
            shown.add((song_id, name))
            events.record(code, name, song_id)

    def home_page(
        code: str, data: dict[str, Any], problems: list[str], status: int = 200
    ) -> HTMLResponse:
        songs = [
            {
                "routine": song.brief.routine,
                "label": views.STATUS_LABELS[song.status],
                "url": song_url(code, song.id),
            }
            for song in store.songs_for_household(code)
        ]
        return page(
            "home.html",
            status,
            title="Make a song",
            step=1,
            step_name="describe the routine",
            home_url=f"/h/{code}",
            action=f"/h/{code}/songs",
            form=views.form_values(data),
            problems=problems,
            styles=[(key, preset.label) for key, preset in STYLE_PRESETS.items()],
            left=pipeline.songs_left_today(code),
            songs=songs,
        )

    def song_page(
        code: str,
        song: Song,
        *,
        editing: bool = False,
        stalled: bool = False,
        problems: list[str] | None = None,
        typed: list[str] | None = None,
        status: int = 200,
    ) -> HTMLResponse:
        view = views.song_view(song, pipeline.limits, editing=editing, stalled=stalled)
        if view["mode"] == "edit" and song.lyrics:
            view["edit_sections"] = views.edit_lines(song.lyrics, typed)
        if view["mode"] in ("words", "edit"):
            once(code, song.id, "words_shown")
        if view["mode"] == "listen":
            once(code, song.id, "audio_shown")
        return page(
            "song.html",
            status,
            title=views.STATUS_LABELS[song.status],
            home_url=f"/h/{code}",
            url=song_url(code, song.id),
            problems=problems or [],
            **view,
        )

    # ---- every request ----------------------------------------------------------------------

    @app.middleware("http")
    async def guard(request: Request, call_next: RequestResponseEndpoint) -> Response:
        refused = _post_problem(request) if request.method == "POST" else None
        response = problem_page(refused) if refused else await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_problem(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
        return problem_page(exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc: RequestValidationError) -> HTMLResponse:
        return problem_page(400)

    @app.exception_handler(Exception)
    async def our_fault(request: Request, exc: Exception) -> HTMLResponse:
        log.error("unhandled %s on %s", type(exc).__name__, request.url.path.split("/")[1:2])
        response = problem_page(500)
        response.headers.update(SECURITY_HEADERS)
        return response

    # ---- pages anyone can open --------------------------------------------------------------

    @app.get("/")
    def landing() -> HTMLResponse:
        return page(
            "message.html",
            title="Musical Memory",
            heading="Musical Memory",
            message=(
                "This is a private study prototype. "
                "To make a song, open the link the team sent you."
            ),
        )

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/static/{name:path}")
    def static_file(name: str) -> Response:
        if name not in static:  # a fixed list, so no path can wander
            raise HTTPException(404)
        headers = {"Cache-Control": "public, max-age=86400"}
        return Response(static[name], media_type=_STATIC[name], headers=headers)

    # ---- the team view: read-only, and it never touches a song ------------------------------

    def team_page(name: str, code: str, tab: str, **context: Any) -> HTMLResponse:
        return page(name, base=f"/studio/{code}", tab=tab, **context)

    @app.get("/studio/{code}")
    def team_live(code: str) -> HTMLResponse:
        if not team_knows(code):
            raise HTTPException(404)
        songs = store.recent_songs(100)
        return team_page(
            "studio.html",
            code,
            "live",
            title="What happened",
            refresh=10,
            numbers=studio.numbers(songs, pipeline.limits, pipeline.controls.generation_enabled()),
            journey=studio.journey_with_counts(songs),
            songs=[studio.song_row(song) for song in songs],
            events=[studio.event_row(entry) for entry in events.recent(60)],
        )

    @app.get("/studio/{code}/journey")
    def team_journey(code: str) -> HTMLResponse:
        if not team_knows(code):
            raise HTTPException(404)
        limits = pipeline.limits
        worst = limits.max_music_calls_per_song * limits.music_price_per_minute_usd
        return team_page(
            "studio_journey.html",
            code,
            "journey",
            title="How it works",
            journey=studio.journey_with_counts([]),
            guardrails=studio.GUARDRAILS,
            decisions=studio.DECISIONS,
            gaps=studio.GAPS,
            checks=studio.checks_summary(),
            redteam=studio.REDTEAM,
            limits=limits,
            worst_case=worst,
        )

    @app.get("/studio/{code}/songs/{song_id}")
    def team_song(code: str, song_id: str) -> HTMLResponse:
        if not team_knows(code):
            raise HTTPException(404)
        try:
            found = store.get(song_id)
        except (KeyError, ValueError):
            raise HTTPException(404) from None
        return team_page(
            "studio_song.html",
            code,
            "live",
            title=found.brief.routine,
            song=studio.song_detail(found),
        )

    # ---- a household's pages ----------------------------------------------------------------

    @app.get("/h/{code}")
    def home(code: str) -> HTMLResponse:
        if not participants.knows(code):
            raise HTTPException(404)
        return home_page(code, views.empty_form(), [])

    @app.post("/h/{code}/songs")
    def start_song(code: str, fields: Form) -> Response:
        if not participants.knows(code):
            raise HTTPException(404)
        data = views.brief_data(fields)
        brief, findings = rules.screen_raw(data)
        if brief is None or findings:
            name = "brief_invalid" if brief is None else "brief_refused"
            events.record(code, name, codes=sorted({finding.code for finding in findings}))
            return home_page(code, data, views.messages(findings), status=422)
        try:
            song = pipeline.create(brief, code)
        except LimitReached as err:
            events.record(code, "limit_reached")
            return home_page(code, data, [str(err)], status=429)
        events.record(code, "song_started", song.id, style=brief.style, steps=len(brief.steps))
        work.kick(song.id)
        return RedirectResponse(song_url(code, song.id), status_code=303)

    @app.get("/h/{code}/songs/{song_id}")
    def show_song(code: str, song_id: str, edit: bool = False) -> HTMLResponse:
        song = find(code, song_id)
        stalled = False
        waiting_on_us = song.status in views.WORKING and song.blocked is None
        if waiting_on_us and not work.is_working(song.id):
            # The work stopped without finishing, perhaps because the server restarted.
            if kicks[song.id] < AUTO_KICKS:
                kicks[song.id] += 1
                work.kick(song.id)
                song = find(code, song_id)
            still_waiting = song.status in views.WORKING and song.blocked is None
            stalled = still_waiting and not work.is_working(song.id)
        if song.status not in views.WORKING:
            kicks.pop(song.id, None)
        return song_page(code, song, editing=edit, stalled=stalled)

    @app.post("/h/{code}/songs/{song_id}/words")
    def decide_words(code: str, song_id: str, fields: Form) -> Response:
        """A parent approves the words, saves their own edit, or asks for a fresh draft."""
        song = find(code, song_id)
        action = views.one(fields, "action")
        typed = fields.get("line", [])
        try:
            if action == "redraft":
                pipeline.redraft(song.id)
                events.record(code, "fresh_draft", song.id)
            elif action == "approve":
                pipeline.approve_lyrics(song.id, by="parent")
                events.record(code, "words_approved", song.id, edited=False)
            elif action == "save" and song.lyrics is not None:
                edited = views.apply_edit(song.lyrics, typed)
                changed = edited != song.lyrics
                pipeline.approve_lyrics(song.id, by="parent", edited=edited if changed else None)
                events.record(code, "words_approved", song.id, edited=changed)
            else:
                raise HTTPException(400)
        except LyricsNotAccepted as err:
            codes = sorted({finding.code for finding in err.findings})
            events.record(code, "edit_refused", song.id, codes=codes)
            problems = views.messages(err.findings)
            return song_page(code, song, editing=True, problems=problems, typed=typed, status=422)
        except ValidationError:
            problems = ["Each line needs some words, and no line can be longer than 100 letters."]
            return song_page(code, song, editing=True, problems=problems, typed=typed, status=422)
        except ValueError:
            raise HTTPException(400) from None
        except WrongState:
            raise HTTPException(409) from None
        except (LimitReached, Blocked) as err:
            return song_page(code, song, editing=action == "save", problems=[str(err)], status=409)
        work.kick(song.id)
        return RedirectResponse(song_url(code, song.id), status_code=303)

    @app.post("/h/{code}/songs/{song_id}/listen")
    def decide_audio(code: str, song_id: str, fields: Form) -> Response:
        """An adult has listened and says yes, no, or no but try once more."""
        song = find(code, song_id)
        decision = views.one(fields, "decision")
        try:
            if decision == "approve":
                if song.status is not SongStatus.AUDIO_CHECKED:
                    raise WrongState("not at the listening step")
                if views.one(fields, "listened") != "yes":
                    problems = ["Tick the box to say you listened to the whole song."]
                    return song_page(code, song, problems=problems, status=422)
                pipeline.adult_approve(song.id, by="parent")
                events.record(code, "listen_approved", song.id)
            elif decision in ("retry", "reject"):
                again = decision == "retry"
                reason = views.clean_reason(views.one(fields, "reason"))
                pipeline.adult_reject(song.id, by="parent", reason=reason, try_again=again)
                events.record(code, "listen_rejected", song.id, try_again=again)
                if again:
                    work.kick(song.id)
            else:
                raise HTTPException(400)
        except WrongState:
            raise HTTPException(409) from None
        return RedirectResponse(song_url(code, song.id), status_code=303)

    @app.post("/h/{code}/songs/{song_id}/resume")
    def resume(code: str, song_id: str) -> Response:
        """Try again after a pause. The pipeline still decides whether anything may run."""
        song = find(code, song_id)
        kicks.pop(song.id, None)
        events.record(code, "resumed", song.id)
        work.kick(song.id)
        return RedirectResponse(song_url(code, song.id), status_code=303)

    @app.get("/h/{code}/songs/{song_id}/audio")
    def audio(code: str, song_id: str, request: Request) -> Response:
        song = find(code, song_id)
        ready = song.status in (SongStatus.AUDIO_CHECKED, SongStatus.PUBLISHED)
        if not ready or song.audio_path is None or song.audio_mime is None:
            raise HTTPException(404)  # nothing to hear before the audio has passed its checks
        data = store.get_audio(song.audio_path)
        return views.ranged(data, song.audio_mime, request.headers.get("range"))

    return app
