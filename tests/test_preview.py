"""The browser copy in docs/ must say the same things the service does.

GitHub Pages serves static files only, so docs/ reimplements the service's rules in JavaScript
for people who cannot run Python. That copy is worth nothing if it drifts, so the lists and the
figures it ships are checked against the real ones here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mm.presets import STYLE_PRESETS
from mm.safety import rules, wordlists
from mm.web import studio

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs"
PAGE = SITE / "index.html"


@pytest.fixture(scope="module")
def embedded() -> dict:
    block = re.search(
        r'<script type="application/json" id="mm-data">(.*?)</script>', PAGE.read_text(), re.S
    )
    assert block, "the page must carry its data in one json block"
    return json.loads(block.group(1))


def test_the_site_has_everything_it_needs_to_be_served_on_its_own():
    for name in ("index.html", "app.js", "app.css", "preview.css", "icon.svg"):
        assert (SITE / name).is_file(), name
    for weight in ("400", "700"):
        assert (SITE / f"fonts/atkinson-hyperlegible-latin-{weight}-normal.woff2").is_file()
    assert (SITE / "fonts/OFL.txt").is_file(), "the font's licence travels with it"


def test_the_word_lists_are_the_services_own(embedded):
    assert embedded["unsafe"] == list(wordlists.UNSAFE)
    assert embedded["medicine"] == list(wordlists.MEDICINE)
    assert embedded["brands"] == list(wordlists.BRANDS)
    assert embedded["imitation"] == list(wordlists.IMITATION)
    assert embedded["injection"] == list(wordlists.INJECTION)
    assert embedded["contact"] == list(wordlists.CONTACT)


def test_the_styles_are_the_services_own(embedded):
    assert embedded["styles"] == {key: preset.label for key, preset in STYLE_PRESETS.items()}


def test_the_journey_and_the_decisions_are_the_services_own(embedded):
    assert [step["name"] for step in embedded["journey"]] == [s.name for s in studio.JOURNEY]
    assert [step["guard"] for step in embedded["journey"]] == [s.guard for s in studio.JOURNEY]
    assert [step["who"] for step in embedded["journey"]] == [s.who for s in studio.JOURNEY]
    assert [tuple(row) for row in embedded["guardrails"]] == list(studio.GUARDRAILS)
    assert [tuple(row) for row in embedded["decisions"]] == list(studio.DECISIONS)
    assert embedded["gaps"] == list(studio.GAPS)


def test_the_figures_it_quotes_are_the_services_own(embedded):
    assert embedded["redteam"] == studio.REDTEAM
    assert embedded["checks"] == studio.checks_summary()


def test_the_limits_it_shows_are_the_services_own():
    from mm.pipeline import Limits

    script = (SITE / "app.js").read_text()
    shown = re.search(r"const LIMITS = \{(.*?)\n\};", script, re.S)
    assert shown
    written = dict(re.findall(r"(\w+): ([\d.]+),", shown.group(1)))
    limits = Limits()
    assert int(written["maxRewrites"]) == limits.max_rewrites
    assert int(written["maxFreshDrafts"]) == limits.max_fresh_drafts
    assert int(written["maxMusicCallsPerSong"]) == limits.max_music_calls_per_song
    assert int(written["maxRegenerations"]) == limits.max_regenerations
    assert int(written["songsPerHouseholdPerDay"]) == limits.songs_per_household_per_day
    assert float(written["dailyBudgetUsd"]) == limits.daily_budget_usd
    assert float(written["musicPricePerMinuteUsd"]) == limits.music_price_per_minute_usd


def test_the_lyric_rules_it_shows_are_the_services_own():
    script = (SITE / "app.js").read_text()
    assert "DATA.checks.min_words" in script, "the word counts are read, not retyped"
    assert "DATA.checks.max_line_words" in script
    assert rules.MIN_WORDS == 60 and rules.MAX_LINE_WORDS == 8  # what the page will show


def test_the_stylesheet_is_the_services_own_with_only_the_font_path_changed():
    served = (ROOT / "src/mm/web/static/app.css").read_text()
    assert (SITE / "app.css").read_text() == served.replace("/static/fonts/", "fonts/")


def test_the_font_files_are_the_services_own():
    for name in (
        "atkinson-hyperlegible-latin-400-normal.woff2",
        "atkinson-hyperlegible-latin-700-normal.woff2",
    ):
        assert (SITE / "fonts" / name).read_bytes() == (
            ROOT / "src/mm/web/static/fonts" / name
        ).read_bytes()


def test_the_page_loads_nothing_from_another_site():
    """The service's rule 9 is 'nothing from another site'. The copy keeps that half of it."""
    for name in ("index.html", "app.js", "app.css", "preview.css"):
        text = (SITE / name).read_text()
        for url in re.findall(r"https?://[^\s\"')]+", text):
            assert url.startswith("https://github.com/siddarak/musical-memory"), f"{name}: {url}"
        assert "//cdn" not in text and "fonts.googleapis" not in text


def test_the_page_says_plainly_what_it_is_and_what_it_cannot_do():
    text = " ".join(PAGE.read_text().split())  # the page wraps; the sentences are what matter
    assert "browser copy" in text
    assert "Nothing you type leaves this page" in text
    assert "template rather than a model" in text
    assert "test tone" in text
    assert "Waiting times are shortened" in text


def test_the_page_never_claims_a_child_may_hear_an_unapproved_song():
    script = (SITE / "app.js").read_text()
    # Publishing is reachable from one place only, and it is gated on the adult's confirmation.
    assert script.count('song.status = "published"') == 2, "the journey, and the seeded cases"
    assert "function approveAudio(song, listened)" in script
    assert "if (!listened)" in script


def test_the_seeded_cases_use_invented_families():
    script = (SITE / "app.js").read_text()
    block = re.search(r"const SEED = \[(.*?)\n\];", script, re.S)
    assert block, "the seeded cases live in one list"
    seeded = re.findall(r'household: "([^"]+)"', block.group(1))
    assert len(seeded) >= 8 and all(name.startswith("demo-") for name in seeded)


def test_a_brief_the_service_refuses_is_in_the_page_as_a_seeded_case():
    """The page should show a refusal on arrival, so nobody has to take the checks on trust."""
    script = (SITE / "app.js").read_text()
    assert '"sing baby shark"' in script
    brief_steps = ("sing baby shark", "brush teeth", "lights out")
    from mm.domain import Brief

    refused = rules.screen_brief(
        Brief(routine="bedtime", steps=brief_steps, style="silly_bounce", age_band="3-4")
    )
    assert [finding.code for finding in refused] == ["brand_name"]
