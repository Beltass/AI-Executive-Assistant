"""Gmail connection check."""

from __future__ import annotations

import os

from ..config import get_integration
from . import CheckResult
from ._common import classify_response, failed, http_get, skipped

SPEC = get_integration("gmail")
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"


def check_connection() -> CheckResult:
    """Ping the Gmail profile endpoint using a Google OAuth access token."""
    missing = SPEC.missing_env()
    if missing:
        return skipped(SPEC.name, missing)

    token = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN", "")
    try:
        resp = http_get(PROFILE_URL, headers={"Authorization": f"Bearer {token}"})
    except Exception as exc:  # network restricted, DNS, TLS, etc.
        return failed(SPEC.name, f"request error: {exc}")
    return classify_response(SPEC.name, resp)
