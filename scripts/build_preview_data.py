"""Write the service's own lists and words into the browser copy at docs/index.html.

The copy in docs/ reimplements the service's rules in JavaScript, because a static host cannot
run Python. The *data* those rules work on is not retyped: it is generated from the Python
source by this script and embedded in the page.

Run it after changing a word list, a style, a song shape, a guardrail, a decision or the gaps:

    python scripts/build_preview_data.py

tests/test_preview.py fails if the page is out of date, so forgetting to run it is caught.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mm.presets import STYLE_PRESETS  # noqa: E402
from mm.safety import wordlists  # noqa: E402
from mm.songwriter import ARRANGEMENTS, SHAPES  # noqa: E402
from mm.web import studio  # noqa: E402

PAGE = ROOT / "docs/index.html"
BLOCK = re.compile(r'(<script type="application/json" id="mm-data">)(.*?)(</script>)', re.S)


def data() -> dict[str, object]:
    return {
        "unsafe": list(wordlists.UNSAFE),
        "medicine": list(wordlists.MEDICINE),
        "brands": list(wordlists.BRANDS),
        "imitation": list(wordlists.IMITATION),
        "injection": list(wordlists.INJECTION),
        "contact": list(wordlists.CONTACT),
        "styles": {key: preset.label for key, preset in STYLE_PRESETS.items()},
        "shapes": {
            style: [
                {
                    "title": shape.title,
                    "intro": list(shape.intro),
                    "chorus": list(shape.chorus),
                    "tails": list(shape.tails),
                    "outro": list(shape.outro),
                }
                for shape in shapes
            ]
            for style, shapes in SHAPES.items()
        },
        "arrangements": [list(pair) for pair in ARRANGEMENTS],
        "journey": [
            {
                "number": step.number,
                "name": step.name,
                "who": step.who,
                "does": step.does,
                "guard": step.guard,
                "isPerson": step.who == "A person",
                "waitsAt": step.waits_at.value if step.waits_at else None,
            }
            for step in studio.JOURNEY
        ],
        "guardrails": [list(row) for row in studio.GUARDRAILS],
        "decisions": [list(row) for row in studio.DECISIONS],
        "gaps": list(studio.GAPS),
        "redteam": studio.REDTEAM,
        "checks": studio.checks_summary(),
    }


def main() -> int:
    page = PAGE.read_text(encoding="utf-8")
    fresh = json.dumps(data(), separators=(",", ":"))
    found = BLOCK.search(page)
    if not found:
        print("docs/index.html has no mm-data block to fill in.")
        return 1
    if found.group(2) == fresh:
        print("docs/index.html is already up to date.")
        return 0
    PAGE.write_text(BLOCK.sub(lambda m: m.group(1) + fresh + m.group(3), page), encoding="utf-8")
    print(f"docs/index.html updated ({len(fresh)} bytes of data).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
