"""Deterministic checks that run before and after the lyrics writer.

This is the cheap, predictable layer. It catches what a list or a count can catch. Anything that
needs judgement (an unsafe instruction in plain words, an unkind tone, another language) is left
to the model judge, which runs only after these checks pass.

Changing this file changes what a child can hear. It needs a human code owner's review.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import ValidationError

from mm import text as t
from mm.domain import Brief, Finding, Lyrics
from mm.safety import wordlists

MIN_WORDS = 60
MAX_WORDS = 110
MAX_LINE_WORDS = 8

_LINE_PUNCTUATION = frozenset(" ,.!?'-’")
# A joined-up name ("pawpatrolpajamas") is only searched for when the name is this long,
# so short names cannot match by accident inside ordinary words.
_MIN_JOINED = 9


def _endings(word: str) -> set[str]:
    """A word with its common endings: hit, hits, hitting; smoke, smoked, smoking."""
    out = {word, word + "s", word + "ed", word + "ing"}
    if word.endswith(("s", "x", "z", "ch", "sh")):
        out.add(word + "es")
    if word.endswith("e"):
        out |= {word + "d", word[:-1] + "ing"}
    short_vowel = len(word) >= 3 and word[-2] in "aeiou" and word[-3] not in "aeiou"
    if short_vowel and word[-1] not in "aeiouwxy":
        out |= {word + word[-1] + "ed", word + word[-1] + "ing"}
    return out


class _Matcher:
    """Finds listed words and phrases in a run of tokens. Whole words only."""

    def __init__(self, terms: Iterable[str], *, endings: bool, joined: bool = False) -> None:
        self.words: set[str] = set()
        self.phrases: list[tuple[str, ...]] = []
        self.joined: set[str] = set()
        for term in terms:
            parts = tuple(t.tokens(term))
            if len(parts) == 1:
                self.words |= _endings(parts[0]) if endings else {parts[0], parts[0] + "s"}
                continue
            self.phrases.append(parts)
            if joined:
                self.words.add("".join(parts))
        if joined:
            names = self.words | {"".join(phrase) for phrase in self.phrases}
            self.joined = {name for name in names if len(name) >= _MIN_JOINED}

    def find(self, toks: list[str]) -> str | None:
        # "monster's" must match "monster", but "he'll" must not become "hell". So each word is
        # tried whole and then cut at its apostrophe; the apostrophe is never simply dropped.
        bases = [tok.split("'")[0] for tok in toks]
        for tok in (*toks, *bases):
            if tok in self.words:
                return tok
        for phrase in self.phrases:
            size = len(phrase)
            for run in (toks, bases):
                for start in range(len(run) - size + 1):
                    if tuple(run[start : start + size]) == phrase:
                        return " ".join(phrase)
        if self.joined:
            joined = "".join(bases)
            for name in self.joined:
                if name in joined:
                    return name
        return None


_UNSAFE = (
    "unsafe_words",
    _Matcher(wordlists.UNSAFE, endings=True),
    "Some of these words are not right for a song for a young child. "
    "Try describing the steps another way.",
)
_MEDICINE = (
    "medicine",
    _Matcher(wordlists.MEDICINE, endings=True),
    "We don't make songs about taking medicine.",
)
_BRANDS = (
    "brand_name",
    _Matcher(wordlists.BRANDS, endings=False, joined=True),
    "We can't use the names of artists, songs, shows or characters. "
    "Describe the steps in plain words and pick one of our styles.",
)
_IMITATION = (
    "imitation",
    _Matcher(wordlists.IMITATION, endings=False),
    "We can't copy an existing song or singer. Pick one of our styles instead.",
)
_INJECTION = (
    "not_a_routine",
    _Matcher(wordlists.INJECTION, endings=True),
    "Please describe the routine steps in plain words.",
)
_CONTACT = (
    "personal_details",
    _Matcher(wordlists.CONTACT, endings=False),
    "Please leave out personal details such as addresses, phone numbers or last names.",
)

_Check = tuple[str, _Matcher, str]  # the code for our logs, the matcher, the words for a parent

_BRIEF_CHECKS: tuple[_Check, ...] = (
    _UNSAFE,
    _MEDICINE,
    _BRANDS,
    _IMITATION,
    _INJECTION,
    _CONTACT,
)
_LYRIC_CHECKS: tuple[_Check, ...] = (_UNSAFE, _MEDICINE, _BRANDS, _CONTACT)
# A child may really be called Elsa or Drake, so a nickname is only checked for unsafe words.
_NICKNAME_CHECKS: tuple[_Check, ...] = (_UNSAFE,)


def _screen(text: str, checks: tuple[_Check, ...]) -> list[Finding]:
    toks = t.squeeze_spelled_words(t.tokens(text))
    found = []
    for code, matcher, message in checks:
        hit = matcher.find(toks)
        if hit:
            found.append(Finding(code=code, message=message, detail=hit))
    return found


def _unique(findings: Iterable[Finding]) -> list[Finding]:
    seen: dict[str, Finding] = {}
    for finding in findings:
        seen.setdefault(finding.code, finding)
    return list(seen.values())


def screen_brief(brief: Brief) -> list[Finding]:
    """Reasons to refuse a brief. An empty list means it may go to the writer."""
    found: list[Finding] = []
    for part in (brief.routine, *brief.steps):
        found += _screen(part, _BRIEF_CHECKS)
    if brief.nickname:
        found += _screen(brief.nickname, _NICKNAME_CHECKS)
    return _unique(found)


def screen_raw(data: object) -> tuple[Brief | None, list[Finding]]:
    """Read untrusted input as a brief and screen it. Use this at every entry point."""
    try:
        brief = Brief.model_validate(data)
    except ValidationError as err:
        found = []
        for problem in err.errors(include_url=False, include_input=False, include_context=False):
            message = str(problem["msg"]).removeprefix("Value error, ")
            where = ".".join(str(part) for part in problem["loc"])
            found.append(Finding(code="invalid_input", message=message, detail=where))
        return None, found
    return brief, screen_brief(brief)


def _same_words(a: str, b: str) -> bool:
    return t.tokens(a) == t.tokens(b)


def check_lyrics(lyrics: Lyrics, brief: Brief) -> list[Finding]:
    """Reasons these lyrics may not be sung. Messages say exactly what to fix."""
    found: list[Finding] = []
    lines = lyrics.lines()

    found += [
        Finding(f.code, "The title uses words we can't use.", f.detail)
        for f in _screen(lyrics.title, _LYRIC_CHECKS)
    ]
    if t.NAME_SLOT in lyrics.title or "{" in lyrics.title or "}" in lyrics.title:
        found.append(Finding("bad_placeholder", "The title must not contain a placeholder."))

    for number, line in enumerate(lines, start=1):
        bare = line.text.replace(t.NAME_SLOT, "")
        if "{" in bare or "}" in bare:
            found.append(
                Finding("bad_placeholder", f"Line {number} uses a placeholder other than {{name}}.")
            )
            bare = bare.replace("{", "").replace("}", "")
        if any(not (ch.isalpha() or ch in _LINE_PUNCTUATION) for ch in bare):
            found.append(
                Finding(
                    "bad_characters",
                    f"Line {number} should use letters and simple punctuation only. "
                    "Write numbers as words.",
                )
            )
        words = t.count_words(line.text)
        if words > MAX_LINE_WORDS:
            found.append(
                Finding(
                    "line_too_long",
                    f"Line {number} has {words} words. The limit is {MAX_LINE_WORDS}.",
                )
            )
        for finding in _screen(line.text, _LYRIC_CHECKS):
            found.append(Finding(finding.code, f"Line {number}: {finding.message}", finding.detail))

    total = lyrics.word_count()
    if total < MIN_WORDS:
        found.append(Finding("too_short", f"The song has {total} words. It needs {MIN_WORDS}."))
    if total > MAX_WORDS:
        found.append(Finding("too_long", f"The song has {total} words. The limit is {MAX_WORDS}."))

    choruses = [section for section in lyrics.sections if section.name == "chorus"]
    if len(choruses) < 2:
        found.append(Finding("chorus_missing", "The chorus must be sung at least twice."))
    else:
        first = "\n".join(line.text for line in choruses[0].lines)
        for other in choruses[1:]:
            if not _same_words(first, "\n".join(line.text for line in other.lines)):
                found.append(
                    Finding("chorus_changes", "Every chorus must use exactly the same words.")
                )
                break

    found += _check_steps(lyrics, brief)
    return found


def _check_steps(lyrics: Lyrics, brief: Brief) -> list[Finding]:
    """Every step of the routine must be sung, by name, in the order the parent gave."""
    found: list[Finding] = []
    first_line: dict[int, int] = {}
    named: set[int] = set()
    for number, line in enumerate(lyrics.lines(), start=1):
        if line.step is None:
            continue
        if line.step >= len(brief.steps):
            found.append(
                Finding("step_unknown", f"Line {number} points at a step that does not exist.")
            )
            continue
        first_line.setdefault(line.step, number)
        if t.content_words(brief.steps[line.step]) & t.all_stems(line.text):
            named.add(line.step)

    for index, step in enumerate(brief.steps):
        if index not in first_line:
            found.append(Finding("step_missing", f'No line sings about the step "{step}".'))
        elif index not in named:
            found.append(
                Finding(
                    "step_not_named",
                    f'The lines for "{step}" never use its words, so a child cannot follow it.',
                )
            )

    order = [first_line[index] for index in range(len(brief.steps)) if index in first_line]
    if order != sorted(order):
        found.append(
            Finding("steps_out_of_order", "The steps must be sung in the order the parent gave.")
        )
    return found
