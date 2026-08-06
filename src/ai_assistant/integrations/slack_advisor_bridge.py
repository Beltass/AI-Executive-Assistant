"""Slack Advisor Bridge — Two-way communication between advisors and Slack.

This module manages:
- Daily advisor updates to Slack
- User requests via @advisor_key mentions
- Multi-turn thread-based conversations
- Drive document sharing and link generation
- Concurrent request handling with error recovery

State Persistence:
  .assistant_state/advisor_threads.json — Maps advisor_key_user_id to Slack thread_ts
  .assistant_state/advisor_requests.json — Tracks pending/completed requests

Thread Format:
  Main message: Advisor intro + capabilities
  Replies: User requests, advisor responses, Drive links
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Callable, Awaitable
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR = ".assistant_state"

ADVISOR_NAMES = {
    "data_analyst": "📊 Veri Analisti",
    "linkedin_coach": "💼 LinkedIn Koçu",
    "social_media_coach": "📱 Sosyal Medya Koçu",
    "personal_assistant": "🤖 Kişisel Asistan",
}

ADVISOR_DESCRIPTIONS = {
    "data_analyst": "CSV/JSON veri analizi, istatistik, grafik oluşturma",
    "linkedin_coach": "LinkedIn profili optimizasyon, kişisel marka geliştirme",
    "social_media_coach": "Sosyal medya stratejisi, içerik planlama, platform optimizasyonu",
    "personal_assistant": "Günlük planlama, görev takibi, hedefler, takvim yönetimi",
}

# Turkish/short aliases users are likely to type instead of the canonical key.
# Keys are normalised (lowercase, no spaces/dots/dashes) before lookup.
ADVISOR_ALIASES: Dict[str, str] = {
    "data_analyst": "data_analyst",
    "dataanalyst": "data_analyst",
    "veri_analisti": "data_analyst",
    "verianalisti": "data_analyst",
    "veri": "data_analyst",
    "analist": "data_analyst",
    "linkedin_coach": "linkedin_coach",
    "linkedincoach": "linkedin_coach",
    "linkedin": "linkedin_coach",
    "linkedin_kocu": "linkedin_coach",
    "linkedinkocu": "linkedin_coach",
    "social_media_coach": "social_media_coach",
    "socialmediacoach": "social_media_coach",
    "sosyal_medya_kocu": "social_media_coach",
    "sosyalmedyakocu": "social_media_coach",
    "sosyal": "social_media_coach",
    "sosyalmedya": "social_media_coach",
    "personal_assistant": "personal_assistant",
    "personalassistant": "personal_assistant",
    "kisisel_asistan": "personal_assistant",
    "kisiselasistan": "personal_assistant",
    "asistan": "personal_assistant",
}

# `@name` at the start of a word. Slack user mentions look like `<@U123>` and are
# stripped first so a bot mention never gets mistaken for an advisor name.
_SLACK_USER_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
_MENTION_RE = re.compile(r"(?:^|\s)@([\wÀ-ɏ]+)", re.UNICODE)

# Turkish characters folded to ASCII so `@kişisel_asistan` matches too.
_TR_FOLD = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
)


def normalize_advisor_name(name: str) -> str:
    """Normalise a raw mention token so it can be looked up in ADVISOR_ALIASES."""
    folded = name.strip().translate(_TR_FOLD).lower()
    return re.sub(r"[^a-z0-9_]", "", folded)


def resolve_advisor_key(name: str) -> Optional[str]:
    """Map a raw mention token to a known advisor key, or None if unknown."""
    normalized = normalize_advisor_name(name)
    if not normalized:
        return None
    if normalized in ADVISOR_NAMES:
        return normalized
    key = ADVISOR_ALIASES.get(normalized)
    if key:
        return key
    # Also accept the alias written without underscores (e.g. "veri analisti").
    return ADVISOR_ALIASES.get(normalized.replace("_", ""))


def parse_advisor_mention(text: str) -> Tuple[Optional[str], Optional[str], str]:
    """Parse an ``@advisor`` mention out of a Slack message.

    Args:
        text: Raw Slack message text.

    Returns:
        ``(advisor_key, raw_mention, remaining_message)``:
        - ``advisor_key`` is the resolved advisor, or ``None`` when the mention
          names an advisor we do not know (or there is no mention at all).
        - ``raw_mention`` is the literal token the user typed after ``@``, or
          ``None`` when the message contains no ``@mention``.
        - ``remaining_message`` is the message with the advisor mention removed.
    """
    if not text:
        return None, None, ""

    cleaned = _SLACK_USER_MENTION_RE.sub(" ", text)

    for match in _MENTION_RE.finditer(cleaned):
        raw = match.group(1)
        key = resolve_advisor_key(raw)
        if key:
            remainder = (cleaned[: match.start()] + " " + cleaned[match.end() :]).strip()
            return key, raw, remainder
        # First mention is unknown — report it so the user gets a help message.
        remainder = (cleaned[: match.start()] + " " + cleaned[match.end() :]).strip()
        return None, raw, remainder

    return None, None, cleaned.strip()


def build_advisor_help_message(unknown_name: Optional[str] = None) -> str:
    """Message listing the advisors that can be mentioned."""
    lines = []
    if unknown_name:
        lines.append(f"❓ `@{unknown_name}` diye bir danışman yok.")
    lines.append("Çağırabileceğin danışmanlar:")
    for key, name in ADVISOR_NAMES.items():
        lines.append(f"• `@{key}` — {name}: {ADVISOR_DESCRIPTIONS.get(key, '')}")
    lines.append("Örnek: `@data_analyst son satış verisini özetler misin?`")
    return "\n".join(lines)


@dataclass
class SlackUpdate:
    """Advisor update to be sent to Slack."""

    advisor_key: str
    advisor_name: str
    title: str
    summary: str
    drive_links: Dict[str, str]  # {"report": "https://...", "data": "https://..."}
    timestamp: datetime
    channel_id: str
    thread_ts: Optional[str] = None


@dataclass
class AdvisorRequest:
    """Track advisor request state."""

    request_id: str
    user_id: str
    advisor_key: str
    message: str
    status: str  # "pending", "processing", "completed", "failed"
    thread_ts: str
    created_at: str
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AdvisorRequest:
        """Create from dict."""
        return cls(**data)


class SlackAdvisorBridge:
    """Manages two-way communication between advisors and Slack."""

    def __init__(
        self,
        slack_token: Optional[str] = None,
        slack_client: Optional[Any] = None,
        drive_manager: Optional[Any] = None,
        notification_manager: Optional[Any] = None,
    ):
        """Initialize Slack Advisor Bridge.

        Args:
            slack_token: Slack bot token (or from SLACK_BOT_TOKEN env)
            slack_client: Slack AsyncWebClient instance
            drive_manager: GoogleDriveManager instance
            notification_manager: NotificationManager instance
        """
        self.slack_token = slack_token or os.getenv("SLACK_BOT_TOKEN", "")
        self.slack_client = slack_client
        self.drive_manager = drive_manager
        self.notification_manager = notification_manager
        self.thread_manager = AdvisorThreadManager()
        self.request_manager = AdvisorRequestManager()

        self._ensure_state_dir()

    @staticmethod
    def _ensure_state_dir() -> None:
        """Ensure state directory exists."""
        os.makedirs(STATE_DIR, exist_ok=True)

    async def send_daily_advisor_update(
        self, advisor_key: str, report_data: dict, channel: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Send daily update from advisor to Slack.

        Format:
        📊 [Advisor Name] Daily Report
        └─ Summary text
        └─ 📄 Drive links (Report, Data, Analysis)
        └─ Thread for Q&A

        Args:
            advisor_key: Key identifying the advisor
            report_data: Dict with keys: summary, drive_links, timestamp
            channel: Slack channel or @user_dm (default: user DM)

        Returns:
            Response dict with ts (message timestamp) or None on error
        """
        if not self.slack_client:
            logger.error("Slack client not configured for daily updates")
            return None

        try:
            blocks = self._build_update_blocks(advisor_key, report_data)

            # Post to channel or DM
            target = channel or "@user_dm"
            response = await self.slack_client.chat_postMessage(
                channel=target,
                blocks=blocks,
                text=f"{advisor_key} daily update",
            )

            if response.get("ok"):
                # Save thread info for follow-ups
                await self.thread_manager.save_thread(
                    advisor_key=advisor_key,
                    user_id="daily_update",
                    thread_ts=response.get("ts", ""),
                    message_type="daily_update",
                )
                logger.info(
                    f"Daily update sent for {advisor_key}, thread_ts={response.get('ts')}"
                )
                return response
            else:
                logger.error(
                    f"Slack error sending daily update: {response.get('error')}"
                )
                return None

        except Exception as e:
            logger.error(f"Failed to send daily advisor update for {advisor_key}: {e}")
            return None

    async def handle_advisor_request(
        self,
        user_id: str,
        advisor_key: str,
        message: str,
        channel: Optional[str] = None,
    ) -> Optional[str]:
        """Handle user request to an advisor.

        Process:
        1. Get/create advisor thread
        2. Acknowledge in Slack (🔄 Processing...)
        3. Process with advisor callback
        4. Upload to Drive
        5. Post Drive links to Slack thread
        6. Reply in thread (✅ Complete)

        Args:
            user_id: Slack user ID
            advisor_key: Advisor identifier
            message: User message/request
            channel: Slack channel (if not DM)

        Returns:
            Request ID or None on error
        """
        if not self.slack_client:
            logger.error("Slack client not configured for advisor requests")
            return None

        thread_ts = await self.thread_manager.get_advisor_thread(
            advisor_key, user_id, self.slack_client
        )
        request_id = f"{advisor_key}_{user_id}_{int(datetime.now().timestamp() * 1000)}"

        try:
            # 1. Show processing status
            target = channel or user_id
            await self.slack_client.chat_postMessage(
                channel=target,
                thread_ts=thread_ts,
                text="🔄 İsteğiniz işleniyor...",
            )

            # 2. Create request tracking
            request = AdvisorRequest(
                request_id=request_id,
                user_id=user_id,
                advisor_key=advisor_key,
                message=message,
                status="processing",
                thread_ts=thread_ts,
                created_at=datetime.now().isoformat(),
            )
            await self.request_manager.save_request(request)

            logger.info(f"Processing request {request_id}: {advisor_key}")

            return request_id

        except Exception as e:
            logger.error(f"Failed to handle advisor request: {e}")
            try:
                target = channel or user_id
                await self.slack_client.chat_postMessage(
                    channel=target,
                    thread_ts=thread_ts,
                    text=f"❌ Hata: {str(e)[:100]}",
                )
            except Exception as post_error:
                logger.error(f"Failed to post error message: {post_error}")
            return None

    async def handle_mention(
        self,
        user_id: str,
        text: str,
        channel: Optional[str] = None,
        thread_ts: Optional[str] = None,
    ) -> Optional[str]:
        """Route an ``@advisor`` mention in a Slack message to the right advisor.

        Args:
            user_id: Slack user ID of the author.
            text: Raw Slack message text (may contain ``<@Uxxxx>`` bot mention).
            channel: Channel the message came from (replies go back here).
            thread_ts: Thread to reply in, when the mention was inside a thread.

        Returns:
            The request ID when the message was routed, otherwise ``None``
            (no mention found, or the advisor name was not recognised).
        """
        advisor_key, raw_mention, remainder = parse_advisor_mention(text)

        if advisor_key is None:
            if raw_mention is None:
                # No @mention at all — nothing to route.
                return None
            logger.info("Unknown advisor mention '@%s' from %s", raw_mention, user_id)
            await self._post_reply(
                channel or user_id,
                build_advisor_help_message(raw_mention),
                thread_ts,
            )
            return None

        if not remainder:
            logger.info(
                "Empty request for advisor %s from %s, sending capabilities",
                advisor_key,
                user_id,
            )
            await self._post_reply(
                channel or user_id,
                f"{ADVISOR_NAMES[advisor_key]} burada. "
                f"{ADVISOR_DESCRIPTIONS.get(advisor_key, '')}\n"
                "Ne yapmamı istediğini yaz.",
                thread_ts,
            )
            return None

        return await self.handle_advisor_request(
            user_id=user_id,
            advisor_key=advisor_key,
            message=remainder,
            channel=channel,
        )

    async def _post_reply(
        self, channel: str, text: str, thread_ts: Optional[str] = None
    ) -> bool:
        """Post a plain text reply, optionally into a thread."""
        if not self.slack_client:
            logger.error("Slack client not configured, cannot reply: %s", text[:80])
            return False
        try:
            kwargs: Dict[str, Any] = {"channel": channel, "text": text}
            if thread_ts:
                kwargs["thread_ts"] = thread_ts
            response = await self.slack_client.chat_postMessage(**kwargs)
            return bool(response.get("ok"))
        except Exception as e:
            logger.error(f"Failed to post reply: {e}")
            return False

    async def complete_advisor_request(
        self,
        request_id: str,
        result: Dict[str, Any],
        drive_links: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Complete an advisor request and post results to Slack.

        Args:
            request_id: Request identifier
            result: Result dict with keys: summary, data, etc.
            drive_links: Dict of {"report": url, "data": url, ...}

        Returns:
            True if successful
        """
        if not self.slack_client:
            logger.error("Slack client not configured for completing requests")
            return False

        try:
            request = await self.request_manager.get_request(request_id)
            if not request:
                logger.error(f"Request not found: {request_id}")
                return False

            # Update request status
            request.status = "completed"
            request.result = result
            request.completed_at = datetime.now().isoformat()
            if drive_links:
                result["drive_links"] = drive_links
            await self.request_manager.save_request(request)

            # Post result to Slack thread
            target = request.user_id  # DM by default
            blocks = self._build_result_blocks(
                request.advisor_key, result, drive_links or {}
            )

            response = await self.slack_client.chat_postMessage(
                channel=target,
                thread_ts=request.thread_ts,
                blocks=blocks,
                text="✅ Analiz tamamlandı",
            )

            if response.get("ok"):
                logger.info(f"Request {request_id} completed successfully")
                return True
            else:
                logger.error(f"Failed to post result: {response.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Failed to complete advisor request {request_id}: {e}")
            return False

    async def fail_advisor_request(self, request_id: str, error: str) -> bool:
        """Mark a request as failed and notify user.

        Args:
            request_id: Request identifier
            error: Error message

        Returns:
            True if successful
        """
        if not self.slack_client:
            logger.error("Slack client not configured for failing requests")
            return False

        try:
            request = await self.request_manager.get_request(request_id)
            if not request:
                logger.error(f"Request not found: {request_id}")
                return False

            # Update request status
            request.status = "failed"
            request.error = error
            request.completed_at = datetime.now().isoformat()
            await self.request_manager.save_request(request)

            # Post error to Slack thread
            target = request.user_id
            await self.slack_client.chat_postMessage(
                channel=target,
                thread_ts=request.thread_ts,
                text=f"❌ Hata oluştu: {error[:200]}",
            )

            logger.warning(f"Request {request_id} failed: {error}")
            return True

        except Exception as e:
            logger.error(f"Failed to fail advisor request {request_id}: {e}")
            return False

    def _build_update_blocks(
        self, advisor_key: str, report_data: dict
    ) -> List[Dict[str, Any]]:
        """Build Block Kit message for daily advisor update."""
        advisor_name = ADVISOR_NAMES.get(advisor_key, advisor_key)
        timestamp = report_data.get("timestamp", datetime.now())
        if isinstance(timestamp, datetime):
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M")
        else:
            timestamp_str = str(timestamp)

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{advisor_name} Günlük Rapor"},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": report_data.get("summary", "")},
            },
        ]

        # Add Drive links if available
        drive_links = report_data.get("drive_links", {})
        if drive_links:
            fields = []
            for key, url in drive_links.items():
                emoji = "📄"
                if "data" in key.lower():
                    emoji = "📊"
                elif "analysis" in key.lower():
                    emoji = "📈"

                fields.append(
                    {
                        "type": "mrkdwn",
                        "text": f"*{key.title()}*\n<{url}|{emoji} Aç>",
                    }
                )

            # Add metadata fields
            fields.extend(
                [
                    {
                        "type": "mrkdwn",
                        "text": f"*Zaman*\n{timestamp_str}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": "*Durum*\n✅ Hazır",
                    },
                ]
            )

            blocks.append(
                {
                    "type": "section",
                    "fields": fields,
                }
            )

        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_Sorular sormak veya daha derin analiz isteyebilmek için bu konuşmaya yanıt verin_",
                },
            }
        )

        return blocks

    def _build_result_blocks(
        self, advisor_key: str, result: dict, drive_links: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """Build Block Kit message for advisor task result."""
        advisor_name = ADVISOR_NAMES.get(advisor_key, advisor_key)

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ {advisor_name} Analizi Tamamlandı",
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": result.get("summary", "")},
            },
            {"type": "divider"},
        ]

        # Add Drive links
        if drive_links:
            fields = []
            for key, url in drive_links.items():
                emoji = "📄"
                if "data" in key.lower():
                    emoji = "📊"
                elif "analysis" in key.lower():
                    emoji = "📈"

                fields.append(
                    {
                        "type": "mrkdwn",
                        "text": f"*{key.title()}*\n<{url}|{emoji} Google Drive'da Aç>",
                    }
                )

            blocks.append(
                {
                    "type": "section",
                    "fields": fields[:4],  # Max 4 fields per section
                }
            )

            # Add extra fields if more than 4
            if len(fields) > 4:
                blocks.append(
                    {
                        "type": "section",
                        "fields": fields[4:],
                    }
                )

        return blocks


class AdvisorThreadManager:
    """Manages Slack thread persistence for ongoing advisor conversations."""

    def __init__(self, state_file: str = f"{STATE_DIR}/advisor_threads.json"):
        """Initialize thread manager.

        Args:
            state_file: Path to thread state JSON file
        """
        self.state_file = state_file
        self._ensure_state_dir()

    @staticmethod
    def _ensure_state_dir() -> None:
        """Ensure state directory exists."""
        os.makedirs(STATE_DIR, exist_ok=True)

    async def get_advisor_thread(
        self,
        advisor_key: str,
        user_id: str,
        slack_client: Optional[Any] = None,
    ) -> str:
        """Get existing or create new thread for advisor-user conversation.

        Args:
            advisor_key: Advisor identifier
            user_id: Slack user ID
            slack_client: AsyncWebClient for creating threads

        Returns:
            Thread timestamp (ts)
        """
        key = f"{advisor_key}_{user_id}"
        threads = self._load_threads()

        if key in threads and threads[key].get("ts"):
            return threads[key]["ts"]

        # Create new thread if client provided
        if slack_client:
            thread_ts = await self._create_advisor_thread(
                advisor_key, user_id, slack_client
            )
            threads[key] = {
                "ts": thread_ts,
                "created_at": datetime.now().isoformat(),
                "advisor_key": advisor_key,
                "user_id": user_id,
            }
            self._save_threads(threads)
            return thread_ts
        else:
            logger.warning(
                f"No existing thread for {key} and slack_client not provided"
            )
            return ""

    async def save_thread(
        self,
        advisor_key: str,
        user_id: str,
        thread_ts: str,
        message_type: str = "conversation",
    ) -> bool:
        """Save thread information.

        Args:
            advisor_key: Advisor identifier
            user_id: Slack user ID
            thread_ts: Thread timestamp
            message_type: Type of thread (conversation, daily_update, etc.)

        Returns:
            True if successful
        """
        try:
            key = f"{advisor_key}_{user_id}"
            threads = self._load_threads()
            threads[key] = {
                "ts": thread_ts,
                "created_at": datetime.now().isoformat(),
                "advisor_key": advisor_key,
                "user_id": user_id,
                "message_type": message_type,
            }
            self._save_threads(threads)
            return True
        except Exception as e:
            logger.error(f"Failed to save thread: {e}")
            return False

    async def _create_advisor_thread(
        self, advisor_key: str, user_id: str, slack_client: Any
    ) -> str:
        """Start new thread with advisor introduction.

        Args:
            advisor_key: Advisor identifier
            user_id: Slack user ID
            slack_client: AsyncWebClient for posting

        Returns:
            Thread timestamp
        """
        advisor_name = ADVISOR_NAMES.get(advisor_key, advisor_key)
        advisor_desc = ADVISOR_DESCRIPTIONS.get(advisor_key, "Destek sağlarım")

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"💬 {advisor_name} Konuşma Odası",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"👋 Merhaba! Ben {advisor_name}.\n\n"
                    f"Uzmanlığım alanlarında soru sorabilirsiniz:\n"
                    f"• {advisor_desc}\n\n"
                    f"İsteklerinizi analiz edip raporları Google Drive üzerinden paylaşırım.",
                },
            },
        ]

        try:
            response = await slack_client.chat_postMessage(
                channel=user_id,
                blocks=blocks,
                text="Danışman konuşması başladı",
            )

            if response.get("ok"):
                return response.get("ts", "")
            else:
                logger.error(f"Failed to create thread: {response.get('error')}")
                return ""
        except Exception as e:
            logger.error(f"Exception creating advisor thread: {e}")
            return ""

    def _load_threads(self) -> Dict[str, Any]:
        """Load thread state from file."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load threads: {e}")
        return {}

    def _save_threads(self, threads: Dict[str, Any]) -> None:
        """Save thread state to file."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(threads, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save threads: {e}")


class AdvisorRequestManager:
    """Manages advisor request state and tracking."""

    def __init__(self, state_file: str = f"{STATE_DIR}/advisor_requests.json"):
        """Initialize request manager.

        Args:
            state_file: Path to requests state JSON file
        """
        self.state_file = state_file
        self._ensure_state_dir()

    @staticmethod
    def _ensure_state_dir() -> None:
        """Ensure state directory exists."""
        os.makedirs(STATE_DIR, exist_ok=True)

    async def save_request(self, request: AdvisorRequest) -> bool:
        """Save request state.

        Args:
            request: AdvisorRequest instance

        Returns:
            True if successful
        """
        try:
            requests = self._load_requests()
            requests[request.request_id] = request.to_dict()
            self._save_requests(requests)
            return True
        except Exception as e:
            logger.error(f"Failed to save request {request.request_id}: {e}")
            return False

    async def get_request(self, request_id: str) -> Optional[AdvisorRequest]:
        """Get request by ID.

        Args:
            request_id: Request identifier

        Returns:
            AdvisorRequest or None if not found
        """
        try:
            requests = self._load_requests()
            data = requests.get(request_id)
            if data:
                return AdvisorRequest.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to get request {request_id}: {e}")
        return None

    async def get_user_requests(
        self, user_id: str, status: Optional[str] = None
    ) -> List[AdvisorRequest]:
        """Get all requests for a user.

        Args:
            user_id: Slack user ID
            status: Filter by status (pending, processing, completed, failed)

        Returns:
            List of AdvisorRequest instances
        """
        try:
            requests = self._load_requests()
            user_requests = [
                AdvisorRequest.from_dict(r)
                for r in requests.values()
                if r.get("user_id") == user_id
            ]

            if status:
                user_requests = [r for r in user_requests if r.status == status]

            return sorted(user_requests, key=lambda r: r.created_at, reverse=True)
        except Exception as e:
            logger.warning(f"Failed to get user requests for {user_id}: {e}")
        return []

    async def cleanup_old_requests(self, days: int = 30) -> int:
        """Remove requests older than N days.

        Args:
            days: Number of days to keep

        Returns:
            Number of requests removed
        """
        try:
            cutoff = datetime.now().timestamp() - (days * 86400)
            requests = self._load_requests()
            removed = 0

            for request_id in list(requests.keys()):
                created_at = datetime.fromisoformat(
                    requests[request_id].get("created_at", "")
                )
                if created_at.timestamp() < cutoff:
                    del requests[request_id]
                    removed += 1

            if removed > 0:
                self._save_requests(requests)
                logger.info(f"Cleaned up {removed} old requests")

            return removed
        except Exception as e:
            logger.error(f"Failed to cleanup requests: {e}")
            return 0

    def _load_requests(self) -> Dict[str, Dict[str, Any]]:
        """Load requests state from file."""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception as e:
            logger.warning(f"Failed to load requests: {e}")
        return {}

    def _save_requests(self, requests: Dict[str, Dict[str, Any]]) -> None:
        """Save requests state to file."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(requests, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save requests: {e}")


# =============================================================================
# CLI entrypoint
# =============================================================================


def build_slack_client(token: Optional[str] = None) -> Optional[Any]:
    """Build an AsyncWebClient, or None when Slack is not configured.

    Returns None (rather than raising) when there is no token or the Slack SDK
    is missing, so callers can report a clear "skipped" instead of a crash.
    """
    token = token or os.getenv("SLACK_BOT_TOKEN", "")
    if not token:
        return None
    try:
        from slack_sdk.web.async_client import AsyncWebClient
    except ImportError:
        logger.error("slack_sdk is not installed; cannot build Slack client")
        return None
    return AsyncWebClient(token=token)


async def process_pending_requests(bridge: SlackAdvisorBridge) -> int:
    """Dispatch every request still sitting in ``pending`` state.

    Returns:
        Number of requests successfully dispatched.
    """
    stored = bridge.request_manager._load_requests()
    pending = [r for r in stored.values() if r.get("status") == "pending"]

    if not pending:
        logger.info("No pending advisor requests to process")
        return 0

    logger.info("Processing %d pending advisor request(s)", len(pending))
    processed = 0
    for raw in pending:
        try:
            request = AdvisorRequest.from_dict(raw)
        except Exception as e:
            logger.error("Skipping malformed request %r: %s", raw, e)
            continue

        advisor_key = request.advisor_key
        message = request.message
        # A request may carry the raw Slack text; re-parse it so an @mention
        # written by the user still wins over whatever was recorded.
        parsed_key, raw_mention, remainder = parse_advisor_mention(message)
        if parsed_key:
            advisor_key = parsed_key
            message = remainder or message
        elif raw_mention and advisor_key not in ADVISOR_NAMES:
            await bridge._post_reply(
                request.user_id,
                build_advisor_help_message(raw_mention),
                request.thread_ts or None,
            )
            await bridge.fail_advisor_request(
                request.request_id, f"unknown advisor: {raw_mention}"
            )
            continue

        result = await bridge.handle_advisor_request(
            user_id=request.user_id,
            advisor_key=advisor_key,
            message=message,
        )
        if result:
            processed += 1
        else:
            logger.warning("Failed to dispatch request %s", request.request_id)

    logger.info("Dispatched %d/%d pending request(s)", processed, len(pending))
    return processed


async def send_daily_updates(
    bridge: SlackAdvisorBridge, advisors: Optional[List[str]] = None
) -> int:
    """Send a daily update for each configured advisor.

    Returns:
        Number of updates posted successfully.
    """
    if advisors is None:
        configured = os.getenv("SLACK_ADVISOR_INCLUDE", "")
        advisors = [a.strip() for a in configured.split(",") if a.strip()] or list(
            ADVISOR_NAMES
        )

    sent = 0
    for advisor_key in advisors:
        report_data = {
            "summary": ADVISOR_DESCRIPTIONS.get(advisor_key, ""),
            "drive_links": {},
            "timestamp": datetime.now(),
        }
        response = await bridge.send_daily_advisor_update(advisor_key, report_data)
        if response and response.get("ok"):
            sent += 1
        else:
            logger.warning("Daily update for %s was not posted", advisor_key)

    logger.info("Posted %d/%d daily advisor update(s)", sent, len(advisors))
    return sent


async def run_cli(args: argparse.Namespace) -> int:
    """Execute the requested CLI action. Returns a process exit code."""
    slack_client = build_slack_client()
    if slack_client is None:
        logger.warning(
            "SKIPPED: Slack is not configured (SLACK_BOT_TOKEN missing or slack_sdk "
            "unavailable) — no advisor requests processed, no updates sent."
        )
        return 0

    bridge = SlackAdvisorBridge(slack_client=slack_client)

    did_something = False
    if args.process_requests:
        await process_pending_requests(bridge)
        did_something = True
    if args.daily_update:
        await send_daily_updates(bridge)
        did_something = True
    if args.cleanup:
        removed = await bridge.request_manager.cleanup_old_requests(days=args.cleanup)
        logger.info("Cleaned up %d old request(s)", removed)
        did_something = True

    if not did_something:
        logger.error("No action requested; pass --process-requests or --daily-update")
        return 1

    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m ai_assistant.integrations.slack_advisor_bridge",
        description="Slack advisor bridge — process requests and post updates.",
    )
    parser.add_argument(
        "--process-requests",
        action="store_true",
        help="Dispatch pending advisor requests to their advisors.",
    )
    parser.add_argument(
        "--daily-update",
        action="store_true",
        help="Post a daily update for each configured advisor.",
    )
    parser.add_argument(
        "--cleanup",
        type=int,
        metavar="DAYS",
        default=0,
        help="Remove requests older than DAYS.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint. Returns an exit code (0 ok / 1 failure)."""
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_arg_parser().parse_args(argv)

    try:
        return asyncio.run(run_cli(args))
    except Exception:
        logger.exception("slack advisor bridge failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
