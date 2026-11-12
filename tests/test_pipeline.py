"""The pipeline's promises, each as one test.

Read these as the contract: what must always be true however the providers behave.
"""

from __future__ import annotations

import pytest

from conftest import Rig
from mm.domain import Brief, SongStatus
from mm.fakes import Crash
from mm.pipeline import (
    MUSIC_FAILED,
    OVER_BUDGET,
    PAUSED,
    Blocked,
    LimitReached,
    Limits,
    LyricsNotAccepted,
    WrongState,
)

HOUSE = "house-a"


def to_words(rig: Rig, brief: Brief, house: str = HOUSE):
    """Create a song and run it until it waits for a parent (or stops)."""
    return rig.pipeline.advance(rig.pipeline.create(brief, house).id)


def to_preview(rig: Rig, brief: Brief, house: str = HOUSE):
    """Run a song until it waits for an adult to listen (or stops)."""
    song = to_words(rig, brief, house)
    rig.pipeline.approve_lyrics(song.id, by="parent")
    return rig.pipeline.advance(song.id)


# ---- the two human gates --------------------------------------------------------------------


def test_a_song_stops_for_a_parent_then_for_an_adult_listener(rig, brief):
    song = to_words(rig, brief)
    assert song.status is SongStatus.LYRICS_READY
    assert rig.music.calls == 0, "no music may be made before a parent approves the words"

    rig.pipeline.approve_lyrics(song.id, by="parent")
    song = rig.pipeline.advance(song.id)
    assert song.status is SongStatus.AUDIO_CHECKED
    assert song.published_at is None, "nothing is published before an adult has listened"

    song = rig.pipeline.adult_approve(song.id, by="parent")
    assert song.status is SongStatus.PUBLISHED
    assert song.lyrics_approved_by == "parent" and song.audio_approved_by == "parent"
    assert rig.music.calls == 1
    assert song.audio_seconds == pytest.approx(60, abs=0.1)
    assert song.transcript_match == 1.0


def test_running_a_waiting_song_again_does_nothing_and_costs_nothing(rig, brief):
    song = to_words(rig, brief)
    before = rig.paid_calls()
    assert rig.pipeline.advance(song.id).status is SongStatus.LYRICS_READY
    assert rig.paid_calls() == before

    song = to_preview(Rig(), brief)
    assert song.status is SongStatus.AUDIO_CHECKED


def test_running_a_song_at_the_listening_step_again_makes_no_second_song(rig, brief):
    song = to_preview(rig, brief)
    before = rig.paid_calls()
    assert rig.pipeline.advance(song.id).status is SongStatus.AUDIO_CHECKED
    assert rig.pipeline.advance(song.id).status is SongStatus.AUDIO_CHECKED
    assert rig.paid_calls() == before


def test_neither_gate_can_be_skipped(rig, brief):
    song = to_words(rig, brief)
    with pytest.raises(WrongState):
        rig.pipeline.adult_approve(song.id, by="parent")  # words not approved, no audio yet
    assert rig.store.get(song.id).status is SongStatus.LYRICS_READY

    song = to_preview(rig, brief, "house-b")
    with pytest.raises(WrongState):
        rig.pipeline.approve_lyrics(song.id, by="parent")  # already past that step
    rig.pipeline.adult_approve(song.id, by="parent")
    with pytest.raises(WrongState):
        rig.pipeline.adult_approve(song.id, by="parent")  # cannot publish twice


def test_an_approval_must_name_a_person(rig, brief):
    song = to_words(rig, brief)
    with pytest.raises(ValueError):
        rig.pipeline.approve_lyrics(song.id, by="")


# ---- refusing and rewriting -----------------------------------------------------------------


def test_a_refused_brief_never_reaches_a_provider(rig):
    bad = Brief(
        routine="bedtime",
        steps=["hit your brother", "say sorry", "go to bed"],
        style="gentle_lullaby",
        age_band="5-6",
    )
    song = to_words(rig, bad)
    assert song.status is SongStatus.REJECTED
    assert song.refusal and "hit" not in " ".join(song.refusal).lower().split()
    assert rig.paid_calls() == 0
    assert rig.pipeline.advance(song.id).status is SongStatus.REJECTED  # and it stays refused


def test_a_draft_that_breaks_a_rule_is_sent_back_with_the_reason(brief):
    rig = Rig(writer=("long_line",))
    song = to_words(rig, brief)
    assert song.status is SongStatus.LYRICS_READY
    assert song.lyrics_source == "writer" and song.rewrites == 1
    assert len(rig.writer.calls) == 2
    first_feedback, second_feedback = rig.writer.calls[0][1], rig.writer.calls[1][1]
    assert first_feedback == ()
    assert any("words" in reason for reason in second_feedback)
    assert len(rig.judge.calls) == 1, "the judge only sees drafts that passed the rules"


def test_a_draft_the_judge_rejects_is_rewritten(brief):
    rig = Rig(judge=("unsafe",))
    song = to_words(rig, brief)
    assert song.status is SongStatus.LYRICS_READY and song.rewrites == 1
    assert rig.writer.calls[1][1] == ("Fake judge: not safe for this age.",)


@pytest.mark.parametrize("bad", ["long_line", "missing_step", "unsafe", "error"])
def test_after_three_bad_drafts_the_words_a_person_wrote_are_used(brief, bad):
    rig = Rig(writer=(bad,) * 3)
    song = to_words(rig, brief)
    assert song.status is SongStatus.LYRICS_READY
    assert song.lyrics_source == "template"
    assert len(rig.writer.calls) == 3, "one draft and two rewrites, then no more"
    assert len(rig.judge.calls) == 1, "the fallback words are judged too"


def test_if_the_judge_rejects_even_the_fallback_the_song_is_refused(brief):
    rig = Rig(writer=("long_line",) * 3, judge=("unsafe",))
    song = to_words(rig, brief)
    assert song.status is SongStatus.REJECTED
    assert song.lyrics is None and rig.music.calls == 0


def test_if_the_judge_cannot_be_reached_nothing_goes_forward(brief):
    rig = Rig(judge=("error", "error"))
    song = to_words(rig, brief)
    assert song.status is SongStatus.FAILED
    assert song.lyrics is None, "words that were never judged are not kept"
    assert len(rig.judge.calls) == 2, "one retry, then stop"


def test_one_judge_hiccup_is_retried(brief):
    rig = Rig(judge=("error",))
    assert to_words(rig, brief).status is SongStatus.LYRICS_READY


# ---- a parent's own edits and fresh drafts --------------------------------------------------


def test_a_parents_edit_goes_through_the_same_checks(rig, brief, good_lyrics):
    song = to_words(rig, brief)
    original = song.lyrics

    bad = good_lyrics.model_copy(deep=True)
    bad.sections[0].lines[0].text = "Bed now, or else no story"
    with pytest.raises(LyricsNotAccepted) as refused:
        rig.pipeline.approve_lyrics(song.id, by="parent", edited=bad)
    assert refused.value.findings[0].code == "unsafe_words"
    saved = rig.store.get(song.id)
    assert saved.status is SongStatus.LYRICS_READY and saved.lyrics == original
    assert saved.edit_checks == 1

    song = rig.pipeline.approve_lyrics(song.id, by="parent", edited=good_lyrics)
    assert song.status is SongStatus.APPROVED
    assert song.lyrics == good_lyrics and song.lyrics_source == "parent_edit"


def test_a_parents_edit_the_judge_rejects_is_not_accepted(brief, good_lyrics):
    rig = Rig(judge=("pass", "unkind"))
    song = to_words(rig, brief)
    with pytest.raises(LyricsNotAccepted):
        rig.pipeline.approve_lyrics(song.id, by="parent", edited=good_lyrics)
    assert rig.store.get(song.id).status is SongStatus.LYRICS_READY


def test_edits_cannot_be_checked_forever(brief, good_lyrics):
    rig = Rig(limits=Limits(max_edit_checks=1))
    song = to_words(rig, brief)
    bad = good_lyrics.model_copy(deep=True)
    bad.sections[0].lines[0].text = "Bed now, or else no story"
    with pytest.raises(LyricsNotAccepted):
        rig.pipeline.approve_lyrics(song.id, by="parent", edited=bad)
    with pytest.raises(LimitReached):
        rig.pipeline.approve_lyrics(song.id, by="parent", edited=good_lyrics)


def test_a_parent_may_ask_for_different_words_twice(rig, brief):
    song = to_words(rig, brief)
    for expected in (1, 2):
        rig.pipeline.redraft(song.id)
        song = rig.pipeline.advance(song.id)
        assert song.status is SongStatus.LYRICS_READY and song.fresh_drafts == expected
    with pytest.raises(LimitReached):
        rig.pipeline.redraft(song.id)
    assert len(rig.writer.calls) == 3


# ---- music: retries, limits and what an adult can ask for ----------------------------------


@pytest.mark.parametrize("bad", ["silent", "short", "loud", "error"])
def test_one_bad_result_from_the_music_provider_is_retried_once(brief, bad):
    rig = Rig(music=(bad, "ok"))
    song = to_preview(rig, brief)
    assert song.status is SongStatus.AUDIO_CHECKED
    assert rig.music.calls == 2 and song.music_calls == 2


def test_two_bad_results_end_the_song_without_a_third_charge(brief):
    rig = Rig(music=("silent", "short"))
    song = to_preview(rig, brief)
    assert song.status is SongStatus.FAILED and song.failure == MUSIC_FAILED
    assert rig.music.calls == 2
    assert song.audio_path is None and song.published_at is None


def test_an_adult_who_says_no_can_ask_for_one_more_try(rig, brief):
    song = to_preview(rig, brief)
    song = rig.pipeline.adult_reject(song.id, by="parent", reason="too fast", try_again=True)
    assert song.status is SongStatus.APPROVED and song.audio_path is None

    song = rig.pipeline.advance(song.id)
    assert song.status is SongStatus.AUDIO_CHECKED and rig.music.calls == 2

    song = rig.pipeline.adult_reject(song.id, by="parent", try_again=True)
    assert song.status is SongStatus.FAILED, "only one extra try is allowed"
    assert rig.music.calls == 2


def test_an_adult_who_says_no_ends_the_song(rig, brief):
    song = to_preview(rig, brief)
    song = rig.pipeline.adult_reject(song.id, by="parent", reason="not right")
    assert song.status is SongStatus.FAILED and song.published_at is None
    assert any(a.step == "preview" and a.outcome == "rejected" for a in song.attempts)


def test_no_song_ever_gets_more_than_three_music_calls(brief):
    rig = Rig(music=("silent", "ok", "silent", "ok"))
    song = to_preview(rig, brief)  # two calls: one bad, one good
    song = rig.pipeline.adult_reject(song.id, by="parent", try_again=True)
    song = rig.pipeline.advance(song.id)  # third call is bad, and there is no fourth
    assert song.status is SongStatus.FAILED
    assert rig.music.calls == 3 and song.music_calls == 3


# ---- money: the kill switch, the daily budget and the household cap -------------------------


def test_the_kill_switch_stops_every_paid_call_and_loses_nothing(rig, brief):
    rig.controls.enabled = False
    song = to_words(rig, brief)
    assert song.status is SongStatus.SCREENED and song.blocked == PAUSED
    assert rig.paid_calls() == 0

    rig.controls.enabled = True
    song = rig.pipeline.advance(song.id)
    assert song.status is SongStatus.LYRICS_READY and song.blocked is None

    rig.pipeline.approve_lyrics(song.id, by="parent")
    rig.controls.enabled = False
    song = rig.pipeline.advance(song.id)
    assert song.status is SongStatus.APPROVED and song.blocked == PAUSED
    assert rig.music.calls == 0

    rig.controls.enabled = True
    assert rig.pipeline.advance(song.id).status is SongStatus.AUDIO_CHECKED


def test_a_parents_edit_is_not_checked_while_paused(rig, brief, good_lyrics):
    song = to_words(rig, brief)
    rig.controls.enabled = False
    with pytest.raises(Blocked):
        rig.pipeline.approve_lyrics(song.id, by="parent", edited=good_lyrics)
    assert rig.store.get(song.id).edit_checks == 0


def test_a_budget_too_small_for_one_song_makes_no_music(brief):
    rig = Rig(limits=Limits(daily_budget_usd=0.10))  # the words fit, a 15 cent song does not
    song = to_preview(rig, brief)
    assert song.status is SongStatus.APPROVED and song.blocked == OVER_BUDGET
    assert rig.music.calls == 0


def test_the_daily_budget_is_shared_by_all_households_and_starts_again_each_day(brief):
    rig = Rig(limits=Limits(daily_budget_usd=0.25))
    assert to_preview(rig, brief, "house-a").status is SongStatus.AUDIO_CHECKED  # about 16 cents
    second = to_preview(rig, brief, "house-b")
    assert second.status is SongStatus.APPROVED and second.blocked == OVER_BUDGET
    assert rig.music.calls == 1

    rig.clock.forward(days=1)
    assert rig.pipeline.advance(second.id).status is SongStatus.AUDIO_CHECKED
    assert rig.music.calls == 2


def test_a_household_gets_five_songs_a_day(rig, brief):
    for _ in range(5):
        rig.pipeline.create(brief, HOUSE)
    with pytest.raises(LimitReached):
        rig.pipeline.create(brief, HOUSE)
    rig.pipeline.create(brief, "house-b")  # another family is not affected
    rig.clock.forward(days=1)
    rig.pipeline.create(brief, HOUSE)  # and tomorrow is a new day


def test_a_brief_we_refused_for_free_does_not_use_up_a_familys_songs(rig, brief):
    bad = brief.model_copy(update={"steps": ("hit your brother", "say sorry", "go to bed")})
    for _ in range(8):
        assert to_words(rig, bad).status is SongStatus.REJECTED
    rig.pipeline.create(brief, HOUSE)


def test_a_household_code_must_look_like_one(rig, brief):
    with pytest.raises(ValueError):
        rig.pipeline.create(brief, "../../etc")


# ---- crashes --------------------------------------------------------------------------------


def test_a_crash_during_a_music_call_still_counts_as_a_call(brief):
    rig = Rig(music=("crash", "ok"))
    song = to_words(rig, brief)
    rig.pipeline.approve_lyrics(song.id, by="parent")
    with pytest.raises(Crash):
        rig.pipeline.advance(song.id)

    saved = rig.store.get(song.id)
    assert saved.status is SongStatus.APPROVED and saved.music_calls == 1
    assert saved.attempts[-1].outcome == "started" and saved.attempts[-1].cost_usd == 0.15

    # A new process picks the song up from what was saved.
    restarted = Rig(store=rig.store, clock=rig.clock)
    song = restarted.pipeline.advance(song.id)
    assert song.status is SongStatus.AUDIO_CHECKED
    assert song.music_calls == 2, "the call that was cut short is still on the books"
    interrupted = [a for a in song.attempts if a.outcome == "interrupted"]
    assert len(interrupted) == 1 and interrupted[0].cost_usd == 0.15
    assert song.spend_usd() == pytest.approx(0.15 + 0.15 + 0.002 + 0.002 + 0.007)


def test_repeated_crashes_cannot_run_up_the_bill(brief):
    rig = Rig(music=("crash", "crash", "ok"))
    song = to_words(rig, brief)
    rig.pipeline.approve_lyrics(song.id, by="parent")
    for _ in range(2):
        with pytest.raises(Crash):
            rig.pipeline.advance(song.id)
    song = rig.pipeline.advance(song.id)
    assert song.status is SongStatus.FAILED
    assert rig.music.calls == 2, "the third call is never made"


def test_a_crash_while_writing_loses_nothing_and_charges_nothing_twice(brief):
    rig = Rig(writer=("crash",))
    song = rig.pipeline.create(brief, HOUSE)
    with pytest.raises(Crash):
        rig.pipeline.advance(song.id)
    assert rig.store.get(song.id).status is SongStatus.SCREENED
    assert rig.pipeline.advance(song.id).status is SongStatus.LYRICS_READY


def test_a_change_that_was_not_saved_is_lost(rig, brief):
    song = to_words(rig, brief)
    song.status = SongStatus.PUBLISHED  # changing what the pipeline handed back
    handed_out = rig.store.get(song.id)
    handed_out.status = SongStatus.PUBLISHED  # changing what the store handed out
    assert rig.store.get(song.id).status is SongStatus.LYRICS_READY


# ---- the audit trail ------------------------------------------------------------------------


def test_every_step_leaves_a_record_with_its_cost(rig, brief):
    song = to_preview(rig, brief)
    song = rig.pipeline.adult_approve(song.id, by="parent")
    steps = [(a.step, a.outcome) for a in song.attempts]
    assert steps == [
        ("screen", "ok"),
        ("write", "ok"),
        ("rules", "ok"),
        ("judge", "ok"),
        ("compose", "ok"),
        ("audio_check", "ok"),
        ("transcribe", "ok"),
        ("preview", "ok"),
    ]
    paid = {a.step: a.cost_usd for a in song.attempts if a.provider != "code"}
    assert paid == {"write": 0.002, "judge": 0.002, "compose": 0.15, "transcribe": 0.007}
    assert song.prompt_version == "fake-1"


def test_how_much_of_the_words_can_be_heard_is_recorded_but_does_not_block(brief):
    rig = Rig(drop_every=3)
    song = to_preview(rig, brief)
    assert song.status is SongStatus.AUDIO_CHECKED
    assert 0.5 < song.transcript_match < 0.8


def test_a_transcript_is_skipped_rather_than_holding_up_a_finished_song(brief):
    # Enough budget for the words and the music, but not for the transcript after them.
    rig = Rig(limits=Limits(daily_budget_usd=0.16))
    song = to_preview(rig, brief)
    assert song.status is SongStatus.AUDIO_CHECKED
    assert song.transcript_match is None and rig.transcriber.calls == 0
    assert song.attempts[-1].step == "transcribe" and song.attempts[-1].outcome == "skipped"
