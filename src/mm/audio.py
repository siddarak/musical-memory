"""Checks on finished audio, plus the test tones the fake music provider returns.

Standard library only. The inspector reads 16-bit WAV, which is what the fakes produce. The real
music adapter will either ask its provider for WAV or bring its own inspector.
"""

from __future__ import annotations

import io
import math
import sys
import wave
from array import array

from mm.domain import Finding
from mm.ports import AudioFacts, UnsupportedAudio

LENGTH_TOLERANCE = 0.20  # a song may be 20% shorter or longer than asked
# Loudness limits are first guesses. Tune them against real provider audio before relying on them.
QUIETEST_DBFS = -40.0
LOUDEST_DBFS = -6.0
_SILENCE_DBFS = -120.0


def _wav(samples: array[int], rate: int) -> bytes:
    if sys.byteorder == "big":
        samples.byteswap()
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return out.getvalue()


def tone_wav(seconds: float, *, amplitude: float = 0.25, rate: int = 8000, hz: int = 400) -> bytes:
    """A plain tone. Stands in for a song when no real music provider is connected."""
    period = rate // hz
    cycle = [round(amplitude * 32767 * math.sin(2 * math.pi * i / period)) for i in range(period)]
    count = int(seconds * rate)
    return _wav(array("h", cycle * (count // period + 1))[:count], rate)


def silence_wav(seconds: float, *, rate: int = 8000) -> bytes:
    return _wav(array("h", [0]) * int(seconds * rate), rate)


class WavInspector:
    """Measures length and loudness of 16-bit WAV audio."""

    def inspect(self, audio: bytes, mime: str) -> AudioFacts:
        if mime not in ("audio/wav", "audio/x-wav"):
            raise UnsupportedAudio(f"cannot inspect {mime}")
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                if wav.getsampwidth() != 2:
                    raise UnsupportedAudio("only 16-bit WAV is supported")
                rate = wav.getframerate()
                frames = wav.getnframes()
                samples = array("h", wav.readframes(frames))
        except (wave.Error, EOFError) as err:
            raise UnsupportedAudio(f"not a readable WAV file: {err}") from err
        if sys.byteorder == "big":
            samples.byteswap()
        if not samples or not rate:
            return AudioFacts(seconds=0.0, peak=0.0, rms_dbfs=_SILENCE_DBFS)
        peak = max(abs(min(samples)), abs(max(samples))) / 32768
        mean_square = sum(sample * sample for sample in samples) / len(samples)
        rms = math.sqrt(mean_square) / 32768
        rms_dbfs = 20 * math.log10(rms) if rms > 0 else _SILENCE_DBFS
        return AudioFacts(seconds=frames / rate, peak=peak, rms_dbfs=max(rms_dbfs, _SILENCE_DBFS))


def check_audio(facts: AudioFacts, target_seconds: float) -> list[Finding]:
    """Reasons this audio should not go to an adult for preview."""
    found = []
    low = target_seconds * (1 - LENGTH_TOLERANCE)
    high = target_seconds * (1 + LENGTH_TOLERANCE)
    if not low <= facts.seconds <= high:
        found.append(
            Finding(
                "wrong_length",
                f"The audio is {facts.seconds:.0f} seconds. "
                f"It should be between {low:.0f} and {high:.0f}.",
            )
        )
    if facts.rms_dbfs < QUIETEST_DBFS:
        found.append(Finding("too_quiet", "The audio is silent or far too quiet."))
    if facts.rms_dbfs > LOUDEST_DBFS:
        found.append(Finding("too_loud", "The audio is too loud for a young child."))
    return found
