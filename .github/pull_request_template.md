## What this changes

<!-- One slice. Two or three sentences. -->

## How it was checked

<!-- Paste the commands you ran and what they printed. -->

- [ ] `ruff check .`, `ruff format --check .`, `mypy`
- [ ] `python scripts/check_secrets.py`
- [ ] `pytest`

## Before asking for review

- [ ] No test was deleted, skipped or loosened to make this pass
- [ ] `docs/spec.md` is updated if behaviour changed
- [ ] If a safety or spending rule changed: I broke it on purpose and a test failed
- [ ] No keys, tokens or personal details anywhere in the diff
- [ ] Touches `src/mm/safety/`, `evals/datasets/`, `.github/` or `.claude/`? Say so above. A person must review it.

## Not done or not verified

<!-- Say it plainly. "Nothing" is a fine answer if it is true. -->
