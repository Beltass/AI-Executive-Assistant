"""LLM provider connection check (Gemini or OpenAI).

Whichever API key is present is used. Gemini is preferred if both are set.
If neither is configured the check is skipped.
"""

from __future__ import annotations

import os

from ..config import get_integration
from . import CheckResult
from ._common import classify_response, failed, http_get
from . import STATUS_SKIPPED

SPEC = get_integration("llm")
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_MODELS_URL = "https://api.openai.com/v1/models"


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
