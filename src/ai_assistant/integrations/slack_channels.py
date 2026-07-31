"""Slack multi-channel distribution for advisor reports.

Extends :mod:`ai_assistant.notifiers.slack_notifier` to support posting
individual advisor reports to channel-specific channels. Each advisor can have
its own dedicated Slack channel configured via environment variables.

Channel configuration:
    SLACK_CHANNEL_<ADVISOR_KEY>  - Dedicated channel for that advisor
    SLACK_MAIN_CHANNEL           - Fallback for advisors without a dedicated channel
    SLACK_CHANNEL                - Legacy fallback (used if main channel not set)

Block Kit formatting is reused from the existing notifier for consistency.
Each posted report includes a link to the dashboard for the full document.

Error handling is defensive: missing channels, webhook/token issues, and Slack
API errors are logged but never crash the posting — posting to other channels
continues regardless.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from ..reports import PublishedReport
from . import CheckResult, STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ._common import failed, http_post, ok, skipped_reason
from .channel_config import get_channel_for_advisor

logger = logging.getLogger(__name__)

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"

POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
NAME = "Slack Channel Notifier"


class SlackChannelNotifier:
    """Posts advisor reports to channel-specific Slack channels.

    Reuses Block Kit formatting from the existing notifier and supports both
    webhook and bot token delivery modes.
    """

    def __init__(self):
        """Initialize the notifier with configured credentials."""
        self.webhook_url = (os.getenv(WEBHOOK_ENV) or "").strip() or None
        self.bot_token = (os.getenv(BOT_TOKEN_ENV) or "").strip() or None

    def post_to_channel(
        self, advisor_key: str, advisor_title: str, report: PublishedReport, channel_id: str
    ) -> CheckResult:
        """Post an advisor's report to a specific Slack channel.

        Builds a Block Kit message with the advisor's headline, reading time,
        and a link to the full report on the dashboard. Uses either webhook
        (if configured) or bot token delivery.

        Args:
            advisor_key: The stable advisor identifier (e.g., "weather").
            advisor_title: The Turkish advisor title for display.
            report: The PublishedReport object containing headline, emoji, etc.
            channel_id: The Slack channel ID to post to (e.g., "C0123456789").

        Returns:
            CheckResult indicating success, skipped (no credentials), or failure.
        """
        if not channel_id:
            return skipped_reason(
                NAME,
                f"{advisor_title}: no channel configured",
            )

        if not self.webhook_url and not self.bot_token:
            return skipped_reason(
                NAME,
                f"{advisor_title}: missing credentials (SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN)",
            )

        try:
            text = f"{report.emoji} {report.name}"
            blocks = self._build_blocks(report)
            return self._send(channel_id, text, blocks)
        except Exception as exc:
            logger.error(f"Error posting {advisor_title} to {channel_id}: {exc}")
            return failed(NAME, f"{advisor_title}: {exc}")

    def _build_blocks(self, report: PublishedReport) -> list:
        """Build Block Kit blocks for the report message.

        Returns a compact message with the advisor's headline, reading time,
        and a link to the full document on the dashboard.
        """
        blocks = []

        # Header with emoji and name
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{report.emoji} *{report.name}*",
                },
            }
        )

        # Headline
        headline = (report.headline or "_(özet çıkarılamadı)_").strip()
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": headline[:2900],  # Slack's section limit
                },
            }
        )

        # Link to dashboard + reading time
        link_text = f"<{report.url}|📄 Tam rapor>" if hasattr(report, "url") else "📄 Tam rapor"
        read_time = f"~{report.read_minutes} dk okuma" if hasattr(report, "read_minutes") else ""
        blocks.append(
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"{link_text} · {read_time}".strip(),
                    }
                ],
            }
        )

        return blocks

    def _send(self, channel: str, text: str, blocks: list) -> CheckResult:
        """Send the message using configured webhook or bot token.

        Args:
            channel: The Slack channel ID.
            text: The fallback text (used for notifications/accessibility).
            blocks: The Block Kit blocks to render.

        Returns:
            CheckResult indicating success or failure.
        """
        if self.webhook_url:
            return self._post_webhook(channel, text, blocks)
        return self._post_bot(channel, text, blocks)

    def _post_webhook(self, channel: str, text: str, blocks: list) -> CheckResult:
        """Post via incoming webhook."""
        payload = {
            "channel": channel,
            "text": text,
            "blocks": blocks,
        }
        try:
            resp = http_post(self.webhook_url, json=payload)
        except Exception as exc:
            return failed(NAME, f"webhook request error: {exc}")

        if resp.is_success:
            try:
                data = resp.json()
                if data.get("ok"):
                    return ok(NAME, f"webhook to {channel}")
                error = data.get("error", "unknown")
                return failed(NAME, f"webhook error: {error}")
            except Exception:
                return failed(NAME, f"webhook: non-JSON response ({resp.status_code})")
        return failed(NAME, f"webhook HTTP {resp.status_code}")

    def _post_bot(self, channel: str, text: str, blocks: list) -> CheckResult:
        """Post via bot token (chat.postMessage)."""
        payload = {
            "channel": channel,
            "text": text,
            "blocks": blocks,
        }
        try:
            resp = http_post(
                POST_MESSAGE_URL,
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json=payload,
            )
        except Exception as exc:
            return failed(NAME, f"chat.postMessage request error: {exc}")

        try:
            data = resp.json()
        except Exception:
            return failed(NAME, f"chat.postMessage: non-JSON response ({resp.status_code})")

        if data.get("ok"):
            return ok(NAME, f"chat.postMessage to {channel}")
        error = data.get("error", "unknown")
        return failed(NAME, f"chat.postMessage error: {error}")


def post_advisor_to_channel(
    advisor_key: str, advisor_title: str, report: PublishedReport
) -> CheckResult:
    """Post an advisor's report to its configured channel.

    Convenience function that looks up the advisor's channel and uses the notifier.

    Args:
        advisor_key: The stable advisor identifier (e.g., "weather").
        advisor_title: The Turkish advisor title for display.
        report: The PublishedReport object.

    Returns:
        CheckResult indicating success, skipped, or failure.
    """
    channel = get_channel_for_advisor(advisor_key, advisor_title)
    if not channel:
        return skipped_reason(
            NAME,
            f"{advisor_title}: no channel configured",
        )
    notifier = SlackChannelNotifier()
    return notifier.post_to_channel(advisor_key, advisor_title, report, channel)
