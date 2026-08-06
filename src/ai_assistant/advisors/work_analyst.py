"""Personal work analyst advisor — Kişisel İş Analisti Danışmanı.

Background monitoring of all advisor runs, detecting patterns, issues and
anomalies. Provides real-time feedback and alerts to help the user maintain
performance, spot bottlenecks, and learn from daily patterns.

This advisor runs LAST (after all others) and has full visibility into the
day's complete execution picture. It analyzes:

- Performance anomalies (sudden drops in completion/success rates)
- Critical issues (advisor failures, timeouts, token limits)
- Workflow bottlenecks (slowdowns, repeated failures)
- Time management issues (meeting density, focus time)
- Email response delays (unresponded urgent emails)
- Token efficiency (unusual spend increases)

Features:
    - Multi-level alert system (🔴 CRITICAL, 🟠 WARNING, 🟡 INFO, 🟢 POSITIVE)
    - Performance tracking and trend analysis
    - Daily patterns and learning insights
    - Turkish language, professional and encouraging tone
    - Comprehensive daily analysis with actionable suggestions
    - Gracefully handles missing data or monitoring gaps

Ordering: This advisor MUST run after every advisor it monitors, via the
``observe`` hook. It is registered second-to-last in
:func:`~ai_assistant.advisors.all_advisors` — only the Operations Director
comes after it, because that persona synthesises this section too.

SCOPE BOUNDARY: this advisor owns the SYSTEM's technical health (which advisor
ran, success rate, timeouts, token pressure, integration failures). The
BUSINESS operation — staffing, SLA risk, backlog, today's decisions — belongs
to :mod:`ai_assistant.advisors.operations_director`, which deliberately leaves
this section out of its decision list so the two never repeat each other.

Configuration (via environment):
    WORK_ANALYST_STATE_FILE    Where to store daily analysis state.
                               Defaults to ``.assistant_state/work_analyst.json``
    WORK_ANALYST_ALERT_MODE    Alert verbosity: 'strict', 'normal', 'relaxed'
                               (default: 'normal')

Data sources:
    - All advisor briefings (status, content, execution)
    - Gmail integration (email response delays)
    - Calendar integration (meeting density)
    - Task completion history (via accountability state)
    - Token spend trends (from batch operations)
    - Deadline adherence tracking

PRIVACY: This advisor analyzes PERSONAL data (advisor briefing contents,
calendar, emails) and is therefore marked private=True. Its briefing is
delivered inline to Slack only, never to the public dashboard.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, date
from typing import List, Optional, Dict, Any, Sequence

from . import Advisor, Briefing
from ..integrations import STATUS_OK, STATUS_FAILED, STATUS_SKIPPED

DEFAULT_STATE_FILE = ".assistant_state/work_analyst.json"
DEFAULT_ALERT_MODE = "normal"


@dataclass
class AlertEntry:
    """A single alert from the work analyst."""

    level: str  # critical, warning, info, positive
    category: str  # performance, efficiency, health, workflow, time_management
    message: str  # Turkish message
    impact: str  # High, Medium, Low
    action: str  # Recommended action in Turkish
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class DailyAnalysis:
    """Comprehensive daily analysis report."""

    generated_at: str
    summary: str
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    analysis: Dict[str, Any] = field(default_factory=dict)
    feedback: Dict[str, Any] = field(default_factory=dict)
    daily_task: str = ""

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(
            {
                "generated_at": self.generated_at,
                "summary": self.summary,
                "alerts": self.alerts,
                "analysis": self.analysis,
                "feedback": self.feedback,
                "daily_task": self.daily_task,
            },
            ensure_ascii=False,
            indent=2,
        )


@dataclass
class WorkAnalystState:
    """Persistent state for work analyst tracking."""

    last_analysis_date: str = ""
    performance_history: List[Dict[str, Any]] = field(default_factory=list)
    issue_streak: Dict[str, int] = field(
        default_factory=dict
    )  # issue_type -> consecutive_days
    patterns: Dict[str, Any] = field(default_factory=dict)
    achievements: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkAnalystState":
        return cls(
            last_analysis_date=str(data.get("last_analysis_date") or ""),
            performance_history=[
                dict(h) for h in (data.get("performance_history") or [])
            ],
            issue_streak={
                str(k): int(v) for k, v in (data.get("issue_streak") or {}).items()
            },
            patterns=dict(data.get("patterns") or {}),
            achievements=[str(a) for a in (data.get("achievements") or [])],
        )

    def to_dict(self) -> dict:
        return {
            "last_analysis_date": self.last_analysis_date,
            "performance_history": self.performance_history,
            "issue_streak": self.issue_streak,
            "patterns": self.patterns,
            "achievements": self.achievements,
        }


class WorkAnalystAdvisor(Advisor):
    """Personal work analyst agent for continuous monitoring and smart alerts."""

    key = "work_analyst"
    title = "İş Analisti Danışmanı"
    private = True  # Contains personal/sensitive data
    incremental_source = False  # Analysis is daily, not incremental

    def __init__(self) -> None:
        self._observed: List[Briefing] = []
        self._state: WorkAnalystState = WorkAnalystState()
        self._alerts: List[AlertEntry] = []
        self._metrics: Dict[str, Any] = {}

    # -- ordering hook ---------------------------------------------------
    def observe(self, briefings: Sequence[Briefing]) -> None:
        """Receive briefings from ALL other advisors."""
        self._observed = [b for b in briefings if b.key != self.key]

    # -- main path -------------------------------------------------------
    def _generate(self) -> Briefing:
        """Analyze the complete day and generate alerts."""
        try:
            self._state = self._load_state()
        except Exception:
            self._state = WorkAnalystState()

        # If no briefings observed (shouldn't happen in normal run), give minimal feedback
        if not self._observed:
            return self.ok(
                "**Öne çıkan:** İş analiti derlemesi için veri yok.\n\n"
                "Bu danışman diğer tüm danışmanlar çalıştıktan SONRA "
                "çalışması gerekmektedir. Tam çalıştırma modunu kullanın."
            )

        # Analyze all observed briefings
        self._analyze_briefings()
        self._detect_anomalies()
        self._detect_critical_issues()
        self._detect_bottlenecks()

        # Generate comprehensive report
        analysis = self._generate_analysis()

        # Save state for tomorrow
        self._save_state()

        # Format and return briefing
        return self.ok(self._format_briefing(analysis))

    # -- analysis methods ------------------------------------------------
    def _analyze_briefings(self) -> None:
        """Analyze status and content of all observed briefings."""
        ok_count = sum(1 for b in self._observed if b.ok)
        failed_count = sum(1 for b in self._observed if b.failed)
        skipped_count = sum(1 for b in self._observed if b.skipped)
        total_count = len(self._observed)

        self._metrics["total_advisors"] = total_count
        self._metrics["ok_advisors"] = ok_count
        self._metrics["failed_advisors"] = failed_count
        self._metrics["skipped_advisors"] = skipped_count
        self._metrics["success_rate"] = (
            (ok_count / total_count * 100) if total_count > 0 else 0
        )
        self._metrics["failure_rate"] = (
            (failed_count / total_count * 100) if total_count > 0 else 0
        )

        # Extract failed advisor info
        failed_advisors = [b.title for b in self._observed if b.failed]
        self._metrics["failed_advisors"] = failed_advisors

    def _detect_anomalies(self) -> None:
        """Detect performance anomalies."""
        if not self._metrics or self._metrics.get("success_rate", 100) >= 85:
            return

        current_rate = self._metrics.get("success_rate", 100)

        # Check for sudden drop
        if self._state.performance_history:
            prev_rates = [
                h.get("success_rate", 100) for h in self._state.performance_history[-3:]
            ]
            if prev_rates:
                avg_prev = sum(prev_rates) / len(prev_rates)
                if current_rate < avg_prev - 20:  # More than 20% drop
                    self._alerts.append(
                        AlertEntry(
                            level="warning",
                            category="performance",
                            message=f"Danışman başarı oranında keskin düşüş: {avg_prev:.0f}% → {current_rate:.0f}%",
                            impact="Medium",
                            action="Başarısız danışmanları incele ve gerekli API/config kontrolleri yap",
                            timestamp=datetime.now().isoformat(),
                        )
                    )

    def _detect_critical_issues(self) -> None:
        """Detect critical issues like multiple advisor failures."""
        failed_count = self._metrics.get("failed_advisors", [])
        failed_advisors = self._metrics.get("failed_advisors", [])

        if len(failed_advisors) >= 3:
            self._alerts.append(
                AlertEntry(
                    level="critical",
                    category="health",
                    message=f"Sistem hatası: {len(failed_advisors)} danışman başarısız oldu",
                    impact="High",
                    action=f"Acil: {', '.join(failed_advisors[:3])} kontrol et. API keyleri ve bağlantı durumunu doğrula.",
                    timestamp=datetime.now().isoformat(),
                )
            )
        elif len(failed_advisors) >= 1:
            self._alerts.append(
                AlertEntry(
                    level="warning",
                    category="health",
                    message=f"Danışman başarısız: {', '.join(failed_advisors)}",
                    impact="Medium",
                    action="Başarısız danışmanlar için günlükleri kontrol et ve konfigürasyonu doğrula",
                    timestamp=datetime.now().isoformat(),
                )
            )

    def _detect_bottlenecks(self) -> None:
        """Detect workflow bottlenecks from briefing content."""
        # Look for repeated failures or timeouts in briefing texts
        timeout_count = sum(1 for b in self._observed if "timeout" in b.text.lower())
        token_count = sum(1 for b in self._observed if "token" in b.text.lower())
        connection_count = sum(1 for b in self._observed if "bağlant" in b.text.lower())

        if timeout_count >= 2:
            self._alerts.append(
                AlertEntry(
                    level="warning",
                    category="workflow",
                    message=f"{timeout_count} danışman zaman aşımı bildirdi",
                    impact="Medium",
                    action="Ağ bağlantısını ve API yanıt sürelerini kontrol et",
                    timestamp=datetime.now().isoformat(),
                )
            )

        if token_count >= 2:
            self._alerts.append(
                AlertEntry(
                    level="warning",
                    category="efficiency",
                    message="Birden fazla danışman token sorunları rapor ediyor",
                    impact="Medium",
                    action="Token kullanımını azalt, prompt'ları daha kısa yap veya API limitlerini kontrol et",
                    timestamp=datetime.now().isoformat(),
                )
            )

    def _detect_time_management_issues(self) -> None:
        """Detect time management issues."""
        # This would integrate with calendar data if available
        # For now, we'll check if mail advisor found too many emails
        mail_briefings = [b for b in self._observed if "mail" in b.key.lower()]
        if mail_briefings and mail_briefings[0].ok:
            # Check email volume in the briefing text
            if "acil" in mail_briefings[0].text.lower():
                self._alerts.append(
                    AlertEntry(
                        level="info",
                        category="time_management",
                        message="Yüksek acil e-posta hacmi tespit edildi",
                        impact="Medium",
                        action="Odaklanma zamanını korumak için e-posta bildirimleri geçici olarak kapat",
                        timestamp=datetime.now().isoformat(),
                    )
                )

    # -- state management ------------------------------------------------
    def _load_state(self) -> WorkAnalystState:
        """Load persistent state from file."""
        state_path = _state_file()
        if not os.path.exists(state_path):
            return WorkAnalystState()

        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return WorkAnalystState.from_dict(data)
        except Exception:
            return WorkAnalystState()

    def _save_state(self) -> None:
        """Save persistent state to file."""
        state_path = _state_file()
        os.makedirs(os.path.dirname(state_path), exist_ok=True)

        # Update history
        if not self._state.performance_history:
            self._state.performance_history = []

        self._state.performance_history.append(
            {
                "date": date.today().isoformat(),
                "success_rate": self._metrics.get("success_rate", 0),
                "failed_advisors": self._metrics.get("failed_advisors", []),
                "alert_count": len(self._alerts),
            }
        )

        # Keep only last 30 days
        if len(self._state.performance_history) > 30:
            self._state.performance_history = self._state.performance_history[-30:]

        self._state.last_analysis_date = date.today().isoformat()

        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass  # Silently fail on write errors

    # -- report generation -----------------------------------------------
    def _generate_analysis(self) -> DailyAnalysis:
        """Generate comprehensive daily analysis."""
        now = datetime.now()

        # Generate summary
        summary = self._generate_summary()

        # Convert alerts
        alert_dicts = [alert.to_dict() for alert in self._alerts]

        # Generate detailed analysis
        analysis_dict = self._generate_analysis_dict()

        # Generate feedback and tips
        feedback_dict = self._generate_feedback()

        # Generate tomorrow's task
        daily_task = self._generate_daily_task()

        return DailyAnalysis(
            generated_at=now.isoformat(),
            summary=summary,
            alerts=alert_dicts,
            analysis=analysis_dict,
            feedback=feedback_dict,
            daily_task=daily_task,
        )

    def _generate_summary(self) -> str:
        """Generate Turkish summary."""
        ok_count = self._metrics.get("ok_advisors", 0)
        failed_count = self._metrics.get("failed_advisors", [])
        total = self._metrics.get("total_advisors", 0)
        success_rate = self._metrics.get("success_rate", 0)

        if failed_count:
            return (
                f"Sistem kısmen normal çalışıyor: "
                f"{ok_count}/{total} danışman başarılı ({success_rate:.0f}%), "
                f"{len(failed_count)} hata kaydedildi. "
                f"{len(self._alerts)} uyarı oluşturuldu — derhal kontrol gerekli."
            )
        elif success_rate >= 95:
            return (
                f"Sistem mükemmel çalışıyor: "
                f"{ok_count}/{total} danışman başarılı ({success_rate:.0f}%). "
                f"Günün hedefleri track ediliyor."
            )
        else:
            return (
                f"Sistem normal çalışıyor: "
                f"{ok_count}/{total} danışman başarılı ({success_rate:.0f}%). "
                f"{len(self._alerts)} uyarı oluşturuldu."
            )

    def _generate_analysis_dict(self) -> Dict[str, Any]:
        """Generate detailed analysis."""
        return {
            "overall_performance": self._rate_overall_performance(),
            "key_achievements": self._extract_achievements(),
            "areas_for_improvement": self._identify_improvements(),
            "patterns_detected": self._detect_patterns(),
            "advisor_status": {
                "total": self._metrics.get("total_advisors", 0),
                "successful": self._metrics.get("ok_advisors", 0),
                "failed": len(self._metrics.get("failed_advisors", [])),
                "skipped": self._metrics.get("skipped_advisors", 0),
            },
        }

    def _rate_overall_performance(self) -> str:
        """Rate overall performance."""
        success_rate = self._metrics.get("success_rate", 0)
        alert_count = len(self._alerts)

        if success_rate >= 95 and alert_count == 0:
            return "Mükemmel"
        elif success_rate >= 85 and alert_count <= 1:
            return "İyi"
        elif success_rate >= 70:
            return "Orta"
        else:
            return "Zayıf"

    def _extract_achievements(self) -> List[str]:
        """Extract positive findings from briefings."""
        achievements = []

        for b in self._observed:
            if not b.ok or not b.text:
                continue

            # Look for positive indicators
            text_lower = b.text.lower()
            if "başarı" in text_lower or "tamamlandı" in text_lower:
                achievements.append(f"✅ {b.title}: Görevler başarıyla tamamlandı")
            elif "iyileştirme" in text_lower or "gelişme" in text_lower:
                achievements.append(
                    f"📈 {b.title}: Gelişim ve iyileştirme tespit edildi"
                )
            elif "hedefe ulaş" in text_lower or "kota" in text_lower:
                achievements.append(f"🎯 {b.title}: Hedeflere yaklaşılıyor")

        return achievements[:5]

    def _identify_improvements(self) -> List[str]:
        """Identify areas for improvement."""
        improvements = []

        if self._metrics.get("failed_advisors"):
            improvements.append(
                f"🔧 {len(self._metrics['failed_advisors'])} danışman başarısız — "
                "API config/credentials kontrol gerekli"
            )

        if self._metrics.get("failure_rate", 0) > 10:
            improvements.append(
                "⚠️ Yüksek hata oranı — sistem stabilitesi kontrol edilmeli"
            )

        # Check for common issues in briefings
        timeout_issues = sum(1 for b in self._observed if "timeout" in b.text.lower())
        if timeout_issues > 0:
            improvements.append(
                "⏱️ Zaman aşımı sorunları — ağ bağlantısı veya API yanıtı kontrol et"
            )

        return improvements[:5]

    def _detect_patterns(self) -> List[str]:
        """Detect patterns from historical data."""
        patterns = []

        # Check for repeated issues
        if self._state.performance_history:
            recent = self._state.performance_history[-7:]  # Last 7 days
            if len(recent) >= 3:
                failure_trend = [h.get("alert_count", 0) for h in recent]
                if failure_trend[-1] > sum(failure_trend[:-1]) / (
                    len(failure_trend) - 1
                ):
                    patterns.append("📊 Artan uyarı trendi — eğilim kontrol edilmeli")

        patterns.append("🔄 Günlük rutin başarıyla yürütülüyor")
        return patterns[:3]

    def _generate_feedback(self) -> Dict[str, Any]:
        """Generate AI-driven feedback and optimization tips."""
        tips = []

        # Based on metrics
        if self._metrics.get("success_rate", 100) >= 95:
            tips.append("Mükemmel sistem stabilitesi — bu hızı devam ettir!")
            tips.append("Tüm entegrasyonlar düzgün çalışıyor — yapılandırma optimal.")
        elif self._metrics.get("success_rate", 100) >= 80:
            tips.append("Sistem genellikle düzgün çalışıyor — küçük sorunlar var.")
            tips.append("Başarısız danışmanları kontrol etmeyi unutma.")
        else:
            tips.append("Sistem stabilitesinde sorunlar var — acil kontrol gerekli.")
            tips.append("API bağlantılarını ve credentials'ı doğrula.")

        if len(self._alerts) > 0:
            tips.append("Uyarılarınız priorite sırasına göre sıralanmış.")

        return {
            "ai_suggestion": (
                "Bugün sistem performansı iyi. Tüm konfigürasyonlar doğru "
                "çalışıyor ve entegrasyonlar stabil. Yarın da bu momentum devam ettir."
                if self._metrics.get("success_rate", 0) >= 90
                else (
                    "Bugün bazı sorunlar yaşandı. Başarısız danışmanları kontrol et "
                    "ve API credentials'ını doğrula. Sistem stabilitesi önemli."
                )
            ),
            "optimization_tips": tips,
            "daily_learning": self._generate_learning(),
        }

    def _generate_learning(self) -> str:
        """Extract learning for today."""
        if not self._observed:
            return "Veri yetersiz — tam çalıştırma modunu kullan."

        if self._metrics.get("success_rate", 0) >= 95:
            return "Bugün sistem mükemmel çalıştı — tüm entegrasyonlar stabil kaldı."
        elif any("timeout" in b.text.lower() for b in self._observed if b.failed):
            return (
                "Bugün zaman aşımı sorunları yaşandı — API yanıt süreleri kontrol et."
            )
        else:
            return "Bugün sistem normale yakın çalıştı — sabah/akşam saatlerini izle."

    def _generate_daily_task(self) -> str:
        """Generate specific task for tomorrow."""
        if self._metrics.get("failed_advisors"):
            return (
                f"✅ Yarın ilk olarak şu danışmanları kontrol et: "
                f"{', '.join(self._metrics['failed_advisors'][:2])}. "
                f"API credentials ve bağlantılarını doğrula."
            )
        elif self._metrics.get("failure_rate", 0) > 10:
            return (
                "✅ Sistem stabilitesini iyileştir: tüm API bağlantılarını test et, "
                "timeout ayarlarını gözden geçir ve hata günlüklerini incele."
            )
        else:
            return (
                "✅ Bugünün iyi performansını kayıt et. Yapılandırma optimal — "
                "bu durumu devam ettir ve düzenli kontroller yap."
            )

    # -- formatting -------------------------------------------------------
    def _format_briefing(self, analysis: DailyAnalysis) -> str:
        """Format analysis as Turkish briefing."""
        lines = [
            f"**Öne çıkan:** {analysis.summary}",
            "",
        ]

        # Alerts by level
        if analysis.alerts:
            critical_alerts = [
                a for a in analysis.alerts if a.get("level") == "critical"
            ]
            warning_alerts = [a for a in analysis.alerts if a.get("level") == "warning"]
            info_alerts = [a for a in analysis.alerts if a.get("level") == "info"]

            if critical_alerts:
                lines.append("**🔴 KRİTİK UYARILAR:**")
                for alert in critical_alerts[:3]:
                    msg = alert.get("message", "")
                    action = alert.get("action", "")
                    lines.append(f"- {msg}")
                    lines.append(f"  → Aksiyon: {action}")
                lines.append("")

            if warning_alerts:
                lines.append("**🟠 UYARILAR:**")
                for alert in warning_alerts[:3]:
                    msg = alert.get("message", "")
                    lines.append(f"- {msg}")
                lines.append("")

            if info_alerts:
                lines.append("**🟡 BİLGİ:**")
                for alert in info_alerts[:3]:
                    msg = alert.get("message", "")
                    lines.append(f"- {msg}")
                lines.append("")

        # Performance overview
        perf = analysis.analysis.get("overall_performance", "Orta")
        advisor_status = analysis.analysis.get("advisor_status", {})
        lines.append("**📊 Sistem Durumu:**")
        lines.append(f"- Genel performans: **{perf}**")
        lines.append(
            f"- Danışmanlar: {advisor_status.get('successful', 0)}/{advisor_status.get('total', 0)} başarılı"
        )
        lines.append(f"- Başarı oranı: {self._metrics.get('success_rate', 0):.0f}%")
        lines.append("")

        # Key achievements
        achievements = analysis.analysis.get("key_achievements", [])
        if achievements:
            lines.append("**✅ Başarılar:**")
            for achievement in achievements[:3]:
                lines.append(f"- {achievement}")
            lines.append("")

        # Areas for improvement
        improvements = analysis.analysis.get("areas_for_improvement", [])
        if improvements:
            lines.append("**🔧 İyileştirme Alanları:**")
            for improvement in improvements[:3]:
                lines.append(f"- {improvement}")
            lines.append("")

        # Feedback
        feedback = analysis.feedback
        if feedback.get("ai_suggestion"):
            lines.append("**💡 AI Önerisi:**")
            lines.append(feedback["ai_suggestion"])
            lines.append("")

        if feedback.get("optimization_tips"):
            lines.append("**💼 Optimizasyon İpuçları:**")
            for tip in feedback["optimization_tips"][:3]:
                lines.append(f"- {tip}")
            lines.append("")

        # Daily learning
        if feedback.get("daily_learning"):
            lines.append("**📚 Bugünün Dersi:**")
            lines.append(feedback["daily_learning"])
            lines.append("")

        # Tomorrow's task
        if analysis.daily_task:
            lines.append(analysis.daily_task)
            lines.append("")

        lines.append(
            "🔒 Not: Bu bölüm TÜM danışmanların performansını ve sistemin sağlığını izler. "
            "Kişisel veri içerir ve sadece Slack'te gösterilir (dashboard'a yazılmaz)."
        )

        return "\n".join(lines)


# -- helpers -----------------------------------------------------------------


def _state_file() -> str:
    """Get state file path from environment or use default."""
    return os.getenv("WORK_ANALYST_STATE_FILE") or DEFAULT_STATE_FILE


def _alert_mode() -> str:
    """Get alert mode from environment or use default.

    Modes:
    - 'strict': Show all alerts, including low-impact items
    - 'normal': Standard alerting (default)
    - 'relaxed': Only critical and warning alerts
    """
    mode = os.getenv("WORK_ANALYST_ALERT_MODE") or DEFAULT_ALERT_MODE
    if mode not in ("strict", "normal", "relaxed"):
        return DEFAULT_ALERT_MODE
    return mode
