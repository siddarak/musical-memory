"""Writes a song for a routine without calling a model.

This is the stand-in lyrics writer. It is not a model and does not pretend to be one: it fits
the parent's own steps into one of ten hand-written song shapes, picked from the brief, so a
different routine or a different style really does give a different song. That is the whole
point. One fixed template for every routine makes a demo look broken, because the words a
parent typed barely show up in what comes back.

Every shape is written to the lyric rules: short lines, a chorus that repeats word for word,
every step sung by name and in order. Rather than trust that, this module builds a few
arrangements, runs each past the real checks, and returns the first that passes. If none did,
it returns the counting song in `templates.py`, which is simpler and always passes. A test says
that last resort is never reached for a valid brief, so we would know if a shape went wrong.

A step may be a verb phrase ("brush teeth") or a noun phrase ("lights out"), so every verse line
puts the step first and adds a short fixed tail: "lights out, soft and slow" reads as well as
"brush teeth, soft and slow". Nothing is inserted before a step, because "now we lights out" is
not English.
"""

from __future__ import annotations

from dataclasses import dataclass

from mm.domain import Brief, Line, Lyrics, Section
from mm.safety.rules import check_lyrics
from mm.templates import fallback_lyrics


@dataclass(frozen=True)
class Shape:
    """One hand-written song: what surrounds the parent's steps.

    `{name}` is where the nickname is sung, and counts as two words because "little one" is
    sung there when a parent gives no name. Tails are at most three words, so the longest step
    a parent can type still leaves a line inside the eight word limit.
    """

    title: str
    intro: tuple[str, str]
    chorus: tuple[str, str, str, str]
    tails: tuple[str, ...]
    outro: tuple[str, str]


SHAPES: dict[str, tuple[Shape, ...]] = {
    "gentle_lullaby": (
        Shape(
            title="Softly now",
            intro=("The moon is up, the day is done", "Softly now, {name}, one by one"),
            chorus=(
                "Step by step, we find our way",
                "Sleepy eyes at end of day",
                "Slow and gentle, soft and low",
                "This is how we always go",
            ),
            tails=("soft and slow", "nice and light", "one by one", "almost there", "quiet now"),
            outro=("All done now, the night is here", "Sleep well, {name}, I am near"),
        ),
        Shape(
            title="Little by little",
            intro=("The stars are out, the lamps are low", "Little by little, off we go"),
            chorus=(
                "Hush now, hush now, close your eyes",
                "Night is falling, soft and wise",
                "One small step and then one more",
                "Dreams are waiting at the door",
            ),
            tails=("hush now", "gently now", "soft and warm", "nearly done", "slow and sure"),
            outro=("The day is over now, {name}", "Goodnight, goodnight, sleep well, you"),
        ),
    ),
    "calm_piano": (
        Shape(
            title="Quiet hands",
            intro=("A quiet song for {name} to hear", "One gentle step and then we cheer"),
            chorus=(
                "Quiet hands and quiet feet",
                "Every step is soft and sweet",
                "One by one we take our time",
                "Like a gentle piano chime",
            ),
            tails=("gently now", "nice and calm", "one by one", "slow and sure", "softly now"),
            outro=("The song is ending, calm and clear", "Well done, {name}, well done, my dear"),
        ),
        Shape(
            title="One small step",
            intro=("Listen to the quiet keys", "They will help us, if you please"),
            chorus=(
                "One small step, and then the next",
                "Nothing hurried, nothing vexed",
                "Soft and steady, that is how",
                "We will do it, here and now",
            ),
            tails=("steady now", "soft and sure", "take your time", "that is how", "calm and kind"),
            outro=("The keys are quiet, we are too", "Beautifully done, {name}, by you"),
        ),
    ),
    "bouncy_ukulele": (
        Shape(
            title="Strum along",
            intro=("Pick it up and strum a tune", "{name} will have it finished soon"),
            chorus=(
                "Strum along and sing with me",
                "Happy as a bird can be",
                "One more time and then we are through",
                "This is what we love to do",
            ),
            tails=("off we go", "one two three", "here we come", "all day long", "sing it out"),
            outro=("The song is finished, that was fun", "Hooray for {name}, the job is done"),
        ),
        Shape(
            title="Up we get",
            intro=("Four small strings and one big grin", "Here we go, let us begin"),
            chorus=(
                "Up we get and on we go",
                "Not too fast and not too slow",
                "Sing it loud and sing it clear",
                "Everybody join in here",
            ),
            tails=("on we go", "sing it out", "one two three", "nearly there", "what a day"),
            outro=("Strum the last one, let it ring", "{name} did every single thing"),
        ),
    ),
    "clap_along_march": (
        Shape(
            title="Left and right",
            intro=("Left and right, let us start the day", "Here we go, {name}, on our way"),
            chorus=(
                "Clap your hands and stamp your feet",
                "One two three, we keep the beat",
                "March along and do not slow",
                "Here we go, go, go, go, go",
            ),
            tails=("left and right", "on we go", "one two three", "march along", "keep it up"),
            outro=("That is the end, we are all done", "Marching, marching, that was fun"),
        ),
        Shape(
            title="Keep the beat",
            intro=("Drums are ready, so are we", "Follow along and you will see"),
            chorus=(
                "One, two, one, two, keep the beat",
                "Swing your arms and lift your feet",
                "Forward, forward, never stop",
                "All the way up to the top",
            ),
            tails=("one two", "keep it up", "stamp stamp stamp", "nearly there", "on we march"),
            outro=(
                "Halt right there, the march is through",
                "Well marched, {name}, well marched by you",
            ),
        ),
    ),
    "silly_bounce": (
        Shape(
            title="Wiggle and giggle",
            intro=("Shake your elbows, wave hello", "Silliest song you will ever know"),
            chorus=(
                "Wiggle, giggle, hop and spin",
                "Here the silly song begins",
                "Boing, boing, up we go",
                "Everybody now, hello",
            ),
            tails=("wiggle wiggle", "boing boing", "giggle giggle", "so silly", "hop hop hop"),
            outro=("That was silly, that was grand", "Give yourself a great big hand"),
        ),
        Shape(
            title="Noodle arms",
            intro=("Noodle arms and jelly knees", "Wobble over here, {name}, please"),
            chorus=(
                "Flippy, floppy, round we spin",
                "Chin to elbow, knee to shin",
                "Silly, silly, what a sight",
                "Doing everything just right",
            ),
            tails=("wobble wobble", "flip flop", "what a sight", "silly silly", "whee"),
            outro=("Flop down now and have a rest", "Silly songs are much the best"),
        ),
    ),
}


def fnv1a(text: str) -> int:
    """A small, stable hash. Python's own `hash` is salted per process, so the same brief would
    get a different song on every restart. FNV-1a is a few lines in any language, which is what
    lets the browser copy in docs/ pick the same shape for the same brief.
    """
    value = 0x811C9DC5
    for byte in text.encode("utf-8"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def _pick(brief: Brief) -> Shape:
    """Which shape this brief gets. The same brief always gets the same one."""
    seed = "|".join([brief.routine, brief.style, *brief.steps]).lower()
    options = SHAPES[brief.style]
    return options[fnv1a(seed) % len(options)]


def _verse(brief: Brief, shape: Shape, with_tails: bool) -> Section:
    lines = []
    for index, step in enumerate(brief.steps):
        tail = shape.tails[index % len(shape.tails)] if with_tails else ""
        lines.append(Line(text=f"{step}, {tail}" if tail else step, step=index))
    return Section(name="verse", lines=lines)


def _build(brief: Brief, shape: Shape, with_intro: bool, with_tails: bool) -> Lyrics:
    chorus = Section(name="chorus", lines=[Line(text=text) for text in shape.chorus])
    sections = []
    if with_intro:
        sections.append(Section(name="intro", lines=[Line(text=text) for text in shape.intro]))
    sections.append(chorus)
    sections.append(_verse(brief, shape, with_tails))
    sections.append(chorus.model_copy(deep=True))
    sections.append(Section(name="outro", lines=[Line(text=text) for text in shape.outro]))
    return Lyrics(title=shape.title, sections=sections)


# Fullest first. A long routine overflows the word limit with the intro in, and a very short one
# falls under it without, so the arrangements are tried in order and the first that passes wins.
ARRANGEMENTS = ((True, True), (False, True), (True, False), (False, False))


def write_song(brief: Brief) -> Lyrics:
    """A song for this brief that passes every lyric rule.

    Falls back to the counting song in `templates.py` only if no arrangement passes, which a
    test says does not happen for a valid brief.
    """
    shape = _pick(brief)
    for with_intro, with_tails in ARRANGEMENTS:
        lyrics = _build(brief, shape, with_intro, with_tails)
        if not check_lyrics(lyrics, brief):
            return lyrics
    return fallback_lyrics(brief)
