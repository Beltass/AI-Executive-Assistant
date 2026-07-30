"""Gmail connection check (Google OAuth)."""

from __future__ import annotations

from ..config import get_integration
from . import CheckResult
from . import google_auth
from ._common import failed, ok, skipped_reason

SPEC = get_integration("gmail")

_SKIP_DETAIL = (
    "no Google credentials/token configured "
    "(run: python -m ai_assistant.integrations.google_auth)"
)


def check_connection() -> CheckResult:
    """Call Gmail ``users.getProfile`` using shared Google OAuth credentials."""
    if not google_auth.google_configured():
        return skipped_reason(SPEC.name, _SKIP_DETAIL)

    try:
        creds = google_auth.get_credentials()
    except google_auth.GoogleAuthError as exc:
        return failed(SPEC.name, str(exc))

    try:
        from googleapiclient.discovery import build

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
    except Exception as exc:  # network restricted, auth error, etc.
        return failed(SPEC.name, f"request error: {exc}")

    return ok(SPEC.name, f"email: {profile.get('emailAddress', 'unknown')}")
