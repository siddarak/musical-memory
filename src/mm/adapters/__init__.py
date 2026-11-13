"""Real providers, chosen only when someone has explicitly asked for them.

`build_providers` is the one door between the fakes and a paid API. Everything that runs by
default (the tests, `mm serve`, `mm demo`, `mm eval`, CI) calls it with an environment that has
no opt-in, and gets fakes. That is the point: there is no code path where forgetting a setting
spends money.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from mm.adapters.elevenlabs import (
    ElevenLabsMusic,
    ElevenLabsTranscriber,
    SpendCap,
    SpendCapReached,
)
from mm.adapters.settings import RealProviderSettings, SettingsError
from mm.fakes import FakeMusic, FakeTranscriber
from mm.ports import MusicProvider, Transcriber

__all__ = [
    "ElevenLabsMusic",
    "ElevenLabsTranscriber",
    "RealProviderSettings",
    "SettingsError",
    "SpendCap",
    "SpendCapReached",
    "build_providers",
]


def build_providers(
    env: Mapping[str, str] | None = None,
) -> tuple[MusicProvider, Transcriber]:
    """Fakes unless the environment explicitly and safely asks for real providers.

    Raises SettingsError when real providers were asked for but the settings are unsafe, so a
    half-configured run stops instead of quietly falling back and looking like it worked.
    """
    settings = RealProviderSettings.from_env(os.environ if env is None else env)
    if settings is None:
        music = FakeMusic(plan=("ok",) * 50)
        return music, FakeTranscriber(music)

    cap = SpendCap(settings.spend_cap_usd)
    return (
        ElevenLabsMusic(settings, cap=cap),
        ElevenLabsTranscriber(settings, cap=cap),
    )
