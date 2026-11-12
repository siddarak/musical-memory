"""Fail if anything that looks like a secret is about to be committed.

Run it before every commit and in CI:  python scripts/check_secrets.py

It checks the files git tracks or would track. It is a seat belt, not a guarantee: it knows the
key shapes of the services this project uses, and it cannot see a secret in a shape it does not
know. The real rule is simpler. Keys live in the provider dashboards, in Railway variables and
in a local .env file that git ignores. They are never pasted into a file, a chat or an issue.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS: dict[str, re.Pattern[str]] = {
    "Anthropic API key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "ElevenLabs API key": re.compile(r"\bsk_[a-f0-9]{40,}\b"),
    "OpenAI-style API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "Supabase secret key": re.compile(r"\bsb_secret_[A-Za-z0-9_\-]{20,}"),
    "JSON web token": re.compile(
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"
    ),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"),
    "Railway or generic bearer token": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.]{30,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "database URL with a password": re.compile(r"postgres(?:ql)?://[^\s:/@]+:[^\s@]{4,}@"),
}

# In an env file, a secret-looking name must have an empty value.
_ENV_LINE = re.compile(
    r"^\s*([A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|CODES|DATABASE_URL)[A-Z0-9_]*)=(.+)$"
)
_SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "out", "build", "dist",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
}  # fmt: skip
_MAX_BYTES = 1_000_000


def files_to_check(root: Path) -> list[Path]:
    """Tracked files plus new files that are not ignored. Falls back to a walk outside git."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        return [root / name for name in listed if (root / name).is_file()]
    except (OSError, subprocess.CalledProcessError):
        return [
            path
            for path in root.rglob("*")
            if path.is_file() and not _SKIP_DIRS.intersection(path.relative_to(root).parts)
        ]


def scan_text(name: str, text: str) -> list[str]:
    problems = []
    is_env_file = Path(name).name.startswith(".env")
    for number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in PATTERNS.items():
            if pattern.search(line):
                problems.append(f"{name}:{number}: looks like a {label}")
        if is_env_file:
            match = _ENV_LINE.match(line)
            if match and match.group(2).strip():
                problems.append(f"{name}:{number}: {match.group(1)} has a value; leave it empty")
    return problems


def scan(root: Path) -> list[str]:
    problems: list[str] = []
    for path in files_to_check(root):
        if path.stat().st_size > _MAX_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary
        problems += scan_text(str(path.relative_to(root)), text)
    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    problems = scan(root)
    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} possible secret(s). Remove them, then rotate the key: once a")
        print("key has been written to a file, treat it as leaked.")
        return 1
    print("No secrets found in the files git would commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
