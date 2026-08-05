"""Gmail connection check and message search (Google OAuth).

Everything here is module-level functions, matching the rest of the
integration checks: there is no per-instance state worth holding, and the
Gmail service object is passed in (or built on demand) so tests never need
credentials. Callers that already hold a service — the meeting-notes poller
builds one per run — pass it to avoid a second OAuth refresh.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..config import get_integration
from . import CheckResult
from . import google_auth
from ._common import failed, ok, skipped_reason

logger = logging.getLogger(__name__)

SPEC = get_integration("gmail")

_SKIP_DETAIL = (
    "no Google credentials/token configured "
    "(run: python -m ai_assistant.integrations.google_auth)"
)

#: Largest page Gmail's ``users.messages.list`` will serve in one call.
GMAIL_MAX_PAGE_SIZE = 100


def build_service(credentials: Any = None) -> Any:
    """Build a Gmail API client from the shared Google OAuth credentials.

    Args:
        credentials: Pre-loaded credentials; loaded from
            :func:`google_auth.get_credentials` when omitted.

    Returns:
        A ``googleapiclient`` Gmail v1 service.

    Raises:
        google_auth.GoogleAuthError: nothing is configured, or the stored
            token cannot be refreshed.
    """
    from googleapiclient.discovery import build

    creds = credentials if credentials is not None else google_auth.get_credentials()
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def search_messages(
    query: str,
    max_results: int = 20,
    *,
    service: Any = None,
) -> List[Dict[str, Any]]:
    """Search the mailbox and return FULL messages for the hits.

    ``users.messages.list`` only ever returns ``{id, threadId}`` stubs, so
    every hit is fetched again with ``format="full"``. That format is not
    optional here: downstream discovery
    (:func:`~ai_assistant.integrations.meeting_notes_poller.extract_audio_source`)
    walks ``payload.parts`` looking for audio attachments and body text, and
    ``metadata``/``minimal`` carry neither.

    Pagination follows ``nextPageToken`` until ``max_results`` messages have
    been collected or Gmail runs out of hits — the limit is never exceeded,
    including mid-page.

    Failure policy: a message that cannot be read is logged and SKIPPED, so
    one unreadable mail never costs us the rest of the search. A failing
    ``list`` call propagates, because that means the search itself is broken
    (bad query, expired credentials) and silently returning "no meetings"
    would hide it.

    Args:
        query: Gmail search syntax, e.g. ``from:notifications has:attachment``.
        max_results: Hard cap on returned messages.
        service: Gmail API service; built from the shared credentials when
            omitted. Injectable so tests never touch the network.

    Returns:
        Full message dicts, oldest-to-newest as Gmail returns them. Empty
        list when nothing matches.
    """
    if max_results <= 0:
        return []

    messages_api = (service if service is not None else build_service()).users().messages()

    collected: List[Dict[str, Any]] = []
    page_token: Optional[str] = None

    while len(collected) < max_results:
        params: Dict[str, Any] = {
            "userId": "me",
            "q": query,
            "maxResults": min(GMAIL_MAX_PAGE_SIZE, max_results - len(collected)),
        }
        # Only sent on later pages, so the first request stays the plain
        # three-parameter call the API documents.
        if page_token:
            params["pageToken"] = page_token

        response = messages_api.list(**params).execute() or {}

        stubs = response.get("messages") or []
        message_ids = [
            str(stub["id"])
            for stub in stubs
            if isinstance(stub, dict) and stub.get("id")
        ]

        for message_id in message_ids:
            if len(collected) >= max_results:
                break
            try:
                full = (
                    messages_api.get(userId="me", id=message_id, format="full").execute()
                )
            except Exception as exc:  # one bad message must not sink the search
                logger.warning(
                    "Gmail message %s could not be read, skipping it: %s",
                    message_id,
                    exc,
                )
                continue
            if full:
                collected.append(full)

        page_token = response.get("nextPageToken")
        if not page_token or not message_ids:
            break

    logger.info("Gmail search '%s' returned %d message(s)", query, len(collected))
    return collected


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
