"""LLM provider connection check (Gemini or OpenAI).

Whichever API key is present is used. Gemini is preferred if both are set.
If neither is configured the check is skipped.
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional

import httpx

from ..config import get_integration
from . import CheckResult
from ._common import classify_response, failed, http_get, http_post
from . import STATUS_SKIPPED

SPEC = get_integration("llm")
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"

# Default generation models. Kept small/fast; either provider is fine.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Max output tokens for generation. gemini-2.5-flash is a "thinking" model that
# spends part of its budget on internal reasoning, so a small budget truncates
# the visible answer. Default kept generous (richer, source-linked briefings
# need headroom); overridable via env var.
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "3072"))


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


def _retry_delay(resp: httpx.Response, attempt: int, base: float) -> float:
    """Seconds to wait before the next 429 retry.

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
    """POST to Gemini, retrying on HTTP 429 with backoff.

    Returns the final response (which may still be a 429 once retries are
    exhausted); callers turn a non-2xx response into a graceful failure.
    """
    max_retries, base = _gemini_retry_config()
    attempt = 0
    while True:
        resp = http_post(url, headers=headers, json=payload)
        if resp.status_code != 429 or attempt >= max_retries:
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


def generate_text(system_prompt: str, user_prompt: str) -> str:
    """Generate a short completion from the configured LLM provider.

    Reuses the same provider selection as :func:`check_connection` (Gemini
    preferred, OpenAI fallback). Raises ``RuntimeError`` if no provider is
    configured, and lets transport/HTTP errors propagate so callers can
    convert them into a graceful ``failed`` result.
    """
    provider = configured_provider()
    if provider is None:
        raise RuntimeError("no LLM provider configured (GEMINI_API_KEY or OPENAI_API_KEY)")

    if provider == "gemini":
        return _generate_gemini(system_prompt, user_prompt)
    return _generate_openai(system_prompt, user_prompt)


def _generate_gemini(system_prompt: str, user_prompt: str) -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    # Send the key via header (Google's recommended method) so it never lands
    # in the URL and therefore never leaks into httpx error strings/logs.
    url = f"{GEMINI_MODELS_URL}/{GEMINI_MODEL}:generateContent"
    headers = {"X-goog-api-key": key}
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
        },
    }
    _apply_request_spacing()
    try:
        resp = _post_gemini_with_retry(url, headers, payload)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        # Redact the key from any transport/HTTP error before it propagates
        # into an advisor's failed message (which may reach Slack).
        raise RuntimeError(_redact_key(str(exc), key)) from None
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise RuntimeError("gemini returned empty text")
    return text


def _generate_openai(system_prompt: str, user_prompt: str) -> str:
    key = os.getenv("OPENAI_API_KEY", "")
    url = "https://api.openai.com/v1/chat/completions"
    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 600,
    }
    resp = http_post(url, headers={"Authorization": f"Bearer {key}"}, json=payload)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("openai returned no choices")
    text = (choices[0].get("message", {}).get("content") or "").strip()
    if not text:
        raise RuntimeError("openai returned empty text")
    return text
