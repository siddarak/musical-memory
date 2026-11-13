/* Musical Memory, in the browser.

   The Python service in this repository is the real thing. GitHub Pages can only serve static
   files, so this file ports the service's rules into the browser: the same word lists, the same
   checks on a brief and on finished lyrics, the same eight steps, the same two human approvals,
   the same caps. Type a routine a check should refuse and it is refused here too.

   The lists and the team-view content come from DATA, which is generated from the Python source
   and checked by tests/test_preview.py, so this page cannot drift from the service.

   Two honest differences, stated on the page as well: the waiting times are shortened, and the
   audio is the same 60 second test tone the service makes until a music key is set. */

"use strict";

const DATA = JSON.parse(document.getElementById("mm-data").textContent);

const MIN_WORDS = DATA.checks.min_words;
const MAX_WORDS = DATA.checks.max_words;
const MAX_LINE_WORDS = DATA.checks.max_line_words;
const NAME_SLOT = "{name}";
const NAME_FALLBACK = "little one";

const LIMITS = {
  maxRewrites: 2,
  maxFreshDrafts: 2,
  maxEditChecks: 5,
  maxMusicCallsPerRound: 2,
  maxRegenerations: 1,
  maxMusicCallsPerSong: 3,
  songsPerHouseholdPerDay: 5,
  dailyBudgetUsd: 5,
  musicPricePerMinuteUsd: 0.15,
};

const COST = { write: 0.002, judge: 0.002, music: 0.15, transcribe: 0.007 };
const WRITE_MS = 1100;
const MUSIC_MS = 2600;

const STATUS_LABELS = {
  draft: "Writing the words",
  screened: "Writing the words",
  lyrics_ready: "Waiting for you to check the words",
  approved: "Making the music",
  composed: "Making the music",
  audio_checked: "Waiting for you to listen",
  published: "Ready to play",
  rejected: "Not made",
  failed: "Did not work out",
};

const WORDS_FROM = { writer: "the model", template: "our fallback", parent_edit: "the parent" };
const JOURNEY_STEPS = ["Describe the routine", "Check the words", "Listen", "Play"];

/* ---------- text, the same way mm/text.py does it ---------- */

const STOPWORDS = new Set(
  ("a an and are at be by do for go in is it my of off on or our out so the to up we with you your").split(" ")
);

function fold(text) {
  return text
    .split(NAME_SLOT)
    .join(" ")
    .replace(/’/g, "'")
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .match(/[a-z]+(?:'[a-z]+)*/g);
}

function tokens(text) {
  return fold(text) || [];
}

function squeezeSpelled(toks) {
  // "h i t him" is "hit him". Spelling a word out must not hide it.
  const out = [];
  let run = [];
  for (const tok of toks.concat([""])) {
    if (tok.length === 1) {
      run.push(tok);
      continue;
    }
    if (run.length >= 3) out.push(run.join(""));
    else out.push(...run);
    run = [];
    if (tok) out.push(tok);
  }
  return out;
}

function countWords(text) {
  const slots = text.split(NAME_SLOT).length - 1;
  const rest = text.split(NAME_SLOT).join(" ");
  const sung = rest.split(/\s+/).filter((part) => /[a-zA-ZÀ-ɏ]/.test(part)).length;
  return sung + slots * 2; // the slot may be sung as "little one"
}

function stem(word) {
  let out = word.split("'")[0];
  for (const suffix of ["ing", "ed"]) {
    if (out.endsWith(suffix) && out.length - suffix.length >= 3) {
      out = out.slice(0, -suffix.length);
      if (out.at(-1) === out.at(-2) && !"ls".includes(out.at(-1))) out = out.slice(0, -1);
      return out.endsWith("e") && out.length > 3 ? out.slice(0, -1) : out;
    }
  }
  if (out.endsWith("ies") && out.length > 4) out = out.slice(0, -3) + "y";
  else if (out.endsWith("es") && /(s|x|z|ch|sh)$/.test(out.slice(0, -2))) out = out.slice(0, -2);
  else if (out.endsWith("s") && !out.endsWith("ss") && out.length > 3) out = out.slice(0, -1);
  return out.endsWith("e") && out.length > 3 ? out.slice(0, -1) : out;
}

function contentWords(text) {
  const toks = tokens(text);
  const kept = toks.filter((tok) => !STOPWORDS.has(tok));
  return new Set((kept.length ? kept : toks).map(stem));
}

function allStems(text) {
  return new Set(tokens(text).map(stem));
}

/* ---------- the word lists, the same way mm/safety/rules.py uses them ---------- */

function endingsOf(word) {
  const out = new Set([word, word + "s", word + "ed", word + "ing"]);
  if (/(s|x|z|ch|sh)$/.test(word)) out.add(word + "es");
  if (word.endsWith("e")) {
    out.add(word + "d");
    out.add(word.slice(0, -1) + "ing");
  }
  const shortVowel =
    word.length >= 3 && "aeiou".includes(word.at(-2)) && !"aeiou".includes(word.at(-3));
  if (shortVowel && !"aeiouwxy".includes(word.at(-1))) {
    out.add(word + word.at(-1) + "ed");
    out.add(word + word.at(-1) + "ing");
  }
  return out;
}

const MIN_JOINED = 9;

function buildMatcher(terms, { endings, joined }) {
  const words = new Set();
  const phrases = [];
  for (const term of terms) {
    const parts = tokens(term);
    if (parts.length === 1) {
      if (endings) for (const form of endingsOf(parts[0])) words.add(form);
      else {
        words.add(parts[0]);
        words.add(parts[0] + "s");
      }
    } else {
      phrases.push(parts);
      if (joined) words.add(parts.join(""));
    }
  }
  let joinedNames = new Set();
  if (joined) {
    const names = new Set([...words, ...phrases.map((p) => p.join(""))]);
    joinedNames = new Set([...names].filter((name) => name.length >= MIN_JOINED));
  }
  return function find(toks) {
    const bases = toks.map((tok) => tok.split("'")[0]);
    for (const tok of toks.concat(bases)) if (words.has(tok)) return tok;
    for (const phrase of phrases) {
      for (const run of [toks, bases]) {
        for (let i = 0; i + phrase.length <= run.length; i++) {
          if (phrase.every((part, j) => run[i + j] === part)) return phrase.join(" ");
        }
      }
    }
    if (joinedNames.size) {
      const run = bases.join("");
      for (const name of joinedNames) if (run.includes(name)) return name;
    }
    return null;
  };
}

const UNSAFE = [
  "unsafe_words",
  buildMatcher(DATA.unsafe, { endings: true }),
  "Some of these words are not right for a song for a young child. Try describing the steps another way.",
];
const MEDICINE = [
  "medicine",
  buildMatcher(DATA.medicine, { endings: true }),
  "We don't make songs about taking medicine.",
];
const BRANDS = [
  "brand_name",
  buildMatcher(DATA.brands, { endings: false, joined: true }),
  "We can't use the names of artists, songs, shows or characters. Describe the steps in plain words and pick one of our styles.",
];
const IMITATION = [
  "imitation",
  buildMatcher(DATA.imitation, { endings: false }),
  "We can't copy an existing song or singer. Pick one of our styles instead.",
];
const INJECTION = [
  "not_a_routine",
  buildMatcher(DATA.injection, { endings: true }),
  "Please describe the routine steps in plain words.",
];
const CONTACT = [
  "personal_details",
  buildMatcher(DATA.contact, { endings: false }),
  "Please leave out personal details such as addresses, phone numbers or last names.",
];

const BRIEF_CHECKS = [UNSAFE, MEDICINE, BRANDS, IMITATION, INJECTION, CONTACT];
const LYRIC_CHECKS = [UNSAFE, MEDICINE, BRANDS, CONTACT];
const NICKNAME_CHECKS = [UNSAFE]; // a child may really be called Elsa

function screenText(text, checks) {
  const toks = squeezeSpelled(tokens(text));
  const found = [];
  for (const [code, find, message] of checks) {
    const hit = find(toks);
    if (hit) found.push({ code, message, detail: hit });
  }
  return found;
}

function unique(findings) {
  const seen = new Map();
  for (const finding of findings) if (!seen.has(finding.code)) seen.set(finding.code, finding);
  return [...seen.values()];
}

/* ---------- reading a brief, the same way mm/domain.py does ---------- */

const PHRASE = /^[A-Za-zÀ-ÖØ-öø-ÿ]+(?:[ '-][A-Za-zÀ-ÖØ-öø-ÿ]+)*$/;
const NICKNAME = /^[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['-][A-Za-zÀ-ÖØ-öø-ÿ]+)?$/;
const LETTERS_ONLY = "Use letters only, with spaces, hyphens or apostrophes. Write numbers as words.";

function tidy(value) {
  return (value || "").normalize("NFKC").replace(/’/g, "'").split(/\s+/).filter(Boolean).join(" ");
}

function checkPhrase(value, what, found) {
  if (!value) return found.push({ code: "invalid_input", message: `${what} is empty.`, detail: "" });
  if (value.length > 40) return found.push({ code: "invalid_input", message: `Keep ${what.toLowerCase()} under 40 letters.`, detail: "" });
  if (!PHRASE.test(value)) return found.push({ code: "invalid_input", message: LETTERS_ONLY, detail: "" });
  if (value.split(" ").length > 5) found.push({ code: "invalid_input", message: `Keep ${what.toLowerCase()} to 5 words or fewer.`, detail: "" });
}

function readBrief(raw) {
  const found = [];
  const routine = tidy(raw.routine);
  const steps = (raw.steps || []).map(tidy).filter(Boolean);
  const nickname = tidy(raw.nickname) || null;

  checkPhrase(routine, "The routine name", found);
  if (steps.length < 3 || steps.length > 5) {
    found.push({ code: "invalid_input", message: "Give 3 to 5 steps.", detail: "" });
  }
  for (const step of steps) checkPhrase(step, "Each step", found);
  if (new Set(steps.map((s) => s.toLowerCase())).size !== steps.length) {
    found.push({ code: "invalid_input", message: "Each step should be different.", detail: "" });
  }
  if (!DATA.styles[raw.style]) {
    found.push({ code: "invalid_input", message: "Choose how the song should sound.", detail: "" });
  }
  if (raw.age_band !== "3-4" && raw.age_band !== "5-6") {
    found.push({ code: "invalid_input", message: "Choose how old your child is.", detail: "" });
  }
  if (nickname && (nickname.length > 20 || !NICKNAME.test(nickname))) {
    found.push({ code: "invalid_input", message: "Use one short nickname or first name, letters only.", detail: "" });
  }
  if (found.length) return { brief: null, findings: unique(found) };

  const brief = { routine, steps, style: raw.style, ageBand: raw.age_band, nickname };
  return { brief, findings: screenBrief(brief) };
}

function screenBrief(brief) {
  const found = [];
  for (const part of [brief.routine, ...brief.steps]) found.push(...screenText(part, BRIEF_CHECKS));
  if (brief.nickname) found.push(...screenText(brief.nickname, NICKNAME_CHECKS));
  return unique(found);
}

/* ---------- the words, from mm/templates.py ---------- */

const COUNT = ["one", "two", "three", "four", "five"];
const CHORUS = [
  "Step by step, we know the way",
  "Step by step, we do it each day",
  "One by one, {name}, here we go",
  "Nice and steady, nice and slow",
];
const OUTRO = ["All done, {name}, all done", "We did it, one by one"];

/* The songwriter, the same shapes and the same assembly as mm/songwriter.py. The shapes
   themselves come from DATA, which is generated from the Python source, and a test runs both
   over the same briefs and compares the result word for word. */

function fnv1a(text) {
  let value = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(text)) {
    value = Math.imul(value ^ byte, 0x01000193) >>> 0;
  }
  return value;
}

function pickShape(brief) {
  const seed = [brief.routine, brief.style, ...brief.steps].join("|").toLowerCase();
  const options = DATA.shapes[brief.style];
  return options[fnv1a(seed) % options.length];
}

function buildSong(brief, shape, withIntro, withTails) {
  const chorus = () => ({ name: "chorus", lines: shape.chorus.map((text) => ({ text, step: null })) });
  const sections = [];
  if (withIntro) sections.push({ name: "intro", lines: shape.intro.map((text) => ({ text, step: null })) });
  sections.push(chorus());
  sections.push({
    name: "verse",
    lines: brief.steps.map((step, index) => {
      const tail = withTails ? shape.tails[index % shape.tails.length] : "";
      return { text: tail ? `${step}, ${tail}` : step, step: index };
    }),
  });
  sections.push(chorus());
  sections.push({ name: "outro", lines: shape.outro.map((text) => ({ text, step: null })) });
  return { title: shape.title, sections };
}

function writeSong(brief) {
  const shape = pickShape(brief);
  for (const [withIntro, withTails] of DATA.arrangements) {
    const lyrics = buildSong(brief, shape, withIntro, withTails);
    if (!checkLyrics(lyrics, brief).length) return lyrics;
  }
  return templateLyrics(brief); // the last resort, as in the service
}

function templateLyrics(brief) {
  const chorus = () => ({ name: "chorus", lines: CHORUS.map((text) => ({ text, step: null })) });
  return {
    title: "Our step by step song",
    sections: [
      chorus(),
      {
        name: "verse",
        lines: brief.steps.map((step, i) => ({ text: `Number ${COUNT[i]}, ${step}`, step: i })),
      },
      chorus(),
      { name: "outro", lines: OUTRO.map((text) => ({ text, step: null })) },
    ],
  };
}

function flatLines(lyrics) {
  return lyrics.sections.flatMap((section) => section.lines);
}

function wordCount(lyrics) {
  return flatLines(lyrics).reduce((total, line) => total + countWords(line.text), 0);
}

function renderWords(lyrics, nickname) {
  const name = nickname || NAME_FALLBACK;
  return lyrics.sections
    .map((section) =>
      section.lines
        .map((line) => {
          const text = line.text.split(NAME_SLOT).join(name);
          return text.charAt(0).toUpperCase() + text.slice(1);
        })
        .join("\n")
    )
    .join("\n\n");
}

const LINE_PUNCTUATION = new Set([" ", ",", ".", "!", "?", "'", "-", "’"]);

function checkLyrics(lyrics, brief) {
  const found = [];
  const lines = flatLines(lyrics);

  lines.forEach((line, index) => {
    const number = index + 1;
    let bare = line.text.split(NAME_SLOT).join("");
    if (bare.includes("{") || bare.includes("}")) {
      found.push({ code: "bad_placeholder", message: `Line ${number} uses a placeholder other than {name}.` });
      bare = bare.replace(/[{}]/g, "");
    }
    if ([...bare].some((ch) => !/[a-zA-ZÀ-ɏ]/.test(ch) && !LINE_PUNCTUATION.has(ch))) {
      found.push({
        code: "bad_characters",
        message: `Line ${number} should use letters and simple punctuation only. Write numbers as words.`,
      });
    }
    const words = countWords(line.text);
    if (words > MAX_LINE_WORDS) {
      found.push({ code: "line_too_long", message: `Line ${number} has ${words} words. The limit is ${MAX_LINE_WORDS}.` });
    }
    for (const finding of screenText(line.text, LYRIC_CHECKS)) {
      found.push({ code: finding.code, message: `Line ${number}: ${finding.message}`, detail: finding.detail });
    }
  });

  const total = wordCount(lyrics);
  if (total < MIN_WORDS) found.push({ code: "too_short", message: `The song has ${total} words. It needs ${MIN_WORDS}.` });
  if (total > MAX_WORDS) found.push({ code: "too_long", message: `The song has ${total} words. The limit is ${MAX_WORDS}.` });

  const choruses = lyrics.sections.filter((section) => section.name === "chorus");
  if (choruses.length < 2) {
    found.push({ code: "chorus_missing", message: "The chorus must be sung at least twice." });
  } else {
    const first = choruses[0].lines.map((line) => line.text).join("\n");
    for (const other of choruses.slice(1)) {
      const text = other.lines.map((line) => line.text).join("\n");
      if (tokens(first).join(" ") !== tokens(text).join(" ")) {
        found.push({ code: "chorus_changes", message: "Every chorus must use exactly the same words." });
        break;
      }
    }
  }

  const firstLine = new Map();
  const named = new Set();
  lines.forEach((line, index) => {
    if (line.step === null || line.step === undefined) return;
    if (line.step >= brief.steps.length) {
      found.push({ code: "step_unknown", message: `Line ${index + 1} points at a step that does not exist.` });
      return;
    }
    if (!firstLine.has(line.step)) firstLine.set(line.step, index + 1);
    const want = contentWords(brief.steps[line.step]);
    const have = allStems(line.text);
    if ([...want].some((word) => have.has(word))) named.add(line.step);
  });
  brief.steps.forEach((step, index) => {
    if (!firstLine.has(index)) {
      found.push({ code: "step_missing", message: `No line sings about the step "${step}".` });
    } else if (!named.has(index)) {
      found.push({
        code: "step_not_named",
        message: `The lines for "${step}" never use its words, so a child cannot follow it.`,
      });
    }
  });
  const order = brief.steps.map((_, i) => firstLine.get(i)).filter((n) => n !== undefined);
  if (order.some((n, i) => i > 0 && n < order[i - 1])) {
    found.push({ code: "steps_out_of_order", message: "The steps must be sung in the order the parent gave." });
  }
  return found;
}

/* ---------- the test tone, the same shape mm/audio.py makes ---------- */

let toneUrl = null;

function toneWav(seconds = 60, rate = 8000, hz = 400, amplitude = 0.25) {
  const count = Math.floor(seconds * rate);
  const buffer = new ArrayBuffer(44 + count * 2);
  const view = new DataView(buffer);
  const text = (offset, value) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + count * 2, true);
  text(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, count * 2, true);
  const period = Math.floor(rate / hz);
  for (let i = 0; i < count; i++) {
    view.setInt16(44 + i * 2, Math.round(amplitude * 32767 * Math.sin((2 * Math.PI * (i % period)) / period)), true);
  }
  return URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
}

function audioUrl() {
  if (!toneUrl) toneUrl = toneWav();
  return toneUrl;
}

/* ---------- the pipeline ---------- */

const state = {
  view: "parent",
  teamTab: "live",
  songs: [],
  events: [],
  currentId: null,
  editing: false,
  problems: [],
  typed: null,
  form: emptyForm(),
  household: "you",
};

let nextId = 1;

function emptyForm() {
  return { routine: "", steps: ["", "", "", "", ""], style: "", age_band: "", nickname: "" };
}

function now() {
  return new Date();
}

function record(song, name, detail = {}) {
  state.events.push({
    at: now(),
    household: song ? song.household : state.household,
    song: song ? song.id : null,
    name,
    detail,
  });
}

function note(song, step, outcome, detail = "", provider = "code", cost = 0) {
  song.attempts.push({ step, provider, outcome, detail, cost, at: now() });
}

function spendToday() {
  return state.songs.reduce((total, song) => total + song.attempts.reduce((n, a) => n + a.cost, 0), 0);
}

function songSpend(song) {
  return song.attempts.reduce((total, attempt) => total + attempt.cost, 0);
}

function countsTowardCap(song) {
  return !(song.status === "rejected" && song.attempts.every((a) => a.provider === "code"));
}

function songsLeftToday() {
  const used = state.songs.filter((s) => s.household === state.household && countsTowardCap(s)).length;
  return Math.max(0, LIMITS.songsPerHouseholdPerDay - used);
}

function createSong(brief, household = state.household) {
  const song = {
    id: "p" + String(nextId++).padStart(4, "0"),
    household,
    brief,
    status: "draft",
    lyrics: null,
    lyricsSource: null,
    rewrites: 0,
    freshDrafts: 0,
    editChecks: 0,
    musicCalls: 0,
    roundMusicCalls: 0,
    regenerations: 0,
    attempts: [],
    refusal: [],
    failure: null,
    blocked: null,
    audio: null,
    audioSeconds: null,
    transcriptMatch: null,
    wordsApprovedBy: null,
    audioApprovedBy: null,
    createdAt: now(),
    working: false,
  };
  state.songs.push(song);
  return song;
}

function screenStep(song) {
  const findings = screenBrief(song.brief);
  note(song, "screen", findings.length ? "rejected" : "ok", findings.map((f) => `${f.code}:${f.detail}`).join(", "));
  if (findings.length) {
    song.status = "rejected";
    song.refusal = findings.map((f) => f.message);
    record(song, "brief_refused", { codes: [...new Set(findings.map((f) => f.code))].sort() });
  } else {
    song.status = "screened";
  }
}

function writeStep(song) {
  // The stand-in writer, the same one the service uses. A model would go here.
  const lyrics = writeSong(song.brief);
  note(song, "write", "ok", "", "stand-in", COST.write);
  const findings = checkLyrics(lyrics, song.brief);
  note(song, "rules", findings.length ? "rejected" : "ok", findings.map((f) => f.code).join(", "));
  if (findings.length) {
    song.rewrites += 1;
    return;
  }
  note(song, "judge", "ok", "passed", "stand-in", COST.judge);
  song.lyrics = lyrics;
  song.lyricsSource = "writer";
  song.status = "lyrics_ready";
}

function composeStep(song) {
  if (song.roundMusicCalls >= LIMITS.maxMusicCallsPerRound || song.musicCalls >= LIMITS.maxMusicCallsPerSong) {
    song.status = "failed";
    song.failure = "The music did not come out right, and this song has no tries left.";
    return;
  }
  if (spendToday() + COST.music > LIMITS.dailyBudgetUsd) {
    song.blocked = "Today's budget for making songs is used up. Please try again tomorrow.";
    return;
  }
  song.musicCalls += 1;
  song.roundMusicCalls += 1;
  note(song, "compose", "ok", "", "stand-in", COST.music);
  song.audio = audioUrl();
  song.audioSeconds = 60;
  note(song, "audio_check", "ok", "");
  note(song, "transcribe", "ok", "", "stand-in", COST.transcribe);
  song.transcriptMatch = 1;
  song.status = "audio_checked";
}

function work(song, ms, job) {
  song.working = true;
  song.blocked = null;
  render();
  window.setTimeout(() => {
    job();
    song.working = false;
    render();
  }, ms);
}

function advanceWords(song) {
  work(song, WRITE_MS, () => {
    while (song.status === "screened") {
      if (song.rewrites > LIMITS.maxRewrites) {
        const lyrics = templateLyrics(song.brief);
        note(song, "rules", "ok", "fallback");
        note(song, "judge", "ok", "passed", "stand-in", COST.judge);
        song.lyrics = lyrics;
        song.lyricsSource = "template";
        song.status = "lyrics_ready";
        break;
      }
      writeStep(song);
    }
    if (song.status === "lyrics_ready") record(song, "words_shown");
  });
}

function startSong(raw) {
  const { brief, findings } = readBrief(raw);
  if (!brief) {
    state.problems = [...new Set(findings.map((f) => f.message))];
    record(null, "brief_invalid", { codes: ["invalid_input"] });
    return;
  }
  if (songsLeftToday() <= 0) {
    state.problems = ["This household has made all of today's songs. Please try again tomorrow."];
    record(null, "limit_reached");
    return;
  }
  state.problems = [];
  const song = createSong(brief);
  record(song, "song_started", { style: brief.style, steps: brief.steps.length });
  screenStep(song);
  state.currentId = song.id;
  state.editing = false;
  state.form = emptyForm();
  if (findings.length) {
    // readBrief already screened it; screenStep repeats the same decision.
  }
  if (song.status === "screened") advanceWords(song);
  else render();
}

function approveWords(song, editedLyrics) {
  if (editedLyrics) {
    if (song.editChecks >= LIMITS.maxEditChecks) {
      state.problems = ["These words have been edited too many times. Start a new song."];
      return render();
    }
    song.editChecks += 1;
    const findings = checkLyrics(editedLyrics, song.brief);
    note(song, "rules", findings.length ? "rejected" : "ok", "edit " + findings.map((f) => f.code).join(", "));
    if (findings.length) {
      record(song, "edit_refused", { codes: [...new Set(findings.map((f) => f.code))].sort() });
      state.problems = [...new Set(findings.map((f) => f.message))];
      state.editing = true;
      return render();
    }
    note(song, "judge", "ok", "passed", "stand-in", COST.judge);
    song.lyrics = editedLyrics;
    song.lyricsSource = "parent_edit";
  }
  state.problems = [];
  state.typed = null;
  state.editing = false;
  song.wordsApprovedBy = "you";
  song.roundMusicCalls = 0;
  song.status = "approved";
  record(song, "words_approved", { edited: Boolean(editedLyrics) });
  work(song, MUSIC_MS, () => {
    composeStep(song);
    if (song.status === "audio_checked") record(song, "audio_shown");
  });
}

function redraft(song) {
  if (song.freshDrafts >= LIMITS.maxFreshDrafts) {
    state.problems = ["This song has had all its fresh drafts. You can still edit the words yourself."];
    return render();
  }
  song.freshDrafts += 1;
  song.rewrites = 0;
  song.lyrics = null;
  song.lyricsSource = null;
  song.status = "screened";
  state.problems = [];
  record(song, "fresh_draft");
  advanceWords(song);
}

function approveAudio(song, listened) {
  if (!listened) {
    state.problems = ["Tick the box to say you listened to the whole song."];
    return render();
  }
  state.problems = [];
  note(song, "preview", "ok", "approved by you");
  song.audioApprovedBy = "you";
  song.status = "published";
  record(song, "listen_approved");
  render();
}

function rejectAudio(song, tryAgain, reason) {
  note(song, "preview", "rejected", `you: ${reason}`.slice(0, 200));
  song.audio = null;
  song.audioSeconds = null;
  song.transcriptMatch = null;
  state.problems = [];
  const left = song.regenerations < LIMITS.maxRegenerations && song.musicCalls < LIMITS.maxMusicCallsPerSong;
  record(song, "listen_rejected", { try_again: Boolean(tryAgain) });
  if (tryAgain && left) {
    song.regenerations += 1;
    song.roundMusicCalls = 0;
    song.status = "approved";
    work(song, MUSIC_MS, () => {
      composeStep(song);
      if (song.status === "audio_checked") record(song, "audio_shown");
    });
  } else {
    song.status = "failed";
    song.failure = "The adult who listened did not approve this song.";
    render();
  }
}

/* ---------- what the team view shows ---------- */

function numbers() {
  const songs = state.songs;
  const published = songs.filter((s) => s.status === "published");
  const musicCalls = songs.reduce((n, s) => n + s.musicCalls, 0);
  return {
    songs: songs.length,
    published: published.length,
    waiting: songs.filter((s) => s.status === "lyrics_ready" || s.status === "audio_checked").length,
    refused: songs.filter((s) => s.status === "rejected").length,
    households: new Set(songs.map((s) => s.household)).size,
    spend: spendToday(),
    musicCalls,
    perSong: published.length ? musicCalls / published.length : null,
  };
}

function journeyCounts() {
  const here = {};
  for (const song of state.songs) here[song.status] = (here[song.status] || 0) + 1;
  return DATA.journey.map((step) => ({ ...step, here: step.waitsAt ? here[step.waitsAt] || 0 : 0 }));
}

/* ---------- drawing the page ---------- */

const app = document.getElementById("app");

function el(html) {
  const wrap = document.createElement("div");
  wrap.innerHTML = html.trim();
  return wrap.firstElementChild;
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

function money(value) {
  return "$" + value.toFixed(2);
}

function clock(date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function current() {
  return state.songs.find((song) => song.id === state.currentId) || null;
}

function problemsHtml() {
  if (!state.problems.length) return "";
  return `<div class="problem" role="alert"><p>Please change this and try again:</p><ul>${state.problems
    .map((text) => `<li>${esc(text)}</li>`)
    .join("")}</ul></div>`;
}

function railHtml(step) {
  return `<nav class="rail" aria-label="Where you are"><ol>${JOURNEY_STEPS.map((name, i) => {
    const n = i + 1;
    const cls = n < step ? "done" : n === step ? "now" : "";
    return `<li class="${cls}"><span class="pip" aria-hidden="true">${n}</span><span class="what">${esc(name)}</span></li>`;
  }).join("")}</ol></nav>`;
}

function sheetHtml(lyrics, nickname) {
  const name = nickname || NAME_FALLBACK;
  const marked = new Set();
  const sections = lyrics.sections
    .map((section) => {
      const lines = section.lines
        .map((line) => {
          const text = line.text.split(NAME_SLOT).join(name);
          const shown = text.charAt(0).toUpperCase() + text.slice(1);
          let bead = "";
          if (line.step !== null && line.step !== undefined && !marked.has(line.step)) {
            marked.add(line.step);
            bead = `<span class="bead" title="Step ${line.step + 1} of the routine">${line.step + 1}</span>`;
          }
          return `<span class="line">${bead}${esc(shown)}</span>`;
        })
        .join("");
      return `<p class="verse">${lines}</p>`;
    })
    .join("");
  return `<div class="sheet">${sections}</div>`;
}

function aboutHtml(song) {
  return `<dl class="about"><dt>Routine</dt><dd>${esc(song.brief.routine)}</dd><dt>Sound</dt><dd>${esc(
    DATA.styles[song.brief.style]
  )}</dd></dl>`;
}

function formHtml() {
  const form = state.form;
  const left = songsLeftToday();
  const steps = form.steps
    .map(
      (value, i) =>
        `<li><label class="sr" for="step-${i + 1}">Step ${i + 1}</label><input id="step-${i + 1}" name="step" value="${esc(
          value
        )}" maxlength="40" autocomplete="off"${i < 3 ? " required" : ""}></li>`
    )
    .join("");
  const styles = Object.entries(DATA.styles)
    .map(
      ([key, label]) =>
        `<label class="pick"><input type="radio" name="style" value="${key}"${
          form.style === key ? " checked" : ""
        } required> ${esc(label)}</label>`
    )
    .join("");
  const ages = ["3-4", "5-6"]
    .map(
      (band) =>
        `<label class="pick"><input type="radio" name="age_band" value="${band}"${
          form.age_band === band ? " checked" : ""
        } required> ${band === "3-4" ? "3 or 4" : "5 or 6"}</label>`
    )
    .join("");

  return `
${railHtml(1)}
<h1>What should the song be about?</h1>
<p class="lead">Name a routine and its steps. We write a short song, you check the words, then you listen before your child does.</p>
${problemsHtml()}
<div class="split">
  <div class="col-main">
  ${
    left > 0
      ? `<form id="brief-form">
    <label class="name" for="routine">Routine</label>
    <p class="hint">For example bedtime, brushing teeth or leaving the house.</p>
    <input id="routine" name="routine" value="${esc(form.routine)}" maxlength="40" required autocomplete="off">
    <fieldset>
      <legend>Steps, in the order they happen</legend>
      <p class="hint">Three to five steps, a few words each. Letters only, so write "two books", not "2 books".</p>
      <ol class="steps-in">${steps}</ol>
    </fieldset>
    <div class="two-up">
      <fieldset><legend>How should it sound?</legend>${styles}</fieldset>
      <div>
        <fieldset><legend>How old is your child?</legend>${ages}</fieldset>
        <label class="name" for="nickname">Name to sing (optional)</label>
        <p class="hint">One word. Leave it empty and we sing "little one".</p>
        <input id="nickname" name="nickname" value="${esc(form.nickname)}" maxlength="20" autocomplete="off">
      </div>
    </div>
    <button class="primary" type="submit" data-act="start">Write the words</button>
    <p class="hint">You can make ${left} more ${left === 1 ? "song" : "songs"} today.</p>
  </form>`
      : `<p class="notice">You have made all of today's songs. Come back tomorrow to make more.</p>`
  }
  </div>
  <aside class="col-side">
    <h2>What happens next</h2>
    <ol class="plan">
      <li><b>We write the words.</b> A few seconds. Nothing is sung yet.</li>
      <li><b>You check them.</b> Approve, edit any line, or ask for different words. No music is made until you say yes.</li>
      <li><b>You listen.</b> You hear the whole song first.</li>
      <li><b>Your child hears it.</b> Only after you say yes.</li>
    </ol>
    ${
      state.songs.filter((s) => s.household === state.household).length
        ? `<h2>Your songs</h2><ul class="songs">${state.songs
            .filter((s) => s.household === state.household)
            .slice()
            .reverse()
            .map(
              (song) =>
                `<li><a href="#" data-open="${song.id}">${esc(song.brief.routine)}</a> <span>${esc(
                  STATUS_LABELS[song.status]
                )}</span></li>`
            )
            .join("")}</ul>`
        : ""
    }
    <p class="hint keep">We keep the routine, an age range and the name to sing. We keep nothing else about your child.</p>
  </aside>
</div>`;
}

function songHtml(song) {
  if (song.working) {
    const writing = song.status === "screened" || song.status === "draft";
    return `${railHtml(writing ? 2 : 3)}
<h1>${writing ? "Writing the words" : "Making the music"}</h1>
<p class="lead">${
      writing
        ? "This takes a few seconds."
        : "In the real service this takes about a minute. Shortened here so you are not kept waiting."
    }</p>
<p class="working" aria-hidden="true"><span></span><span></span><span></span></p>`;
  }

  if (song.status === "rejected") {
    return `<h1>We can't make this song</h1>
<ul class="reasons">${song.refusal.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
<p class="more"><a href="#" data-go="home">Describe the routine again</a></p>`;
  }

  if (song.status === "failed") {
    return `<h1>This song did not work out</h1><p class="lead">${esc(song.failure || "")}</p>
<p class="more"><a href="#" data-go="home">Start a new song</a></p>`;
  }

  if (song.blocked) {
    return `<h1>Paused for now</h1><p class="lead">${esc(song.blocked)}</p>
<p class="more"><a href="#" data-go="home">Back</a></p>`;
  }

  if (song.status === "lyrics_ready" && state.editing) {
    const typed = state.typed || flatLines(song.lyrics).map((line) => line.text);
    let n = 0;
    const boxes = song.lyrics.sections
      .map((section) => {
        const inputs = section.lines
          .map(() => {
            const value = typed[n] ?? "";
            n += 1;
            return `<input name="line" value="${esc(value)}" maxlength="100" required autocomplete="off" aria-label="Line ${n}">`;
          })
          .join("");
        return `<fieldset>${inputs}</fieldset>`;
      })
      .join("");
    return `${railHtml(2)}
<h1>Change the words</h1>
<p class="lead">Edit any line. We check your changes the same way we check our own words.</p>
${problemsHtml()}
<div class="split">
  <div class="col-main">
    <form id="edit-form" class="edit">${boxes}
      <button class="primary" type="submit" data-act="save-edit">Save my changes and make the song</button>
    </form>
    <p class="more"><a href="#" data-go="words">Leave the words as they were</a></p>
  </div>
  <aside class="col-side">
    <h2>Keep to these</h2>
    <ul class="plan">
      <li>{name} is where the name is sung.</li>
      <li>At most ${MAX_LINE_WORDS} words in a line.</li>
      <li>Both choruses have to match word for word.</li>
      <li>Every step of your routine still has to be sung, in order.</li>
    </ul>
    ${aboutHtml(song)}
  </aside>
</div>`;
  }

  if (song.status === "lyrics_ready") {
    const fresh = LIMITS.maxFreshDrafts - song.freshDrafts;
    return `${railHtml(2)}
<h1>Do these words sound right?</h1>
<p class="lead">No music is made until you say yes.</p>
${problemsHtml()}
<div class="split">
  <div class="col-main">${sheetHtml(song.lyrics, song.brief.nickname)}</div>
  <aside class="col-side">
    ${song.lyricsSource === "template" ? '<p class="hint">This is our simple counting song with your steps in it.</p>' : ""}
    <button class="primary" data-act="approve-words">Yes, make the song</button>
    <p class="more"><a href="#" data-go="edit">Change the words myself</a></p>
    ${fresh > 0 ? `<button class="plain" data-act="redraft">Write different words (${fresh} left)</button>` : ""}
    <p class="hint">The numbers show where each step of your routine is sung.</p>
    ${aboutHtml(song)}
  </aside>
</div>`;
  }

  const ready = song.status === "published";
  return `${railHtml(ready ? 4 : 3)}
<h1>${ready ? "Ready to play" : "Listen before your child does"}</h1>
<p class="lead">${
    ready
      ? "You checked the words and you listened. Play it when the routine starts."
      : "Play the whole song. If anything sounds wrong, say no."
  }</p>
<div class="split">
  <div class="col-main">
    <audio controls preload="metadata" src="${song.audio}"></audio>
    <p class="hint stand-in">This is the 60 second test tone the service makes until a music key is set. It is not the song.</p>
    ${sheetHtml(song.lyrics, song.brief.nickname)}
  </div>
  <aside class="col-side">
    ${
      ready
        ? `<p class="done-note">Approved by you. Your child can hear this song.</p>
           <p class="more"><a href="#" data-go="home">Make another song</a></p>`
        : `${problemsHtml()}
           <label class="pick"><input type="checkbox" id="listened"> I listened to the whole song</label>
           <button class="primary" data-act="approve-audio">Yes, my child can hear this</button>
           <label class="name" for="reason">If not, what was wrong? (optional)</label>
           <input id="reason" maxlength="200" autocomplete="off">
           ${
             song.regenerations < LIMITS.maxRegenerations && song.musicCalls < LIMITS.maxMusicCallsPerSong
               ? '<button class="plain" data-act="retry-audio">No, make the music again</button>'
               : ""
           }
           <button class="plain" data-act="reject-audio">No, do not use this song</button>`
    }
    ${aboutHtml(song)}
  </aside>
</div>`;
}

function liveHtml() {
  const n = numbers();
  const rows = state.songs
    .slice()
    .reverse()
    .map(
      (song) => `<tr>
    <td><a href="#" data-open="${song.id}">${esc(song.brief.routine)}</a></td>
    <td class="code">${esc(song.household)}</td>
    <td><span class="pill ${song.status === "published" ? "good" : song.status === "rejected" || song.status === "failed" ? "stop" : ""}">${esc(
        STATUS_LABELS[song.status]
      )}</span></td>
    <td>${esc(WORDS_FROM[song.lyricsSource] || "—")}${song.rewrites ? `, ${song.rewrites} rewrites` : ""}</td>
    <td class="num-col">${song.musicCalls}</td>
    <td class="num-col">$${songSpend(song).toFixed(3)}</td>
    <td class="when">${clock(song.createdAt)}</td>
  </tr>`
    )
    .join("");
  const events = state.events
    .slice(-60)
    .reverse()
    .map(
      (event) => `<tr><td class="when">${clock(event.at)}</td><td class="code">${esc(event.household)}</td>
    <td>${esc(event.name.replace(/_/g, " "))}</td>
    <td class="quiet">${esc(
      Object.entries(event.detail)
        .sort()
        .map(([k, v]) => `${k}: ${typeof v === "boolean" ? (v ? "yes" : "no") : v}`)
        .join(", ")
    )}</td></tr>`
    )
    .join("");

  return `<h1>What happened</h1>
<p class="lead">Every song this service has been asked for, and every step it took.</p>
<div class="tiles">
  <div class="tile"><b>${n.songs}</b><span>songs asked for</span></div>
  <div class="tile"><b>${n.published}</b><span>finished and approved</span></div>
  <div class="tile"><b>${n.waiting}</b><span>waiting for a person</span></div>
  <div class="tile"><b>${n.refused}</b><span>refused by the checks</span></div>
  <div class="tile"><b>${money(n.spend)}</b><span>spent, of ${money(LIMITS.dailyBudgetUsd)} a day</span></div>
  <div class="tile"><b>${n.perSong === null ? "—" : n.perSong.toFixed(2)}</b><span>music calls per finished song</span></div>
</div>
<h2>Where the songs are now</h2>
<ol class="journey tight">${journeyCounts()
    .map(
      (step) => `<li class="${step.isPerson ? "person" : ""}"><span class="num">${step.number}</span>
  <span class="what"><b>${esc(step.name)}</b><span class="who">${esc(step.who)}</span></span>
  <span class="count">${step.here ? step.here + " here" : "—"}</span></li>`
    )
    .join("")}</ol>
<h2>Songs</h2>
${
  state.songs.length
    ? `<div class="scroll"><table><thead><tr><th>Routine</th><th>Household</th><th>Where it got to</th><th>Words</th><th class="num-col">Music calls</th><th class="num-col">Cost</th><th>Started</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<p class="notice">No songs yet. Make one on the parent side and it appears here.</p>'
}
<h2>What parents did</h2>
${
  state.events.length
    ? `<div class="scroll"><table><thead><tr><th>Time</th><th>Household</th><th>What happened</th><th>Detail</th></tr></thead><tbody>${events}</tbody></table></div>
<p class="hint">The log records which step happened and when. It never holds what a parent typed.</p>`
    : '<p class="notice">Nothing logged yet.</p>'
}`;
}

function howHtml() {
  const worst = LIMITS.maxMusicCallsPerSong * LIMITS.musicPricePerMinuteUsd;
  return `<h1>How it works</h1>
<p class="lead">A parent types a routine and gets a short song for a child aged 3 to 6. Eight steps stand between those two things. Two of them wait for a person, and nothing can skip them.</p>
<h2>The eight steps</h2>
<ol class="journey">${DATA.journey
    .map(
      (step) => `<li class="${step.isPerson ? "person" : ""}"><span class="num">${step.number}</span>
  <span class="what"><b>${esc(step.name)}</b><span class="who">${esc(step.who)}</span>
  <span class="does">${esc(step.does)}</span>
  <span class="guard"><b>Refuses:</b> ${esc(step.guard)}</span></span></li>`
    )
    .join("")}</ol>
<h2>Rules that do not bend</h2>
<dl class="rules">${DATA.guardrails.map(([name, why]) => `<dt>${esc(name)}</dt><dd>${esc(why)}</dd>`).join("")}</dl>
<h2>The caps</h2>
<div class="scroll"><table><thead><tr><th>Cap</th><th class="num-col">Now</th></tr></thead><tbody>
<tr><td>Rewrites of a draft before we use words a person wrote</td><td class="num-col">${LIMITS.maxRewrites}</td></tr>
<tr><td>Fresh drafts a parent may ask for</td><td class="num-col">${LIMITS.maxFreshDrafts}</td></tr>
<tr><td>Music calls per song, including retries</td><td class="num-col">${LIMITS.maxMusicCallsPerSong}</td></tr>
<tr><td>Extra versions an adult may ask for after listening</td><td class="num-col">${LIMITS.maxRegenerations}</td></tr>
<tr><td>Songs per household per day</td><td class="num-col">${LIMITS.songsPerHouseholdPerDay}</td></tr>
<tr><td>Spending per day, everyone together</td><td class="num-col">${money(LIMITS.dailyBudgetUsd)}</td></tr>
<tr><td>Worst case for one song, at ${money(LIMITS.musicPricePerMinuteUsd)} a minute</td><td class="num-col">${money(worst)}</td></tr>
</tbody></table></div>
<h2>What the checks cover</h2>
<p>The free layer runs first and never calls a model: <b>${DATA.checks.unsafe_words}</b> unsafe words and phrases, <b>${
    DATA.checks.brand_names
  }</b> artist and character names, and the shape of the song itself, which has to be ${DATA.checks.min_words} to ${
    DATA.checks.max_words
  } words with at most ${DATA.checks.max_line_words} words in a line. A parent picks one of <b>${
    DATA.checks.styles
  }</b> styles; there is no free-text style anywhere.</p>
<p>Against ${DATA.redteam.total} hostile prompts written to break it, this layer stops <b>${
    DATA.redteam.stopped
  }</b>. The other ${DATA.redteam.for_judge} need judgement that a word list cannot do, such as an unsafe instruction in ordinary words or a routine written in another language. Those are the model judge's job.</p>
<h2>What we chose, and what it costs us</h2>
<dl class="rules">${DATA.decisions
    .map(([name, what, why]) => `<dt>${esc(name)}</dt><dd>${esc(what)} <span class="quiet">${esc(why)}</span></dd>`)
    .join("")}</dl>
<h2>Not built yet</h2>
<ul class="plan">${DATA.gaps.map((gap) => `<li>${esc(gap)}</li>`).join("")}</ul>`;
}

function render() {
  const parent = state.view === "parent";
  document.body.classList.toggle("studio", !parent);
  document.getElementById("tab-parent").setAttribute("aria-current", parent ? "page" : "false");
  document.getElementById("tab-team").setAttribute("aria-current", parent ? "false" : "page");

  if (parent) {
    const song = current();
    app.innerHTML = song ? songHtml(song) : formHtml();
  } else {
    const live = state.teamTab === "live";
    app.innerHTML = `<nav class="tabs" aria-label="Team view">
      <a href="#" data-team="live"${live ? ' aria-current="page"' : ""}>What happened</a>
      <a href="#" data-team="how"${!live ? ' aria-current="page"' : ""}>How it works</a>
    </nav>${live ? liveHtml() : howHtml()}`;
  }
}

/* ---------- what a click does ---------- */

function readForm() {
  const steps = [...app.querySelectorAll('input[name="step"]')].map((input) => input.value);
  const picked = (name) => {
    const chosen = app.querySelector(`input[name="${name}"]:checked`);
    return chosen ? chosen.value : "";
  };
  return {
    routine: app.querySelector("#routine").value,
    steps,
    style: picked("style"),
    age_band: picked("age_band"),
    nickname: app.querySelector("#nickname").value,
  };
}

function startFromForm() {
  const raw = readForm();
  state.form = { ...raw, steps: raw.steps.concat(["", "", "", "", ""]).slice(0, 5) };
  startSong(raw);
}

function saveEdit(song) {
  const typed = [...app.querySelectorAll('input[name="line"]')].map((input) => input.value);
  state.typed = typed;
  const lines = flatLines(song.lyrics);
  if (typed.length !== lines.length) return;
  let n = 0;
  const edited = {
    title: song.lyrics.title,
    sections: song.lyrics.sections.map((section) => ({
      name: section.name,
      lines: section.lines.map((line) => ({
        text: typed[n++].split(/\s+/).filter(Boolean).join(" "),
        step: line.step,
      })),
    })),
  };
  if (edited.sections.some((s) => s.lines.some((l) => !l.text))) {
    state.problems = ["Each line needs some words."];
    return render();
  }
  const same = JSON.stringify(edited) === JSON.stringify(song.lyrics);
  approveWords(song, same ? null : edited);
}

/* This page can run inside a frame whose sandbox does not allow form submission, and there a
   submit event never fires at all, so a page that waited for one did nothing when the button
   was pressed. Every action is driven by the click handler below instead, which works in any
   sandbox. This listener is only for the Enter key where forms are allowed; a click cannot
   reach it, because the click handler calls preventDefault before the form would submit. */
document.addEventListener("submit", (event) => {
  event.preventDefault();
  const song = current();
  if (event.target.id === "brief-form") startFromForm();
  else if (event.target.id === "edit-form" && song) saveEdit(song);
});

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-act], [data-go], [data-open], [data-team], [data-view]");
  if (!target) return;
  event.preventDefault();
  const song = current();

  if (target.dataset.view) {
    state.view = target.dataset.view;
    return render();
  }
  if (target.dataset.team) {
    state.teamTab = target.dataset.team;
    return render();
  }
  if (target.dataset.open) {
    state.view = "parent";
    state.currentId = target.dataset.open;
    state.editing = false;
    state.problems = [];
    state.typed = null;
    return render();
  }
  if (target.dataset.go === "home") {
    state.currentId = null;
    state.editing = false;
    state.problems = [];
    return render();
  }
  if (target.dataset.act === "start") return startFromForm();
  if (!song) return;
  if (target.dataset.act === "save-edit") return saveEdit(song);
  if (target.dataset.go === "edit") {
    state.editing = true;
    state.typed = null;
    state.problems = [];
    return render();
  }
  if (target.dataset.go === "words") {
    state.editing = false;
    state.typed = null;
    state.problems = [];
    return render();
  }
  const act = target.dataset.act;
  if (act === "approve-words") approveWords(song, null);
  else if (act === "redraft") redraft(song);
  else if (act === "approve-audio") approveAudio(song, app.querySelector("#listened").checked);
  else if (act === "retry-audio") rejectAudio(song, true, app.querySelector("#reason").value);
  else if (act === "reject-audio") rejectAudio(song, false, app.querySelector("#reason").value);
});

/* ---------- the forced cases, so the page is not empty on arrival ---------- */

const SEED = [
  { household: "demo-ferrara", routine: "bedtime", steps: ["brush teeth", "put on pajamas", "read one book", "lights out"], style: "gentle_lullaby", age: "3-4", nickname: "Mina", end: "published", minutesAgo: 180 },
  { household: "demo-ferrara", routine: "brushing teeth", steps: ["wet the brush", "tiny bit of toothpaste", "brush every tooth", "spit and rinse"], style: "silly_bounce", age: "5-6", nickname: "Mina", end: "published", edit: [4, "First we wet the brush"], refusedEdit: [0, "Here we go, it's brushing time"], minutesAgo: 150 },
  { household: "demo-okonkwo", routine: "tidy-up time", steps: ["blocks in the box", "books on the shelf", "cars in the bin"], style: "clap_along_march", age: "3-4", end: "published", extraCall: true, minutesAgo: 120 },
  { household: "demo-okonkwo", routine: "bath time", steps: ["climb in the tub", "wash your hair", "rinse the bubbles", "dry off"], style: "calm_piano", age: "3-4", nickname: "Tobi", end: "published", retried: true, minutesAgo: 90 },
  { household: "demo-lindqvist", routine: "getting ready for school", steps: ["make the bed", "brush your hair", "pack your bag", "shoes on"], style: "clap_along_march", age: "5-6", end: "audio_checked", fallback: true, minutesAgo: 40 },
  { household: "demo-lindqvist", routine: "leaving the house", steps: ["shoes on", "coat on", "hold my hand"], style: "bouncy_ukulele", age: "3-4", nickname: "Elin", end: "audio_checked", minutesAgo: 20 },
  { household: "demo-ferrara", routine: "snack time", steps: ["wash your hands", "sit at the table", "eat your apple"], style: "bouncy_ukulele", age: "3-4", nickname: "Mina", end: "lyrics_ready", minutesAgo: 8 },
  { household: "demo-okonkwo", routine: "bedtime", steps: ["sing baby shark", "brush teeth", "lights out"], style: "silly_bounce", age: "3-4", end: "rejected", minutesAgo: 5 },
];

function seed() {
  for (const row of SEED) {
    const at = new Date(Date.now() - row.minutesAgo * 60000);
    const { brief } = readBrief({
      routine: row.routine,
      steps: row.steps,
      style: row.style,
      age_band: row.age,
      nickname: row.nickname,
    });
    if (!brief) continue;
    const song = createSong(brief, row.household);
    song.createdAt = at;
    const stamp = () => song.attempts.forEach((a) => (a.at = at));
    record(song, "song_started", { style: row.style, steps: row.steps.length });
    state.events.at(-1).at = at;
    screenStep(song);
    stamp();
    if (song.status === "rejected") {
      state.events.at(-1).at = at;
      continue;
    }

    if (row.fallback) {
      song.rewrites = 3;
      for (let i = 0; i < 3; i++) {
        note(song, "write", "ok", "", "stand-in", COST.write);
        note(song, "rules", "rejected", "line_too_long");
      }
      note(song, "rules", "ok", "fallback");
      note(song, "judge", "ok", "passed", "stand-in", COST.judge);
      song.lyrics = templateLyrics(brief);
      song.lyricsSource = "template";
      song.status = "lyrics_ready";
    } else {
      writeStep(song);
    }
    record(song, "words_shown");
    stamp();
    state.events.at(-1).at = at;
    if (row.end === "lyrics_ready") continue;

    if (row.refusedEdit) {
      note(song, "rules", "rejected", "edit chorus_changes");
      record(song, "edit_refused", { codes: ["chorus_changes"] });
      state.events.at(-1).at = at;
    }
    let edited = null;
    if (row.edit) {
      const lines = flatLines(song.lyrics);
      let n = 0;
      edited = {
        title: song.lyrics.title,
        sections: song.lyrics.sections.map((section) => ({
          name: section.name,
          lines: section.lines.map((line) => {
            const text = n === row.edit[0] ? row.edit[1] : line.text;
            n += 1;
            return { text, step: line.step };
          }),
        })),
      };
      if (checkLyrics(edited, brief).length) edited = null;
      else {
        note(song, "rules", "ok", "edit");
        note(song, "judge", "ok", "passed", "stand-in", COST.judge);
        song.lyrics = edited;
        song.lyricsSource = "parent_edit";
      }
    }
    song.wordsApprovedBy = "a parent";
    song.status = "approved";
    record(song, "words_approved", { edited: Boolean(edited) });
    state.events.at(-1).at = at;

    if (row.extraCall) {
      song.musicCalls += 1;
      note(song, "compose", "ok", "came back silent", "stand-in", COST.music);
      note(song, "audio_check", "rejected", "too_quiet");
    }
    song.roundMusicCalls = 0;
    composeStep(song);
    record(song, "audio_shown");
    state.events.at(-1).at = at;

    if (row.retried) {
      note(song, "preview", "rejected", "a parent: the singing was too fast");
      record(song, "listen_rejected", { try_again: true });
      state.events.at(-1).at = at;
      song.regenerations = 1;
      song.roundMusicCalls = 0;
      composeStep(song);
      record(song, "audio_shown");
      state.events.at(-1).at = at;
    }
    stamp();
    if (row.end !== "published") continue;
    note(song, "preview", "ok", "approved by a parent");
    song.audioApprovedBy = "a parent";
    song.status = "published";
    record(song, "listen_approved");
    state.events.at(-1).at = at;
    stamp();
  }
}

seed();
render();
