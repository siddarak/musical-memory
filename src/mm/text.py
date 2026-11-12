"""Small text helpers shared by the rules, the fallback lyrics and the audio checks."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

NAME_SLOT = "{name}"
NAME_FALLBACK = "little one"
# The slot counts as two words, so a line still fits when the fallback is sung instead of a name.
NAME_SLOT_WORDS = 2

_TOKEN = re.compile(r"[a-z]+(?:'[a-z]+)*")
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "at", "be", "by", "do", "for", "go", "in", "is", "it", "my",
    "of", "off", "on", "or", "our", "out", "so", "the", "to", "up", "we", "with", "you", "your",
})  # fmt: skip


def fold(text: str) -> str:
    """Lower-case the text, strip accents and keep only words.

    Apostrophes stay inside words, so "he'll" never turns into a different word.
    """
    text = text.replace(NAME_SLOT, " ").replace("’", "'")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(_TOKEN.findall(text))


def tokens(text: str) -> list[str]:
    return fold(text).split()


def squeeze_spelled_words(toks: list[str]) -> list[str]:
    """Turn "h i t him" into "hit him", so spelling a word out does not hide it."""
    out: list[str] = []
    run: list[str] = []
    for tok in [*toks, ""]:
        if len(tok) == 1:
            run.append(tok)
            continue
        out.extend(["".join(run)] if len(run) >= 3 else run)
        run = []
        if tok:
            out.append(tok)
    return out


def count_words(text: str) -> int:
    """Count the words a child would sing in a line."""
    rest = text.replace(NAME_SLOT, " ")
    sung = sum(1 for part in rest.split() if any(ch.isalpha() for ch in part))
    return sung + text.count(NAME_SLOT) * NAME_SLOT_WORDS


def stem(word: str) -> str:
    """Rough stem, used only to see whether a line names a step.

    It is deliberately loose ("hate" and "hat" collide), so never use it to match blocked words.
    """
    word = word.split("'")[0]
    for suffix in ("ing", "ed"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            if word[-1] == word[-2] and word[-1] not in "ls":
                word = word[:-1]
            break
    else:
        if word.endswith("ies") and len(word) > 4:
            word = word[:-3] + "y"
        elif word.endswith("es") and word[:-2].endswith(("s", "x", "z", "ch", "sh")):
            word = word[:-2]
        elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
            word = word[:-1]
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    return word


def content_words(text: str) -> frozenset[str]:
    """The stems of the words that carry meaning ("put on pajamas" gives put, pajama)."""
    toks = tokens(text)
    kept = [tok for tok in toks if tok not in _STOPWORDS] or toks
    return frozenset(stem(tok) for tok in kept)


def all_stems(text: str) -> frozenset[str]:
    """The stems of every word, small words included."""
    return frozenset(stem(tok) for tok in tokens(text))


def match_ratio(expected: str, heard: str) -> float:
    """Share of the expected words that also appear in what was heard (0 to 1)."""
    want = Counter(tokens(expected))
    got = Counter(tokens(heard))
    total = sum(want.values())
    if not total:
        return 0.0
    return sum(min(count, got[word]) for word, count in want.items()) / total
