"""Who may use the prototype.

During the study a family gets a link that contains a participant code. The code is the only
key to that family's songs, so it has to be long and random, and it must never be logged
anywhere a third party could read it.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Iterable
from typing import Protocol

_CODE = re.compile(r"^[A-Za-z0-9_-]{3,40}$")


class Participants(Protocol):
    def knows(self, code: str) -> bool: ...


class Allowlist:
    """A fixed set of participant codes."""

    def __init__(self, codes: Iterable[str]) -> None:
        self._codes = frozenset(codes)
        for code in self._codes:
            if not _CODE.match(code):
                raise ValueError("a participant code may only use letters, digits, - and _")

    @classmethod
    def from_env(cls, variable: str = "PARTICIPANT_CODES") -> Allowlist:
        raw = os.environ.get(variable, "")
        return cls(code.strip() for code in raw.split(",") if code.strip())

    def knows(self, code: str) -> bool:
        return code in self._codes

    def __len__(self) -> int:
        return len(self._codes)


def new_code() -> str:
    """A fresh participant code: 12 random characters, safe to put in a link."""
    return secrets.token_urlsafe(9)
