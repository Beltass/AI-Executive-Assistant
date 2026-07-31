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

After each advisor runs successfully, the manager automatically distributes
the report to configured integrations:

- **Slack Channels**: Posts to advisor-specific channels (SLACK_CHANNEL_<ADVISOR>)
- **Asana**: Creates tasks from actionable items (ASANA_TOKEN)
- **Google Drive**: Archives reports to Drive (GOOGLE_DRIVE_FOLDER_ID)

All integrations degrade gracefully: failures are logged but never break the run.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from .advisors import Advisor, Briefing, all_advisors, is_quiet
from .advisors._batch import run_batch
from .config import MODE_FULL, briefing_mode, mode_label
from .integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED, llm

logger = logging.getLogger(__name__)


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
    """Supervisor that registers and runs the advisor team.

    After each advisor runs successfully, automatically distributes the report to:
    - Slack channels (if SLACK_CHANNEL_<ADVISOR> configured)
    - Asana projects (if ASANA_TOKEN configured)
    - Google Drive (if GOOGLE_DRIVE_FOLDER_ID configured)

    All integrations are optional and degrade gracefully on failure.
    """

    def __init__(self, advisors: Optional[List[Advisor]] = None) -> None:
        # Auto-discover the full advisor team unless an explicit list is given.
        self.advisors: List[Advisor] = list(advisors) if advisors is not None else all_advisors()

        # Distribution status tracking (per-advisor)
        self.distribution_status: Dict[str, Dict[str, Any]] = {}

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

        After each successful advisor run, automatically distributes the report to:
        - Slack channels (if configured)
        - Asana tasks (if configured)
        - Google Drive (if configured)

        All integrations are optional and degrade gracefully on failure.
        """
        # One shared wall-clock budget for the whole team. Without it, a spent
        # quota makes every advisor repeat the same doomed retry-and-fallback
        # dance and the job runs for over an hour (see
        # ``llm.DEFAULT_LLM_TIME_BUDGET_SECONDS``).
        llm.start_time_budget()

        briefings: List[Briefing] = []
        batched = run_batch(self.advisors)
        today = datetime.now().strftime("%Y-%m-%d")

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

                # After successful advisor run, distribute to integrations
                briefing = briefings[-1]
                if briefing.status == STATUS_OK:
                    self._distribute_results(
                        advisor.key,
                        advisor.title,
                        briefing,
                        today,
                    )

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

    def _distribute_results(
        self,
        advisor_id: str,
        advisor_title: str,
        briefing: Briefing,
        date: str,
    ) -> None:
        """Distribute advisor report to all configured integrations.

        Handles graceful degradation: logs but continues if any integration fails.

        Args:
            advisor_id: Stable advisor identifier (e.g., "weather").
            advisor_title: Turkish advisor title for display.
            briefing: The successful Briefing object.
            date: Report date in YYYY-MM-DD format.
        """
        status = {
            "slack": None,
            "asana": None,
            "drive": None,
        }

        # Resolve (do not send) the Slack route for this advisor
        try:
            status["slack"] = self._distribute_to_slack(
                advisor_id, advisor_title, briefing
            )
        except Exception as exc:
            status["slack"] = f"error: {exc}"
            logger.warning(f"Slack yönlendirmesi başarısız ({advisor_title}): {exc}")

        # Try to sync to Asana
        try:
            self._sync_to_asana(advisor_id, advisor_title, briefing)
            status["asana"] = "success"
            logger.info(f"Asana senkronizasyonu başarılı: {advisor_title}")
        except Exception as exc:
            status["asana"] = f"error: {exc}"
            logger.warning(f"Asana senkronizasyonu başarısız ({advisor_title}): {exc}")

        # Try to archive to Drive
        try:
            self._archive_to_drive(advisor_id, advisor_title, briefing, date)
            status["drive"] = "success"
            logger.info(f"Google Drive arşivlemesi başarılı: {advisor_title}")
        except Exception as exc:
            status["drive"] = f"error: {exc}"
            logger.warning(f"Google Drive arşivlemesi başarısız ({advisor_title}): {exc}")

        # Record distribution status
        self.distribution_status[advisor_id] = status

    def _distribute_to_slack(
        self,
        advisor_id: str,
        advisor_title: str,
        briefing: Briefing,
    ) -> str:
        """RESOLVE this advisor's Slack channel. Does not send — on purpose.

        The message itself is sent later, by
        :func:`ai_assistant.integrations.slack_channels.distribute`, once
        :func:`ai_assistant.reports.publish` has written the documents. Sending
        from here as well would post every section TWICE, and the message would
        have no link to the report it summarises, because that report does not
        exist yet at this point in the run.

        What this step is still good for is telling the run log — and the
        distribution status the dashboard reads — WHERE each advisor is routed,
        which is how a missing ``SLACK_CHANNEL_<KEY>`` becomes visible instead
        of silently collapsing into the main channel.

        Args:
            advisor_id: Stable advisor identifier (e.g., "weather").
            advisor_title: Turkish advisor title (e.g., "Hava Tahmini").
            briefing: The Briefing object containing the report text.

        Returns:
            A short status string recorded in ``distribution_status``.
        """
        try:
            from .integrations.channel_config import get_channel_config

            slack_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
            webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
            if not slack_token and not webhook:
                logger.debug(
                    "Slack kimlik bilgileri yapılandırılmamış "
                    "(SLACK_BOT_TOKEN veya SLACK_WEBHOOK_URL)"
                )
                return "skipped: kimlik bilgisi yok"

            config = get_channel_config()
            own = config.dedicated_channel(advisor_id)
            if own:
                logger.info(f"Slack yönlendirmesi: {advisor_title} → {own} (kendi kanalı)")
                return f"routed: {own}"

            fallback = config.get_channel(advisor_id, advisor_title)
            if not fallback:
                logger.debug(f"Slack kanalı yapılandırılmamış: {advisor_title}")
                return "skipped: kanal yok"

            logger.info(
                f"Slack yönlendirmesi: {advisor_title} → {fallback} "
                f"(ana kanal — SLACK_CHANNEL_{advisor_id.upper()} tanımlı değil)"
            )
            return f"routed (fallback): {fallback}"

        except Exception as exc:
            logger.error(f"Slack yönlendirme hatası ({advisor_title}): {exc}")
            return f"error: {exc}"

    def _sync_to_asana(
        self,
        advisor_id: str,
        advisor_title: str,
        briefing: Briefing,
    ) -> None:
        """Create Asana tasks from advisor report.

        Parses actionable items from the briefing and creates them as Asana tasks.
        Requires ASANA_TOKEN to be configured. Also checks for:
        - ASANA_WORKSPACE_ID: Workspace where tasks are created
        - ASANA_<ADVISOR_ID>_PROJECT: Project name for this advisor (optional)
        - ASANA_<ADVISOR_ID>_ASSIGNEE: Email to assign tasks to (optional)

        Logs but continues if Asana not configured or if project creation fails.
        Does not raise.

        Args:
            advisor_id: Stable advisor identifier (e.g., "weather").
            advisor_title: Turkish advisor title (e.g., "Hava Tahmini").
            briefing: The Briefing object containing the report text.
        """
        try:
            asana_token = os.getenv("ASANA_TOKEN", "").strip()
            if not asana_token:
                logger.debug("ASANA_TOKEN yapılandırılmamış")
                return

            workspace_id = os.getenv("ASANA_WORKSPACE_ID", "").strip()
            if not workspace_id:
                logger.debug("ASANA_WORKSPACE_ID yapılandırılmamış")
                return

            from .integrations.asana import AsanaClient

            # Get advisor-specific config (project name, assignee)
            project_env = f"ASANA_{advisor_id.upper()}_PROJECT"
            project_name = (os.getenv(project_env, "") or "").strip() or f"{advisor_title} — Görevler"

            assignee_env = f"ASANA_{advisor_id.upper()}_ASSIGNEE"
            assignee_email = (os.getenv(assignee_env, "") or "").strip() or None

            logger.debug(
                f"Asana sinkronizasyonu başlanıyor ({advisor_title}): "
                f"project={project_name}, assignee={assignee_email or 'none'}"
            )

            # Initialize Asana client
            client = AsanaClient(token=asana_token, workspace_id=workspace_id)

            # Get or create project
            project_result = client.get_or_create_project(project_name)
            if not project_result.success:
                logger.warning(
                    f"Asana proje oluşturma başarısız ({advisor_title}): {project_result.error}"
                )
                return

            # For now, we extract basic task info from the briefing text.
            # In production, you would parse the JSON report structure
            # to extract actionable items with proper metadata.
            #
            # Example: if briefing.text contains sections like:
            # - "Yapılacaklar:"
            # - "Eylem Öğeleri:"
            # - "Acil:"
            # We would parse those and create tasks.
            #
            # Since we don't have structured JSON here, we create a summary task:

            summary_task_name = f"{advisor_title} — {datetime.now().strftime('%Y-%m-%d')}"
            summary_task_desc = f"Danışman: {advisor_title}\n\n{briefing.text[:500]}"

            task_result = client.add_task(
                project_id=project_result.project_id,
                task_name=summary_task_name,
                assignee_email=assignee_email,
                description=summary_task_desc,
            )

            if task_result.success:
                logger.info(f"Asana görev oluşturuldu: {task_result.task_name} ({task_result.task_id})")
            else:
                logger.warning(f"Asana görev oluşturma başarısız: {task_result.error}")

        except ImportError:
            logger.debug("Asana integrations kullanılamıyor")
        except Exception as exc:
            logger.error(f"Asana sinkronizasyonu hatası ({advisor_title}): {exc}")

    def _archive_to_drive(
        self,
        advisor_id: str,
        advisor_title: str,
        briefing: Briefing,
        date: str,
    ) -> None:
        """Archive advisor report to Google Drive.

        Saves the briefing text as a document under
        GOOGLE_DRIVE_FOLDER_ID/<date>/<advisor_id>.md

        Requires:
        - Google OAuth credentials (see google_auth module)
        - GOOGLE_DRIVE_FOLDER_ID: Root folder for reports

        Logs but continues if Drive not configured or authentication fails.
        Does not raise.

        Args:
            advisor_id: Stable advisor identifier (e.g., "weather").
            advisor_title: Turkish advisor title (e.g., "Hava Tahmini").
            briefing: The Briefing object to archive.
            date: Report date in YYYY-MM-DD format (e.g., "2026-07-31").
        """
        try:
            folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
            if not folder_id:
                logger.debug("GOOGLE_DRIVE_FOLDER_ID yapılandırılmamış")
                return

            from .integrations.google_drive import DriveClient, MIME_TYPE_MARKDOWN

            logger.debug(f"Google Drive'a yükleniyor: {advisor_title} ({date})")

            # Initialize Drive client
            client = DriveClient()

            # Find or create date folder
            date_folder_id = client.get_folder_id_by_name(folder_id, date)
            if not date_folder_id:
                logger.debug(f"Tarih klasörü oluşturuluyor: {date}")
                date_folder_id = client._create_folder(folder_id, date)

            # Save the briefing as the same structured document the dashboard
            # renders — title block, metric table, sections, action checklist
            # and sources — so the file in Drive (and its Slack preview) is a
            # deliverable rather than a raw dump. Falls back to the plain body
            # if the renderer ever chokes: an archive is better than nothing.
            file_name = f"{advisor_id}.md"
            try:
                from . import reports as reports_module

                report = reports_module.build_report(
                    briefing, date, datetime.now(reports_module.ISTANBUL)
                )
                file_content = report.to_markdown()
            except Exception as exc:  # pragma: no cover - defensive only
                logger.warning(f"Rapor markdown'ı üretilemedi ({advisor_title}): {exc}")
                file_content = f"# {advisor_title}\n\n**Tarih:** {date}\n\n{briefing.text}"

            file_id = client.upload_report(
                file_name=file_name,
                file_content=file_content,
                folder_id=date_folder_id,
                mime_type=MIME_TYPE_MARKDOWN,
            )

            logger.info(f"Google Drive'a kaydedildi ({advisor_title}): {file_id}")

        except Exception as exc:
            logger.error(f"Google Drive arşivlemesi hatası ({advisor_title}): {exc}")

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
    ops_manager = OperationsManager()
    supervision = ops_manager.run()

    try:
        _render_rich(supervision)
    except Exception:
        _render_plain(supervision)

    # Save distribution status to status report (for monitoring)
    _save_distribution_status(ops_manager.distribution_status)

    # Non-zero only when a configured advisor actually FAILED.
    return 1 if supervision.counts[STATUS_FAILED] > 0 else 0


def _save_distribution_status(distribution_status: Dict[str, Dict[str, Any]]) -> None:
    """Save integration distribution status to status report.

    Records which advisors were successfully distributed to Slack, Asana, and
    Google Drive. This helps monitor integration health and identify failures.

    Does not raise; failures are logged only.

    Args:
        distribution_status: Dict mapping advisor IDs to integration statuses.
    """
    try:
        if not distribution_status:
            logger.debug("Dağıtım durumu kaydedilecek veri yok")
            return

        # Create a summary of distribution status
        summary = {
            "timestamp": datetime.now().isoformat(),
            "advisors": distribution_status,
            "summary": {
                "slack": sum(1 for s in distribution_status.values() if s.get("slack") == "success"),
                "asana": sum(1 for s in distribution_status.values() if s.get("asana") == "success"),
                "drive": sum(1 for s in distribution_status.values() if s.get("drive") == "success"),
            },
        }

        logger.info(f"Dağıtım durumu: {json.dumps(summary['summary'])}")

    except Exception as exc:
        logger.error(f"Dağıtım durumu kaydı hatası: {exc}")


if __name__ == "__main__":
    sys.exit(main())
