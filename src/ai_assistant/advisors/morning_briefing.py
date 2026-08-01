"""Morning performance metrics briefing — Sabah Performans Brifingi.

Analyzes the previous 24 hours of work performance and provides a comprehensive
morning briefing with detailed metrics, trends, and actionable daily goals.

Tracks:
  - Completion Rate: % of tasks completed vs assigned
  - Deadline Adherence: % of deadlines met on time
  - Success Rate: % of successful operations (advisors ran without errors)
  - Effort Efficiency: Token spend vs output quality
  - Meeting Duration: Total hours in meetings (from Day Planner)
  - Focus Time: Uninterrupted work blocks available
  - Email Response: Average response time to emails

Data sources:
  - Previous day's status.json files
  - Advisor reports and execution logs
  - Calendar data (Day Planner advisor)
  - Gmail data (Mail Analyst advisor)
  - Task completion (Accountability Coach)

The briefing includes:
  - Current 24-hour metrics
  - 7-day and 30-day trend comparison
  - Directional indicators (↑ ↓ →)
  - Smart daily goals in Turkish
  - Daily task (Günlük görev) in Turkish

Error handling:
  - If no history: graceful skip
  - If incomplete data: estimate from available
  - Never crash on data issues

Configuration (via environment):
    MORNING_BRIEFING_STATE_FILE   Where the metrics state lives (default:
                                   `.assistant_state/morning_briefing.json`)
    MORNING_BRIEFING_HISTORY_DAYS  Number of days to keep in history (default: 30)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

from . import Advisor, Briefing
from ..config import setting
from ..integrations import STATUS_OK

DEFAULT_STATE_FILE = ".assistant_state/morning_briefing.json"
DEFAULT_HISTORY_DAYS = 30
MIN_HISTORY_RECORDS = 2


@dataclass
class DailyMetrics:
    """Metrics for a single day of performance."""

    date: str  # ISO format YYYY-MM-DD
    completion_rate: float = 0.0  # Percentage 0-100
    deadline_adherence: float = 0.0  # Percentage 0-100
    success_rate: float = 0.0  # Percentage 0-100
    token_efficiency: float = 0.0  # Tokens per unit output
    meeting_hours: float = 0.0  # Hours spent in meetings
    focus_time_hours: float = 0.0  # Hours of uninterrupted work
    email_response_time_hours: float = 0.0  # Average hours to respond
    tasks_completed: int = 0
    tasks_assigned: int = 0
    errors_count: int = 0
    operations_count: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "DailyMetrics":
        """Create from dictionary, with graceful defaults for missing fields."""
        return cls(
            date=str(data.get("date", "")),
            completion_rate=float(data.get("completion_rate") or 0.0),
            deadline_adherence=float(data.get("deadline_adherence") or 0.0),
            success_rate=float(data.get("success_rate") or 0.0),
            token_efficiency=float(data.get("token_efficiency") or 0.0),
            meeting_hours=float(data.get("meeting_hours") or 0.0),
            focus_time_hours=float(data.get("focus_time_hours") or 0.0),
            email_response_time_hours=float(data.get("email_response_time_hours") or 0.0),
            tasks_completed=int(data.get("tasks_completed") or 0),
            tasks_assigned=int(data.get("tasks_assigned") or 0),
            errors_count=int(data.get("errors_count") or 0),
            operations_count=int(data.get("operations_count") or 0),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @property
    def success_operations(self) -> int:
        """Count of successful operations (total - errors)."""
        return max(0, self.operations_count - self.errors_count)


@dataclass
class BriefingMetrics:
    """The complete briefing metrics report."""

    generated_at: str  # ISO format timestamp
    date: str  # ISO format YYYY-MM-DD
    summary: str  # Turkish summary
    metrics: Dict[str, float] = field(default_factory=dict)
    trends: Dict[str, str] = field(default_factory=dict)
    goals_for_today: List[str] = field(default_factory=list)
    daily_task: str = ""  # Turkish daily task

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "generated_at": self.generated_at,
            "date": self.date,
            "summary": self.summary,
            "metrics": self.metrics,
            "trends": self.trends,
            "goals_for_today": self.goals_for_today,
            "daily_task": self.daily_task,
        }

    def as_text(self) -> str:
        """Format as readable briefing text."""
        lines: List[str] = []

        # Header with summary
        lines.append("*Sabah Performans Brifingi*")
        lines.append(f"📊 **Öne çıkan:** {self.summary}")
        lines.append("")

        # Current metrics section
        lines.append("*📈 Günün Metrikleri*")
        if self.metrics:
            metrics_display = {
                "completion_rate": "Tamamlanma Oranı",
                "deadline_adherence": "Zaman Takvimi Uyumu",
                "success_rate": "Başarı Oranı",
                "token_efficiency": "Token Verimliliği",
                "meeting_hours": "Toplantı Saatleri",
                "focus_time_hours": "Yoğunlaşma Saati",
                "email_response_time_hours": "Email Cevap Süresi (sa.)",
            }

            for key, label in metrics_display.items():
                if key in self.metrics:
                    value = self.metrics[key]
                    if "hours" in key or "time" in key:
                        lines.append(f"- {label}: {value:.1f}")
                    elif "efficiency" in key:
                        lines.append(f"- {label}: {value:.1f}")
                    else:
                        lines.append(f"- {label}: {value:.1f}%")
        else:
            lines.append("- Veri henüz mevcut değil")

        lines.append("")

        # Trends section
        lines.append("*📊 Trendler (7 gün ortalamasına kıyasla)*")
        if self.trends:
            for metric, trend in self.trends.items():
                lines.append(f"- {metric}: {trend}")
        else:
            lines.append("- Trend verileri henüz mevcut değil")

        lines.append("")

        # Goals section
        lines.append("*🎯 Bugünün Hedefleri*")
        if self.goals_for_today:
            for i, goal in enumerate(self.goals_for_today, 1):
                lines.append(f"{i}. {goal}")
        else:
            lines.append("- Hedefler henüz belirlenmedim")

        lines.append("")

        # Daily task
        lines.append("*✅ Bugünün görevi*")
        if self.daily_task:
            lines.append(self.daily_task)
        else:
            lines.append("Günü başarıyla bitir.")

        return "\n".join(lines)


class MorningBriefingMetrics:
    """State management for historical metrics and calculations."""

    def __init__(self) -> None:
        self._state_file = setting("MORNING_BRIEFING_STATE_FILE")
        self._history_days = self._get_history_days()
        self._history: Dict[str, DailyMetrics] = {}
        self._load_history()

    def _get_history_days(self) -> int:
        """Load history retention period from config."""
        try:
            days = int(os.getenv("MORNING_BRIEFING_HISTORY_DAYS") or DEFAULT_HISTORY_DAYS)
            return max(2, min(days, 365))
        except ValueError:
            return DEFAULT_HISTORY_DAYS

    def _load_history(self) -> None:
        """Load metric history from state file."""
        if not self._state_file or not os.path.exists(self._state_file):
            return

        try:
            with open(self._state_file, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
                for iso_date, metrics_dict in data.items():
                    try:
                        self._history[iso_date] = DailyMetrics.from_dict(
                            {"date": iso_date, **metrics_dict}
                        )
                    except Exception:
                        # Corrupt entry; skip it
                        continue
        except Exception:
            # Corrupt or unreadable state; start fresh
            pass

    def save_today_metrics(self, metrics: DailyMetrics) -> None:
        """Save today's metrics to state file."""
        if not self._state_file:
            return

        self._history[metrics.date] = metrics
        self._cleanup_old_records()

        try:
            directory = os.path.dirname(self._state_file)
            if directory:
                os.makedirs(directory, exist_ok=True)

            # Serialize history to file
            data_to_save = {
                date_str: metrics.to_dict()
                for date_str, metrics in self._history.items()
            }

            with open(self._state_file, "w", encoding="utf-8") as fh:
                json.dump(data_to_save, fh, ensure_ascii=False, indent=2)
        except Exception:
            # Write-protected or unwritable path; silently degrade
            pass

    def _cleanup_old_records(self) -> None:
        """Keep only the last N days of history."""
        cutoff = (date.today() - timedelta(days=self._history_days)).isoformat()
        old_keys = [k for k in self._history if k < cutoff]
        for key in old_keys:
            self._history.pop(key, None)

    def get_today_metrics(self) -> Optional[DailyMetrics]:
        """Get metrics for today, if available."""
        today_str = date.today().isoformat()
        return self._history.get(today_str)

    def get_yesterday_metrics(self) -> Optional[DailyMetrics]:
        """Get metrics for yesterday."""
        yesterday_str = (date.today() - timedelta(days=1)).isoformat()
        return self._history.get(yesterday_str)

    def get_week_average(self) -> Optional[DailyMetrics]:
        """Calculate average metrics for the past 7 days."""
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        recent = [m for m in self._history.values() if m.date >= cutoff]

        if len(recent) < 2:
            return None

        return self._average_metrics(recent)

    def get_month_average(self) -> Optional[DailyMetrics]:
        """Calculate average metrics for the past 30 days."""
        cutoff = (date.today() - timedelta(days=30)).isoformat()
        recent = [m for m in self._history.values() if m.date >= cutoff]

        if len(recent) < 3:
            return None

        return self._average_metrics(recent)

    @staticmethod
    def _average_metrics(metrics_list: List[DailyMetrics]) -> DailyMetrics:
        """Calculate average of multiple metric records."""
        if not metrics_list:
            return DailyMetrics(date=date.today().isoformat())

        avg = DailyMetrics(date=date.today().isoformat())
        count = len(metrics_list)

        avg.completion_rate = sum(m.completion_rate for m in metrics_list) / count
        avg.deadline_adherence = sum(m.deadline_adherence for m in metrics_list) / count
        avg.success_rate = sum(m.success_rate for m in metrics_list) / count
        avg.token_efficiency = sum(m.token_efficiency for m in metrics_list) / count
        avg.meeting_hours = sum(m.meeting_hours for m in metrics_list) / count
        avg.focus_time_hours = sum(m.focus_time_hours for m in metrics_list) / count
        avg.email_response_time_hours = (
            sum(m.email_response_time_hours for m in metrics_list) / count
        )
        avg.tasks_completed = int(sum(m.tasks_completed for m in metrics_list) / count)
        avg.tasks_assigned = int(sum(m.tasks_assigned for m in metrics_list) / count)

        return avg


class MorningBriefingAdvisor(Advisor):
    """Morning performance metrics briefing advisor.

    Analyzes previous 24 hours and provides actionable insights on:
    - Task completion and deadline adherence
    - Success rate of operations
    - Effort efficiency metrics
    - Time allocation (meetings vs focus time)
    - Communication responsiveness
    - Trends compared to weekly/monthly averages
    - Smart daily goals and tasks
    """

    key = "morning_briefing"
    title = "Sabah Performans Brifingi"

    def __init__(self) -> None:
        self._metrics_manager = MorningBriefingMetrics()
        self._todays_metrics: Optional[DailyMetrics] = None

    def _generate(self) -> Briefing:
        """Generate the morning briefing with metrics and trends."""
        # Build today's metrics from available data
        today_metrics = self._build_todays_metrics()

        # Get historical context
        week_avg = self._metrics_manager.get_week_average()
        month_avg = self._metrics_manager.get_month_average()
        yesterday = self._metrics_manager.get_yesterday_metrics()

        # If no data at all, skip gracefully
        if not today_metrics and not yesterday and not week_avg:
            return self.skipped(
                "performans verileri henüz mevcut değil; "
                "danışmanlar çalıştıktan sonra veriler toplanacak"
            )

        # Save today's metrics for future reference
        if today_metrics:
            self._metrics_manager.save_today_metrics(today_metrics)

        # Generate the briefing
        briefing_metrics = self._generate_briefing_report(
            today_metrics or yesterday,
            week_avg,
            month_avg,
            yesterday,
        )

        return self.ok(briefing_metrics.as_text())

    def _build_todays_metrics(self) -> Optional[DailyMetrics]:
        """Gather today's metrics from available data sources."""
        today_str = date.today().isoformat()
        metrics = DailyMetrics(date=today_str)

        # Try to load from existing status file if available
        status_data = self._load_status_file()
        if status_data:
            metrics = self._extract_metrics_from_status(status_data, metrics)

        # If we have some data, consider it valid
        if metrics.tasks_assigned > 0 or metrics.operations_count > 0:
            return metrics

        # Return None if truly no data
        return None if metrics.tasks_assigned == 0 and metrics.operations_count == 0 else metrics

    def _load_status_file(self) -> Optional[Dict[str, Any]]:
        """Try to load status data from status.json."""
        status_file = ".assistant_state/status.json"
        if not os.path.exists(status_file):
            return None

        try:
            with open(status_file, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def _extract_metrics_from_status(
        self, status_data: Dict[str, Any], metrics: DailyMetrics
    ) -> DailyMetrics:
        """Extract metrics from status.json structure."""
        # Try to extract task metrics
        if "tasks" in status_data:
            tasks = status_data.get("tasks", {})
            metrics.tasks_assigned = int(tasks.get("assigned") or 0)
            metrics.tasks_completed = int(tasks.get("completed") or 0)

            if metrics.tasks_assigned > 0:
                metrics.completion_rate = (
                    metrics.tasks_completed / metrics.tasks_assigned * 100
                )

        # Try to extract deadline metrics
        if "deadlines" in status_data:
            deadlines = status_data.get("deadlines", {})
            total = int(deadlines.get("total") or 0)
            met = int(deadlines.get("met") or 0)

            if total > 0:
                metrics.deadline_adherence = met / total * 100

        # Try to extract success metrics
        if "operations" in status_data:
            ops = status_data.get("operations", {})
            metrics.operations_count = int(ops.get("total") or 0)
            metrics.errors_count = int(ops.get("errors") or 0)

            if metrics.operations_count > 0:
                metrics.success_rate = (
                    (metrics.operations_count - metrics.errors_count)
                    / metrics.operations_count
                    * 100
                )

        # Try to extract meeting hours
        if "calendar" in status_data:
            calendar = status_data.get("calendar", {})
            metrics.meeting_hours = float(calendar.get("meeting_hours") or 0.0)
            metrics.focus_time_hours = float(calendar.get("focus_time_hours") or 0.0)

        # Try to extract email metrics
        if "email" in status_data:
            email = status_data.get("email", {})
            metrics.email_response_time_hours = float(
                email.get("avg_response_time_hours") or 0.0
            )

        # Try to extract token efficiency
        if "tokens" in status_data:
            tokens = status_data.get("tokens", {})
            metrics.token_efficiency = float(tokens.get("efficiency") or 0.0)

        return metrics

    def _generate_briefing_report(
        self,
        today: Optional[DailyMetrics],
        week_avg: Optional[DailyMetrics],
        month_avg: Optional[DailyMetrics],
        yesterday: Optional[DailyMetrics],
    ) -> BriefingMetrics:
        """Generate the formatted briefing report."""
        today_data = today or DailyMetrics(date=date.today().isoformat())
        week_data = week_avg or DailyMetrics(date=date.today().isoformat())

        briefing = BriefingMetrics(
            generated_at=datetime.now().isoformat(),
            date=date.today().isoformat(),
            summary="",
            metrics=self._format_metrics(today_data),
            trends=self._calculate_trends(today_data, week_data),
            goals_for_today=self._generate_goals(today_data),
            daily_task=self._generate_daily_task(today_data),
        )

        # Generate summary
        briefing.summary = self._generate_summary(today_data)

        return briefing

    @staticmethod
    def _format_metrics(metrics: DailyMetrics) -> Dict[str, float]:
        """Format metrics for display."""
        return {
            "completion_rate": round(metrics.completion_rate, 1),
            "deadline_adherence": round(metrics.deadline_adherence, 1),
            "success_rate": round(metrics.success_rate, 1),
            "token_efficiency": round(metrics.token_efficiency, 1),
            "meeting_hours": round(metrics.meeting_hours, 1),
            "focus_time_hours": round(metrics.focus_time_hours, 1),
            "email_response_time_hours": round(metrics.email_response_time_hours, 1),
        }

    @staticmethod
    def _calculate_trends(
        today: DailyMetrics, week_avg: DailyMetrics
    ) -> Dict[str, str]:
        """Calculate trends compared to weekly average."""
        trends = {}

        # Completion rate trend
        completion_diff = today.completion_rate - week_avg.completion_rate
        trends["Tamamlanma"] = _format_trend(
            completion_diff, "↑ +{:.1f}%", "↓ -{:.1f}%", "→ Sabit"
        )

        # Deadline adherence trend
        deadline_diff = today.deadline_adherence - week_avg.deadline_adherence
        trends["Zaman Takvimi"] = _format_trend(
            deadline_diff, "↑ +{:.1f}%", "↓ -{:.1f}%", "→ Sabit"
        )

        # Success rate trend
        success_diff = today.success_rate - week_avg.success_rate
        trends["Başarı"] = _format_trend(
            success_diff, "↑ +{:.1f}%", "↓ -{:.1f}%", "→ Sabit"
        )

        # Focus time trend
        focus_diff = today.focus_time_hours - week_avg.focus_time_hours
        if abs(focus_diff) < 0.1:
            trends["Yoğunlaşma Saati"] = "→ Sabit"
        elif focus_diff > 0:
            trends["Yoğunlaşma Saati"] = f"↑ +{focus_diff:.1f}sa vs dün"
        else:
            trends["Yoğunlaşma Saati"] = f"↓ -{abs(focus_diff):.1f}sa vs dün"

        return trends

    @staticmethod
    def _generate_summary(metrics: DailyMetrics) -> str:
        """Generate Turkish summary of key metrics."""
        if metrics.completion_rate >= 85 and metrics.deadline_adherence >= 90:
            base = "Güçlü bir gün başlangıcı: tamamlanma %{:.0f}, zaman takvimi %{:.0f}".format(
                metrics.completion_rate, metrics.deadline_adherence
            )
        elif metrics.completion_rate >= 70 and metrics.deadline_adherence >= 80:
            base = "Orta ölçüde performans: tamamlanma %{:.0f}, zaman takvimi %{:.0f}".format(
                metrics.completion_rate, metrics.deadline_adherence
            )
        else:
            base = "Dikkat: tamamlanma %{:.0f}, zaman takvimi %{:.0f} — iyileştirilmesi gerekli".format(
                metrics.completion_rate, metrics.deadline_adherence
            )

        if metrics.focus_time_hours >= 3:
            base += ", odaklanma saati yeterli"
        elif metrics.focus_time_hours > 1:
            base += ", odaklanma saati kısıtlı"
        else:
            base += ", odaklanma saati çok az"

        return base + "."

    @staticmethod
    def _generate_goals(metrics: DailyMetrics) -> List[str]:
        """Generate smart daily goals based on metrics."""
        goals = []

        # Completion-focused goal
        if metrics.completion_rate < 80:
            goals.append(
                "Tamamlanma oranını %80+ seviyesine çık — "
                "sabah ilk 2 saatinde en zor görevleri bitir"
            )
        else:
            goals.append(
                "Tamamlanma oranını %85+ sabit tut — "
                "dün başlattığın yarım görevleri bitir"
            )

        # Deadline adherence goal
        if metrics.deadline_adherence < 90:
            goals.append(
                "Zaman takvimi uyumunu %90+ çık — "
                "tüm deadline'lı görevler için günü başında takvim set et"
            )
        else:
            goals.append("Zaman takvimi uyumunu %92+ sabit tut — standartını koru")

        # Focus time goal
        if metrics.meeting_hours > 4:
            goals.append(
                "Toplantı yükünü azalt — "
                "en az 2 saat yoğunlaşma bloğu güvenlik altına al"
            )
        else:
            goals.append("Odaklanma zamanını maksimum kullan — kesintisiz çalış")

        # Email response goal
        if metrics.email_response_time_hours > 2:
            goals.append(
                "Email cevap süresini kısalt — "
                "gün içinde 3 kez e-postayı kontrol et (09:00, 13:00, 17:00)"
            )

        return goals

    @staticmethod
    def _generate_daily_task(metrics: DailyMetrics) -> str:
        """Generate the daily task in Turkish."""
        if metrics.deadline_adherence >= 90:
            return (
                "Günü %92+ deadline adherence ile bitir — "
                "hiç bir tarih uzatması kabul etme."
            )
        elif metrics.completion_rate >= 85:
            return (
                "En az 3 yüksek öncelikli görevi tamamla ve "
                "tüm deadline'ları kontrol et."
            )
        else:
            return (
                "Sabah plan yap, tamamlanma oranını %75+ çık ve "
                "her cevap verilecek e-postaya 4 saat içinde yanıt ver."
            )


# --- Helpers ----


def _format_trend(diff: float, up_fmt: str, down_fmt: str, stable_fmt: str) -> str:
    """Format trend indicator based on difference."""
    threshold = 0.5
    if abs(diff) < threshold:
        return stable_fmt
    elif diff > 0:
        return up_fmt.format(diff)
    else:
        return down_fmt.format(abs(diff))
