"""Stand-ins for the paid providers. Free, instant and predictable.

Tests and local runs use these by default, so nothing here can spend money or reach the network.
Each fake takes a `plan`: a list of behaviours to play back, one per call. When the plan runs
out, the fake behaves well.
"""

from __future__ import annotations

from collections.abc import Sequence

from mm.audio import silence_wav, tone_wav
from mm.domain import Brief, JudgeVerdict, Line, Lyrics
from mm.ports import Audio, Draft, Judgement, ProviderError, Transcript
from mm.presets import StylePreset
from mm.songwriter import write_song


class Crash(RuntimeError):
    """Stands in for the process dying in the middle of a provider call."""


def _next(plan: list[str], default: str = "ok") -> str:
    return plan.pop(0) if plan else default


class FakeWriter:
    """Writes a real song for the brief, or a broken draft when told to.

    The words come from `mm.songwriter`, which is not a model but does give a different song for
    a different routine or style. A real writer replaces this without the pipeline changing.

    Plan items: "ok", "long_line", "missing_step", "unsafe", "error", "crash".
    """

    name = "fake"
    model = "fake-writer"
    prompt_version = "fake-1"

    def __init__(self, plan: Sequence[str] = (), cost_usd: float = 0.002) -> None:
        self.plan = list(plan)
        self.cost_usd = cost_usd
        self.calls: list[tuple[Brief, tuple[str, ...]]] = []

    def write(self, brief: Brief, feedback: Sequence[str]) -> Draft:
        self.calls.append((brief, tuple(feedback)))
        behaviour = _next(self.plan)
        if behaviour == "error":
            raise ProviderError("the fake writer is down")
        if behaviour == "crash":
            raise Crash("writer")
        lyrics = write_song(brief)
        # The verse is found by name, not position: a shape may or may not open with an intro.
        verse = next(section for section in lyrics.sections if section.name == "verse")
        if behaviour == "long_line":
            verse.lines.append(
                Line(text="and this one line goes on for far too many words to sing")
            )
        elif behaviour == "missing_step":
            verse.lines.pop()
        elif behaviour == "unsafe":
            verse.lines.append(Line(text="or else the monster comes"))
        elif behaviour != "ok":
            raise ValueError(f"unknown fake writer behaviour: {behaviour}")
        return Draft(lyrics=lyrics, cost_usd=self.cost_usd)


class FakeJudge:
    """Passes everything, or fails when told to.

    Plan items: "pass", "unsafe", "unkind", "error".
    """

    name = "fake"
    model = "fake-judge"

    def __init__(self, plan: Sequence[str] = (), cost_usd: float = 0.002) -> None:
        self.plan = list(plan)
        self.cost_usd = cost_usd
        self.calls: list[Lyrics] = []

    def judge(self, brief: Brief, lyrics: Lyrics) -> Judgement:
        self.calls.append(lyrics)
        behaviour = _next(self.plan, "pass")
        if behaviour == "error":
            raise ProviderError("the fake judge is down")
        verdict = JudgeVerdict(safe=True, faithful=True, kind_tone=True, age_fit=True)
        if behaviour == "unsafe":
            verdict = verdict.model_copy(
                update={"safe": False, "issues": ["Fake judge: not safe for this age."]}
            )
        elif behaviour == "unkind":
            verdict = verdict.model_copy(
                update={"kind_tone": False, "issues": ["Fake judge: the tone is not kind."]}
            )
        elif behaviour != "pass":
            raise ValueError(f"unknown fake judge behaviour: {behaviour}")
        return Judgement(verdict=verdict, cost_usd=self.cost_usd)


class FakeMusic:
    """Returns a test tone of the right length, or bad audio when told to.

    Plan items: "ok", "silent", "short", "loud", "error", "crash".
    """

    name = "fake"
    model = "fake-music"

    def __init__(self, plan: Sequence[str] = (), price_per_minute_usd: float = 0.15) -> None:
        self.plan = list(plan)
        self.price_per_minute_usd = price_per_minute_usd
        self.calls = 0
        self.last_text = ""

    def compose(self, lyrics: Lyrics, nickname: str | None, preset: StylePreset) -> Audio:
        self.calls += 1
        behaviour = _next(self.plan)
        if behaviour == "error":
            raise ProviderError("the fake music provider is down")
        if behaviour == "crash":
            raise Crash("music")
        seconds = float(preset.seconds)
        self.last_text = lyrics.render(nickname)
        if behaviour == "silent":
            data = silence_wav(seconds)
            self.last_text = ""
        elif behaviour == "short":
            seconds = seconds * 0.3
            data = tone_wav(seconds)
        elif behaviour == "loud":
            data = tone_wav(seconds, amplitude=0.99)
        elif behaviour == "ok":
            data = tone_wav(seconds)
        else:
            raise ValueError(f"unknown fake music behaviour: {behaviour}")
        cost = round(seconds / 60 * self.price_per_minute_usd, 4)
        return Audio(data=data, mime="audio/wav", cost_usd=cost)


class FakeTranscriber:
    """Reports the words the fake music provider was last asked to sing.

    `drop_every=3` loses every third word, to imitate a singer who slurs.
    """

    name = "fake"
    model = "fake-transcriber"

    def __init__(self, music: FakeMusic, drop_every: int = 0, cost_usd: float = 0.007) -> None:
        self.music = music
        self.drop_every = drop_every
        self.cost_usd = cost_usd
        self.calls = 0

    def transcribe(self, audio: bytes, mime: str) -> Transcript:
        self.calls += 1
        words = self.music.last_text.split()
        if self.drop_every:
            words = [word for index, word in enumerate(words, 1) if index % self.drop_every]
        return Transcript(text=" ".join(words), cost_usd=self.cost_usd)
