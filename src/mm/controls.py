"""The kill switch: one place to stop every paid call at once."""

from __future__ import annotations

import os

_ON = frozenset({"1", "true", "on", "yes"})


class StaticControls:
    """A switch held in memory. Used by tests and local runs."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def generation_enabled(self) -> bool:
        return self.enabled


class EnvControls:
    """Reads GENERATION_ENABLED on every call, so changing it takes effect at once.

    Unset means on. Anything we do not recognise means off, so a typo stops spending
    rather than allowing it.
    """

    def __init__(self, variable: str = "GENERATION_ENABLED") -> None:
        self.variable = variable

    def generation_enabled(self) -> bool:
        value = os.environ.get(self.variable)
        if value is None:
            return True
        return value.strip().lower() in _ON
