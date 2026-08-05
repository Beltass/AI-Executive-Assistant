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

from . import memory
from .advisors import Advisor, BatchSection, Briefing, all_advisors, is_quiet
from .advisors._batch import (
    batch_mode_enabled,
    collect_sections,
    last_outcome,
    per_advisor_fallback_enabled,
    run_batch,
)
from .config import MODE_FULL, briefing_mode, mode_label
from .integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED, llm
from .status_report import (
    ADVISOR_META,
    TRIGGER_ALWAYS,
    TRIGGER_DATA,
    TRIGGER_USER_REQUESTED,
    TRIGGER_WEEKLY,
    advisor_data_owner,
    advisor_trigger,
)

logger = logging.getLogger(__name__)

# --- why an advisor did not run ---------------------------------------------
#
# Machine-readable reason codes. They end up in the metrics file next to the
# token counts (:mod:`ai_assistant.metrics`), which is what turns "this run was
# cheap" into "this run was cheap BECAUSE nine advisors had no new data".

#: The shared batched call carried this advisor and came back with nothing, and
#: ``DIGEST_BATCH_FALLBACK_MODE`` is ``off`` — see :mod:`ai_assistant.advisors._batch`.
SKIP_BATCH_FAILED = "batch_failed"

#: This advisor's source has not changed since it last reported on it.
SKIP_DATA_UNCHANGED = "veri_degismedi"

#: This advisor's trigger is not due on this run (weekly / user-requested).
SKIP_NOT_TRIGGERED = "tetiklenmedi"

#: Incremental run, and the advisor had nothing genuinely new.
SKIP_NOTHING_NEW = "yeni_bulgu_yok"

_SKIP_NOTE = {
    SKIP_BATCH_FAILED: (
        "toplu brifing başarısız oldu ve tekil yedek mod kapalı "
        "(DIGEST_BATCH_FALLBACK_MODE=off)"
    ),
    SKIP_DATA_UNCHANGED: "kaynak verisi son çalıştırmadan beri değişmedi",
    SKIP_NOT_TRIGGERED: "bu çalıştırmada tetiklenmedi",
}


# --- WHO runs on THIS run ----------------------------------------------------
#
# Every advisor used to run on every run, four times a day, whatever it had to
# say. "Bu haftanın liderlik dersi" does not change between 07:00 and 10:00, and
# a career feed that has not published anything since breakfast has nothing to
# add either — but both still cost their slice of a batched prompt.
#
# So the manifest's ``trigger`` field now decides, and this is where it is read
# (:mod:`ai_assistant.status_report`):
#
#   always          every run — the briefing is useless without it
#   data_triggered  only when its ``data_owner`` source actually changed
#   weekly          only on the weekly slot
#   user_requested  only when named explicitly
#
# TWO DELIBERATE ESCAPE HATCHES.
#   * ``DIGEST_FORCE_ADVISORS`` names advisors that must run regardless of their
#     trigger (``all`` forces the whole roster). This is the manual path a
#     workflow_dispatch input maps onto, and it is what makes a
#     ``user_requested`` advisor reachable at all.
#   * An advisor that is NOT in the manifest — a test double, a locally
#     registered one — is always treated as ``always``. The filter may not
#     silence something it knows nothing about.

#: Comma-separated advisor keys to run no matter what their trigger says.
FORCE_ADVISORS_ENV = "DIGEST_FORCE_ADVISORS"
#: Value that forces the ENTIRE roster.
FORCE_ALL = "all"

#: Explicit yes/no for "is this the weekly slot?"; overrides the weekday check.
WEEKLY_RUN_ENV = "DIGEST_WEEKLY_RUN"
#: Which weekday IS the weekly slot (0 = Monday), when the env above is unset.
WEEKLY_DAY_ENV = "DIGEST_WEEKLY_DAY"
DEFAULT_WEEKLY_DAY = 0  # Monday: the week's plan is worth having on day one.

_TRUTHY = {"1", "true", "yes", "on", "evet"}
_FALSY = {"0", "false", "no", "off", "hayir", "hayır"}


def forced_advisors() -> frozenset:
    """Advisor keys the user explicitly asked for (``DIGEST_FORCE_ADVISORS``).

    Returns ``frozenset({"all"})`` when the whole roster was forced, so callers
    check with :func:`_is_forced` rather than by membership.
    """
    raw = (os.getenv(FORCE_ADVISORS_ENV) or "").strip()
    if not raw:
        return frozenset()
    keys = {part.strip().lower() for part in raw.replace(";", ",").split(",")}
    return frozenset(key for key in keys if key)


def _is_forced(key: str, forced: frozenset) -> bool:
    return FORCE_ALL in forced or key in forced


def weekly_due(now: Optional[datetime] = None) -> bool:
    """Whether THIS run is the weekly slot.

    ``DIGEST_WEEKLY_RUN`` answers outright when set (that is how the scheduled
    weekly workflow says "this is the one"). Otherwise the weekday decides, so
    a repository with no extra configuration still gets its weekly sections
    exactly once a week instead of never.
    """
    raw = (os.getenv(WEEKLY_RUN_ENV) or "").strip().lower()
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    try:
        day = int((os.getenv(WEEKLY_DAY_ENV) or "").strip() or DEFAULT_WEEKLY_DAY)
    except ValueError:
        day = DEFAULT_WEEKLY_DAY
    if not 0 <= day <= 6:
        day = DEFAULT_WEEKLY_DAY
    return (now or datetime.now()).weekday() == day


def trigger_allows(key: str, forced: frozenset, weekly: bool) -> bool:
    """Whether ``key``'s trigger lets it run on this run.

    ``data_triggered`` returns ``True`` here: whether its SOURCE moved is a
    separate, more expensive question, answered later by the data gate once the
    material has actually been gathered.
    """
    if _is_forced(key, forced):
        return True
    if key not in ADVISOR_META:
        return True  # unknown advisor: never silenced by a rule about others
    trigger = advisor_trigger(key)
    if trigger == TRIGGER_WEEKLY:
        return weekly
    if trigger == TRIGGER_USER_REQUESTED:
        return False
    return True  # always, data_triggered, or an unrecognised value: run it


@dataclass
class Supervision:
    """Aggregated outcome of one supervised advisor run.

    ``mode`` records HOW the team ran: the flagship ``full`` briefing or an
    ``incremental`` top-up that reports only what is new (see
    :mod:`ai_assistant.memory`).

    ``executed_advisors`` / ``skipped_advisors`` record WHO actually worked and
    why the others did not. A run that costs a tenth of yesterday's tokens is
    either a big win or a silent outage, and only the reason codes tell the two
    apart; :mod:`ai_assistant.metrics` writes them next to the token counts.
    """

    briefings: List[Briefing] = field(default_factory=list)
    mode: str = MODE_FULL
    #: Keys of the advisors that really ran this time, in roster order.
    executed_advisors: List[str] = field(default_factory=list)
    #: ``{advisor_key: reason_code}`` for everyone who did not — see the
    #: ``SKIP_*`` constants in this module.
    skipped_advisors: Dict[str, str] = field(default_factory=dict)

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
            STATUS_SKIPPED: sum(
                1 for b in self.briefings if b.status == STATUS_SKIPPED
            ),
        }

    @property
    def failures(self) -> List[Briefing]:
        return [b for b in self.briefings if b.status == STATUS_FAILED]

    def summary_line(self) -> str:
        """A compact one-line summary, e.g. ``3 ok, 0 failed, 1 skipped``."""
        c = self.counts
        return (
            f"{c[STATUS_OK]} ok, {c[STATUS_FAILED]} failed, {c[STATUS_SKIPPED]} skipped"
        )


class OperationsManager:
    """Supervisor that registers and runs the advisor team.

    After each advisor runs successfully, automatically distributes the report to:
    - Slack channels (if SLACK_CHANNEL_<ADVISOR> configured)
    - Asana projects (if ASANA_TOKEN configured)
    - Google Drive (if GOOGLE_DRIVE_FOLDER_ID configured)

    All integrations are optional and degrade gracefully on failure.
    """

    def __init__(
        self,
        advisors: Optional[List[Advisor]] = None,
        use_manifest_filters: Optional[bool] = None,
    ) -> None:
        # Auto-discover the full advisor team unless an explicit list is given.
        explicit = advisors is not None
        self.advisors: List[Advisor] = list(advisors) if explicit else all_advisors()

        # The manifest-driven gates — run by trigger, skip on unchanged data —
        # govern the AUTO-DISCOVERED team. Handing this class an explicit list
        # is itself a request to run exactly those advisors (that is how the
        # chat and test entry points use it), so the gates stay out of the way
        # unless asked for. ``use_manifest_filters`` overrides either default.
        self.use_manifest_filters: bool = (
            (not explicit)
            if use_manifest_filters is None
            else bool(use_manifest_filters)
        )

        # Distribution status tracking (per-advisor)
        self.distribution_status: Dict[str, Dict[str, Any]] = {}

    def register(self, advisor: Advisor) -> None:
        """Add an advisor to the supervised team."""
        self.advisors.append(advisor)

    def run(self) -> Supervision:
        """Run every advisor, isolating failures. Returns a supervision summary.

        By default the LLM-backed advisors are served by ONE batched model call
        (see :mod:`ai_assistant.advisors._batch`) instead of one call each,
        which is what makes the run fit a free-tier quota. Advisors that never
        joined the batch — the non-LLM ones, and everybody when batching is
        switched off — run their own per-advisor path as before.

        An advisor that WAS in the batch and got nothing back is ``skipped``
        with the reason ``batch_failed`` rather than re-asked: the batch
        normally fails because the quota is gone, and retrying it once per
        advisor spends fifteen more calls proving it. Set
        ``DIGEST_BATCH_FALLBACK_MODE=per_advisor`` to restore the old retry.

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
        executed: List[str] = []
        skipped: Dict[str, str] = {}

        if self.use_manifest_filters:
            forced = forced_advisors()
            weekly = weekly_due()
            due, not_triggered = self._by_trigger(forced, weekly)
            sections, unchanged = self._data_gate(due, forced)
        else:
            due, not_triggered, sections, unchanged = self.advisors, {}, None, {}
        runnable = [a for a in due if a.key not in unchanged]

        batched = run_batch(runnable, sections=sections)
        batch = last_outcome()
        allow_fallback = per_advisor_fallback_enabled()
        if batch.failed:
            logger.error(
                "toplu brifing başarısız (%s): %s — tekil yedek mod %s",
                batch.failure_reason,
                batch.failure_detail,
                "AÇIK" if allow_fallback else "kapalı, ilgili ajanlar atlanacak",
            )
        today = datetime.now().strftime("%Y-%m-%d")

        for advisor in self.advisors:
            try:
                # Let an advisor see what the team produced before it. The
                # accountability coach (registered last) needs this to collect
                # the other personas' "✅ Bugünün görevi" items; for everyone
                # else it is a no-op.
                self._observe(advisor, briefings)
                reason = not_triggered.get(advisor.key) or unchanged.get(advisor.key)
                if reason:
                    # Its trigger is not due, or its source has not moved since
                    # the last delivered run. Either way: no prompt, no call.
                    briefings.append(advisor.skipped(_SKIP_NOTE[reason]))
                    skipped[advisor.key] = reason
                    continue
                if is_quiet(advisor):
                    # Incremental run, nothing new from this advisor: say so in
                    # one line instead of repeating this morning's section.
                    briefings.append(advisor.nothing_new())
                    skipped[advisor.key] = SKIP_NOTHING_NEW
                    continue
                text = batched.get(advisor.key)
                if text:
                    briefings.append(advisor.briefing_from_batch(text))
                elif batch.missing(advisor.key) and not allow_fallback:
                    # This advisor WAS in the failed batch. Re-asking it on its
                    # own would turn one dead call into one per advisor, which
                    # is exactly how a spent quota becomes a spent hour.
                    logger.warning(
                        "'%s' atlandı: toplu brifing başarısız (%s), tekil çağrı "
                        "yapılmıyor",
                        advisor.key,
                        batch.failure_reason or "eksik bölüm",
                    )
                    briefings.append(advisor.skipped(_SKIP_NOTE[SKIP_BATCH_FAILED]))
                    skipped[advisor.key] = SKIP_BATCH_FAILED
                    continue
                else:
                    briefings.append(advisor.generate_briefing())
                executed.append(advisor.key)

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
        return Supervision(
            briefings=briefings,
            mode=briefing_mode(),
            executed_advisors=executed,
            skipped_advisors=skipped,
        )

    # -- who runs --------------------------------------------------------
    def _by_trigger(
        self, forced: frozenset, weekly: bool
    ) -> "tuple[List[Advisor], Dict[str, str]]":
        """Split the team into "due on this run" and "not triggered".

        Reads the manifest's ``trigger`` field only — no gathering happens
        here, so an advisor whose trigger is not due costs nothing at all, not
        even the fetch it would have summarised.
        """
        due: List[Advisor] = []
        not_triggered: Dict[str, str] = {}
        for advisor in self.advisors:
            key = getattr(advisor, "key", "")
            if trigger_allows(key, forced, weekly):
                due.append(advisor)
            else:
                not_triggered[key] = SKIP_NOT_TRIGGERED
        if not_triggered:
            logger.info(
                "tetiklenmediği için atlanan danışmanlar (haftalık slot %s): %s",
                "açık" if weekly else "kapalı",
                ", ".join(sorted(not_triggered)),
            )
        return due, not_triggered

    def _data_gate(
        self, due: List[Advisor], forced: frozenset
    ) -> "tuple[Optional[List[BatchSection]], Dict[str, str]]":
        """Drop the ``data_triggered`` advisors whose SOURCE did not change.

        HOW IT KNOWS. Each advisor's batch section carries everything it
        gathered — the headlines, the calendar entries, the mail subjects —
        because that material IS the prompt. Hashing the sections of one
        ``data_owner`` therefore hashes that owner's raw data, with no second
        collection pass and no advisor-side bookkeeping: the sections collected
        here are handed straight to :func:`run_batch`.

        Identical hash to the last DELIVERED run means the model would be asked
        the same question again and would produce the section the user already
        read this morning, so its advisors are skipped with the reason
        ``veri_degismedi``. The hash is only staged; it is committed with the
        findings ledger after the digest actually goes out.

        Returns ``(sections, {advisor_key: reason})``. ``sections`` is ``None``
        when nothing was collected (batching off), which tells
        :func:`run_batch` to collect them itself exactly as before.
        """
        if not batch_mode_enabled():
            # Per-advisor mode does not build a shared prompt, so there is no
            # gathered material to hash without fetching everything twice.
            return None, {}

        sections = collect_sections(due)
        by_key = {section.key: section for section in sections}

        # Only the data-triggered members define their owner's content. An
        # ``always`` advisor sharing the source must never be able to invalidate
        # the gate (its prompt carries the date, so it changes every day).
        owners: Dict[str, List[str]] = {}
        for advisor in due:
            key = getattr(advisor, "key", "")
            if key not in ADVISOR_META or advisor_trigger(key) != TRIGGER_DATA:
                continue
            if _is_forced(key, forced):
                continue  # explicitly asked for: the gate does not apply
            owner = advisor_data_owner(key)
            if owner and key in by_key:
                owners.setdefault(owner, []).append(key)

        ledger = memory.shared()
        unchanged: Dict[str, str] = {}
        for owner, keys in owners.items():
            payload = {
                key: (by_key[key].system_prompt or "") + (by_key[key].user_prompt or "")
                for key in sorted(keys)
            }
            try:
                changed = ledger.source_changed(owner, payload)
            except Exception as exc:  # a broken ledger must not skip anyone
                logger.warning("veri kapısı okunamadı (%s): %s", owner, exc)
                continue
            if changed:
                ledger.stage_source(owner, payload)
                continue
            logger.info(
                "'%s' kaynağı son çalıştırmadan beri değişmedi: %s atlanıyor",
                owner,
                ", ".join(sorted(keys)),
            )
            for key in keys:
                unchanged[key] = SKIP_DATA_UNCHANGED

        if unchanged:
            sections = [s for s in sections if s.key not in unchanged]
        return sections, unchanged

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
            status["asana"] = self._sync_to_asana(advisor_id, advisor_title, briefing)
        except Exception as exc:
            status["asana"] = f"error: {exc}"
        self._log_integration("Asana senkronizasyonu", advisor_title, status["asana"])

        # Try to archive to Drive
        try:
            status["drive"] = self._archive_to_drive(
                advisor_id, advisor_title, briefing, date
            )
        except Exception as exc:
            status["drive"] = f"error: {exc}"
        self._log_integration(
            "Google Drive arşivlemesi", advisor_title, status["drive"]
        )

        # Record distribution status
        self.distribution_status[advisor_id] = status

    @staticmethod
    def _log_integration(label: str, advisor_title: str, status: str) -> None:
        """Report an integration's REAL outcome, never a blanket "başarılı".

        ``status`` is the short string the ``_sync_*``/``_archive_*`` helpers
        return and ``distribution_status`` records. Only ``success`` — meaning
        work actually happened (a task created, a document uploaded) — is
        reported as success; an unconfigured integration says which setting is
        missing, and one that ran without doing anything says exactly that.
        """
        detail = status.split(":", 1)[1].strip() if ":" in status else ""

        if status.startswith("success"):
            logger.info(f"{label} başarılı: {advisor_title}")
        elif status.startswith("skipped"):
            logger.info(
                f"{label} atlandı ({advisor_title}): "
                f"{detail or 'yapılandırma eksik'}"
            )
        elif status.startswith("error"):
            logger.warning(f"{label} başarısız ({advisor_title}): {detail or status}")
        else:
            logger.info(
                f"{label} çalıştı ama hiçbir iş yapmadı ({advisor_title}): "
                f"{detail or status}"
            )

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
                logger.info(
                    f"Slack yönlendirmesi: {advisor_title} → {own} (kendi kanalı)"
                )
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
    ) -> str:
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

        Returns:
            A short status string recorded in ``distribution_status``.
            ``success`` ONLY when a task was really created.
        """
        try:
            asana_token = os.getenv("ASANA_TOKEN", "").strip()
            if not asana_token:
                return "skipped: ASANA_TOKEN tanımlı değil"

            workspace_id = os.getenv("ASANA_WORKSPACE_ID", "").strip()
            if not workspace_id:
                return "skipped: ASANA_WORKSPACE_ID tanımlı değil"

            from .integrations.asana import AsanaClient

            # Get advisor-specific config (project name, assignee)
            project_env = f"ASANA_{advisor_id.upper()}_PROJECT"
            project_name = (
                os.getenv(project_env, "") or ""
            ).strip() or f"{advisor_title} — Görevler"

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
                return f"error: proje oluşturulamadı — {project_result.error}"

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

            summary_task_name = (
                f"{advisor_title} — {datetime.now().strftime('%Y-%m-%d')}"
            )
            summary_task_desc = f"Danışman: {advisor_title}\n\n{briefing.text[:500]}"

            task_result = client.add_task(
                project_id=project_result.project_id,
                task_name=summary_task_name,
                assignee_email=assignee_email,
                description=summary_task_desc,
            )

            if task_result.success:
                logger.info(
                    f"Asana görev oluşturuldu: {task_result.task_name} ({task_result.task_id})"
                )
                return "success: 1 görev oluşturuldu"

            return f"error: görev oluşturulamadı — {task_result.error}"

        except ImportError:
            return "skipped: Asana entegrasyon modülü kullanılamıyor"
        except Exception as exc:
            return f"error: {exc}"

    def _archive_to_drive(
        self,
        advisor_id: str,
        advisor_title: str,
        briefing: Briefing,
        date: str,
    ) -> str:
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

        Returns:
            A short status string recorded in ``distribution_status``.
            ``success`` ONLY when a document was really uploaded.
        """
        try:
            folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
            if not folder_id:
                return "skipped: GOOGLE_DRIVE_FOLDER_ID tanımlı değil"

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
                file_content = (
                    f"# {advisor_title}\n\n**Tarih:** {date}\n\n{briefing.text}"
                )

            file_id = client.upload_report(
                file_name=file_name,
                file_content=file_content,
                folder_id=date_folder_id,
                mime_type=MIME_TYPE_MARKDOWN,
            )

            if not file_id:
                return "no-op: belge yüklenmedi"

            logger.info(f"Google Drive'a kaydedildi ({advisor_title}): {file_id}")
            return "success: 1 belge yüklendi"

        except Exception as exc:
            return f"error: {exc}"

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
        "Operasyon Yöneticisi — Günlük Danışman Denetimi " f"({supervision.mode_label})"
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

        # Create a summary of distribution status. Only a status that STARTS
        # with "success" counts: a skipped or no-op integration must not
        # inflate these numbers (see ``_log_integration``).
        def _succeeded(value: Any) -> bool:
            return isinstance(value, str) and value.startswith("success")

        summary = {
            "timestamp": datetime.now().isoformat(),
            "advisors": distribution_status,
            "summary": {
                "slack": sum(
                    1
                    for s in distribution_status.values()
                    if _succeeded(s.get("slack"))
                ),
                "asana": sum(
                    1
                    for s in distribution_status.values()
                    if _succeeded(s.get("asana"))
                ),
                "drive": sum(
                    1
                    for s in distribution_status.values()
                    if _succeeded(s.get("drive"))
                ),
            },
        }

        logger.info(f"Dağıtım durumu: {json.dumps(summary['summary'])}")

    except Exception as exc:
        logger.error(f"Dağıtım durumu kaydı hatası: {exc}")


if __name__ == "__main__":
    sys.exit(main())
