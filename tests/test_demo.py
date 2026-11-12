"""The forced test cases: each one really happened, and none of them got a free pass."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from mm.cli import build_site, main
from mm.demo import (
    CASES,
    PUBLISH,
    REFUSED,
    STOP_AT_LISTEN,
    STOP_AT_WORDS,
    Case,
    Clock,
    seed,
)
from mm.domain import CODE, SongStatus
from mm.pipeline import Limits, day_start
from mm.safety import rules
from mm.store import InMemoryStore, JsonDirStore
from mm.web.events import MemoryEvents
from test_web import FORM

ENDS_AT = {
    PUBLISH: SongStatus.PUBLISHED,
    STOP_AT_WORDS: SongStatus.LYRICS_READY,
    STOP_AT_LISTEN: SongStatus.AUDIO_CHECKED,
    REFUSED: SongStatus.REJECTED,
}


@pytest.fixture(scope="module")
def seeded() -> tuple[list, MemoryEvents]:
    events = MemoryEvents()
    songs = seed(InMemoryStore(), events)
    return songs, events


def test_every_case_ends_where_it_says_it_does(seeded):
    songs, _ = seeded
    assert len(songs) == len(CASES)
    for case, song in zip(CASES, songs, strict=True):
        assert song.status is ENDS_AT[case.ends_at], case.shows


def test_the_cases_cover_every_state_a_reviewer_should_see(seeded):
    songs, _ = seeded
    shown = {song.status for song in songs}
    assert shown == {
        SongStatus.PUBLISHED,
        SongStatus.AUDIO_CHECKED,
        SongStatus.LYRICS_READY,
        SongStatus.REJECTED,
    }
    sources = {song.lyrics_source for song in songs}
    assert "writer" in sources and "parent_edit" in sources and "template" in sources
    assert any(song.music_calls > 1 for song in songs), "one song needed more than one try"
    assert len({song.household_id for song in songs}) >= 3


def test_every_song_really_went_through_the_pipeline(seeded):
    songs, _ = seeded
    for song in songs:
        assert song.attempts, "nothing was written into the store by hand"
        assert song.attempts[0].step == "screen", "every song was screened first"
        if song.status is SongStatus.PUBLISHED:
            steps = [attempt.step for attempt in song.attempts]
            for needed in ("write", "rules", "judge", "compose", "audio_check", "preview"):
                assert needed in steps, f"{needed} is missing from a published song"


def test_nothing_was_approved_by_anyone_but_a_person(seeded):
    songs, _ = seeded
    for song in songs:
        if song.status is SongStatus.PUBLISHED:
            assert song.lyrics_approved_by and song.audio_approved_by
        else:
            assert song.audio_approved_by is None


def test_the_refused_brief_was_refused_by_the_real_checks_and_cost_nothing(seeded):
    songs, _ = seeded
    refused = [song for song in songs if song.status is SongStatus.REJECTED]
    assert len(refused) == 1
    song = refused[0]
    assert song.spend_usd() == 0
    assert all(attempt.provider == CODE for attempt in song.attempts)
    assert song.refusal and "shark" not in " ".join(song.refusal).lower()
    # The same brief, screened directly, is refused for the same reason.
    assert rules.screen_brief(song.brief)[0].code == "brand_name"


def test_a_parents_edit_was_refused_before_one_was_accepted(seeded):
    songs, events = seeded
    edited = [song for song in songs if song.lyrics_source == "parent_edit"]
    assert len(edited) == 1
    song = edited[0]
    assert song.edit_checks == 2, "one edit refused, one accepted"
    rejected = [a for a in song.attempts if a.step == "rules" and a.outcome == "rejected"]
    assert any("chorus" in a.detail for a in rejected)
    assert "edit_refused" in events.names()
    assert song.status is SongStatus.PUBLISHED


def test_the_fallback_words_were_used_only_after_the_writer_failed(seeded):
    songs, _ = seeded
    fallback = [song for song in songs if song.lyrics_source == "template"]
    assert len(fallback) == 1
    song = fallback[0]
    assert song.rewrites == 3, "one draft and two rewrites, all refused"
    assert len([a for a in song.attempts if a.step == "write"]) == 3
    assert song.lyrics and rules.check_lyrics(song.lyrics, song.brief) == []


def test_the_retried_song_was_paid_for_twice_and_says_so(seeded):
    songs, _ = seeded
    retried = [song for song in songs if song.music_calls > 1]
    assert retried
    for song in retried:
        paid = [a for a in song.attempts if a.step == "compose"]
        assert len(paid) == song.music_calls
        assert song.spend_usd() > 0.3


def test_the_waiting_song_has_cost_nothing_but_the_words(seeded):
    songs, _ = seeded
    waiting = [song for song in songs if song.status is SongStatus.LYRICS_READY]
    assert len(waiting) == 1
    song = waiting[0]
    assert song.music_calls == 0 and song.audio_path is None
    assert song.spend_usd() < 0.01


def test_the_cases_are_written_with_invented_families(seeded):
    songs, _ = seeded
    for song in songs:
        assert song.household_id.startswith("demo-")


def test_every_case_explains_what_it_is_there_to_show():
    for case in CASES:
        assert case.shows.endswith(".") and len(case.shows) > 30
        assert case.ends_at in ENDS_AT
    assert len({case.shows for case in CASES}) == len(CASES)


def test_the_log_and_the_songs_agree_about_when_things_happened(tmp_path):
    clock = Clock()
    events = MemoryEvents(clock)
    songs = seed(InMemoryStore(), events, clock=clock)

    for song in songs:
        for item in events.items:
            if item["song"] == song.id:
                logged = datetime.fromisoformat(item["at"])
                assert abs((logged - song.created_at).total_seconds()) < 60, song.id
    times = {item["at"] for item in events.items}
    assert len(times) > 1, "the whole afternoon did not happen in one second"


def test_a_refused_brief_is_logged_by_its_code_not_by_the_parents_words(seeded):
    _, events = seeded
    refused = [item for item in events.items if item["name"] == "brief_refused"]
    assert len(refused) == 1
    assert refused[0]["detail"] == {"codes": ["brand_name"]}


def test_the_seeding_writes_an_event_for_every_song(seeded):
    songs, events = seeded
    started = [item for item in events.items if item["name"] == "song_started"]
    assert len(started) == len(songs)
    written = json.dumps(events.items).lower()
    for typed in ("brush teeth", "mina", "shark", "bedtime"):
        assert typed not in written, "the log never holds what a parent typed"


def test_an_edit_that_was_meant_to_be_refused_but_passes_is_an_error():
    """If a rule is ever loosened, this case stops being a demonstration of it. Say so loudly."""
    broken = Case(
        shows="An edit that the checks were meant to refuse, but will not.",
        household="demo-test",
        routine="bedtime",
        steps=("brush teeth", "pajamas on", "lights out"),
        style="gentle_lullaby",
        age_band="3-4",
        ends_at=PUBLISH,
        refused_edit=(4, "Number one, brush teeth"),  # the line it already says
    )
    with pytest.raises(AssertionError, match="meant to be refused"):
        seed(InMemoryStore(), MemoryEvents(), [broken])


def test_seeding_lifts_the_caps_only_for_itself(tmp_path):
    """Eight demo songs need the caps lifted. The running service must still enforce them."""
    cap = Limits().songs_per_household_per_day
    store = JsonDirStore(tmp_path)
    songs = seed(store, MemoryEvents())
    assert len(songs) > cap, "the seeding really did make more songs than one day allows"

    household = songs[0].household_id
    client = TestClient(build_site(tmp_path, [household], ["crew"]), follow_redirects=False)
    brief = {
        "routine": "bedtime",
        "step": ["brush teeth", "pajamas on", "lights out"],
        "style": "gentle_lullaby",
        "age_band": "3-4",
    }
    # Ask for more songs than a day allows and let the service decide where to stop, rather
    # than working the arithmetic out here and getting it wrong.
    codes = [
        client.post(
            f"/h/{household}/songs", content=urlencode(brief, doseq=True), headers=FORM
        ).status_code
        for _ in range(cap + 3)
    ]
    assert codes[-1] == 429, "the running service still enforces the daily cap"
    assert codes.count(303) < cap, "the seeded songs already used part of the day"
    assert store.songs_counted_since(household, day_start(datetime.now(UTC))) == cap


def test_the_demo_command_seeds_a_folder_and_lists_what_it_made(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    assert main(["demo", "--data", str(tmp_path / "demo"), "--team-code", "crew"]) == 0
    printed = capsys.readouterr().out
    assert f"Seeded {len(CASES)} songs" in printed
    for case in CASES:
        assert case.shows in printed
    assert "/studio/crew" in printed
    assert "test tone, not music" in printed
    assert len(list((tmp_path / "demo" / "songs").glob("*.json"))) == len(CASES)
    assert (tmp_path / "demo" / "events.jsonl").exists()


def test_running_the_demo_again_starts_from_a_clean_folder(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: None)
    where = tmp_path / "demo"
    main(["demo", "--data", str(where), "--team-code", "crew"])
    main(["demo", "--data", str(where), "--team-code", "crew"])
    capsys.readouterr()
    assert len(list((where / "songs").glob("*.json"))) == len(CASES), "not doubled"

    main(["demo", "--data", str(where), "--team-code", "crew", "--keep"])
    capsys.readouterr()
    assert len(list((where / "songs").glob("*.json"))) == 2 * len(CASES), "--keep adds"
