"""Slack multi-channel distribution — one channel per advisor.

The workspace layout this module implements:

* ONE main channel (``SLACK_MAIN_CHANNEL``) that carries the daily SUMMARY:
  one line per advisor with its headline, a deep link to the full report on the
  dashboard, and a link into that advisor's own channel;
* ONE sub-channel per advisor (``SLACK_CHANNEL_<ADVISOR_KEY>``) that carries
  that advisor's own section in full.

Use :func:`ai_assistant.integrations.slack_setup` to create the eleven channels
and print the ids in ready-to-paste form.

Channel configuration:
    SLACK_CHANNEL_<ADVISOR_KEY>  - Dedicated channel for that advisor
    SLACK_MAIN_CHANNEL           - Summary channel + fallback for advisors
                                   without a dedicated channel
    SLACK_CHANNEL                - Legacy fallback (used if main channel not set)

DELIVERY MODE MATTERS
---------------------

An incoming webhook (``SLACK_WEBHOOK_URL``) is bound at creation time to ONE
channel and Slack IGNORES the ``channel`` field in the payload. Fan-out over a
webhook therefore silently dumps every advisor into the same room — which is
exactly the bug this module used to have. So:

* with ``SLACK_BOT_TOKEN`` set, every message is delivered with
  ``chat.postMessage`` to the exact target channel (real routing);
* with only a webhook, the fan-out reports ``skipped`` for each advisor and
  explains that a bot token is required. The summary still goes out.

Error handling is defensive: missing channels, credential problems and Slack
API errors are logged but never crash the run — the remaining channels are
still attempted.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..reports import PublishedReport
from . import CheckResult, STATUS_FAILED, STATUS_OK
from ._common import failed, http_post, ok, skipped_reason
from .channel_config import get_channel_config, get_channel_for_advisor

logger = logging.getLogger(__name__)

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"

POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
PERMALINK_URL = "https://slack.com/api/chat.getPermalink"
NAME = "Slack Channel Notifier"

#: Slack's own limits, minus a safety margin (a rejected message is a lost one).
MAX_SECTION_CHARS = 2900
MAX_BODY_CHUNKS = 3

WEBHOOK_CANNOT_ROUTE = (
    "gelen webhook tek bir kanala bağlıdır; kanal başına dağıtım için "
    "SLACK_BOT_TOKEN gerekir"
)


def channel_link(channel_id: str) -> str:
    """A workspace-independent deep link that opens a channel in Slack."""
    return f"https://slack.com/app_redirect?channel={channel_id}"


@dataclass
class ChannelPost:
    """The outcome of posting ONE advisor's section to ONE channel."""

    key: str
    title: str
    channel: str = ""
    #: Whether the advisor's channel is its OWN (vs. borrowed main channel).
    dedicated: bool = False
    result: Optional[CheckResult] = None
    #: Message timestamp returned by ``chat.postMessage`` (thread anchor).
    ts: str = ""
    #: Permalink to the posted message, when Slack gave us one.
    permalink: str = ""

    @property
    def delivered(self) -> bool:
        return bool(self.result is not None and self.result.status == STATUS_OK)

    @property
    def link(self) -> str:
        """Best available link: the message permalink, else the channel."""
        if self.permalink:
            return self.permalink
        return channel_link(self.channel) if self.channel else ""


@dataclass
class Distribution:
    """What one fan-out produced, ready for the main-channel summary."""

    posts: List[ChannelPost] = field(default_factory=list)
    #: Why the fan-out did nothing at all, when it did nothing at all.
    skipped_reason: str = ""

    @property
    def links(self) -> Dict[str, str]:
        """``advisor key -> link`` for every section that actually landed."""
        return {p.key: p.link for p in self.posts if p.delivered and p.link}

    @property
    def delivered_keys(self) -> set:
        """Advisors whose section reached a channel OF THEIR OWN.

        The summary uses this to stop inlining a private section into the main
        channel: it already has a room where it lives in full.
        """
        return {p.key for p in self.posts if p.delivered and p.dedicated}

    @property
    def delivered(self) -> int:
        return sum(1 for p in self.posts if p.delivered)

    @property
    def failures(self) -> List[ChannelPost]:
        return [
            p
            for p in self.posts
            if p.result is not None and p.result.status == STATUS_FAILED
        ]

    def summary_line(self) -> str:
        """One Turkish line for the job log."""
        if self.skipped_reason:
            return f"kanal dağıtımı yapılmadı — {self.skipped_reason}"
        return f"{self.delivered}/{len(self.posts)} bölüm kendi kanalına gönderildi" + (
            f" · {len(self.failures)} hata" if self.failures else ""
        )


def _blocks_module():
    """The shared Block Kit presenter, imported lazily to avoid an import cycle.

    The formatting itself lives in :mod:`ai_assistant.notifiers.slack_blocks`
    so the main-channel summary and this fan-out can never drift apart again.
    """
    from ..notifiers import slack_blocks

    return slack_blocks


def _dashboard_base_url() -> str:
    """The dashboard base URL, from the shared presenter."""
    return _blocks_module().dashboard_base_url()


def _to_mrkdwn(text: str) -> str:
    """Markdown -> Slack mrkdwn, from the shared presenter."""
    return _blocks_module().to_mrkdwn(text)


def _section(text: str) -> dict:
    return _blocks_module().section(text)


def _context(text: str) -> dict:
    return _blocks_module().context(text)


class SlackChannelNotifier:
    """Posts advisor sections to channel-specific Slack channels.

    Bot token first: only ``chat.postMessage`` can actually choose a channel.
    """

    def __init__(self):
        """Initialize the notifier with configured credentials."""
        self.webhook_url = (os.getenv(WEBHOOK_ENV) or "").strip() or None
        self.bot_token = (os.getenv(BOT_TOKEN_ENV) or "").strip() or None

    # --- public API ---------------------------------------------------------

    def post_to_channel(
        self,
        advisor_key: str,
        advisor_title: str,
        report: PublishedReport,
        channel_id: str,
        base_url: str = "",
    ) -> CheckResult:
        """Post a published advisor report to a specific Slack channel.

        Kept for backwards compatibility; :func:`distribute` is what the daily
        run uses. Returns a :class:`CheckResult` and never raises.
        """
        post = self.post_report(
            advisor_key, advisor_title, report, channel_id, base_url
        )
        return post.result or failed(NAME, f"{advisor_title}: bilinmeyen hata")

    def post_report(
        self,
        advisor_key: str,
        advisor_title: str,
        report: PublishedReport,
        channel_id: str,
        base_url: str = "",
        new_findings: int = 0,
    ) -> ChannelPost:
        """Post a PUBLISHED report as a scannable Block Kit card.

        Never the whole body: the card carries the headline, the metric strip,
        a few bullets and the deep link to the full document on the dashboard.
        """
        post = ChannelPost(key=advisor_key, title=advisor_title, channel=channel_id)
        guard = self._guard(post)
        if guard is not None:
            return guard
        try:
            text, blocks = _blocks_module().build_report_message(
                report, base_url=base_url, new_findings=new_findings
            )
        except Exception as exc:  # pragma: no cover - defensive only
            logger.error(f"Blok oluşturulamadı ({advisor_title}): {exc}")
            post.result = failed(NAME, f"{advisor_title}: {exc}")
            return post
        return self._deliver(post, text, blocks)

    def post_briefing(
        self,
        advisor_key: str,
        advisor_title: str,
        briefing: Any,
        channel_id: str,
        emoji: str = "🧩",
    ) -> ChannelPost:
        """Post a PRIVATE section in full: it has no public document to link to."""
        post = ChannelPost(key=advisor_key, title=advisor_title, channel=channel_id)
        guard = self._guard(post)
        if guard is not None:
            return guard
        try:
            text, blocks = _blocks_module().build_briefing_message(
                advisor_title, briefing, emoji=emoji, max_body_blocks=MAX_BODY_CHUNKS
            )
        except Exception as exc:  # pragma: no cover - defensive only
            logger.error(f"Blok oluşturulamadı ({advisor_title}): {exc}")
            post.result = failed(NAME, f"{advisor_title}: {exc}")
            return post
        return self._deliver(post, text, blocks)

    # --- block builders -----------------------------------------------------

    def _report_blocks(self, report: PublishedReport, base_url: str = "") -> list:
        """Blocks for a published report — see :mod:`notifiers.slack_blocks`."""
        return _blocks_module().report_blocks(report, base_url=base_url)

    def _briefing_blocks(self, advisor_title: str, briefing: Any, emoji: str) -> list:
        """Blocks for a private section: the whole body, chunked to fit Slack."""
        return _blocks_module().briefing_blocks(
            advisor_title, briefing, emoji=emoji, max_body_blocks=MAX_BODY_CHUNKS
        )

    # --- delivery -----------------------------------------------------------

    def _guard(self, post: ChannelPost) -> Optional[ChannelPost]:
        """Reject a post we cannot route. Returns the post, or ``None`` to proceed."""
        if not post.channel:
            post.result = skipped_reason(NAME, f"{post.title}: kanal yapılandırılmamış")
            return post
        if not self.bot_token:
            reason = (
                WEBHOOK_CANNOT_ROUTE
                if self.webhook_url
                else f"kimlik bilgisi yok ({BOT_TOKEN_ENV})"
            )
            post.result = skipped_reason(NAME, f"{post.title}: {reason}")
            return post
        return None

    def _deliver(self, post: ChannelPost, text: str, blocks: list) -> ChannelPost:
        """Send with ``chat.postMessage`` and remember where the message landed."""
        result, ts = self._post_bot(post.channel, text, blocks)
        post.result = result
        post.ts = ts
        if ts:
            post.permalink = self._permalink(post.channel, ts)
        return post

    def _post_bot(
        self, channel: str, text: str, blocks: list
    ) -> Tuple[CheckResult, str]:
        """Post via bot token. Returns ``(result, message_ts)``."""
        payload = {"channel": channel, "text": text, "blocks": blocks}
        try:
            resp = http_post(
                POST_MESSAGE_URL,
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json=payload,
            )
        except Exception as exc:
            return failed(NAME, f"chat.postMessage isteği başarısız: {exc}"), ""

        try:
            data = resp.json()
        except Exception:
            return (
                failed(
                    NAME, f"chat.postMessage: JSON olmayan yanıt ({resp.status_code})"
                ),
                "",
            )

        if data.get("ok"):
            return ok(NAME, f"chat.postMessage → {channel}"), str(data.get("ts") or "")
        error = str(data.get("error", "unknown"))
        return failed(NAME, f"chat.postMessage hatası ({channel}): {error}"), ""

    def _permalink(self, channel: str, ts: str) -> str:
        """Ask Slack for the message permalink. Best effort — never raises."""
        try:
            resp = http_post(
                PERMALINK_URL,
                headers={"Authorization": f"Bearer {self.bot_token}"},
                json={"channel": channel, "message_ts": ts},
            )
            data = resp.json()
            if data.get("ok"):
                return str(data.get("permalink") or "")
        except Exception as exc:  # pragma: no cover - link is a nicety
            logger.debug(f"Kalıcı bağlantı alınamadı ({channel}): {exc}")
        return ""


def _chunks(text: str, size: int = MAX_SECTION_CHARS) -> List[str]:
    """Split a long body on paragraph boundaries so no block exceeds ``size``."""
    return _blocks_module().chunks(text, size)


def _advisor_emoji(key: str) -> str:
    from ..status_report import ADVISOR_META, DEFAULT_META

    return str(ADVISOR_META.get(key, DEFAULT_META).get("emoji") or "🧩")


def distribute(
    supervision: Any,
    publication: Any = None,
    base_url: str = "",
    notifier: Optional[SlackChannelNotifier] = None,
) -> Distribution:
    """Fan one run out to the advisors' own channels.

    Every advisor section goes to ``SLACK_CHANNEL_<KEY>``; public sections carry
    their headline plus a deep link to the dashboard document, private sections
    carry their full body (they have no public document to link to).

    An advisor without a channel of its own falls back to the main channel — the
    documented behaviour — but the fan-out as a WHOLE stays off until at least
    one dedicated channel exists, because otherwise it would just repeat the
    summary once per advisor in the single configured room.

    Never raises: a channel that refuses the message costs that channel only.
    """
    dist = Distribution()
    config = get_channel_config()

    if not config.has_dedicated_channels():
        dist.skipped_reason = (
            "hiçbir danışman için özel kanal tanımlı değil "
            "(SLACK_CHANNEL_<DANIŞMAN>)"
        )
        logger.info(f"Kanal dağıtımı atlandı: {dist.skipped_reason}")
        return dist

    sender = notifier or SlackChannelNotifier()
    if not sender.bot_token:
        dist.skipped_reason = (
            WEBHOOK_CANNOT_ROUTE
            if sender.webhook_url
            else f"kimlik bilgisi yok ({BOT_TOKEN_ENV})"
        )
        logger.warning(f"Kanal dağıtımı atlandı: {dist.skipped_reason}")
        return dist

    base = base_url or _dashboard_base_url()
    main_channel = config.resolve_main_channel()
    reports_by_key = {r.id: r for r in list(getattr(publication, "reports", []) or [])}

    for briefing in list(getattr(supervision, "briefings", []) or []):
        key = str(getattr(briefing, "key", "") or "")
        title = str(getattr(briefing, "title", "") or key)
        if str(getattr(briefing, "status", "")) != STATUS_OK:
            continue
        if getattr(briefing, "nothing_new", False):
            # An incremental run's "yeni bulgu yok" line is not worth a message
            # in a dedicated channel; the summary already says who was quiet.
            continue

        channel = get_channel_for_advisor(key, title)
        if not channel:
            continue
        dedicated = bool(config.dedicated_channel(key))

        report = reports_by_key.get(key)
        if report is not None:
            post = sender.post_report(
                key,
                title,
                report,
                channel,
                base_url=base,
                new_findings=int(getattr(briefing, "new_findings", 0) or 0),
            )
        else:
            post = sender.post_briefing(
                key, title, briefing, channel, emoji=_advisor_emoji(key)
            )
        post.dedicated = dedicated and channel != main_channel
        dist.posts.append(post)

        detail = getattr(post.result, "detail", "")
        if post.delivered:
            logger.info(f"{title} → {channel}")
        else:
            logger.warning(f"{title} → {channel} gönderilemedi: {detail}")

    return dist


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
        return skipped_reason(NAME, f"{advisor_title}: kanal yapılandırılmamış")
    notifier = SlackChannelNotifier()
    return notifier.post_to_channel(advisor_key, advisor_title, report, channel)
