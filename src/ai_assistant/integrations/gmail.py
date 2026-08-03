"""Gmail connection check and draft creation (Google OAuth)."""

from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Optional

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


def create_draft(subject: str, body: str, to: Optional[str] = None) -> dict:
    """Create a Gmail draft via ``users.drafts.create``.

    Builds an RFC 822 message, base64url-encodes it, and stores it as a
    draft under the authenticated account. The draft is only saved, never
    sent.

    Args:
        subject: The email subject line.
        body: The plain-text message body.
        to: Optional recipient address; omit to leave the draft unaddressed.

    Returns:
        The created draft resource (a dict including its ``id``).

    Raises:
        google_auth.GoogleAuthError: if Google credentials are missing or
            cannot be refreshed.
    """
    creds = google_auth.get_credentials()

    message = EmailMessage()
    message["Subject"] = subject
    if to:
        message["To"] = to
    message.set_content(body)

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    from googleapiclient.discovery import build

    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return (
        service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )
