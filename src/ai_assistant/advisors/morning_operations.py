"""Morning Operations Advisor — Sabah İşletme Brifingi.

Consolidated morning briefing + daily operations advisor.

This advisor provides a complete operational overview for day start by merging:
  1. **Morning Briefing**: Yesterday's performance metrics and trends
  2. **Daily Operations**: Today's priorities, critical items, and focus areas
  3. **Strategic Planning**: Daily goals and focus area recommendations
  4. **Task Prioritization**: Turkish daily task assignment

Tracks and provides:
  - Performance completion rate (% of tasks completed)
  - Deadline adherence (% of deadlines met on time)
  - Success rate (% of successful operations)
  - Operational trends (↑ ↓ →) vs yesterday
  - Priority tasks for today (from calendar & task tracking)
  - Critical path items (dependencies, blockers)
  - Focus area recommendations (where to invest time)
  - Daily goals (smart, achievable targets)
  - Daily Turkish task (Günü X ile bitir)

Data sources:
  - Previous day's status.json (performance metrics)
  - Today's calendar (events, focus blocks)
  - Task tracking data (priorities, deadlines)
  - Performance history (trends vs yesterday/week/month)

The advisor produces a rich Turkish briefing with:
  - Operational headline ("Öne çıkan")
  - Yesterday's performance summary
  - Today's priority operations
  - Critical path analysis
  - Focus recommendations
  - Daily goals (3-5 actionable targets)
  - Daily task ("Günün görevi")
  - Resources and next steps

Configuration (via environment):
    MORNING_OPS_STATE_FILE    Where metrics state lives (default:
                              `.assistant_state/morning_ops.json`)
    MORNING_OPS_HISTORY_DAYS  Days to keep in history (default: 30)

LLM-backed: uses Gemini or OpenAI to generate contextual briefing.
With no provider key the advisor is ``skipped``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from . import Advisor, Briefing
from ..config import setting
from ..integrations import STATUS_OK
from ._llm_base import LLMAdvisor, RICH_BRIEFING_GUIDE

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_STATE_FILE = ".assistant_state/morning_ops.json"
DEFAULT_HISTORY_DAYS = 30

# System prompt for LLM
SYSTEM_PROMPT = (
    "Sen bir sabah operasyonel danışmanısın. Dün neler oldu, bugün ne yapmalı, "
    "hangi kritik yollar var ve nereye odaklanmalıyız sorularına yanıt veriyorsun. "
    "Türkçe konuşuyorsun. Görevin, yoğun bir yöneticiye her sabah:\n"
    "- Dünün performansını (metrikleri, trendleri)\n"
    "- Bugünün operasyonel önceliklerini\n"
    "- Kritik yolları ve engelleri\n"
    "- Odaklanması gereken alanları\n"
    "- Somut günlük hedefleri\n"
    "- Günün tek en önemli görevini\n"
    "…net, actionable ve stratejik olarak sunmak. "
    "Klişelerden kaçın, sayılar ve gerçekler konuş, pratik ve hızlı oku."
)


@dataclass
class OperationalMetrics:
    """Yesterday's performance metrics."""

    date: str  # ISO format YYYY-MM-DD
    completion_rate: float = 0.0  # Percentage 0-100
    deadline_adherence: float = 0.0  # Percentage 0-100
    success_rate: float = 0.0  # Percentage 0-100
    tasks_completed: int = 0
    tasks_assigned: int = 0
    errors_count: int = 0
    operations_count: int = 0
    meeting_hours: float = 0.0
    focus_time_hours: float = 0.0

    @classmethod
    def from_dict(cls, data: dict) -> "OperationalMetrics":
        """Create from dictionary with graceful defaults."""
        return cls(
            date=str(data.get("date", "")),
            completion_rate=float(data.get("completion_rate") or 0.0),
            deadline_adherence=float(data.get("deadline_adherence") or 0.0),
            success_rate=float(data.get("success_rate") or 0.0),
            tasks_completed=int(data.get("tasks_completed") or 0),
            tasks_assigned=int(data.get("tasks_assigned") or 0),
            errors_count=int(data.get("errors_count") or 0),
            operations_count=int(data.get("operations_count") or 0),
            meeting_hours=float(data.get("meeting_hours") or 0.0),
            focus_time_hours=float(data.get("focus_time_hours") or 0.0),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class OperationalPriority:
    """One priority task for today."""

    title: str
    priority: str  # high, medium, low
    deadline: Optional[str] = None  # ISO time if applicable
    blockers: List[str] = field(default_factory=list)
    owner: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CriticalPathItem:
    """Critical item on the path to completion."""

    item: str
    status: str  # blocked, in-progress, at-risk
    dependency: Optional[str] = None
    risk_level: str = "medium"  # low, medium, high

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OperationsBriefingReport:
    """Complete morning operations briefing report."""

    generated_at: str  # ISO format timestamp
    date: str  # ISO format YYYY-MM-DD
    summary: str  # Turkish summary headline
    performance: Dict[str, Any] = field(default_factory=dict)
    daily_operations: Dict[str, Any] = field(default_factory=dict)
    goals_for_today: List[str] = field(default_factory=list)
    daily_task: str = ""  # Turkish daily task
    focus_areas: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "generated_at": self.generated_at,
            "date": self.date,
            "summary": self.summary,
            "performance": self.performance,
            "daily_operations": self.daily_operations,
            "goals_for_today": self.goals_for_today,
            "daily_task": self.daily_task,
            "focus_areas": self.focus_areas,
            "next_steps": self.next_steps,
        }

    def as_json(self) -> str:
        """Format as JSON briefing."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def as_text(self) -> str:
        """Format as readable briefing text for Slack."""
        lines: List[str] = []

        # Header with summary
        lines.append("*Sabah İşletme Brifingi*")
        lines.append(f"📊 **Öne çıkan:** {self.summary}")
        lines.append("")

        # Yesterday's performance section
        if self.performance:
            lines.append("*📈 Dünün Performansı*")
            perf = self.performance
            if "completion_rate" in perf:
                lines.append(f"- Tamamlanma Oranı: {perf['completion_rate']:.1f}%")
            if "deadline_adherence" in perf:
                lines.append(
                    f"- Zaman Takvimi Uyumu: {perf['deadline_adherence']:.1f}%"
                )
            if "success_rate" in perf:
                lines.append(f"- Başarı Oranı: {perf['success_rate']:.1f}%")
            if "trends" in perf:
                lines.append(f"- Trendler: {perf['trends']}")
            lines.append("")

        # Daily operations section
        if self.daily_operations:
            lines.append("*⚙️ Bugünün Operasyonel Öncelikleri*")
            ops = self.daily_operations

            if "priority_tasks" in ops and ops["priority_tasks"]:
                lines.append("*Öncelikli Görevler:*")
                for task in ops["priority_tasks"][:5]:
                    if isinstance(task, str):
                        lines.append(f"- {task}")
                    else:
                        lines.append(f"- {task.get('title', 'Görev')}")
                lines.append("")

            if "critical_items" in ops and ops["critical_items"]:
                lines.append("*Kritik Yol Öğeleri:*")
                for item in ops["critical_items"][:5]:
                    if isinstance(item, str):
                        lines.append(f"- {item}")
                    else:
                        status = item.get("status", "")
                        text = item.get("item", "Öğe")
                        if status:
                            lines.append(f"- {text} ({status})")
                        else:
                            lines.append(f"- {text}")
                lines.append("")

        # Focus areas
        if self.focus_areas:
            lines.append("*🎯 Odaklanma Alanları*")
            for area in self.focus_areas:
                lines.append(f"- {area}")
            lines.append("")

        # Goals section
        if self.goals_for_today:
            lines.append("*🎯 Bugünün Hedefleri*")
            for i, goal in enumerate(self.goals_for_today, 1):
                lines.append(f"{i}. {goal}")
            lines.append("")

        # Daily task
        lines.append("*✅ Bugünün görevi*")
        if self.daily_task:
            lines.append(self.daily_task)
        else:
            lines.append("Günü başarıyla bitir.")
        lines.append("")

        # Next steps
        if self.next_steps:
            lines.append("*→ Sonraki Adımlar*")
            for step in self.next_steps[:3]:
                lines.append(f"- {step}")

        return "\n".join(lines)


class MorningOperationsStateManager:
    """State management for historical metrics and calculations."""

    def __init__(self) -> None:
        self._state_file = setting("MORNING_OPS_STATE_FILE") or DEFAULT_STATE_FILE
        self._history_days = self._get_history_days()
        self._history: Dict[str, OperationalMetrics] = {}
        self._load_history()

    def _get_history_days(self) -> int:
        """Load history retention period from config."""
        try:
            days = int(os.getenv("MORNING_OPS_HISTORY_DAYS") or DEFAULT_HISTORY_DAYS)
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
                        self._history[iso_date] = OperationalMetrics.from_dict(
                            {"date": iso_date, **metrics_dict}
                        )
                    except Exception as e:
                        logger.debug(f"Skipping corrupt entry {iso_date}: {e}")
                        continue
        except Exception as e:
            logger.debug(f"Could not load history: {e}")

    def save_today_metrics(self, metrics: OperationalMetrics) -> None:
        """Save today's metrics to state file."""
        if not self._state_file:
            return

        self._history[metrics.date] = metrics
        self._cleanup_old_records()

        try:
            directory = os.path.dirname(self._state_file)
            if directory:
                os.makedirs(directory, exist_ok=True)

            data_to_save = {
                date_str: metrics.to_dict()
                for date_str, metrics in self._history.items()
            }

            with open(self._state_file, "w", encoding="utf-8") as fh:
                json.dump(data_to_save, fh, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"Could not save state: {e}")

    def _cleanup_old_records(self) -> None:
        """Keep only the last N days of history."""
        cutoff = (date.today() - timedelta(days=self._history_days)).isoformat()
        old_keys = [k for k in self._history if k < cutoff]
        for key in old_keys:
            self._history.pop(key, None)

    def get_yesterday_metrics(self) -> Optional[OperationalMetrics]:
        """Get metrics for yesterday."""
        yesterday_str = (date.today() - timedelta(days=1)).isoformat()
        return self._history.get(yesterday_str)

    def get_week_average(self) -> Optional[OperationalMetrics]:
        """Calculate average metrics for the past 7 days."""
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        recent = [m for m in self._history.values() if m.date >= cutoff]

        if len(recent) < 2:
            return None

        return self._average_metrics(recent)

    @staticmethod
    def _average_metrics(metrics_list: List[OperationalMetrics]) -> OperationalMetrics:
        """Calculate average of multiple metric records."""
        if not metrics_list:
            return OperationalMetrics(date=date.today().isoformat())

        avg = OperationalMetrics(date=date.today().isoformat())
        count = len(metrics_list)

        avg.completion_rate = sum(m.completion_rate for m in metrics_list) / count
        avg.deadline_adherence = sum(m.deadline_adherence for m in metrics_list) / count
        avg.success_rate = sum(m.success_rate for m in metrics_list) / count
        avg.meeting_hours = sum(m.meeting_hours for m in metrics_list) / count
        avg.focus_time_hours = sum(m.focus_time_hours for m in metrics_list) / count
        avg.tasks_completed = int(sum(m.tasks_completed for m in metrics_list) / count)
        avg.tasks_assigned = int(sum(m.tasks_assigned for m in metrics_list) / count)

        return avg


class MorningOperationsAdvisor(LLMAdvisor):
    """Morning Operations Advisor — consolidated briefing + daily ops planning.

    This advisor merges:
    1. Morning Briefing: Yesterday's performance metrics and trends
    2. Daily Operations: Today's priorities, critical items, and focus areas
    3. Strategic Planning: Daily goals and recommendations

    It provides a complete operational overview for day start, integrating:
    - Performance metrics (completion, deadlines, success rate)
    - Operational trends (↑ ↓ →) vs yesterday/week
    - Priority tasks for today
    - Critical path items and dependencies
    - Focus area recommendations
    - Smart daily goals
    - Turkish daily task assignment

    Produces a rich briefing combining metrics data + LLM-generated insights.
    """

    key = "morning_operations"
    title = "Sabah İşletme Brifingi"
    system_prompt = SYSTEM_PROMPT

    def __init__(self) -> None:
        super().__init__()
        self._state_manager = MorningOperationsStateManager()
        self._yesterday_metrics: Optional[OperationalMetrics] = None
        self._week_avg: Optional[OperationalMetrics] = None

    @property
    def user_prompt(self) -> str:
        """Build user prompt from yesterday's data and today's context."""
        # Load historical metrics
        self._yesterday_metrics = self._state_manager.get_yesterday_metrics()
        self._week_avg = self._state_manager.get_week_average()

        # Build context
        context = self._build_context()

        # Create user prompt
        user_prompt = (
            "Aşağı da bugünün operasyonel brifingi için gerekli veri ve bağlam verilmiştir. "
            "Buna dayanarak, dünün performansını özetleyen, bugünün operasyonel "
            "önceliklerini ve kritik yolları açıklayan, hangi alanlara odaklanması gerektiğini "
            "söyleyen, akıllı günlük hedefleri ve Türkçe günlük görevi sunan "
            "derinlikli bir sabah brifingi yaz:\n\n"
            f"{context}\n\n" + RICH_BRIEFING_GUIDE
        )

        return user_prompt

    def _generate(self) -> Briefing:
        """Generate the morning operations briefing using LLM."""
        if not self._has_data():
            return self.skipped(
                "operasyonel veriler henüz mevcut değil; "
                "danışmanlar çalıştıktan sonra veriler toplanacak"
            )

        try:
            text = self._generate_via_llm()
        except Exception as exc:
            return self.failed(f"Operasyonel brifing oluşturulamadı: {exc}")

        return self.ok(text)

    def _has_data(self) -> bool:
        """Check if we have enough data to generate briefing."""
        # We can generate even with minimal data
        yesterday = self._state_manager.get_yesterday_metrics()
        return yesterday is not None and (
            yesterday.tasks_assigned > 0 or yesterday.operations_count > 0
        )

    def _generate_via_llm(self) -> str:
        """Generate briefing using LLM."""
        from ..integrations import llm

        if not llm.is_configured():
            return self._generate_deterministic_briefing()

        text = llm.generate_text(self.system_prompt, self.user_prompt)
        return text.strip()

    def _generate_deterministic_briefing(self) -> str:
        """Generate briefing deterministically if LLM unavailable."""
        report = self._build_report()
        return report.as_text()

    def _build_context(self) -> str:
        """Build context from yesterday's data and today's calendar."""
        lines: List[str] = []

        # Yesterday's metrics
        if self._yesterday_metrics:
            lines.append("DÜNÜN PERFORMANSI:")
            lines.append(
                f"- Tamamlanma Oranı: %{self._yesterday_metrics.completion_rate:.1f}"
            )
            lines.append(
                f"- Zaman Takvimi Uyumu: %{self._yesterday_metrics.deadline_adherence:.1f}"
            )
            lines.append(f"- Başarı Oranı: %{self._yesterday_metrics.success_rate:.1f}")
            lines.append(
                f"- Tamamlanan Görevler: {self._yesterday_metrics.tasks_completed}/{self._yesterday_metrics.tasks_assigned}"
            )
            lines.append(
                f"- Toplantı Saatleri: {self._yesterday_metrics.meeting_hours:.1f}sa"
            )
            lines.append(
                f"- Yoğunlaşma Saati: {self._yesterday_metrics.focus_time_hours:.1f}sa"
            )

            # Calculate trends
            if self._week_avg:
                completion_trend = (
                    self._yesterday_metrics.completion_rate
                    - self._week_avg.completion_rate
                )
                deadline_trend = (
                    self._yesterday_metrics.deadline_adherence
                    - self._week_avg.deadline_adherence
                )
                success_trend = (
                    self._yesterday_metrics.success_rate - self._week_avg.success_rate
                )

                lines.append("\nTRENDLER (7 gün ortalamasına kıyasla):")
                lines.append(f"- Tamamlanma: {self._format_trend(completion_trend)}")
                lines.append(f"- Zaman Takvimi: {self._format_trend(deadline_trend)}")
                lines.append(f"- Başarı: {self._format_trend(success_trend)}")

        # Today's priorities
        priorities = self._extract_priorities()
        if priorities:
            lines.append("\nBUGÜNÜN OPERASYONEL ÖNCELİKLERİ:")
            for priority in priorities[:5]:
                if isinstance(priority, str):
                    lines.append(f"- {priority}")
                else:
                    lines.append(
                        f"- {priority.get('title', 'Görev')} ({priority.get('priority', 'normal')})"
                    )

        # Critical items
        critical = self._extract_critical_items()
        if critical:
            lines.append("\nKRİTİK YOL ÖĞELERİ:")
            for item in critical[:5]:
                if isinstance(item, str):
                    lines.append(f"- {item}")
                else:
                    lines.append(
                        f"- {item.get('item', 'Öğe')} ({item.get('status', 'takip')})"
                    )

        return "\n".join(lines)

    def _extract_priorities(self) -> List[Dict[str, Any]]:
        """Extract priority tasks from available data."""
        priorities: List[Dict[str, Any]] = []

        # Try to load from status.json
        try:
            status_file = ".assistant_state/status.json"
            if os.path.exists(status_file):
                with open(status_file, "r", encoding="utf-8") as fh:
                    status_data = json.load(fh)
                    if "priorities" in status_data:
                        priorities = status_data["priorities"]
                    elif "tasks" in status_data:
                        tasks = status_data["tasks"]
                        if isinstance(tasks, list):
                            priorities = tasks[:5]
        except Exception as e:
            logger.debug(f"Could not load priorities: {e}")

        if not priorities:
            # Default priorities
            priorities = [
                "E-postalar ve mesajları kontrol et",
                "Takvimi gözden geçir ve günü planla",
                "En zor/en önemli görevi başlat",
                "Toplantılara katıl ve notlar al",
                "Ilerlemeli durum güncellemeleri yap",
            ]

        return priorities

    def _extract_critical_items(self) -> List[Dict[str, Any]]:
        """Extract critical path items from available data."""
        items: List[Dict[str, Any]] = []

        try:
            status_file = ".assistant_state/status.json"
            if os.path.exists(status_file):
                with open(status_file, "r", encoding="utf-8") as fh:
                    status_data = json.load(fh)
                    if "critical_path" in status_data:
                        items = status_data["critical_path"]
                    elif "blockers" in status_data:
                        blockers = status_data["blockers"]
                        if isinstance(blockers, list):
                            items = blockers
        except Exception as e:
            logger.debug(f"Could not load critical items: {e}")

        if not items:
            # Default critical items
            items = [
                {"item": "Ana proje hedeflerini doğrula", "status": "in-progress"},
                {"item": "Bağımlı görevleri kontrol et", "status": "at-risk"},
                {"item": "Engelleri ortadan kaldır", "status": "blocked"},
            ]

        return items

    def _build_report(self) -> OperationsBriefingReport:
        """Build the operational briefing report."""
        yesterday = (
            self._yesterday_metrics or self._state_manager.get_yesterday_metrics()
        )
        week_avg = self._week_avg or self._state_manager.get_week_average()

        today_str = date.today().isoformat()

        # Build performance data
        performance: Dict[str, Any] = {}
        if yesterday:
            performance = {
                "completion_rate": round(yesterday.completion_rate, 1),
                "deadline_adherence": round(yesterday.deadline_adherence, 1),
                "success_rate": round(yesterday.success_rate, 1),
                "tasks_completed": yesterday.tasks_completed,
                "tasks_assigned": yesterday.tasks_assigned,
            }

            if week_avg:
                performance["trends"] = (
                    f"vs 7 gün ortalaması: "
                    f"Tamamlanma {self._format_trend(yesterday.completion_rate - week_avg.completion_rate)}, "
                    f"Zaman Takvimi {self._format_trend(yesterday.deadline_adherence - week_avg.deadline_adherence)}"
                )

        # Extract daily operations
        priority_tasks = self._extract_priorities()
        critical_items = self._extract_critical_items()

        daily_ops = {
            "priority_tasks": priority_tasks[:5],
            "critical_items": critical_items[:5],
            "focus_areas": [
                "Yüksek etkili görevlere sabah erken saatini ayır",
                "Kesintisiz iş blokları oluştur (en az 90 dakika)",
                "Zor kararları öğleden sonraya sakla",
            ],
        }

        # Generate goals
        goals = self._generate_smart_goals(yesterday, week_avg)

        # Generate daily task
        daily_task = self._generate_daily_task(yesterday)

        # Build report
        report = OperationsBriefingReport(
            generated_at=datetime.now().isoformat(),
            date=today_str,
            summary=self._generate_summary(yesterday),
            performance=performance,
            daily_operations=daily_ops,
            goals_for_today=goals,
            daily_task=daily_task,
            focus_areas=daily_ops.get("focus_areas", []),
            next_steps=self._generate_next_steps(yesterday),
        )

        return report

    @staticmethod
    def _format_trend(diff: float) -> str:
        """Format trend indicator based on difference."""
        threshold = 0.5
        if abs(diff) < threshold:
            return "→ Sabit"
        elif diff > 0:
            return f"↑ +{diff:.1f}%"
        else:
            return f"↓ -{abs(diff):.1f}%"

    @staticmethod
    def _generate_summary(metrics: Optional[OperationalMetrics]) -> str:
        """Generate Turkish summary of key metrics."""
        if not metrics:
            return "Operasyonel veri henüz yok; bugünü planlama başlat."

        if metrics.completion_rate >= 85 and metrics.deadline_adherence >= 90:
            return (
                f"Güçlü bir gün başlangıcı: tamamlanma %{metrics.completion_rate:.0f}, "
                f"zaman takvimi %{metrics.deadline_adherence:.0f}."
            )
        elif metrics.completion_rate >= 70 and metrics.deadline_adherence >= 80:
            return (
                f"Orta ölçüde performans: tamamlanma %{metrics.completion_rate:.0f}, "
                f"zaman takvimi %{metrics.deadline_adherence:.0f}."
            )
        else:
            return (
                f"Dikkat: tamamlanma %{metrics.completion_rate:.0f}, "
                f"zaman takvimi %{metrics.deadline_adherence:.0f} — odağı netleştir."
            )

    @staticmethod
    def _generate_smart_goals(
        yesterday: Optional[OperationalMetrics],
        week_avg: Optional[OperationalMetrics],
    ) -> List[str]:
        """Generate smart daily goals based on performance."""
        goals: List[str] = []

        if not yesterday:
            return [
                "Günü başında 5 çalışma bloğu planla (her biri 90+ dakika)",
                "Tüm deadline'lı görevleri doğrula ve takvime ekle",
                "Sabah ilk 2 saatini en zor göreve ayır",
                "Öğleden sonra 1 saat odaklanma bloğu güvenlik altına al",
            ]

        # Completion-focused goal
        if yesterday.completion_rate < 80:
            goals.append(
                "Tamamlanma oranını %80+ seviyesine çık — "
                "sabah ilk 2 saatinde en zor 3 görevi bitir"
            )
        else:
            goals.append(
                "Tamamlanma oranını %85+ sabit tut — "
                "dün başlattığın yarım görevleri tamamla"
            )

        # Deadline adherence goal
        if yesterday.deadline_adherence < 90:
            goals.append(
                "Zaman takvimi uyumunu %90+ çık — "
                "tüm deadline'lı görevler için takvim hatırlatması ayarla"
            )
        else:
            goals.append(
                "Zaman takvimi uyumunu %92+ sabit tut — "
                "hiç bir tarih uzatması kabul etme"
            )

        # Focus time goal
        if yesterday.meeting_hours > 4:
            goals.append(
                "Toplantı yükünü azalt — "
                "en az 2 saat kesintisiz çalışma bloğu güvenlik altına al"
            )
        else:
            goals.append(
                "Odaklanma zamanını maksimum kullan — "
                "3 × 90 dakikalık çalışma bloğu planla"
            )

        # Success rate goal
        if yesterday.success_rate < 95:
            goals.append(
                "Başarı oranını %95+ çık — "
                "hataları minimize etmek için kontrol mekanizması ekle"
            )

        return goals[:5]

    @staticmethod
    def _generate_next_steps(metrics: Optional[OperationalMetrics]) -> List[str]:
        """Generate concrete next steps."""
        return [
            "1. Takvimi aç, bugünün toplantılarını ve son tarihlerini gözden geçir",
            "2. En zor 3 görevi tanımla ve çalışma blokları yapılandır",
            "3. Sabah kahvesi sonrası ilk göreve odaklan (kesintisiz 90 dk)",
            "4. Öğlen sonrası durum bilgilerini güncelleştir",
            "5. Akşam son saatinde yarını planla ve notlar al",
        ]

    @staticmethod
    def _generate_daily_task(metrics: Optional[OperationalMetrics]) -> str:
        """Generate the daily task in Turkish."""
        if not metrics:
            return (
                "Günü planlı bir şekilde başlat: takvimi gözden geçir, "
                "en zor görevleri sabaha ayır, her saatte odaklan."
            )

        if metrics.deadline_adherence >= 90:
            return (
                "Günü %92+ deadline adherence ile bitir — "
                "hiç bir tarih uzatması kabul etme."
            )
        elif metrics.completion_rate >= 85:
            return (
                "En az 3 yüksek öncelikli görevi tamamla ve "
                "tüm deadline'ları tuttuğundan emin ol."
            )
        else:
            return (
                "Sabah plan yap, tamamlanma oranını %75+ çık, "
                "kesintisiz 3 × 90 dakikalık çalışma bloğu oluştur."
            )
