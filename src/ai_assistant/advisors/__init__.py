"""Daily advisor agents.

Each advisor is a small persona that produces a short daily briefing. They
share one interface — :meth:`Advisor.generate_briefing` — which returns a
structured :class:`Briefing` with a status of ``ok``, ``failed`` or
``skipped``.

Advisors NEVER raise on network/LLM errors: they catch problems internally
and degrade to a ``failed`` (something configured broke) or ``skipped``
(nothing configured) briefing. With an empty ``.env`` every advisor reports
``skipped``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..config import is_incremental
from ..integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED

# What an advisor says on an incremental run when it has nothing to add.
NOTHING_NEW_NOTE = "yeni bulgu yok"


@dataclass
class BatchSection:
    """One advisor's LLM work, to be folded into a single batched request.

    The free Gemini tier only allows a couple of ``generateContent`` calls per
    quota window, so instead of one call per advisor the Operations Manager
    collects these sections and asks the model for the whole briefing at once
    (see :mod:`ai_assistant.advisors._batch`).

    Attributes:
        key: The advisor key, used as the section marker in the response.
        title: Human-readable Turkish title shown to the model.
        system_prompt: The persona the model should adopt for this section.
        user_prompt: What that persona should produce today.
    """

    key: str
    title: str
    system_prompt: str
    user_prompt: str


@dataclass
class Briefing:
    """Structured outcome of a single advisor run.

    Attributes:
        key: Stable identifier (e.g. ``weather``).
        title: Human-readable, Turkish advisor title shown in reports.
        status: One of ``ok``, ``failed`` or ``skipped``.
        text: The briefing body (Turkish) or a short reason when not ``ok``.
        new_findings: How many genuinely NEW findings fed this section, for
            finding-driven advisors. ``None`` means "not applicable".
        nothing_new: True for the compact "yeni bulgu yok" section an
            incremental run produces when an advisor has nothing to add.
        private: True when this section may contain PERSONAL data and must
            therefore never be published to the public dashboard (see
            :mod:`ai_assistant.reports`). Such sections go to Slack inline.
    """

    key: str
    title: str
    status: str
    text: str = ""
    new_findings: Optional[int] = None
    nothing_new: bool = False
    private: bool = False

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def failed(self) -> bool:
        return self.status == STATUS_FAILED

    @property
    def skipped(self) -> bool:
        return self.status == STATUS_SKIPPED


class Advisor:
    """Base class / interface for every daily advisor.

    Subclasses set ``key`` and ``title`` and implement
    :meth:`_generate`, returning a :class:`Briefing`. The public
    :meth:`generate_briefing` wraps that call so an unexpected exception is
    turned into a ``failed`` briefing rather than propagating.
    """

    key: str = "advisor"
    title: str = "Danışman"

    #: Whether this advisor can produce genuinely NEW findings between two runs
    #: on the same day. Feed-driven advisors set it to ``True``; the timeless
    #: coaching personas leave it ``False`` and stay quiet on incremental runs
    #: (see :func:`is_quiet`), which is what keeps four runs a day inside the
    #: free LLM quota.
    incremental_source: bool = False

    #: Whether this advisor's briefing may contain PERSONAL data (mail
    #: subjects, calendar entries, names). The dashboard is public — a public
    #: repository served from GitHub Pages and Vercel — so a ``private``
    #: advisor is NEVER written to ``frontend/reports/``; its section is
    #: delivered inline in the Slack message instead. Default ``False``: most
    #: advisors summarise public sources and are safe to publish.
    private: bool = False

    def _generate(self) -> Briefing:  # pragma: no cover - overridden
        raise NotImplementedError

    def generate_briefing(self) -> Briefing:
        """Run the advisor, never raising. Returns a structured briefing."""
        try:
            return self._generate()
        except Exception as exc:  # defensive: never let one advisor crash
            return self.failed(f"beklenmeyen hata: {exc}")

    # -- ordering hook ----------------------------------------------------
    def observe(self, briefings: Sequence["Briefing"]) -> None:
        """Receive the briefings produced EARLIER in the same run.

        A no-op for almost every advisor. The accountability coach uses it to
        read the other personas' ``✅ Bugünün görevi`` items, which is why it is
        registered last in :func:`all_advisors`. Implementations must never
        raise; the supervisor guards this call anyway.
        """
        return None

    # -- batching hooks ---------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        """LLM work to fold into the shared batched call, or ``None``.

        ``None`` means "leave me out of the batch": the advisor either does not
        use an LLM at all (the SRE watchdog) or cannot run right now (no
        provider key, missing config). Non-LLM data gathering — Google Calendar
        and Drive, RSS feeds — always stays outside the batch and runs per
        advisor.
        """
        return None

    def briefing_from_batch(self, text: str) -> Briefing:
        """Turn this advisor's slice of the batched response into a briefing.

        Only called when :meth:`batch_section` returned a section and the model
        actually produced content for it. Subclasses override to append their
        own deterministic extras (search links, caveats).
        """
        return self.ok(text.strip())

    # -- deduplication hooks ---------------------------------------------
    def new_finding_count(self) -> int:
        """How many genuinely new findings this advisor has for this run.

        Feed-driven advisors override it (after filtering their fetched items
        through :mod:`ai_assistant.memory`). Everyone else has no notion of
        "new", so the base returns 0.
        """
        return 0

    # -- helpers for subclasses ------------------------------------------
    def ok(self, text: str) -> Briefing:
        return Briefing(
            key=self.key,
            title=self.title,
            status=STATUS_OK,
            text=text,
            new_findings=self.new_finding_count() if self.incremental_source else None,
            private=self.private,
        )

    def failed(self, text: str) -> Briefing:
        return Briefing(
            key=self.key,
            title=self.title,
            status=STATUS_FAILED,
            text=text,
            private=self.private,
        )

    def skipped(self, text: str) -> Briefing:
        return Briefing(
            key=self.key,
            title=self.title,
            status=STATUS_SKIPPED,
            text=text,
            private=self.private,
        )

    def nothing_new(self, note: str = "") -> Briefing:
        """The compact "yeni bulgu yok" section for an incremental run.

        Reported as ``skipped`` — this advisor deliberately produced nothing —
        but flagged with ``nothing_new`` so the digest and the dashboard can
        render it as "nothing new" rather than "not configured".
        """
        return Briefing(
            key=self.key,
            title=self.title,
            status=STATUS_SKIPPED,
            text=note or NOTHING_NEW_NOTE,
            new_findings=0,
            nothing_new=True,
            private=self.private,
        )


def is_quiet(advisor: Advisor) -> bool:
    """Whether ``advisor`` should stay silent on THIS run.

    Only ever true in ``incremental`` mode, where an advisor works if — and
    only if — it found something the user has not already been told:

    * feed-driven advisors (``incremental_source``) run when their deduplicated
      item list is non-empty;
    * the timeless coaching personas always stay quiet, because "today's
      leadership lesson" is not a *new finding* and re-running it would both
      repeat yesterday and burn free-tier quota.

    Never raises: an advisor whose count blows up is treated as having
    something to say, which fails towards informing the user.
    """
    if not is_incremental():
        return False
    if not getattr(advisor, "incremental_source", False):
        return True
    try:
        return advisor.new_finding_count() <= 0
    except Exception:  # pragma: no cover - defensive only
        return False


def all_advisors() -> List[Advisor]:
    """Auto-discover and instantiate every advisor, in report order.

    Imports are local so that importing this package never pulls in a
    provider SDK eagerly and so a broken module cannot break discovery.

    PHASE 1A CONSOLIDATION:
    - New consolidated advisors: MorningOperationsAdvisor, CommunicationsCalendarAdvisor,
      ExecutiveCoachingAdvisor
    - Old advisors kept but commented for rollback capability
    - Transition period: both old and new imports available

    PHASE 1B CONSOLIDATION:
    - New consolidated advisors: CareerDevelopmentAdvisor, MarketIntelligenceAdvisor,
      AiInnovationAdvisor
    - Nine more old advisors commented out (career_hr, job_scout, language_coach,
      free_certs, sector_intel, ai_news, cx_research, banking_cc_projects,
      ai_mastery, innovation_lab) plus daily_ops_briefing, superseded by
      MorningOperationsAdvisor
    - Their .py files stay on disk so a rollback is a comment change, not a revert
    - Result: the team is down to the TEN advisors of the restructuring plan

    PHASE 1C CONSOLIDATION:
    - Two advisors retired from the live roster: weather (a phone already tells
      the user the forecast) and anka_bridge (the bridge is no longer fed)
    - Three advisors added: MeetingPrepAdvisor (toplantı hazırlık & takip),
      ComplaintRadarAdvisor (müşteri şikâyet & itibar radarı), and
      LinkedInCoach (professional image & content management)
    - The retired modules stay on disk, so a rollback is a comment change
    """
    # PHASE 1C: Retired from the live roster (module kept for rollback)
    # from .weather import WeatherAdvisor
    # PHASE 1A: Replaced by consolidated MorningOperationsAdvisor
    # from .morning_briefing import MorningBriefingAdvisor
    # from .mail_analyst import MailAnalystAdvisor
    # from .day_planner import DayPlannerAdvisor

    # NEW CONSOLIDATED ADVISORS (PHASE 1A)
    from .communications_calendar import CommunicationsCalendarAdvisor
    from .morning_operations import MorningOperationsAdvisor
    from .executive_coaching import ExecutiveCoachingAdvisor

    # NEW ADVISORS (PHASE 1C): morning meeting prep, sector complaint radar
    from .meeting_prep import MeetingPrepAdvisor
    from .complaint_radar import ComplaintRadarAdvisor

    # LinkedIn İmaj Koçu (LinkedIn profile & content management)
    from .linkedin_coach import LinkedInCoach

    # PHASE 1A: Consolidated into ExecutiveCoachingAdvisor
    # from .leadership_coach import LeadershipCoachAdvisor

    # NEW CONSOLIDATED ADVISORS (PHASE 1B)
    from .career_development import CareerDevelopmentAdvisor
    from .market_intelligence import MarketIntelligenceAdvisor
    from .ai_innovation import AiInnovationAdvisor

    from .kids_development import KidsDevelopmentAdvisor
    # PHASE 1B: Consolidated into CareerDevelopmentAdvisor
    # from .career_hr import CareerHrAdvisor
    # from .job_scout import JobScoutAdvisor
    # from .language_coach import LanguageCoachAdvisor
    # from .free_certs import FreeCertsAdvisor

    # PHASE 1B: Consolidated into MarketIntelligenceAdvisor
    # from .sector_intel import SectorIntelAdvisor
    # from .ai_news import AiNewsAdvisor
    # from .cx_research import CxResearchAdvisor
    # from .banking_cc_projects import BankingCcProjectsAdvisor

    # PHASE 1B: Consolidated into AiInnovationAdvisor
    # from .ai_mastery import AiMasteryAdvisor
    # from .innovation_lab import InnovationLabAdvisor

    # PHASE 1B: Superseded by MorningOperationsAdvisor (PHASE 1A)
    # from .daily_ops_briefing import DailyOpsBriefingAdvisor

    # ANALYSIS ENGINE PERSONAS: the data analyst reads the operation's own
    # numbers (see :mod:`ai_assistant.analysis`), the operations director turns
    # the whole run into a decision list.
    from .data_analyst import DataAnalystAdvisor
    from .operations_director import OperationsDirectorAdvisor

    # PHASE 1C: Retired from the live roster (module kept for rollback)
    # from .anka_bridge import AnkaBridgeAdvisor
    # PHASE 1A: Consolidated into ExecutiveCoachingAdvisor
    # from .accountability_coach import AccountabilityCoachAdvisor
    from .work_analyst import WorkAnalystAdvisor

    # 7/24 teknik nöbetçi (ai_assistant.watchdog) — brifinge bağlayan sarmalayıcı.
    from .sre_watchdog import SreWatchdogAdvisor

    return [
        # Position 1: Morning operations (PHASE 1A consolidation)
        MorningOperationsAdvisor(),
        # Position 2: Communications and calendar (PHASE 1A consolidation)
        CommunicationsCalendarAdvisor(),
        # Position 3: Career development (PHASE 1B consolidation)
        CareerDevelopmentAdvisor(),
        # Position 4: Market intelligence (PHASE 1B consolidation)
        MarketIntelligenceAdvisor(),
        # Position 5: Comprehensive market & sentiment analysis (expanded)
        ComplaintRadarAdvisor(),
        # Position 6: LinkedIn coach
        LinkedInCoach(),
        # Position 7: The operation's OWN numbers, read by the analysis engine.
        # Registered right after the market view: outside-in first, then
        # inside-out, which is the order a director reads a morning pack in.
        DataAnalystAdvisor(),
        # Position 9: AI mastery + innovation ideas (PHASE 1B consolidation)
        AiInnovationAdvisor(),
        # Other advisors (unchanged)
        KidsDevelopmentAdvisor(),
        # Executive coaching (PHASE 1A consolidation of Leadership + Accountability)
        ExecutiveCoachingAdvisor(),
        # Work Analyst: consolidates the SYSTEM's health after everyone ran.
        WorkAnalystAdvisor(),
        # Operations Director LAST of the content advisors: it synthesises
        # every section above — including the work analyst's — into the day's
        # decision list, so it must be the only one with the complete picture.
        OperationsDirectorAdvisor(),
        # SRE watchdog closes the run: it reports on the MACHINE (cron
        # freshness, quota, delivery, feeds, state commit) rather than on this
        # run's content, so it is registered after every content advisor.
        SreWatchdogAdvisor(),
    ]


__all__ = [
    "Advisor",
    "BatchSection",
    "Briefing",
    "NOTHING_NEW_NOTE",
    "all_advisors",
    "is_quiet",
]
