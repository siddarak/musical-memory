"""Places to keep songs: in memory for tests, in a folder for local runs.

Both hand out copies, never the object they hold, so a change that was not saved is lost. That
is how the real database behaves, and it lets the tests catch a forgotten save.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from mm.domain import Song

_SONG_ID = re.compile(r"^[a-z0-9]{6,40}$")
_EXTENSIONS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3"}


def _check_id(song_id: str) -> str:
    if not _SONG_ID.match(song_id):
        raise ValueError("song id is not valid")
    return song_id


def _extension(mime: str) -> str:
    try:
        return _EXTENSIONS[mime]
    except KeyError:
        raise ValueError(f"unsupported audio type: {mime}") from None


def _counted(songs: list[Song], household_id: str, start: datetime) -> int:
    return sum(
        1
        for song in songs
        if song.household_id == household_id
        and song.created_at >= start
        and song.counts_toward_daily_cap()
    )


def _by_age(songs: list[Song]) -> list[Song]:
    return sorted(songs, key=lambda song: (song.created_at, song.id), reverse=True)


def _newest_first(songs: list[Song], household_id: str) -> list[Song]:
    return _by_age([song for song in songs if song.household_id == household_id])


def _spent(songs: list[Song], start: datetime) -> float:
    return sum(
        attempt.cost_usd
        for song in songs
        for attempt in song.attempts
        if attempt.started_at >= start
    )


class InMemoryStore:
    def __init__(self) -> None:
        self._songs: dict[str, Song] = {}
        self._audio: dict[str, bytes] = {}

    def save(self, song: Song) -> None:
        self._songs[_check_id(song.id)] = song.model_copy(deep=True)

    def get(self, song_id: str) -> Song:
        return self._songs[song_id].model_copy(deep=True)

    def songs_for_household(self, household_id: str) -> list[Song]:
        copies = [song.model_copy(deep=True) for song in self._songs.values()]
        return _newest_first(copies, household_id)

    def recent_songs(self, limit: int = 50) -> list[Song]:
        copies = [song.model_copy(deep=True) for song in self._songs.values()]
        return _by_age(copies)[:limit]

    def songs_counted_since(self, household_id: str, start: datetime) -> int:
        return _counted(list(self._songs.values()), household_id, start)

    def spend_since(self, start: datetime) -> float:
        return _spent(list(self._songs.values()), start)

    def put_audio(self, song_id: str, data: bytes, mime: str) -> str:
        taken = sum(1 for path in self._audio if path.startswith(f"audio/{song_id}-"))
        path = f"audio/{_check_id(song_id)}-{taken + 1}.{_extension(mime)}"
        self._audio[path] = data
        return path

    def get_audio(self, path: str) -> bytes:
        return self._audio[path]


class JsonDirStore:
    """One JSON file per song under `songs/`, audio under `audio/`."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        (self.root / "songs").mkdir(parents=True, exist_ok=True)
        (self.root / "audio").mkdir(parents=True, exist_ok=True)

    def _song_file(self, song_id: str) -> Path:
        return self.root / "songs" / f"{_check_id(song_id)}.json"

    def _all(self) -> list[Song]:
        files = sorted((self.root / "songs").glob("*.json"))
        return [Song.model_validate_json(file.read_text(encoding="utf-8")) for file in files]

    def save(self, song: Song) -> None:
        target = self._song_file(song.id)
        partial = target.with_suffix(".json.part")
        partial.write_text(song.model_dump_json(indent=2), encoding="utf-8")
        os.replace(partial, target)  # a crash leaves the old file or the new one, never half

    def get(self, song_id: str) -> Song:
        try:
            return Song.model_validate_json(self._song_file(song_id).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise KeyError(song_id) from None

    def songs_for_household(self, household_id: str) -> list[Song]:
        return _newest_first(self._all(), household_id)

    def recent_songs(self, limit: int = 50) -> list[Song]:
        return _by_age(self._all())[:limit]

    def songs_counted_since(self, household_id: str, start: datetime) -> int:
        return _counted(self._all(), household_id, start)

    def spend_since(self, start: datetime) -> float:
        return _spent(self._all(), start)

    def put_audio(self, song_id: str, data: bytes, mime: str) -> str:
        folder = self.root / "audio"
        taken = len(list(folder.glob(f"{_check_id(song_id)}-*")))
        path = f"audio/{song_id}-{taken + 1}.{_extension(mime)}"
        (self.root / path).write_bytes(data)
        return path

    def get_audio(self, path: str) -> bytes:
        target = (self.root / path).resolve()
        if not target.is_relative_to((self.root / "audio").resolve()):
            raise ValueError("audio path is outside the store")
        return target.read_bytes()
