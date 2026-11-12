# Decisions

Short records of choices between real alternatives. Newest at the bottom. Add one when you
choose; do not rewrite old ones, add a new entry that replaces them.

## 1. A fixed pipeline, not an agent

**Decided.** The order of steps is written in code (`_STEPS` in `mm/pipeline.py`). Models fill
in words and sound and never choose what happens next.

Why: the output is for children aged 3 to 6. We need to be able to say exactly which checks ran
on every song, test each one, and prove that nothing can skip the two human approvals. A
free-running agent makes all three harder and buys nothing here, because the task is the same
eight steps every time.

## 2. Providers sit behind ports, and fakes are the default

**Decided.** The pipeline only knows the shapes in `mm/ports.py`. Tests, the CLI and CI use
`mm/fakes.py`.

Why: the checks and limits can be built and tested before any key exists, tests cost nothing
and never flake on a network, and the music or lyrics provider can be swapped without touching
the pipeline. The cost: fakes cannot tell us whether real songs are any good. Only evals on
real providers can.

## 3. Two layers of checking: lists and counts first, a model judge second

**Decided.** Deterministic rules run first. The model judge runs only on what passes them.

Why: rules are free, instant and predictable, so they should catch everything they can. They
cannot understand meaning, so a second layer has to. Words whose safety depends on context
(kick, oven, weed) are left to the judge so that ordinary routines are not refused. The
hostile prompts are labelled by which layer must stop them, and a test fails if a label is
wrong.

## 4. If a check cannot run, stop

**Decided.** If the judge cannot be reached, the song fails. If audio cannot be read, it is
treated as bad audio. An unclear kill-switch value means off.

Why: the safe mistake is a song that was not made.

## 5. Styles are a short list of presets

**Decided.** No free-text style. See `mm/presets.py`.

Why: the music provider's terms forbid artist names and song titles in what we send. A fixed
list keeps them out, makes results predictable enough to test, and removes one place where
hostile text could reach a model.

## 6. What a parent types is tightly limited

**Decided.** Letters, spaces, hyphens and apostrophes only; 5 words and 40 characters per step.

Why: it removes whole classes of problems before any list is consulted. Phone numbers, emails,
links and markup cannot be typed. Long instructions aimed at the model do not fit. The cost is
that a parent writes "two books", not "2 books".

## 7. Money is recorded before it is spent

**Decided.** A music call is saved on the song as started, with its estimated cost, before the
provider is called.

Why: if the process dies mid-call we cannot know whether we were charged. Assuming we were is
the only choice that keeps the caps true.

## 8. Core has one dependency

**Decided.** The pipeline depends on pydantic and the standard library.

Why: less to break, less to review, quick installs in CI. Web and provider libraries will be
added only where they are used.

## 9. Stack for the hosted service

**Proposed. Waiting for Sid's OK.** Python with FastAPI and server-rendered pages, one
always-on container per environment on Railway, Supabase for Postgres and private file storage,
ElevenLabs for music, the Claude API for the writer and judge.

Why this over Next.js on Vercel: a song takes around a minute to make, which suits an always-on
process better than serverless time limits; the team reads Python; and one small container is
simpler to reason about than functions plus a queue. Sources and prices are in the plan doc.

Open questions that could change it: whether ElevenLabs' terms allow end users to supply the
words on the plan we would use (ask them), and Cornell's rules for studies that involve
children (ask the coach).

## 10. Agent permissions are guard rails, not walls

**Decided.** `.claude/settings.json` denies reading `.env` files and destructive commands, and
asks before pushes, installs and edits to safety files, datasets, CI and settings.

Why: these rules stop the ordinary mistake. They are not a security boundary: a command can be
written another way. The real protection is that no production key or database is ever
reachable from a machine where an agent runs.
