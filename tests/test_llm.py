"""Tests for the Gemini LLM integration (offline, no real network).

Covers the security + resilience hardening:
- the API key is sent via the ``X-goog-api-key`` header, never in the URL;
- HTTP 429 AND transient server errors (500/502/503/504) are retried with
  backoff, honouring ``Retry-After``;
- a model that keeps failing is transparently swapped for the next one in the
  fallback chain;
- every surfaced error is REDACTED so the key can never leak into an advisor's
  failed message / Slack / logs.

All sleeps are patched out, so the suite stays fast.
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


@pytest.fixture()
def gemini_env(monkeypatch):
    """A Gemini-only environment with fast, deterministic retry settings."""
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_RETRY_BASE_SECONDS", "0")
    monkeypatch.setenv("GEMINI_REQUEST_SPACING_SECONDS", "0")
    monkeypatch.delenv("LLM_TIME_BUDGET_SECONDS", raising=False)
    llm.clear_time_budget()  # no deadline unless a test starts one
    yield
    llm.clear_time_budget()


def _single_model_chain(monkeypatch):
    """Reduce the chain to the primary model so retries can be counted alone."""
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS", raising=False)
    monkeypatch.setattr(llm, "DEFAULT_GEMINI_FALLBACK_MODELS", "")


def test_blank_fallback_env_keeps_the_builtin_chain(monkeypatch):
    """An unset GitHub secret expands to "" — it must not disable fallbacks."""
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "  ")
    assert llm._gemini_model_chain() == [
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.0-flash",
    ]


def test_redact_key_strips_query_param_and_raw_value():
    raw = f"error for url ...:generateContent?key={FAKE_KEY} boom {FAKE_KEY}"
    redacted = llm._redact_key(raw, FAKE_KEY)
    assert FAKE_KEY not in redacted
    assert "key=REDACTED" in redacted


def test_model_chain_defaults_to_primary_then_fallbacks(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_FALLBACK_MODELS", raising=False)
    assert llm._gemini_model_chain() == [
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-2.0-flash",
    ]


def test_model_chain_is_overridable_and_deduplicated(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-2.0-flash, my-model ,")
    assert llm._gemini_model_chain() == ["gemini-2.0-flash", "my-model"]


def test_default_max_output_tokens_is_8192(monkeypatch):
    monkeypatch.delenv("GEMINI_MAX_OUTPUT_TOKENS", raising=False)
    assert llm._gemini_max_output_tokens() == 8192


def test_gemini_uses_header_not_url(monkeypatch, gemini_env):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["timeout"] = timeout
        captured["payload"] = json
        return _resp(200)

    def fake_json(self):
        return {"candidates": [{"content": {"parts": [{"text": "merhaba"}]}}]}

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(httpx.Response, "json", fake_json, raising=False)

    text = llm.generate_text("sys", "user")

    assert text == "merhaba"
    assert "key=" not in captured["url"]
    assert captured["headers"].get("X-goog-api-key") == FAKE_KEY
    # A per-request timeout is always sent so a hung call can't stall the job.
    assert captured["timeout"] == 120.0


def test_generate_text_honors_max_output_tokens_override(monkeypatch, gemini_env):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _resp(200)

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(
        httpx.Response,
        "json",
        lambda self: {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        raising=False,
    )

    llm.generate_text("sys", "user", max_output_tokens=32768)

    assert captured["payload"]["generationConfig"]["maxOutputTokens"] == 32768


def test_gemini_retries_on_429_and_redacts_key(monkeypatch, gemini_env):
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "3")
    _single_model_chain(monkeypatch)  # isolate retry behaviour

    calls = {"n": 0}
    sleeps: list[float] = []

    def fake_post(url, headers=None, json=None, timeout=None):
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


@pytest.mark.parametrize("status", [500, 502, 503, 504])
def test_gemini_retries_transient_server_errors(monkeypatch, gemini_env, status):
    """The reported bug: a 503 used to give up immediately. Now it retries."""
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "2")
    _single_model_chain(monkeypatch)  # isolate retry behaviour

    calls = {"n": 0}
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        # Succeed on the last allowed attempt to prove the retry paid off.
        if calls["n"] > 2:
            return _resp(200)
        return _resp(status, {"Retry-After": "1"})

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(
        httpx.Response,
        "json",
        lambda self: {"candidates": [{"content": {"parts": [{"text": "kurtardık"}]}}]},
        raising=False,
    )

    assert llm.generate_text("sys", "user") == "kurtardık"
    assert calls["n"] == 3


def test_gemini_falls_back_to_next_model_on_503(monkeypatch, gemini_env):
    """503 "model overloaded" on the primary transparently uses the next model."""
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "1")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-flash-latest,gemini-2.0-flash")

    seen_models: list[str] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    def fake_post(url, headers=None, json=None, timeout=None):
        model = url.rsplit("/", 1)[-1].split(":")[0]
        seen_models.append(model)
        if model == "gemini-2.5-flash":
            return _resp(503)
        return _resp(200)

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(
        httpx.Response,
        "json",
        lambda self: {
            "candidates": [{"content": {"parts": [{"text": "yedek model"}]}}]
        },
        raising=False,
    )

    text = llm.generate_text("sys", "user")

    assert text == "yedek model"
    # Primary tried (initial + 1 retry) and then the first fallback served it.
    assert seen_models == [
        "gemini-2.5-flash",
        "gemini-2.5-flash",
        "gemini-flash-latest",
    ]


def test_gemini_all_models_fail_error_is_redacted(monkeypatch, gemini_env):
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "0")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-flash-latest,gemini-2.0-flash")

    def fake_post(url, headers=None, json=None, timeout=None):
        # A hostile body that echoes the key back at us.
        return httpx.Response(
            503,
            text=f"model overloaded for key={FAKE_KEY} ({FAKE_KEY})",
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError) as excinfo:
        llm.generate_text("sys", "user")

    message = str(excinfo.value)
    assert FAKE_KEY not in message
    assert "gemini-2.0-flash" in message  # every model in the chain was tried


def test_gemini_falls_back_when_a_model_times_out(monkeypatch, gemini_env):
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "0")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-flash-latest")

    seen_models: list[str] = []

    def fake_post(url, headers=None, json=None, timeout=None):
        model = url.rsplit("/", 1)[-1].split(":")[0]
        seen_models.append(model)
        if model == "gemini-2.5-flash":
            raise httpx.ReadTimeout(f"timed out (key={FAKE_KEY})")
        return _resp(200)

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(
        httpx.Response,
        "json",
        lambda self: {"candidates": [{"content": {"parts": [{"text": "yedek"}]}}]},
        raising=False,
    )

    assert llm.generate_text("sys", "user") == "yedek"
    assert seen_models == ["gemini-2.5-flash", "gemini-flash-latest"]


def test_gemini_honors_retry_after_header(monkeypatch, gemini_env):
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "1")
    monkeypatch.setenv("GEMINI_RETRY_BASE_SECONDS", "20")

    sleeps: list[float] = []
    responses = [_resp(429, {"Retry-After": "7"}), _resp(200)]

    def fake_post(url, headers=None, json=None, timeout=None):
        return responses.pop(0)

    def fake_json(self):
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(httpx.Response, "json", fake_json, raising=False)

    text = llm.generate_text("sys", "user")

    assert text == "ok"
    assert sleeps == [7.0]  # honored the Retry-After header, not the backoff


def test_gemini_hard_error_fails_fast_and_is_redacted(monkeypatch, gemini_env):
    """A bad key (401) must NOT burn the whole fallback chain."""
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "2")

    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return httpx.Response(
            401,
            text=f"invalid key={FAKE_KEY}",
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError) as excinfo:
        llm.generate_text("sys", "user")

    assert calls["n"] == 1
    assert FAKE_KEY not in str(excinfo.value)


# --- shared LLM time budget -------------------------------------------------
#
# Retries multiply with the model fallback chain, and again with the
# per-advisor path, so an exhausted quota could stretch a run past an hour.
# One shared wall-clock budget keeps the job bounded.


def test_no_budget_by_default(gemini_env):
    """Library/test use must stay unlimited unless a run starts a budget."""
    assert llm.time_budget_remaining() is None
    assert llm.time_budget_exhausted() is False


def test_budget_can_be_disabled_with_zero(monkeypatch, gemini_env):
    monkeypatch.setenv("LLM_TIME_BUDGET_SECONDS", "0")
    llm.start_time_budget()
    assert llm.time_budget_remaining() is None
    assert llm.time_budget_exhausted() is False


def test_exhausted_budget_skips_every_remaining_model(monkeypatch, gemini_env):
    """Once the budget is spent, no further model is even attempted."""
    monkeypatch.setenv("LLM_TIME_BUDGET_SECONDS", "600")
    llm.start_time_budget()
    # Jump the clock past the budget.
    monkeypatch.setattr(llm.time, "monotonic", lambda: llm._budget_started_at + 601)

    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return _resp(200)

    monkeypatch.setattr(llm, "http_post", fake_post)

    with pytest.raises(RuntimeError) as excinfo:
        llm.generate_text("sys", "user")

    assert calls["n"] == 0  # not a single request was made
    assert "süre bütçesi" in str(excinfo.value)
    assert FAKE_KEY not in str(excinfo.value)


def test_retry_does_not_sleep_past_the_budget(monkeypatch, gemini_env):
    """A backoff longer than the time left is abandoned, not slept through."""
    _single_model_chain(monkeypatch)
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "4")
    monkeypatch.setenv("GEMINI_RETRY_BASE_SECONDS", "20")
    monkeypatch.setenv("LLM_TIME_BUDGET_SECONDS", "600")

    llm.start_time_budget()
    started = llm._budget_started_at
    # Only 5 seconds left — shorter than the 20s first backoff.
    monkeypatch.setattr(llm.time, "monotonic", lambda: started + 595)

    calls = {"n": 0}
    sleeps = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return _resp(429)

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))

    with pytest.raises(RuntimeError):
        llm.generate_text("sys", "user")

    assert sleeps == []  # never waited out a window we had no time for
    assert calls["n"] == 1  # one attempt, then gave up instead of 5


def test_budget_still_allows_a_retry_that_fits(monkeypatch, gemini_env):
    """A backoff shorter than the remaining time is still honoured."""
    _single_model_chain(monkeypatch)
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "1")
    monkeypatch.setenv("GEMINI_RETRY_BASE_SECONDS", "20")
    monkeypatch.setenv("LLM_TIME_BUDGET_SECONDS", "600")

    llm.start_time_budget()
    started = llm._budget_started_at
    monkeypatch.setattr(llm.time, "monotonic", lambda: started + 100)  # 500s left

    responses = [_resp(429), _resp(200)]
    sleeps = []

    monkeypatch.setattr(llm, "http_post", lambda url, **kw: responses.pop(0))
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(
        httpx.Response,
        "json",
        lambda self: {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        raising=False,
    )

    assert llm.generate_text("sys", "user") == "ok"
    assert sleeps == [20.0]


# --- per-call cost accounting ----------------------------------------------
#
# The whole team rides on ONE batched generation, so what that call COST is the
# only lever the user has on a free tier. These tests pin down that the numbers
# reported are the provider's own, never guessed, and that a failed call still
# leaves a record behind.


def _usage_payload(text: str = "merhaba", **usage) -> dict:
    counters = {
        "promptTokenCount": 1200,
        "candidatesTokenCount": 800,
        "thoughtsTokenCount": 300,
        "totalTokenCount": 2300,
    }
    counters.update(usage)
    return {
        "candidates": [{"content": {"parts": [{"text": text}]}}],
        "usageMetadata": counters,
    }


def test_usage_metadata_is_captured_from_the_response(monkeypatch, gemini_env):
    monkeypatch.setattr(llm, "http_post", lambda *a, **k: _resp(200))
    monkeypatch.setattr(
        httpx.Response, "json", lambda self: _usage_payload(), raising=False
    )

    llm.generate_text("sys", "user")

    stats = llm.last_call_stats()
    assert stats is not None
    assert stats.prompt_tokens == 1200
    assert stats.output_tokens == 800
    assert stats.thoughts_tokens == 300
    assert stats.total_tokens == 2300
    assert stats.ok is True
    assert stats.provider == "gemini"
    assert stats.model == "gemini-2.5-flash"
    assert stats.retries == 0
    assert stats.fallback_used is False
    assert stats.latency_seconds >= 0


def test_missing_thoughts_token_count_degrades_to_zero(monkeypatch, gemini_env):
    """Non-thinking models omit the field entirely; that is not an error."""
    payload = {
        "candidates": [{"content": {"parts": [{"text": "x"}]}}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
    }
    monkeypatch.setattr(llm, "http_post", lambda *a, **k: _resp(200))
    monkeypatch.setattr(httpx.Response, "json", lambda self: payload, raising=False)

    llm.generate_text("sys", "user")

    stats = llm.last_call_stats()
    assert stats.thoughts_tokens == 0
    # No totalTokenCount either: it is reconstructed rather than left at zero.
    assert stats.total_tokens == 15


def test_absent_usage_metadata_is_zero_not_a_crash(monkeypatch, gemini_env):
    monkeypatch.setattr(llm, "http_post", lambda *a, **k: _resp(200))
    monkeypatch.setattr(
        httpx.Response,
        "json",
        lambda self: {"candidates": [{"content": {"parts": [{"text": "x"}]}}]},
        raising=False,
    )

    assert llm.generate_text("sys", "user") == "x"
    assert llm.last_call_stats().total_tokens == 0


def test_retries_are_counted_on_the_call_record(monkeypatch, gemini_env):
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "3")
    _single_model_chain(monkeypatch)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    calls = {"n": 0}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        return _resp(200 if calls["n"] > 2 else 429)

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(
        httpx.Response, "json", lambda self: _usage_payload(), raising=False
    )

    llm.generate_text("sys", "user")

    assert llm.last_call_stats().retries == 2


def test_falling_back_to_the_second_model_is_recorded(monkeypatch, gemini_env):
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "0")
    monkeypatch.setenv("GEMINI_FALLBACK_MODELS", "gemini-flash-latest")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)

    def fake_post(url, headers=None, json=None, timeout=None):
        return _resp(503 if "gemini-2.5-flash" in url else 200)

    monkeypatch.setattr(llm, "http_post", fake_post)
    monkeypatch.setattr(
        httpx.Response, "json", lambda self: _usage_payload(), raising=False
    )

    llm.generate_text("sys", "user")

    stats = llm.last_call_stats()
    assert stats.fallback_used is True
    assert stats.model == "gemini-flash-latest"
    assert stats.models_tried == 2


def test_a_failed_call_still_leaves_a_cost_record(monkeypatch, gemini_env):
    """Latency and retries spent on a doomed call are exactly what we must see."""
    monkeypatch.setenv("GEMINI_MAX_RETRIES", "1")
    _single_model_chain(monkeypatch)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm, "http_post", lambda *a, **k: _resp(429))

    with pytest.raises(RuntimeError):
        llm.generate_text("sys", "user")

    stats = llm.last_call_stats()
    assert stats is not None
    assert stats.ok is False
    assert stats.retries == 1


def test_no_generation_means_no_call_record():
    assert llm.last_call_stats() is None


def test_call_stats_dict_carries_no_secret(monkeypatch, gemini_env):
    """The record is written to a PUBLIC file: it may only contain numbers."""
    monkeypatch.setattr(llm, "http_post", lambda *a, **k: _resp(200))
    monkeypatch.setattr(
        httpx.Response, "json", lambda self: _usage_payload(), raising=False
    )

    llm.generate_text("sys", "user")

    payload = llm.last_call_stats().to_dict()
    assert FAKE_KEY not in str(payload)
    # Only counters, a public model name and a provider name.
    assert payload["model"] == "gemini-2.5-flash"
    assert set(payload) == {
        "provider",
        "model",
        "prompt_tokens",
        "output_tokens",
        "thoughts_tokens",
        "total_tokens",
        "latency_seconds",
        "retries",
        "fallback_used",
        "models_tried",
        "ok",
    }


def test_openai_usage_is_captured_too(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key-for-tests-1234567890")
    payload = {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {
            "prompt_tokens": 90,
            "completion_tokens": 40,
            "total_tokens": 130,
            "completion_tokens_details": {"reasoning_tokens": 12},
        },
    }
    monkeypatch.setattr(llm, "http_post", lambda *a, **k: _resp(200))
    monkeypatch.setattr(httpx.Response, "json", lambda self: payload, raising=False)

    assert llm.generate_text("sys", "user") == "hello"

    stats = llm.last_call_stats()
    assert stats.provider == "openai"
    assert (stats.prompt_tokens, stats.output_tokens, stats.total_tokens) == (
        90,
        40,
        130,
    )
    assert stats.thoughts_tokens == 12


# --- counting the calls, and paying for no thinking on structured work -------


def test_every_generation_is_counted(monkeypatch, gemini_env):
    """``last_call_stats`` describes the last call; this counts them all.

    One batched call for the whole team and fifteen per-advisor retries after
    a failed batch look identical in the token record of the LAST call — the
    count is what makes the difference visible in the metrics file.
    """
    monkeypatch.setattr(llm, "http_post", lambda *a, **k: _resp(200))
    monkeypatch.setattr(
        httpx.Response, "json", lambda self: _usage_payload(), raising=False
    )

    llm.start_time_budget()
    assert llm.call_count() == 0

    llm.generate_text("sys", "user")
    llm.generate_text("sys", "user")

    assert llm.call_count() == 2

    llm.start_time_budget()  # a new run starts from zero
    assert llm.call_count() == 0


def test_a_failed_generation_is_counted_too(monkeypatch, gemini_env):
    """A call that cost quota and returned nothing still cost quota."""
    monkeypatch.setattr(llm, "http_post", lambda *a, **k: _resp(400, "bad"))
    llm.start_time_budget()

    with pytest.raises(Exception):
        llm.generate_text("sys", "user")

    assert llm.call_count() == 1


def test_structured_callers_ask_for_no_thinking_budget(monkeypatch, gemini_env):
    """Summarising a note has nothing to reason about — see ``ask._generate_summary``."""
    from ai_assistant.chat import ask

    sent = {}

    def fake_generate(system_prompt, user_prompt, **kwargs):
        sent.update(kwargs)
        return "özet"

    monkeypatch.setattr(ask.llm, "generate_text", fake_generate)
    ask._generate_summary("sys", "user")

    assert sent["thinking_budget"] == llm.STRUCTURED_THINKING_BUDGET == 0
