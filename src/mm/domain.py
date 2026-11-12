"""The shapes of the data that moves through the song pipeline."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mm.presets import STYLE_PRESETS
from mm.text import NAME_FALLBACK, NAME_SLOT, count_words

MIN_STEPS = 3
MAX_STEPS = 5
MAX_PHRASE_WORDS = 5
MAX_PHRASE_CHARS = 40
MAX_NICKNAME_CHARS = 20

_LETTERS = "A-Za-zÀ-ÖØ-öø-ÿ"
_PHRASE = re.compile(rf"^[{_LETTERS}]+(?:[ '\-][{_LETTERS}]+)*$")
_NICKNAME = re.compile(rf"^[{_LETTERS}]+(?:['\-][{_LETTERS}]+)?$")

LETTERS_ONLY = "Use letters only, with spaces, hyphens or apostrophes. Write numbers as words."


class SongStatus(StrEnum):
    DRAFT = "draft"  # brief saved, nothing checked yet
    SCREENED = "screened"  # brief passed the screen; words are being written
    LYRICS_READY = "lyrics_ready"  # words passed every check; waiting for the parent
    APPROVED = "approved"  # the parent approved the words; music may be made
    COMPOSED = "composed"  # audio exists but has not been checked
    AUDIO_CHECKED = "audio_checked"  # audio passed the checks; waiting for an adult to listen
    PUBLISHED = "published"  # an adult listened and approved; a child may hear it
    REJECTED = "rejected"  # we refused to make this song
    FAILED = "failed"  # we tried and could not finish


WAITING_FOR_A_PERSON = frozenset({SongStatus.LYRICS_READY, SongStatus.AUDIO_CHECKED})
FINISHED = frozenset({SongStatus.PUBLISHED, SongStatus.REJECTED, SongStatus.FAILED})


@dataclass(frozen=True)
class Finding:
    """One reason a check did not pass."""

    code: str  # stable name for logs and tests, such as "brand_name"
    message: str  # plain words that are safe to show a parent
    detail: str = ""  # what matched or where; for logs, never shown to a parent


def _clean(value: object) -> object:
    if not isinstance(value, str):
        return value
    value = unicodedata.normalize("NFKC", value).replace("’", "'")
    return " ".join(value.split())


def _phrase(value: str, what: str) -> str:
    if not value:
        raise ValueError(f"{what} is empty.")
    if len(value) > MAX_PHRASE_CHARS:
        raise ValueError(f"Keep {what.lower()} under {MAX_PHRASE_CHARS} letters.")
    if not _PHRASE.match(value):
        raise ValueError(LETTERS_ONLY)
    if len(value.split()) > MAX_PHRASE_WORDS:
        raise ValueError(f"Keep {what.lower()} to {MAX_PHRASE_WORDS} words or fewer.")
    return value


class Brief(BaseModel):
    """What a parent gives us. This is all we ever store about a child."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    routine: str
    steps: tuple[str, ...]
    style: str
    age_band: Literal["3-4", "5-6"]
    nickname: str | None = None

    @field_validator("routine", "style", "nickname", mode="before")
    @classmethod
    def _tidy(cls, value: object) -> object:
        return _clean(value)

    @field_validator("steps", mode="before")
    @classmethod
    def _tidy_steps(cls, value: object) -> object:
        if isinstance(value, (list, tuple)):
            return tuple(_clean(item) for item in value)
        return value

    @field_validator("routine")
    @classmethod
    def _check_routine(cls, value: str) -> str:
        return _phrase(value, "The routine name")

    @field_validator("steps")
    @classmethod
    def _check_steps(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not MIN_STEPS <= len(value) <= MAX_STEPS:
            raise ValueError(f"Give {MIN_STEPS} to {MAX_STEPS} steps.")
        for step in value:
            _phrase(step, "Each step")
        if len({step.lower() for step in value}) != len(value):
            raise ValueError("Each step should be different.")
        return value

    @field_validator("style")
    @classmethod
    def _check_style(cls, value: str) -> str:
        if value not in STYLE_PRESETS:
            raise ValueError("Pick one of the listed styles.")
        return value

    @field_validator("nickname")
    @classmethod
    def _check_nickname(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if len(value) > MAX_NICKNAME_CHARS or not _NICKNAME.match(value):
            raise ValueError("Use one short nickname or first name, letters only.")
        return value


class Line(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=100)
    step: int | None = Field(default=None, ge=0, lt=MAX_STEPS)  # which step this line sings about


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["intro", "verse", "chorus", "outro"]
    lines: list[Line] = Field(min_length=1, max_length=8)


class Lyrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=60)
    sections: list[Section] = Field(min_length=1, max_length=8)

    def lines(self) -> list[Line]:
        return [line for section in self.sections for line in section.lines]

    def word_count(self) -> int:
        return sum(count_words(line.text) for line in self.lines())

    def render(self, nickname: str | None = None) -> str:
        """The words as they will be sung, with the name filled in."""
        name = nickname or NAME_FALLBACK
        blocks = []
        for section in self.sections:
            sung = [line.text.replace(NAME_SLOT, name) for line in section.lines]
            blocks.append("\n".join(text[:1].upper() + text[1:] for text in sung))
        return "\n\n".join(blocks)


class JudgeVerdict(BaseModel):
    """What the model judge said about one set of lyrics."""

    model_config = ConfigDict(extra="forbid")

    safe: bool
    faithful: bool
    kind_tone: bool
    age_fit: bool
    issues: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.safe and self.faithful and self.kind_tone and self.age_fit


# Steps that run in our own code and cost nothing carry the provider name "code".
CODE = "code"

StepName = Literal[
    "screen", "write", "rules", "judge", "compose", "audio_check", "transcribe", "preview"
]
Outcome = Literal["started", "ok", "rejected", "error", "interrupted", "skipped"]


class Attempt(BaseModel):
    """One thing the pipeline did for a song. The list of these is the song's audit trail."""

    model_config = ConfigDict(extra="forbid")

    step: StepName
    provider: str = CODE
    model: str = ""
    started_at: datetime
    duration_ms: int = 0
    cost_usd: float = 0.0
    outcome: Outcome
    detail: str = ""


class Song(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    household_id: str
    brief: Brief
    status: SongStatus = SongStatus.DRAFT
    created_at: datetime
    updated_at: datetime

    lyrics: Lyrics | None = None
    lyrics_source: Literal["writer", "template", "parent_edit"] | None = None
    prompt_version: str | None = None
    feedback: list[str] = Field(default_factory=list)  # what the next rewrite has to fix
    rewrites: int = 0  # rewrites used on the current draft
    fresh_drafts: int = 0  # times the parent asked for different words
    edit_checks: int = 0  # times the parent's own edits were checked
    lyrics_approved_by: str | None = None

    music_calls: int = 0  # every call to the music provider, including ones cut short
    round_music_calls: int = 0  # calls since the words were approved or a retry was asked for
    regenerations: int = 0  # times an adult asked for another try after listening
    audio_path: str | None = None
    audio_mime: str | None = None
    audio_seconds: float | None = None
    transcript_match: float | None = None
    audio_approved_by: str | None = None
    published_at: datetime | None = None

    refusal: list[str] = Field(default_factory=list)  # why we said no, in plain words
    failure: str | None = None  # why we could not finish
    blocked: str | None = None  # a temporary stop (paused or over budget); cleared on the next run
    attempts: list[Attempt] = Field(default_factory=list)

    def used_a_provider(self) -> bool:
        return any(attempt.provider != CODE for attempt in self.attempts)

    def counts_toward_daily_cap(self) -> bool:
        """A brief we refused before spending anything does not use up a family's daily songs."""
        return not (self.status is SongStatus.REJECTED and not self.used_a_provider())

    def spend_usd(self) -> float:
        return sum(attempt.cost_usd for attempt in self.attempts)
