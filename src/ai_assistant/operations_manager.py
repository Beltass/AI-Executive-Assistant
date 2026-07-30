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

By default the LLM-backed advisors share ONE batched model call
(``DIGEST_BATCH_MODE``, see :mod:`ai_assistant.advisors._batch`); set it to
``false`` to go back to one call per advisor.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import List, Optional

from .advisors import Advisor, Briefing, all_advisors, is_quiet
from .advisors._batch import run_batch
from .config import MODE_FULL, briefing_mode, mode_label
from .integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED, llm


@dataclass
class Supervision:
    """Aggregated outcome of one supervised advisor run.

    ``mode`` records HOW the team ran: the flagship ``full`` briefing or an
    ``incremental`` top-up that reports only what is new (see
    :mod:`ai_assistant.memory`).
    """

    briefings: List[Briefing] = field(default_factory=list)
    mode: str = MODE_FULL

    @property
    def mode_label(self) -> str:
        """Turkish label for the run mode (``tam brifing`` / ``artımlı``)."""
        return mode_label(self.mode)

    @property
    def new_findings(self) -> int:
        """Total number of genuinely new findings across the whole team."""
        return sum(b.new_findings or 0 for b in self.briefings)

    @property
    def has_new_findings(self) -> bool:
        """True when at least one advisor found something not yet reported."""
        return self.new_findings > 0

    @property
    def nothing_new(self) -> List[Briefing]:
        return [b for b in self.briefings if b.nothing_new]

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
        """Run every advisor, isolating failures. Returns a supervision summary.

        By default the LLM-backed advisors are served by ONE batched model call
        (see :mod:`ai_assistant.advisors._batch`) instead of one call each,
        which is what makes the run fit a free-tier quota. Any advisor the
        batch did not cover — non-LLM ones, or sections the model omitted, or
        the whole team if the batched call failed — transparently falls back to
        its own per-advisor path.

        On an ``incremental`` run (``BRIEFING_MODE=incremental``) the advisors
        with nothing NEW to report never reach either path: they return a
        one-line "yeni bulgu yok" section and are kept out of the batched
        prompt, so a quiet run costs no model tokens at all.

        All LLM work shares one wall-clock budget
        (``LLM_TIME_BUDGET_SECONDS``), so an exhausted provider quota can never
        stretch the run past it: once spent, the remaining sections fail fast
        and the digest is still delivered on time.
        """
        # One shared wall-clock budget for the whole team. Without it, a spent
        # quota makes every advisor repeat the same doomed retry-and-fallback
        # dance and the job runs for over an hour (see
        # ``llm.DEFAULT_LLM_TIME_BUDGET_SECONDS``).
        llm.start_time_budget()

        briefings: List[Briefing] = []
        batched = run_batch(self.advisors)

        for advisor in self.advisors:
            try:
                # Let an advisor see what the team produced before it. The
                # accountability coach (registered last) needs this to collect
                # the other personas' "✅ Bugünün görevi" items; for everyone
                # else it is a no-op.
                self._observe(advisor, briefings)
                if is_quiet(advisor):
                    # Incremental run, nothing new from this advisor: say so in
                    # one line instead of repeating this morning's section.
                    briefings.append(advisor.nothing_new())
                    continue
                text = batched.get(advisor.key)
                if text:
                    briefings.append(advisor.briefing_from_batch(text))
                else:
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
        return Supervision(briefings=briefings, mode=briefing_mode())

    @staticmethod
    def _observe(advisor: Advisor, briefings: List[Briefing]) -> None:
        """Feed an advisor the run so far, never letting the hook break it."""
        try:
            advisor.observe(list(briefings))
        except Exception:  # a broken hook must not cost us the briefing
            return

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
    table = Table(
        title=(
            "Operasyon Yöneticisi — Günlük Danışman Denetimi "
            f"({supervision.mode_label})"
        )
    )
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
    print(
        "Operasyon Yöneticisi — Günlük Danışman Denetimi "
        f"({supervision.mode_label})"
    )
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
