"""Service for Slack integration."""

import logging
import json
from typing import Optional, Dict, Any
import requests

from app.config import settings

logger = logging.getLogger(__name__)


class SlackService:
    """Service for Slack integration."""

    def __init__(self):
        """Initialize Slack service."""
        self.bot_token = settings.SLACK_BOT_TOKEN
        self.signing_secret = settings.SLACK_SIGNING_SECRET
        self.base_url = "https://slack.com/api"

    async def send_message(
        self, channel: str, text: str, blocks: Optional[list] = None
    ) -> bool:
        """
        Send message to Slack channel.

        Args:
            channel: Channel ID or name
            text: Message text
            blocks: Optional message blocks for rich formatting

        Returns:
            True if successful
        """
        try:
            payload = {
                "channel": channel,
                "text": text,
            }

            if blocks:
                payload["blocks"] = blocks

            response = requests.post(
                f"{self.base_url}/chat.postMessage",
                json=payload,
                headers={"Authorization": f"Bearer {self.bot_token}"},
                timeout=10,
            )

            if response.status_code != 200:
                logger.error(f"Slack API error: {response.text}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error sending Slack message: {e}")
            return False

    async def send_content_approval_request(
        self, channel: str, content_id: int, topic: str, preview: str
    ) -> bool:
        """Send content approval request to Slack."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*New content ready for approval*\n\nTopic: {topic}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Preview:\n```{preview[:500]}...```",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "value": f"approve_{content_id}",
                        "action_id": "content_approve",
                        "style": "primary",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Regenerate"},
                        "value": f"regenerate_{content_id}",
                        "action_id": "content_regenerate",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "value": f"reject_{content_id}",
                        "action_id": "content_reject",
                        "style": "danger",
                    },
                ],
            },
        ]

        return await self.send_message(
            channel, f"Content {content_id} ready for review", blocks
        )

    async def send_engagement_summary(
        self, channel: str, content_id: int, metrics: Dict[str, Any]
    ) -> bool:
        """Send engagement summary for content."""
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Engagement Summary - Content #{content_id}*",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Views:*\n{metrics.get('views', 0)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Likes:*\n{metrics.get('likes', 0)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Comments:*\n{metrics.get('comments', 0)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Shares:*\n{metrics.get('shares', 0)}",
                    },
                ],
            },
        ]

        return await self.send_message(channel, "Engagement Summary", blocks)

    async def get_user_by_email(self, email: str) -> Optional[str]:
        """Get Slack user ID by email."""
        try:
            response = requests.post(
                f"{self.base_url}/users.lookupByEmail",
                data={"email": email},
                headers={"Authorization": f"Bearer {self.bot_token}"},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    return data.get("user", {}).get("id")

            return None

        except Exception as e:
            logger.error(f"Error looking up user: {e}")
            return None

    async def open_modal(self, trigger_id: str, view: Dict[str, Any]) -> bool:
        """Open a modal in Slack."""
        try:
            response = requests.post(
                f"{self.base_url}/views.open",
                json={"trigger_id": trigger_id, "view": view},
                headers={"Authorization": f"Bearer {self.bot_token}"},
                timeout=10,
            )

            if response.status_code != 200:
                logger.error(f"Slack API error: {response.text}")
                return False

            return True

        except Exception as e:
            logger.error(f"Error opening modal: {e}")
            return False

    def verify_request(self, timestamp: str, signature: str, body: str) -> bool:
        """Verify Slack request signature."""
        import hmac
        import hashlib

        if abs(int(timestamp) - self._get_current_time()) > 300:
            return False

        basestring = f"v0:{timestamp}:{body}"
        my_signature = (
            "v0="
            + hmac.new(
                self.signing_secret.encode(),
                basestring.encode(),
                hashlib.sha256,
            ).hexdigest()
        )

        return hmac.compare_digest(my_signature, signature)

    def _get_current_time(self) -> int:
        """Get current Unix timestamp."""
        import time

        return int(time.time())
