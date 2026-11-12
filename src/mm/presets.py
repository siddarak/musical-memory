"""Music styles a parent can pick. Free-text styles are not accepted anywhere.

Each preset is a fixed set of style words that we have listened to and approved. Keeping
styles to a short list stops artist and song names from reaching the music provider, which
its terms prohibit, and keeps results predictable enough to test.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StylePreset:
    label: str
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    seconds: int = 60


_NEVER = ("shouting", "distortion", "harsh drums", "spoken word", "child vocal")

STYLE_PRESETS: dict[str, StylePreset] = {
    "gentle_lullaby": StylePreset(
        "Gentle lullaby",
        ("soft lullaby", "acoustic guitar", "warm adult vocal", "slow tempo", "clear diction"),
        _NEVER,
    ),
    "calm_piano": StylePreset(
        "Calm piano",
        ("calm piano", "warm adult vocal", "gentle melody", "slow tempo", "clear diction"),
        _NEVER,
    ),
    "bouncy_ukulele": StylePreset(
        "Bouncy ukulele",
        ("bright ukulele", "warm adult vocal", "happy", "medium tempo", "clear diction"),
        _NEVER,
    ),
    "clap_along_march": StylePreset(
        "Clap-along march",
        ("hand claps", "marching beat", "warm adult vocal", "medium tempo", "clear diction"),
        _NEVER,
    ),
    "silly_bounce": StylePreset(
        "Silly bounce",
        ("playful", "bouncy bass", "warm adult vocal", "medium tempo", "clear diction"),
        _NEVER,
    ),
}
