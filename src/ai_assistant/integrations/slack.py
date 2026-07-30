"""Slack connection check."""

from __future__ import annotations

import os

from ..config import get_integration
from . import CheckResult
from ._common import failed, http_post, ok, skipped

SPEC = get_integration("slack")
AUTH_TEST_URL = "https://slack.com/api/auth.test"


def check_connection() -> CheckResult:
    """Call Slack's ``auth.test`` with the bot token.

    Slack returns HTTP 200 even for bad tokens, with ``{"ok": false}`` in
    the body, so we inspect the JSON ``ok`` field rather than the status.
    """
    missing = SPEC.missing_env()
    if missing:
        return skipped(SPEC.name, missing)

    token = os.getenv("SLACK_BOT_TOKEN", "")
    try:
        resp = http_post(
            AUTH_TEST_URL,
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception as exc:
        return failed(SPEC.name, f"request error: {exc}")

    try:
        data = resp.json()
    except Exception:
        return failed(SPEC.name, f"HTTP {resp.status_code}: non-JSON response")

    if data.get("ok"):
        team = data.get("team", "?")
        return ok(SPEC.name, f"team: {team}")
    return failed(SPEC.name, f"auth.test error: {data.get('error', 'unknown')}")
