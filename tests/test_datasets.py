"""The eval datasets are part of the safety case, so their shape is tested too."""

import json
from collections import Counter
from pathlib import Path

import pytest

from mm.cli import GOLDEN, REDTEAM, main
from mm.safety import rules
from mm.templates import fallback_lyrics

ROOT = Path(__file__).resolve().parents[1]


def _rows(path: Path) -> list[dict]:
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


GOLDEN_ROWS = _rows(GOLDEN)
REDTEAM_ROWS = _rows(REDTEAM)


def test_there_are_thirty_golden_briefs_five_for_each_of_six_routines():
    ids = [row["id"] for row in GOLDEN_ROWS]
    assert len(ids) == len(set(ids)) == 30
    assert Counter(row_id.rsplit("-", 1)[0] for row_id in ids) == {
        "bedtime": 5,
        "morning": 5,
        "teeth": 5,
        "tidy": 5,
        "bath": 5,
        "leaving": 5,
    }


@pytest.mark.parametrize("row", GOLDEN_ROWS, ids=lambda row: row["id"])
def test_no_golden_brief_is_wrongly_refused(row):
    brief, findings = rules.screen_raw(row["brief"])
    assert brief is not None and findings == [], findings


@pytest.mark.parametrize("row", GOLDEN_ROWS, ids=lambda row: row["id"])
def test_the_fallback_song_works_for_every_golden_brief(row):
    brief, _ = rules.screen_raw(row["brief"])
    assert rules.check_lyrics(fallback_lyrics(brief), brief) == []


def test_the_red_team_set_is_big_enough_and_well_formed():
    ids = [row["id"] for row in REDTEAM_ROWS]
    assert len(ids) == len(set(ids)) >= 20
    for row in REDTEAM_ROWS:
        assert set(row) == {"id", "category", "layer", "why", "brief"}
        assert row["layer"] in {"rules", "judge"}
        assert row["why"]


@pytest.mark.parametrize(
    "row", [row for row in REDTEAM_ROWS if row["layer"] == "rules"], ids=lambda row: row["id"]
)
def test_every_hostile_prompt_meant_for_the_rules_is_stopped_by_them(row):
    _, findings = rules.screen_raw(row["brief"])
    assert findings, f"{row['id']} got through: {row['why']}"


@pytest.mark.parametrize(
    "row", [row for row in REDTEAM_ROWS if row["layer"] == "judge"], ids=lambda row: row["id"]
)
def test_prompts_left_for_the_judge_really_do_get_past_the_rules(row):
    # If one of these starts failing, the rules now catch it: move the row to "rules".
    brief, findings = rules.screen_raw(row["brief"])
    assert brief is not None and findings == []


def test_the_red_team_command_passes_and_says_what_is_not_covered(capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    assert main(["redteam"]) == 0
    printed = capsys.readouterr().out
    assert "GOT THROUGH" not in printed
    assert "NOT covered" in printed


def test_the_red_team_command_fails_when_a_prompt_gets_through(tmp_path, capsys):
    leak = {
        "id": "leak-01",
        "category": "test",
        "layer": "rules",
        "why": "an ordinary brief wrongly marked as hostile",
        "brief": GOLDEN_ROWS[0]["brief"],
    }
    path = tmp_path / "leak.jsonl"
    path.write_text(json.dumps(leak) + "\n", encoding="utf-8")
    assert main(["redteam", "--data", str(path)]) == 1
    assert "GOT THROUGH: leak-01" in capsys.readouterr().out


def test_the_eval_command_finishes_every_golden_brief_on_fakes(capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    assert main(["eval"]) == 0
    printed = capsys.readouterr().out
    assert "reached a finished song: 30 of 30" in printed
    assert "music calls per finished song: 1.00" in printed


def test_the_eval_command_fails_when_the_budget_runs_out(capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    assert main(["eval", "--budget", "1"]) == 1
    assert "DID NOT FINISH" in capsys.readouterr().out


def test_the_example_brief_in_the_readme_is_valid(capsys, monkeypatch):
    monkeypatch.chdir(ROOT)
    assert main(["screen", "examples/bedtime.json"]) == 0
