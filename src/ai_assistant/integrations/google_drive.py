"""Google Drive connection check (Google OAuth)."""

from __future__ import annotations

from ..config import get_integration
from . import CheckResult
from . import google_auth
from ._common import failed, ok, skipped_reason

SPEC = get_integration("google_drive")

_SKIP_DETAIL = (
    "no Google credentials/token configured "
    "(run: python -m ai_assistant.integrations.google_auth)"
)


def check_connection() -> CheckResult:
    """Query the Drive ``about`` endpoint to confirm authentication."""
    if not google_auth.google_configured():
        return skipped_reason(SPEC.name, _SKIP_DETAIL)

    try:
        creds = google_auth.get_credentials()
    except google_auth.GoogleAuthError as exc:
        return failed(SPEC.name, str(exc))

    try:
        from googleapiclient.discovery import build

        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        about = service.about().get(fields="user").execute()
    except Exception as exc:
        return failed(SPEC.name, f"request error: {exc}")

    user = about.get("user", {}).get("emailAddress", "unknown")
    return ok(SPEC.name, f"user: {user}")
