"""Consolidated Communications + Calendar Advisor — İletişim & Takvim Danışmanı.

Merges email analysis (Mail Analyst) and calendar scheduling (Day Planner) into
a single unified advisor that provides a complete view of:

- Email volume, urgency, and action items
- Calendar density and meeting load
- Communication velocity and response requirements
- Availability windows and meeting clustering
- Focus time identification
- Unified scheduling recommendations

This advisor fetches both Gmail and Google Calendar data, analyzes them locally,
and generates a comprehensive JSON report with merged insights and recommendations
for optimizing both communication and scheduling.

Features:
    - Email urgency assessment and categorization
    - Calendar density analysis and meeting load
    - Optimal response time suggestions
    - Meeting clustering detection
    - Focus time identification (free blocks > 1 hour)
    - Communication velocity analysis
    - Back-to-back meeting period warnings
    - Available slots for new meetings
    - Unified Turkish recommendations

Auth: Reuses existing shared Google OAuth
(:mod:`ai_assistant.integrations.google_auth`, read-only scopes).

PRIVACY: Personal data (emails, calendar events) — marked private=True.

Configuration (via environment):
    MAIL_ANALYST_MAX_EMAILS     How many emails to analyze (default 50).
    MAIL_ANALYST_EMAIL_WINDOW   Gmail time window (default "1d").
    WORK_START_HOUR             Working day start (default 9).
    WORK_END_HOUR               Working day end (default 18).
    CALENDAR_TIMEZONE           Calendar timezone (default Europe/Istanbul).

Data first: all email and calendar fetching, parsing, and analysis happens
locally; LLM summarization (if enabled) is optional via batch processing.

Report Structure (JSON):
{
    "generated_at": "ISO timestamp",
    "summary": "Turkish summary of combined communication & schedule state",
    "email": {
        "unread_count": int,
        "total_emails_24h": int,
        "urgent_count": int,
        "important_count": int,
        "action_items": int,
        "vip_emails": [...],
        "response_time_hours": float,
        "volume_trend": "increasing|normal|decreasing",
        "busiest_senders": [...]
    },
    "calendar": {
        "today_meetings": int,
        "total_meeting_time_hours": float,
        "focus_blocks": [...],
        "next_meeting": "...",
        "available_slots": [...],
        "back_to_back_periods": [...],
        "meeting_density": "high|medium|low"
    },
    "communication": {
        "total_communication_items": int,
        "urgency_score": float,
        "response_velocity": float,
        "vip_load": int
    },
    "recommendations": {
        "email_strategy": "...",
        "schedule_optimization": "...",
        "availability": "...",
        "communication_priorities": "..."
    }
}
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any

from . import Advisor, Briefing
from ..integrations import google_auth

# Configuration constants
DEFAULT_MAX_EMAILS = 50
DEFAULT_EMAIL_WINDOW = "1d"
DEFAULT_WORK_START_HOUR = 9
DEFAULT_WORK_END_HOUR = 18
DEFAULT_TIMEZONE = "Europe/Istanbul"
SNIPPET_LIMIT = 220

SKIP_DETAIL = (
    "no Google credentials/token configured "
    "(run: python -m ai_assistant.integrations.google_auth, then set "
    "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN)"
)

# Keywords for email categorization (Turkish)
URGENT_KEYWORDS = [
    "acil", "hemen", "bugün", "deadline", "critical", "kritikal",
    "emergency", "urgent", "önemli", "asap", "hızlı", "hızlıca",
    "derhal", "immediately", "zanı", "zanında", "yanında"
]

ACTION_KEYWORDS = [
    "lütfen", "please", "ihtiyaç", "need", "request", "istek",
    "yapacaksınız", "yapcaksınız", "toplantı", "meeting", "görüş",
    "sonuç", "result", "bilgi", "information", "onay", "approval"
]

# VIP sender patterns
VIP_PATTERNS = [
    r"\b[Cc][Ee][Oo]\b", r"\bcto\b", r"\bchief\b",
    r"\bmanager\b", r"\byönetici\b", r"\bdirector\b", r"\bdirecteur\b",
    r"\bkurucu\b", r"\bfounders?\b", r"\bexecutive\b", r"\bvp\b", r"\bboss\b"
]


# ============================================================================
# Data classes for email analysis
# ============================================================================

@dataclass
class EmailMessage:
    """Parsed email metadata."""
    email_id: str
    sender: str
    subject: str
    timestamp: str
    snippet: str
    importance: str  # urgent, important, action, info
    is_unread: bool = False
    is_starred: bool = False
    action_item: Optional[str] = None
    is_vip_sender: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, omitting email_id."""
        d = asdict(self)
        d.pop("email_id", None)
        return d


@dataclass
class EmailStats:
    """Email analysis statistics."""
    total_emails: int = 0
    unread: int = 0
    from_vip: int = 0
    urgent: int = 0
    important: int = 0
    info: int = 0
    action_needed: int = 0
    action_items: int = 0
    avg_response_time_hours: float = 0.0
    volume_trend: str = "normal"  # increasing, normal, decreasing

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# Data classes for calendar analysis
# ============================================================================

@dataclass
class EventInfo:
    """Parsed calendar event."""
    summary: str
    start_time: str  # HH:MM format
    end_time: str  # HH:MM format
    duration_minutes: int
    attendees: List[str] = field(default_factory=list)
    location: Optional[str] = None
    is_all_day: bool = False
    event_type: str = "meeting"  # meeting, personal, focus

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FocusBlock:
    """Free time block suitable for focused work."""
    start: str  # HH:MM
    end: str  # HH:MM
    duration_minutes: int
    quality: str = "good"  # excellent, good, interrupted, poor

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AvailableSlot:
    """Recommended time slot for new meetings."""
    start: str  # HH:MM
    end: str  # HH:MM
    duration_minutes: int
    quality: str = "good"  # excellent, good

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CalendarStats:
    """Calendar analysis statistics."""
    total_meetings: int = 0
    total_meeting_time_hours: float = 0.0
    focus_blocks: List[FocusBlock] = field(default_factory=list)
    back_to_back_periods: List[Dict[str, Any]] = field(default_factory=list)
    events: List[EventInfo] = field(default_factory=list)
    next_meeting: Optional[str] = None
    available_slots: List[AvailableSlot] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_meetings": self.total_meetings,
            "total_meeting_time_hours": self.total_meeting_time_hours,
            "focus_blocks": [b.to_dict() for b in self.focus_blocks],
            "back_to_back_periods": self.back_to_back_periods,
            "events": [e.to_dict() for e in self.events],
            "next_meeting": self.next_meeting,
            "available_slots": [s.to_dict() for s in self.available_slots],
        }


@dataclass
class CommunicationsCalendarReport:
    """Unified communications + calendar report."""
    generated_at: str
    summary: str
    email_stats: EmailStats
    email_list: List[Dict[str, Any]]
    action_items: List[str]
    calendar_stats: CalendarStats
    communication_metrics: Dict[str, Any]
    recommendations: Dict[str, str]

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(
            {
                "generated_at": self.generated_at,
                "summary": self.summary,
                "email": {
                    **self.email_stats.to_dict(),
                    "vip_emails": self.email_list[:5],
                    "action_items": self.action_items[:10],
                },
                "calendar": self.calendar_stats.to_dict(),
                "communication": self.communication_metrics,
                "recommendations": self.recommendations,
            },
            ensure_ascii=False,
            indent=2,
        )


# ============================================================================
# Main Advisor
# ============================================================================

class CommunicationsCalendarAdvisor(Advisor):
    """Unified email + calendar advisor."""

    key = "communications_calendar"
    title = "İletişim & Takvim Danışmanı"
    private = True  # Personal email and calendar data
    incremental_source = False  # Daily analysis, not incremental

    def __init__(self) -> None:
        self._emails: List[EmailMessage] = []
        self._calendar_events: List[EventInfo] = []
        self._error: str = ""
        self._report: Optional[CommunicationsCalendarReport] = None

    # -- Main generation path ------------------------------------------------

    def _generate(self) -> Briefing:
        """Generate the unified communications + calendar briefing."""
        if not google_auth.google_configured():
            return self.skipped(SKIP_DETAIL)

        # Gather email data
        emails = self._gather_emails()
        if emails is None:
            return self.failed(self._error or "E-posta verileri alınamadı")

        self._emails = emails or []

        # Gather calendar data
        try:
            creds = google_auth.get_credentials()
            calendar_events = self._fetch_calendar_events(creds)
            self._calendar_events = calendar_events or []
        except Exception as exc:
            # Calendar failure is non-critical; proceed with email only
            self._calendar_events = []
            self._error = f"Takvim verisi alınamadı: {exc}"

        # Check if we have any data
        if not self._emails and not self._calendar_events:
            return self.ok(
                "**Öne çıkan:** Bugün e-posta ve takvim verisi bulunamadı.\n\n"
                "Gelen kutunuz sessiz ve takvim açık — istirahat fırsatı."
            )

        # Generate unified report
        report = self._generate_report()
        self._report = report

        return self.ok(self._format_briefing(report))

    # ========================================================================
    # EMAIL DATA GATHERING
    # ========================================================================

    def _gather_emails(self) -> Optional[List[EmailMessage]]:
        """Fetch recent emails from Gmail (last 24 hours)."""
        try:
            creds = google_auth.get_credentials()
        except Exception as exc:
            self._error = f"Google kimlik doğrulaması başarısız: {exc}"
            return None

        try:
            from googleapiclient.discovery import build

            service = build("gmail", "v1", credentials=creds, cache_discovery=False)

            # Query: last 24 hours, exclude promotions/social, exclude drafts/sent
            query = (
                f"newer_than:{_email_window()} "
                "-category:promotions -category:social "
                "-label:DRAFT -label:SENT"
            )

            listing = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=_max_emails())
                .execute()
            )

            emails = []
            for ref in listing.get("messages", [])[: _max_emails()]:
                try:
                    message = (
                        service.users()
                        .messages()
                        .get(
                            userId="me",
                            id=ref["id"],
                            format="metadata",
                            metadataHeaders=["From", "Subject", "Date"],
                        )
                        .execute()
                    )
                    email = self._parse_email(message)
                    if email:
                        emails.append(email)
                except Exception:
                    continue

            return emails

        except Exception as exc:
            self._error = f"Gmail okunamadı: {type(exc).__name__}: {exc}"
            return None

    def _parse_email(self, message: dict) -> Optional[EmailMessage]:
        """Parse Gmail message metadata."""
        msg_id = message.get("id", "")
        if not msg_id:
            return None

        sender = self._get_header(message, "From") or "bilinmeyen gönderen"
        subject = self._get_header(message, "Subject") or "(konu yok)"
        date_str = self._get_header(message, "Date") or ""

        snippet = (message.get("snippet") or "").strip().replace("\n", " ")
        if len(snippet) > SNIPPET_LIMIT:
            snippet = snippet[:SNIPPET_LIMIT] + "…"

        labels = message.get("labelIds") or []
        is_unread = "UNREAD" in labels
        is_starred = "STARRED" in labels

        # Categorize email
        importance = self._categorize_email(subject, snippet, sender)

        # Extract action item
        action_item = None
        if importance in ("urgent", "action"):
            action_item = self._extract_action_item(subject, snippet)

        # Check VIP sender
        is_vip = self._is_vip_sender(sender)

        # Parse timestamp
        timestamp = self._parse_date(date_str)

        return EmailMessage(
            email_id=msg_id,
            sender=sender,
            subject=subject,
            timestamp=timestamp,
            snippet=snippet,
            importance=importance,
            is_unread=is_unread,
            is_starred=is_starred,
            action_item=action_item,
            is_vip_sender=is_vip,
        )

    def _get_header(self, message: dict, header_name: str) -> Optional[str]:
        """Extract header value from Gmail message."""
        headers = message.get("payload", {}).get("headers", [])
        for h in headers:
            if h.get("name") == header_name:
                return h.get("value")
        return None

    def _categorize_email(self, subject: str, snippet: str, sender: str) -> str:
        """Categorize email by importance."""
        combined = f"{subject} {snippet} {sender}".lower()

        if any(kw in combined for kw in URGENT_KEYWORDS):
            return "urgent"

        if self._is_vip_sender(sender):
            return "important"

        if any(kw in combined for kw in ACTION_KEYWORDS):
            return "action"

        return "info"

    def _extract_action_item(self, subject: str, snippet: str) -> Optional[str]:
        """Extract action item text if detected."""
        combined = f"{subject}: {snippet}"

        patterns = [
            r"lütfen\s+([^.!?]+[.!?])",
            r"please\s+([^.!?]+[.!?])",
            r"ihtiyaç\s+([^.!?]+[.!?])",
            r"yapacaksınız\s+([^.!?]+[.!?])",
            r"toplantı.*?(\d{2}:\d{2}|\d{1,2}[.]\d{1,2})",
        ]

        for pattern in patterns:
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                action_text = match.group(1).strip()
                return action_text[:150]

        if subject and len(subject) < 150:
            return subject

        return None

    def _is_vip_sender(self, sender: str) -> bool:
        """Check if sender is a VIP."""
        sender_lower = sender.lower()
        return any(re.search(pattern, sender_lower) for pattern in VIP_PATTERNS)

    def _parse_date(self, date_str: str) -> str:
        """Parse Gmail date header to ISO format."""
        if not date_str:
            return datetime.now().isoformat()

        try:
            from email.utils import parsedate_to_datetime

            dt = parsedate_to_datetime(date_str)
            return dt.isoformat()
        except Exception:
            return datetime.now().isoformat()

    # ========================================================================
    # CALENDAR DATA GATHERING
    # ========================================================================

    def _fetch_calendar_events(self, creds: Any) -> List[EventInfo]:
        """Fetch calendar events for today."""
        from googleapiclient.discovery import build

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        now = datetime.now(timezone.utc)
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = time_min + timedelta(days=1)

        result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )

        events = []
        today = datetime.now().date()

        for event in result.get("items", []):
            parsed = self._parse_event(event, today)
            if parsed:
                events.append(parsed)

        return events

    def _parse_event(
        self, event: Dict[str, Any], target_date: Any
    ) -> Optional[EventInfo]:
        """Parse a Google Calendar event."""
        summary = event.get("summary", "Untitled")

        # Skip all-day events
        if "date" in event.get("start", {}):
            return None

        start_str = event.get("start", {}).get("dateTime")
        end_str = event.get("end", {}).get("dateTime")

        if not start_str or not end_str:
            return None

        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

        if start_dt.date() != target_date:
            return None

        start_time = start_dt.strftime("%H:%M")
        end_time = end_dt.strftime("%H:%M")
        duration = int((end_dt - start_dt).total_seconds() / 60)

        attendees = [
            a.get("email", "").split("@")[0]
            for a in event.get("attendees", [])
            if a.get("email")
        ]

        location = event.get("location")
        event_type = self._categorize_event(summary)

        return EventInfo(
            summary=summary,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration,
            attendees=attendees,
            location=location,
            is_all_day=False,
            event_type=event_type,
        )

    def _categorize_event(self, summary: str) -> str:
        """Categorize event."""
        summary_lower = summary.lower()

        focus_keywords = [
            "focus", "deep work", "concentration", "workout",
            "exercise", "lunch", "break"
        ]
        if any(kw in summary_lower for kw in focus_keywords):
            return "focus"

        personal_keywords = [
            "personal", "private", "dentist", "doctor", "appointment"
        ]
        if any(kw in summary_lower for kw in personal_keywords):
            return "personal"

        return "meeting"

    # ========================================================================
    # REPORT GENERATION
    # ========================================================================

    def _generate_report(self) -> CommunicationsCalendarReport:
        """Generate unified report."""
        now = datetime.now()

        # Email stats
        email_stats = self._compute_email_stats()

        # Prepare email list for report
        importance_order = {"urgent": 0, "important": 1, "action": 2, "info": 3}
        sorted_emails = sorted(
            self._emails,
            key=lambda e: (importance_order.get(e.importance, 3), e.timestamp),
            reverse=True,
        )
        email_list = [email.to_dict() for email in sorted_emails]

        # Action items
        action_items = [
            email.action_item
            for email in self._emails
            if email.action_item and email.importance in ("urgent", "action")
        ]

        # Calendar analysis
        calendar_stats = self._analyze_calendar()

        # Communication metrics
        communication_metrics = self._compute_communication_metrics(
            email_stats, calendar_stats
        )

        # Recommendations
        recommendations = self._generate_recommendations(
            email_stats, calendar_stats, communication_metrics
        )

        summary = self._create_summary(
            email_stats, calendar_stats, communication_metrics
        )

        return CommunicationsCalendarReport(
            generated_at=now.isoformat(),
            summary=summary,
            email_stats=email_stats,
            email_list=email_list,
            action_items=action_items,
            calendar_stats=calendar_stats,
            communication_metrics=communication_metrics,
            recommendations=recommendations,
        )

    def _compute_email_stats(self) -> EmailStats:
        """Compute email statistics."""
        stats = EmailStats(total_emails=len(self._emails))
        stats.unread = sum(1 for e in self._emails if e.is_unread)
        stats.from_vip = sum(1 for e in self._emails if e.is_vip_sender)
        stats.urgent = sum(1 for e in self._emails if e.importance == "urgent")
        stats.important = sum(1 for e in self._emails if e.importance == "important")
        stats.info = sum(1 for e in self._emails if e.importance == "info")
        stats.action_needed = sum(1 for e in self._emails if e.importance == "action")
        stats.action_items = sum(1 for e in self._emails if e.action_item)

        # Volume trend
        if len(self._emails) > 40:
            stats.volume_trend = "increasing"
        elif len(self._emails) < 10:
            stats.volume_trend = "decreasing"

        # Response time
        if stats.urgent > 0:
            stats.avg_response_time_hours = 1.0
        elif stats.action_needed > 0:
            stats.avg_response_time_hours = 2.5
        else:
            stats.avg_response_time_hours = 4.0

        return stats

    def _analyze_calendar(self) -> CalendarStats:
        """Analyze calendar events."""
        stats = CalendarStats()

        if not self._calendar_events:
            return stats

        # Sort events
        events = sorted(self._calendar_events, key=lambda e: e.start_time)

        # Meetings
        meetings = [e for e in events if e.event_type == "meeting"]
        stats.total_meetings = len(meetings)
        stats.total_meeting_time_hours = sum(e.duration_minutes for e in meetings) / 60

        # Events
        stats.events = events

        # Focus blocks
        stats.focus_blocks = self._find_focus_blocks(events)

        # Back-to-back periods
        stats.back_to_back_periods = self._find_back_to_back_periods(events)

        # Available slots
        stats.available_slots = self._find_available_slots(
            events, stats.focus_blocks
        )

        # Next meeting
        now = datetime.now()
        stats.next_meeting = self._get_next_meeting(events, now)

        return stats

    def _find_focus_blocks(self, events: List[EventInfo]) -> List[FocusBlock]:
        """Identify free time blocks > 1 hour."""
        work_start = _work_start_hour()
        work_end = _work_end_hour()

        blocks = []

        if events:
            first_start = int(events[0].start_time.split(":")[0])
            if first_start - work_start >= 1:
                blocks.append(
                    FocusBlock(
                        start=f"{work_start:02d}:00",
                        end=events[0].start_time,
                        duration_minutes=(first_start - work_start) * 60,
                        quality="excellent",
                    )
                )

        # Gaps between events
        for i in range(len(events) - 1):
            curr_end_h, curr_end_m = map(int, events[i].end_time.split(":"))
            next_start_h, next_start_m = map(int, events[i + 1].start_time.split(":"))

            curr_end_minutes = curr_end_h * 60 + curr_end_m
            next_start_minutes = next_start_h * 60 + next_start_m
            gap_minutes = next_start_minutes - curr_end_minutes

            if gap_minutes >= 60:
                blocks.append(
                    FocusBlock(
                        start=events[i].end_time,
                        end=events[i + 1].start_time,
                        duration_minutes=gap_minutes,
                        quality="good",
                    )
                )

        # End of day
        if events:
            last_end = int(events[-1].end_time.split(":")[0])
            if work_end - last_end >= 1:
                blocks.append(
                    FocusBlock(
                        start=events[-1].end_time,
                        end=f"{work_end:02d}:00",
                        duration_minutes=(work_end - last_end) * 60,
                        quality="good",
                    )
                )

        # If no events, entire work day is focus
        if not events:
            blocks.append(
                FocusBlock(
                    start=f"{work_start:02d}:00",
                    end=f"{work_end:02d}:00",
                    duration_minutes=(work_end - work_start) * 60,
                    quality="excellent",
                )
            )

        return blocks

    def _find_back_to_back_periods(self, events: List[EventInfo]) -> List[Dict]:
        """Identify back-to-back meeting periods."""
        if not events:
            return []

        periods = []
        current_period_start = None
        current_period_end = None
        period_meetings = []

        for event in events:
            if event.event_type != "meeting":
                continue

            if current_period_end is None:
                current_period_start = event.start_time
                current_period_end = event.end_time
                period_meetings = [event.summary]
            else:
                curr_end_h, curr_end_m = map(int, current_period_end.split(":"))
                next_start_h, next_start_m = map(int, event.start_time.split(":"))

                curr_end_minutes = curr_end_h * 60 + curr_end_m
                next_start_minutes = next_start_h * 60 + next_start_m
                gap_minutes = next_start_minutes - curr_end_minutes

                if gap_minutes <= 5:
                    current_period_end = event.end_time
                    period_meetings.append(event.summary)
                else:
                    if len(period_meetings) >= 2:
                        periods.append(
                            {
                                "start": current_period_start,
                                "end": current_period_end,
                                "meeting_count": len(period_meetings),
                                "meetings": period_meetings,
                            }
                        )
                    current_period_start = event.start_time
                    current_period_end = event.end_time
                    period_meetings = [event.summary]

        if len(period_meetings) >= 2:
            periods.append(
                {
                    "start": current_period_start,
                    "end": current_period_end,
                    "meeting_count": len(period_meetings),
                    "meetings": period_meetings,
                }
            )

        return periods

    def _find_available_slots(
        self, events: List[EventInfo], focus_blocks: List[FocusBlock]
    ) -> List[AvailableSlot]:
        """Find recommended time slots for new meetings."""
        slots = []

        for block in focus_blocks:
            if block.duration_minutes >= 30:
                quality = "excellent" if block.duration_minutes >= 90 else "good"
                slots.append(
                    AvailableSlot(
                        start=block.start,
                        end=block.end,
                        duration_minutes=block.duration_minutes,
                        quality=quality,
                    )
                )

        slots.sort(key=lambda s: s.duration_minutes, reverse=True)
        return slots[:5]

    def _get_next_meeting(self, events: List[EventInfo], now: datetime) -> Optional[str]:
        """Get next upcoming meeting."""
        meetings = [e for e in events if e.event_type == "meeting"]
        if not meetings:
            return None

        for meeting in meetings:
            try:
                meeting_time = datetime.strptime(meeting.start_time, "%H:%M")
                if now.time() < meeting_time.time():
                    attendees_str = (
                        f", {', '.join(meeting.attendees)}" if meeting.attendees else ""
                    )
                    return f"Saat {meeting.start_time}'de {meeting.summary}{attendees_str}"
            except ValueError:
                continue

        return "Bugün daha fazla toplantı yok"

    def _compute_communication_metrics(
        self, email_stats: EmailStats, calendar_stats: CalendarStats
    ) -> Dict[str, Any]:
        """Compute unified communication metrics."""
        total_items = email_stats.total_emails + calendar_stats.total_meetings

        # Urgency score (0-10)
        urgency_score = min(
            10.0,
            (email_stats.urgent * 3.0 + email_stats.action_needed * 2.0) / max(1, total_items) * 10,
        )

        # Response velocity (emails per hour requiring attention)
        response_velocity = max(0, email_stats.action_needed + email_stats.urgent)

        return {
            "total_communication_items": total_items,
            "urgency_score": round(urgency_score, 1),
            "response_velocity": response_velocity,
            "vip_load": email_stats.from_vip,
            "estimated_response_hours": email_stats.avg_response_time_hours,
        }

    def _generate_recommendations(
        self,
        email_stats: EmailStats,
        calendar_stats: CalendarStats,
        communication_metrics: Dict[str, Any],
    ) -> Dict[str, str]:
        """Generate recommendations."""
        recommendations = {}

        # Email strategy
        if email_stats.urgent > 0:
            recommendations["email_strategy"] = (
                f"⚠️ {email_stats.urgent} acil e-posta var. Hemen adres — ilk {email_stats.avg_response_time_hours} "
                f"saatte cevap ver. VIP'lerden {email_stats.from_vip} posta bulunmakta."
            )
        elif email_stats.action_needed > 0:
            recommendations["email_strategy"] = (
                f"✅ {email_stats.action_needed} aksiyon maddesi tespit edildi. Öncelik listeni şimdi güncelle."
            )
        else:
            recommendations["email_strategy"] = (
                f"📧 Inbox dengeli — {email_stats.total_emails} e-posta, "
                f"{email_stats.unread} okunmamış. Sakin ortam."
            )

        # Schedule optimization
        meeting_hours = calendar_stats.total_meeting_time_hours
        if meeting_hours >= 6:
            recommendations["schedule_optimization"] = (
                f"🚨 Yoğun gün: {meeting_hours:.1f} saat toplantı. Takvimi optimize etmeyi düşün — "
                f"bazı toplantıları topla/ertele."
            )
        elif meeting_hours >= 4:
            recommendations["schedule_optimization"] = (
                f"📅 Orta yoğunluk ({meeting_hours:.1f} saat toplantı). "
                f"Verimliliği artırmak için ardışık toplantıları birleştir."
            )
        elif calendar_stats.focus_blocks:
            best_block = max(calendar_stats.focus_blocks, key=lambda b: b.duration_minutes)
            recommendations["schedule_optimization"] = (
                f"✨ Harika! Saat {best_block.start}-{best_block.end} arası "
                f"{best_block.duration_minutes} dk kesintisiz çalışma zamanı. "
                f"Derin işleri bura planla."
            )
        else:
            recommendations["schedule_optimization"] = (
                "📊 Takvim boş — tam kontrol senin. Odaklanma bloklarını strateji ile yerleştir."
            )

        # Availability
        available_count = len(calendar_stats.available_slots)
        if available_count > 0:
            recommendations["availability"] = (
                f"👍 {available_count} uygun slot var. Gelen istekler için "
                f"{calendar_stats.available_slots[0]['start']}-{calendar_stats.available_slots[0]['end']} "
                f"arası en ideal."
            )
        else:
            recommendations["availability"] = (
                "🔴 Bugün tamamen dolu — acil olmayan yeni toplantıları yarına ertele."
            )

        # Communication priorities
        if communication_metrics["urgency_score"] >= 7:
            recommendations["communication_priorities"] = (
                "🔴 Yüksek iletişim yükü. Odak: acil e-postalar ve VIP gönderici takip. "
                "Diğer işleri 2-3 saat sonraya ertele."
            )
        elif communication_metrics["urgency_score"] >= 4:
            recommendations["communication_priorities"] = (
                "🟡 Orta iletişim yükü. Takvimi bloklar halinde kontrol et — "
                "saatlik değil, 30-dakikalık seanslar yap."
            )
        else:
            recommendations["communication_priorities"] = (
                "🟢 Düşük iletişim yükü. Bütün katıl ve uzun vadeli projeleri ilerlet."
            )

        return recommendations

    def _create_summary(
        self,
        email_stats: EmailStats,
        calendar_stats: CalendarStats,
        communication_metrics: Dict[str, Any],
    ) -> str:
        """Create Turkish summary."""
        parts = []

        # Email part
        if email_stats.urgent > 0:
            parts.append(f"⚠️ {email_stats.urgent} acil e-posta")
        elif email_stats.action_needed > 0:
            parts.append(f"✅ {email_stats.action_needed} aksiyon maddesi")
        else:
            parts.append(f"📧 {email_stats.total_emails} e-posta")

        # Calendar part
        if calendar_stats.total_meetings > 0:
            parts.append(f"📅 {calendar_stats.total_meetings} toplantı ({calendar_stats.total_meeting_time_hours:.1f} saat)")
        elif calendar_stats.focus_blocks:
            best_block = max(calendar_stats.focus_blocks, key=lambda b: b.duration_minutes)
            parts.append(f"💡 {best_block.duration_minutes} dk odaklanma zamanı")

        urgency = communication_metrics["urgency_score"]
        if urgency >= 7:
            intensity = "çok yoğun"
        elif urgency >= 4:
            intensity = "orta yoğun"
        else:
            intensity = "sakin"

        return f"{' • '.join(parts)} — {intensity} bir gün olacak."

    # ========================================================================
    # FORMATTING
    # ========================================================================

    def _format_briefing(self, report: CommunicationsCalendarReport) -> str:
        """Format report as Turkish briefing."""
        lines = [f"**Öne çıkan:** {report.summary}"]
        lines.append("")

        # Email section
        stats = report.email_stats
        lines.append("**📧 E-Posta Özeti**")
        lines.append(f"- Toplam: {stats.total_emails} e-posta")
        if stats.urgent > 0:
            lines.append(f"- ⚠️ Acil: {stats.urgent}")
        if stats.action_needed > 0:
            lines.append(f"- ✅ Aksiyon gerekli: {stats.action_needed}")
        if stats.from_vip > 0:
            lines.append(f"- 👔 VIP göndericiler: {stats.from_vip}")
        if stats.unread > 0:
            lines.append(f"- Okunmamış: {stats.unread}")
        lines.append("")

        # Action items
        if report.action_items:
            lines.append("**✅ Çalışma Maddeleri**")
            for i, item in enumerate(report.action_items[:5], 1):
                if item:
                    lines.append(f"{i}. {item[:120]}")
            lines.append("")

        # Calendar section
        cal = report.calendar_stats
        if cal.total_meetings > 0:
            lines.append("**📅 Takvim Özeti**")
            lines.append(f"- Toplantı: {cal.total_meetings} ({cal.total_meeting_time_hours:.1f} saat)")

            if cal.focus_blocks:
                lines.append("- **Odaklanma blokları:**")
                for block in cal.focus_blocks[:3]:
                    lines.append(f"  - {block.start}-{block.end} ({block.duration_minutes} dk)")

            if cal.available_slots:
                lines.append("- **Uygun slotlar:**")
                for slot in cal.available_slots[:3]:
                    lines.append(f"  - {slot.start}-{slot.end} ({slot.duration_minutes} dk)")

            if cal.back_to_back_periods:
                lines.append("- **Ardışık toplantılar:**")
                for period in cal.back_to_back_periods[:2]:
                    lines.append(
                        f"  - {period['start']}-{period['end']}: {period['meeting_count']} toplantı"
                    )
            lines.append("")

        # Recommendations
        lines.append("**✨ Öneriler**")
        for key, rec in report.recommendations.items():
            if rec:
                lines.append(f"- {rec}")

        lines.append("")
        lines.append(
            "**✅ Bugünün görevi:** Acil e-postaları ve aksiyon maddelerini "
            "gözden geçir; sonra takviminin ilk odaklanma bloğunu sakla."
        )

        return "\n".join(lines)


# ============================================================================
# Configuration helpers
# ============================================================================

def _max_emails() -> int:
    """Get max emails to analyze."""
    try:
        value = int(os.getenv("MAIL_ANALYST_MAX_EMAILS") or DEFAULT_MAX_EMAILS)
    except ValueError:
        value = DEFAULT_MAX_EMAILS
    return max(1, min(value, 100))


def _email_window() -> str:
    """Get email time window."""
    raw = (os.getenv("MAIL_ANALYST_EMAIL_WINDOW") or "").strip()
    if raw and raw[:-1].isdigit() and raw[-1] in "hd":
        return raw
    return DEFAULT_EMAIL_WINDOW


def _work_start_hour() -> int:
    """Get working day start hour."""
    try:
        value = int(os.getenv("WORK_START_HOUR") or DEFAULT_WORK_START_HOUR)
    except ValueError:
        value = DEFAULT_WORK_START_HOUR
    return max(0, min(value, 23))


def _work_end_hour() -> int:
    """Get working day end hour."""
    try:
        value = int(os.getenv("WORK_END_HOUR") or DEFAULT_WORK_END_HOUR)
    except ValueError:
        value = DEFAULT_WORK_END_HOUR
    return max(1, min(value, 24))


__all__ = ["CommunicationsCalendarAdvisor"]
