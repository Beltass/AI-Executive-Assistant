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

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Awaitable
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
                logger.error(f"Slack error sending daily update: {response.get('error')}")
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
        request_id = f"{advisor_key}_{user_id}_{int(datetime.now().timestamp())}"

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
