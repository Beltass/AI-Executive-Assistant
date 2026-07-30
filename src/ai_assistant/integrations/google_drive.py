"""Google Drive connection check."""

from __future__ import annotations

import os

from ..config import get_integration
from . import CheckResult
from ._common import classify_response, failed, http_get, skipped

SPEC = get_integration("google_drive")
ABOUT_URL = "https://www.googleapis.com/drive/v3/about?fields=user"


def check_connection() -> CheckResult:
    """Query the Drive ``about`` endpoint to confirm authentication."""
    missing = SPEC.missing_env()
    if missing:
        return skipped(SPEC.name, missing)

    token = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN", "")
    try:
        resp = http_get(ABOUT_URL, headers={"Authorization": f"Bearer {token}"})
    except Exception as exc:
        return failed(SPEC.name, f"request error: {exc}")
    return classify_response(SPEC.name, resp)
