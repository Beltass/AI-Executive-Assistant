"""Notion connection check."""

from __future__ import annotations

import os

from ..config import get_integration
from . import CheckResult
from ._common import classify_response, failed, http_get, skipped

SPEC = get_integration("notion")
ME_URL = "https://api.notion.com/v1/users/me"
# Pinned Notion API version; required on every request.
NOTION_VERSION = "2022-06-28"


def check_connection() -> CheckResult:
    """Fetch the bot user via ``/users/me`` to confirm the integration key."""
    missing = SPEC.missing_env()
    if missing:
        return skipped(SPEC.name, missing)

    token = os.getenv("NOTION_API_KEY", "")
    try:
        resp = http_get(
            ME_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
            },
        )
    except Exception as exc:
        return failed(SPEC.name, f"request error: {exc}")
    return classify_response(SPEC.name, resp)
