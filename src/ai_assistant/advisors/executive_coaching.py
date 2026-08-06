"""Executive coaching advisor — Yönetici Gelişim Koçu.

Consolidated leadership coaching + accountability advisor that merges:
- Professional development and leadership growth (from Leadership Coach)
- Commitment tracking and task accountability (from Accountability Coach)

This advisor provides a holistic coaching framework that combines:
1. Leadership development insights and frameworks
2. Accountability for commitments and task completion
3. Progress monitoring and blocker identification
4. Win celebration and personal growth recommendations
5. Coaching feedback and actionable next steps

The advisor produces a structured JSON report that includes:
- Leadership focus areas and development strategy
- Accountability tracking with completion status
- Personalized coaching insights and recommendations
- Daily growth task for continuous improvement

Data sources:
    - Task completion history and performance metrics
    - Historical coaching notes and observations
    - Commitment tracking and progress status
    - Personal achievements and wins
    - Blockers and obstacles encountered

This consolidation creates a unified executive development experience
that addresses both the "who you're becoming" (leadership) and "what
you're committing to" (accountability) dimensions of executive growth.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Any, Sequence

from ._llm_base import LLMAdvisor, RICH_BRIEFING_GUIDE
from . import Briefing
from ..config import setting
from ..integrations import STATUS_OK

# --- System and User Prompts -----------------------------------------------

SYSTEM_PROMPT = (
    "Sen kıdemli bir yönetici koçu ve deneyimli bir liderlik danışmanısın. "
    "Yıllarca C-level yöneticileri, kurucuları ve hızlı yükselen liderləri "
    "geliştirmiş, zorlu iş kararlarında rehberlik etmiş, ekip dinamiklerini "
    "dönüştürmüş birisin. Aynı zamanda başarıyı takip etme ve taahhütlere "
    "bağlılığı sağlama konusunda da uzman ve deneyimlisin.\n\n"
    "Görevin, yoğun çalışan bir yöneticiye her gün derin, gelişimsel ve "
    "actionable bir koçluk briefingi vermektir. Bu brifing iki kritik boyutu "
    "birleştirir:\n"
    "1. KİŞİSEL GELİŞİM: liderlik yetkinlikleri, kendi farkındalığı, "
    "stratejik düşünüş, insanları yönetme sanatı\n"
    "2. HESAP VEREBILIRLIK: taahhütlere bağlılık, görevleri bitirme disiplini, "
    "engelleri aşma kararlılığı, kazanımları kutlama\n\n"
    "Klişelerden kaçın. Somut olun. Uygulanabilir olun. Sıcak ama profesyonel "
    "bir ton kullanın. Her koçluk notu, yöneticinin o gün atması gereken "
    "gerçek bir adımı önerecek şekilde tasarlanmalı."
)

USER_PROMPT = (
    "Bugün için derin ve tamamlayıcı bir yönetici koçluk briefingi hazırla. "
    "Bu brifing iki entegre bölümden oluşmalı:\n\n"
    "## A. KİŞİSEL GELİŞİM (Leadership Development)\n"
    "Bir GERÇEK liderlik teması seç (örneğin: zor konuşmalar, güven inşası, "
    "kriz yönetimi, delegasyon mastery'si, kendi liderlik stilini anlama, "
    "değişime karşı koymanın üstesinden gelme, ya da ekip dinamiklerinde "
    "gizli güç dinamikleri). Seçtiğin temayı derinlemesine işle:\n"
    "- Adı olan, bilimsel temelli bir çerçeve/model tanıt (örn. Crucial "
    "Conversations, Situational Leadership, Johari Window vs.) ve kaynağını belirt\n"
    "- Çerçeveyi adım adım bir iş durumunda nasıl uygulanacağını göster "
    "(gerçek bir diyalog, vaka ya da senaryo)\n"
    "- Yöneticilerin bu konuda EN SIK yaptığı hatayı ve düzeltmesini anlat\n"
    "- Bu gelişimin ekibe, sonuçlara ve kişisel etkiye ne kadar katkı "
    "yapabileceğini açıkla\n\n"
    "## B. HESAP VEREBILIRLIK (Accountability & Wins)\n"
    "Taahhütlere bağlılık perspektifinden koç ol:\n"
    "- Dün verilen görevlerin durumunu değerlendir (yapıldı mı, yarıda mı, "
    "engeller neler?)\n"
    "- Son zamanlardaki başarıları ve küçük kazanımları kutla (motivasyon "
    "kritiktir)\n"
    "- Eğer engeller varsa, bunları tespit et ve çözmek için bir strateji öner\n"
    "- Bugün için SOMUT, 15-30 dakikalık TEK bir gelişim görevini tanımla "
    "(liderlik + verimlilik kombinasyonu)\n\n"
    "## Genel Talimatlar\n"
    "- Türkçe olsun ve akıcı olsun; yapay kurum dili yok\n"
    "- Derinlik: kısa cümlelerden kaçın, her noktaya neden önemli olduğunu açıkla\n"
    "- Pratiklik: 'yapılması gereken' değil, 'nasıl yapılacağı' anlatılacak\n"
    "- Tones: cesur ama destekleyici; zorlama istediğin şeyler saygıdeğer\n"
    + RICH_BRIEFING_GUIDE
)


# --- Data Structures -------------------------------------------------------

DEFAULT_STATE_FILE = ".assistant_state/executive_coaching.json"


@dataclass
class LeadershipMetrics:
    """Leadership development tracking."""

    current_focus: str = ""
    strengths: List[str] = field(default_factory=list)
    development_areas: List[str] = field(default_factory=list)
    frameworks_studied: List[str] = field(default_factory=list)
    this_week_challenge: str = ""


@dataclass
class AccountabilityMetrics:
    """Commitment and task accountability tracking."""

    commitments: List[str] = field(default_factory=list)
    completion_status: Dict[str, str] = field(
        default_factory=dict
    )  # commitment -> status
    blockers: List[str] = field(default_factory=list)
    wins: List[str] = field(default_factory=list)
    streak_days: int = 0


@dataclass
class CoachingInsight:
    """A coaching observation and recommendation."""

    observation: str = ""
    recommendation: str = ""
    next_steps: List[str] = field(default_factory=list)
    priority: str = "medium"  # high, medium, low


@dataclass
class ExecutiveCoachingReport:
    """Complete executive coaching report."""

    generated_at: str
    summary: str
    leadership: Dict[str, Any] = field(default_factory=dict)
    accountability: Dict[str, Any] = field(default_factory=dict)
    coaching_insights: Dict[str, Any] = field(default_factory=dict)
    daily_task: str = ""

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(
            {
                "generated_at": self.generated_at,
                "summary": self.summary,
                "leadership": self.leadership,
                "accountability": self.accountability,
                "coaching_insights": self.coaching_insights,
                "daily_task": self.daily_task,
            },
            ensure_ascii=False,
            indent=2,
        )


@dataclass
class ExecutiveCoachingState:
    """Persistent state for executive coaching."""

    last_generated: str = ""
    leadership_history: List[Dict[str, Any]] = field(default_factory=list)
    accountability_history: List[Dict[str, Any]] = field(default_factory=list)
    coaching_notes: List[Dict[str, Any]] = field(default_factory=list)
    achievements: List[str] = field(default_factory=list)
    patterns: Dict[str, Any] = field(default_factory=dict)
    growth_areas: Dict[str, int] = field(default_factory=dict)  # area -> days_focused

    @classmethod
    def from_dict(cls, data: dict) -> "ExecutiveCoachingState":
        """Load from dictionary."""
        return cls(
            last_generated=str(data.get("last_generated") or ""),
            leadership_history=[
                dict(h) for h in (data.get("leadership_history") or [])
            ],
            accountability_history=[
                dict(h) for h in (data.get("accountability_history") or [])
            ],
            coaching_notes=[dict(n) for n in (data.get("coaching_notes") or [])],
            achievements=[str(a) for a in (data.get("achievements") or [])],
            patterns=dict(data.get("patterns") or {}),
            growth_areas={
                str(k): int(v) for k, v in (data.get("growth_areas") or {}).items()
            },
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "last_generated": self.last_generated,
            "leadership_history": self.leadership_history,
            "accountability_history": self.accountability_history,
            "coaching_notes": self.coaching_notes,
            "achievements": self.achievements,
            "patterns": self.patterns,
            "growth_areas": self.growth_areas,
        }


# --- Main Advisor Class -----------------------------------------------


class ExecutiveCoachingAdvisor(LLMAdvisor):
    """Consolidated executive coaching advisor.

    Merges leadership development coaching with accountability tracking
    into a unified executive growth framework. Provides both "who you're
    becoming" (leadership) and "what you're committing to" (accountability)
    coaching.
    """

    key = "executive_coaching"
    title = "Yönetici Koçu (Gelişim + Hesap Verebilirlik)"
    system_prompt = SYSTEM_PROMPT
    user_prompt = USER_PROMPT
    private = True  # Contains personal development data

    def __init__(self) -> None:
        """Initialize the executive coaching advisor."""
        self._state = ExecutiveCoachingState()
        self._observed: List[Briefing] = []

    # -- State Management ---------------------------------------------------

    @staticmethod
    def _state_path() -> str:
        """Get the state file path."""
        return setting("EXECUTIVE_COACHING_STATE_FILE") or DEFAULT_STATE_FILE

    def _load_state(self) -> ExecutiveCoachingState:
        """Load persistent state. Missing/broken file returns fresh start."""
        path = self._state_path()
        if not path or not os.path.exists(path):
            return ExecutiveCoachingState()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return ExecutiveCoachingState.from_dict(json.load(fh))
        except Exception:
            # Corrupt or unreadable state defaults to fresh start
            return ExecutiveCoachingState()

    def _save_state(self, state: ExecutiveCoachingState) -> None:
        """Persist state to disk. I/O errors are swallowed."""
        path = self._state_path()
        if not path:
            return
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(state.to_dict(), fh, ensure_ascii=False, indent=2)
        except Exception:
            # Read-only or unwritable path must never break the briefing
            return

    # -- Observation Hook ---------------------------------------------------

    def observe(self, briefings: Sequence[Briefing]) -> None:
        """Receive briefings from other advisors for context."""
        self._observed = [b for b in briefings if b.key != self.key]

    # -- Main Generation Path -----------------------------------------------

    def _generate(self) -> Briefing:
        """Generate executive coaching briefing."""
        if not self._is_configured():
            return self.skipped("missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY")

        try:
            # Load persistent state
            self._state = self._load_state()

            # Generate LLM-based coaching content
            text = self._generate_coaching_content()

            # Parse and structure the response
            report = self._structure_coaching_report(text)

            # Save state for next run
            self._update_and_save_state(report)

            # Format for briefing
            briefing_text = self._format_briefing(report)

            return self.ok(briefing_text)

        except Exception as exc:
            return self.failed(f"Koçluk üretim hatası: {exc}")

    def _is_configured(self) -> bool:
        """Check if LLM provider is configured."""
        from ..integrations import llm

        return llm.is_configured()

    def _generate_coaching_content(self) -> str:
        """Generate LLM-based coaching content."""
        from ..integrations import llm

        return llm.generate_text(self.system_prompt, self.user_prompt)

    def _structure_coaching_report(self, llm_text: str) -> ExecutiveCoachingReport:
        """Structure LLM response into coaching report format."""
        now = datetime.now().isoformat()

        # Extract Turkish summary (first paragraph)
        summary = self._extract_summary(llm_text)

        # Build leadership section
        leadership = self._extract_leadership_section(llm_text)

        # Build accountability section
        accountability = self._extract_accountability_section(llm_text)

        # Build coaching insights section
        coaching_insights = self._extract_coaching_insights(llm_text)

        # Extract daily task
        daily_task = self._extract_daily_task(llm_text)

        return ExecutiveCoachingReport(
            generated_at=now,
            summary=summary,
            leadership=leadership,
            accountability=accountability,
            coaching_insights=coaching_insights,
            daily_task=daily_task,
        )

    def _extract_summary(self, text: str) -> str:
        """Extract Turkish summary from coaching content."""
        # Look for first meaningful paragraph or use first 100 words
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            return lines[0][:300] + ("..." if len(lines[0]) > 300 else "")
        return "Yönetici koçluk brifingi hazırlandı."

    def _extract_leadership_section(self, text: str) -> Dict[str, Any]:
        """Extract leadership development section from text."""
        leadership = {
            "current_focus": self._extract_focus_area(text),
            "strengths": self._extract_strengths(text),
            "development_areas": self._extract_dev_areas(text),
            "this_week_challenge": self._extract_challenge(text),
        }
        return leadership

    def _extract_accountability_section(self, text: str) -> Dict[str, Any]:
        """Extract accountability tracking section from text."""
        accountability = {
            "commitments": self._extract_commitments(text),
            "completion_status": {},
            "blockers": self._extract_blockers(text),
            "wins": self._extract_wins(text),
        }
        return accountability

    def _extract_coaching_insights(self, text: str) -> Dict[str, Any]:
        """Extract coaching insights and recommendations."""
        insights = {
            "observation": self._extract_observation(text),
            "recommendation": self._extract_recommendation(text),
            "next_steps": self._extract_next_steps(text),
        }
        return insights

    def _extract_daily_task(self, text: str) -> str:
        """Extract the daily coaching task (✅ Bugünün görevi)."""
        from .accountability_coach import extract_task

        task = extract_task(text)
        if task:
            return f"Günü şu görevle bitir: {task}"
        return "Bugünün koçluk görevini tanımlayın."

    # --- Helper Methods for Extraction ---

    def _extract_focus_area(self, text: str) -> str:
        """Extract main leadership focus area."""
        lines = text.split("\n")
        for line in lines:
            if "liderlik" in line.lower() and len(line) < 150:
                return line.strip()[:200]
        return "Liderlik gelişimi"

    def _extract_strengths(self, text: str) -> List[str]:
        """Extract identified strengths from text."""
        strengths = []
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if any(w in line.lower() for w in ["güçlü", "başarılı", "yetkin"]):
                strength = line.strip()
                if strength and len(strength) < 200:
                    strengths.append(strength)
                    if len(strengths) >= 3:
                        break
        return strengths[:3] if strengths else ["Liderlik potansiyeli güçlü"]

    def _extract_dev_areas(self, text: str) -> List[str]:
        """Extract development areas from text."""
        areas = []
        lines = text.split("\n")
        for line in lines:
            if any(
                w in line.lower() for w in ["gelişim", "çalışabilir", "geliştirebilir"]
            ):
                area = line.strip()
                if area and len(area) < 200:
                    areas.append(area)
                    if len(areas) >= 3:
                        break
        return areas[:3] if areas else ["Sürekli gelişim hedefleri"]

    def _extract_challenge(self, text: str) -> str:
        """Extract this week's challenge."""
        lines = text.split("\n")
        for line in lines:
            if "meydan" in line.lower() or "hedef" in line.lower():
                return line.strip()[:250]
        return "Liderlik kapasitesini geliştirmek"

    def _extract_commitments(self, text: str) -> List[str]:
        """Extract commitments from text."""
        commitments = []
        lines = text.split("\n")
        for line in lines:
            if "taahhüt" in line.lower() or "hedef" in line.lower():
                commitment = line.strip()
                if commitment and len(commitment) < 200:
                    commitments.append(commitment)
                    if len(commitments) >= 5:
                        break
        return commitments

    def _extract_blockers(self, text: str) -> List[str]:
        """Extract blockers/obstacles from text."""
        blockers = []
        lines = text.split("\n")
        for line in lines:
            if "engel" in line.lower() or "zorluk" in line.lower():
                blocker = line.strip()
                if blocker and len(blocker) < 200:
                    blockers.append(blocker)
                    if len(blockers) >= 3:
                        break
        return blockers

    def _extract_wins(self, text: str) -> List[str]:
        """Extract wins and achievements from text."""
        wins = []
        lines = text.split("\n")
        for line in lines:
            if any(
                w in line.lower() for w in ["başarı", "kazanım", "tamamladı", "yapıldı"]
            ):
                win = line.strip()
                if win and len(win) < 200:
                    wins.append(win)
                    if len(wins) >= 3:
                        break
        return wins

    def _extract_observation(self, text: str) -> str:
        """Extract key observation from coaching content."""
        lines = text.split("\n")
        # Look for observation-like content
        for line in lines:
            if len(line) > 50 and len(line) < 300:
                return line.strip()
        return text.split("\n")[0].strip() if text else "Koçluk gözlemi"

    def _extract_recommendation(self, text: str) -> str:
        """Extract main recommendation from coaching content."""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        # Look for actionable recommendations
        for line in lines:
            if "yapmalı" in line or "öner" in line.lower():
                return line[:300]
        return "Belirlenen alanlara odaklanarak gelişim sağlayın."

    def _extract_next_steps(self, text: str) -> List[str]:
        """Extract next steps from coaching content."""
        steps = []
        lines = text.split("\n")
        for line in lines:
            if "adım" in line.lower() or "yap" in line.lower():
                step = line.strip()
                if step and len(step) < 200:
                    steps.append(step)
                    if len(steps) >= 5:
                        break
        return steps[:5] if steps else ["Belirtilen önerileri uygulayın"]

    # --- State Management ---

    def _update_and_save_state(self, report: ExecutiveCoachingReport) -> None:
        """Update persistent state with new coaching data."""
        # Add to leadership history
        self._state.leadership_history.append(
            {
                "generated_at": report.generated_at,
                "focus": report.leadership.get("current_focus", ""),
                "strengths": report.leadership.get("strengths", []),
                "dev_areas": report.leadership.get("development_areas", []),
            }
        )

        # Add to accountability history
        self._state.accountability_history.append(
            {
                "generated_at": report.generated_at,
                "commitments": report.accountability.get("commitments", []),
                "blockers": report.accountability.get("blockers", []),
                "wins": report.accountability.get("wins", []),
            }
        )

        # Add coaching notes
        self._state.coaching_notes.append(
            {
                "generated_at": report.generated_at,
                "observation": report.coaching_insights.get("observation", ""),
                "recommendation": report.coaching_insights.get("recommendation", ""),
            }
        )

        # Track achievements
        wins = report.accountability.get("wins", [])
        self._state.achievements.extend(wins)

        # Update last generated timestamp
        self._state.last_generated = report.generated_at

        # Keep history manageable (last 30 days of data)
        self._trim_state_history()

        # Save to disk
        self._save_state(self._state)

    def _trim_state_history(self) -> None:
        """Keep state file manageable by limiting history."""
        # Keep last 30 entries
        if len(self._state.leadership_history) > 30:
            self._state.leadership_history = self._state.leadership_history[-30:]
        if len(self._state.accountability_history) > 30:
            self._state.accountability_history = self._state.accountability_history[
                -30:
            ]
        if len(self._state.coaching_notes) > 30:
            self._state.coaching_notes = self._state.coaching_notes[-30:]
        if len(self._state.achievements) > 50:
            self._state.achievements = self._state.achievements[-50:]

    # --- Formatting ---

    def _format_briefing(self, report: ExecutiveCoachingReport) -> str:
        """Format the structured report as readable briefing text."""
        lines = []

        # Headline
        lines.append(f"**Öne çıkan:** {report.summary}")
        lines.append("")

        # Leadership Section
        lines.append("*🎯 Liderlik Gelişimi*")
        if report.leadership.get("current_focus"):
            lines.append(f"• Bugünün Odağı: {report.leadership['current_focus']}")
        if report.leadership.get("strengths"):
            lines.append("• Güçlü Yönler:")
            for strength in report.leadership["strengths"][:2]:
                lines.append(f"  - {strength}")
        if report.leadership.get("development_areas"):
            lines.append("• Gelişim Alanları:")
            for area in report.leadership["development_areas"][:2]:
                lines.append(f"  - {area}")
        if report.leadership.get("this_week_challenge"):
            lines.append(
                f"• Bu Hafta Meydan: {report.leadership['this_week_challenge']}"
            )
        lines.append("")

        # Accountability Section
        lines.append("*✅ Hesap Verebilirlik & Kazanımlar*")
        if report.accountability.get("wins"):
            lines.append("• Yapılan Kazanımlar:")
            for win in report.accountability["wins"][:3]:
                lines.append(f"  - {win}")
        if report.accountability.get("commitments"):
            lines.append("• Taahhütler:")
            for commitment in report.accountability["commitments"][:3]:
                lines.append(f"  - {commitment}")
        if report.accountability.get("blockers"):
            lines.append("• Engeller:")
            for blocker in report.accountability["blockers"][:2]:
                lines.append(f"  - {blocker}")
        lines.append("")

        # Coaching Insights
        lines.append("*💡 Koçluk İçgörüleri*")
        if report.coaching_insights.get("observation"):
            lines.append(f"Gözlem: {report.coaching_insights['observation']}")
        if report.coaching_insights.get("recommendation"):
            lines.append(f"Öneri: {report.coaching_insights['recommendation']}")
        if report.coaching_insights.get("next_steps"):
            lines.append("Sonraki Adımlar:")
            for step in report.coaching_insights["next_steps"][:3]:
                lines.append(f"  - {step}")
        lines.append("")

        # Daily Task
        if report.daily_task:
            lines.append(f"✅ Bugünün görevi: {report.daily_task}")

        return "\n".join(lines)


__all__ = [
    "ExecutiveCoachingAdvisor",
    "ExecutiveCoachingReport",
    "ExecutiveCoachingState",
    "LeadershipMetrics",
    "AccountabilityMetrics",
    "CoachingInsight",
]
