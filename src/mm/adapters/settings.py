"""What has to be true before a single dollar can be spent.

Rule 2 of the project notes: fakes by default, and a real call needs an explicit setting and a
dollar cap. This module is where both are enforced. `from_env` returns None unless someone has
deliberately asked for real providers, so forgetting to configure anything leaves you on fakes
rather than on a paid API.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

OPT_IN = "MM_REAL_PROVIDERS"
CAP = "MM_SPEND_CAP_USD"
KEY = "ELEVENLABS_API_KEY"

# Only this exact word turns real providers on. "true", "1" and "y" are all somebody guessing,
# and guessing should not be able to spend money.
OPT_IN_WORD = "yes"

# A cap above this is almost certainly a typo (a stray zero) rather than an intention.
SANE_CAP_CEILING_USD = 50.00


class SettingsError(Exception):
    """Real providers were asked for but the settings are not safe to run with."""


@dataclass(frozen=True)
class RealProviderSettings:
    """Everything the adapters need. Built only by `from_env` or by a test."""

    api_key: str
    spend_cap_usd: float

    # music_v2_5 is newer but we have listened to v2 and its terms are the ones we read.
    music_model: str = "music_v2"

    # PCM so the bytes can be wrapped in a WAV header with the standard library, which keeps
    # WavInspector working. pcm_44100 would be better quality but needs a Pro plan; 22050 is
    # allowed on Starter. mp3 would need a decoder we do not have.
    output_format: str = "pcm_22050"
    sample_rate: int = 22050

    # Unverified against a real response. If this is wrong the song comes back the wrong
    # length, which the adapter turns into a loud error rather than a quietly bad song.
    channels: int = 2

    transcriber_model: str = "scribe_v1"
    timeout_seconds: float = 180.0

    # Published rates, Nov 2026. Music is per minute, speech to text is per hour.
    music_price_per_minute_usd: float = 0.15
    transcribe_price_per_hour_usd: float = 0.22

    def __post_init__(self) -> None:
        if not self.api_key:
            raise SettingsError(f"{KEY} is empty")
        if self.spend_cap_usd <= 0:
            raise SettingsError(f"{CAP} must be more than zero")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RealProviderSettings | None:
        """None means stay on fakes. An exception means the request was unsafe, not absent."""
        if env.get(OPT_IN) != OPT_IN_WORD:
            return None

        key = env.get(KEY, "").strip()
        if not key:
            raise SettingsError(
                f"{OPT_IN} is on but {KEY} is not set. Put it in .env, which git ignores."
            )

        raw_cap = env.get(CAP, "").strip()
        if not raw_cap:
            raise SettingsError(
                f"{OPT_IN} is on but {CAP} is not set. There is no default: name a dollar "
                "figure you are willing to lose."
            )
        try:
            cap = float(raw_cap)
        except ValueError:
            raise SettingsError(f"{CAP} is not a number") from None
        if cap <= 0:
            raise SettingsError(f"{CAP} must be more than zero")
        if cap > SANE_CAP_CEILING_USD:
            raise SettingsError(
                f"{CAP} is {cap:.2f} dollars, which is above the {SANE_CAP_CEILING_USD:.2f} "
                "ceiling in settings.py. Raise the ceiling on purpose if you mean it."
            )

        return cls(api_key=key, spend_cap_usd=cap)
