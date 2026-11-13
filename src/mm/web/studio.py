"""The team view: what the service is meant to do, and what it actually did.

Nothing here changes a song. It reads what the pipeline already wrote and arranges it, so the
team can show the design and the evidence side by side without opening a database.

The journey below is written out rather than derived from the code on purpose: it says what each
step is for and what it refuses, which the code cannot say about itself. When the pipeline
changes, change this too. A test checks that the eight steps still name real song statuses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mm.domain import CODE, Song, SongStatus
from mm.pipeline import Limits
from mm.presets import STYLE_PRESETS
from mm.safety import rules
from mm.safety.wordlists import BRANDS, UNSAFE


@dataclass(frozen=True)
class Step:
    number: int
    name: str
    who: str  # "Our code", "A model", or "A person"
    does: str
    guard: str  # what this step refuses, in plain words
    waits_at: SongStatus | None  # the status a song sits at while this step is due


JOURNEY: tuple[Step, ...] = (
    Step(
        1,
        "Screen the brief",
        "Our code",
        "Reads what the parent typed and decides whether we will write a song at all.",
        "Anything but letters, so no phone numbers, links or markup. Then word lists: unsafe "
        "words, medicine, artist and character names, asking for a copy of an existing song, "
        "text aimed at the model, and hints of personal details.",
        SongStatus.DRAFT,
    ),
    Step(
        2,
        "Write the words",
        "A model",
        "Drafts lyrics for this routine. Each line is tagged with the step it sings about.",
        "The model never chooses what happens next. Its draft goes straight to step 3.",
        SongStatus.SCREENED,
    ),
    Step(
        3,
        "Check the words",
        "Our code, then a model",
        "Counts and rules first, free and instant. Only a draft that passes them is sent to a "
        "second model, which judges whether the words are safe, faithful, kind and right for "
        "the age.",
        "60 to 110 words, 8 words a line, a chorus repeated word for word, every step sung by "
        "name and in order. Two rewrites, then words a person wrote. The judge has the last "
        "say on those too. If the judge cannot be reached, the song stops here.",
        None,
    ),
    Step(
        4,
        "The parent approves the words",
        "A person",
        "The parent reads the words and approves them, edits any line, or asks for a different "
        "draft. An edit goes through step 3 again.",
        "No music is made before this. There is no path around it and no setting that skips it.",
        SongStatus.LYRICS_READY,
    ),
    Step(
        5,
        "Make the music",
        "A model",
        "Sends the approved words and the chosen style to the music provider.",
        "The only paid step. It is written down before it is made, so a call cut short by a "
        "crash still counts against the limits and is never quietly repeated for free.",
        SongStatus.APPROVED,
    ),
    Step(
        6,
        "Check the audio",
        "Our code",
        "Measures the finished audio and writes down how much of the words can be heard.",
        "Right length, not silent, not too loud. One automatic retry; two bad results end the "
        "song.",
        SongStatus.COMPOSED,
    ),
    Step(
        7,
        "An adult listens",
        "A person",
        "An adult plays the whole song and says whether a child may hear it. They can also ask "
        "for one more version.",
        "Nothing is published before this. The page asks them to confirm they listened to the "
        "whole song.",
        SongStatus.AUDIO_CHECKED,
    ),
    Step(
        8,
        "Publish",
        "Our code",
        "The song becomes playable for this household, and who approved it is recorded.",
        "A child only ever hears a song that an adult has heard first.",
        SongStatus.PUBLISHED,
    ),
)

GUARDRAILS: tuple[tuple[str, str], ...] = (
    (
        "An adult hears every song first",
        "Two steps wait for a person, and the pipeline owns both. The web page cannot skip "
        "either one, which is checked by breaking it on purpose in the tests.",
    ),
    (
        "We keep almost nothing about a child",
        "An age range and an optional one-word name to sing. There is no field for anything "
        "else, and a brief carrying an extra field is refused.",
    ),
    (
        "No child accounts",
        "A parent holds the link. Children never sign in and never type anything.",
    ),
    (
        "Spending cannot run away",
        "A kill switch, a daily budget shared by everyone, a per-household daily cap, and a "
        "hard limit of three music calls per song.",
    ),
    (
        "Nothing reaches another company",
        "No scripts on any page and nothing loaded from another site. The font and the "
        "stylesheet are served by the app itself.",
    ),
    (
        "No artist, song or character names",
        "The music provider's terms forbid them. Styles are a short fixed list, never free "
        "text, and the word lists refuse them in what a parent types and in finished lyrics.",
    ),
    (
        "The log holds no personal detail",
        "It records which step happened and when, never what a parent typed.",
    ),
)

# Each decision, and the thing it costs us. Kept short; docs/decisions.md has the long form.
DECISIONS: tuple[tuple[str, str, str], ...] = (
    (
        "A fixed pipeline, not an agent",
        "The order of the eight steps is written in code. Models fill in words and sound and "
        "never choose what happens next.",
        "We can say exactly which checks ran on any song, and test each one.",
    ),
    (
        "Fake providers by default",
        "Tests, the command line and CI all run on stand-ins. A real paid call needs an "
        "explicit setting and a dollar cap.",
        "The checks and limits were built and tested before any key existed.",
    ),
    (
        "Two layers of checking",
        "Free, predictable rules first. The model judge only sees what passes them.",
        "Words whose safety depends on context are left to the judge, so ordinary routines "
        "are not refused.",
    ),
    (
        "If a check cannot run, stop",
        "No judge means no song. Audio we cannot read counts as bad audio. An unclear kill "
        "switch means off.",
        "The safe mistake is a song that was not made.",
    ),
    (
        "Styles are a short list",
        "Five presets, no free text.",
        "Artist names cannot reach the music provider, and results stay predictable enough "
        "to test.",
    ),
    (
        "What a parent types is tightly limited",
        "Letters, spaces, hyphens and apostrophes. Five words and 40 letters a step.",
        "Phone numbers, emails, links and markup cannot be typed at all. The cost is writing "
        "“two books” instead of “2 books”.",
    ),
    (
        "Money is recorded before it is spent",
        "A music call is saved as started, with its estimated cost, before the provider is called.",
        "If the process dies mid-call we cannot know whether we were charged, so we assume we "
        "were. It is the only choice that keeps the caps true.",
    ),
    (
        "Pages without scripts",
        "Server-rendered HTML and plain forms. A waiting page reloads itself.",
        "Nothing about a family reaches a third party, and a policy the browser enforces can "
        "prove it.",
    ),
    (
        "A participant code is the key",
        "A family gets a long random code in their link. No accounts or passwords yet.",
        "Nothing to sign up for and no email addresses to store. The cost is that the link is "
        "a password.",
    ),
)


# How the hostile prompts in evals/datasets/redteam.jsonl land today. These are written here
# rather than read at run time, because the dataset is not shipped with the package. A test
# checks them against the dataset and the real rules, so they cannot quietly drift.
REDTEAM = {"total": 37, "stopped": 29, "for_judge": 8}

# Said plainly, because a demo should not imply more than exists.
GAPS: tuple[str, ...] = (
    "The model judge is not built. Eight of the hostile prompts get past the free checks "
    "today, and the stand-in judge passes everything.",
    "No model writes the words. They come from ten hand-written song shapes with the "
    "parent's own steps fitted in, so a different routine really does give a different song, "
    "but a model would do better.",
    "There is no real music. The audio is a test tone, so nothing here says anything about "
    "how a real song would sound.",
    "Nothing is hosted. The service runs on one machine, started by hand.",
    "The word lists are English only, and short on purpose.",
    "There is no private play link for a child yet. A parent plays the song from their own page.",
    "No sign-in beyond participant codes, and no limit on how fast one visitor can send requests.",
)


def _spend(songs: list[Song]) -> float:
    return sum(song.spend_usd() for song in songs)


def numbers(songs: list[Song], limits: Limits, generation_on: bool) -> dict[str, Any]:
    """The few figures the team actually watches."""
    published = [song for song in songs if song.status is SongStatus.PUBLISHED]
    music_calls = sum(song.music_calls for song in songs)
    return {
        "songs": len(songs),
        "published": len(published),
        "refused": sum(1 for song in songs if song.status is SongStatus.REJECTED),
        "failed": sum(1 for song in songs if song.status is SongStatus.FAILED),
        "waiting_on_a_person": sum(
            1
            for song in songs
            if song.status in (SongStatus.LYRICS_READY, SongStatus.AUDIO_CHECKED)
        ),
        "households": len({song.household_id for song in songs}),
        "spend": round(_spend(songs), 2),
        "budget": limits.daily_budget_usd,
        "music_calls": music_calls,
        "calls_per_song": round(music_calls / len(published), 2) if published else None,
        "edits": sum(1 for song in songs if song.lyrics_source == "parent_edit"),
        "fell_back": sum(1 for song in songs if song.lyrics_source == "template"),
        "generation_on": generation_on,
    }


def journey_with_counts(songs: list[Song]) -> list[dict[str, Any]]:
    """The eight steps, each with how many songs are sitting there now."""
    waiting: dict[SongStatus, int] = {}
    for song in songs:
        waiting[song.status] = waiting.get(song.status, 0) + 1
    return [
        {
            "number": step.number,
            "name": step.name,
            "who": step.who,
            "does": step.does,
            "guard": step.guard,
            "is_person": step.who == "A person",
            "here": waiting.get(step.waits_at, 0) if step.waits_at else 0,
        }
        for step in JOURNEY
    ]


# What the team should read where the code says "writer", "template" or "parent_edit".
WORDS_FROM = {
    "writer": "the model",
    "template": "our fallback",
    "parent_edit": "the parent",
}


def song_row(song: Song) -> dict[str, Any]:
    from mm.web.views import STATUS_LABELS

    return {
        "id": song.id,
        "household": song.household_id,
        "routine": song.brief.routine,
        "status": song.status.value,
        "label": STATUS_LABELS[song.status],
        "at": _when(song.created_at),
        "spend": round(song.spend_usd(), 3),
        "music_calls": song.music_calls,
        "rewrites": song.rewrites,
        "source": WORDS_FROM.get(song.lyrics_source or "", ""),
        "done": song.status is SongStatus.PUBLISHED,
        "stopped": song.status in (SongStatus.REJECTED, SongStatus.FAILED),
    }


def song_detail(song: Song) -> dict[str, Any]:
    """One song's whole trail: the brief, where it got to, and every step it went through."""
    row = song_row(song)
    row.update(
        steps=[step for step in song.brief.steps],
        style=STYLE_PRESETS[song.brief.style].label,
        age_band=song.brief.age_band,
        has_nickname=song.brief.nickname is not None,
        words=song.lyrics.render(song.brief.nickname) if song.lyrics else "",
        word_count=song.lyrics.word_count() if song.lyrics else 0,
        audio_seconds=song.audio_seconds,
        transcript_match=song.transcript_match,
        words_approved_by=song.lyrics_approved_by,
        audio_approved_by=song.audio_approved_by,
        refusal=song.refusal,
        failure=song.failure,
        blocked=song.blocked,
        attempts=[
            {
                "step": attempt.step,
                "by": "our code" if attempt.provider == CODE else attempt.provider,
                "paid": attempt.provider != CODE,
                "outcome": attempt.outcome,
                "cost": round(attempt.cost_usd, 4),
                "ms": attempt.duration_ms,
                "detail": attempt.detail,
                "at": _when(attempt.started_at),
            }
            for attempt in song.attempts
        ],
    )
    return row


def _said(value: Any) -> str:
    """True and False are programmer's words. A log a person reads says yes and no."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def event_row(entry: dict[str, Any]) -> dict[str, Any]:
    detail = entry.get("detail") or {}
    return {
        "at": _when(entry.get("at")),
        "household": entry.get("household", ""),
        "song": entry.get("song") or "",
        "name": str(entry.get("name", "")).replace("_", " "),
        "detail": ", ".join(f"{key}: {_said(value)}" for key, value in sorted(detail.items())),
    }


def checks_summary() -> dict[str, Any]:
    """How much the deterministic layer actually covers, counted from the lists themselves."""
    return {
        "unsafe_words": len(UNSAFE),
        "brand_names": len(BRANDS),
        "styles": len(STYLE_PRESETS),
        "min_words": rules.MIN_WORDS,
        "max_words": rules.MAX_WORDS,
        "max_line_words": rules.MAX_LINE_WORDS,
    }


def _when(value: datetime | str | None) -> str:
    """A short, readable time. Dates are UTC, which is what the pipeline counts days in."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return value[:19]  # not a time we recognise; show it as it was written
    else:
        moment = value
    return moment.strftime("%d %b %H:%M:%S")
