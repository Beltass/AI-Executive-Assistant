"""Tests for the Gemini LLM integration (offline, no real network).

Covers the security + resilience hardening:
- the API key is sent via the ``X-goog-api-key`` header, never in the URL;
- HTTP 429 responses are retried with backoff;
- when retries are exhausted the raised error is REDACTED so the key can
  never leak into an advisor's failed message / Slack / logs.
"""

from __future__ import annotations

import httpx
import pytest

from ai_assistant.integrations import llm

FAKE_KEY = "AQ.FAKE-secret-key-should-never-leak-123456"


def _resp(status_code: int, headers: dict | None = None) -> httpx.Response:
    """Build an httpx.Response bound to a request (so raise_for_status works)."""
    request = httpx.Request(
        "POST",
        "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent",
    )
    return httpx.Response(status_code, headers=headers or {}, request=request)


def test_redact_key_strips_query_param_and_raw_value():
    raw = f"error for url ...:generateContent?key={FAKE_KEY} boom {FAKE_KEY}"
    redacted = llm._redact_key(raw, FAKE_KEY)
    assert FAKE_KEY not in redacted
    assert "key=REDACTED" in redacted


def test_gemini_uses_header_not_url(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    captured = {}

    def fake_post(url, headers=None, json=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        return _resp(200)

    def fake_json(self):
        return {"candidates": [{"content": {"parts": [{"text": "merhaba"}]}}]}

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(httpx.Response, "json", fake_json, raising=False)

    text = llm.generate_text("sys", "user")

    assert text == "merhaba"
    assert "key=" not in captured["url"]
    assert captured["headers"].get("X-goog-api-key") == FAKE_KEY


def test_gemini_retries_on_429_and_redacts_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "3")
    monkeypatch.setenv("GEMINI_RETRY_BASE_SECONDS", "0")  # keep the test fast
    monkeypatch.setenv("GEMINI_REQUEST_SPACING_SECONDS", "0")

    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_post(url, headers=None, json=None):
        calls["n"] += 1
        # Always 429 so retries are exhausted; URL never carries the key.
        assert "key=" not in url
        return _resp(429)

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(RuntimeError) as excinfo:
        llm.generate_text("sys", "user")

    # 1 initial attempt + 3 retries = 4 calls; 3 backoff sleeps.
    assert calls["n"] == 4
    assert len(sleeps) == 3
    # The key must not appear anywhere in the surfaced error.
    assert FAKE_KEY not in str(excinfo.value)


def test_gemini_honors_retry_after_header(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "1")
    monkeypatch.setenv("GEMINI_RETRY_BASE_SECONDS", "20")

    sleeps: list[float] = []
    responses = [_resp(429, {"Retry-After": "7"}), _resp(200)]

    def fake_post(url, headers=None, json=None):
        return responses.pop(0)

    def fake_json(self):
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(httpx.Response, "json", fake_json, raising=False)

    text = llm.generate_text("sys", "user")

    assert text == "ok"
    assert sleeps == [7.0]  # honored the Retry-After header, not the backoff
