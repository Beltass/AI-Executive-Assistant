"""Operations Manager — the supervising agent over the daily advisors.

This is the single orchestration entry point. It auto-discovers every
advisor, runs each one, captures a structured :class:`~ai_assistant.advisors.Briefing`
per advisor, and guarantees that a failure in one advisor never breaks the
others. The result is a :class:`Supervision` summary describing who ran, each
status, any failure reasons, and aggregate counts.

Run with::

    python -m ai_assistant.operations_manager

Exits non-zero only when a *configured* advisor actually FAILED (mirroring
``health.py``). Advisors that ``skipped`` (nothing configured) exit 0.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import List, Optional

from .advisors import Advisor, Briefing, all_advisors
from .integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED


@dataclass
class Supervision:
    """Aggregated outcome of one supervised advisor run."""

    briefings: List[Briefing] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {
            STATUS_OK: sum(1 for b in self.briefings if b.status == STATUS_OK),
            STATUS_FAILED: sum(1 for b in self.briefings if b.status == STATUS_FAILED),
            STATUS_SKIPPED: sum(1 for b in self.briefings if b.status == STATUS_SKIPPED),
        }

    @property
    def failures(self) -> List[Briefing]:
        return [b for b in self.briefings if b.status == STATUS_FAILED]

    def summary_line(self) -> str:
        """A compact one-line summary, e.g. ``3 ok, 0 failed, 1 skipped``."""
        c = self.counts
        return f"{c[STATUS_OK]} ok, {c[STATUS_FAILED]} failed, {c[STATUS_SKIPPED]} skipped"


class OperationsManager:
    """Supervisor that registers and runs the advisor team."""

    def __init__(self, advisors: Optional[List[Advisor]] = None) -> None:
        # Auto-discover the full advisor team unless an explicit list is given.
        self.advisors: List[Advisor] = list(advisors) if advisors is not None else all_advisors()

    def register(self, advisor: Advisor) -> None:
        """Add an advisor to the supervised team."""
        self.advisors.append(advisor)

    def run(self) -> Supervision:
        """Run every advisor, isolating failures. Returns a supervision summary."""
        briefings: List[Briefing] = []
        for advisor in self.advisors:
            try:
                briefings.append(advisor.generate_briefing())
            except Exception as exc:  # extra guard beyond the advisor's own
                briefings.append(
                    Briefing(
                        key=getattr(advisor, "key", "unknown"),
                        title=getattr(advisor, "title", "Danışman"),
                        status=STATUS_FAILED,
                        text=f"denetleyici yakaladı, beklenmeyen hata: {exc}",
                    )
                )
        return Supervision(briefings=briefings)

    # Alias to make the supervisory intent explicit.
    supervise = run


_STATUS_STYLE = {
    STATUS_OK: ("OK", "green"),
    STATUS_FAILED: ("FAILED", "red"),
    STATUS_SKIPPED: ("SKIPPED", "yellow"),
}


def _render_rich(supervision: Supervision) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Operasyon Yöneticisi — Günlük Danışman Denetimi")
    table.add_column("Danışman", style="bold")
    table.add_column("Durum")
    table.add_column("Özet", overflow="fold")

    for b in supervision.briefings:
        label, color = _STATUS_STYLE.get(b.status, (b.status.upper(), "white"))
        preview = b.text if b.status != STATUS_OK else _first_line(b.text)
        table.add_row(b.title, f"[{color}]{label}[/{color}]", preview)

    console.print(table)
    c = supervision.counts
    console.print(
        f"Denetim özeti: [green]{c[STATUS_OK]} ok[/green], "
        f"[red]{c[STATUS_FAILED]} failed[/red], "
        f"[yellow]{c[STATUS_SKIPPED]} skipped[/yellow]"
    )


def _render_plain(supervision: Supervision) -> None:
    print("Operasyon Yöneticisi — Günlük Danışman Denetimi")
    print("-" * 60)
    for b in supervision.briefings:
        label = _STATUS_STYLE.get(b.status, (b.status.upper(), ""))[0]
        preview = b.text if b.status != STATUS_OK else _first_line(b.text)
        print(f"{b.title:<28} {label:<8} {preview}")
    print("-" * 60)
    print(f"Denetim özeti: {supervision.summary_line()}")


def _first_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return (line[:80] + "…") if len(line) > 80 else line


def main() -> int:
    """CLI entrypoint. Returns the process exit code."""
    supervision = OperationsManager().run()

    try:
        _render_rich(supervision)
    except Exception:
        _render_plain(supervision)

    # Non-zero only when a configured advisor actually FAILED.
    return 1 if supervision.counts[STATUS_FAILED] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
