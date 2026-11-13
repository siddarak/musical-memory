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

**Proposed. Waiting for Sid's OK. The music provider is settled in decision 21, and this entry's open question about ElevenLabs' input rules is answered there.** Python
with FastAPI and server-rendered pages, one always-on container per environment on Railway,
Supabase for Postgres and private file storage, ElevenLabs for music, the Claude API for the
writer and judge.

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

## 11. Pages without scripts

**Decided.** The web page is server-rendered HTML and plain forms. No page carries a script,
and nothing is loaded from another site: the font and the stylesheet are served by the app.

Why: the audience is families, so nothing about them should reach a third party, and "no
scripts" is a promise a content security policy can enforce and a test can check. A waiting
page reloads itself with a plain refresh. The cost is a less lively page, which is fine for a
study prototype. The plan had proposed HTMX for partial page updates. It was not needed.

## 12. A participant code in the address is the key

**Decided for the study.** A family gets a link that contains a long random code. There are no
accounts or passwords until the M6 version.

Why: nothing to sign up for during a study, and no email addresses to store. The cost is that
the link is a password. So the pages send `Referrer-Policy: no-referrer`, the server writes no
access log, links are not printed on a hosted service, and every "not found" looks the same
whether the code, the household or the song was wrong.

## 13. The form checks a brief before a song exists

**Decided.** The web page runs the same input rules and word lists as the pipeline and shows
problems on the form. A song is only created for a brief that passes. The pipeline still
screens every brief itself.

Why: a parent can fix a mistake in place, refused briefs do not pile up as songs, and the
pipeline stays the one place that decides.

## 14. One page per thing a person is doing, in two columns

**Decided.** On a tablet or a laptop a page splits in two: what you are reading on the left, what
you can do about it on the right. On a phone it stays one column.

Why: the decision a parent is being asked to make is about something they have to read first, so
the words and the buttons belong on screen together. The phone layout is unchanged because there
is no room for a second column at that width.

## 15. A team view, separate from the parent's pages

**Decided.** `/studio/{code}` shows every household's songs, every step each one took, the event
log, and the design itself: the eight steps, the guardrails, the caps and the decisions. It is
read-only and sits behind its own codes.

Why: the service makes claims about itself (an adult always listens first, spending cannot run
away, every step of a routine is sung) and a reviewer should be able to check them without
reading the code or opening a database. It also gives the team one place to see what a study
session actually did.

What it costs: one more door to keep shut. The team codes are separate from participant codes,
neither opens the other, and the team view never serves audio.

The figures on its pages are not retyped from the documentation. The step counts come from the
pipeline's own statuses, the word-list sizes from the lists, and the hostile-prompt results from
the dataset, each checked by a test, so the page cannot quietly drift from what the code does.

## 16. Forced test cases, run for real

**Decided.** `mm demo` seeds one case for every state a reviewer should see, by running each
one through the pipeline rather than writing rows into the store.

Why: a prototype that opens empty shows nothing, and a prototype seeded with hand-written rows
proves nothing. Running the cases for real means the demo is also a test: if a check stops
working, the case that depended on it changes or fails, and the team view shows it.

What it costs: the cases have to be kept in step with the pipeline, and the seeding needs the
daily caps lifted for itself. Both are stated where they happen and covered by tests.

## 17. A browser copy, so the prototype has a link

**Decided.** `docs/` holds a single-page version of the product, served by GitHub Pages at
https://siddarak.github.io/musical-memory/. It ports the service's rules into JavaScript: the
same word lists, the same checks on a brief and on finished lyrics, the same eight steps, the
same two human approvals, the same caps.

Why: a prototype that needs Python installed before anyone can see it is not a prototype anyone
will look at. Teammates, a class, a room with a projector: all of them need a link. A static
host cannot run the Python service, so the only way to get one without paying for hosting is to
reimplement the rules where the browser can run them.

What it costs: two copies of the same rules, which can drift. `tests/test_preview.py` is the
answer to that. The lists, the styles, the eight steps, the guardrails, the decisions, the
caps, the stylesheet and the font files are all checked against the service's own, so a change
in one that is not carried to the other fails the build.

It also breaks rule 9 of `CLAUDE.md`, which says no scripts on any page. That rule protects a
family's data on the real service. The copy keeps the half that still applies, loading nothing
from any other site, and stores nothing at all, which the page says plainly.

What stays true: the copy cannot write a song. Its words come from the template and its audio
is the test tone, and the page says so above the player rather than leaving anyone to guess.

## 18. A songwriter with no model in it

**Decided.** `mm/songwriter.py` fits the parent's steps into one of ten hand-written song
shapes, two per style, chosen from the brief. It is the stand-in writer until a model is wired
in, and the browser copy runs the same one.

Why: the earlier stand-in returned one counting song for every brief, so "bedtime" and
"cleaning up" came back word for word the same, with the parent's steps barely visible. That
makes a demo look broken and tells a reviewer nothing. Ten shapes with the steps carried into
the verse gives a different, singable song for a different routine, with no key and no cost.

How it stays correct: every verse line puts the step first and adds a short fixed tail, because
a step can be a noun phrase ("lights out") as easily as a verb phrase, and nothing reads well in
front of both. The builder tries four arrangements, runs each past the real lyric rules, and
returns the first that passes; if none does it returns the counting song, which always passes. A
test says that last resort is never reached for any brief the app accepts, so a mistake in a
hand-written shape shows up as a failure rather than a quiet downgrade. Two of my own shapes had
a nine word line and two had a four word tail; the sweep caught all four.

What it is not: a model. The words are ours, not written for this family, and the gaps list on
the team view says so.

## 19. The browser copy is driven by clicks, not by form submission

**Decided, after it broke.** Every action on the page hangs off a click handler. The submit
handler remains, but only so the Enter key still works where forms are allowed.

Why: the page is shown inside a frame whose sandbox does not permit form submission. There a
submit event never fires, so the first version did nothing at all when "Write the words" was
pressed. The form looked fine, the console was clean, and the whole journey was unreachable.
It worked everywhere I had tested it, because serving the page directly is not the same as
serving it in a frame.

What it costs: two handlers instead of one, and a rule to keep. Three tests pin it: every
button that does something carries its own action, the two submit buttons are checked by name,
and the click handler must call preventDefault so a click can never also fire the form and run
an action twice. Reintroducing the bug fails all three.

The lesson worth keeping: test the thing in the frame it will actually run in. A page that works
on a local web server tells you nothing about a page inside someone else's sandbox.

## 20. Lyria 3.5 through the Gemini API for music, not ElevenLabs

**Superseded the same day by decision 21. Kept for what it was weighed on.** This replaces the music half of decision 9. The writer and
the judge still go through the Claude API.

Why: one call returns a sung song with the words in time, so the pipeline loses a step it would
otherwise need to join music and a voice. Google's price list shows a full song at $0.08 with no
free tier, against $0.15 a minute at ElevenLabs, and there is no monthly fee, so a day of the
$5 cap buys 62 songs instead of 33. On the paid tier Google does not use what we send to
improve their products; on the free tier it does, and for a page where a parent types something
about their own child that difference decides it. The paid tier is the only one that carries
Lyria anyway.

The term we read and accepted: the Gemini API age requirements say a developer must be 18 or
older, and that the API must not be used as part of a service "directed towards or is likely to
be accessed by individuals under the age of 18". Sid's reading is that the service is operated
by a parent from end to end. A parent types the routine, a parent approves the words, and an
adult listens to the whole song before a child hears any of it. No child signs in, and no screen
is built for a child. The songs are for children aged 3 to 6 and a child hears the audio, so
this is a reading and not a certainty. It is recorded here so that a reviewer can disagree with
it in one place rather than guess at it.

Still to ask the coach: Cornell's rules for a study that involves children. That question is open
from decision 9 and this does not close it.

Still open, and found while writing this down: ElevenLabs was going to do two jobs, not one. The
other is the transcriber, which listens to the finished song and reads back what was actually
sung so the pipeline can compare it with the words the parent approved. Lyria does not do that,
and its own timed lyrics are not a substitute, because the point of that step is to check the
audio rather than trust what the provider says it made. So a transcriber still has to be chosen.
Gemini can transcribe audio, which would keep us to two vendors, but then the same vendor both
makes the song and marks its own work. A different vendor is the safer shape. Not decided here.

What it costs: nothing in the pipeline. `MusicProvider` in `src/mm/ports.py` already says what an
adapter has to do, so this is one file in `src/mm/adapters/` either way, and the steps, the
limits and the two approvals do not move. If the reading above turns out to be wrong, the
adapter is replaced and nothing else is.

## 21. ElevenLabs for music and for the transcriber, which supersedes decision 20

**Decided by Sid on 13 Nov 2026, the same day as decision 20.** Decision 20 stands as the record
of what Lyria was weighed on, because the reasoning is worth keeping. This replaces its
conclusion. Starter plan, $6 a month, bought before this was written.

What changed in the few hours between them: reading ElevenLabs' terms properly, which decision 9
had left as an open question, and finding they are cleaner for this project in the one way that
matters most.

The input rule, which is the question decision 9 was waiting on. Section 2.1 of the Eleven Music
terms says a customer must not submit as input artist names, songwriter names, song titles, album
titles, publisher names or record label names, and item (g) adds a substantial or distinctive
portion of any song's lyrics where a reasonable person would judge the prompt to be referencing a
particular song. Our own original words are nowhere prohibited, and the only duty attached to
them is the warranty in section 2.2 that we hold the rights to what we submit. So a parent's
routine, turned into words we wrote, is allowed. Decision 9's open question is closed.

The age rule, which is why this beats Lyria. ElevenLabs requires the account holder to be 18 or
over and says nothing about who the audience is. There is no counterpart to the Gemini term that
forbids use in a service directed towards, or likely to be accessed by, anyone under 18. Decision
20 accepted a reading of that term. This needs no reading at all. For a graded project whose whole
subject is children aged 3 to 6, paying more to have nothing for a reviewer to question is worth
it. Our word lists already exist to block exactly the inputs section 2.1 names, so the safety
layer we built for one provider fits the other unchanged.

It also closes the gap decision 20 opened. ElevenLabs does the transcriber as well, so the step
that listens to a finished song and reads back what was actually sung has a provider again, and it
is one key instead of two vendors.

What it costs, and this is the part to watch. Published rates are $0.15 a minute for music and
$0.22 an hour for Scribe. In the credits the subscription meters, music is about 900 a minute and
speech to text about 330, so one 60 second song plus the check on it is roughly 1,230 credits
against the 30,000 a month Starter includes. That is about 24 songs a month, which is far tighter
than the $5 a day in `Limits` assumes. Whether API calls draw down those credits or bill
separately as pay as you go is not something we have established, and the sources disagree. We
will know from what the usage page deducts after the first real call, and the number here is
provisional until then.

The consequence is immediate and worth naming: `mm eval` runs 30 briefs end to end. Pointed at the
real provider even once, that single command would spend more than a month of Starter credits. It
must stay on fakes, which rule 2 already requires and which the adapter must not make easy to
undo.
