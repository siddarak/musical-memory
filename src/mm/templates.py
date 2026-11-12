"""Fallback lyrics written by a person, used when the writer cannot produce a draft that passes.

It is a counting song. The only words that change are the parent's own steps, and those were
screened before we got here, so the result passes the lyric rules for every valid brief: the
fixed lines are short, the chorus is identical both times, and each step is sung by name in
order. A test checks this for the shortest and longest briefs the app accepts.
"""

from __future__ import annotations

from mm.domain import Brief, Line, Lyrics, Section

_COUNT = ("one", "two", "three", "four", "five")

_CHORUS = (
    "Step by step, we know the way",
    "Step by step, we do it each day",
    "One by one, {name}, here we go",
    "Nice and steady, nice and slow",
)

_OUTRO = (
    "All done, {name}, all done",
    "We did it, one by one",
)


def fallback_lyrics(brief: Brief) -> Lyrics:
    chorus = Section(name="chorus", lines=[Line(text=text) for text in _CHORUS])
    verse = Section(
        name="verse",
        lines=[
            Line(text=f"Number {_COUNT[index]}, {step}", step=index)
            for index, step in enumerate(brief.steps)
        ],
    )
    outro = Section(name="outro", lines=[Line(text=text) for text in _OUTRO])
    return Lyrics(
        title="Our step by step song",
        sections=[chorus, verse, chorus.model_copy(deep=True), outro],
    )
