"""Tests for real meeting-audio transcription (offline, no real network).

Two layers, tested separately:

* :func:`ai_assistant.integrations.llm.generate_from_audio` — what REQUEST is
  built for a recording (inline data, size ceiling, thinking budget) and that
  it inherits the existing retry/stats machinery rather than a second HTTP
  path of its own.
* :meth:`MeetingNotesAgent.transcribe_audio` — that the transcript it returns
  is DERIVED FROM the model's answer. The old test asserted a hard-coded
  string against a hard-coded return value, which is why nobody noticed the
  function never opened the audio; every assertion here would fail if the
  canned text came back.
"""

from __future__ import annotations

import asyncio
import base64
from unittest.mock import Mock, patch

import httpx
import pytest

from ai_assistant.advisors.meeting_notes import MeetingNotesAgent
from ai_assistant.integrations import llm

FAKE_KEY = "AQ.FAKE-secret-key-should-never-leak-123456"

#: The exact opening line of the placeholder transcript this work deleted. If
#: it ever comes back, the behaviour tests below must fail.
CANNED_OPENING = "Selamlar herkese. Bugünün toplantısında üç ana konuyu ele aldık."

AUDIO = b"ID3\x04\x00\x00fake-mp3-bytes"


def _resp(status_code: int, headers: dict | None = None) -> httpx.Response:
    request = httpx.Request(
        "POST",
        "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent",
    )
    return httpx.Response(status_code, headers=headers or {}, request=request)


@pytest.fixture()
def gemini_env(monkeypatch):
    """Gemini-only environment with fast, deterministic retries."""
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_THINKING_BUDGET", raising=False)
    monkeypatch.setenv("GEMINI_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("GEMINI_REQUEST_SPACING_SECONDS", "0")
    monkeypatch.delenv("LLM_TIME_BUDGET_SECONDS", raising=False)
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS", raising=False)
    monkeypatch.setattr(llm, "DEFAULT_GEMINI_FALLBACK_MODELS", "")
    llm.clear_time_budget()
    llm.reset_call_stats()
    yield
    llm.clear_time_budget()
    llm.reset_call_stats()


def _capture_post(monkeypatch, answer="deşifre metni", statuses=(200,)):
    """Patch the shared POST helper and record every request body."""
    captured = {"calls": [], "urls": []}
    remaining = list(statuses)

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["calls"].append(json)
        captured["urls"].append(url)
        captured["headers"] = headers or {}
        status = remaining.pop(0) if remaining else 200
        return _resp(status)

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(
        httpx.Response,
        "json",
        lambda self: {
            "candidates": [{"content": {"parts": [{"text": answer}]}}],
            "usageMetadata": {
                "promptTokenCount": 4000,
                "candidatesTokenCount": 900,
                "totalTokenCount": 4900,
            },
        },
        raising=False,
    )
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    return captured


# ---------------------------------------------------------------------------
# llm.generate_from_audio — the request that goes out
# ---------------------------------------------------------------------------


def test_audio_is_sent_as_inline_data_with_mime_and_base64(monkeypatch, gemini_env):
    captured = _capture_post(monkeypatch)

    llm.generate_from_audio(AUDIO, "audio/mpeg", "sys", "deşifre et")

    parts = captured["calls"][0]["contents"][0]["parts"]
    inline = next(part["inlineData"] for part in parts if "inlineData" in part)
    assert inline["mimeType"] == "audio/mpeg"
    # The bytes must arrive intact, base64-encoded — not a path, not a URL.
    assert base64.b64decode(inline["data"]) == AUDIO
    # The text turn rides alongside the audio in the same user message.
    assert any(part.get("text") == "deşifre et" for part in parts)
    assert captured["calls"][0]["system_instruction"]["parts"][0]["text"] == "sys"


def test_audio_over_the_inline_limit_is_refused_without_a_request(
    monkeypatch, gemini_env
):
    captured = _capture_post(monkeypatch)
    too_big = b"x" * (llm.MAX_INLINE_AUDIO_BYTES + 1)

    with pytest.raises(ValueError) as excinfo:
        llm.generate_from_audio(too_big, "audio/mpeg", "sys", "user")

    message = str(excinfo.value)
    assert str(llm.MAX_INLINE_AUDIO_BYTES) in message
    assert "100 MB" in message
    assert captured["calls"] == []  # nothing went over the wire


def test_audio_at_exactly_the_limit_is_still_sent(monkeypatch, gemini_env):
    captured = _capture_post(monkeypatch)

    llm.generate_from_audio(
        b"x" * llm.MAX_INLINE_AUDIO_BYTES, "audio/wav", "sys", "user"
    )

    assert len(captured["calls"]) == 1


def test_thinking_budget_is_passed_through(monkeypatch, gemini_env):
    captured = _capture_post(monkeypatch)

    llm.generate_from_audio(AUDIO, "audio/mpeg", "sys", "user", thinking_budget=0)

    config = captured["calls"][0]["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingBudget": 0}


def test_no_thinking_config_when_no_budget_is_configured(monkeypatch, gemini_env):
    captured = _capture_post(monkeypatch)

    llm.generate_from_audio(AUDIO, "audio/mpeg", "sys", "user")

    assert "thinkingConfig" not in captured["calls"][0]["generationConfig"]


def test_max_output_tokens_is_honoured(monkeypatch, gemini_env):
    captured = _capture_post(monkeypatch)

    llm.generate_from_audio(
        AUDIO, "audio/mpeg", "sys", "user", max_output_tokens=32768
    )

    assert captured["calls"][0]["generationConfig"]["maxOutputTokens"] == 32768


def test_key_travels_in_the_header_not_the_url(monkeypatch, gemini_env):
    captured = _capture_post(monkeypatch)

    llm.generate_from_audio(AUDIO, "audio/mpeg", "sys", "user")

    assert captured["headers"]["X-goog-api-key"] == FAKE_KEY
    assert "key=" not in captured["urls"][0]


def test_audio_call_reuses_the_retry_and_stats_machinery(monkeypatch, gemini_env):
    """A 503 must be retried and accounted for, exactly as for text."""
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "3")
    captured = _capture_post(monkeypatch, answer="metin", statuses=(503, 200))

    text = llm.generate_from_audio(AUDIO, "audio/mpeg", "sys", "user")

    assert text == "metin"
    assert len(captured["calls"]) == 2  # retried, not given up on
    stats = llm.last_call_stats()
    assert stats is not None
    assert stats.provider == "gemini"
    assert stats.retries == 1
    assert stats.ok is True
    assert stats.prompt_tokens == 4000


def test_empty_audio_is_refused(monkeypatch, gemini_env):
    captured = _capture_post(monkeypatch)

    with pytest.raises(ValueError):
        llm.generate_from_audio(b"", "audio/mpeg", "sys", "user")

    assert captured["calls"] == []


def test_missing_mime_type_is_refused(monkeypatch, gemini_env):
    captured = _capture_post(monkeypatch)

    with pytest.raises(ValueError, match="mime_type"):
        llm.generate_from_audio(AUDIO, "  ", "sys", "user")

    assert captured["calls"] == []


def test_no_provider_configured_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm.generate_from_audio(AUDIO, "audio/mpeg", "sys", "user")


def test_openai_only_environment_says_audio_needs_gemini(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")

    with pytest.raises(RuntimeError, match="Gemini"):
        llm.generate_from_audio(AUDIO, "audio/mpeg", "sys", "user")


# ---------------------------------------------------------------------------
# MeetingNotesAgent.transcribe_audio — behaviour, not canned text
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent() -> MeetingNotesAgent:
    with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"), patch(
        "ai_assistant.advisors.meeting_notes.TaskTracker"
    ):
        agent = MeetingNotesAgent()
    agent.drive_manager = Mock()
    agent.task_tracker = Mock()
    return agent


def test_transcript_is_derived_from_the_model_answer(agent, monkeypatch):
    """The one test that would have caught the placeholder."""
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(
        llm,
        "generate_from_audio",
        lambda *args, **kwargs: "  Konuşmacı 1: KUZEY RÜZGARI raporu hazır.  ",
    )

    transcript = asyncio.run(agent.transcribe_audio(AUDIO, mime_type="audio/mpeg"))

    assert transcript == "Konuşmacı 1: KUZEY RÜZGARI raporu hazır."
    assert CANNED_OPENING not in transcript
    assert "John" not in transcript  # a name only the placeholder ever had
    assert agent.last_transcription_error is None


def test_audio_bytes_and_mime_type_reach_the_model(agent, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    seen = {}

    def fake_generate(audio_bytes, mime_type, system_prompt, user_prompt, **kwargs):
        seen.update(
            audio=audio_bytes,
            mime=mime_type,
            system=system_prompt,
            kwargs=kwargs,
        )
        return "metin"

    monkeypatch.setattr(llm, "generate_from_audio", fake_generate)

    asyncio.run(agent.transcribe_audio(AUDIO, mime_type="audio/x-m4a"))

    assert seen["audio"] == AUDIO
    assert seen["mime"] == "audio/x-m4a"
    assert "deşifre" in seen["system"].lower()
    # Transcripts are long; the default 8k output budget would truncate them.
    assert seen["kwargs"]["max_output_tokens"] > 8192


def test_transcription_output_budget_is_configurable(agent, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setenv("MEETING_TRANSCRIPTION_MAX_OUTPUT_TOKENS", "1234")
    seen = {}

    def fake_generate(*args, **kwargs):
        seen.update(kwargs)
        return "metin"

    monkeypatch.setattr(llm, "generate_from_audio", fake_generate)

    asyncio.run(agent.transcribe_audio(AUDIO))

    assert seen["max_output_tokens"] == 1234


def test_thinking_budget_is_forwarded(agent, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    seen = {}

    def fake_generate(*args, **kwargs):
        seen.update(kwargs)
        return "metin"

    monkeypatch.setattr(llm, "generate_from_audio", fake_generate)

    asyncio.run(agent.transcribe_audio(AUDIO, thinking_budget=0))

    assert seen["thinking_budget"] == 0


def test_no_llm_key_skips_instead_of_inventing_a_transcript(agent, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: False)
    monkeypatch.setattr(
        llm,
        "generate_from_audio",
        Mock(side_effect=AssertionError("must not be called")),
    )

    transcript = asyncio.run(agent.transcribe_audio(AUDIO))

    assert transcript == ""
    assert CANNED_OPENING not in transcript
    assert "atlandı" in agent.last_transcription_error
    assert "GEMINI_API_KEY" in agent.last_transcription_error


def test_a_failed_request_returns_nothing_and_records_why(agent, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)

    def boom(*args, **kwargs):
        raise RuntimeError("gemini tüm modellerde başarısız")

    monkeypatch.setattr(llm, "generate_from_audio", boom)

    transcript = asyncio.run(agent.transcribe_audio(AUDIO, source_label="gmail://m1/a1"))

    assert transcript == ""
    assert "gemini tüm modellerde başarısız" in agent.last_transcription_error
    assert "gmail://m1/a1" in agent.last_transcription_error


def test_an_empty_model_answer_is_not_a_transcript(agent, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "generate_from_audio", lambda *a, **k: "   ")

    assert asyncio.run(agent.transcribe_audio(AUDIO)) == ""
    assert agent.last_transcription_error


def test_empty_audio_never_reaches_the_model(agent, monkeypatch):
    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(
        llm,
        "generate_from_audio",
        Mock(side_effect=AssertionError("must not be called")),
    )

    assert asyncio.run(agent.transcribe_audio(b"")) == ""
    assert agent.last_transcription_error


def test_passing_a_url_is_a_clear_type_error(agent):
    """The old signature took a URL; callers must now download first."""
    with pytest.raises(TypeError, match="fetch_audio_bytes"):
        asyncio.run(agent.transcribe_audio("https://example.com/meeting.mp3"))
