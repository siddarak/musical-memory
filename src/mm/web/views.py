"""Small pure helpers for the pages: turning forms into data and data into what a page shows."""

from __future__ import annotations

import re
from typing import Any

from fastapi.responses import Response

from mm.domain import Finding, Lyrics, Song, SongStatus
from mm.pipeline import Limits
from mm.presets import STYLE_PRESETS
from mm.safety.rules import MAX_LINE_WORDS
from mm.text import NAME_FALLBACK, NAME_SLOT

Fields = dict[str, list[str]]

WORKING = frozenset(
    {SongStatus.DRAFT, SongStatus.SCREENED, SongStatus.APPROVED, SongStatus.COMPOSED}
)

STATUS_LABELS = {
    SongStatus.DRAFT: "Writing the words",
    SongStatus.SCREENED: "Writing the words",
    SongStatus.LYRICS_READY: "Waiting for you to check the words",
    SongStatus.APPROVED: "Making the music",
    SongStatus.COMPOSED: "Making the music",
    SongStatus.AUDIO_CHECKED: "Waiting for you to listen",
    SongStatus.PUBLISHED: "Ready to play",
    SongStatus.REJECTED: "Not made",
    SongStatus.FAILED: "Did not work out",
}

# Pydantic's own wording for these two fields is written for programmers.
_FIELD_MESSAGES = {
    "age_band": "Choose how old your child is.",
    "style": "Choose how the song should sound.",
}

_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


def one(fields: Fields, name: str) -> str:
    """The first value of a form field, trimmed. Empty when the field is missing."""
    values = fields.get(name, [])
    return values[0].strip() if values else ""


def brief_data(fields: Fields) -> dict[str, Any]:
    """What the form says, in the shape of a brief. Nothing is trusted yet."""
    steps = [value.strip() for value in fields.get("step", []) if value.strip()]
    return {
        "routine": one(fields, "routine"),
        "steps": steps,
        "style": one(fields, "style"),
        "age_band": one(fields, "age_band"),
        "nickname": one(fields, "nickname") or None,
    }


def empty_form() -> dict[str, Any]:
    return {"routine": "", "steps": [], "style": "", "age_band": "", "nickname": None}


def form_values(data: dict[str, Any]) -> dict[str, Any]:
    """What to put back into the form after a problem, with five step boxes."""
    steps = [str(step) for step in data.get("steps", [])][:5]
    return {
        "routine": data.get("routine") or "",
        "steps": steps + [""] * (5 - len(steps)),
        "style": data.get("style") or "",
        "age_band": data.get("age_band") or "",
        "nickname": data.get("nickname") or "",
    }


def messages(findings: list[Finding]) -> list[str]:
    """Plain reasons for a parent, each said once."""
    out: list[str] = []
    for finding in findings:
        field = finding.detail.split(".")[0]
        text = finding.message
        if finding.code == "invalid_input" and field in _FIELD_MESSAGES:
            text = _FIELD_MESSAGES[field]
        if text not in out:
            out.append(text)
    return out


def sheet(lyrics: Lyrics, nickname: str | None) -> list[list[dict[str, Any]]]:
    """The words as they will be sung, with a number beside the first line of each step."""
    name = nickname or NAME_FALLBACK
    marked: set[int] = set()
    sections = []
    for section in lyrics.sections:
        rows = []
        for line in section.lines:
            text = line.text.replace(NAME_SLOT, name)
            number = None
            if line.step is not None and line.step not in marked:
                marked.add(line.step)
                number = line.step + 1
            rows.append({"text": text[:1].upper() + text[1:], "step": number})
        sections.append(rows)
    return sections


def edit_lines(lyrics: Lyrics, typed: list[str] | None) -> list[list[str]]:
    """The text for each box of the edit form: what was typed, or the current words."""
    texts = iter(typed if typed is not None else [line.text for line in lyrics.lines()])
    return [[next(texts) for _ in section.lines] for section in lyrics.sections]


def apply_edit(lyrics: Lyrics, typed: list[str]) -> Lyrics:
    """New lyrics with the typed text in place. The shape and the step tags stay as they were.

    Raises ValueError when the number of lines does not match, and pydantic's ValidationError
    when a line is empty or too long.
    """
    if len(typed) != len(lyrics.lines()):
        raise ValueError("the form does not match the song")
    texts = iter(" ".join(text.split()) for text in typed)
    data = lyrics.model_dump()
    for section in data["sections"]:
        for line in section["lines"]:
            line["text"] = next(texts)
    return Lyrics.model_validate(data)


def song_view(song: Song, limits: Limits, *, editing: bool, stalled: bool) -> dict[str, Any]:
    """Which page a song shows, and what goes on it."""
    view: dict[str, Any] = {
        "mode": "failed",
        "step": None,
        "step_name": "",
        "refresh": None,
        "sheet": sheet(song.lyrics, song.brief.nickname) if song.lyrics else [],
        "from_template": song.lyrics_source == "template",
        "fresh_left": max(0, limits.max_fresh_drafts - song.fresh_drafts),
        "can_retry": (
            song.regenerations < limits.max_regenerations
            and song.music_calls < limits.max_music_calls_per_song
        ),
        "blocked": song.blocked,
        "reasons": song.refusal,
        "failure": song.failure,
        "max_line_words": MAX_LINE_WORDS,
        "style": STYLE_PRESETS[song.brief.style].label,
        "routine": song.brief.routine,
    }
    status = song.status
    early = status in (SongStatus.DRAFT, SongStatus.SCREENED)
    if status in WORKING and (song.blocked or stalled):
        view.update(mode="blocked" if song.blocked else "stalled")
        view.update(step=2 if early else 3, step_name="check the words" if early else "listen")
    elif early:
        view.update(mode="writing", step=2, step_name="check the words", refresh=2)
    elif status is SongStatus.LYRICS_READY:
        view.update(mode="edit" if editing else "words", step=2, step_name="check the words")
    elif status in (SongStatus.APPROVED, SongStatus.COMPOSED):
        view.update(mode="composing", step=3, step_name="listen", refresh=3)
    elif status is SongStatus.AUDIO_CHECKED:
        view.update(mode="listen", step=3, step_name="listen")
    elif status is SongStatus.PUBLISHED:
        view.update(mode="ready", step=4, step_name="play")
    elif status is SongStatus.REJECTED:
        view.update(mode="refused")
    return view


def clean_reason(text: str) -> str:
    """A reviewer's note: one line, no control characters, at most 200 characters."""
    printable = "".join(ch if ch.isprintable() else " " for ch in text)
    return " ".join(printable.split())[:200]


def ranged(data: bytes, mime: str, header: str | None) -> Response:
    """Serve audio, honouring a byte range. Phones will not play audio without this."""
    total = len(data)
    base = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
        "Content-Disposition": "inline",
    }
    match = _RANGE.fullmatch(header.strip()) if header else None
    if match is None or match.groups() == ("", ""):
        return Response(data, media_type=mime, headers=base)
    first, last = match.groups()
    if first == "":  # "bytes=-500" asks for the last 500 bytes
        start, end = max(0, total - int(last)), total - 1
        if int(last) == 0:
            start = total  # nothing to send
    else:
        start, end = int(first), min(int(last) if last else total - 1, total - 1)
    if start >= total or start > end:
        unsatisfiable = {**base, "Content-Range": f"bytes */{total}"}
        return Response(status_code=416, headers=unsatisfiable)
    headers = {**base, "Content-Range": f"bytes {start}-{end}/{total}"}
    return Response(data[start : end + 1], status_code=206, media_type=mime, headers=headers)
