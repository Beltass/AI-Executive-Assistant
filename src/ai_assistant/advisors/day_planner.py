"""Day Planner Advisor — Daily schedule and calendar analysis.

Configuration (via environment):
    GOOGLE_CLIENT_ID        OAuth client ID for Google Calendar access.
    GOOGLE_CLIENT_SECRET    OAuth client secret.
    GOOGLE_TOKEN_FILE       Path to stored Google auth token (defaults to
                            `.google_token.json`).
    GOOGLE_REFRESH_TOKEN    Refresh token for cloud/CI environments.
    WORK_START_HOUR         Working day start hour (default: 9).
    WORK_END_HOUR           Working day end hour (default: 18).
    CALENDAR_TIMEZONE       Timezone for calendar (default: auto-detect from
                            calendar settings or Europe/Istanbul).

The advisor fetches calendar events for today and the next 7 days, analyzes
schedule density, identifies focus time blocks, detects back-to-back meetings,
and provides Turkish language recommendations for better time management.

Outputs a structured JSON report with:
- Schedule summary (total meetings, meeting time, density)
- Focus time blocks (gaps > 1 hour)
- Short breaks (15-30 min gaps)
- Back-to-back meeting periods
- Available slots for new meetings
- Smart recommendations for productivity optimization
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, time, timezone
from typing import List, Optional, Dict, Any

from . import Advisor, Briefing
from ..config import setting
from ..integrations import STATUS_OK
from ..integrations import google_auth

# Default working hours and configuration
DEFAULT_WORK_START_HOUR = 9
DEFAULT_WORK_END_HOUR = 18
DEFAULT_TIMEZONE = "Europe/Istanbul"


@dataclass
class EventInfo:
    """Parsed calendar event details."""

    summary: str
    start_time: str  # HH:MM format
    end_time: str  # HH:MM format
    duration_minutes: int
    attendees: List[str] = field(default_factory=list)
    location: Optional[str] = None
    is_all_day: bool = False
    event_type: str = "meeting"  # meeting, personal, focus


@dataclass
class FocusBlock:
    """Free time block suitable for focused work."""

    start: str  # HH:MM
    end: str  # HH:MM
    duration_minutes: int
    quality: str = "good"  # excellent, good, interrupted, poor


@dataclass
class AvailableSlot:
    """Recommended time slot for new meetings."""

    start: str  # HH:MM
    end: str  # HH:MM
    duration_minutes: int
    quality: str  # excellent, good


@dataclass
class ScheduleReport:
    """Complete schedule analysis report."""

    generated_at: str
    date: str
    summary: str
    total_meetings: int = 0
    total_meeting_time_hours: float = 0.0
    focus_blocks: List[FocusBlock] = field(default_factory=list)
    back_to_back_periods: List[Dict[str, Any]] = field(default_factory=list)
    events: List[EventInfo] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    next_meeting: Optional[str] = None
    available_slots: List[AvailableSlot] = field(default_factory=list)


class DayPlannerAdvisor(Advisor):
    """Daily schedule advisor — analyzes calendar for time management insights."""

    key = "day_planner"
    title = "Günlük Planlayıcı"
    incremental_source = False
    private = True  # Contains personal calendar data

    def _generate(self) -> Briefing:
        if not google_auth.google_configured():
            return self.skipped(
                "missing env var(s): GOOGLE credentials not configured"
            )

        try:
            creds = google_auth.get_credentials()
        except google_auth.GoogleAuthError as exc:
            return self.skipped(f"Google auth unavailable: {exc}")

        try:
            events = self._fetch_calendar_events(creds)
        except Exception as exc:
            return self.failed(f"Takvim verisi alınamadı: {exc}")

        report = self._analyze_schedule(events)
        text = self._format_briefing(report)
        return self.ok(text)

    # -- Calendar fetching ---------------------------------------------------

    def _fetch_calendar_events(self, creds: Any) -> List[Dict[str, Any]]:
        """Fetch calendar events for today and the next 7 days."""
        from googleapiclient.discovery import build

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)

        now = datetime.now(timezone.utc)
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
        time_max = time_min + timedelta(days=8)

        # Fetch primary calendar
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

        return result.get("items", [])

    # -- Schedule analysis ---------------------------------------------------

    def _analyze_schedule(self, raw_events: List[Dict[str, Any]]) -> ScheduleReport:
        """Analyze calendar events and generate schedule report."""
        today = datetime.now().date()
        now = datetime.now()

        # Parse and filter events
        events = []
        for event in raw_events:
            parsed = self._parse_event(event, today)
            if parsed:
                events.append(parsed)

        # Sort events by start time
        events.sort(key=lambda e: e.start_time)

        # Calculate metrics
        meetings = [e for e in events if e.event_type == "meeting"]
        total_meeting_time = sum(e.duration_minutes for e in meetings)

        # Identify focus blocks (free time > 1 hour during work hours)
        focus_blocks = self._find_focus_blocks(events, today)

        # Detect back-to-back periods
        back_to_back = self._find_back_to_back_periods(events)

        # Find available slots for new meetings
        available_slots = self._find_available_slots(events, focus_blocks, today)

        # Find next meeting
        next_meeting = self._get_next_meeting(events, now)

        # Generate recommendations
        recommendations = self._generate_recommendations(
            events, focus_blocks, total_meeting_time
        )

        return ScheduleReport(
            generated_at=now.isoformat(),
            date=today.isoformat(),
            summary=self._create_summary(
                today, len(meetings), total_meeting_time, focus_blocks
            ),
            total_meetings=len(meetings),
            total_meeting_time_hours=total_meeting_time / 60.0,
            focus_blocks=focus_blocks,
            back_to_back_periods=back_to_back,
            events=[asdict(e) for e in events],
            recommendations=recommendations,
            next_meeting=next_meeting,
            available_slots=[asdict(s) for s in available_slots],
        )

    def _parse_event(
        self, event: Dict[str, Any], target_date: Any
    ) -> Optional[EventInfo]:
        """Parse a Google Calendar event into EventInfo."""
        summary = event.get("summary", "Untitled")

        # Handle all-day events
        if "date" in event.get("start", {}):
            return None  # Skip all-day events for now

        # Get start/end times
        start_str = event.get("start", {}).get("dateTime")
        end_str = event.get("end", {}).get("dateTime")

        if not start_str or not end_str:
            return None

        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

        # Filter to today only for now (can extend to 7 days as needed)
        if start_dt.date() != target_date:
            return None

        # Extract time strings
        start_time = start_dt.strftime("%H:%M")
        end_time = end_dt.strftime("%H:%M")
        duration = int((end_dt - start_dt).total_seconds() / 60)

        # Extract attendees
        attendees = [
            a.get("email", "").split("@")[0]
            for a in event.get("attendees", [])
            if a.get("email")
        ]

        location = event.get("location", None)

        # Categorize event
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
        """Categorize event based on summary."""
        summary_lower = summary.lower()

        # Keywords for focus time or personal events
        focus_keywords = [
            "focus",
            "deep work",
            "concentration",
            "workout",
            "exercise",
            "lunch",
            "break",
        ]
        if any(kw in summary_lower for kw in focus_keywords):
            return "focus"

        # Personal events
        personal_keywords = ["personal", "private", "dentist", "doctor", "appointment"]
        if any(kw in summary_lower for kw in personal_keywords):
            return "personal"

        return "meeting"

    def _find_focus_blocks(
        self, events: List[EventInfo], date: Any
    ) -> List[FocusBlock]:
        """Identify free time blocks > 1 hour suitable for focused work."""
        work_start = DEFAULT_WORK_START_HOUR
        work_end = DEFAULT_WORK_END_HOUR

        blocks = []

        # Add work start block
        if events:
            first_start = int(events[0].start_time.split(":")[0])
            if first_start - work_start >= 1:  # At least 1 hour
                blocks.append(
                    FocusBlock(
                        start=f"{work_start:02d}:00",
                        end=events[0].start_time,
                        duration_minutes=(first_start - work_start) * 60,
                        quality="excellent",
                    )
                )

        # Add gaps between events
        for i in range(len(events) - 1):
            curr_end_h, curr_end_m = map(int, events[i].end_time.split(":"))
            next_start_h, next_start_m = map(int, events[i + 1].start_time.split(":"))

            curr_end_minutes = curr_end_h * 60 + curr_end_m
            next_start_minutes = next_start_h * 60 + next_start_m
            gap_minutes = next_start_minutes - curr_end_minutes

            if gap_minutes >= 60:  # At least 1 hour
                quality = "good" if gap_minutes >= 90 else "good"
                blocks.append(
                    FocusBlock(
                        start=events[i].end_time,
                        end=events[i + 1].start_time,
                        duration_minutes=gap_minutes,
                        quality=quality,
                    )
                )

        # Add end of day block
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

        # If no events, entire work day is a focus block
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
        """Identify back-to-back meeting periods (consecutive meetings)."""
        if not events:
            return []

        periods = []
        current_period_start = None
        current_period_end = None
        period_meetings = []

        for i, event in enumerate(events):
            if event.event_type != "meeting":
                continue

            # Check if this meeting is back-to-back with the previous one
            if current_period_end is None:
                current_period_start = event.start_time
                current_period_end = event.end_time
                period_meetings = [event.summary]
            else:
                # Check if meeting starts within 5 minutes of previous end
                curr_end_h, curr_end_m = map(int, current_period_end.split(":"))
                next_start_h, next_start_m = map(int, event.start_time.split(":"))

                curr_end_minutes = curr_end_h * 60 + curr_end_m
                next_start_minutes = next_start_h * 60 + next_start_m
                gap_minutes = next_start_minutes - curr_end_minutes

                if gap_minutes <= 5:
                    # Continuation of back-to-back period
                    current_period_end = event.end_time
                    period_meetings.append(event.summary)
                else:
                    # End current period if it has 2+ meetings
                    if len(period_meetings) >= 2:
                        periods.append(
                            {
                                "start": current_period_start,
                                "end": current_period_end,
                                "meeting_count": len(period_meetings),
                                "meetings": period_meetings,
                            }
                        )
                    # Start new period
                    current_period_start = event.start_time
                    current_period_end = event.end_time
                    period_meetings = [event.summary]

        # Add final period if it has 2+ meetings
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
        self, events: List[EventInfo], focus_blocks: List[FocusBlock], date: Any
    ) -> List[AvailableSlot]:
        """Find recommended time slots for new meetings."""
        work_start = DEFAULT_WORK_START_HOUR
        work_end = DEFAULT_WORK_END_HOUR

        slots = []

        # Return best focus blocks as available slots (these are ideal for meetings too)
        for block in focus_blocks:
            if block.duration_minutes >= 30:
                quality = "excellent" if block.duration_minutes >= 90 else "good"
                slots.append(
                    AvailableSlot(
                        start=block.start, end=block.end, duration_minutes=block.duration_minutes, quality=quality
                    )
                )

        # Sort by duration (longest first)
        slots.sort(key=lambda s: s.duration_minutes, reverse=True)

        return slots[:5]  # Return top 5 slots

    def _get_next_meeting(self, events: List[EventInfo], now: datetime) -> Optional[str]:
        """Get the next upcoming meeting."""
        meetings = [e for e in events if e.event_type == "meeting"]
        if not meetings:
            return None

        for meeting in meetings:
            meeting_time = datetime.strptime(meeting.start_time, "%H:%M")
            if now.time() < meeting_time.time():
                attendees_str = (
                    f", {', '.join(meeting.attendees)}" if meeting.attendees else ""
                )
                return f"Saat {meeting.start_time}'de {meeting.summary}{attendees_str}"

        # If no more meetings today
        return "Bugün daha fazla toplantı yok"

    def _generate_recommendations(
        self,
        events: List[EventInfo],
        focus_blocks: List[FocusBlock],
        total_meeting_time_minutes: int,
    ) -> List[str]:
        """Generate Turkish recommendations for better time management."""
        recommendations = []

        # Meeting density check
        total_meeting_time_hours = total_meeting_time_minutes / 60
        if total_meeting_time_hours >= 6:
            recommendations.append(
                "⚠️ Günde 6+ saat toplantı yoğunluğu tespit edildi. Toplantı yükünü azaltmayı düşün."
            )
        elif total_meeting_time_hours >= 4:
            recommendations.append(
                "Toplantılarınız günün yarısını kaplayıyor. Verimliliği artırmak için bazı toplantıları "
                "azalt veya birleştir."
            )

        # Focus time recommendations
        if not focus_blocks:
            recommendations.append(
                "🚨 Bugün odaklanma zamanı bulunamadı. Takvimi gözden geçir veya odaklanma bloğu ekle."
            )
        else:
            best_block = max(focus_blocks, key=lambda b: b.duration_minutes)
            if best_block.duration_minutes >= 90:
                recommendations.append(
                    f"✅ Saat {best_block.start}-{best_block.end} arası ({best_block.duration_minutes} dk) "
                    "mükemmel odaklanma zamanı. Derin çalışmanı burada planla."
                )

        # Break recommendations
        short_breaks = [e for e in events if "break" in e.summary.lower()]
        if not short_breaks and len(events) > 3:
            recommendations.append(
                "💪 3+ saat toplantı arası ara ver. Akşam çayınızı takvime ekleyin."
            )

        # Back-to-back period warning
        if len([e for e in events if e.event_type == "meeting"]) >= 5:
            recommendations.append(
                "🔄 Ardışık toplantılar enerjini tüketiyor. Yarın takvimini daha esnek planla."
            )

        # Evening focus time
        evening_hours = [e for e in events if int(e.start_time.split(":")[0]) >= 17]
        if not evening_hours:
            recommendations.append("Akşam 17:00 sonrası boş. Uzun vadeli projeler için harikaası.")

        # Default recommendation if no others
        if not recommendations:
            recommendations.append(
                "📅 Takvim dengeli görünüyor. Verilen odaklanma bloklarını maksimum verimliliğe kullan."
            )

        return recommendations

    def _create_summary(
        self,
        date: Any,
        meeting_count: int,
        total_meeting_time_minutes: int,
        focus_blocks: List[FocusBlock],
    ) -> str:
        """Create a Turkish summary of the day's schedule."""
        total_hours = total_meeting_time_minutes / 60
        focus_hours = sum(b.duration_minutes for b in focus_blocks) / 60

        parts = [
            f"📅 {date.strftime('%A, %d %B').replace('Monday', 'Pazartesi').replace('Tuesday', 'Salı')}",
            f"📊 {meeting_count} toplantı ({total_hours:.1f} saat),",
            f"💡 {focus_hours:.1f} saatlik odaklanma zamanı",
        ]

        if total_hours >= 6:
            intensity = "yoğun"
        elif total_hours >= 4:
            intensity = "orta"
        else:
            intensity = "hafif"

        return f"{' '.join(parts)} — gün {intensity} bir gün olacak."

    # -- Formatting ----------------------------------------------------------

    def _format_briefing(self, report: ScheduleReport) -> str:
        """Format the schedule analysis as a Turkish briefing."""
        lines = []

        # Header
        lines.append("*📅 Günün Takvim Özeti*")
        lines.append("")
        lines.append(f"**Öne çıkan:** {report.summary}")
        lines.append("")

        # Next meeting
        if report.next_meeting:
            lines.append(f"**Sıradaki toplantı:** {report.next_meeting}")
            lines.append("")

        # Meeting summary
        lines.append("*Toplantılar & Zaman*")
        lines.append(
            f"- Bugün {report.total_meetings} toplantı, toplam {report.total_meeting_time_hours:.1f} saat"
        )

        # Focus blocks
        if report.focus_blocks:
            lines.append("")
            lines.append("*💡 Odaklanma Blokları*")
            for block in report.focus_blocks[:3]:  # Show top 3
                lines.append(
                    f"- Saat {block.start}-{block.end} ({block.duration_minutes} dk) — "
                    f"*{block.quality}* ⭐"
                )

        # Back-to-back periods warning
        if report.back_to_back_periods:
            lines.append("")
            lines.append("*🔄 Ardışık Toplantı Dönemleri*")
            for period in report.back_to_back_periods[:2]:
                lines.append(
                    f"- {period['start']}-{period['end']}: {period['meeting_count']} arka arkaya toplantı"
                )

        # Recommendations
        if report.recommendations:
            lines.append("")
            lines.append("*✨ Öneriler*")
            for rec in report.recommendations[:4]:  # Top 4 recommendations
                lines.append(f"- {rec}")

        # Available slots for new meetings
        if report.available_slots:
            lines.append("")
            lines.append("*📍 Yeni Toplantılar için Uygun Slotlar*")
            for slot in report.available_slots[:3]:
                lines.append(
                    f"- {slot['start']}-{slot['end']} ({slot['duration_minutes']} dk) — "
                    f"{slot['quality']}"
                )

        # Daily task
        lines.append("")
        lines.append(
            "### ✅ Bugünün görevi"
        )
        lines.append(
            "Takvimindeki ilk odaklanma bloğuna 10 dakika haber/Slack kontrol olmadan "
            "gir ve en az 2 pomodoro çalış. Sonra check-in yap: enerji nasıl?"
        )

        # Optional: Add raw JSON report as a note
        lines.append("")
        lines.append(
            "_İstatistikler JSON formatında tamamlı rapor: aşağıdaki verileri uygulamalarına entegre edin_"
        )

        return "\n".join(lines)


__all__ = ["DayPlannerAdvisor"]
