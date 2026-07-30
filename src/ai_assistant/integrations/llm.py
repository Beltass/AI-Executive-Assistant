"""LLM provider connection check (Gemini or OpenAI).

Whichever API key is present is used. Gemini is preferred if both are set.
If neither is configured the check is skipped.
"""

from __future__ import annotations

import os
from typing import Optional

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
# the visible answer. Default kept generous; overridable via env var.
GEMINI_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "2048"))


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
            resp = http_get(f"{GEMINI_MODELS_URL}?key={gemini_key}")
        except Exception as exc:
            return failed(SPEC.name, f"request error (gemini): {exc}")
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
    url = f"{GEMINI_MODELS_URL}/{GEMINI_MODEL}:generateContent?key={key}"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": GEMINI_MAX_OUTPUT_TOKENS,
        },
    }
    resp = http_post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
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
