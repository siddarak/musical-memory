# Musical Memory

A parent types a routine. The service writes a short song about it, checks the words, makes the
audio, and waits for an adult to listen before any child hears it.

Class prototype for TECH 5900 Product Studio, Team 118.

## Where things stand

This is the skeleton: project settings, the rules coding agents follow, a secret scanner and CI.
The song pipeline arrives in the next pull request. Nothing here can spend money or reach the
network.

## Set up

You need Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Rules that do not bend

1. An adult approves the words, and an adult hears the audio, before a child can hear a song.
2. Tests and local runs use fake providers. A real, paid call needs an explicit choice and a cap.
3. No keys in this repo, in chat, in issues or in logs.
4. The only things kept about a child are an age band and an optional nickname.
5. No artist, song, show or character names go to the music provider.

`CLAUDE.md` has the longer version that coding agents follow. `docs/decisions.md` records what
we chose and why.

## Before you commit

```bash
ruff check . && ruff format --check .
mypy
python scripts/check_secrets.py
pytest
```

CI runs the same commands on every pull request.

## Secrets

Copy `.env.example` to `.env` and fill it in on your own machine. Git ignores `.env`. Keys also
live in the provider dashboards and, later, in Railway variables. If a key is ever pasted into a
file, a chat or an issue, treat it as leaked: delete it at the provider and make a new one.
