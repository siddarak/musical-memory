"""The web page's promises: what a parent can do, and what nobody can do through it."""

from __future__ import annotations

import json
import re
import threading
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from conftest import Rig
from mm.cli import build_site, main
from mm.domain import Line, SongStatus
from mm.pipeline import Limits
from mm.web import create_app
from mm.web.access import Allowlist, new_code
from mm.web.app import AUTO_KICKS, MAX_BODY
from mm.web.events import JsonlEvents, MemoryEvents
from mm.web.runner import InlineRunner, ThreadRunner

A = "house-a"
B = "house-b"
FORM = {"content-type": "application/x-www-form-urlencoded"}
BRIEF = {
    "routine": "bedtime",
    "step": ["brush teeth", "put on pajamas", "read one book", "lights out", ""],
    "style": "gentle_lullaby",
    "age_band": "3-4",
    "nickname": "Mimi",
}


class Site:
    """The web app on a test rig, with helpers for the things a parent does."""

    def __init__(self, rig: Rig | None = None) -> None:
        self.rig = rig or Rig()
        self.events = MemoryEvents(self.rig.clock)
        self.app = create_app(
            pipeline=self.rig.pipeline,
            participants=Allowlist([A, B]),
            events=self.events,
            runner=InlineRunner(self.rig.pipeline),
        )
        self.client = TestClient(self.app, follow_redirects=False)

    def get(self, path: str, **headers: str):
        return self.client.get(path, headers=headers)

    def post(self, path: str, data: dict | None = None, **headers: str):
        body = urlencode(data or {}, doseq=True)
        return self.client.post(path, content=body, headers={**FORM, **headers})

    def start(self, code: str = A, **changes: object) -> str:
        """Send a good brief and return the address of the new song."""
        response = self.post(f"/h/{code}/songs", {**BRIEF, **changes})
        assert response.status_code == 303, response.text
        return response.headers["location"]

    def to_listen(self, code: str = A) -> str:
        url = self.start(code)
        assert self.post(f"{url}/words", {"action": "approve"}).status_code == 303
        return url

    def song(self, url: str):
        return self.rig.store.get(url.rsplit("/", 1)[1])


@pytest.fixture
def site() -> Site:
    return Site()


def problems(html: str) -> str:
    """The text of the 'please change this' box, or an empty string."""
    found = re.search(r'<div class="problem".*?</div>', html, re.S)
    return found.group(0) if found else ""


# ---- the whole journey ----------------------------------------------------------------------


def test_a_parent_can_make_a_song_from_start_to_finish(site):
    home = site.get(f"/h/{A}")
    assert home.status_code == 200
    assert "What should the song be about?" in home.text
    assert "You can make 5 more songs today" in home.text

    url = site.start()
    words = site.get(url)
    assert "Do these words sound right?" in words.text
    assert "Mimi" in words.text, "the name the parent gave is sung"
    for number, step in enumerate(site.song(url).brief.steps, start=1):
        bead = f'<span class="bead" title="Step {number} of the routine">{number}</span>'
        assert bead in words.text, f"step {number} has no number beside it"
        assert step.capitalize() in words.text or step in words.text, step
    assert site.rig.music.calls == 0

    assert site.post(f"{url}/words", {"action": "approve"}).status_code == 303
    listen = site.get(url)
    assert "Listen before your child does" in listen.text
    assert f'<audio controls preload="metadata" src="{url}/audio">' in listen.text

    audio = site.get(f"{url}/audio")
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav"

    done = site.post(f"{url}/listen", {"decision": "approve", "listened": "yes"})
    assert done.status_code == 303
    assert "Ready to play" in site.get(url).text
    assert site.song(url).status is SongStatus.PUBLISHED
    assert site.events.names() == [
        "song_started",
        "words_shown",
        "words_approved",
        "audio_shown",
        "listen_approved",
    ]
    assert "Ready to play" in site.get(f"/h/{A}").text  # and it is listed on the home page


# ---- what nobody can do ---------------------------------------------------------------------


def test_nothing_can_be_heard_or_published_before_the_words_are_approved(site):
    url = site.start()
    assert site.get(f"{url}/audio").status_code == 404
    assert site.post(f"{url}/listen", {"decision": "approve", "listened": "yes"}).status_code == 409
    assert site.post(f"{url}/listen", {"decision": "retry"}).status_code == 409
    assert site.song(url).status is SongStatus.LYRICS_READY
    assert site.rig.music.calls == 0


def test_audio_that_has_not_passed_its_checks_cannot_be_heard(site):
    url = site.start()
    song = site.song(url)
    song.audio_path = site.rig.store.put_audio(song.id, b"RIFF unchecked", "audio/wav")
    song.audio_mime = "audio/wav"
    song.status = SongStatus.COMPOSED  # made, but the audio checks have not run yet
    site.rig.store.save(song)
    held = create_app(
        pipeline=site.rig.pipeline,
        participants=Allowlist([A]),
        events=site.events,
        runner=_Busy(),
    )
    assert TestClient(held).get(f"{url}/audio").status_code == 404


def test_publishing_needs_the_adult_to_say_they_listened(site):
    url = site.to_listen()
    refused = site.post(f"{url}/listen", {"decision": "approve"})
    assert refused.status_code == 422
    assert "Tick the box" in problems(refused.text)
    assert site.song(url).status is SongStatus.AUDIO_CHECKED

    assert site.post(f"{url}/listen", {"decision": "approve", "listened": "no"}).status_code == 422
    assert site.post(f"{url}/listen", {"decision": "approve", "listened": "yes"}).status_code == 303
    assert site.song(url).status is SongStatus.PUBLISHED


def test_a_step_cannot_be_done_twice(site):
    url = site.to_listen()
    assert site.post(f"{url}/words", {"action": "approve"}).status_code == 409
    assert site.post(f"{url}/words", {"action": "redraft"}).status_code == 409
    site.post(f"{url}/listen", {"decision": "approve", "listened": "yes"})
    assert site.post(f"{url}/listen", {"decision": "approve", "listened": "yes"}).status_code == 409
    assert site.post(f"{url}/listen", {"decision": "reject"}).status_code == 409
    assert site.song(url).status is SongStatus.PUBLISHED


def test_one_household_cannot_see_or_touch_anothers_song(site):
    url = site.to_listen(A)
    theirs = url.replace(f"/h/{A}/", f"/h/{B}/")
    assert site.get(theirs).status_code == 404
    assert site.get(f"{theirs}/audio").status_code == 404
    yes = {"decision": "approve", "listened": "yes"}
    assert site.post(f"{theirs}/listen", yes).status_code == 404
    assert site.post(f"{theirs}/listen", {"decision": "reject"}).status_code == 404
    assert site.post(f"{theirs}/resume").status_code == 404
    assert site.song(url).status is SongStatus.AUDIO_CHECKED
    assert "Your songs" not in site.get(f"/h/{B}").text  # and it is not on their home page


def test_an_unknown_code_or_song_is_simply_not_found(site):
    url = site.start()
    pages = [
        site.get("/h/not-a-code"),
        site.post("/h/not-a-code/songs", BRIEF),
        site.get(f"/h/not-a-code/songs/{url.rsplit('/', 1)[1]}"),
        site.get(f"/h/{A}/songs/song9999"),
        site.get(f"/h/{A}/songs/..%2F..%2Fetc"),
    ]
    assert {page.status_code for page in pages} == {404}
    assert len({page.text for page in pages}) == 1, "every miss looks the same"
    assert len(site.rig.store.songs_for_household("not-a-code")) == 0


def test_a_code_that_was_taken_off_the_list_opens_nothing(site):
    url = site.to_listen(A)
    without_a = create_app(
        pipeline=site.rig.pipeline,
        participants=Allowlist([B]),
        events=site.events,
        runner=InlineRunner(site.rig.pipeline),
    )
    client = TestClient(without_a, follow_redirects=False)
    assert client.get(url).status_code == 404
    assert client.get(f"{url}/audio").status_code == 404
    assert client.get(f"/h/{A}").status_code == 404


def test_a_form_sent_from_another_site_is_ignored(site):
    for origin in ("cross-site", "same-site"):
        response = site.post(f"/h/{A}/songs", BRIEF, **{"sec-fetch-site": origin})
        assert response.status_code == 403
    assert site.rig.store.songs_for_household(A) == []
    assert site.post(f"/h/{A}/songs", BRIEF, **{"sec-fetch-site": "same-origin"}).status_code == 303


def test_oversized_and_odd_posts_are_refused_before_they_are_read(site):
    big = {**BRIEF, "nickname": "x" * (MAX_BODY + 1)}
    assert site.post(f"/h/{A}/songs", big).status_code == 413
    as_json = site.client.post(
        f"/h/{A}/songs", content=json.dumps(BRIEF), headers={"content-type": "application/json"}
    )
    assert as_json.status_code == 415
    assert site.rig.store.songs_for_household(A) == []


# ---- the brief form -------------------------------------------------------------------------


def test_a_brief_with_a_mistake_is_explained_and_nothing_is_made(site):
    response = site.post(f"/h/{A}/songs", {**BRIEF, "step": ["brush teeth", "lights out"]})
    assert response.status_code == 422
    assert "Give 3 to 5 steps." in problems(response.text)
    assert 'value="brush teeth"' in response.text, "what was typed is still in the form"
    assert site.rig.store.songs_for_household(A) == []
    assert site.events.names() == ["brief_invalid"]


def test_choices_that_were_skipped_get_plain_messages(site):
    response = site.post(f"/h/{A}/songs", {**BRIEF, "style": "", "age_band": ""})
    text = problems(response.text)
    assert "Choose how the song should sound." in text
    assert "Choose how old your child is." in text
    assert "Input should be" not in response.text


def test_a_refused_brief_says_why_without_repeating_the_words(site):
    steps = ["sing baby shark", "brush teeth", "lights out"]
    response = site.post(f"/h/{A}/songs", {**BRIEF, "step": steps})
    assert response.status_code == 422
    text = problems(response.text)
    assert "artists, songs, shows or characters" in text
    assert "shark" not in text
    assert site.rig.store.songs_for_household(A) == [] and site.rig.paid_calls() == 0
    assert site.events.items[-1]["detail"] == {"codes": ["brand_name"]}


def test_the_daily_limit_is_explained(site):
    site.rig.pipeline.limits = Limits(songs_per_household_per_day=1)
    site.start()
    assert "all of today's songs" in site.get(f"/h/{A}").text
    again = site.post(f"/h/{A}/songs", BRIEF)
    assert again.status_code == 429
    assert "made all of today's songs" in again.text
    assert site.post(f"/h/{B}/songs", BRIEF).status_code == 303  # another family still can


# ---- checking and changing the words --------------------------------------------------------


def typed_lines(site: Site, url: str) -> list[str]:
    return [line.text for line in site.song(url).lyrics.lines()]


def chorus_line_numbers(site: Site, url: str) -> list[int]:
    """Where each chorus's first line sits in the flat list the edit form posts back."""
    song = site.song(url)
    found, seen = [], 0
    for section in song.lyrics.sections:
        if section.name == "chorus":
            found.append(seen)
        seen += len(section.lines)
    return found


def test_a_parent_can_change_the_words(site):
    url = site.start()
    form = site.get(f"{url}?edit=1")
    lines = typed_lines(site, url)
    assert form.text.count('name="line"') == len(lines)
    assert f'value="{lines[0]}"' in form.text, "the words are in the form, ready to edit"

    # Both choruses have to change together, which is the rule this edit respects.
    first, second = chorus_line_numbers(site, url)
    lines[first] = lines[second] = "Step by step, we find our way"
    saved = site.post(f"{url}/words", {"action": "save", "line": lines})
    assert saved.status_code == 303
    song = site.song(url)
    assert song.lyrics_source == "parent_edit"
    assert song.lyrics.lines()[first].text == "Step by step, we find our way"
    steps = [line.step for line in song.lyrics.lines() if line.step is not None]
    assert steps == sorted(steps) and set(steps) == set(range(len(song.brief.steps)))
    assert site.events.items[-1]["detail"] == {"edited": True}


def test_a_change_with_refused_words_is_sent_back_with_the_typing_kept(site):
    url = site.start()
    before = site.song(url).lyrics
    lines = typed_lines(site, url)
    lines[-1] = "Bed now, or else no story"
    refused = site.post(f"{url}/words", {"action": "save", "line": lines})
    assert refused.status_code == 422
    assert "not right for a song for a young child" in problems(refused.text)
    assert 'value="Bed now, or else no story"' in refused.text
    saved = site.song(url)
    assert saved.status is SongStatus.LYRICS_READY and saved.lyrics == before
    assert "edit_refused" in site.events.names() and "words_approved" not in site.events.names()


def test_saving_without_changing_anything_is_a_plain_approval(site):
    url = site.start()
    judged = len(site.rig.judge.calls)
    unchanged = site.post(f"{url}/words", {"action": "save", "line": typed_lines(site, url)})
    assert unchanged.status_code == 303
    song = site.song(url)
    assert song.lyrics_source == "writer" and song.status is SongStatus.AUDIO_CHECKED
    assert len(site.rig.judge.calls) == judged, "nothing changed, so nothing to judge again"


def test_an_edit_form_that_does_not_fit_the_song_is_refused(site):
    url = site.start()
    lines = typed_lines(site, url)
    assert site.post(f"{url}/words", {"action": "save", "line": lines[:-1]}).status_code == 400
    longer = {"action": "save", "line": [*lines, "more"]}
    assert site.post(f"{url}/words", longer).status_code == 400
    assert site.post(f"{url}/words", {"action": "something"}).status_code == 400
    blank = site.post(f"{url}/words", {"action": "save", "line": ["   ", *lines[1:]]})
    assert blank.status_code == 422 and "Each line needs some words" in problems(blank.text)
    assert site.song(url).status is SongStatus.LYRICS_READY


def test_a_parent_can_ask_for_different_words_twice(site):
    url = site.start()
    assert "Write different words (2 left)" in site.get(url).text
    site.post(f"{url}/words", {"action": "redraft"})
    assert "Write different words (1 left)" in site.get(url).text
    site.post(f"{url}/words", {"action": "redraft"})
    assert "Write different words" not in site.get(url).text
    refused = site.post(f"{url}/words", {"action": "redraft"})
    assert refused.status_code == 409 and "fresh drafts" in problems(refused.text)


# ---- listening ------------------------------------------------------------------------------


def test_an_adult_can_ask_for_the_music_again_once(site):
    url = site.to_listen()
    assert "No, make the music again" in site.get(url).text
    note = "too fast\r\nand <b>loud</b>" + "!" * 400
    assert site.post(f"{url}/listen", {"decision": "retry", "reason": note}).status_code == 303
    again = site.get(url)
    assert "Listen before your child does" in again.text and site.rig.music.calls == 2
    assert "No, make the music again" not in again.text

    said = [a.detail for a in site.song(url).attempts if a.step == "preview"][0]
    assert "\n" not in said and "\r" not in said and len(said) <= 300

    site.post(f"{url}/listen", {"decision": "reject"})
    page = site.get(url).text
    assert "This song did not work out" in page and "<b>" not in page
    assert site.get(f"{url}/audio").status_code == 404


def test_audio_can_be_asked_for_in_pieces_as_phones_do(site):
    url = site.to_listen()
    whole = site.get(f"{url}/audio").content
    first = site.get(f"{url}/audio", range="bytes=0-99")
    assert first.status_code == 206 and first.content == whole[:100]
    assert first.headers["content-range"] == f"bytes 0-99/{len(whole)}"
    assert first.headers["accept-ranges"] == "bytes"
    middle = site.get(f"{url}/audio", range="bytes=1000-")
    assert middle.status_code == 206 and middle.content == whole[1000:]
    last = site.get(f"{url}/audio", range="bytes=-100")
    assert last.status_code == 206 and last.content == whole[-100:]
    assert site.get(f"{url}/audio", range=f"bytes={len(whole)}-").status_code == 416
    assert site.get(f"{url}/audio", range="bytes=-0").status_code == 416
    assert site.get(f"{url}/audio", range="lines=1-2").content == whole
    assert site.get(f"{url}/audio").headers["cache-control"] == "no-store"


# ---- pauses and stalls ----------------------------------------------------------------------


def test_a_paused_song_says_so_and_can_be_tried_again(site):
    site.rig.controls.enabled = False
    url = site.start()
    page = site.get(url)
    assert "Paused for now" in page.text and "Song making is paused" in page.text
    assert 'http-equiv="refresh"' not in page.text, "a paused page does not keep asking"
    assert site.rig.paid_calls() == 0

    site.rig.controls.enabled = True
    assert site.post(f"{url}/resume").status_code == 303
    assert "Do these words sound right?" in site.get(url).text


def test_work_that_stopped_is_picked_up_when_the_page_is_opened(site, brief):
    song = site.rig.pipeline.create(brief, A)  # saved, but nothing ever worked on it
    page = site.get(f"/h/{A}/songs/{song.id}")
    assert "Do these words sound right?" in page.text


def test_work_that_keeps_stopping_is_not_restarted_forever():
    site = Site(Rig(writer=("crash",) * 20))
    url = site.start()
    for _ in range(AUTO_KICKS + 4):
        page = site.get(url)
    assert "This is taking longer than it should" in page.text
    assert 'http-equiv="refresh"' not in page.text
    assert len(site.rig.writer.calls) == 1 + AUTO_KICKS

    site.post(f"{url}/resume")  # asking again is the parent's choice, and it is allowed
    assert len(site.rig.writer.calls) == 2 + AUTO_KICKS


def test_a_song_being_worked_on_shows_a_waiting_page_that_reloads(brief):
    rig = Rig()
    app = create_app(
        pipeline=rig.pipeline,
        participants=Allowlist([A]),
        events=MemoryEvents(rig.clock),
        runner=_Busy(),
    )
    client = TestClient(app)
    song = rig.pipeline.create(brief, A)
    page = client.get(f"/h/{A}/songs/{song.id}")
    assert "Writing the words" in page.text and 'http-equiv="refresh" content="2"' in page.text

    rig.pipeline.advance(song.id)
    rig.pipeline.approve_lyrics(song.id, by="parent")
    page = client.get(f"/h/{A}/songs/{song.id}")
    assert "Making the music" in page.text and 'http-equiv="refresh" content="3"' in page.text


class _Busy:
    """A runner that is always in the middle of something."""

    def kick(self, song_id: str) -> None:
        raise AssertionError("work that is already running must not be started again")

    def is_working(self, song_id: str) -> bool:
        return True


# ---- what every page carries ----------------------------------------------------------------


def every_kind_of_page(site: Site) -> dict[str, object]:
    url = site.start()
    listen = site.to_listen(B)
    paused_site = Site()
    paused_site.rig.controls.enabled = False
    paused = paused_site.start()
    return {
        "landing": site.get("/"),
        "home": site.get(f"/h/{A}"),
        "words": site.get(url),
        "edit": site.get(f"{url}?edit=1"),
        "listen": site.get(listen),
        "audio": site.get(f"{listen}/audio"),
        "not found": site.get("/h/nope"),
        "problem": site.post(f"/h/{A}/songs", {**BRIEF, "step": ["one"]}),
        "redirect": site.post(f"{url}/words", {"action": "approve"}),
        "refused post": site.post(f"/h/{A}/songs", BRIEF, **{"sec-fetch-site": "cross-site"}),
        "paused": paused_site.get(paused),
        "health": site.get("/healthz"),
        "style": site.get("/static/app.css"),
    }


def test_every_response_carries_the_safety_headers(site):
    for name, response in every_kind_of_page(site).items():
        headers = response.headers
        assert "default-src 'none'" in headers["content-security-policy"], name
        assert "script-src" not in headers["content-security-policy"], name
        assert headers["referrer-policy"] == "no-referrer", name
        assert headers["x-content-type-options"] == "nosniff", name
        assert headers["x-frame-options"] == "DENY", name
        assert "noindex" in headers["x-robots-tag"], name
        if name != "style":
            assert headers["cache-control"] == "no-store", name


def test_no_page_has_a_script_or_loads_anything_from_another_site(site):
    pages = every_kind_of_page(site)
    for name in ("landing", "home", "words", "edit", "listen", "not found", "problem", "paused"):
        html = pages[name].text.lower()
        assert "<script" not in html, name
        assert "http://" not in html and "https://" not in html and 'src="//' not in html, name
        assert " style=" not in html and "<style" not in html, name
        assert "onclick" not in html and "javascript:" not in html, name
    css = pages["style"].text
    assert "http://" not in css and "https://" not in css and "@import" not in css


def test_whatever_is_shown_is_escaped(site):
    url = site.start()
    song = site.song(url)
    song.lyrics.sections[0].lines.append(Line(text="<script>alert(1)</script>"))
    song.brief = song.brief.model_copy(update={"nickname": '"><img src=x>'})
    site.rig.store.save(song)  # straight into the store, around every check
    for page in (site.get(url).text, site.get(f"{url}?edit=1").text):
        assert "<script>" not in page and "<img" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_the_event_log_holds_nothing_a_parent_typed(site):
    url = site.to_listen()
    site.post(f"{url}/listen", {"decision": "retry", "reason": "the singer sounded cross"})
    site.post(f"/h/{A}/songs", {**BRIEF, "step": ["sing baby shark", "teeth", "bed"]})
    written = json.dumps(site.events.items).lower()
    for typed in ("mimi", "brush teeth", "bedtime", "shark", "cross"):
        assert typed not in written
    for event in site.events.items:
        assert set(event) == {"at", "household", "song", "name", "detail"}


def test_static_files_come_from_a_fixed_list(site):
    assert site.get("/static/app.css").headers["content-type"].startswith("text/css")
    font = site.get("/static/fonts/atkinson-hyperlegible-latin-700-normal.woff2")
    assert font.status_code == 200 and font.headers["content-type"] == "font/woff2"
    for path in ("/static/app.py", "/static/..%2Fapp.py", "/static/fonts/OFL.txt", "/static/"):
        assert site.get(path).status_code == 404


def test_the_health_check_says_nothing_but_ok(site):
    assert site.get("/healthz").json() == {"status": "ok"}
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert site.get(path).status_code == 404


# ---- the parts around the pages -------------------------------------------------------------


def test_participant_codes_are_checked_and_new_ones_are_long_and_random(monkeypatch):
    with pytest.raises(ValueError):
        Allowlist(["has a space"])
    with pytest.raises(ValueError):
        Allowlist(["../../etc"])
    monkeypatch.setenv("PARTICIPANT_CODES", " one-code, two_code ,,")
    listed = Allowlist.from_env()
    assert len(listed) == 2 and listed.knows("two_code") and not listed.knows("")
    made = {new_code() for _ in range(50)}
    assert len(made) == 50 and all(len(code) == 12 for code in made)
    assert Allowlist(made).knows(next(iter(made)))


def test_the_event_file_gets_one_line_per_event(tmp_path, site):
    log = JsonlEvents(tmp_path / "deep" / "events.jsonl", site.rig.clock)
    log.record(A, "song_started", "song0001", steps=4)
    log.record(A, "limit_reached")
    first, second = (json.loads(line) for line in log.path.read_text().splitlines())
    assert first == {
        "at": "2026-11-12T09:00:00+00:00",
        "household": A,
        "song": "song0001",
        "name": "song_started",
        "detail": {"steps": 4},
    }
    assert second["song"] is None and second["detail"] == {}


def test_the_background_runner_works_on_a_song_once_at_a_time():
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    class Slow:
        def advance(self, song_id: str) -> None:
            calls.append(song_id)
            started.set()
            release.wait(timeout=5)

    runner = ThreadRunner(Slow())  # type: ignore[arg-type]
    runner.kick("song0001")
    assert started.wait(timeout=5)
    runner.kick("song0001")  # already being worked on
    assert runner.is_working("song0001") and calls == ["song0001"]
    release.set()
    for _ in range(200):
        if not runner.is_working("song0001"):
            break
        threading.Event().wait(0.01)
    assert not runner.is_working("song0001")
    runner.kick("song0001")  # and it can be started again afterwards
    for _ in range(200):
        if len(calls) == 2:
            break
        threading.Event().wait(0.01)
    assert calls == ["song0001", "song0001"]


def test_a_failure_in_the_background_does_not_take_the_runner_down():
    class Broken:
        def advance(self, song_id: str) -> None:
            raise RuntimeError("provider exploded")

    InlineRunner(Broken()).kick("song0001")  # type: ignore[arg-type]


def test_the_serve_command_builds_a_working_site(tmp_path):
    client = TestClient(build_site(tmp_path, ["local-code"]), follow_redirects=False)
    assert client.get("/healthz").status_code == 200
    assert client.get("/h/local-code").status_code == 200
    assert client.get("/h/other").status_code == 404
    started = client.post("/h/local-code/songs", content=urlencode(BRIEF, doseq=True), headers=FORM)
    assert started.status_code == 303
    for _ in range(200):  # the work runs on a background thread here
        if "Do these words sound right?" in client.get(started.headers["location"]).text:
            break
        threading.Event().wait(0.02)
    else:
        raise AssertionError("the background work never finished")
    assert list((tmp_path / "songs").glob("*.json"))
    assert "song_started" in (tmp_path / "events.jsonl").read_text()


def test_the_codes_command_prints_codes_or_links(capsys):
    assert main(["codes", "--count", "3"]) == 0
    codes = capsys.readouterr().out.split()
    assert len(set(codes)) == 3
    assert main(["codes", "--base-url", "https://example.test/"]) == 0
    assert capsys.readouterr().out.startswith("https://example.test/h/")
