# Musical Memory

A parent types a routine. The service writes a short song about it, checks the words, makes the
audio, and waits for an adult to listen before any child hears it.

Class prototype for TECH 5900 Product Studio, Team 118.

## Where things stand

| Piece | State |
| --- | --- |
| Song pipeline: 8 fixed steps, two human approvals, spending limits | Built. Runs on fake providers. |
| Input checks and word lists | Built. |
| 30 test briefs and 37 hostile prompts | Built. 29 hostile prompts are stopped today. 8 need the model judge. |
| Web page for parents: describe, check the words, listen, play | Built. Runs on your machine with fake providers. |
| Real lyrics writer and judge (Claude API) | Not built. |
| Real music (ElevenLabs) | Not built. |
| Hosting | Not set up. |

Nothing in this repo can spend money or reach the network yet. The "song" it makes is a
60 second test tone. That is on purpose: the checks, limits and approvals were built and tested
first, so the paid parts plug into something that already says no when it should.

## Try it

You need Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest                               # about 320 tests, a few seconds
mm serve                             # the web page; it prints a link to open
mm generate examples/bedtime.json    # writes the words, then stops for a parent
mm generate examples/bedtime.json --yes   # approve both human steps yourself
mm screen examples/bedtime.json      # check a brief without making anything
mm redteam                           # run the hostile prompts against the checks
mm eval                              # run the 30 test briefs end to end
```

`mm serve` saves songs and the event log under `data/`, and `mm generate` under `out/`. Git
ignores both. Each song has a JSON record with every step it went through and what each step
cost.

To give a family their own link, make a code with `mm codes` and start the page with
`mm serve --code THE-CODE`. A code is the only key to that family's songs, so treat a link like
a password.

## How it fits together

```
src/mm/
  domain.py        the data: Brief, Lyrics, Song, and the song's status
  pipeline.py      the steps, the two human approvals, and every limit
  safety/rules.py  checks on what a parent types and on finished lyrics
  safety/wordlists.py
  templates.py     fallback words a person wrote, for when the writer fails
  audio.py         checks on finished audio
  ports.py         the shapes a provider must fit (writer, judge, music, store)
  fakes.py         free, instant stand-ins for the paid providers
  store.py         where songs are kept (memory, or a folder of JSON files)
  controls.py      the kill switch
  cli.py           the mm command
  web/app.py       the pages and forms; it asks the pipeline, it never decides
  web/views.py     turning forms into data and songs into pages
  web/runner.py    does the slow work in the background
  web/access.py    participant codes
  web/events.py    the study's event log
  web/templates/, web/static/   the pages, one stylesheet, the font (no scripts)
evals/datasets/    30 test briefs, 37 hostile prompts
tests/             the pipeline's promises, one test each
docs/spec.md       what the pipeline must do (read this before changing it)
docs/decisions.md  what we chose and why
```

## Rules that do not bend

1. An adult approves the words, and an adult hears the audio, before a child can hear a song.
2. Tests and local runs use fake providers. A real, paid call needs an explicit choice and a cap.
3. No keys in this repo, in chat, in issues or in logs.
4. The only things kept about a child are an age band and an optional nickname.
5. No artist, song, show or character names go to the music provider.
6. No scripts on any page, and nothing loaded from another site.

`CLAUDE.md` has the longer version that coding agents follow.

## Before you commit

```bash
ruff check . && ruff format --check .
mypy
python scripts/check_secrets.py
pytest
```

CI runs the same commands on every pull request, plus `mm redteam` and `mm eval`.

## Secrets

Copy `.env.example` to `.env` and fill it in on your own machine. Git ignores `.env`. Keys also
live in the provider dashboards and, later, in Railway variables. If a key is ever pasted into a
file, a chat or an issue, treat it as leaked: delete it at the provider and make a new one.
