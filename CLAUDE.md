# Musical Memory: notes for coding agents

A parent types a routine. The service writes checked lyrics, makes a 60 second song, and an adult
hears it before any child does. Class prototype for TECH 5900 (M6 demo on Dec 4). The audience
is children aged 3 to 6, so being wrong here is worse than being slow.

Read `docs/spec.md` before changing the pipeline. Read `docs/decisions.md` before proposing a
different tool or design.

## Rules that do not bend

1. **Two human approvals.** A parent approves the words. An adult listens to the whole song.
   Never add a path around either one, a flag that skips one, or a default that assumes one.
2. **Fakes by default.** Tests, the CLI and CI use `mm.fakes`. Never call a paid provider from
   a test. A real call needs an explicit setting and a dollar cap.
3. **No secrets.** Do not read `.env`. Do not print, log or commit a key. Do not ask for a key
   to be pasted into chat. If you see one in a file, stop and say so.
4. **Child data.** An age band and an optional nickname. Do not add a field about a child.
5. **No names of artists, songs, shows or characters** in prompts, presets, test data or
   anything else that reaches a music provider.
6. **Never weaken a test to make a change pass.** Do not delete, skip, loosen or rewrite a test
   so that it stops failing. If you think a test is wrong, stop and explain why.
7. **Ask before touching** `src/mm/safety/`, `evals/datasets/`, `.github/`, `.claude/` or this
   file. These need a person's review. The permission settings will prompt you.
8. **Production is off limits.** No production database, keys or deploys. Staging only, and
   read-only unless told otherwise.

## Commands

```bash
pip install -e ".[dev]"            # once
pytest                             # all tests, a few seconds
pytest tests/test_pipeline.py -k crash
ruff check . && ruff format .      # lint and format
mypy                               # types, strict
python scripts/check_secrets.py    # before every commit
mm redteam                         # hostile prompts against the checks
mm eval                            # 30 test briefs end to end on fakes
```

All of these must pass before you say a change is done. Say what you ran and what it printed.

## Map

- `src/mm/pipeline.py`: the steps, the approvals and every limit (`Limits`). The order of steps
  lives in `_STEPS` at the bottom. Models never choose the next step.
- `src/mm/safety/rules.py`, `wordlists.py`: checks on input and on lyrics.
- `src/mm/ports.py`: what a provider must look like. Real adapters go in `src/mm/adapters/`
  (not built yet) and must fit these shapes without changing the pipeline.
- `src/mm/fakes.py`: stand-ins. Each takes a `plan` of behaviours to play back.
- `tests/test_pipeline.py`: the contract. One promise per test.

## How to work

- **One slice per pull request**, small enough to review in ten minutes. Branch from `main`.
  Never push to `main`.
- **Test first.** Write or change the test, watch it fail, then make it pass.
- **Update `docs/spec.md` in the same pull request** when behaviour changes.
- **Write a decision down** in `docs/decisions.md` when you choose between real alternatives.
- **After three failed attempts at the same problem, stop.** Write up what you tried and what
  you saw. Do not try a fourth variation of the same idea.
- **Check your own work the way a stranger would.** After a change to a safety or spending
  rule, break the rule on purpose and confirm a test fails. If none does, add the test.
- **Prompts are code.** They live in the repo, carry a version, and change through pull
  requests with eval results attached.
- Say plainly what is not done, not tested or not verified. Do not round up.

## Style

Plain words in anything a parent might read: no jargon, no blame, never repeat the words that
were refused. Comments explain why, not what. Money is written in dollars.
