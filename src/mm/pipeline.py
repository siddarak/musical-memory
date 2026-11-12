"""The song pipeline: a fixed series of checked steps.

This is a workflow, not a free-running agent. The order of the steps is written here in code.
The models only fill in words and sound, and nothing they return can skip a step. Two steps wait
for a person: a parent approves the words, and an adult listens before any child can.

Every step saves its result, so a crash or a restart picks up where it stopped. A call to the
music provider is recorded on the song before it is made, so a call that was cut short still
counts against the limits and is never silently repeated for free.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol, TypeVar

from mm.audio import check_audio
from mm.domain import (
    CODE,
    Attempt,
    Brief,
    Finding,
    JudgeVerdict,
    Lyrics,
    Outcome,
    Song,
    SongStatus,
    StepName,
)
from mm.ports import (
    AudioFacts,
    AudioInspector,
    Controls,
    LyricsJudge,
    LyricsWriter,
    MusicProvider,
    ProviderError,
    SongStore,
    Transcriber,
    UnsupportedAudio,
)
from mm.presets import STYLE_PRESETS
from mm.safety import rules
from mm.templates import fallback_lyrics
from mm.text import match_ratio

_HOUSEHOLD = re.compile(r"^[A-Za-z0-9_-]{3,40}$")
_MAX_MOVES = 40  # far more than any song needs; reaching it means a bug, not a long song

PAUSED = "Song making is paused right now. Nothing was lost. Please try again later."
OVER_BUDGET = "Today's budget for making songs is used up. Please try again tomorrow."
CANNOT_CHECK = "We could not check the words, so we stopped. No music was made."
NO_SAFE_SONG = (
    "We could not turn this routine into a song that passed our safety check. "
    "Try describing the steps another way."
)
MUSIC_FAILED = "The music did not come out right, and this song has no tries left."
REVIEWER_SAID_NO = "The adult who listened did not approve this song."


@dataclass(frozen=True)
class Limits:
    """Every cap in one place. Change a number here, not in the steps below."""

    max_rewrites: int = 2  # rewrites of one draft before the fallback words are used
    max_fresh_drafts: int = 2  # times a parent may ask for different words
    max_edit_checks: int = 5  # times a parent's own edits are checked
    max_music_calls_per_round: int = 2  # the first try plus one automatic retry
    max_regenerations: int = 1  # times an adult may ask for another try after listening
    max_music_calls_per_song: int = 3
    songs_per_household_per_day: int = 5
    daily_budget_usd: float = 5.00
    music_price_per_minute_usd: float = 0.15
    llm_call_estimate_usd: float = 0.01
    transcript_estimate_usd: float = 0.01


class PipelineError(Exception):
    """The caller asked for something that cannot be done. The message is safe to show a parent."""


class WrongState(PipelineError):
    """The song is not at the step this action belongs to."""


class LimitReached(PipelineError):
    """A cap was hit. Nothing was spent."""


class Blocked(PipelineError):
    """Paused or over budget. Trying again later may work."""


class LyricsNotAccepted(PipelineError):
    """A parent's edit did not pass the same checks the writer's draft has to pass."""

    def __init__(self, findings: list[Finding]) -> None:
        super().__init__(" ".join(finding.message for finding in findings))
        self.findings = findings


class _Provider(Protocol):
    name: str
    model: str


class _Priced(Protocol):
    @property
    def cost_usd(self) -> float: ...


R = TypeVar("R", bound=_Priced)


def day_start(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def _codes(findings: list[Finding]) -> str:
    return ", ".join(f"{f.code}:{f.detail}" if f.detail else f.code for f in findings)


class Pipeline:
    def __init__(
        self,
        *,
        store: SongStore,
        writer: LyricsWriter,
        judge: LyricsJudge,
        music: MusicProvider,
        transcriber: Transcriber,
        inspector: AudioInspector,
        controls: Controls,
        limits: Limits | None = None,
        clock: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self.store = store
        self.writer = writer
        self.judge = judge
        self.music = music
        self.transcriber = transcriber
        self.inspector = inspector
        self.controls = controls  # the kill switch; the team view reads it to show the state
        self.limits = limits or Limits()
        self._now = clock or (lambda: datetime.now(UTC))
        self._new_id = new_id or (lambda: uuid.uuid4().hex)
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    # ---- what callers use -------------------------------------------------------------------

    def create(self, brief: Brief, household_id: str) -> Song:
        """Save a new song request. Nothing is checked or spent yet."""
        if not _HOUSEHOLD.match(household_id):
            raise ValueError("household code is not valid")
        with self._guard:
            now = self._now()
            used = self.store.songs_counted_since(household_id, day_start(now))
            if used >= self.limits.songs_per_household_per_day:
                raise LimitReached(
                    "This household has made all of today's songs. Please try again tomorrow."
                )
            song = Song(
                id=self._new_id(),
                household_id=household_id,
                brief=brief,
                created_at=now,
                updated_at=now,
            )
            self.store.save(song)
        return song

    def songs_left_today(self, household_id: str) -> int:
        used = self.store.songs_counted_since(household_id, day_start(self._now()))
        return max(0, self.limits.songs_per_household_per_day - used)

    def advance(self, song_id: str) -> Song:
        """Run every step that can run without a person, then stop and report.

        Safe to call again at any time: it starts from what was last saved and does nothing
        when the song is waiting for a person or is finished.
        """
        with self._lock(song_id):
            song = self.store.get(song_id)
            song.blocked = None
            self._close_interrupted(song)
            for _ in range(_MAX_MOVES):
                step = _STEPS.get(song.status)
                if step is None:
                    break
                moved = step(self, song)
                self._save(song)
                if not moved:
                    break
            else:
                raise RuntimeError(f"song {song.id} did not settle; this is a bug")
            self._save(song)
            return song

    def approve_lyrics(self, song_id: str, *, by: str, edited: Lyrics | None = None) -> Song:
        """A parent approves the words, with or without their own edits.

        Edited words go through the same rules and the same judge as a draft from the writer.
        """
        with self._lock(song_id):
            song = self._load(song_id, SongStatus.LYRICS_READY)
            if not by:
                raise ValueError("an approval has to say who gave it")
            if edited is not None:
                self._check_edit(song, edited)
                song.lyrics = edited
                song.lyrics_source = "parent_edit"
            song.lyrics_approved_by = by
            song.round_music_calls = 0
            song.status = SongStatus.APPROVED
            self._save(song)
            return song

    def redraft(self, song_id: str) -> Song:
        """A parent asks for different words. Call advance() afterwards to write them."""
        with self._lock(song_id):
            song = self._load(song_id, SongStatus.LYRICS_READY)
            if song.fresh_drafts >= self.limits.max_fresh_drafts:
                raise LimitReached(
                    "This song has had all its fresh drafts. You can still edit the words yourself."
                )
            song.fresh_drafts += 1
            song.rewrites = 0
            song.feedback = []
            song.lyrics = None
            song.lyrics_source = None
            song.status = SongStatus.SCREENED
            self._save(song)
            return song

    def adult_approve(self, song_id: str, *, by: str) -> Song:
        """An adult has listened to the whole song and says a child may hear it."""
        with self._lock(song_id):
            song = self._load(song_id, SongStatus.AUDIO_CHECKED)
            if not by:
                raise ValueError("an approval has to say who gave it")
            self._note(song, "preview", "ok", f"approved by {by}")
            song.audio_approved_by = by
            song.published_at = self._now()
            song.status = SongStatus.PUBLISHED
            self._save(song)
            return song

    def adult_reject(
        self, song_id: str, *, by: str, reason: str = "", try_again: bool = False
    ) -> Song:
        """An adult has listened and says no. With try_again, one more version may be made."""
        with self._lock(song_id):
            song = self._load(song_id, SongStatus.AUDIO_CHECKED)
            self._note(song, "preview", "rejected", f"{by}: {reason}")
            song.audio_path = None
            song.audio_mime = None
            song.audio_seconds = None
            song.transcript_match = None
            tries_left = (
                song.regenerations < self.limits.max_regenerations
                and song.music_calls < self.limits.max_music_calls_per_song
            )
            if try_again and tries_left:
                song.regenerations += 1
                song.round_music_calls = 0
                song.status = SongStatus.APPROVED
            else:
                self._fail(song, REVIEWER_SAID_NO)
            self._save(song)
            return song

    # ---- the steps --------------------------------------------------------------------------

    def _screen(self, song: Song) -> bool:
        findings = rules.screen_brief(song.brief)
        self._note(song, "screen", "rejected" if findings else "ok", _codes(findings))
        if findings:
            song.status = SongStatus.REJECTED
            song.refusal = [finding.message for finding in findings]
        else:
            song.status = SongStatus.SCREENED
        return True

    def _write(self, song: Song) -> bool:
        if song.rewrites > self.limits.max_rewrites:
            return self._fall_back(song)
        # The writer and the judge are paid for together, so a draft is never bought and then
        # left unchecked because the budget ran out in between.
        if not self._may_spend(song, 2 * self.limits.llm_call_estimate_usd):
            return False
        draft = self._call(
            song,
            "write",
            self.writer,
            lambda: self.writer.write(song.brief, tuple(song.feedback)),
            self.limits.llm_call_estimate_usd,
        )
        if draft is None:
            song.rewrites += 1
            return True
        song.prompt_version = self.writer.prompt_version
        findings = rules.check_lyrics(draft.lyrics, song.brief)
        self._note(song, "rules", "rejected" if findings else "ok", _codes(findings))
        if findings:
            song.rewrites += 1
            song.feedback = [finding.message for finding in findings]
            return True
        verdict = self._ask_judge(song, draft.lyrics)
        if verdict is None:
            return self._fail(song, CANNOT_CHECK)
        if not verdict.passed:
            song.rewrites += 1
            song.feedback = verdict.issues or ["The judge did not accept the draft."]
            return True
        self._lyrics_ready(song, draft.lyrics, "writer")
        return True

    def _fall_back(self, song: Song) -> bool:
        """Use the words a person wrote. The judge still has the last say."""
        if not self._may_spend(song, self.limits.llm_call_estimate_usd):
            return False
        lyrics = fallback_lyrics(song.brief)
        findings = rules.check_lyrics(lyrics, song.brief)
        self._note(song, "rules", "rejected" if findings else "ok", "fallback " + _codes(findings))
        if findings:
            return self._fail(song, "Our fallback words did not pass our own rules. This is a bug.")
        verdict = self._ask_judge(song, lyrics)
        if verdict is None:
            return self._fail(song, CANNOT_CHECK)
        if not verdict.passed:
            song.status = SongStatus.REJECTED
            song.refusal = [NO_SAFE_SONG]
            return True
        self._lyrics_ready(song, lyrics, "template")
        return True

    def _compose(self, song: Song) -> bool:
        limits = self.limits
        out_of_tries = (
            song.round_music_calls >= limits.max_music_calls_per_round
            or song.music_calls >= limits.max_music_calls_per_song
        )
        if out_of_tries:
            return self._fail(song, MUSIC_FAILED)
        preset = STYLE_PRESETS[song.brief.style]
        estimate = round(preset.seconds / 60 * limits.music_price_per_minute_usd, 4)
        if not self._may_spend(song, estimate):
            return False
        lyrics = self._words(song)
        song.music_calls += 1
        song.round_music_calls += 1
        audio = self._call(
            song,
            "compose",
            self.music,
            lambda: self.music.compose(lyrics, song.brief.nickname, preset),
            estimate,
            save_first=True,
        )
        if audio is None:
            return True  # comes straight back here, which tries once more or gives up
        song.audio_path = self.store.put_audio(song.id, audio.data, audio.mime)
        song.audio_mime = audio.mime
        song.status = SongStatus.COMPOSED
        return True

    def _check_audio(self, song: Song) -> bool:
        if song.audio_path is None or song.audio_mime is None:
            raise RuntimeError(f"song {song.id} is composed but has no audio; this is a bug")
        preset = STYLE_PRESETS[song.brief.style]
        data = self.store.get_audio(song.audio_path)
        facts: AudioFacts | None = None
        try:
            facts = self.inspector.inspect(data, song.audio_mime)
            findings = check_audio(facts, preset.seconds)
        except UnsupportedAudio as err:
            findings = [Finding("unreadable_audio", str(err))]
        self._note(song, "audio_check", "rejected" if findings else "ok", _codes(findings))
        if findings or facts is None:
            song.audio_path = None
            song.audio_mime = None
            song.status = SongStatus.APPROVED  # back to compose, which enforces the limits
            return True
        song.audio_seconds = round(facts.seconds, 2)
        self._measure_transcript(song, data, song.audio_mime)
        song.status = SongStatus.AUDIO_CHECKED
        return True

    def _measure_transcript(self, song: Song, data: bytes, mime: str) -> None:
        """Record how many of the words can be heard. A measurement for us, not a gate."""
        if self._why_not_spend(self.limits.transcript_estimate_usd):
            self._note(song, "transcribe", "skipped", "paused or over budget")
            return
        heard = self._call(
            song,
            "transcribe",
            self.transcriber,
            lambda: self.transcriber.transcribe(data, mime),
            self.limits.transcript_estimate_usd,
        )
        if heard is not None:
            sung = self._words(song).render(song.brief.nickname)
            song.transcript_match = round(match_ratio(sung, heard.text), 3)

    # ---- helpers ----------------------------------------------------------------------------

    def _check_edit(self, song: Song, edited: Lyrics) -> None:
        if song.edit_checks >= self.limits.max_edit_checks:
            raise LimitReached("These words have been edited too many times. Start a new song.")
        reason = self._why_not_spend(self.limits.llm_call_estimate_usd)
        if reason:
            raise Blocked(reason)
        song.edit_checks += 1
        findings = rules.check_lyrics(edited, song.brief)
        self._note(song, "rules", "rejected" if findings else "ok", "edit " + _codes(findings))
        if not findings:
            verdict = self._ask_judge(song, edited)
            if verdict is None:
                self._save(song)
                raise Blocked("We could not check your changes just now. Please try again.")
            if not verdict.passed:
                issues = verdict.issues or ["These words did not pass our safety check."]
                findings = [Finding("judge", issue) for issue in issues]
        if findings:
            self._save(song)  # keeps the count and the log; the words stay as they were
            raise LyricsNotAccepted(findings)

    def _ask_judge(self, song: Song, lyrics: Lyrics) -> JudgeVerdict | None:
        """Ask the judge, once more if the first call fails. None means it could not be reached."""
        for _ in range(2):
            result = self._call(
                song,
                "judge",
                self.judge,
                lambda: self.judge.judge(song.brief, lyrics),
                self.limits.llm_call_estimate_usd,
            )
            if result is not None:
                verdict = result.verdict
                said = "passed" if verdict.passed else "failed: " + "; ".join(verdict.issues)
                song.attempts[-1].detail = said[:300]
                return verdict
        return None

    def _call(
        self,
        song: Song,
        step: StepName,
        provider: _Provider,
        run: Callable[[], R],
        estimate: float,
        *,
        save_first: bool = False,
    ) -> R | None:
        """Make one provider call and record it. None means the provider reported an error."""
        attempt = self._note(
            song, step, "started", provider=provider.name, model=provider.model, cost=estimate
        )
        if save_first:
            self._save(song)
        began = time.monotonic()
        try:
            result = run()
        except ProviderError as err:
            attempt.outcome = "error"
            attempt.cost_usd = err.cost_usd
            attempt.detail = str(err)[:300]
            return None
        finally:
            attempt.duration_ms = int((time.monotonic() - began) * 1000)
        attempt.outcome = "ok"
        attempt.cost_usd = result.cost_usd
        return result

    def _note(
        self,
        song: Song,
        step: StepName,
        outcome: Outcome,
        detail: str = "",
        *,
        provider: str = CODE,
        model: str = "",
        cost: float = 0.0,
    ) -> Attempt:
        attempt = Attempt(
            step=step,
            provider=provider,
            model=model,
            started_at=self._now(),
            cost_usd=cost,
            outcome=outcome,
            detail=detail[:300],
        )
        song.attempts.append(attempt)
        return attempt

    def _why_not_spend(self, estimate: float) -> str | None:
        """The reason a paid call may not be made right now, or None when it may."""
        if not self.controls.generation_enabled():
            return PAUSED
        spent = self.store.spend_since(day_start(self._now()))
        if spent + estimate > self.limits.daily_budget_usd:
            return OVER_BUDGET
        return None

    def _may_spend(self, song: Song, estimate: float) -> bool:
        song.blocked = self._why_not_spend(estimate)
        return song.blocked is None

    def _close_interrupted(self, song: Song) -> None:
        """A call still marked as started was cut short. Keep its estimated cost on the books."""
        for attempt in song.attempts:
            if attempt.outcome == "started":
                attempt.outcome = "interrupted"
                attempt.detail = "cut short; counted as spent"

    def _lyrics_ready(
        self, song: Song, lyrics: Lyrics, source: Literal["writer", "template"]
    ) -> None:
        song.lyrics = lyrics
        song.lyrics_source = source
        song.feedback = []
        song.status = SongStatus.LYRICS_READY

    def _words(self, song: Song) -> Lyrics:
        if song.lyrics is None:
            raise RuntimeError(f"song {song.id} has no words at {song.status.value}; this is a bug")
        return song.lyrics

    def _fail(self, song: Song, reason: str) -> bool:
        song.status = SongStatus.FAILED
        song.failure = reason
        return True

    def _load(self, song_id: str, expected: SongStatus) -> Song:
        song = self.store.get(song_id)
        if song.status is not expected:
            raise WrongState(
                f"This song is at '{song.status.value}'. "
                f"It has to be at '{expected.value}' for that."
            )
        return song

    def _save(self, song: Song) -> None:
        song.updated_at = self._now()
        self.store.save(song)

    def _lock(self, song_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(song_id, threading.Lock())


# Which step runs at each status. A status that is not listed here either waits for a person
# (lyrics_ready, audio_checked) or is finished (published, rejected, failed).
_STEPS: dict[SongStatus, Callable[[Pipeline, Song], bool]] = {
    SongStatus.DRAFT: Pipeline._screen,
    SongStatus.SCREENED: Pipeline._write,
    SongStatus.APPROVED: Pipeline._compose,
    SongStatus.COMPOSED: Pipeline._check_audio,
}
