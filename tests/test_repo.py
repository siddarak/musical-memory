"""Checks on the repository itself: no secrets, and the safety settings are still in place."""

import json
from pathlib import Path

import pytest

import check_secrets
import mm

ROOT = Path(__file__).resolve().parents[1]


def test_the_package_has_a_version():
    assert mm.__version__


def test_nothing_that_looks_like_a_secret_is_in_the_repo():
    assert check_secrets.scan(ROOT) == []


@pytest.mark.parametrize(
    "line",
    [
        # Built at run time so that this file never contains something shaped like a key.
        "ANTHROPIC_API_KEY=" + "sk-" + "ant-" + "a1B2" * 8,
        "xi-api-key: " + "sk" + "_" + "0a1b2c3d4e" * 5,
        "token = " + "gh" + "p_" + "A1b2" * 10,
        "DATABASE_URL=postgres" + "ql://app:" + "hunter2222" + "@db.example.com:5432/app",
        "-----BEGIN RSA " + "PRIVATE KEY-----",
        "Authorization: Bearer " + "eyJ" + "hbGciOiJIUzI1NiJ9" + "." + "a" * 20 + "." + "b" * 20,
    ],
)
def test_the_scanner_spots_the_key_shapes_this_project_uses(line):
    assert check_secrets.scan_text("notes.txt", line)


def test_the_scanner_wants_empty_values_in_env_files():
    assert check_secrets.scan_text(".env.example", "ELEVENLABS_API_KEY=") == []
    assert check_secrets.scan_text(".env.example", "DAILY_BUDGET_USD=5") == []
    assert check_secrets.scan_text(".env.example", "ELEVENLABS_API_KEY=something")


def test_ordinary_text_is_not_flagged():
    text = "Set ELEVENLABS_API_KEY in Railway. The task list is at docs/spec.md."
    assert check_secrets.scan_text("README.md", text) == []


def test_env_files_are_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert ".env" in ignored


def test_the_agent_settings_still_protect_secrets_and_ask_before_risky_changes():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    rules = settings["permissions"]
    assert "Read(/.env)" in rules["deny"]
    assert "Bash(git push --force *)" in rules["deny"]
    assert "Bash(git push *)" in rules["ask"]
    assert "Edit(/src/mm/safety/**)" in rules["ask"]
    assert not any(rule in ("Bash", "Bash(*)") for rule in rules["allow"])
