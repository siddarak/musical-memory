"""The team view: it shows what happened, and it can never change it."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from conftest import Rig
from mm.cli import REDTEAM as REDTEAM_FILE
from mm.domain import SongStatus
from mm.safety import rules
from mm.web import create_app, studio
from mm.web.access import Allowlist
from mm.web.events import MemoryEvents
from mm.web.runner import InlineRunner
from test_web import BRIEF, FORM, A, B, Site

TEAM = "team-code"
ROOT = Path(__file__).resolve().parents[1]


class TeamSite(Site):
    """A site with the team view switched on, plus helpers for its pages."""

    def __init__(self, rig: Rig | None = None, team_codes: tuple[str, ...] = (TEAM,)) -> None:
        super().__init__(rig)
        self.events = MemoryEvents(self.rig.clock)
        self.app = create_app(
            pipeline=self.rig.pipeline,
            participants=Allowlist([A, B]),
            events=self.events,
            runner=InlineRunner(self.rig.pipeline),
            team=Allowlist(team_codes),
        )
        self.client = TestClient(self.app, follow_redirects=False)

    def live(self):
        return self.get(f"/studio/{TEAM}")

    def journey(self):
        return self.get(f"/studio/{TEAM}/journey")


@pytest.fixture
def team() -> TeamSite:
    return TeamSite()


# ---- the live page --------------------------------------------------------------------------


def test_the_log_is_written_in_words_a_person_reads(team):
    url = team.start()
    team.post(f"{url}/words", {"action": "approve"})
    rows = [studio.event_row(entry) for entry in team.events.recent(20)]
    approved = next(row for row in rows if row["name"] == "words approved")
    assert approved["detail"] == "edited: no"
    assert "False" not in team.live().text


def test_the_songs_table_says_where_the_words_came_from(team):
    url = team.start()
    assert "the model" in team.live().text
    team.rig.pipeline.redraft(url.rsplit("/", 1)[1])
    assert studio.WORDS_FROM["template"] == "our fallback"
    assert studio.WORDS_FROM["parent_edit"] == "the parent"


def test_the_live_page_shows_a_song_as_it_moves(team, brief):
    empty = team.live()
    assert empty.status_code == 200
    assert "No songs yet" in empty.text

    url = team.start()
    waiting = team.live()
    assert "Waiting for you to check the words" in waiting.text
    assert "bedtime" in waiting.text
    assert "1 here" in waiting.text, "the song is sitting at the parent's approval step"

    team.post(f"{url}/words", {"action": "approve"})
    team.post(f"{url}/listen", {"decision": "approve", "listened": "yes"})
    done = team.live()
    assert "Ready to play" in done.text
    assert "$0.161" in done.text, "what the song cost, to three decimals"


def test_the_live_page_counts_what_the_team_watches(team):
    for _ in range(2):
        url = team.start()
        team.post(f"{url}/words", {"action": "approve"})
        team.post(f"{url}/listen", {"decision": "approve", "listened": "yes"})
    team.post(f"/h/{A}/songs", {**BRIEF, "step": ["sing baby shark", "teeth", "bed"]})
    team.start(B)

    songs = team.rig.store.recent_songs(100)
    counted = studio.numbers(songs, team.rig.pipeline.limits, True)
    assert counted["songs"] == 3  # the refused brief never became a song
    assert counted["published"] == 2
    assert counted["waiting_on_a_person"] == 1
    assert counted["households"] == 2
    assert counted["calls_per_song"] == 1.0
    assert counted["music_calls"] == 2
    # Two finished songs at 16.1 cents each, plus two cheap calls on the one still waiting.
    assert counted["spend"] == 0.33


def test_the_live_page_shows_the_kill_switch(team):
    assert "Song making is paused" not in team.live().text
    team.rig.controls.enabled = False
    assert "Song making is paused" in team.live().text


def test_the_live_page_shows_every_households_songs_and_the_event_log(team):
    team.get(team.start(A))  # opening the song's page is itself an event
    team.start(B)
    page = team.live().text
    assert page.count("bedtime") >= 2
    assert A in page and B in page
    assert "song started" in page and "words shown" in page


def test_the_live_page_refreshes_itself(team):
    assert 'http-equiv="refresh"' in team.live().text


# ---- one song's trail -----------------------------------------------------------------------


def test_a_songs_page_shows_every_step_it_took(team):
    url = team.start()
    team.post(f"{url}/words", {"action": "approve"})
    team.post(f"{url}/listen", {"decision": "approve", "listened": "yes"})
    song_id = url.rsplit("/", 1)[1]

    page = team.get(f"/studio/{TEAM}/songs/{song_id}")
    assert page.status_code == 200
    for step in ("screen", "write", "rules", "judge", "compose", "audio_check", "preview"):
        assert f"<td>{step}</td>" in page.text
    assert page.text.count('class="pill pay"') == 4, "writer, judge, music and transcript"
    for step in team.rig.store.get(song_id).brief.steps:
        assert step.capitalize() in page.text or step in page.text, "the words it ended up with"
    assert "brush teeth" in page.text and "put on pajamas" in page.text, "the brief's steps"
    assert "100% of the lyrics" in page.text
    assert "parent" in page.text, "who approved it"


def test_the_team_sees_which_word_was_refused_though_the_parent_never_does(team):
    """The parent gets a reason with the words left out (tested in test_web). The team needs
    the word itself: without it they cannot tell a good refusal from a false alarm."""
    steps = ("sing baby shark", "brush teeth", "lights out")
    brief = team.rig.store.get(team.start().rsplit("/", 1)[1]).brief
    refused = team.rig.pipeline.create(brief.model_copy(update={"steps": steps}), A)
    team.rig.pipeline.advance(refused.id)

    page = team.get(f"/studio/{TEAM}/songs/{refused.id}").text
    assert "brand_name:baby shark" in page, "the team can see exactly what matched"

    for_the_parent = team.get(f"/h/{A}/songs/{refused.id}").text
    assert "shark" not in for_the_parent
    assert "artists, songs, shows or characters" in for_the_parent


def test_a_songs_page_shows_why_a_brief_was_refused(team):
    steps = ["sing baby shark", "brush teeth", "lights out"]
    brief = team.rig.store.get(team.start().rsplit("/", 1)[1]).brief
    refused = team.rig.pipeline.create(brief.model_copy(update={"steps": tuple(steps)}), A)
    team.rig.pipeline.advance(refused.id)
    page = team.get(f"/studio/{TEAM}/songs/{refused.id}")
    assert page.status_code == 200
    assert "We refused this brief" in page.text
    assert "artists, songs, shows or characters" in page.text
    assert "screen" in page.text, "and the step that refused it"


def test_a_songs_page_never_serves_the_audio(team):
    url = team.to_listen()
    song_id = url.rsplit("/", 1)[1]
    page = team.get(f"/studio/{TEAM}/songs/{song_id}")
    assert "<audio" not in page.text
    assert "/audio" not in page.text


# ---- what the team view cannot do -------------------------------------------------------------


def test_the_team_view_is_read_only(team):
    url = team.to_listen()
    song_id = url.rsplit("/", 1)[1]
    before = team.rig.store.get(song_id)
    for path in (
        f"/studio/{TEAM}",
        f"/studio/{TEAM}/journey",
        f"/studio/{TEAM}/songs/{song_id}",
    ):
        assert team.client.post(path, content="x=1", headers=FORM).status_code in (404, 405)
    assert team.rig.store.get(song_id) == before


def test_a_parent_code_does_not_open_the_team_view(team):
    song_id = team.start().rsplit("/", 1)[1]
    for code in (A, B, "nope"):
        assert team.get(f"/studio/{code}").status_code == 404
        assert team.get(f"/studio/{code}/journey").status_code == 404
        assert team.get(f"/studio/{code}/songs/{song_id}").status_code == 404
    assert team.live().status_code == 200
    assert team.get(f"/studio/{TEAM}/songs/{song_id}").status_code == 200


def test_a_team_code_does_not_open_a_households_pages(team, brief):
    url = team.to_listen()
    song_id = url.rsplit("/", 1)[1]
    assert team.get(f"/h/{TEAM}").status_code == 404
    assert team.get(f"/h/{TEAM}/songs/{song_id}").status_code == 404
    assert team.get(f"/h/{TEAM}/songs/{song_id}/audio").status_code == 404

    # Not even for a song filed under the team's own code: the team view is never a household.
    theirs = team.rig.pipeline.create(brief, TEAM)
    team.rig.pipeline.advance(theirs.id)
    assert team.get(f"/h/{TEAM}/songs/{theirs.id}").status_code == 404
    assert team.post(f"/h/{TEAM}/songs/{theirs.id}/words", {"action": "approve"}).status_code == 404
    assert team.rig.store.get(theirs.id).status is SongStatus.LYRICS_READY


def test_without_team_codes_there_is_no_team_view():
    plain = Site()  # built the way the parent-only tests build it: no team codes at all
    for path in (f"/studio/{TEAM}", "/studio/anything", f"/studio/{A}"):
        assert plain.get(path).status_code == 404


def test_the_team_view_carries_the_same_safety_headers(team):
    for response in (team.live(), team.journey()):
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cache-control"] == "no-store"
        assert "<script" not in response.text.lower()


def test_a_missing_song_is_simply_not_found(team):
    assert team.get(f"/studio/{TEAM}/songs/song9999").status_code == 404
    assert team.get(f"/studio/{TEAM}/songs/..%2F..%2Fetc").status_code == 404


# ---- the design page ---------------------------------------------------------------------------


def test_the_journey_page_names_all_eight_steps_and_marks_the_two_people_do(team):
    page = team.journey().text
    for step in studio.JOURNEY:
        assert step.name in page
    assert page.count('class="person"') == 2
    assert "The parent approves the words" in page and "An adult listens" in page


def test_the_journey_page_states_the_caps_and_the_worst_case(team):
    page = team.journey().text
    assert "Songs per household per day" in page and ">5<" in page
    assert "$5.00" in page  # the daily budget
    assert "$0.45" in page  # three music calls at 15 cents


def test_the_journey_page_says_what_is_not_built(team):
    page = team.journey().text
    assert "Not built yet" in page
    assert "model judge is not built" in page
    assert "audio is a test tone" in page


def test_the_journey_page_shows_the_decisions_and_the_guardrails(team):
    page = team.journey().text
    assert "A fixed pipeline, not an agent" in page
    assert "An adult hears every song first" in page
    assert "Money is recorded before it is spent" in page


# ---- the figures on those pages are true --------------------------------------------------------


def test_the_written_journey_is_eight_steps_numbered_one_to_eight():
    assert [step.number for step in studio.JOURNEY] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert len({step.name for step in studio.JOURNEY}) == 8
    assert all(
        step.who in ("Our code", "A model", "Our code, then a model", "A person")
        for step in studio.JOURNEY
    )


def test_every_step_of_the_written_journey_names_a_real_song_status():
    waits = [step.waits_at for step in studio.JOURNEY if step.waits_at]
    assert len(studio.JOURNEY) == 8
    assert len(set(waits)) == len(waits), "no two steps claim the same status"
    for status in SongStatus:
        if status in (SongStatus.REJECTED, SongStatus.FAILED):
            continue
        assert status in waits, f"no step of the journey covers {status.value}"


def test_the_people_steps_are_the_ones_the_pipeline_waits_at():
    from mm.domain import WAITING_FOR_A_PERSON

    written = {step.waits_at for step in studio.JOURNEY if step.who == "A person"}
    assert written == WAITING_FOR_A_PERSON


def test_the_hostile_prompt_figures_match_the_dataset_and_the_real_rules():
    lines = (ROOT / REDTEAM_FILE).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    stopped = sum(1 for row in rows if rules.screen_raw(row["brief"])[1])
    for_judge = sum(1 for row in rows if row["layer"] == "judge")
    assert {
        "total": len(rows),
        "stopped": stopped,
        "for_judge": for_judge,
    } == studio.REDTEAM


def test_the_counts_of_the_checks_come_from_the_lists_themselves():
    from mm.presets import STYLE_PRESETS
    from mm.safety.wordlists import UNSAFE

    summary = studio.checks_summary()
    assert summary["unsafe_words"] == len(UNSAFE)
    assert summary["styles"] == len(STYLE_PRESETS)
    assert summary["max_line_words"] == rules.MAX_LINE_WORDS


def test_times_are_shown_short_and_odd_ones_are_not_guessed_at():
    assert studio._when(None) == ""
    assert studio._when("2026-11-12T09:00:00+00:00") == "12 Nov 09:00:00"
    assert studio._when("not a time at all") == "not a time at all"


# ---- the command line -----------------------------------------------------------------------


def test_the_serve_command_builds_a_site_with_both_doors(tmp_path):
    from mm.cli import build_site

    client = TestClient(build_site(tmp_path, ["fam"], ["crew"]), follow_redirects=False)
    assert client.get("/h/fam").status_code == 200
    assert client.get("/studio/crew").status_code == 200
    assert client.get("/studio/fam").status_code == 404
    assert client.get("/h/crew").status_code == 404
    started = client.post("/h/fam/songs", content=urlencode(BRIEF, doseq=True), headers=FORM)
    assert started.status_code == 303


def test_a_site_built_without_team_codes_has_no_team_view(tmp_path):
    from mm.cli import build_site

    client = TestClient(build_site(tmp_path, ["fam"]))
    assert client.get("/studio/fam").status_code == 404
