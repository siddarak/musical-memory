"""ElevenLabs behind the MusicProvider and Transcriber shapes in ports.py.

Nothing in here decides anything about a song. It turns approved words into one HTTP request,
turns the reply into the dataclasses the pipeline already understands, and refuses to spend
past its cap. The pipeline cannot tell this apart from `mm.fakes`.

The transport is injected so a test never reaches the network. The default transport is the
only code here that opens a socket.

Verified against the published API reference, not against a live call: this adapter has never
spoken to ElevenLabs. The two things most likely to be wrong on the first real call are the
channel count of the PCM that comes back and the exact shape of the speech-to-text reply.
Both fail loudly rather than quietly, on purpose.
"""

from __future__ import annotations

import functools
import io
import json
import re
import ssl
import urllib.error
import urllib.request
import uuid
import wave
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

from mm.adapters.settings import RealProviderSettings
from mm.domain import Lyrics
from mm.ports import Audio, ProviderError, Transcript
from mm.presets import StylePreset
from mm.safety.wordlists import BRANDS

BASE = "https://api.elevenlabs.io"
MUSIC_URL = f"{BASE}/v1/music"
TRANSCRIBE_URL = f"{BASE}/v1/speech-to-text"

# How far the returned audio may be from the length we asked for before we treat it as a fault.
LENGTH_TOLERANCE_SECONDS = 5.0


@dataclass(frozen=True)
class Reply:
    """What a transport gives back. Deliberately not an HTTP library's own type."""

    status: int
    body: bytes
    content_type: str


class Transport(Protocol):
    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes) -> Reply: ...


class SpendCapReached(ProviderError):
    """The dollar cap would be exceeded. Nothing was sent."""


class SpendCap:
    """One running total, shared by every adapter that bills to the same key.

    Spend is reserved *before* a call and settled afterwards, so a call that crashes halfway
    still counts against the cap. The pipeline already does this for music calls; doing it
    here too means a crash in the HTTP layer cannot give us a free retry.
    """

    def __init__(self, cap_usd: float) -> None:
        self.cap_usd = cap_usd
        self.spent_usd = 0.0

    def reserve(self, estimate_usd: float) -> None:
        if self.spent_usd + estimate_usd > self.cap_usd:
            raise SpendCapReached(
                f"this call would take spending past the {self.cap_usd:.2f} dollar cap"
            )
        self.spent_usd = round(self.spent_usd + estimate_usd, 6)

    def settle(self, estimate_usd: float, actual_usd: float) -> None:
        self.spent_usd = round(self.spent_usd - estimate_usd + actual_usd, 6)


@functools.cache
def trust() -> ssl.SSLContext | None:
    """Where to look for the certificates that say a connection is really the provider.

    The python.org build of Python on macOS ships without its certificate store connected, so
    a plain HTTPS call fails with CERTIFICATE_VERIFY_FAILED until somebody runs a script that
    needs permissions they may not have. Rather than make every reader solve that, we look for
    a trust store ourselves, in the order that needs least of them:

    1. `truststore`, which uses the operating system's own store (Keychain on macOS). Nothing
       to install or maintain, and it follows whatever the machine already trusts.
    2. `certifi`, the bundled list most of the Python world uses.
    3. Python's default, which is what failed above but is right on a well set-up machine.

    None means "use the default". Both packages are optional: `pip install -e ".[real]"`.
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # noqa: BLE001 - any failure here just means try the next one
        pass
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return None


def default_transport(
    method: str, url: str, headers: dict[str, str], body: bytes, timeout: float = 180.0
) -> Reply:
    """The only thing here that opens a socket."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(  # noqa: S310
            request, timeout=timeout, context=trust()
        ) as response:
            return Reply(
                status=response.status,
                body=response.read(),
                content_type=response.headers.get("Content-Type", ""),
            )
    except urllib.error.HTTPError as err:
        return Reply(
            status=err.code,
            body=err.read(),
            content_type=err.headers.get("Content-Type", "") if err.headers else "",
        )


_BRAND_PATTERNS = tuple(re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE) for word in BRANDS)


def _brand_in(text: str) -> bool:
    """A last look before the wire, because the provider's terms forbid these as input.

    This is a simpler matcher than the one in mm.safety.rules, which has already screened this
    text. It exists to catch a future change that puts free text into the prompt, not to
    replace the real check. Promoting it to the real matcher means editing mm/safety/, which
    needs a person's review.
    """
    return any(pattern.search(text) for pattern in _BRAND_PATTERNS)


def redact(text: str, key: str) -> str:
    """Never let the key travel in a message, however the message was built."""
    if key and key in text:
        text = text.replace(key, "***")
    return text


def _unreachable(err: Exception, key: str, what: str) -> ProviderError:
    """Say why the call did not happen.

    The reason here comes from our own socket, not from the provider, so it is safe to show and
    is usually the whole answer: a certificate problem, no network, a timeout. An earlier
    version printed only the exception's class name, which told a reader nothing they could act
    on. The key is redacted anyway, because a message nobody checks is a message that leaks.
    """
    reason = getattr(err, "reason", None)
    detail = str(reason) if reason is not None else str(err)
    detail = redact(detail.strip(), key)[:200] or type(err).__name__
    return ProviderError(f"{what} could not be reached: {detail}")


def _fail(status: int) -> ProviderError:
    """Never include the provider's own message: it can carry the key back at us."""
    if status in (401, 403):
        return ProviderError("the music provider refused our key")
    if status == 422:
        return ProviderError("the music provider rejected the request")
    if status == 429:
        return ProviderError("the music provider is rate limiting us")
    return ProviderError(f"the music provider returned {status}")


class ElevenLabsMusic:
    """Composes one song. Fits ports.MusicProvider."""

    name = "elevenlabs"

    def __init__(
        self,
        settings: RealProviderSettings,
        *,
        transport: Transport | None = None,
        cap: SpendCap | None = None,
    ) -> None:
        self.settings = settings
        self.model = settings.music_model
        self.cap = cap or SpendCap(settings.spend_cap_usd)
        self._transport: Transport = transport or self._default

    def _default(self, method: str, url: str, headers: dict[str, str], body: bytes) -> Reply:
        return default_transport(method, url, headers, body, self.settings.timeout_seconds)

    def _prompt(self, lyrics: Lyrics, nickname: str | None, preset: StylePreset) -> str:
        """Style words from the preset, then the words a parent approved. No free text."""
        return "\n".join(
            [
                "A song for a young child.",
                "Style: " + ", ".join(preset.positive) + ".",
                "Avoid: " + ", ".join(preset.negative) + ".",
                "Sing these words exactly:",
                lyrics.render(nickname),
            ]
        )

    def compose(self, lyrics: Lyrics, nickname: str | None, preset: StylePreset) -> Audio:
        prompt = self._prompt(lyrics, nickname, preset)
        if _brand_in(prompt):
            # Say what happened without repeating the word, per the style rules.
            raise ProviderError("these words cannot be sent to the music provider")

        estimate = round(preset.seconds / 60 * self.settings.music_price_per_minute_usd, 6)
        self.cap.reserve(estimate)

        url = MUSIC_URL + "?" + urlencode({"output_format": self.settings.output_format})
        body = json.dumps(
            {
                "prompt": prompt,
                "music_length_ms": preset.seconds * 1000,
                "model_id": self.settings.music_model,
            }
        ).encode()
        headers = {
            "xi-api-key": self.settings.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/*",
        }

        try:
            reply = self._transport("POST", url, headers, body)
        except SpendCapReached:
            raise
        except Exception as err:  # the money is gone whatever went wrong
            raise _unreachable(err, self.settings.api_key, "the music provider") from None

        if reply.status != 200:
            raise _fail(reply.status)

        data = self._to_wav(reply.body)
        seconds = self._seconds(reply.body)
        if abs(seconds - preset.seconds) > LENGTH_TOLERANCE_SECONDS:
            raise ProviderError(
                f"the music provider returned {seconds:.0f} seconds of audio where "
                f"{preset.seconds} were asked for, so the length is wrong"
            )

        actual = round(seconds / 60 * self.settings.music_price_per_minute_usd, 6)
        self.cap.settle(estimate, actual)
        return Audio(data=data, mime="audio/wav", cost_usd=round(actual, 4))

    def _seconds(self, pcm: bytes) -> float:
        frame = 2 * self.settings.channels  # 16-bit samples
        if frame == 0:
            raise ProviderError("the adapter is misconfigured: zero channels")
        return len(pcm) / frame / self.settings.sample_rate

    def _to_wav(self, pcm: bytes) -> bytes:
        """Wrap raw PCM in a WAV header so the existing inspector can read it."""
        out = io.BytesIO()
        with wave.open(out, "wb") as handle:
            handle.setnchannels(self.settings.channels)
            handle.setsampwidth(2)
            handle.setframerate(self.settings.sample_rate)
            handle.writeframes(pcm)
        return out.getvalue()


class ElevenLabsTranscriber:
    """Reads back what was actually sung. Fits ports.Transcriber."""

    name = "elevenlabs"

    def __init__(
        self,
        settings: RealProviderSettings,
        *,
        transport: Transport | None = None,
        cap: SpendCap | None = None,
    ) -> None:
        self.settings = settings
        self.model = settings.transcriber_model
        self.cap = cap or SpendCap(settings.spend_cap_usd)
        self._transport: Transport = transport or self._default

    def _default(self, method: str, url: str, headers: dict[str, str], body: bytes) -> Reply:
        return default_transport(method, url, headers, body, self.settings.timeout_seconds)

    def transcribe(self, audio: bytes, mime: str) -> Transcript:
        seconds = _wav_seconds(audio)
        estimate = round(seconds / 3600 * self.settings.transcribe_price_per_hour_usd, 6)
        self.cap.reserve(estimate)

        boundary = f"----mm{uuid.uuid4().hex}"
        body = _multipart(boundary, self.settings.transcriber_model, audio, mime)
        headers = {
            "xi-api-key": self.settings.api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        }

        try:
            reply = self._transport("POST", TRANSCRIBE_URL, headers, body)
        except SpendCapReached:
            raise
        except Exception as err:
            raise _unreachable(err, self.settings.api_key, "the transcriber") from None

        if reply.status != 200:
            raise _fail(reply.status)

        try:
            parsed = json.loads(reply.body)
        except json.JSONDecodeError:
            raise ProviderError("the transcriber did not return readable JSON") from None
        if not isinstance(parsed, dict) or "text" not in parsed:
            raise ProviderError("the transcriber returned no words")
        text = parsed["text"]
        if not isinstance(text, str):
            raise ProviderError("the transcriber returned no words")

        self.cap.settle(estimate, estimate)
        return Transcript(text=text, cost_usd=round(estimate, 4))


def _wav_seconds(audio: bytes) -> float:
    try:
        with wave.open(io.BytesIO(audio), "rb") as handle:
            return handle.getnframes() / handle.getframerate()
    except (wave.Error, EOFError, ZeroDivisionError):
        raise ProviderError("the audio to transcribe is not readable WAV") from None


def _multipart(boundary: str, model: str, audio: bytes, mime: str) -> bytes:
    sep = f"--{boundary}".encode()
    return b"\r\n".join(
        [
            sep,
            b'Content-Disposition: form-data; name="model_id"',
            b"",
            model.encode(),
            sep,
            b'Content-Disposition: form-data; name="file"; filename="song.wav"',
            f"Content-Type: {mime}".encode(),
            b"",
            audio,
            f"--{boundary}--".encode(),
            b"",
        ]
    )
