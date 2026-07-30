"""Slack notifier — deliver the daily digest to Slack.

Two delivery modes are supported, in priority order:

1. Incoming Webhook via ``SLACK_WEBHOOK_URL``.
2. Bot token via ``SLACK_BOT_TOKEN`` + ``SLACK_CHANNEL`` (``chat.postMessage``).

If neither is configured the notifier is ``skipped`` (never crashes).

Run with::

    python -m ai_assistant.notifiers.slack_notifier
"""

from __future__ import annotations

import os
import sys

from ..daily_digest import build_digest
from ..integrations import (
    CheckResult,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED,
)
from ..integrations._common import failed, http_post, ok, skipped_reason

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
CHANNEL_ENV = "SLACK_CHANNEL"
POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

NAME = "Slack Notifier"


def _post_webhook(url: str, text: str) -> CheckResult:
    try:
        resp = http_post(url, json={"text": text})
    except Exception as exc:
        return failed(NAME, f"request error (webhook): {exc}")
    if resp.is_success:
        return ok(NAME, f"webhook — HTTP {resp.status_code}")
    snippet = resp.text.strip().replace("\n", " ")[:160]
    return failed(NAME, f"webhook — HTTP {resp.status_code}: {snippet}")


def _post_bot(token: str, channel: str, text: str) -> CheckResult:
    try:
        resp = http_post(
            POST_MESSAGE_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": channel, "text": text},
        )
    except Exception as exc:
        return failed(NAME, f"request error (chat.postMessage): {exc}")
    try:
        data = resp.json()
    except Exception:
        return failed(NAME, f"HTTP {resp.status_code}: non-JSON response")
    if data.get("ok"):
        return ok(NAME, f"chat.postMessage — channel: {channel}")
    return failed(NAME, f"chat.postMessage error: {data.get('error', 'unknown')}")


def send_message(text: str) -> CheckResult:
    """Send a plain-text message to Slack using whichever mode is configured."""
    webhook = os.getenv(WEBHOOK_ENV)
    if webhook:
        return _post_webhook(webhook, text)

    token = os.getenv(BOT_TOKEN_ENV)
    channel = os.getenv(CHANNEL_ENV)
    if token and channel:
        return _post_bot(token, channel, text)

    return skipped_reason(
        NAME,
        f"missing env var(s): {WEBHOOK_ENV} or ({BOT_TOKEN_ENV} + {CHANNEL_ENV})",
    )


def send_daily_digest() -> CheckResult:
    """Build the daily digest and post it to Slack."""
    digest = build_digest()
    return send_message(digest.text)


_STATUS_LABEL = {
    STATUS_OK: "OK",
    STATUS_FAILED: "FAILED",
    STATUS_SKIPPED: "SKIPPED",
}


def main() -> int:
    """CLI entrypoint. Builds + sends the digest. Returns the exit code."""
    result = send_daily_digest()
    label = _STATUS_LABEL.get(result.status, result.status.upper())
    print(f"Slack Notifier: {label} — {result.detail}")
    return 1 if result.status == STATUS_FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
