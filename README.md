# Musical Memory

A parent types a routine. The service writes a short song about it, checks the words, makes the
audio, and waits for an adult to listen before any child hears it.

Built by Team 118 for TECH 5900 Product Studio at Cornell Tech, with Claude as a coding
assistant. Siddhesh Darak, Lemuel Sumardy, Daniel Xing.

## Click it

**https://siddarak.github.io/musical-memory/**

If that link 404s, Pages has not been switched on yet. One person does it once: **Settings,
Pages, Source: Deploy from a branch, branch `main`, folder `/docs`, Save.** It is live about a
minute later, and every push to main republishes it.

That is the browser copy: the same screens, the same word lists, the same checks and the same
caps, with no install. Type a routine a check should refuse and it is refused there too. It
opens with eight songs already in it, so both the parent side and the team view have something
to look at.

Two things the browser copy cannot do, and it says so on the page: no model writes the words,
and the audio is the 60 second test tone. It runs the same songwriter as the service, checked
song for song by a test, so what you hear described there is what the service does.

## Run it

You need Python 3.11 or newer. Nothing else: no Docker, no database, no hosting account.

```bash
git clone https://github.com/siddarak/musical-memory.git
cd musical-memory
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
mm demo
```

`mm demo` fills the service with eight forced test cases and then starts it, so you can see the
whole product on the first click instead of an empty page. Every one of those cases is a real
run through the real eight steps: a finished song, one waiting for a parent to check the words,
one waiting for an adult to listen, one where the parent's first edit was refused and the second
accepted, one that needed a second music try, one that fell back to the words a person wrote,
and one brief the checks refused outright.

Use `mm serve` instead to start empty and make your own.

Either command prints two links:

- **The parent link.** The whole journey: describe a routine, check the words, listen, play.
- **The team link.** Every song, every step it took, what it cost, and the thinking behind the
  design. Read-only.

To open it from a tablet on the same wifi, run `mm serve --host 0.0.0.0` and use your computer's
address instead of `127.0.0.1`.

Each link is a password. Anyone who has one can use it, so treat them that way.

## What works today, and what does not

| | |
| --- | --- |
| The eight-step pipeline, both human approvals, every limit | Works |
| The web pages, on a phone, a tablet or a laptop | Works |
| The team view: journey, songs, costs, event log, decisions | Works |
| A different song for a different routine, from hand-written shapes | Works |
| **Words written by a model** | **Needs an Anthropic API key** |
| **Real music** | **Needs a Gemini API key with billing on** |
| Hosting | Not set up. One machine, started by hand. |

Without those two keys the service still runs end to end. The words come from ten hand-written
song shapes with your own steps fitted in, so "bedtime" and "cleaning up" really do give
different songs, and the audio is a 60 second test tone. A model would write better words and a
music provider would make an actual song, but everything they pass through is real: the same
checks, the same approvals, the same limits, and the same record of what each step cost.

## Other commands

```bash
mm generate examples/bedtime.json    # one brief, start to finish, on the command line
mm screen examples/bedtime.json      # check a brief without making anything
mm redteam                           # run the hostile prompts against the checks
mm eval                              # run the 30 test briefs end to end
mm codes --count 3                   # make participant codes for a study
mm serve                             # start empty, make your own songs
pytest                               # about 365 tests, a few seconds
```

Songs and the event log are saved under `data/` for `mm serve`, `demo-data/` for `mm demo` and
`out/` for `mm generate`. Git ignores all three. Running `mm demo` again starts from a clean
folder unless you pass `--keep`.

## How it is built

```
src/mm/
  domain.py        the data: Brief, Lyrics, Song, and the song's status
  pipeline.py      the eight steps, the two human approvals, and every limit
  safety/rules.py  checks on what a parent types and on finished lyrics
  safety/wordlists.py
  songwriter.py    writes a song from hand-written shapes, with no model
  templates.py     the simplest possible song, the last resort if even that fails
  audio.py         checks on finished audio
  ports.py         the shapes a provider must fit (writer, judge, music, store)
  fakes.py         free, instant stand-ins for the paid providers
  store.py         where songs are kept (memory, or a folder of JSON files)
  controls.py      the kill switch
  cli.py           the mm command
  demo.py          the forced test cases behind mm demo
  web/             the pages: app.py holds every address, and asks the pipeline
docs/              the browser copy served at the link above, plus the spec and decisions
evals/datasets/    30 test briefs, 37 hostile prompts
tests/             the promises this service makes, one test each
docs/spec.md       what the pipeline must do (read this before changing it)
docs/decisions.md  what we chose and why
```

The order of the eight steps is written in code. The models fill in words and sound, and never
choose what happens next. That is what makes it possible to say exactly which checks ran on any
song, and to test each one.

## Rules that do not bend

1. An adult approves the words, and an adult hears the audio, before a child can hear a song.
2. Tests and local runs use fake providers. A real, paid call needs an explicit choice and a cap.
3. No keys in this repository, in chat, in issues or in logs.
4. The only things kept about a child are an age band and an optional nickname.
5. No artist, song, show or character names go to the music provider.
6. No scripts on any page, and nothing loaded from another site.

Rule 6 is about the service. The browser copy in `docs/` has to be a script, because that is
what a static host can run; it keeps the second half of the rule, loads nothing from anywhere
else, and stores nothing. Tests check that its lists and figures still match the service's.

`CLAUDE.md` has the longer version that coding agents follow. The team view's "How it works"
page explains all of this to a reader who has never seen the code.

## Before you commit

```bash
ruff check . && ruff format --check .
mypy
python scripts/check_secrets.py
pytest
```

CI runs the same commands on every pull request, plus `mm redteam` and `mm eval`. No secrets are
available to CI, because nothing in it needs any.

## Keys, when you add them

Copy `.env.example` to `.env` and fill it in. Git ignores `.env`. If a key is ever pasted into a
file, a chat or an issue, treat it as leaked: delete it at the provider and make a new one.
