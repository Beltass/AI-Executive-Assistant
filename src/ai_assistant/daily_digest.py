"""Daily digest — assemble one Turkish report from the advisor team.

``build_digest()`` runs the :class:`~ai_assistant.operations_manager.OperationsManager`,
then formats every advisor's briefing into a single dated Turkish report with a
short supervision line from the manager. It returns the formatted text plus the
underlying supervision object (statuses/counts).

Multi-channel distribution is handled by ``distribute_digest_by_channel()``, which:
- Posts each advisor's report to its own SLACK_CHANNEL_<ADVISOR> sub-channel
- Posts the compact summary (one line + links per advisor) to SLACK_MAIN_CHANNEL
- Logs all distribution attempts and gracefully handles missing channels

The daily job does NOT call it directly: ``python -m
ai_assistant.notifiers.slack_notifier`` already publishes, fans out and
summarises in one pass. This function exists for a manual re-delivery.

Run with::

    python -m ai_assistant.daily_digest
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import date

from .advisors import NOTHING_NEW_NOTE
from .config import MODE_INCREMENTAL
from .integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from .operations_manager import OperationsManager, Supervision

logger = logging.getLogger(__name__)

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
    incremental = supervision.mode == MODE_INCREMENTAL
    heading = "🔄 Ara Brifing (yeni gelişmeler)" if incremental else "🗓️ Günlük Brifing"
    lines = [
        f"{heading} — {today}",
        "=" * 40,
        "",
    ]
    if incremental:
        lines.append(
            f"_Bu, günün ara çalıştırması: yalnızca yeni bulgular var "
            f"({supervision.new_findings} yeni)._"
        )
        lines.append("")

    # Advisors with nothing new are collapsed into ONE line at the end instead
    # of taking a section each — an incremental digest should be short.
    quiet = []
    for b in supervision.briefings:
        if b.nothing_new:
            quiet.append(b.title)
            continue
        label = _STATUS_LABEL.get(b.status, b.status.upper())
        lines.append(f"## {b.title} [{label}]")
        if b.status == STATUS_OK:
            lines.append(b.text.strip())
        elif b.status == STATUS_SKIPPED:
            lines.append(f"_Atlandı: {b.text}_")
        else:
            lines.append(f"_Bu bölüm hazırlanamadı: {b.text}_")
        lines.append("")

    if quiet:
        lines.append(f"🟰 {NOTHING_NEW_NOTE}: {', '.join(quiet)}")
        lines.append("")

    c = supervision.counts
    lines.append("-" * 40)
    lines.append(
        f"Operasyon Yöneticisi ({supervision.mode_label}): {c[STATUS_OK]} ok, "
        f"{c[STATUS_FAILED]} failed, {c[STATUS_SKIPPED]} skipped"
    )

    return Digest(text="\n".join(lines), supervision=supervision)


def distribute_digest_by_channel(
    supervision: Supervision, publication=None
) -> dict:
    """Distribute one run across the Slack workspace: sub-channels + summary.

    Each advisor's section goes to its OWN channel (``SLACK_CHANNEL_<KEY>``),
    then the MAIN channel (``SLACK_MAIN_CHANNEL``, falling back to
    ``SLACK_CHANNEL``) receives the compact digest: one line per advisor with
    its headline, a deep link to the full report on the dashboard, and a link
    into that advisor's channel.

    An advisor with no channel of its own falls back to the main channel.

    Both halves are delegated so there is exactly ONE implementation of each:
    :func:`ai_assistant.integrations.slack_channels.distribute` for the fan-out
    and :func:`ai_assistant.notifiers.slack_notifier.send_briefing_index` for
    the summary.

    Args:
        supervision: The Supervision object containing briefings and metadata.
        publication: An already-written :class:`ai_assistant.reports.Publication`.
            Omit it and the reports are published first, because the summary
            and the sub-channel messages both link to those documents.

    Returns:
        A distribution result dictionary with keys:
            - "main_channel": CheckResult for the main-channel summary
            - "advisor_channels": dict of advisor_key -> CheckResult
            - "distribution": the raw Distribution object (or None)
            - "summary": human-readable summary of the distribution
    """
    from . import reports as reports_module
    from .integrations.slack_channels import distribute
    from .notifiers.slack_notifier import send_briefing_index

    result = {
        "main_channel": None,
        "advisor_channels": {},
        "distribution": None,
        "summary": "Dağıtım yapılmadı",
    }

    if publication is None:
        publication = reports_module.publish(supervision)

    distribution = distribute(supervision, publication)
    result["distribution"] = distribution
    result["advisor_channels"] = {p.key: p.result for p in distribution.posts}

    main_result = send_briefing_index(
        supervision, publication, distribution=distribution
    )
    result["main_channel"] = main_result

    main_label = {
        STATUS_OK: "ana kanal ✓",
        STATUS_FAILED: "ana kanal ✗",
    }.get(main_result.status, "ana kanal atlandı")
    result["summary"] = f"{main_label} · {distribution.summary_line()}"
    logger.info(result["summary"])
    return result


def main() -> int:
    """CLI entrypoint. Prints the digest. Returns the process exit code."""
    digest = build_digest()
    print(digest.text)
    return 1 if digest.counts[STATUS_FAILED] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
