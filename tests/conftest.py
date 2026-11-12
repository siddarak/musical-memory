"""Shared test setup: a sample brief, sample lyrics, and a rig that wires the pipeline to fakes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mm.audio import WavInspector
from mm.controls import StaticControls
from mm.domain import Brief, Line, Lyrics, Section
from mm.fakes import FakeJudge, FakeMusic, FakeTranscriber, FakeWriter
from mm.pipeline import Limits, Pipeline
from mm.store import InMemoryStore


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 12, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def forward(self, **amount: float) -> None:
        self.now += timedelta(**amount)


class Rig:
    """A pipeline on fake providers, with every part reachable so a test can inspect it."""

    def __init__(
        self,
        *,
        writer: tuple[str, ...] = (),
        judge: tuple[str, ...] = (),
        music: tuple[str, ...] = (),
        limits: Limits | None = None,
        store: InMemoryStore | None = None,
        clock: Clock | None = None,
        drop_every: int = 0,
    ) -> None:
        self.clock = clock or Clock()
        self.store = store or InMemoryStore()
        self.writer = FakeWriter(plan=writer)
        self.judge = FakeJudge(plan=judge)
        self.music = FakeMusic(plan=music)
        self.transcriber = FakeTranscriber(self.music, drop_every=drop_every)
        self.controls = StaticControls()
        self._count = 0
        self.pipeline = Pipeline(
            store=self.store,
            writer=self.writer,
            judge=self.judge,
            music=self.music,
            transcriber=self.transcriber,
            inspector=WavInspector(),
            controls=self.controls,
            limits=limits,
            clock=self.clock,
            new_id=self._next_id,
        )

    def _next_id(self) -> str:
        self._count += 1
        return f"song{self._count:04d}"

    def paid_calls(self) -> int:
        return (
            len(self.writer.calls)
            + len(self.judge.calls)
            + self.music.calls
            + self.transcriber.calls
        )


@pytest.fixture
def brief() -> Brief:
    return Brief(
        routine="bedtime",
        steps=["brush teeth", "put on pajamas", "read one book", "lights out"],
        style="gentle_lullaby",
        age_band="3-4",
        nickname="Mimi",
    )


def _section(name: str, *lines: tuple[str, int | None]) -> Section:
    return Section(name=name, lines=[Line(text=text, step=step) for text, step in lines])


@pytest.fixture
def good_lyrics() -> Lyrics:
    """Hand-written lyrics for the sample brief that pass every rule."""
    chorus = (("Sleepy steps, one two three", None), ("Sleepy steps for you and me", None))
    return Lyrics(
        title="Sleepy steps",
        sections=[
            _section(
                "intro",
                ("The moon is up, the day is done", None),
                ("Come on, {name}, it's bedtime fun", None),
            ),
            _section(
                "verse",
                ("Brush your teeth, up and down", 0),
                ("Brush them clean, round and round", 0),
                ("Pajamas on, so soft and warm", 1),
                ("Put them on, all cozy and warm", 1),
            ),
            _section("chorus", *chorus),
            _section(
                "verse",
                ("Read one book, just you and me", 2),
                ("Turn the page and what do we see", 2),
                ("Lights out now, the stars are bright", 3),
                ("Close your eyes and say goodnight", 3),
            ),
            _section("chorus", *chorus),
            _section("outro", ("Goodnight, {name}, sleep tight", None)),
        ],
    )


@pytest.fixture
def rig() -> Rig:
    return Rig()
