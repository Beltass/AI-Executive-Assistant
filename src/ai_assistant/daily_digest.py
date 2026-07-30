"""Daily digest — assemble one Turkish report from the advisor team.

``build_digest()`` runs the :class:`~ai_assistant.operations_manager.OperationsManager`,
then formats every advisor's briefing into a single dated Turkish report with a
short supervision line from the manager. It returns the formatted text plus the
underlying supervision object (statuses/counts).

Run with::

    python -m ai_assistant.daily_digest
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from .integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from .operations_manager import OperationsManager, Supervision

_STATUS_LABEL = {
    STATUS_OK: "OK",
    STATUS_FAILED: "HATA",
    STATUS_SKIPPED: "ATLANDI",
}


@dataclass
class Digest:
    """A rendered daily digest plus its supervision metadata."""

    text: str
    supervision: Supervision

    @property
    def counts(self) -> dict:
        return self.supervision.counts


def build_digest(supervision: Supervision | None = None) -> Digest:
    """Run the Operations Manager and assemble one formatted Turkish report."""
    if supervision is None:
        supervision = OperationsManager().run()

    today = date.today().strftime("%d.%m.%Y")
    lines = [
        f"🗓️ Günlük Brifing — {today}",
        "=" * 40,
        "",
    ]

    for b in supervision.briefings:
        label = _STATUS_LABEL.get(b.status, b.status.upper())
        lines.append(f"## {b.title} [{label}]")
        if b.status == STATUS_OK:
            lines.append(b.text.strip())
        elif b.status == STATUS_SKIPPED:
            lines.append(f"_Atlandı: {b.text}_")
        else:
            lines.append(f"_Bu bölüm hazırlanamadı: {b.text}_")
        lines.append("")

    c = supervision.counts
    lines.append("-" * 40)
    lines.append(
        f"Operasyon Yöneticisi: {c[STATUS_OK]} ok, "
        f"{c[STATUS_FAILED]} failed, {c[STATUS_SKIPPED]} skipped"
    )

    return Digest(text="\n".join(lines), supervision=supervision)


def main() -> int:
    """CLI entrypoint. Prints the digest. Returns the process exit code."""
    digest = build_digest()
    print(digest.text)
    return 1 if digest.counts[STATUS_FAILED] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
