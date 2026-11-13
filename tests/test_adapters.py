"""The real-provider adapters' promises, each as one test.

Nothing here touches the network. Every test passes a fake transport, so a mistake in this
file cannot spend money. The one test that proves the default path is still fakes is the most
important one in the file.
"""

from __future__ import annotations

import io
import json
import wave

import pytest

from mm.adapters import SpendCapReached, build_providers
from mm.adapters.elevenlabs import ElevenLabsMusic, ElevenLabsTranscriber, Reply
from mm.adapters.settings import RealProviderSettings, SettingsError
from mm.audio import WavInspector
from mm.domain import Brief, Lyrics
from mm.ports import ProviderError
from mm.presets import STYLE_PRESETS

PRESET = STYLE_PRESETS["gentle_lullaby"]


def pcm(seconds: float, *, rate: int = 22050, channels: int = 2) -> bytes:
    """Raw 16-bit little-endian PCM of the length ElevenLabs would return."""
    return b"\x11\x00" * int(seconds * rate * channels)


class Transport:
    """Stands in for the network. Records what was sent, replays what it was told to."""

    def __init__(self, *replies: Reply) -> None:
        self.replies = list(replies)
        self.sent: list[tuple[str, str, dict[str, str], bytes]] = []

    def __call__(self, method: str, url: str, headers: dict[str, str], body: bytes) -> Reply:
        self.sent.append((method, url, headers, body))
        if not self.replies:
            raise AssertionError("the transport was called more times than the test allows")
        return self.replies.pop(0)

    @property
    def last_body(self) -> dict[str, object]:
        return json.loads(self.sent[-1][3])


def settings(**over: object) -> RealProviderSettings:
    base: dict[str, object] = {"api_key": "test-key-not-real", "spend_cap_usd": 1.00}
    base.update(over)
    return RealProviderSettings(**base)  # type: ignore[arg-type]


def music_reply(seconds: float = 60.0, **over: object) -> Reply:
    body = over.pop("body", pcm(seconds))
    return Reply(status=200, body=body, content_type="audio/pcm", **over)  # type: ignore[arg-type]


# ---- fakes stay the default -----------------------------------------------------------------


def test_with_no_environment_set_the_providers_are_fakes():
    music, transcriber = build_providers(env={})
    assert music.name == "fake"
    assert transcriber.name == "fake"


def test_a_key_on_its_own_is_not_enough_to_go_real():
    """A key in the environment must never be sufficient. The opt-in has to be deliberate."""
    music, _ = build_providers(env={"ELEVENLABS_API_KEY": "test-key-not-real"})
    assert music.name == "fake"


def test_the_opt_in_must_be_the_exact_word_yes():
    for value in ("true", "1", "YES ", "y", "on", ""):
        music, _ = build_providers(
            env={
                "MM_REAL_PROVIDERS": value,
                "ELEVENLABS_API_KEY": "test-key-not-real",
                "MM_SPEND_CAP_USD": "1.00",
            }
        )
        assert music.name == "fake", f"{value!r} should not turn real providers on"


def test_opting_in_without_a_spend_cap_refuses_rather_than_defaulting():
    with pytest.raises(SettingsError, match="MM_SPEND_CAP_USD"):
        build_providers(env={"MM_REAL_PROVIDERS": "yes", "ELEVENLABS_API_KEY": "test-key-not-real"})


def test_opting_in_without_a_key_refuses_and_does_not_name_the_variable_value():
    with pytest.raises(SettingsError) as caught:
        build_providers(env={"MM_REAL_PROVIDERS": "yes", "MM_SPEND_CAP_USD": "1.00"})
    assert "ELEVENLABS_API_KEY" in str(caught.value)


def test_a_cap_of_zero_or_less_is_refused():
    for value in ("0", "-1", "nonsense"):
        with pytest.raises(SettingsError):
            build_providers(
                env={
                    "MM_REAL_PROVIDERS": "yes",
                    "ELEVENLABS_API_KEY": "test-key-not-real",
                    "MM_SPEND_CAP_USD": value,
                }
            )


def test_opting_in_properly_does_give_the_real_adapters():
    music, transcriber = build_providers(
        env={
            "MM_REAL_PROVIDERS": "yes",
            "ELEVENLABS_API_KEY": "test-key-not-real",
            "MM_SPEND_CAP_USD": "1.00",
        }
    )
    assert music.name == "elevenlabs"
    assert transcriber.name == "elevenlabs"


# ---- the dollar cap -------------------------------------------------------------------------


def test_the_cap_stops_a_call_before_it_is_made(good_lyrics: Lyrics):
    transport = Transport(music_reply())
    provider = ElevenLabsMusic(settings(spend_cap_usd=0.01), transport=transport)
    with pytest.raises(SpendCapReached):
        provider.compose(good_lyrics, "Mimi", PRESET)
    assert transport.sent == [], "nothing may be sent once the cap would be exceeded"


def test_spend_is_recorded_before_the_call_so_a_crash_still_counts(good_lyrics: Lyrics):
    def explode(method: str, url: str, headers: dict[str, str], body: bytes) -> Reply:
        raise OSError("the connection dropped mid-call")

    provider = ElevenLabsMusic(settings(spend_cap_usd=0.20), transport=explode)
    with pytest.raises(ProviderError):
        provider.compose(good_lyrics, "Mimi", PRESET)
    assert provider.cap.spent_usd > 0, "a call that crashed still cost us money"


def test_the_cap_is_shared_between_music_and_transcription(good_lyrics: Lyrics):
    """One budget, not one each. Two adapters on one cap must see the same total."""
    transport = Transport(music_reply())
    music = ElevenLabsMusic(settings(spend_cap_usd=0.20), transport=transport)
    transcriber = ElevenLabsTranscriber(
        settings(spend_cap_usd=0.20), transport=transport, cap=music.cap
    )
    music.compose(good_lyrics, "Mimi", PRESET)
    assert transcriber.cap.spent_usd == music.cap.spent_usd
    assert transcriber.cap is music.cap


# ---- what goes on the wire ------------------------------------------------------------------


def test_the_request_asks_for_the_preset_length_and_the_configured_model(good_lyrics: Lyrics):
    transport = Transport(music_reply())
    ElevenLabsMusic(settings(), transport=transport).compose(good_lyrics, "Mimi", PRESET)
    method, url, headers, _ = transport.sent[0]
    assert method == "POST"
    assert url.startswith("https://api.elevenlabs.io/v1/music")
    assert headers["xi-api-key"] == "test-key-not-real"
    assert transport.last_body["music_length_ms"] == PRESET.seconds * 1000
    assert transport.last_body["model_id"] == "music_v2"


def test_the_words_sent_are_the_words_the_parent_approved(good_lyrics: Lyrics):
    transport = Transport(music_reply())
    ElevenLabsMusic(settings(), transport=transport).compose(good_lyrics, "Mimi", PRESET)
    prompt = str(transport.last_body["prompt"])
    assert "Goodnight, Mimi, sleep tight" in prompt
    assert "{name}" not in prompt, "the name slot must be filled in before sending"


def test_the_style_words_sent_are_only_the_preset_s_own(good_lyrics: Lyrics):
    transport = Transport(music_reply())
    ElevenLabsMusic(settings(), transport=transport).compose(good_lyrics, "Mimi", PRESET)
    prompt = str(transport.last_body["prompt"])
    for word in PRESET.positive:
        assert word in prompt
    for word in PRESET.negative:
        assert word in prompt


def with_a_brand_in_a_sung_line(lyrics: Lyrics) -> Lyrics:
    """A brand name in a line that would really be sung, which is the path that reaches the wire.

    The title is not sung and never leaves us, so putting one there would prove nothing.
    """
    sections = [section.model_copy(deep=True) for section in lyrics.sections]
    sections[0].lines[0].text = "Sing it like Elsa would sing it"
    return lyrics.model_copy(update={"sections": sections})


def test_a_brand_name_in_the_outgoing_prompt_is_never_sent(good_lyrics: Lyrics):
    """A second line of defence. The provider's terms forbid these, so we check at the wire."""
    transport = Transport(music_reply())
    provider = ElevenLabsMusic(settings(), transport=transport)
    with pytest.raises(ProviderError, match="cannot be sent"):
        provider.compose(with_a_brand_in_a_sung_line(good_lyrics), "Mimi", PRESET)
    assert transport.sent == []


def test_the_refusal_does_not_repeat_the_word_that_was_refused(good_lyrics: Lyrics):
    provider = ElevenLabsMusic(settings(), transport=Transport(music_reply()))
    with pytest.raises(ProviderError) as caught:
        provider.compose(with_a_brand_in_a_sung_line(good_lyrics), "Mimi", PRESET)
    assert "elsa" not in str(caught.value).lower()


def test_a_title_is_not_sent_at_all_so_it_cannot_leak(good_lyrics: Lyrics):
    """Pins the reason the test above puts the word in a line instead of the title."""
    transport = Transport(music_reply())
    lyrics = good_lyrics.model_copy(update={"title": "Sleepy steps at bedtime"})
    ElevenLabsMusic(settings(), transport=transport).compose(lyrics, "Mimi", PRESET)
    assert "Sleepy steps at bedtime" not in str(transport.last_body["prompt"])


def test_logging_is_left_on_because_zero_retention_needs_an_enterprise_plan(good_lyrics: Lyrics):
    """Asking for zero retention on our plan would fail the call. Recorded, not silently dropped."""
    transport = Transport(music_reply())
    ElevenLabsMusic(settings(), transport=transport).compose(good_lyrics, "Mimi", PRESET)
    assert "enable_logging=false" not in transport.sent[0][1]


# ---- the audio that comes back --------------------------------------------------------------


def test_the_audio_returned_is_wav_that_the_inspector_can_actually_read(good_lyrics: Lyrics):
    """The whole point of asking for PCM: the existing inspector keeps working."""
    transport = Transport(music_reply(seconds=60.0))
    audio = ElevenLabsMusic(settings(), transport=transport).compose(good_lyrics, "Mimi", PRESET)
    assert audio.mime == "audio/wav"
    facts = WavInspector().inspect(audio.data, audio.mime)
    assert facts.seconds == pytest.approx(60.0, abs=0.5)


def test_the_pcm_format_asked_for_is_one_a_starter_plan_allows(good_lyrics: Lyrics):
    transport = Transport(music_reply())
    ElevenLabsMusic(settings(), transport=transport).compose(good_lyrics, "Mimi", PRESET)
    url = transport.sent[0][1]
    assert "output_format=pcm_22050" in url
    assert "pcm_44100" not in url, "pcm_44100 needs a Pro plan"


def test_audio_of_the_wrong_length_is_an_error_rather_than_a_bad_song(good_lyrics: Lyrics):
    """If the channel count is wrong the duration comes out wrong. Fail loudly, not quietly."""
    transport = Transport(music_reply(seconds=30.0))
    provider = ElevenLabsMusic(settings(), transport=transport)
    with pytest.raises(ProviderError, match="length"):
        provider.compose(good_lyrics, "Mimi", PRESET)


def test_the_cost_is_worked_out_from_the_length_actually_returned(good_lyrics: Lyrics):
    transport = Transport(music_reply(seconds=60.0))
    audio = ElevenLabsMusic(settings(), transport=transport).compose(good_lyrics, "Mimi", PRESET)
    assert audio.cost_usd == pytest.approx(0.15, abs=0.001)


@pytest.mark.parametrize("status", [401, 422, 429, 500])
def test_an_error_status_becomes_a_provider_error_the_pipeline_can_handle(
    good_lyrics: Lyrics, status: int
):
    transport = Transport(Reply(status=status, body=b'{"detail":"no"}', content_type="text/json"))
    provider = ElevenLabsMusic(settings(), transport=transport)
    with pytest.raises(ProviderError):
        provider.compose(good_lyrics, "Mimi", PRESET)


def test_an_error_body_is_not_shown_to_a_parent(good_lyrics: Lyrics):
    secret = b'{"detail":"key xi-abc123 is invalid"}'
    transport = Transport(Reply(status=401, body=secret, content_type="text/json"))
    provider = ElevenLabsMusic(settings(), transport=transport)
    with pytest.raises(ProviderError) as caught:
        provider.compose(good_lyrics, "Mimi", PRESET)
    assert "xi-abc123" not in str(caught.value)


# ---- the transcriber ------------------------------------------------------------------------


def wav(seconds: float, rate: int = 22050) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x11\x00" * int(seconds * rate))
    return out.getvalue()


def test_the_transcriber_returns_the_words_the_provider_heard():
    reply = Reply(status=200, body=b'{"text":"sleepy steps one two three"}', content_type="json")
    transcriber = ElevenLabsTranscriber(settings(), transport=Transport(reply))
    assert transcriber.transcribe(wav(60), "audio/wav").text == "sleepy steps one two three"


def test_the_transcriber_sends_the_audio_as_a_file_and_names_the_model():
    transport = Transport(Reply(status=200, body=b'{"text":"hi"}', content_type="json"))
    ElevenLabsTranscriber(settings(), transport=transport).transcribe(wav(60), "audio/wav")
    method, url, headers, body = transport.sent[0]
    assert url.startswith("https://api.elevenlabs.io/v1/speech-to-text")
    assert headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert b'name="model_id"' in body
    assert b"scribe_v1" in body
    assert b'name="file"' in body


def test_the_transcriber_charges_by_the_hour_not_the_minute():
    transport = Transport(Reply(status=200, body=b'{"text":"hi"}', content_type="json"))
    transcriber = ElevenLabsTranscriber(settings(), transport=transport)
    result = transcriber.transcribe(wav(3600), "audio/wav")
    assert result.cost_usd == pytest.approx(0.22, abs=0.001)


def test_a_reply_without_a_text_field_is_an_error_not_an_empty_transcript():
    transport = Transport(Reply(status=200, body=b'{"words":[]}', content_type="json"))
    transcriber = ElevenLabsTranscriber(settings(), transport=transport)
    with pytest.raises(ProviderError):
        transcriber.transcribe(wav(60), "audio/wav")


def test_an_empty_transcript_is_passed_through_because_silence_is_a_real_answer():
    """The audio check exists to catch a silent song. The transcriber must not hide one."""
    transport = Transport(Reply(status=200, body=b'{"text":""}', content_type="json"))
    transcriber = ElevenLabsTranscriber(settings(), transport=transport)
    assert transcriber.transcribe(wav(60), "audio/wav").text == ""


# ---- the adapters fit the ports -------------------------------------------------------------


def test_the_adapters_satisfy_the_ports_the_pipeline_declares(brief: Brief):
    from mm.ports import MusicProvider, Transcriber

    music: MusicProvider = ElevenLabsMusic(settings(), transport=Transport())
    transcriber: Transcriber = ElevenLabsTranscriber(settings(), transport=Transport())
    assert music.model and transcriber.model
    assert brief.style in STYLE_PRESETS


# ---- the commands that must never be able to spend ------------------------------------------


FULLY_CONFIGURED = {
    "MM_REAL_PROVIDERS": "yes",
    "ELEVENLABS_API_KEY": "test-key-not-real",
    "MM_SPEND_CAP_USD": "1.00",
}


def test_eval_stays_on_fakes_even_when_real_providers_are_fully_configured(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """One eval run is 30 songs, more than a month of Starter credits. It must not be reachable."""
    from mm.cli import main

    for name, value in FULLY_CONFIGURED.items():
        monkeypatch.setenv(name, value)
    assert main(["eval"], env_file=None) == 0
    assert "Providers: fake" in capsys.readouterr().out


def test_check_provider_sends_nothing_without_an_explicit_yes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from mm.cli import main

    for name, value in FULLY_CONFIGURED.items():
        monkeypatch.setenv(name, value)
    assert main(["check-provider"], env_file=None) == 0
    out = capsys.readouterr().out
    assert "Nothing was sent" in out
    assert "$0.15" in out, "the estimate must be shown before anything is spent"


def test_check_provider_refuses_when_it_would_only_use_fakes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from mm.cli import main

    for name in FULLY_CONFIGURED:
        monkeypatch.delenv(name, raising=False)
    assert main(["check-provider", "--yes"], env_file=None) == 2
    assert "would prove nothing" in capsys.readouterr().out


def test_check_provider_never_prints_the_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    from mm.cli import main

    for name, value in FULLY_CONFIGURED.items():
        monkeypatch.setenv(name, value)
    main(["check-provider"], env_file=None)
    assert "test-key-not-real" not in capsys.readouterr().out


# ---- reading .env ---------------------------------------------------------------------------


def test_the_env_file_is_what_makes_a_key_in_a_file_actually_arrive(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """The bug this file exists to prevent: a key sitting in .env that nothing ever reads."""
    from mm.cli import main

    for name in FULLY_CONFIGURED:
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "MM_REAL_PROVIDERS=yes\n"
        'ELEVENLABS_API_KEY="test-key-not-real"\n'
        "export MM_SPEND_CAP_USD=1.00\n"
    )
    assert main(["check-provider"], env_file=env) == 0


def test_a_value_already_in_the_environment_beats_the_file(tmp_path, monkeypatch):
    from mm.env import load_env

    monkeypatch.setenv("MM_SPEND_CAP_USD", "0.50")
    env = tmp_path / ".env"
    env.write_text("MM_SPEND_CAP_USD=9.00\n")
    load_env(env)
    import os

    assert os.environ["MM_SPEND_CAP_USD"] == "0.50"


def test_loading_reports_names_and_never_values(tmp_path, monkeypatch):
    from mm.env import load_env

    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("ELEVENLABS_API_KEY=test-key-not-real\n")
    assert load_env(env) == ["ELEVENLABS_API_KEY"]


def test_a_missing_env_file_is_not_an_error_because_fakes_are_the_default(tmp_path):
    from mm.env import load_env

    assert load_env(tmp_path / "nothing-here") == []
    assert load_env(None) == []


@pytest.mark.parametrize(
    "line, expected",
    [
        ("A=1", {"A": "1"}),
        ("  A = 1  ", {"A": "1"}),
        ("A='quoted'", {"A": "quoted"}),
        ('A="quoted"', {"A": "quoted"}),
        ("export A=1", {"A": "1"}),
        ("# A=1", {}),
        ("", {}),
        ("no equals sign", {}),
        # A bare valid name must be skipped, not turned into an empty value.
        ("JUSTANAME", {}),
        ("MM_REAL_PROVIDERS", {}),
        ("A=has=equals", {"A": "has=equals"}),
        ("A=", {"A": ""}),
        ("not a name!=1", {}),
    ],
)
def test_the_parser_skips_what_it_cannot_read_rather_than_guessing(line: str, expected: dict):
    from mm.env import parse_env

    assert parse_env(line) == expected


# ---- serve can make real music, demo and eval cannot ----------------------------------------


def test_serve_without_the_flag_is_on_fakes_even_with_the_settings_in_place(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """Two gates, not one: the environment alone must not make a served page spend money."""
    from mm import cli

    for name, value in FULLY_CONFIGURED.items():
        monkeypatch.setenv(name, value)

    def must_not_be_called(*args: object, **kwargs: object) -> object:
        raise AssertionError("serve reached the paid provider without --real")

    monkeypatch.setattr(cli, "_real_pipeline", must_not_be_called)
    built: list[str] = []
    real_fake = cli._fake_pipeline

    def note_it(*args: object, **kwargs: object) -> object:
        built.append("fake")
        return real_fake(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "_fake_pipeline", note_it)
    cli.build_site(tmp_path / "data", ["code-a"], ["team-a"])
    assert built == ["fake"]


def test_serve_with_the_flag_refuses_when_the_settings_are_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """Better to refuse to start than to serve a test tone to a watching audience."""
    from mm.adapters import SettingsError
    from mm.cli import build_site

    for name in FULLY_CONFIGURED:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SettingsError, match="not configured"):
        build_site(tmp_path / "data", ["code-a"], ["team-a"], real=True)


def test_serve_with_the_flag_and_the_settings_uses_the_real_music_provider(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    from mm.cli import _real_pipeline
    from mm.controls import StaticControls
    from mm.store import JsonDirStore

    for name, value in FULLY_CONFIGURED.items():
        monkeypatch.setenv(name, value)
    pipeline = _real_pipeline(JsonDirStore(tmp_path / "data"), StaticControls())
    assert pipeline.music.name == "elevenlabs"
    assert pipeline.transcriber.name == "elevenlabs"
    assert pipeline.writer.name == "fake", "the writer is still a stand-in; say so, do not hide it"


# ---- an error a person can act on --------------------------------------------------------


def test_an_unreachable_provider_says_why_not_just_the_exception_name(good_lyrics: Lyrics):
    """ "URLError" told Sid nothing. The reason is what he needed, and it is ours, not theirs."""
    import ssl
    import urllib.error

    def cert_problem(method: str, url: str, headers: dict[str, str], body: bytes) -> Reply:
        raise urllib.error.URLError(
            ssl.SSLCertVerificationError("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get issuer")
        )

    provider = ElevenLabsMusic(settings(), transport=cert_problem)
    with pytest.raises(ProviderError, match="CERTIFICATE_VERIFY_FAILED"):
        provider.compose(good_lyrics, "Mimi", PRESET)


def test_the_key_is_redacted_from_a_connection_error_even_so(good_lyrics: Lyrics):
    def leaky(method: str, url: str, headers: dict[str, str], body: bytes) -> Reply:
        raise OSError("connection to https://api.elevenlabs.io?k=test-key-not-real refused")

    provider = ElevenLabsMusic(settings(), transport=leaky)
    with pytest.raises(ProviderError) as caught:
        provider.compose(good_lyrics, "Mimi", PRESET)
    assert "test-key-not-real" not in str(caught.value)
    assert "***" in str(caught.value)


def test_a_very_long_error_is_cut_short_rather_than_filling_the_screen(good_lyrics: Lyrics):
    def chatty(method: str, url: str, headers: dict[str, str], body: bytes) -> Reply:
        raise OSError("x" * 5000)

    provider = ElevenLabsMusic(settings(), transport=chatty)
    with pytest.raises(ProviderError) as caught:
        provider.compose(good_lyrics, "Mimi", PRESET)
    assert len(str(caught.value)) < 300


def test_an_error_with_nothing_to_say_still_names_its_type(good_lyrics: Lyrics):
    def silent(method: str, url: str, headers: dict[str, str], body: bytes) -> Reply:
        raise TimeoutError()

    provider = ElevenLabsMusic(settings(), transport=silent)
    with pytest.raises(ProviderError, match="TimeoutError"):
        provider.compose(good_lyrics, "Mimi", PRESET)


@pytest.mark.parametrize(
    "message, expected",
    [
        ("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get issuer", "Install Certificates"),
        ("nodename nor servname provided", "DNS"),
        ("The read operation timed out", "timed out"),
        ("something nobody predicted", "Send me the line above"),
    ],
)
def test_the_hint_points_at_the_usual_cause(message: str, expected: str):
    from mm.cli import _hint

    assert expected in _hint(message)
