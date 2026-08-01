"""LLM provider connection check (Gemini or OpenAI).

Whichever API key is present is used. Gemini is preferred if both are set.
If neither is configured the check is skipped.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_integration
from . import CheckResult
from ._common import classify_response, failed, http_get, http_post
from . import STATUS_SKIPPED

logger = logging.getLogger(__name__)

SPEC = get_integration("llm")
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"

# Default generation models. Kept small/fast; either provider is fine.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Alternate models tried, in order, when the primary one keeps returning
# transient server errors (503 "model overloaded" / 500 / 502 / 504) or is not
# available at all. Overridable via ``GEMINI_FALLBACK_MODELS`` (comma-separated).
DEFAULT_GEMINI_FALLBACK_MODELS = "gemini-flash-latest,gemini-2.0-flash"

# Max output tokens for generation. gemini-2.5-flash is a "thinking" model that
# spends part of its budget on internal reasoning, so a small budget truncates
# the visible answer. Default kept generous (deep, multi-section, source-linked
# briefings need real headroom); overridable via env var.
DEFAULT_GEMINI_MAX_OUTPUT_TOKENS = 8192
GEMINI_MAX_OUTPUT_TOKENS = int(
    os.getenv("GEMINI_MAX_OUTPUT_TOKENS") or DEFAULT_GEMINI_MAX_OUTPUT_TOKENS
)

# Per-request timeout (seconds) for a Gemini generation call, so a hung request
# can never stall the daily job indefinitely.
DEFAULT_GEMINI_TIMEOUT_SECONDS = 120.0

# Transient conditions worth retrying the SAME model for: rate limiting (429)
# and server-side hiccups (500/502/503/504 — "model overloaded", "service
# unavailable", gateway errors).
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)

# Conditions worth moving on to the NEXT model in the chain: everything above
# (still failing after retries) plus 404, which means the model name is not
# available on this endpoint/key.
FALLBACK_STATUS_CODES = RETRYABLE_STATUS_CODES + (404,)

# Wall-clock ceiling for ALL LLM work in one run (``LLM_TIME_BUDGET_SECONDS``).
#
# WHY: retries and model fallback multiply. One generation can spend ~3 minutes
# retrying a rate-limited model, times three models in the chain, and if the
# batched call still fails every advisor repeats that dance on its own. In
# practice a fallback model has so far always answered (gemini-2.5-flash is
# routinely 429 on the free tier, gemini-flash-latest picks it up), but if the
# WHOLE chain is rate limited nothing bounds the fan-out: simulating that case
# costs ~79 minutes and ~120 requests to rediscover, over and over, that the
# quota is still spent — and every attempt digs the hole deeper.
#
# The budget makes the run bounded: once it is spent, further attempts fail
# fast, the remaining sections degrade gracefully (the news advisors still show
# their real RSS headlines, weather is unaffected) and the digest is delivered
# on time instead of an hour late. It only ever cuts short waiting that was
# already failing, so the healthy path is unchanged.
DEFAULT_LLM_TIME_BUDGET_SECONDS = 600.0

# Set by :func:`start_time_budget`. ``None`` means "no budget" — the default for
# library/test use, so importing this module never imposes a deadline.
_budget_started_at: Optional[float] = None


def start_time_budget() -> None:
    """Start (or restart) the shared LLM time budget for this run."""
    global _budget_started_at
    _budget_started_at = time.monotonic()


def clear_time_budget() -> None:
    """Remove the budget, restoring unlimited behaviour."""
    global _budget_started_at
    _budget_started_at = None


# Which model actually served the last successful generation. Purely
# observational (the monitoring dashboard reports it); never a secret, since it
# is only a public model NAME such as ``gemini-2.5-flash``.
_last_model: Optional[str] = None


def _record_model(model: str) -> None:
    global _last_model
    _last_model = model


def last_model() -> Optional[str]:
    """Name of the model that served the last successful generation.

    ``None`` when nothing has been generated in this process yet (no provider
    configured, or every attempt failed).
    """
    return _last_model


# --- per-call accounting ----------------------------------------------------
#
# WHY: the whole advisor team rides on ONE batched generation, and until now
# nothing recorded what that call actually COST. Without token counts there is
# no way to answer the only question that matters on a free tier — "where is the
# quota going, and what can I stop sending?" — so every generation now leaves
# behind a :class:`CallStats` record.
#
# NOTHING SECRET LIVES HERE. Only counters, a wall-clock duration and PUBLIC
# model names (``gemini-2.5-flash``). No prompt, no response, no key: the record
# is written to a file in a public repository (see
# :mod:`ai_assistant.metrics`), so it may only ever contain numbers.


@dataclass
class CallStats:
    """What one generation cost — tokens, wall clock, retries, fallback.

    Attributes:
        provider: ``gemini`` or ``openai``.
        model: The model that actually SERVED the answer (or the last one
            tried, when everything failed). A public name, never a key.
        prompt_tokens: Input tokens billed (Gemini ``promptTokenCount``).
        output_tokens: Visible answer tokens (``candidatesTokenCount``).
        thoughts_tokens: Internal reasoning tokens of a "thinking" model
            (``thoughtsTokenCount``); 0 when the provider does not report any.
        total_tokens: Provider-reported total (``totalTokenCount``), falling
            back to the sum of the three above when it is absent.
        latency_seconds: Wall clock for the whole call INCLUDING retry sleeps
            and fallback attempts — what the run actually waited.
        retries: How many times a request was re-sent after a transient
            failure (429/5xx), summed across every model tried.
        fallback_used: True when the primary model did not serve the answer
            and a model further down the chain had to.
        models_tried: How many models of the chain were attempted.
        ok: Whether a usable answer came back at all.
    """

    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    output_tokens: int = 0
    thoughts_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0
    retries: int = 0
    fallback_used: bool = False
    models_tried: int = 0
    ok: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "prompt_tokens": int(self.prompt_tokens),
            "output_tokens": int(self.output_tokens),
            "thoughts_tokens": int(self.thoughts_tokens),
            "total_tokens": int(self.total_tokens),
            "latency_seconds": round(float(self.latency_seconds), 2),
            "retries": int(self.retries),
            "fallback_used": bool(self.fallback_used),
            "models_tried": int(self.models_tried),
            "ok": bool(self.ok),
        }


_last_call: Optional[CallStats] = None


def _record_call(stats: CallStats) -> None:
    global _last_call
    _last_call = stats


def last_call_stats() -> Optional[CallStats]:
    """Cost of the most recent generation in this process, or ``None``.

    ``None`` means no generation was even attempted (no provider configured, or
    a quiet incremental run where nobody had anything new to say).
    """
    return _last_call


def reset_call_stats() -> None:
    """Forget the recorded call — used by tests and by long-lived processes."""
    global _last_call
    _last_call = None


def _int(value: Any) -> int:
    """Coerce a provider-reported counter to a non-negative int, never raising."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def _gemini_usage(data: dict) -> Dict[str, int]:
    """Read ``usageMetadata`` off a generateContent payload.

    Every field is optional in practice (older models omit
    ``thoughtsTokenCount`` entirely, and a malformed payload may omit the block
    altogether), so each one degrades to 0 and the total is reconstructed when
    the provider did not send it.
    """
    usage = data.get("usageMetadata") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        usage = {}
    prompt = _int(usage.get("promptTokenCount"))
    output = _int(usage.get("candidatesTokenCount"))
    thoughts = _int(usage.get("thoughtsTokenCount"))
    total = _int(usage.get("totalTokenCount")) or (prompt + output + thoughts)
    return {
        "prompt_tokens": prompt,
        "output_tokens": output,
        "thoughts_tokens": thoughts,
        "total_tokens": total,
    }


def _openai_usage(data: dict) -> Dict[str, int]:
    """The same counters from an OpenAI chat-completions payload."""
    usage = data.get("usage") if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        usage = {}
    details = usage.get("completion_tokens_details")
    thoughts = (
        _int(details.get("reasoning_tokens")) if isinstance(details, dict) else 0
    )
    prompt = _int(usage.get("prompt_tokens"))
    output = _int(usage.get("completion_tokens"))
    total = _int(usage.get("total_tokens")) or (prompt + output)
    return {
        "prompt_tokens": prompt,
        "output_tokens": output,
        "thoughts_tokens": thoughts,
        "total_tokens": total,
    }


def _time_budget_seconds() -> float:
    """The configured budget; ``0`` or less disables it."""
    try:
        return float(
            os.getenv("LLM_TIME_BUDGET_SECONDS") or DEFAULT_LLM_TIME_BUDGET_SECONDS
        )
    except ValueError:
        return DEFAULT_LLM_TIME_BUDGET_SECONDS


def time_budget_remaining() -> Optional[float]:
    """Seconds left in the budget, or ``None`` when no budget applies."""
    if _budget_started_at is None:
        return None
    budget = _time_budget_seconds()
    if budget <= 0:
        return None
    return budget - (time.monotonic() - _budget_started_at)


def time_budget_exhausted() -> bool:
    """True once this run has spent its whole LLM time budget."""
    remaining = time_budget_remaining()
    return remaining is not None and remaining <= 0


def _redact_key(text: str, key: str = "") -> str:
    """Strip any API key from an error/log string.

    Removes both ``key=<value>`` URL query params and the raw key value so the
    secret can never surface in an advisor's ``failed`` message (which may be
    posted to Slack) or in logs.
    """
    if not text:
        return text
    # Redact `?key=...` / `&key=...` query params regardless of the value.
    redacted = re.sub(r"([?&]key=)[^&\s\"']+", r"\1REDACTED", text)
    # Belt-and-braces: scrub the literal key value if we know it.
    if key:
        redacted = redacted.replace(key, "REDACTED")
    return redacted


def _gemini_retry_config() -> tuple[int, float]:
    """Read retry knobs from the environment at call time.

    ``GEMINI_MAX_RETRIES`` (default 4) and ``GEMINI_RETRY_BASE_SECONDS``
    (default 20) are read lazily so tests can override them per-call.
    """
    try:
        max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "4"))
    except ValueError:
        max_retries = 4
    try:
        base = float(os.getenv("GEMINI_RETRY_BASE_SECONDS", "20"))
    except ValueError:
        base = 20.0
    return max(0, max_retries), max(0.0, base)


def _gemini_timeout() -> float:
    """Per-request timeout for a Gemini call (``GEMINI_TIMEOUT_SECONDS``)."""
    try:
        timeout = float(
            os.getenv("GEMINI_TIMEOUT_SECONDS") or DEFAULT_GEMINI_TIMEOUT_SECONDS
        )
    except ValueError:
        timeout = DEFAULT_GEMINI_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_GEMINI_TIMEOUT_SECONDS


def _gemini_max_output_tokens() -> int:
    """Output-token budget, read at call time so tests/env can override it."""
    try:
        tokens = int(
            os.getenv("GEMINI_MAX_OUTPUT_TOKENS") or DEFAULT_GEMINI_MAX_OUTPUT_TOKENS
        )
    except ValueError:
        tokens = DEFAULT_GEMINI_MAX_OUTPUT_TOKENS
    return tokens if tokens > 0 else DEFAULT_GEMINI_MAX_OUTPUT_TOKENS


def _gemini_model_chain() -> List[str]:
    """Ordered list of models to try: primary first, then the fallbacks.

    The primary comes from ``GEMINI_MODEL`` (default ``gemini-2.5-flash``); the
    fallbacks from ``GEMINI_FALLBACK_MODELS`` (comma-separated, default
    ``gemini-flash-latest,gemini-2.0-flash``). Duplicates are dropped so the
    primary is never queried twice.
    """
    primary = (os.getenv("GEMINI_MODEL") or "").strip() or DEFAULT_GEMINI_MODEL
    # An unset GitHub secret expands to an empty string, so treat blank as
    # "use the built-in chain" rather than "disable the fallbacks".
    raw = (os.getenv("GEMINI_FALLBACK_MODELS") or "").strip()
    if not raw:
        raw = DEFAULT_GEMINI_FALLBACK_MODELS
    chain: List[str] = []
    for model in [primary] + [part.strip() for part in raw.split(",")]:
        if model and model not in chain:
            chain.append(model)
    return chain


def _retry_delay(resp: httpx.Response, attempt: int, base: float) -> float:
    """Seconds to wait before the next retry of a transient failure.

    Honours the ``Retry-After`` header when present, otherwise exponential
    backoff capped at ``3 * base`` (e.g. 20s, 40s, 60s, 60s for base=20).
    """
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return min(base * (attempt + 1), base * 3)


def _apply_request_spacing() -> None:
    """Optionally pause before a request to spread calls across quota windows.

    Off by default (``GEMINI_REQUEST_SPACING_SECONDS`` unset/0) so offline
    tests and local runs stay fast; the daily workflow can raise it.
    """
    try:
        spacing = float(os.getenv("GEMINI_REQUEST_SPACING_SECONDS", "0"))
    except ValueError:
        spacing = 0.0
    if spacing > 0:
        time.sleep(spacing)


def _post_gemini_with_retry(
    url: str, headers: dict, payload: dict
) -> tuple[httpx.Response, int]:
    """POST to Gemini, retrying transient failures with backoff.

    Retries on rate limiting (429) AND on transient server errors
    (500/502/503/504 — the "model is overloaded" / "service unavailable"
    family), honouring ``Retry-After`` when the API sends it.

    Returns ``(response, retries)``. The response may still be a failure once
    retries are exhausted; callers either fall back to the next model or turn it
    into a graceful failure. ``retries`` counts the RE-sends (0 = answered
    first try) and is recorded on :class:`CallStats` so the dashboard can show
    how much of a run was spent fighting the quota.
    """
    max_retries, base = _gemini_retry_config()
    attempt = 0
    while True:
        resp = http_post(url, headers=headers, json=payload, timeout=_gemini_timeout())
        if resp.status_code not in RETRYABLE_STATUS_CODES or attempt >= max_retries:
            return resp, attempt
        delay = _retry_delay(resp, attempt, base)
        # Never sleep past the run's budget: waiting out a quota window we no
        # longer have time for only delays the digest.
        remaining = time_budget_remaining()
        if remaining is not None and delay >= remaining:
            logger.warning(
                "kalan süre bütçesi (%.0fs) yeniden denemeye yetmiyor, vazgeçiliyor",
                max(0.0, remaining),
            )
            return resp, attempt
        time.sleep(delay)
        attempt += 1


def check_connection() -> CheckResult:
    """Ping the configured LLM provider's model-list endpoint."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not gemini_key and not openai_key:
        return CheckResult(
            name=SPEC.name,
            status=STATUS_SKIPPED,
            detail="missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY",
        )

    if gemini_key:
        try:
            resp = http_get(
                GEMINI_MODELS_URL,
                headers={"X-goog-api-key": gemini_key},
            )
        except Exception as exc:
            return failed(SPEC.name, _redact_key(f"request error (gemini): {exc}", gemini_key))
        result = classify_response(SPEC.name, resp)
        result.detail = f"gemini — {result.detail}"
        return result

    # OpenAI fallback.
    try:
        resp = http_get(
            OPENAI_MODELS_URL,
            headers={"Authorization": f"Bearer {openai_key}"},
        )
    except Exception as exc:
        return failed(SPEC.name, f"request error (openai): {exc}")
    result = classify_response(SPEC.name, resp)
    result.detail = f"openai — {result.detail}"
    return result


def configured_provider() -> Optional[str]:
    """Return the name of the configured LLM provider, or ``None``.

    Gemini is preferred when both keys are present (matching
    :func:`check_connection`).
    """
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return None


def is_configured() -> bool:
    """True if any LLM provider key is present in the environment."""
    return configured_provider() is not None


def generate_text(
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: Optional[int] = None,
) -> str:
    """Generate a completion from the configured LLM provider.

    Reuses the same provider selection as :func:`check_connection` (Gemini
    preferred, OpenAI fallback). ``max_output_tokens`` overrides the default
    budget — the batched digest asks for the whole team's briefing in one
    response and needs far more headroom than a single section. Raises
    ``RuntimeError`` if no provider is configured, and lets transport/HTTP
    errors propagate (key-redacted) so callers can convert them into a
    graceful ``failed`` result.
    """
    provider = configured_provider()
    if provider is None:
        raise RuntimeError("no LLM provider configured (GEMINI_API_KEY or OPENAI_API_KEY)")

    if provider == "gemini":
        return _generate_gemini(system_prompt, user_prompt, max_output_tokens)
    return _generate_openai(system_prompt, user_prompt, max_output_tokens)


def _extract_gemini_text(data: dict) -> str:
    """Pull the answer text out of a generateContent payload (may be empty)."""
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts).strip()


def _generate_gemini(
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: Optional[int] = None,
) -> str:
    """Generate with Gemini, retrying transients and falling back per model.

    Walks :func:`_gemini_model_chain`. Each model gets the full retry budget;
    if it still returns a transient/unavailable status (or an empty answer, or
    a transport error such as a timeout) the next model in the chain is tried
    transparently. Hard errors (400/401/403 — bad request or bad key) fail fast.
    Every surfaced message is passed through :func:`_redact_key` first.
    """
    key = os.getenv("GEMINI_API_KEY", "")
    # Send the key via header (Google's recommended method) so it never lands
    # in the URL and therefore never leaks into httpx error strings/logs.
    headers = {"X-goog-api-key": key}
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": max_output_tokens or _gemini_max_output_tokens(),
        },
    }

    models = _gemini_model_chain()
    last_error = "bilinmeyen hata"

    # Cost accounting for THIS call: wall clock across every model and every
    # retry, so the dashboard reports what the run really waited for.
    started = time.monotonic()
    stats = CallStats(provider="gemini")

    for position, model in enumerate(models):
        stats.models_tried = position + 1
        stats.model = model
        if time_budget_exhausted():
            # Every remaining model would hit the same exhausted quota window;
            # fail fast so the digest still goes out with what we do have.
            last_error = f"süre bütçesi doldu, denenmedi: {model}"
            logger.warning(
                "süre bütçesi doldu; '%s' ve sonraki modeller denenmiyor", model
            )
            break

        url = f"{GEMINI_MODELS_URL}/{model}:generateContent"
        _apply_request_spacing()
        try:
            resp, retries = _post_gemini_with_retry(url, headers, payload)
            stats.retries += retries
        except Exception as exc:
            # Transport-level problem (timeout, DNS, TLS): try the next model.
            last_error = _redact_key(f"{model}: {exc}", key)
            logger.warning("gemini modeli '%s' ulaşılamadı: %s", model, last_error)
            continue

        if resp.status_code in FALLBACK_STATUS_CODES:
            snippet = resp.text.strip().replace("\n", " ")[:160]
            last_error = _redact_key(
                f"{model}: HTTP {resp.status_code}: {snippet}", key
            )
            logger.warning(
                "gemini modeli '%s' geçici olarak kullanılamadı (HTTP %s), "
                "sıradaki modele geçiliyor",
                model,
                resp.status_code,
            )
            continue

        try:
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            # Redact the key from any transport/HTTP error before it propagates
            # into an advisor's failed message (which may reach Slack).
            stats.latency_seconds = time.monotonic() - started
            _record_call(stats)
            raise RuntimeError(_redact_key(f"{model}: {exc}", key)) from None

        text = _extract_gemini_text(data)
        if not text:
            last_error = f"{model}: gemini boş yanıt döndürdü"
            logger.warning("gemini modeli '%s' boş yanıt döndürdü", model)
            continue

        # Log WHICH model actually served the answer (never the key).
        logger.info("gemini yanıtı '%s' modelinden alındı", model)
        _record_model(model)
        for name, value in _gemini_usage(data).items():
            setattr(stats, name, value)
        stats.ok = True
        # "Fallback" means the PRIMARY model did not serve this answer.
        stats.fallback_used = position > 0
        stats.latency_seconds = time.monotonic() - started
        _record_call(stats)
        logger.info(
            "token kullanımı: girdi %s · çıktı %s · düşünme %s · toplam %s (%.1fs)",
            stats.prompt_tokens,
            stats.output_tokens,
            stats.thoughts_tokens,
            stats.total_tokens,
            stats.latency_seconds,
        )
        return text

    stats.fallback_used = len(models) > 1
    stats.latency_seconds = time.monotonic() - started
    _record_call(stats)
    raise RuntimeError(
        f"gemini tüm modellerde başarısız ({', '.join(models)}) — son hata: {last_error}"
    )


def _generate_openai(
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: Optional[int] = None,
) -> str:
    key = os.getenv("OPENAI_API_KEY", "")
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        # Same budget as Gemini: the deep, multi-section briefings need headroom.
        "max_tokens": max_output_tokens or _gemini_max_output_tokens(),
    }
    started = time.monotonic()
    stats = CallStats(provider="openai", model=OPENAI_MODEL, models_tried=1)
    try:
        resp = http_post(
            url,
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
            timeout=_gemini_timeout(),
        )
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("openai returned no choices")
        text = (choices[0].get("message", {}).get("content") or "").strip()
        if not text:
            raise RuntimeError("openai returned empty text")
    except Exception:
        stats.latency_seconds = time.monotonic() - started
        _record_call(stats)
        raise
    _record_model(OPENAI_MODEL)
    for name, value in _openai_usage(data).items():
        setattr(stats, name, value)
    stats.ok = True
    stats.latency_seconds = time.monotonic() - started
    _record_call(stats)
    return text
