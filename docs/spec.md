# What the pipeline must do

This is the contract the code is tested against. If the code and this page disagree, one of them
is wrong: fix it in the same pull request.

## The eight steps

A song moves through a fixed series of steps. The code decides the order. The models only supply
words and sound, and nothing they return can skip a step.

| # | Step | Song status while it waits here | Who moves it on |
| --- | --- | --- | --- |
| 1 | Screen the brief | `draft` | Code. Free. |
| 2 | Write the words | `screened` | Lyrics writer. |
| 3 | Check the words | `screened` | Code rules, then the model judge. |
| 4 | **Parent approves the words** | `lyrics_ready` | A parent. |
| 5 | Make the music | `approved` | Music provider. |
| 6 | Check the audio | `composed` | Code, plus a transcript as a measurement. |
| 7 | **Adult listens** | `audio_checked` | An adult. |
| 8 | Publish | `published` | Nothing further. A child may hear it. |

Two more statuses end a song: `rejected` (we refused to make it) and `failed` (we tried and
could not finish). `advance()` runs every step that needs no person and then stops. Calling it
again on a song that is waiting or finished does nothing and costs nothing.

### Step 1: screen the brief

A brief is a routine name, 3 to 5 steps, a style, an age band, and an optional nickname.

- Routine name and each step: up to 5 words and 40 characters; letters, spaces, hyphens and
  apostrophes only. Digits and symbols are refused, so phone numbers, emails, links and markup
  cannot be typed at all. Numbers are written as words.
- Style: one of the presets in `mm/presets.py`. There is no free-text style.
- Age band: `3-4` or `5-6`. Nickname: one word, up to 20 letters. No other field is accepted.
- Word lists then refuse: unsafe words, medicine, names of artists and characters, requests to
  copy existing music, text aimed at the model, and hints of personal details.

A refused brief becomes `rejected` with a plain reason that never repeats the refused words.
No provider is called. A brief refused this way does not count against a family's daily songs.

### Steps 2 and 3: write and check the words

1. The writer drafts lyrics. Each line may be tagged with the step it sings about.
2. Code rules check the draft (below). Any failure sends it back with the exact reasons.
3. If the rules pass, the model judge checks: safe for the age, faithful to the routine, kind
   in tone, right for the age. A failure sends the draft back with the judge's reasons.
4. After the first draft and 2 rewrites fail, the fallback words are used: a counting song a
   person wrote (`mm/templates.py`). The rules and the judge check those too.
5. If the judge rejects the fallback words, the song is `rejected`.
6. If the judge cannot be reached (two tries), the song is `failed`. Words that were never
   judged are never kept or shown.

Rules for lyrics:

- 60 to 110 words in total. At most 8 words in a line (`{name}` counts as two).
- A chorus that is sung at least twice with exactly the same words.
- Every step is sung, uses the step's own words, and the steps come in the parent's order.
- The only placeholder is `{name}`. Letters and simple punctuation only.
- The same word lists as the brief, except the two that only make sense for typed input.

### Step 4: a parent approves the words

A parent can approve, edit and approve, or ask for a fresh draft.

- An edit goes through the same rules and the same judge. If it fails, the words stay as they
  were and the parent is told what to fix. At most 5 edit checks per song.
- At most 2 fresh drafts per song. Each gets its own 2 rewrites.
- No music is made before this approval. The approval records who gave it.

### Steps 5 and 6: make and check the music

- The call to the music provider is written to the song's record **before** it is made. If the
  process dies mid-call, the next run marks the call as cut short, keeps its estimated cost on
  the books, and counts it against the limits.
- Audio checks: length within 20% of the target, not silent, not too loud.
- A provider error or failed check gets one automatic retry. Two bad results end the song.
- A transcript is taken and compared with the words. The match is recorded, not enforced. If
  the budget does not allow it, it is skipped and the song still moves on.

### Step 7: an adult listens

An adult hears the whole song, then approves or rejects. A rejection can ask for one more
version. Nothing is published without this approval, and it records who gave it.

In study Card 1 and at M6 the adult is the parent. In Cards 2 and 3 a teammate listens first.
That choice belongs to the web layer, not the pipeline.

## The web page

Server-rendered pages and plain forms in `mm/web/`. The web layer adds no rules of its own
about songs. It calls the pipeline, which owns both approvals and every limit.

| Address | What it does |
| --- | --- |
| `GET /` | Says this is a private prototype. No form. |
| `GET /h/{code}` | A household's home: the brief form and its songs. |
| `POST /h/{code}/songs` | Checks the brief, starts a song, sends the parent to it. |
| `GET /h/{code}/songs/{id}` | The song's page. What it shows depends on where the song is. |
| `POST .../words` | Approve the words, save an edit, or ask for a fresh draft. |
| `POST .../listen` | After listening: yes, no, or no and make the music again. |
| `POST .../resume` | Try again after a pause. |
| `GET .../audio` | The audio, once it has passed its checks. Honours byte ranges. |
| `GET /healthz` | `{"status": "ok"}` and nothing else. |

What the web page promises. Each line has a test.

- A participant code is the only key to a household's songs. An unknown code, a code taken off
  the list, another household's song and a missing song all get the same "not found" page.
- Publishing needs the box "I listened to the whole song" ticked, on top of the pipeline's own
  check that the song is at the listening step.
- No audio is served before it has passed its checks.
- A brief with a mistake, or with refused words, is explained on the form and no song is
  created. The explanation never repeats the refused words.
- An edit keeps the song's shape: the same number of lines and the same step tags.
- No page has a script, and nothing loads from another site. Every response carries a content
  security policy that forbids scripts, `Referrer-Policy: no-referrer` so the code in the
  address never leaks, and `Cache-Control: no-store` on pages and audio.
- A form posted from another site is refused. So is a post over 20 KB or of the wrong type,
  before anything reads it.
- Everything a page prints is escaped.
- The event log holds the household code, the song, the event's name, a small detail and the
  time. Nothing a parent typed, no IP address, no browser name.
- Slow work runs in the background, one worker per song. A waiting page reloads by itself. If
  work stopped, for example after a restart, opening the page restarts it up to 3 times; after
  that the page offers a "Try again" button. A paused page does not reload.

## Limits

All in `Limits` in `mm/pipeline.py`.

| Limit | Value |
| --- | --- |
| Rewrites of one draft before the fallback words | 2 |
| Fresh drafts a parent may ask for | 2 |
| Checks of a parent's own edits | 5 |
| Music calls per round (first try plus one retry) | 2 |
| Extra versions an adult may ask for after listening | 1 |
| Music calls per song, in total | 3 |
| Songs per household per day | 5 |
| Spending per day, all households together | $5.00 |

Days are UTC days. Before every paid call the pipeline checks the kill switch and the daily
budget. If either says no, the song stays where it is with a short reason, loses nothing, and
continues the next time `advance()` is called.

Worst case for one song at $0.15 a minute: 3 music calls, about $0.45, plus a few cents of
writer, judge and transcript calls.

## The record

Every song carries a list of attempts: each step, the provider and model, when it started, how
long it took, what it cost, how it ended, and a short detail. This list is the audit trail and
the source for the study metrics (paid tries per usable song, time to a playable song).

## Known gaps

Stated plainly so nobody assumes more than exists.

- **No model judge yet.** 8 of the 37 hostile prompts need judgement (an unsafe instruction in
  ordinary words, an unkind tone, another language). They get through today. The fake judge
  passes everything.
- **No real writer or music.** The fake writer returns the fallback song, so results on fakes
  say nothing about song quality, cost per usable song or speed.
- **Word lists are English only** and short on purpose.
- **Loudness thresholds are first guesses.** Tune them on real audio.
- **The audio inspector reads 16-bit WAV only.**
- **One process only.** The per-song lock and the list of songs being worked on live in
  memory. The database store must use a row lock before a second process is added.
- **No retry for a failed song.** A parent starts a new one, which uses one of the day's songs.
- **Not hosted, and no sign-in beyond participant codes.** The page has only been run on a
  development machine, in Chrome. It has not been tried on an iPhone, where audio is the usual
  trouble spot.
- **No limit on how fast one visitor can send requests.**
- **No private play link for a child yet.** A parent plays the song from their own page.

## What comes next

1. Real adapters for the writer, judge, music and transcript, behind `mm/ports.py`, with an
   eval run that has its own dollar cap. Needs API keys.
2. Hosting: a database store, a container, staging on Railway. Needs accounts.
3. Private play links and the review queue (Card 2). The nightly log (Card 3).
