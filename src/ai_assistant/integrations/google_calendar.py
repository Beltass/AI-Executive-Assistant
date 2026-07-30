"""Google Calendar connection check (Google OAuth)."""

from __future__ import annotations

from ..config import get_integration
from . import CheckResult
from . import google_auth
from ._common import failed, ok, skipped_reason

SPEC = get_integration("google_calendar")

_SKIP_DETAIL = (
    "no Google credentials/token configured "
    "(run: python -m ai_assistant.integrations.google_auth)"
)


def check_connection() -> CheckResult:
    """List one calendar entry to confirm the shared Google token is valid."""
    if not google_auth.google_configured():
        return skipped_reason(SPEC.name, _SKIP_DETAIL)

    try:
        creds = google_auth.get_credentials()
    except google_auth.GoogleAuthError as exc:
        return failed(SPEC.name, str(exc))

    try:
        from googleapiclient.discovery import build

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        result = service.calendarList().list(maxResults=1).execute()
    except Exception as exc:
        return failed(SPEC.name, f"request error: {exc}")

    count = len(result.get("items", []))
    return ok(SPEC.name, f"calendarList reachable ({count} entry seen)")
