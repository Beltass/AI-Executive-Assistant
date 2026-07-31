"""Daily digest — assemble one Turkish report from the advisor team.

``build_digest()`` runs the :class:`~ai_assistant.operations_manager.OperationsManager`,
then formats every advisor's briefing into a single dated Turkish report with a
short supervision line from the manager. It returns the formatted text plus the
underlying supervision object (statuses/counts).

Multi-channel distribution is handled by ``distribute_digest_by_channel()``, which:
- Posts the briefing summary to SLACK_MAIN_CHANNEL
- Posts each advisor's report to their specific SLACK_CHANNEL_<ADVISOR>
- Logs all distribution attempts and gracefully handles missing channels

Run with::

    python -m ai_assistant.daily_digest
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .advisors import NOTHING_NEW_NOTE
from .config import MODE_INCREMENTAL
from .integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from .operations_manager import OperationsManager, Supervision

logger = logging.getLogger(__name__)

_STATUS_LABEL = {
    STATUS_OK: "OK",
    STATUS_FAILED: "HATA",
    STATUS_SKIPPED: "ATLANDI",
}


@dataclass
class Digest:
    """A rendered daily digest plus its supervision metadata."""

    text: str
    supervision: Supervision

    @property
    def counts(self) -> dict:
        return self.supervision.counts


def build_digest(supervision: Supervision | None = None) -> Digest:
    """Run the Operations Manager and assemble one formatted Turkish report."""
    if supervision is None:
        supervision = OperationsManager().run()

    today = date.today().strftime("%d.%m.%Y")
    incremental = supervision.mode == MODE_INCREMENTAL
    heading = "🔄 Ara Brifing (yeni gelişmeler)" if incremental else "🗓️ Günlük Brifing"
    lines = [
        f"{heading} — {today}",
        "=" * 40,
        "",
    ]
    if incremental:
        lines.append(
            f"_Bu, günün ara çalıştırması: yalnızca yeni bulgular var "
            f"({supervision.new_findings} yeni)._"
        )
        lines.append("")

    # Advisors with nothing new are collapsed into ONE line at the end instead
    # of taking a section each — an incremental digest should be short.
    quiet = []
    for b in supervision.briefings:
        if b.nothing_new:
            quiet.append(b.title)
            continue
        label = _STATUS_LABEL.get(b.status, b.status.upper())
        lines.append(f"## {b.title} [{label}]")
        if b.status == STATUS_OK:
            lines.append(b.text.strip())
        elif b.status == STATUS_SKIPPED:
            lines.append(f"_Atlandı: {b.text}_")
        else:
            lines.append(f"_Bu bölüm hazırlanamadı: {b.text}_")
        lines.append("")

    if quiet:
        lines.append(f"🟰 {NOTHING_NEW_NOTE}: {', '.join(quiet)}")
        lines.append("")

    c = supervision.counts
    lines.append("-" * 40)
    lines.append(
        f"Operasyon Yöneticisi ({supervision.mode_label}): {c[STATUS_OK]} ok, "
        f"{c[STATUS_FAILED]} failed, {c[STATUS_SKIPPED]} skipped"
    )

    return Digest(text="\n".join(lines), supervision=supervision)


def distribute_digest_by_channel(
    supervision: Supervision, briefing_json: Optional[str] = None
) -> dict:
    """Distribute digest to multi-channel Slack by advisor.

    Posts the briefing summary to SLACK_MAIN_CHANNEL and each advisor's report
    to their specific channel (if configured). Gracefully handles missing channels
    and logs all distribution attempts.

    Args:
        supervision: The Supervision object containing briefings and metadata.
        briefing_json: Optional pre-built briefing JSON for reference.

    Returns:
        A distribution result dictionary with keys:
            - "main_channel": CheckResult for main channel post
            - "advisor_channels": dict of advisor_key -> CheckResult
            - "summary": Human-readable summary of distribution
    """
    from .integrations.channel_config import get_channel_config
    from .integrations.slack_channels import SlackChannelNotifier

    result = {
        "main_channel": None,
        "advisor_channels": {},
        "summary": "Not distributed",
    }

    config = get_channel_config()
    notifier = SlackChannelNotifier()

    # Check if any channel is configured
    if not config.has_any_channel():
        logger.info("No Slack channels configured for multi-channel distribution.")
        result["summary"] = "No channels configured — skipped"
        return result

    # Send summary to main channel (always attempt)
    main_channel = config.main_channel or os.getenv("SLACK_CHANNEL", "").strip()
    if main_channel:
        logger.info(f"Distributing briefing summary to main channel: {main_channel}")
        # Build a brief summary for main channel
        summary_text = _build_channel_summary(supervision)
        try:
            # Use the notifier's _send method to post to main channel
            from .integrations._common import ok, failed

            payload = {
                "channel": main_channel,
                "text": f"🗓️ {date.today().strftime('%d.%m.%Y')} — Günlük Brifing Özeti",
                "blocks": _build_summary_blocks(supervision, summary_text),
            }
            if notifier.webhook_url:
                from .integrations._common import http_post

                resp = http_post(notifier.webhook_url, json=payload)
                if resp.is_success:
                    data = resp.json()
                    if data.get("ok"):
                        result["main_channel"] = ok("Slack Main Channel", main_channel)
                        logger.info(f"Main channel post succeeded: {main_channel}")
                    else:
                        error = data.get("error", "unknown")
                        result["main_channel"] = failed("Slack Main Channel", error)
                        logger.error(f"Main channel post failed: {error}")
                else:
                    result["main_channel"] = failed("Slack Main Channel", f"HTTP {resp.status_code}")
                    logger.error(f"Main channel HTTP error: {resp.status_code}")
            elif notifier.bot_token:
                from .integrations._common import http_post

                resp = http_post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {notifier.bot_token}"},
                    json=payload,
                )
                try:
                    data = resp.json()
                    if data.get("ok"):
                        result["main_channel"] = ok("Slack Main Channel", main_channel)
                        logger.info(f"Main channel post succeeded: {main_channel}")
                    else:
                        error = data.get("error", "unknown")
                        result["main_channel"] = failed("Slack Main Channel", error)
                        logger.error(f"Main channel post failed: {error}")
                except Exception:
                    result["main_channel"] = failed(
                        "Slack Main Channel", f"HTTP {resp.status_code}: non-JSON response"
                    )
                    logger.error(f"Main channel JSON error: {resp.status_code}")
            else:
                result["main_channel"] = failed(
                    "Slack Main Channel", "No webhook URL or bot token configured"
                )
                logger.warning("No Slack credentials configured for main channel post")
        except Exception as exc:
            result["main_channel"] = failed("Slack Main Channel", str(exc))
            logger.error(f"Error posting to main channel: {exc}")

    # Distribute each advisor's report to their specific channel
    from . import reports

    publication = reports.Publication()  # This will be populated by the caller if needed

    for briefing in supervision.briefings:
        advisor_key = briefing.key
        advisor_title = briefing.title

        # Skip private or non-OK briefings for channel distribution
        if briefing.status != STATUS_OK:
            logger.debug(f"Skipping {advisor_title}: status is {briefing.status}")
            continue

        # Get the advisor's channel
        channel = config.get_channel(advisor_key, advisor_title)
        if not channel:
            logger.debug(f"No channel configured for {advisor_title}")
            continue

        logger.info(f"Distributing {advisor_title} to channel: {channel}")

        try:
            # Build advisor-specific message
            advisor_blocks = _build_advisor_blocks(briefing)
            payload = {
                "channel": channel,
                "text": f"{briefing.title}",
                "blocks": advisor_blocks,
            }

            if notifier.webhook_url:
                from .integrations._common import http_post

                resp = http_post(notifier.webhook_url, json=payload)
                if resp.is_success:
                    data = resp.json()
                    if data.get("ok"):
                        result["advisor_channels"][advisor_key] = ok(
                            f"Slack ({advisor_title})", channel
                        )
                        logger.info(f"Advisor channel post succeeded: {advisor_title} → {channel}")
                    else:
                        error = data.get("error", "unknown")
                        result["advisor_channels"][advisor_key] = failed(
                            f"Slack ({advisor_title})", error
                        )
                        logger.error(f"Advisor channel post failed ({advisor_title}): {error}")
                else:
                    result["advisor_channels"][advisor_key] = failed(
                        f"Slack ({advisor_title})", f"HTTP {resp.status_code}"
                    )
                    logger.error(f"Advisor HTTP error ({advisor_title}): {resp.status_code}")
            elif notifier.bot_token:
                from .integrations._common import http_post

                resp = http_post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {notifier.bot_token}"},
                    json=payload,
                )
                try:
                    data = resp.json()
                    if data.get("ok"):
                        result["advisor_channels"][advisor_key] = ok(
                            f"Slack ({advisor_title})", channel
                        )
                        logger.info(f"Advisor channel post succeeded: {advisor_title} → {channel}")
                    else:
                        error = data.get("error", "unknown")
                        result["advisor_channels"][advisor_key] = failed(
                            f"Slack ({advisor_title})", error
                        )
                        logger.error(f"Advisor channel post failed ({advisor_title}): {error}")
                except Exception:
                    result["advisor_channels"][advisor_key] = failed(
                        f"Slack ({advisor_title})", f"HTTP {resp.status_code}: non-JSON"
                    )
                    logger.error(f"Advisor JSON error ({advisor_title}): {resp.status_code}")

        except Exception as exc:
            result["advisor_channels"][advisor_key] = failed(
                f"Slack ({advisor_title})", str(exc)
            )
            logger.error(f"Error distributing {advisor_title} to {channel}: {exc}")

    # Build summary
    succeeded = sum(
        1
        for v in result["advisor_channels"].values()
        if v and getattr(v, "status", "") == STATUS_OK
    )
    if result["main_channel"] and getattr(result["main_channel"], "status", "") == STATUS_OK:
        result["summary"] = (
            f"Multi-channel distribution: main channel + {succeeded} advisor channels"
        )
    else:
        result["summary"] = f"Partial distribution: {succeeded} advisor channels"

    return result


def _build_channel_summary(supervision: Supervision) -> str:
    """Build a brief summary for the main channel.

    Returns a short text highlighting key findings across all advisors.
    """
    lines = []
    for briefing in supervision.briefings:
        if briefing.status == STATUS_OK and not briefing.nothing_new:
            # Extract first line or headline
            text = briefing.text.strip().split("\n")[0]
            if text:
                lines.append(f"• {briefing.title}: {text[:100]}")

    return "\n".join(lines) if lines else "_Yeni bulgu yok._"


def _build_summary_blocks(supervision: Supervision, summary_text: str) -> list:
    """Build Block Kit blocks for main channel summary message."""
    today = date.today().strftime("%d.%m.%Y")
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🗓️ Günlük Brifing — {today}", "emoji": True},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Özet*\n{summary_text[:2900]}"},
        },
    ]

    # Add counts
    c = supervision.counts
    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"{c[STATUS_OK]} ajan çalıştı · {c[STATUS_FAILED]} başarısız · {c[STATUS_SKIPPED]} atlandı",
                }
            ],
        }
    )

    return blocks


def _build_advisor_blocks(briefing) -> list:
    """Build Block Kit blocks for an advisor's channel post."""
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{briefing.title}*"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": briefing.text[:2900]},
        },
    ]
    return blocks


def main() -> int:
    """CLI entrypoint. Prints the digest. Returns the process exit code."""
    digest = build_digest()
    print(digest.text)
    return 1 if digest.counts[STATUS_FAILED] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
