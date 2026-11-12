"""Command line for the pipeline.

Everything here runs on the fake providers, so it is free, offline and safe to run anywhere.
The audio it writes is a test tone, not music.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mm import __version__
from mm.audio import WavInspector
from mm.controls import EnvControls, StaticControls
from mm.domain import SongStatus
from mm.fakes import FakeJudge, FakeMusic, FakeTranscriber, FakeWriter
from mm.pipeline import LimitReached, Limits, Pipeline
from mm.ports import Controls, SongStore
from mm.safety import rules
from mm.store import InMemoryStore, JsonDirStore

GOLDEN = Path("evals/datasets/briefs.golden.jsonl")
REDTEAM = Path("evals/datasets/redteam.jsonl")
FAKE_NOTE = "Providers: fake. This checks the plumbing, not how good or safe a real song is."


def _fake_pipeline(store: SongStore, controls: Controls, limits: Limits | None = None) -> Pipeline:
    music = FakeMusic()
    return Pipeline(
        store=store,
        writer=FakeWriter(),
        judge=FakeJudge(),
        music=music,
        transcriber=FakeTranscriber(music),
        inspector=WavInspector(),
        controls=controls,
        limits=limits,
    )


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _generate(args: argparse.Namespace) -> int:
    brief, findings = rules.screen_raw(_read_json(args.brief))
    if brief is None:
        print("This brief cannot be used:")
        for finding in findings:
            print(f"  - {finding.detail}: {finding.message}")
        return 2
    pipeline = _fake_pipeline(JsonDirStore(args.out), EnvControls())
    try:
        song = pipeline.create(brief, args.household)
    except (LimitReached, ValueError) as err:
        print(err)
        return 1
    song = pipeline.advance(song.id)
    if song.status is SongStatus.REJECTED:
        print("We will not make this song:")
        for reason in song.refusal:
            print(f"  - {reason}")
        return 1
    if song.status is not SongStatus.LYRICS_READY or song.lyrics is None:
        print(song.blocked or song.failure or f"Stopped at {song.status.value}.")
        return 1

    print(f"Words (from the {song.lyrics_source}, {song.lyrics.word_count()} words):\n")
    print(song.lyrics.render(brief.nickname))
    print()
    if not args.yes:
        print("Stopped here: a parent has to approve these words before any music is made.")
        print("To approve both human steps yourself for a local test, run again with --yes.")
        return 0

    pipeline.approve_lyrics(song.id, by="local-test")
    song = pipeline.advance(song.id)
    if song.status is not SongStatus.AUDIO_CHECKED:
        print(song.blocked or song.failure or f"Stopped at {song.status.value}.")
        return 1
    song = pipeline.adult_approve(song.id, by="local-test")
    print(f"Published song {song.id} (both human steps approved by you, for a local test).")
    print(f"  audio: {args.out / str(song.audio_path)} ({song.audio_seconds:.0f} seconds)")
    print(f"  record: {args.out / 'songs' / (song.id + '.json')}")
    print(f"  music calls: {song.music_calls}, pretend cost: ${song.spend_usd():.2f}")
    print(f"  words heard in the audio: {song.transcript_match:.0%}")
    print(FAKE_NOTE + " The audio is a test tone.")
    return 0


def _screen(args: argparse.Namespace) -> int:
    _, findings = rules.screen_raw(_read_json(args.brief))
    if not findings:
        print("This brief passes the input checks and the word lists.")
        return 0
    print("This brief is refused:")
    for finding in findings:
        print(f"  - [{finding.code}] {finding.message}")
    return 1


def _redteam(args: argparse.Namespace) -> int:
    rows = _read_jsonl(args.data)
    stopped: list[str] = []
    leaked: list[str] = []
    waiting: list[str] = []
    mislabelled: list[str] = []
    for row in rows:
        _, findings = rules.screen_raw(row["brief"])
        if row["layer"] == "judge":
            (mislabelled if findings else waiting).append(row["id"])
        else:
            (stopped if findings else leaked).append(row["id"])

    print(f"Red-team prompts: {len(rows)}")
    print(f"  stopped by input checks and word lists: {len(stopped)} of {len(stopped + leaked)}")
    if leaked:
        print(f"  GOT THROUGH: {', '.join(leaked)}")
    if mislabelled:
        print(f"  marked for the judge but stopped earlier (fix the label): {mislabelled}")
    print(f"  need the model judge, which is not built yet: {len(waiting)} (NOT covered)")
    return 1 if leaked or mislabelled else 0


def _eval(args: argparse.Namespace) -> int:
    rows = _read_jsonl(args.data)
    limits = Limits(daily_budget_usd=args.budget)
    pipeline = _fake_pipeline(InMemoryStore(), StaticControls(), limits)
    refused: list[str] = []
    stuck: list[str] = []
    first_time = fallback = published = music_calls = 0
    for row in rows:
        brief, findings = rules.screen_raw(row["brief"])
        if brief is None or findings:
            refused.append(row["id"])
            continue
        song = pipeline.advance(pipeline.create(brief, f"eval-{row['id']}").id)
        if song.status is not SongStatus.LYRICS_READY:
            stuck.append(f"{row['id']} ({song.status.value})")
            continue
        first_time += song.lyrics_source == "writer" and song.rewrites == 0
        fallback += song.lyrics_source == "template"
        pipeline.approve_lyrics(song.id, by="eval")
        song = pipeline.advance(song.id)
        if song.status is not SongStatus.AUDIO_CHECKED:
            stuck.append(f"{row['id']} ({song.blocked or song.failure or song.status.value})")
            continue
        song = pipeline.adult_approve(song.id, by="eval")
        published += 1
        music_calls += song.music_calls

    total = len(rows)
    print(f"Golden briefs: {total}")
    print(f"  passed the input checks and word lists: {total - len(refused)} of {total}")
    if refused:
        print(f"  WRONGLY REFUSED: {', '.join(refused)}")
    print(f"  words accepted on the first draft: {first_time}")
    print(f"  fell back to the words a person wrote: {fallback}")
    print(f"  reached a finished song: {published} of {total}")
    if stuck:
        print(f"  DID NOT FINISH: {', '.join(stuck)}")
    if published:
        print(f"  music calls per finished song: {music_calls / published:.2f}")
    print(FAKE_NOTE)
    return 1 if refused or stuck else 0


def build_site(data: Path, codes: list[str], team: list[str] | None = None) -> Any:
    """The web app on fake providers, saving songs and the event log under `data`."""
    from mm.web import create_app
    from mm.web.access import Allowlist
    from mm.web.events import JsonlEvents
    from mm.web.runner import ThreadRunner

    pipeline = _fake_pipeline(JsonDirStore(data), EnvControls())
    return create_app(
        pipeline=pipeline,
        participants=Allowlist(codes),
        events=JsonlEvents(data / "events.jsonl"),
        runner=ThreadRunner(pipeline),
        team=Allowlist(team or []),
    )


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn

        from mm.web.access import new_code
    except ImportError:
        print('The web page needs extra packages. Install them with: pip install -e ".[web]"')
        return 2
    where = f"http://{args.host}:{args.port}"
    from_env = os.environ.get("PARTICIPANT_CODES", "")
    codes = [code.strip() for code in [*args.code, *from_env.split(",")] if code.strip()]
    made_here = not codes
    if made_here:
        codes = [new_code()]
    team = [code.strip() for code in args.team_code if code.strip()] or [new_code()]

    print()
    if made_here:
        # On a machine of your own this is the whole setup. On a hosted service, pass --code
        # instead: anything printed here would land in that service's logs.
        print("A parent opens this (it works on a phone, a tablet or a laptop):")
        print(f"  {where}/h/{codes[0]}")
    else:
        print(f"{len(codes)} participant code(s) loaded. Their links are not printed here.")
    print()
    print("The team watches this. It shows every song, every step and every decision:")
    print(f"  {where}/studio/{team[0]}")
    print()
    print("Each link is a password. Anyone who has one can use it. Stop the server with Ctrl-C.")
    print(FAKE_NOTE + " The audio is a test tone, not music.")
    print()

    app = build_site(args.data, codes, team)
    # The access log is off because every address contains a code.
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    return 0


def _demo(args: argparse.Namespace) -> int:
    """Fill a folder with forced test cases, then serve them. No keys, no setup."""
    import shutil

    from mm.demo import CASES, Clock, seed
    from mm.web.access import new_code
    from mm.web.events import JsonlEvents

    if args.data.exists() and not args.keep:
        shutil.rmtree(args.data)
    clock = Clock()  # shared, so the event log and the songs agree about when things happened
    store = JsonDirStore(args.data)
    events = JsonlEvents(args.data / "events.jsonl", clock)
    songs = seed(store, events, clock=clock)

    print()
    print(f"Seeded {len(songs)} songs, each run through the real eight steps:")
    for case, song in zip(CASES, songs, strict=True):
        print(f"  {song.status.value:<13} {case.shows}")

    codes = sorted({song.household_id for song in songs})
    team = args.team_code or new_code()
    where = f"http://{args.host}:{args.port}"
    print()
    print("Open a family's pages:")
    for code in codes:
        print(f"  {where}/h/{code}")
    print()
    print("Open the team view, which shows all of them at once:")
    print(f"  {where}/studio/{team}")
    print()
    print(FAKE_NOTE + " The audio is a test tone, not music.")
    print("Stop the server with Ctrl-C.")
    print()

    try:
        import uvicorn
    except ImportError:
        print('The web page needs extra packages. Install them with: pip install -e ".[web]"')
        return 2
    app = build_site(args.data, codes, [team])
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)
    return 0


def _codes(args: argparse.Namespace) -> int:
    from mm.web.access import new_code

    for _ in range(args.count):
        code = new_code()
        print(f"{args.base_url.rstrip('/')}/h/{code}" if args.base_url else code)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mm", description="Musical Memory pipeline tools. Fake providers only: free, offline."
    )
    parser.add_argument("--version", action="version", version=f"mm {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="run one brief through the whole pipeline")
    generate.add_argument("brief", type=Path, help="a JSON file with one brief")
    generate.add_argument("--out", type=Path, default=Path("out"), help="where to save the song")
    generate.add_argument("--household", default="local-test", help="participant code")
    generate.add_argument(
        "--yes", action="store_true", help="approve both human steps yourself (local tests only)"
    )
    generate.set_defaults(run=_generate)

    screen = commands.add_parser("screen", help="check one brief without making anything")
    screen.add_argument("brief", type=Path, help="a JSON file with one brief")
    screen.set_defaults(run=_screen)

    redteam = commands.add_parser("redteam", help="run the hostile prompts against the checks")
    redteam.add_argument("--data", type=Path, default=REDTEAM)
    redteam.set_defaults(run=_redteam)

    evaluate = commands.add_parser("eval", help="run the golden briefs through the pipeline")
    evaluate.add_argument("--data", type=Path, default=GOLDEN)
    evaluate.add_argument("--budget", type=float, default=10.0, help="pretend dollars for the run")
    evaluate.set_defaults(run=_eval)

    serve = commands.add_parser("serve", help="run the web page for parents on this machine")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--data", type=Path, default=Path("data"), help="where songs are saved")
    serve.add_argument("--code", action="append", default=[], help="a participant code to accept")
    serve.add_argument(
        "--team-code", action="append", default=[], help="a code that opens the team view"
    )
    serve.set_defaults(run=_serve)

    demo = commands.add_parser(
        "demo", help="seed forced test cases and serve them, to see the whole product"
    )
    demo.add_argument("--host", default="127.0.0.1")
    demo.add_argument("--port", type=int, default=8000)
    demo.add_argument("--data", type=Path, default=Path("demo-data"))
    demo.add_argument("--team-code", default="", help="a code that opens the team view")
    demo.add_argument("--keep", action="store_true", help="add to what is there, do not wipe it")
    demo.set_defaults(run=_demo)

    codes = commands.add_parser("codes", help="make new participant codes")
    codes.add_argument("--count", type=int, default=1)
    codes.add_argument("--base-url", default="", help="print whole links for this site instead")
    codes.set_defaults(run=_codes)

    args = parser.parse_args(argv)
    run: Callable[[argparse.Namespace], int] = args.run
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
