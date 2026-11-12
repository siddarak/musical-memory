"""The edges of the pipeline: everything it needs from the outside world.

The pipeline only knows these shapes. Real providers (ElevenLabs, Claude, Postgres) and the
fakes used in tests both fit them, so swapping one for another never touches pipeline code.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from mm.domain import Brief, JudgeVerdict, Lyrics, Song
from mm.presets import StylePreset


class ProviderError(Exception):
    """A provider call failed in a way the pipeline can recover from."""

    def __init__(self, message: str, *, cost_usd: float = 0.0) -> None:
        super().__init__(message)
        self.cost_usd = cost_usd


class UnsupportedAudio(Exception):
    """The audio is in a format the inspector cannot read."""


@dataclass(frozen=True)
class Draft:
    lyrics: Lyrics
    cost_usd: float


@dataclass(frozen=True)
class Judgement:
    verdict: JudgeVerdict
    cost_usd: float


@dataclass(frozen=True)
class Audio:
    data: bytes
    mime: str
    cost_usd: float


@dataclass(frozen=True)
class Transcript:
    text: str
    cost_usd: float


@dataclass(frozen=True)
class AudioFacts:
    seconds: float
    peak: float  # 0 to 1
    rms_dbfs: float  # average loudness; 0 is the loudest possible, more negative is quieter


class LyricsWriter(Protocol):
    name: str
    model: str
    prompt_version: str

    def write(self, brief: Brief, feedback: Sequence[str]) -> Draft: ...


class LyricsJudge(Protocol):
    name: str
    model: str

    def judge(self, brief: Brief, lyrics: Lyrics) -> Judgement: ...


class MusicProvider(Protocol):
    name: str
    model: str

    def compose(self, lyrics: Lyrics, nickname: str | None, preset: StylePreset) -> Audio: ...


class Transcriber(Protocol):
    name: str
    model: str

    def transcribe(self, audio: bytes, mime: str) -> Transcript: ...


class AudioInspector(Protocol):
    def inspect(self, audio: bytes, mime: str) -> AudioFacts: ...


class SongStore(Protocol):
    def save(self, song: Song) -> None: ...

    def get(self, song_id: str) -> Song: ...

    def songs_for_household(self, household_id: str) -> list[Song]: ...

    def recent_songs(self, limit: int = 50) -> list[Song]: ...

    def songs_counted_since(self, household_id: str, start: datetime) -> int: ...

    def spend_since(self, start: datetime) -> float: ...

    def put_audio(self, song_id: str, data: bytes, mime: str) -> str: ...

    def get_audio(self, path: str) -> bytes: ...


class Controls(Protocol):
    def generation_enabled(self) -> bool: ...
