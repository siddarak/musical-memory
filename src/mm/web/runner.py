"""Runs the pipeline for a song outside the request that asked for it.

Making music takes about a minute, far too long to hold a page open. A request starts the work
and returns at once; the page then refreshes until the song needs a person again.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from mm.pipeline import Pipeline

log = logging.getLogger("mm.web")


class Runner(Protocol):
    def kick(self, song_id: str) -> None: ...

    def is_working(self, song_id: str) -> bool: ...


def _advance(pipeline: Pipeline, song_id: str) -> None:
    try:
        pipeline.advance(song_id)
    except Exception:
        # The song keeps whatever was last saved. The page offers to try again.
        log.exception("work on song %s stopped", song_id)


class InlineRunner:
    """Does the work before returning. For tests, where the fake providers are instant."""

    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline

    def kick(self, song_id: str) -> None:
        _advance(self.pipeline, song_id)

    def is_working(self, song_id: str) -> bool:
        return False


class ThreadRunner:
    """Does the work on a background thread, at most one per song."""

    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self._active: set[str] = set()
        self._lock = threading.Lock()

    def kick(self, song_id: str) -> None:
        with self._lock:
            if song_id in self._active:
                return
            self._active.add(song_id)
        threading.Thread(
            target=self._run, args=(song_id,), name=f"song-{song_id}", daemon=True
        ).start()

    def _run(self, song_id: str) -> None:
        try:
            _advance(self.pipeline, song_id)
        finally:
            with self._lock:
                self._active.discard(song_id)

    def is_working(self, song_id: str) -> bool:
        with self._lock:
            return song_id in self._active
