"""A log of what a family did, for the study.

It records the household code, the song, the name of the event and a small detail, with a time.
It never records an IP address, a browser name or anything a parent typed.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EventLog(Protocol):
    def record(self, household: str, name: str, song: str | None = None, **detail: Any) -> None: ...


def _entry(
    clock: Callable[[], datetime],
    household: str,
    name: str,
    song: str | None,
    detail: dict[str, Any],
) -> dict[str, Any]:
    return {
        "at": clock().isoformat(),
        "household": household,
        "song": song,
        "name": name,
        "detail": detail,
    }


class MemoryEvents:
    def __init__(self, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock
        self.items: list[dict[str, Any]] = []

    def record(self, household: str, name: str, song: str | None = None, **detail: Any) -> None:
        self.items.append(_entry(self._clock, household, name, song, detail))

    def names(self) -> list[str]:
        return [item["name"] for item in self.items]


class JsonlEvents:
    """One JSON object per line, appended to a file."""

    def __init__(self, path: Path | str, clock: Callable[[], datetime] = _utc_now) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()

    def record(self, household: str, name: str, song: str | None = None, **detail: Any) -> None:
        line = json.dumps(_entry(self._clock, household, name, song, detail))
        with self._lock, self.path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
