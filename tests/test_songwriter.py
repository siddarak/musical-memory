"""The songwriter's promise: a real song for any brief the app accepts, and a different one
for a different routine."""

from __future__ import annotations

import itertools

import pytest

from mm.domain import Brief
from mm.presets import STYLE_PRESETS
from mm.safety import rules
from mm.safety.rules import _LYRIC_CHECKS, MAX_LINE_WORDS, _screen
from mm.songwriter import SHAPES, write_song
from mm.templates import fallback_lyrics
from mm.text import count_words

SHORT = ["brush teeth", "lights out", "shoes on", "coat on", "hat on"]
LONGEST = [f"{word} two three four five" for word in ("ant", "bee", "cat", "dog", "eel")]
MIXED = ["put on pajamas", "read one book", "lights out", "wash your hands", "sit at the table"]
NAMES = [None, "Mina", "Aleksandrina"]


def briefs():
    """Every shape of brief the app accepts: each style, 3 to 5 steps, short to longest."""
    for style, steps, count, nickname in itertools.product(
        STYLE_PRESETS, (SHORT, LONGEST, MIXED), (3, 4, 5), NAMES
    ):
        yield Brief(
            routine="bedtime",
            steps=steps[:count],
            style=style,
            age_band="3-4",
            nickname=nickname,
        )


ALL = list(briefs())


def test_the_sweep_really_covers_every_style_and_every_length():
    assert len(ALL) == len(STYLE_PRESETS) * 3 * 3 * 3 == 135
    assert {brief.style for brief in ALL} == set(STYLE_PRESETS)
    assert {len(brief.steps) for brief in ALL} == {3, 4, 5}


@pytest.mark.parametrize("brief", ALL, ids=lambda b: f"{b.style}-{len(b.steps)}-{b.steps[0][:3]}")
def test_every_brief_the_app_accepts_gets_a_song_that_passes_every_rule(brief):
    assert rules.check_lyrics(write_song(brief), brief) == []


@pytest.mark.parametrize("brief", ALL, ids=lambda b: f"{b.style}-{len(b.steps)}-{b.steps[0][:3]}")
def test_the_last_resort_is_never_needed(brief):
    """write_song falls back to the counting song if no arrangement passes. If this ever fails,
    a hand-written shape is wrong: fix the shape rather than relying on the fallback."""
    assert write_song(brief).title != fallback_lyrics(brief).title


def test_a_different_routine_or_style_gives_a_different_song():
    routines = [
        ("bedtime", ("brush teeth", "pajamas on", "lights out")),
        ("cleaning up", ("clear the plates", "fill the sink", "wash each cup")),
        ("leaving the house", ("shoes on", "coat on", "hold my hand")),
    ]
    songs = {
        (routine, style): write_song(
            Brief(routine=routine, steps=steps, style=style, age_band="5-6", nickname="Ravi")
        ).render("Ravi")
        for routine, steps in routines
        for style in STYLE_PRESETS
    }
    assert len(set(songs.values())) == len(songs), "every one of these is its own song"
    # The words a parent typed are what carries into the song.
    assert "Clear the plates" in songs[("cleaning up", "gentle_lullaby")]
    assert "Shoes on" in songs[("leaving the house", "silly_bounce")]


def test_the_same_brief_always_gives_the_same_song():
    brief = Brief(
        routine="bath time",
        steps=("wash your hair", "rinse the bubbles", "dry off"),
        style="calm_piano",
        age_band="3-4",
    )
    first = write_song(brief)
    assert all(write_song(brief) == first for _ in range(5))


def test_both_shapes_of_a_style_are_reachable():
    """Two songs per style only help if briefs actually land on both."""
    for style in STYLE_PRESETS:
        titles = {
            write_song(Brief(routine=routine, steps=SHORT[:3], style=style, age_band="3-4")).title
            for routine in ("bedtime", "bath time", "tidy-up time", "snack time", "morning")
        }
        assert len(titles) == 2, f"{style} always picks the same shape"


# ---- the hand-written words themselves --------------------------------------------------------


def shape_lines():
    for style, shapes in SHAPES.items():
        for shape in shapes:
            for where, lines in (
                ("intro", shape.intro),
                ("chorus", shape.chorus),
                ("outro", shape.outro),
            ):
                for text in lines:
                    yield style, shape.title, where, text


@pytest.mark.parametrize(
    ("style", "title", "where", "text"), list(shape_lines()), ids=lambda v: str(v)[:18]
)
def test_no_hand_written_line_is_too_long(style, title, where, text):
    """The name slot counts as two words, because "little one" is sung there when a parent
    gives no name. A line that only fits with a short name is a line that breaks."""
    assert count_words(text) <= MAX_LINE_WORDS


@pytest.mark.parametrize(
    ("style", "title", "where", "text"), list(shape_lines()), ids=lambda v: str(v)[:18]
)
def test_no_hand_written_line_trips_our_own_word_lists(style, title, where, text):
    assert _screen(text, _LYRIC_CHECKS) == []


def test_every_tail_leaves_room_for_the_longest_step_a_parent_can_type():
    longest_step = 5  # the brief rules cap a step at five words
    for style, shapes in SHAPES.items():
        for shape in shapes:
            for tail in shape.tails:
                assert count_words(tail) + longest_step <= MAX_LINE_WORDS, (style, tail)


def test_every_style_has_shapes_and_every_shape_is_whole():
    assert set(SHAPES) == set(STYLE_PRESETS)
    titles = []
    for shapes in SHAPES.values():
        assert len(shapes) == 2
        for shape in shapes:
            titles.append(shape.title)
            assert len(shape.intro) == 2 and len(shape.outro) == 2
            assert len(shape.chorus) == 4
            assert len(shape.tails) >= 5, "enough tails that five steps do not repeat one"
    assert len(set(titles)) == len(titles), "every shape has its own title"


def test_the_stand_in_writer_uses_the_songwriter():
    from mm.fakes import FakeWriter

    brief = Brief(
        routine="tidy-up time",
        steps=("blocks in the box", "books on the shelf", "cars in the bin"),
        style="clap_along_march",
        age_band="5-6",
    )
    assert FakeWriter().write(brief, ()).lyrics == write_song(brief)
