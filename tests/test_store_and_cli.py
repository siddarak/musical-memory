import json
from datetime import UTC, datetime

import pytest

from mm.audio import tone_wav
from mm.cli import main
from mm.controls import EnvControls
from mm.domain import Attempt, Song, SongStatus
from mm.store import InMemoryStore, JsonDirStore

NOON = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def _song(brief, song_id="song0001", household="house-a", cost=0.0):
    song = Song(id=song_id, household_id=household, brief=brief, created_at=NOON, updated_at=NOON)
    if cost:
        song.attempts.append(
            Attempt(step="compose", provider="fake", started_at=NOON, cost_usd=cost, outcome="ok")
        )
    return song


@pytest.fixture(params=["memory", "folder"])
def store(request, tmp_path):
    return InMemoryStore() if request.param == "memory" else JsonDirStore(tmp_path)


def test_a_song_comes_back_as_it_was_saved(store, brief):
    song = _song(brief, cost=0.15)
    store.save(song)
    assert store.get(song.id) == song
    with pytest.raises(KeyError):
        store.get("song9999")


def test_the_store_hands_out_copies_so_an_unsaved_change_is_lost(store, brief):
    song = _song(brief)
    store.save(song)
    song.status = SongStatus.PUBLISHED  # changed after saving
    store.get(song.id).status = SongStatus.PUBLISHED  # changed on a copy we were handed
    assert store.get(song.id).status is SongStatus.DRAFT


def test_the_store_adds_up_spending_and_songs_since_a_moment(store, brief):
    store.save(_song(brief, "song0001", cost=0.15))
    store.save(_song(brief, "song0002", cost=0.10))
    store.save(_song(brief, "song0003", household="house-b"))
    morning = NOON.replace(hour=0)
    afternoon = NOON.replace(hour=13)
    assert store.spend_since(morning) == pytest.approx(0.25)
    assert store.spend_since(afternoon) == 0
    assert store.songs_counted_since("house-a", morning) == 2
    assert store.songs_counted_since("house-a", afternoon) == 0


def test_a_households_songs_are_listed_newest_first_and_only_its_own(store, brief):
    older = _song(brief, "song0001")
    newer = _song(brief, "song0002")
    newer.created_at = NOON.replace(hour=15)
    for song in (older, newer, _song(brief, "song0003", household="house-b")):
        store.save(song)
    assert [song.id for song in store.songs_for_household("house-a")] == ["song0002", "song0001"]
    assert store.songs_for_household("nobody") == []


def test_audio_is_kept_per_song_and_never_overwritten(store):
    first = store.put_audio("song0001", b"one", "audio/wav")
    second = store.put_audio("song0001", b"two", "audio/wav")
    assert first != second
    assert store.get_audio(first) == b"one" and store.get_audio(second) == b"two"


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "UPPER", "x", ""])
def test_an_odd_song_id_is_refused(store, bad_id):
    with pytest.raises(ValueError):
        store.put_audio(bad_id, b"data", "audio/wav")


def test_the_folder_store_will_not_read_outside_its_audio_folder(tmp_path, brief):
    store = JsonDirStore(tmp_path / "data")
    store.save(_song(brief))
    with pytest.raises(ValueError):
        store.get_audio("../outside.wav")
    with pytest.raises(ValueError):
        store.get_audio("songs/song0001.json")


def test_the_env_switch_is_on_by_default_and_off_for_anything_unclear(monkeypatch):
    controls = EnvControls()
    monkeypatch.delenv("GENERATION_ENABLED", raising=False)
    assert controls.generation_enabled()
    for value in ("true", "1", "ON"):
        monkeypatch.setenv("GENERATION_ENABLED", value)
        assert controls.generation_enabled()
    for value in ("false", "0", "off", "", "maybe"):
        monkeypatch.setenv("GENERATION_ENABLED", value)
        assert not controls.generation_enabled()


# ---- command line ---------------------------------------------------------------------------


@pytest.fixture
def brief_file(tmp_path, brief):
    path = tmp_path / "brief.json"
    path.write_text(brief.model_dump_json(), encoding="utf-8")
    return path


def test_generate_stops_for_a_parent_unless_told_otherwise(tmp_path, brief_file, capsys):
    out = tmp_path / "out"
    assert main(["generate", str(brief_file), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "a parent has to approve these words" in printed
    assert "Mimi" in printed
    assert not list((out / "audio").iterdir()), "no audio before the words are approved"


def test_generate_with_yes_writes_a_song_and_its_record(tmp_path, brief_file, capsys):
    out = tmp_path / "out"
    assert main(["generate", str(brief_file), "--out", str(out), "--yes"]) == 0
    printed = capsys.readouterr().out
    assert "test tone" in printed

    (record,) = (out / "songs").glob("*.json")
    song = Song.model_validate_json(record.read_text(encoding="utf-8"))
    assert song.status is SongStatus.PUBLISHED
    (audio,) = (out / "audio").glob("*.wav")
    assert len(audio.read_bytes()) == len(tone_wav(60))


def test_generate_respects_the_kill_switch(tmp_path, brief_file, capsys, monkeypatch):
    monkeypatch.setenv("GENERATION_ENABLED", "false")
    assert main(["generate", str(brief_file), "--out", str(tmp_path / "out"), "--yes"]) == 1
    assert "paused" in capsys.readouterr().out


def test_generate_explains_a_refusal(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "routine": "bedtime",
                "steps": ["sing baby shark", "brush teeth", "lights out"],
                "style": "silly_bounce",
                "age_band": "3-4",
            }
        ),
        encoding="utf-8",
    )
    assert main(["generate", str(path), "--out", str(tmp_path / "out"), "--yes"]) == 1
    assert "artists, songs, shows or characters" in capsys.readouterr().out
    assert main(["screen", str(path)]) == 1


def test_generate_rejects_a_file_that_is_not_a_brief(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"routine": "bedtime"}', encoding="utf-8")
    assert main(["generate", str(path), "--out", str(tmp_path / "out")]) == 2
    assert "cannot be used" in capsys.readouterr().out


def test_screen_passes_a_good_brief(brief_file, capsys):
    assert main(["screen", str(brief_file)]) == 0
