"""Notification system for task deadlines via Slack, Email, and SMS.

Provides multi-channel alert delivery with intelligent scheduling:
- Slack: Direct messages with interactive buttons
- Email: HTML-formatted alerts via Gmail
- SMS: Critical alerts via Twilio
- Deadline tracking: -1 day, -2 hours, overdue levels
- Timezone-aware scheduling
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import List, Optional, Dict, Any

import pytz

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Alert severity levels."""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    def emoji(self) -> str:
        """Get emoji representation."""
        return {
            AlertLevel.LOW: "ℹ️",
            AlertLevel.MEDIUM: "⏰",
            AlertLevel.HIGH: "⚠️",
            AlertLevel.CRITICAL: "🚨",
        }[self]


@dataclass
class AlertMessage:
    """Alert message to be sent across channels."""

    task_id: str
    title: str
    deadline: datetime
    owner: str
    level: AlertLevel
    message: str
    channels: List[str]  # ["slack", "email", "sms"]
    description: Optional[str] = None
    priority: int = 3


class NotificationManager:
    """Manages multi-channel alert delivery for task deadlines.

    Supports:
    - Slack direct messages with interactive buttons
    - Email alerts via Gmail
    - SMS alerts via Twilio (for HIGH/CRITICAL only)
    - Concurrent delivery with error handling
    """

    def __init__(
        self,
        slack_token: Optional[str] = None,
        gmail_creds: Optional[Dict[str, Any]] = None,
        twilio_sid: Optional[str] = None,
        twilio_token: Optional[str] = None,
        twilio_phone: Optional[str] = None,
    ):
        """Initialize NotificationManager.

        Args:
            slack_token: Slack bot token for API calls
            gmail_creds: Google service credentials dict
            twilio_sid: Twilio account SID
            twilio_token: Twilio auth token
            twilio_phone: Twilio phone number
        """
        self.slack_token = slack_token or os.getenv("SLACK_BOT_TOKEN")
        self.gmail_creds = gmail_creds
        self.twilio_sid = twilio_sid or os.getenv("TWILIO_ACCOUNT_SID")
        self.twilio_token = twilio_token or os.getenv("TWILIO_AUTH_TOKEN")
        self.twilio_phone = twilio_phone or os.getenv("TWILIO_PHONE_NUMBER")

        self.slack_client = None
        self.gmail_service = None
        self.twilio_client = None

        self._init_clients()

    def _init_clients(self) -> None:
        """Initialize API clients."""
        # Slack client
        if self.slack_token:
            try:
                from slack_sdk import WebClient

                self.slack_client = WebClient(token=self.slack_token)
                logger.info("Slack client initialized")
            except ImportError:
                logger.warning("slack-sdk not installed; Slack alerts disabled")
            except Exception as e:
                logger.error(f"Failed to initialize Slack client: {e}")

        # Gmail service
        if self.gmail_creds:
            try:
                from googleapiclient.discovery import build

                self.gmail_service = build("gmail", "v1", credentials=self.gmail_creds)
                logger.info("Gmail service initialized")
            except ImportError:
                logger.warning("google-api-client not installed; Email alerts disabled")
            except Exception as e:
                logger.error(f"Failed to initialize Gmail service: {e}")

        # Twilio client
        if self.twilio_sid and self.twilio_token:
            try:
                from twilio.rest import Client

                self.twilio_client = Client(self.twilio_sid, self.twilio_token)
                logger.info("Twilio client initialized")
            except ImportError:
                logger.warning("twilio not installed; SMS alerts disabled")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}")

    def send_alert_sync(self, alert: AlertMessage) -> Dict[str, bool]:
        """Send alert across multiple channels (synchronous).

        Args:
            alert: AlertMessage to send

        Returns:
            Dictionary mapping channel names to success status
        """
        results = {}

        if "slack" in alert.channels and self.slack_client:
            results["slack"] = self._send_slack_alert(alert)

        if "email" in alert.channels and self.gmail_service:
            results["email"] = self._send_email_alert(alert)

        if (
            "sms" in alert.channels
            and self.twilio_client
            and alert.level in [AlertLevel.HIGH, AlertLevel.CRITICAL]
        ):
            results["sms"] = self._send_sms_alert(alert)

        return results

    async def send_alert(self, alert: AlertMessage) -> Dict[str, bool]:
        """Send alert across multiple channels (async wrapper).

        Args:
            alert: AlertMessage to send

        Returns:
            Dictionary mapping channel names to success status
        """
        # Run synchronous operations in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.send_alert_sync, alert)

    def _send_slack_alert(self, alert: AlertMessage) -> bool:
        """Send alert to Slack with interactive buttons.

        Args:
            alert: Alert message

        Returns:
            True if successful
        """
        if not self.slack_client:
            return False

        try:
            blocks = [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"{alert.level.emoji()} Task Deadline Alert",
                    },
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Task:*\n{alert.title}"},
                        {"type": "mrkdwn", "text": f"*Owner:*\n{alert.owner}"},
                        {
                            "type": "mrkdwn",
                            "text": f"*Deadline:*\n{alert.deadline.strftime('%Y-%m-%d %H:%M')}",
                        },
                        {"type": "mrkdwn", "text": f"*Level:*\n{alert.level.name}"},
                    ],
                },
            ]

            if alert.message:
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": alert.message},
                    }
                )

            # Add interactive buttons
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "✅ Mark Done"},
                            "value": alert.task_id,
                            "action_id": f"task_done_{alert.task_id}",
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "🔄 Reschedule"},
                            "value": alert.task_id,
                            "action_id": f"task_reschedule_{alert.task_id}",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "👤 Reassign"},
                            "value": alert.task_id,
                            "action_id": f"task_reassign_{alert.task_id}",
                        },
                    ],
                }
            )

            response = self.slack_client.chat_postMessage(
                channel=f"@{alert.owner}",
                blocks=blocks,
                text=f"Task Alert: {alert.title}",
            )

            if response.get("ok"):
                logger.info(
                    f"Slack alert sent to @{alert.owner} for task {alert.task_id}"
                )
                return True
            else:
                logger.error(f"Slack alert failed: {response.get('error')}")
                return False

        except Exception as e:
            logger.error(f"Slack alert error: {e}")
            return False

    def _send_email_alert(self, alert: AlertMessage) -> bool:
        """Send email alert via Gmail.

        Args:
            alert: Alert message

        Returns:
            True if successful
        """
        if not self.gmail_service:
            return False

        try:
            import base64
            from email.mime.text import MIMEText

            subject = f"Task Alert: {alert.title}"
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <h2>{alert.title}</h2>
                <p><strong>Owner:</strong> {alert.owner}</p>
                <p><strong>Deadline:</strong> {alert.deadline.strftime('%Y-%m-%d %H:%M')}</p>
                <p><strong>Level:</strong> <span style="color: red;">{alert.level.name}</span></p>
                {f'<p>{alert.description}</p>' if alert.description else ''}
                <p>{alert.message}</p>
                <hr>
                <p style="color: gray; font-size: 12px;">
                    This is an automated notification from AI Executive Assistant.
                </p>
            </body>
            </html>
            """

            message = MIMEText(html_body, "html")
            message["to"] = alert.owner
            message["subject"] = subject

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

            self.gmail_service.users().messages().send(
                userId="me", body={"raw": raw_message}
            ).execute()

            logger.info(f"Email alert sent to {alert.owner} for task {alert.task_id}")
            return True

        except Exception as e:
            logger.error(f"Email alert error: {e}")
            return False

    def _send_sms_alert(self, alert: AlertMessage) -> bool:
        """Send SMS alert via Twilio (critical alerts only).

        Args:
            alert: Alert message

        Returns:
            True if successful
        """
        if not self.twilio_client or not self.twilio_phone:
            return False

        try:
            message_text = (
                f"{alert.level.emoji()} {alert.title} due "
                f"{alert.deadline.strftime('%Y-%m-%d %H:%M')}"
            )

            # In production, look up user phone from profile
            user_phone = os.getenv(f"PHONE_{alert.owner.upper()}")
            if not user_phone:
                logger.warning(f"No phone number for {alert.owner}")
                return False

            message = self.twilio_client.messages.create(
                body=message_text, from_=self.twilio_phone, to=user_phone
            )

            logger.info(f"SMS alert sent to {alert.owner} (SID: {message.sid})")
            return True

        except Exception as e:
            logger.error(f"SMS alert error: {e}")
            return False


class DeadlineTracker:
    """Monitors tasks and sends alerts at appropriate times.

    Alert thresholds:
    - -1 day: MEDIUM alert
    - -2 hours: HIGH alert
    - Overdue: CRITICAL alert
    """

    def __init__(
        self, notification_manager: NotificationManager, user_timezone: str = "UTC"
    ):
        """Initialize DeadlineTracker.

        Args:
            notification_manager: NotificationManager instance
            user_timezone: User's timezone (e.g., 'Europe/Istanbul')
        """
        self.notification_manager = notification_manager
        self.user_timezone = pytz.timezone(user_timezone)
        self.checked_alerts: set = set()  # Track which alerts have been sent

    async def check_deadlines(self, tasks: List[Any]) -> Dict[str, int]:
        """Check tasks for upcoming deadlines and send alerts.

        Args:
            tasks: List of Task objects

        Returns:
            Dictionary with counts of alerts sent per level
        """
        alert_counts = {
            "low": 0,
            "medium": 0,
            "high": 0,
            "critical": 0,
        }

        for task in tasks:
            if task.status == "completed" or not task.deadline:
                continue

            # Get current time in user's timezone
            now = datetime.now(self.user_timezone)
            deadline_tz = task.deadline.astimezone(self.user_timezone)

            time_until = deadline_tz - now
            seconds_until = time_until.total_seconds()

            # Determine alert level based on time remaining
            alert_level = None
            reason = ""

            if seconds_until < 0:
                # Overdue
                alert_level = AlertLevel.CRITICAL
                reason = "Overdue"
            elif 0 <= seconds_until <= 7200:
                # Within 2 hours
                alert_level = AlertLevel.HIGH
                reason = "Due within 2 hours"
            elif 7200 < seconds_until <= 86400:
                # Within 1 day
                alert_level = AlertLevel.MEDIUM
                reason = "Due within 1 day"
            elif 86400 < seconds_until <= 172800:
                # Within 2 days - only for high priority
                if task.priority >= 4:
                    alert_level = AlertLevel.LOW
                    reason = "High priority, due within 2 days"

            if alert_level:
                alert_key = f"{task.id}_{alert_level.name}"
                if alert_key not in self.checked_alerts:
                    alert = AlertMessage(
                        task_id=task.id,
                        title=task.title,
                        deadline=task.deadline,
                        owner=task.owner,
                        level=alert_level,
                        message=f"{reason}\n\n{task.description}"
                        if task.description
                        else reason,
                        channels=self._get_channels_for_level(alert_level),
                        description=task.description,
                        priority=task.priority,
                    )

                    await self.notification_manager.send_alert(alert)
                    self.checked_alerts.add(alert_key)

                    # Count by level
                    alert_counts[alert_level.name.lower()] += 1

        return alert_counts

    def _get_channels_for_level(self, level: AlertLevel) -> List[str]:
        """Determine which channels to use for alert level.

        Args:
            level: Alert level

        Returns:
            List of channel names
        """
        if level == AlertLevel.CRITICAL:
            return ["slack", "email", "sms"]
        elif level == AlertLevel.HIGH:
            return ["slack", "email"]
        else:
            return ["slack"]

    def reset_alerts(self) -> None:
        """Reset alert history (daily).

        Call this once per day to allow alerts to be re-sent.
        """
        self.checked_alerts.clear()
        logger.info("Alert history reset")
