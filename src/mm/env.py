"""Read a `.env` file into the environment.

Hand-written rather than a dependency, for the reason in decision 8: fewer moving parts. It is
deliberately dull. It does not expand variables, run a shell, or follow includes, because a
`.env` file holding a key is not a place to want surprises.

Two rules it will not break:

- A name already in the environment wins. So `MM_SPEND_CAP_USD=0.50 mm check-provider` beats
  whatever the file says, and a value set for one command cannot be silently replaced.
- No value is ever returned, printed or logged. `load_env` reports the names it set and
  nothing else, so a caller cannot accidentally put a key on the screen.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PATH = Path(".env")


def parse_env(text: str) -> dict[str, str]:
    """Names and values from the text of a `.env` file. Bad lines are skipped, not guessed at."""
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, sep, value = line.partition("=")
        if not sep:
            continue
        name = name.strip()
        if not name or not name.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        found[name] = value
    return found


def load_env(path: Path | None = DEFAULT_PATH) -> list[str]:
    """Set anything in the file that is not already set. Returns the names set, never values.

    A missing file is not an error: fakes are the default, so no file means no real providers.
    """
    if path is None or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    set_now = []
    for name, value in parse_env(text).items():
        if name not in os.environ:
            os.environ[name] = value
            set_now.append(name)
    return set_now
