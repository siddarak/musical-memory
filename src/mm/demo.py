"""Forced test cases, so the whole product can be seen without any provider keys.

Each case below is a real run through the real pipeline. Nothing is written into the store by
hand. A case that needs something to go wrong makes it go wrong the honest way, by telling a
fake provider to misbehave, so the song's record shows exactly what a bad day looks like.

What this cannot fake is the song. The audio is still a test tone until a music key is set.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from mm.audio import WavInspector
from mm.controls import StaticControls
from mm.domain import Brief, Lyrics, Song, SongStatus
from mm.fakes import FakeJudge, FakeMusic, FakeTranscriber, FakeWriter
from mm.pipeline import Limits, LyricsNotAccepted, Pipeline
from mm.ports import SongStore
from mm.safety import rules
from mm.web.events import EventLog

# Invented families. No real person's details belong in a demo.
HOUSEHOLDS = ("demo-ferrara", "demo-okonkwo", "demo-lindqvist")

# How far through a song the case should go.
STOP_AT_WORDS = "words"  # waiting for the parent to check the words
STOP_AT_LISTEN = "listen"  # waiting for an adult to listen
PUBLISH = "publish"  # all the way through
REFUSED = "refused"  # we will not make this song


@dataclass(frozen=True)
class Case:
    """One thing a reviewer should be able to see happening."""

    shows: str  # what this case is here to demonstrate
    household: str
    routine: str
    steps: tuple[str, ...]
    style: str
    age_band: Literal["3-4", "5-6"]
    ends_at: str
    nickname: str | None = None
    writer_plan: tuple[str, ...] = ()
    music_plan: tuple[str, ...] = ()
    # Lines the parent rewrites, as the form would send them. The refused one is tried first.
    refused_edit: tuple[int, str] | None = None
    edit_line: tuple[int, str] | None = None
    retry_once: bool = False  # the adult says no the first time, then approves
    minutes_ago: int = 0
    reviewer: str = "parent"


CASES: tuple[Case, ...] = (
    Case(
        shows="A finished song, start to end, with nothing going wrong.",
        household=HOUSEHOLDS[0],
        routine="bedtime",
        steps=("brush teeth", "put on pajamas", "read one book", "lights out"),
        style="gentle_lullaby",
        age_band="3-4",
        nickname="Mina",
        ends_at=PUBLISH,
        minutes_ago=180,
    ),
    Case(
        shows="A parent's first edit was refused, and their second was accepted.",
        household=HOUSEHOLDS[0],
        routine="brushing teeth",
        steps=("wet the brush", "tiny bit of toothpaste", "brush every tooth", "spit and rinse"),
        style="silly_bounce",
        age_band="5-6",
        nickname="Mina",
        ends_at=PUBLISH,
        # Line 0 is in the chorus, which is sung twice, so changing one copy is refused.
        refused_edit=(0, "Here we go, it's brushing time"),
        edit_line=(4, "First we wet the brush"),
        minutes_ago=150,
    ),
    Case(
        shows="The first music call came back silent, so it was made once more.",
        household=HOUSEHOLDS[1],
        routine="tidy-up time",
        steps=("blocks in the box", "books on the shelf", "cars in the bin"),
        style="clap_along_march",
        age_band="3-4",
        ends_at=PUBLISH,
        music_plan=("silent", "ok"),
        minutes_ago=120,
    ),
    Case(
        shows="The adult listened, said no, and asked for the music again.",
        household=HOUSEHOLDS[1],
        routine="bath time",
        steps=("climb in the tub", "wash your hair", "rinse the bubbles", "dry off"),
        style="calm_piano",
        age_band="3-4",
        nickname="Tobi",
        ends_at=PUBLISH,
        retry_once=True,
        minutes_ago=90,
    ),
    Case(
        shows="The writer kept breaking the rules, so the words a person wrote were used.",
        household=HOUSEHOLDS[2],
        routine="getting ready for school",
        steps=("make the bed", "brush your hair", "pack your bag", "shoes on"),
        style="clap_along_march",
        age_band="5-6",
        ends_at=STOP_AT_LISTEN,
        writer_plan=("long_line", "missing_step", "unsafe"),
        minutes_ago=40,
    ),
    Case(
        shows="A song waiting for an adult to listen before any child can hear it.",
        household=HOUSEHOLDS[2],
        routine="leaving the house",
        steps=("shoes on", "coat on", "hold my hand"),
        style="bouncy_ukulele",
        age_band="3-4",
        nickname="Elin",
        ends_at=STOP_AT_LISTEN,
        minutes_ago=20,
    ),
    Case(
        shows="A song waiting for the parent to check the words. No music has been made.",
        household=HOUSEHOLDS[0],
        routine="snack time",
        steps=("wash your hands", "sit at the table", "eat your apple"),
        style="bouncy_ukulele",
        age_band="3-4",
        nickname="Mina",
        ends_at=STOP_AT_WORDS,
        minutes_ago=8,
    ),
    Case(
        shows="A brief the checks refused, before anything was written or spent.",
        household=HOUSEHOLDS[1],
        routine="bedtime",
        steps=("sing baby shark", "brush teeth", "lights out"),
        style="silly_bounce",
        age_band="3-4",
        ends_at=REFUSED,
        minutes_ago=5,
    ),
)


@dataclass
class Clock:
    """A clock the seeding moves by hand, so the demo has a believable afternoon in it."""

    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __call__(self) -> datetime:
        return self.now


def _ids() -> Callable[[], str]:
    """Ids for one seeding run. The run's own token keeps a second run from overwriting it."""
    run = secrets.token_hex(3)
    count = 0

    def mint() -> str:
        nonlocal count
        count += 1
        return f"demo{run}{count:03d}"

    return mint


def _edited(lyrics: Lyrics, which: int, text: str) -> Lyrics:
    """The words with one line rewritten, the way a parent's edit arrives from the form."""
    data = lyrics.model_dump()
    flat = [line for section in data["sections"] for line in section["lines"]]
    flat[which]["text"] = text
    return Lyrics.model_validate(data)


def seed(
    store: SongStore,
    events: EventLog,
    cases: Sequence[Case] = CASES,
    limits: Limits | None = None,
    clock: Clock | None = None,
) -> list[Song]:
    """Run every case through the pipeline and return the songs, newest last.

    The daily caps are lifted for the seeding only. A demo wants eight songs on screen, and
    three of these households would otherwise hit their five-a-day limit; the running service
    still enforces whatever limits it was given.

    Pass the same `clock` to the event log, so the log and the songs agree about when things
    happened. Without it the log reads as if the whole afternoon happened in one second.
    """
    clock = clock or Clock()
    room = limits or Limits()
    seeding = Limits(
        **{
            **vars(room),
            "songs_per_household_per_day": 1000,
            "daily_budget_usd": 1000.0,
        }
    )
    mint = _ids()
    made: list[Song] = []

    for case in cases:
        clock.now = datetime.now(UTC) - timedelta(minutes=case.minutes_ago)
        music = FakeMusic(plan=case.music_plan)
        pipeline = Pipeline(
            store=store,
            writer=FakeWriter(plan=case.writer_plan),
            judge=FakeJudge(),
            music=music,
            transcriber=FakeTranscriber(music),
            inspector=WavInspector(),
            controls=StaticControls(),
            limits=seeding,
            clock=clock,
            new_id=mint,
        )
        made.append(_run(pipeline, events, case))
    return made


def _run(pipeline: Pipeline, events: EventLog, case: Case) -> Song:
    brief = Brief(
        routine=case.routine,
        steps=case.steps,
        style=case.style,
        age_band=case.age_band,
        nickname=case.nickname,
    )
    song = pipeline.create(brief, case.household)
    events.record(case.household, "song_started", song.id, style=case.style, steps=len(case.steps))
    song = pipeline.advance(song.id)

    if song.status is SongStatus.REJECTED:
        codes = sorted({finding.code for finding in rules.screen_brief(brief)})
        events.record(case.household, "brief_refused", song.id, codes=codes)
        return song
    if case.ends_at == STOP_AT_WORDS:
        events.record(case.household, "words_shown", song.id)
        return song

    events.record(case.household, "words_shown", song.id)
    if case.refused_edit and song.lyrics:
        try:
            pipeline.approve_lyrics(
                song.id, by=case.reviewer, edited=_edited(song.lyrics, *case.refused_edit)
            )
        except LyricsNotAccepted as refusal:
            codes = sorted({finding.code for finding in refusal.findings})
            events.record(case.household, "edit_refused", song.id, codes=codes)
        else:
            raise AssertionError(f"{case.shows}: this edit was meant to be refused")
        song = pipeline.store.get(song.id)

    edited = None
    if case.edit_line and song.lyrics:
        edited = _edited(song.lyrics, *case.edit_line)
    song = pipeline.approve_lyrics(song.id, by=case.reviewer, edited=edited)
    events.record(case.household, "words_approved", song.id, edited=edited is not None)
    song = pipeline.advance(song.id)

    if song.status is not SongStatus.AUDIO_CHECKED:
        return song
    events.record(case.household, "audio_shown", song.id)

    if case.retry_once:
        song = pipeline.adult_reject(
            song.id, by=case.reviewer, reason="the singing was too fast", try_again=True
        )
        events.record(case.household, "listen_rejected", song.id, try_again=True)
        song = pipeline.advance(song.id)
        if song.status is not SongStatus.AUDIO_CHECKED:
            return song
        events.record(case.household, "audio_shown", song.id)

    if case.ends_at != PUBLISH:
        return song
    song = pipeline.adult_approve(song.id, by=case.reviewer)
    events.record(case.household, "listen_approved", song.id)
    return song
