"""LLM provider connection check (Gemini or OpenAI).

Whichever API key is present is used. Gemini is preferred if both are set.
If neither is configured the check is skipped.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import List, Optional

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


def _post_gemini_with_retry(url: str, headers: dict, payload: dict) -> httpx.Response:
    """POST to Gemini, retrying transient failures with backoff.

    Retries on rate limiting (429) AND on transient server errors
    (500/502/503/504 — the "model is overloaded" / "service unavailable"
    family), honouring ``Retry-After`` when the API sends it.

    Returns the final response (which may still be a failure once retries are
    exhausted); callers either fall back to the next model or turn it into a
    graceful failure.
    """
    max_retries, base = _gemini_retry_config()
    attempt = 0
    while True:
        resp = http_post(url, headers=headers, json=payload, timeout=_gemini_timeout())
        if resp.status_code not in RETRYABLE_STATUS_CODES or attempt >= max_retries:
            return resp
        time.sleep(_retry_delay(resp, attempt, base))
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

    for model in models:
        url = f"{GEMINI_MODELS_URL}/{model}:generateContent"
        _apply_request_spacing()
        try:
            resp = _post_gemini_with_retry(url, headers, payload)
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
            raise RuntimeError(_redact_key(f"{model}: {exc}", key)) from None

        text = _extract_gemini_text(data)
        if not text:
            last_error = f"{model}: gemini boş yanıt döndürdü"
            logger.warning("gemini modeli '%s' boş yanıt döndürdü", model)
            continue

        # Log WHICH model actually served the answer (never the key).
        logger.info("gemini yanıtı '%s' modelinden alındı", model)
        return text

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
    return text
