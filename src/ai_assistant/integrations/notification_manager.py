"""Notification system for task deadlines via Slack and Email.

Provides multi-channel alert delivery with intelligent scheduling:
- Slack: Direct messages with interactive buttons
- Email: HTML-formatted alerts via Gmail
- Deadline tracking: -1 day, -2 hours, overdue levels
- Timezone-aware scheduling
- Escalation: unanswered critical alerts climb Slack DM -> e-mail
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
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
    channels: List[str]  # ["slack", "email"]
    description: Optional[str] = None
    priority: int = 3


class NotificationManager:
    """Manages multi-channel alert delivery for task deadlines.

    Supports:
    - Slack direct messages with interactive buttons
    - Email alerts via Gmail
    - Concurrent delivery with error handling
    """

    def __init__(
        self,
        slack_token: Optional[str] = None,
        gmail_creds: Optional[Dict[str, Any]] = None,
    ):
        """Initialize NotificationManager.

        Args:
            slack_token: Slack bot token for API calls
            gmail_creds: Google service credentials dict
        """
        self.slack_token = slack_token or os.getenv("SLACK_BOT_TOKEN")
        self.gmail_creds = gmail_creds

        self.slack_client = None
        self.gmail_service = None

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
                        message=(
                            f"{reason}\n\n{task.description}"
                            if task.description
                            else reason
                        ),
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
        if level in (AlertLevel.CRITICAL, AlertLevel.HIGH):
            return ["slack", "email"]
        else:
            return ["slack"]

    def reset_alerts(self) -> None:
        """Reset alert history (daily).

        Call this once per day to allow alerts to be re-sent.
        """
        self.checked_alerts.clear()
        logger.info("Alert history reset")


# =========================================================================== #
# ESCALATION — "telefonuma özel mesaj, cevap vermezsem başka kanaldan ara"
# =========================================================================== #
#
# The chain, in order, and why it is in this order:
#
#   1. slack  — a Slack DM raises a push notification on the phone and costs
#               nothing. It is the primary channel for every alert.
#   2. email  — the last rung, sent only if the DM went unanswered for
#               ESCALATION_DELAY_MINUTES (default 30). Uses the Gmail service
#               NotificationManager already holds. Once it goes out the chain
#               is exhausted; there is no paid channel behind it.
#
# Two guard rails:
#   * Only alerts at or above ESCALATION_MIN_PRIORITY (default P1) may climb.
#     Everything else gets the Slack DM and stops there, so a P3 reminder
#     never makes the phone ring at 03:00.
#   * State lives in .assistant_state/escalations.json — the same store the
#     rest of the assistant uses — so a restarted process does not re-send an
#     alert it already delivered, and an acknowledged alert stays quiet.

STATE_DIR = ".assistant_state"
DEFAULT_ESCALATION_STATE_FILE = f"{STATE_DIR}/escalations.json"

#: Channels in the order they are tried. Index 0 is sent immediately.
ESCALATION_CHAIN = ("slack", "email")

DEFAULT_ESCALATION_DELAY_MINUTES = 30
DEFAULT_ESCALATION_MIN_PRIORITY = "P1"

#: Priority code -> urgency rank (smaller is more urgent). Mirrors
#: ``ai_assistant.action_center``; kept local so this module has no import
#: cycle with the report layer.
_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

#: AlertLevel -> priority code, so DeadlineTracker alerts can feed the chain.
_LEVEL_TO_PRIORITY = {
    AlertLevel.CRITICAL: "P0",
    AlertLevel.HIGH: "P1",
    AlertLevel.MEDIUM: "P2",
    AlertLevel.LOW: "P3",
}


def _env_flag(name: str, default: bool = False) -> bool:
    """Read a boolean env var. Anything not clearly true is false."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "evet"}


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back on anything unparseable."""
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("%s=%r is not an integer; using %s", name, raw, default)
        return default
    return value


def normalize_alert_priority(value: Any, default: str = "P2") -> str:
    """Coerce whatever the caller has into a ``P0``-``P3`` code.

    Accepts the P codes, the 1-5 integer scale used by task objects, and
    :class:`AlertLevel` members.
    """
    if isinstance(value, AlertLevel):
        return _LEVEL_TO_PRIORITY[value]
    if isinstance(value, bool):
        return default
    if isinstance(value, str):
        code = value.strip().upper()
        if code in _PRIORITY_RANK:
            return code
        try:
            value = int(code)
        except (TypeError, ValueError):
            return default
    if isinstance(value, (int, float)):
        rank = min(5, max(1, int(value)))
        return {1: "P0", 2: "P1", 3: "P2", 4: "P3", 5: "P3"}[rank]
    return default


@dataclass
class EscalationRecord:
    """One alert's journey through the channel chain.

    ``stage`` is the index in :data:`ESCALATION_CHAIN` of the channel most
    recently ATTEMPTED, so ``stage=0`` means "the Slack DM went out and we are
    waiting". ``attempts`` keeps the outcome per channel — including the
    honest ``failed:<timestamp>`` entries — because an alert that was never
    delivered must not look like one that was.
    """

    alert_id: str
    title: str
    body: str = ""
    priority: str = "P2"
    created_at: str = ""
    last_sent_at: str = ""
    stage: int = -1
    attempts: Dict[str, str] = field(default_factory=dict)
    acknowledged: bool = False
    acknowledged_at: Optional[str] = None
    closed: bool = False
    closed_reason: str = ""
    escalatable: bool = False
    targets: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EscalationRecord":
        data = dict(data or {})
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def next_channel(self) -> Optional[str]:
        """The channel that would be tried next, or ``None`` at the end."""
        nxt = self.stage + 1
        if nxt >= len(ESCALATION_CHAIN):
            return None
        return ESCALATION_CHAIN[nxt]


class EscalationManager:
    """Sends an alert on Slack and climbs channels while it stays unanswered.

    The manager owns no API client of its own: Slack goes through the
    :class:`~ai_assistant.integrations.slack_advisor_bridge.SlackAdvisorBridge`
    (or, absent one, the Slack client :class:`NotificationManager` already
    built) and e-mail goes through that same NotificationManager's Gmail
    service.
    """

    def __init__(
        self,
        notification_manager: Optional[NotificationManager] = None,
        slack_bridge: Optional[Any] = None,
        state_file: str = DEFAULT_ESCALATION_STATE_FILE,
        delay_minutes: Optional[int] = None,
        min_priority: Optional[str] = None,
        clock: Optional[Any] = None,
    ):
        """Initialize the escalation manager.

        Args:
            notification_manager: Supplies the Slack/Gmail plumbing.
            slack_bridge: Optional SlackAdvisorBridge; preferred for DMs.
            state_file: Where the chain state is persisted.
            delay_minutes: Wait between rungs (default ESCALATION_DELAY_MINUTES).
            min_priority: Lowest priority allowed to escalate (default P1).
            clock: Callable returning an aware ``datetime`` — for tests.
        """
        self.notification_manager = notification_manager or NotificationManager()
        self.slack_bridge = slack_bridge
        self.state_file = Path(state_file)
        self.delay_minutes = (
            delay_minutes
            if delay_minutes is not None
            else _env_int("ESCALATION_DELAY_MINUTES", DEFAULT_ESCALATION_DELAY_MINUTES)
        )
        self.min_priority = normalize_alert_priority(
            min_priority
            or os.getenv("ESCALATION_MIN_PRIORITY")
            or DEFAULT_ESCALATION_MIN_PRIORITY,
            default=DEFAULT_ESCALATION_MIN_PRIORITY,
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

    # --- state ------------------------------------------------------------

    def _now(self) -> datetime:
        moment = self._clock()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment

    def _load(self) -> Dict[str, EscalationRecord]:
        """Read the state file. A corrupt file is a warning, not a crash."""
        if not self.state_file.exists():
            return {}
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8") or "{}")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Escalation state unreadable (%s); starting empty", exc)
            return {}
        records = raw.get("escalations", raw) if isinstance(raw, dict) else {}
        out: Dict[str, EscalationRecord] = {}
        for key, value in (records or {}).items():
            try:
                out[key] = EscalationRecord.from_dict(value)
            except TypeError:
                logger.warning("Dropping malformed escalation record %s", key)
        return out

    def _save(self, records: Dict[str, EscalationRecord]) -> None:
        payload = {
            "schema_version": 1,
            "updated_at": self._now().isoformat(),
            "escalations": {k: v.to_dict() for k, v in records.items()},
        }
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            logger.error("Could not persist escalation state: %s", exc)

    def get(self, alert_id: str) -> Optional[EscalationRecord]:
        """Return the stored record for ``alert_id``, if any."""
        return self._load().get(alert_id)

    def open_escalations(self) -> List[EscalationRecord]:
        """Records still waiting for an answer."""
        return [r for r in self._load().values() if not r.closed and not r.acknowledged]

    # --- policy -----------------------------------------------------------

    def is_escalatable(self, priority: Any) -> bool:
        """True when this priority is urgent enough to climb the chain."""
        code = normalize_alert_priority(priority)
        return _PRIORITY_RANK[code] <= _PRIORITY_RANK[self.min_priority]

    def _due(self, record: EscalationRecord, now: datetime) -> bool:
        """Has the wait since the last send elapsed?"""
        if not record.last_sent_at:
            return True
        try:
            last = datetime.fromisoformat(record.last_sent_at)
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (now - last) >= timedelta(minutes=self.delay_minutes)

    # --- public API -------------------------------------------------------

    async def notify(
        self,
        alert_id: str,
        title: str,
        body: str = "",
        priority: Any = "P2",
        slack_target: Optional[str] = None,
        email_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send the first rung (Slack DM) and register the chain.

        Re-calling with an ``alert_id`` that is still open is a no-op: the
        point of the state file is that the same alert does not get sent over
        and over on every scheduler tick.

        Returns:
            ``{"status": ..., "channel": ..., "sent": bool, "record": dict}``
        """
        records = self._load()
        existing = records.get(alert_id)
        if existing and not existing.closed and not existing.acknowledged:
            return {
                "status": "already_open",
                "channel": ESCALATION_CHAIN[max(existing.stage, 0)],
                "sent": False,
                "record": existing.to_dict(),
            }

        now = self._now()
        code = normalize_alert_priority(priority)
        record = EscalationRecord(
            alert_id=alert_id,
            title=title,
            body=body,
            priority=code,
            created_at=now.isoformat(),
            escalatable=self.is_escalatable(code),
            targets={
                "slack": slack_target or os.getenv("ESCALATION_SLACK_TARGET", ""),
                "email": email_to or os.getenv("ESCALATION_EMAIL_TO", ""),
            },
        )

        sent = await self._send(record, "slack")
        record.stage = 0
        record.attempts["slack"] = ("sent:" if sent else "failed:") + now.isoformat()
        record.last_sent_at = now.isoformat()
        if not record.escalatable:
            # Below the threshold: the DM is the whole story, so close the
            # record now rather than leave a chain that will never advance.
            record.closed = True
            record.closed_reason = "below_priority_threshold"

        records[alert_id] = record
        self._save(records)
        return {
            "status": "sent" if sent else "failed",
            "channel": "slack",
            "sent": sent,
            "record": record.to_dict(),
        }

    def acknowledge(self, alert_id: str, when: Optional[datetime] = None) -> bool:
        """Mark an alert answered. The chain stops here.

        Returns:
            True if an open record was found and closed.
        """
        records = self._load()
        record = records.get(alert_id)
        if not record or record.acknowledged:
            return False
        moment = when or self._now()
        record.acknowledged = True
        record.acknowledged_at = moment.isoformat()
        record.closed = True
        record.closed_reason = "acknowledged"
        records[alert_id] = record
        self._save(records)
        logger.info("Escalation %s acknowledged; chain stopped", alert_id)
        return True

    async def run_escalations(self) -> List[Dict[str, Any]]:
        """Advance every alert whose wait has elapsed. Call this on a timer.

        Returns:
            One result dict per alert that moved a rung.
        """
        records = self._load()
        now = self._now()
        results: List[Dict[str, Any]] = []

        for alert_id, record in records.items():
            if record.closed or record.acknowledged or not record.escalatable:
                continue
            if not self._due(record, now):
                continue

            channel = record.next_channel
            if channel is None:
                record.closed = True
                record.closed_reason = "chain_exhausted"
                results.append(
                    {"alert_id": alert_id, "channel": None, "sent": False,
                     "status": "exhausted"}
                )
                continue

            sent = await self._send(record, channel)
            record.stage += 1
            record.attempts[channel] = (
                "sent:" if sent else "failed:"
            ) + now.isoformat()
            record.last_sent_at = now.isoformat()
            if record.next_channel is None:
                record.closed = True
                record.closed_reason = "chain_exhausted"
            results.append(
                {
                    "alert_id": alert_id,
                    "channel": channel,
                    "sent": sent,
                    "status": "sent" if sent else "failed",
                }
            )

        if results:
            self._save(records)
        return results

    # --- channels ---------------------------------------------------------

    async def _send(self, record: EscalationRecord, channel: str) -> bool:
        """Dispatch to one channel. Never raises; a failure is just ``False``."""
        try:
            if channel == "slack":
                return await self._send_slack(record)
            if channel == "email":
                return await self._send_email(record)
        except Exception as exc:
            logger.error("Escalation %s on %s failed: %s", record.alert_id, channel, exc)
        return False

    def _compose(self, record: EscalationRecord, prefix: str = "") -> str:
        head = f"{prefix}{record.priority} · {record.title}".strip()
        return f"{head}\n{record.body}".strip() if record.body else head

    async def _send_slack(self, record: EscalationRecord) -> bool:
        """Primary rung: a Slack DM, which is the phone's push notification.

        Prefers the SlackAdvisorBridge's client so there is exactly one Slack
        client in the process; falls back to NotificationManager's.
        """
        target = record.targets.get("slack") or ""
        message = self._compose(record, "🚨 ")

        client = getattr(self.slack_bridge, "slack_client", None)
        if client is not None:
            response = client.chat_postMessage(
                channel=target or "@user_dm", text=message
            )
            if asyncio.iscoroutine(response):
                response = await response
            ok = bool(response.get("ok")) if hasattr(response, "get") else bool(response)
            if not ok:
                logger.error("Slack DM failed for %s", record.alert_id)
            return ok

        fallback = getattr(self.notification_manager, "slack_client", None)
        if fallback is None:
            logger.info("Slack DM skipped for %s: no Slack client", record.alert_id)
            return False
        response = fallback.chat_postMessage(channel=target or "@user_dm", text=message)
        if asyncio.iscoroutine(response):
            response = await response
        return bool(response.get("ok")) if hasattr(response, "get") else bool(response)

    async def _send_email(self, record: EscalationRecord) -> bool:
        """Last rung: the same Gmail path NotificationManager already uses."""
        target = record.targets.get("email") or ""
        if not target:
            logger.info("Email escalation skipped for %s: no recipient", record.alert_id)
            return False
        alert = AlertMessage(
            task_id=record.alert_id,
            title=record.title,
            deadline=self._now(),
            owner=target,
            level=(
                AlertLevel.CRITICAL if record.priority == "P0" else AlertLevel.HIGH
            ),
            message=(
                f"{record.body}\n\nBu uyarı Slack DM'de "
                f"{self.delay_minutes} dakikadır yanıtsız kaldığı için e-postaya "
                "yükseltildi."
            ),
            channels=["email"],
            priority=_PRIORITY_RANK[record.priority] + 1,
        )
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.notification_manager._send_email_alert, alert
        )


async def notify_with_escalation(
    alert: AlertMessage,
    manager: Optional[EscalationManager] = None,
) -> Dict[str, Any]:
    """Convenience bridge: put an :class:`AlertMessage` on the chain."""
    escalation = manager or EscalationManager()
    return await escalation.notify(
        alert_id=alert.task_id,
        title=alert.title,
        body=alert.message,
        priority=alert.level,
    )
