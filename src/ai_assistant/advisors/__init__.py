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
from typing import List

from ..integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED


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

    return [
        WeatherAdvisor(),
        LeadershipCoachAdvisor(),
        KidsDevelopmentAdvisor(),
        CareerHrAdvisor(),
    ]


__all__ = ["Advisor", "Briefing", "all_advisors"]
