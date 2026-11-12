import pytest

from mm.audio import WavInspector, check_audio, silence_wav, tone_wav
from mm.domain import Brief
from mm.ports import AudioFacts, UnsupportedAudio
from mm.safety import rules
from mm.templates import fallback_lyrics


def _brief(steps, nickname=None):
    return Brief(
        routine="bedtime", steps=steps, style="calm_piano", age_band="5-6", nickname=nickname
    )


@pytest.mark.parametrize(
    "steps",
    [
        ["a", "b", "c"],  # the shortest brief the app accepts
        # the longest: five steps of five words each
        [f"{word} two three four five" for word in ("ant", "bee", "cat", "dog", "eel")],
        ["shoes on", "coat on", "hat on"],  # steps made mostly of small words
    ],
)
def test_the_fallback_song_passes_the_rules_for_any_valid_brief(steps):
    brief = _brief(steps)
    lyrics = fallback_lyrics(brief)
    assert rules.check_lyrics(lyrics, brief) == []
    assert 60 <= lyrics.word_count() <= 110


def test_the_fallback_song_sings_every_step_in_order():
    brief = _brief(["brush teeth", "pajamas on", "lights out"], nickname="Leo")
    sung = fallback_lyrics(brief).render("Leo")
    assert sung.index("brush teeth") < sung.index("pajamas on") < sung.index("lights out")
    assert "Leo" in sung and "{name}" not in sung


def test_a_tone_has_the_length_and_loudness_we_expect():
    facts = WavInspector().inspect(tone_wav(3.0), "audio/wav")
    assert facts.seconds == pytest.approx(3.0, abs=0.01)
    assert -20 < facts.rms_dbfs < -10
    assert check_audio(facts, target_seconds=3.0) == []


def test_silence_is_caught():
    facts = WavInspector().inspect(silence_wav(3.0), "audio/wav")
    assert [finding.code for finding in check_audio(facts, 3.0)] == ["too_quiet"]


def test_audio_that_is_too_loud_is_caught():
    facts = WavInspector().inspect(tone_wav(3.0, amplitude=0.99), "audio/wav")
    assert [finding.code for finding in check_audio(facts, 3.0)] == ["too_loud"]


@pytest.mark.parametrize(("seconds", "ok"), [(47, False), (48, True), (72, True), (73, False)])
def test_length_may_be_off_by_a_fifth(seconds, ok):
    facts = AudioFacts(seconds=seconds, peak=0.3, rms_dbfs=-15)
    assert (check_audio(facts, target_seconds=60) == []) is ok


def test_audio_we_cannot_read_is_refused_not_guessed_at():
    with pytest.raises(UnsupportedAudio):
        WavInspector().inspect(b"ID3 not a wav", "audio/mpeg")
    with pytest.raises(UnsupportedAudio):
        WavInspector().inspect(b"not a wav at all", "audio/wav")
