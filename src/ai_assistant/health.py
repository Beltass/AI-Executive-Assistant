"""Aggregate connection checks and provide a CLI entrypoint.

Run with::

    python -m ai_assistant.health

Exits non-zero if any *configured* integration check FAILED. A ``skipped``
integration (missing credentials) does not cause a non-zero exit.
"""

from __future__ import annotations

import sys
from typing import Callable, List

from .integrations import (
    CheckResult,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED,
    asana,
    gmail,
    google_calendar,
    google_drive,
    llm,
    notion,
    slack,
    todoist,
)

# Ordered list of every integration check function.
CHECKS: List[Callable[[], CheckResult]] = [
    gmail.check_connection,
    google_calendar.check_connection,
    google_drive.check_connection,
    slack.check_connection,
    todoist.check_connection,
    notion.check_connection,
    llm.check_connection,
    asana.check_connection,
]


def run_all_checks() -> List[CheckResult]:
    """Run every integration check and return the aggregated results.

    Each check is individually guarded so that an unexpected exception in
    one integration cannot prevent the others from running.
    """
    results: List[CheckResult] = []
    for check in CHECKS:
        try:
            results.append(check())
        except Exception as exc:  # defensive: never let one check crash the run
            results.append(
                CheckResult(
                    name=getattr(check, "__module__", "unknown"),
                    status=STATUS_FAILED,
                    detail=f"unexpected error: {exc}",
                )
            )
    return results


def summarize(results: List[CheckResult]) -> dict:
    """Return counts keyed by status."""
    return {
        STATUS_OK: sum(1 for r in results if r.status == STATUS_OK),
        STATUS_FAILED: sum(1 for r in results if r.status == STATUS_FAILED),
        STATUS_SKIPPED: sum(1 for r in results if r.status == STATUS_SKIPPED),
    }


_STATUS_STYLE = {
    STATUS_OK: ("OK", "green"),
    STATUS_FAILED: ("FAILED", "red"),
    STATUS_SKIPPED: ("SKIPPED", "yellow"),
}


def _render_rich(results: List[CheckResult], counts: dict) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="AI Executive Assistant — Connection Check")
    table.add_column("Integration", style="bold")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")

    for r in results:
        label, color = _STATUS_STYLE.get(r.status, (r.status.upper(), "white"))
        table.add_row(r.name, f"[{color}]{label}[/{color}]", r.detail)

    console.print(table)
    console.print(
        f"Summary: [green]{counts[STATUS_OK]} ok[/green], "
        f"[red]{counts[STATUS_FAILED]} failed[/red], "
        f"[yellow]{counts[STATUS_SKIPPED]} skipped[/yellow]"
    )


def _render_plain(results: List[CheckResult], counts: dict) -> None:
    print("AI Executive Assistant — Connection Check")
    print("-" * 60)
    for r in results:
        label = _STATUS_STYLE.get(r.status, (r.status.upper(), ""))[0]
        print(f"{r.name:<24} {label:<8} {r.detail}")
    print("-" * 60)
    print(
        f"Summary: {counts[STATUS_OK]} ok, "
        f"{counts[STATUS_FAILED]} failed, "
        f"{counts[STATUS_SKIPPED]} skipped"
    )


def main() -> int:
    """CLI entrypoint. Returns the process exit code."""
    results = run_all_checks()
    counts = summarize(results)

    try:
        _render_rich(results, counts)
    except Exception:
        # rich not installed or a rendering issue — degrade to plain text.
        _render_plain(results, counts)

    # Non-zero exit only when something actually FAILED.
    return 1 if counts[STATUS_FAILED] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
