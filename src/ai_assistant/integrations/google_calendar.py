"""Google Calendar connection check."""

from __future__ import annotations

import os

from ..config import get_integration
from . import CheckResult
from ._common import classify_response, failed, http_get, skipped

SPEC = get_integration("google_calendar")
CALENDAR_LIST_URL = (
    "https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=1"
)


def check_connection() -> CheckResult:
    """List one calendar entry to confirm the token is valid."""
    missing = SPEC.missing_env()
    if missing:
        return skipped(SPEC.name, missing)

    token = os.getenv("GOOGLE_OAUTH_ACCESS_TOKEN", "")
    try:
        resp = http_get(CALENDAR_LIST_URL, headers={"Authorization": f"Bearer {token}"})
    except Exception as exc:
        return failed(SPEC.name, f"request error: {exc}")
    return classify_response(SPEC.name, resp)
