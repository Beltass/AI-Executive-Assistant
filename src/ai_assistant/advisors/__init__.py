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

from ..integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED


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
    """

    key: str
    title: str
    status: str
    text: str = ""

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
        use an LLM at all (weather, Anka bridge) or cannot run right now (no
        provider key, missing config). Non-LLM data gathering — Open-Meteo,
        RSS feeds — always stays outside the batch and runs per advisor.
        """
        return None

    def briefing_from_batch(self, text: str) -> Briefing:
        """Turn this advisor's slice of the batched response into a briefing.

        Only called when :meth:`batch_section` returned a section and the model
        actually produced content for it. Subclasses override to append their
        own deterministic extras (search links, caveats).
        """
        return self.ok(text.strip())

    # -- helpers for subclasses ------------------------------------------
    def ok(self, text: str) -> Briefing:
        return Briefing(key=self.key, title=self.title, status=STATUS_OK, text=text)

    def failed(self, text: str) -> Briefing:
        return Briefing(key=self.key, title=self.title, status=STATUS_FAILED, text=text)

    def skipped(self, text: str) -> Briefing:
        return Briefing(key=self.key, title=self.title, status=STATUS_SKIPPED, text=text)


def all_advisors() -> List[Advisor]:
    """Auto-discover and instantiate every advisor, in report order.

    Imports are local so that importing this package never pulls in a
    provider SDK eagerly and so a broken module cannot break discovery.
    """
    from .weather import WeatherAdvisor
    from .leadership_coach import LeadershipCoachAdvisor
    from .kids_development import KidsDevelopmentAdvisor
    from .career_hr import CareerHrAdvisor
    from .job_scout import JobScoutAdvisor
    from .sector_intel import SectorIntelAdvisor
    from .ai_news import AiNewsAdvisor
    from .free_certs import FreeCertsAdvisor
    from .banking_cc_projects import BankingCcProjectsAdvisor
    from .daily_ops_briefing import DailyOpsBriefingAdvisor
    from .language_coach import LanguageCoachAdvisor
    from .anka_bridge import AnkaBridgeAdvisor
    from .accountability_coach import AccountabilityCoachAdvisor

    return [
        WeatherAdvisor(),
        LeadershipCoachAdvisor(),
        KidsDevelopmentAdvisor(),
        CareerHrAdvisor(),
        JobScoutAdvisor(),
        SectorIntelAdvisor(),
        AiNewsAdvisor(),
        FreeCertsAdvisor(),
        BankingCcProjectsAdvisor(),
        DailyOpsBriefingAdvisor(),
        LanguageCoachAdvisor(),
        AnkaBridgeAdvisor(),
        # LAST on purpose: the accountability coach consolidates the OTHER
        # advisors' "✅ Bugünün görevi" items, so it must see them first.
        AccountabilityCoachAdvisor(),
    ]


__all__ = ["Advisor", "BatchSection", "Briefing", "all_advisors"]
