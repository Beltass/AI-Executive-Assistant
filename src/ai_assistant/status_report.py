"""Status report — the machine-readable record of one briefing run.

Every run of the daily briefing ends by writing a small JSON file describing
what happened: how many advisors succeeded, which ones failed and why, whether
Slack accepted the digest, and a rolling window of the previous runs. That file
is what the static dashboard in ``frontend/`` renders, which turns the
otherwise invisible 07:00 UTC cron job into something the user can actually
watch from a phone.

Where it is written is controlled by ``STATUS_REPORT_FILE`` (default
``frontend/status.json``) so the file lands next to the dashboard and is served
from the same origin — no API, no CORS, no backend.

TWO HARD RULES, because the repository is PUBLIC:

1. **No content, ever.** The briefing bodies are the user's personal daily
   report. Only their character COUNT is recorded — a cheap, non-revealing
   proxy for "did we get real content".
2. **No secrets, ever.** Failure reasons are short diagnostics produced deep in
   the network layer; they are passed through :func:`sanitize` (which redacts
   every configured secret value plus the well-known key shapes) before being
   written, on top of the redaction the LLM layer already does.

And one operational rule: writing this file must NEVER break the briefing. Any
error is logged and swallowed — a monitoring artefact is worth strictly less
than the report it monitors.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .config import MODE_FULL, mode_label
from .integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED

logger = logging.getLogger(__name__)

STATUS_FILE_ENV = "STATUS_REPORT_FILE"
DEFAULT_STATUS_FILE = "frontend/status.json"

# How many past runs the dashboard's trend view keeps.
HISTORY_LIMIT = 30

# Turkey has been on a permanent UTC+3 since 2016, so a fixed offset is exact
# and needs no tz database on the runner.
ISTANBUL = timezone(timedelta(hours=3), "Europe/Istanbul")

# Longest failure/skip reason kept. Long enough to diagnose, short enough that
# a runaway error message cannot bloat the file the dashboard downloads.
MAX_DETAIL_CHARS = 400


# --- presentation metadata --------------------------------------------------
#
# Icon + category per advisor, kept HERE rather than on the advisor classes so
# the advisors stay purely about producing briefings. ``category`` is what the
# dashboard groups and filters by.

CATEGORY_CAREER = "kariyer"
CATEGORY_FAMILY = "aile"
CATEGORY_SECTOR = "sektör"
CATEGORY_GROWTH = "kişisel gelişim"
CATEGORY_OPS = "operasyon"

ADVISOR_META: Dict[str, Dict[str, str]] = {
    "weather": {"emoji": "🌤️", "category": CATEGORY_OPS},
    "leadership_coach": {"emoji": "🧭", "category": CATEGORY_GROWTH},
    "kids_development": {"emoji": "👨‍👩‍👧", "category": CATEGORY_FAMILY},
    "career_hr": {"emoji": "💼", "category": CATEGORY_CAREER},
    "job_scout": {"emoji": "🔎", "category": CATEGORY_CAREER},
    "sector_intel": {"emoji": "📊", "category": CATEGORY_SECTOR},
    "ai_news": {"emoji": "🤖", "category": CATEGORY_SECTOR},
    "free_certs": {"emoji": "🎓", "category": CATEGORY_GROWTH},
    "banking_cc_projects": {"emoji": "🏦", "category": CATEGORY_SECTOR},
    "ai_mastery": {"emoji": "🧠", "category": CATEGORY_GROWTH},
    "cx_research": {"emoji": "🎧", "category": CATEGORY_SECTOR},
    "daily_ops_briefing": {"emoji": "📋", "category": CATEGORY_OPS},
    "language_coach": {"emoji": "🗣️", "category": CATEGORY_GROWTH},
    "anka_bridge": {"emoji": "🕊️", "category": CATEGORY_OPS},
    "accountability_coach": {"emoji": "🔥", "category": CATEGORY_GROWTH},
}

DEFAULT_META = {"emoji": "🧩", "category": CATEGORY_OPS}


# --- sanitising -------------------------------------------------------------

# Env vars whose VALUE must never appear in the file. Their contents are
# replaced with a placeholder wherever they show up in a diagnostic string.
SECRET_ENV_VARS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "SLACK_WEBHOOK_URL",
    "SLACK_BOT_TOKEN",
    "ANKA_API_KEY",
    "ANKA_WEBHOOK_URL",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "GOOGLE_CLIENT_ID",
    "NOTION_API_KEY",
    "TODOIST_API_TOKEN",
)

# Well-known credential shapes, redacted even when the value never passed
# through this process's environment (a copy/pasted key inside an upstream
# error message, say).
_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z\-_]{10,}"),            # Google / Gemini
    re.compile(r"sk-[A-Za-z0-9\-_]{16,}"),             # OpenAI
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{8,}"),       # Slack tokens
    re.compile(r"ghp_[A-Za-z0-9]{16,}"),               # GitHub PAT
    re.compile(r"hooks\.slack\.com/services/\S+"),     # Slack webhook path
    re.compile(r"(?i)(api[-_]?key|token|secret|password)=[^\s&\"']+"),
)

REDACTED = "***"


def sanitize(text: Any, limit: int = MAX_DETAIL_CHARS) -> str:
    """Return ``text`` with every known secret removed and its length capped.

    Belt and braces: the LLM layer already redacts its own key from the errors
    it raises, but this file is committed to a PUBLIC repository, so every
    string that reaches it is scrubbed again here.

    ``limit`` caps the result; pass ``0`` to keep the full length, which is what
    :mod:`ai_assistant.reports` needs when it scrubs a whole report line by line
    (a report must stay readable, only its secrets must go).
    """
    if not text:
        return ""
    cleaned = str(text).replace("\n", " ").strip()

    for name in SECRET_ENV_VARS:
        value = (os.getenv(name) or "").strip()
        # Short values would cause absurd false positives ("1", "true"…).
        if len(value) >= 8 and value in cleaned:
            cleaned = cleaned.replace(value, REDACTED)

    for pattern in _SECRET_PATTERNS:
        cleaned = pattern.sub(REDACTED, cleaned)

    if limit and len(cleaned) > limit:
        cleaned = cleaned[:limit].rstrip() + "…"
    return cleaned


# --- helpers ----------------------------------------------------------------


def status_file_path() -> str:
    """Where the status file is written (``STATUS_REPORT_FILE`` or default)."""
    return (os.getenv(STATUS_FILE_ENV) or "").strip() or DEFAULT_STATUS_FILE


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _istanbul_label(moment: datetime) -> str:
    """``30.07.2026 10:04`` — the time the user actually thinks in."""
    return moment.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M")


def _conclusion(counts: Dict[str, int]) -> str:
    """One machine-readable word for how the run went.

    ``ok`` (nothing failed, something ran), ``partial`` (mixed), ``failed``
    (everything that ran, failed) or ``idle`` (nothing was configured at all).
    """
    if counts[STATUS_FAILED] == 0:
        return STATUS_OK if counts[STATUS_OK] > 0 else "idle"
    return "partial" if counts[STATUS_OK] > 0 else STATUS_FAILED


def _read_existing(path: str) -> Dict[str, Any]:
    """Load the previous status file. A missing/corrupt file is just ``{}``."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("mevcut durum dosyası okunamadı (%s): %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _previous_history(existing: Dict[str, Any]) -> List[dict]:
    history = existing.get("history")
    if not isinstance(history, list):
        return []
    return [entry for entry in history if isinstance(entry, dict)]


def _accountability_snapshot() -> Dict[str, Any]:
    """Streak + today's task count from the coach's state file, if present."""
    snapshot: Dict[str, Any] = {
        "available": False,
        "streak": 0,
        "today_task_count": 0,
        "last_date": "",
    }
    try:
        from .advisors.accountability_coach import DEFAULT_STATE_FILE

        path = (os.getenv("ACCOUNTABILITY_STATE_FILE") or "").strip() or DEFAULT_STATE_FILE
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return snapshot
        snapshot["available"] = True
        snapshot["streak"] = int(data.get("streak") or 0)
        snapshot["last_date"] = str(data.get("last_date") or "")
        snapshot["today_task_count"] = len(data.get("last_tasks") or [])
    except Exception:
        # No state yet is the normal day-one case, not an error.
        return snapshot
    return snapshot


def _batch_snapshot() -> Dict[str, Any]:
    """What the single shared LLM call did, plus the model that served it."""
    info: Dict[str, Any] = {
        "enabled": True,
        "attempted": False,
        "used": False,
        "sections_requested": 0,
        "sections_produced": 0,
        "model": "",
        "provider": "",
    }
    try:
        from .advisors import _batch
        from .integrations import llm

        info.update(_batch.last_outcome().to_dict())
        info["model"] = llm.last_model() or ""
        info["provider"] = llm.configured_provider() or ""
    except Exception as exc:  # pragma: no cover - defensive only
        logger.warning("toplu çağrı bilgisi okunamadı: %s", exc)
    return info


def _tokens_snapshot() -> Dict[str, Any]:
    """What the batched call cost, in tokens — counters only, never a secret.

    The full history lives in ``metrics.json`` (see :mod:`ai_assistant.metrics`);
    this is the one-line version the dashboard's health header shows without
    having to load the whole history.
    """
    info: Dict[str, Any] = {
        "called": False,
        "prompt": 0,
        "output": 0,
        "thoughts": 0,
        "total": 0,
        "latency_seconds": 0.0,
        "retries": 0,
        "fallback_used": False,
    }
    try:
        from .integrations import llm

        stats = llm.last_call_stats()
        if stats is None:
            return info
        info.update(
            {
                "called": True,
                "prompt": int(stats.prompt_tokens),
                "output": int(stats.output_tokens),
                "thoughts": int(stats.thoughts_tokens),
                "total": int(stats.total_tokens),
                "latency_seconds": round(float(stats.latency_seconds), 2),
                "retries": int(stats.retries),
                "fallback_used": bool(stats.fallback_used),
            }
        )
    except Exception as exc:  # pragma: no cover - defensive only
        logger.warning("token bilgisi okunamadı: %s", exc)
    return info


def _advisor_entry(briefing: Any) -> Dict[str, Any]:
    key = str(getattr(briefing, "key", "") or "unknown")
    status = str(getattr(briefing, "status", "") or STATUS_SKIPPED)
    text = getattr(briefing, "text", "") or ""
    meta = ADVISOR_META.get(key, DEFAULT_META)
    new_findings = getattr(briefing, "new_findings", None)
    return {
        "id": key,
        "name": str(getattr(briefing, "title", "") or key),
        "status": status,
        # Content itself is NEVER written — only how much of it there was.
        "content_length": len(text) if status == STATUS_OK else 0,
        # For ok advisors there is no reason to report; for the others the
        # short (sanitised) diagnostic IS the useful part.
        "detail": "" if status == STATUS_OK else sanitize(text),
        "emoji": meta["emoji"],
        "category": meta["category"],
        # How much of this section was genuinely NEW (null for advisors that
        # have no notion of new findings), and whether the advisor deliberately
        # stayed quiet on an incremental run.
        "new_findings": int(new_findings) if new_findings is not None else None,
        "nothing_new": bool(getattr(briefing, "nothing_new", False)),
    }


# --- the report -------------------------------------------------------------


def build_status(
    supervision: Any,
    slack_result: Any = None,
    duration_seconds: Optional[float] = None,
    previous_history: Optional[List[dict]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Assemble the full status document for one completed run.

    Args:
        supervision: The :class:`~ai_assistant.operations_manager.Supervision`
            produced by the run (anything exposing ``briefings`` + ``counts``).
        slack_result: The notifier's ``CheckResult``, or ``None`` when delivery
            was not attempted at all.
        duration_seconds: Wall-clock length of the run.
        previous_history: Earlier run summaries to extend (oldest first).
        now: Injectable clock, for tests.
    """
    moment = now or _now_utc()
    briefings = list(getattr(supervision, "briefings", []) or [])
    counts = dict(getattr(supervision, "counts", {}) or {})
    for status in (STATUS_OK, STATUS_FAILED, STATUS_SKIPPED):
        counts.setdefault(status, 0)

    advisors = [_advisor_entry(b) for b in briefings]
    conclusion = _conclusion(counts)
    duration = round(float(duration_seconds), 1) if duration_seconds is not None else None
    batch = _batch_snapshot()
    tokens = _tokens_snapshot()

    # How this run was asked to work, and how much of it was actually new.
    mode = str(getattr(supervision, "mode", MODE_FULL) or MODE_FULL)
    new_findings = sum(
        entry["new_findings"] or 0 for entry in advisors
    )
    quiet = sum(1 for entry in advisors if entry["nothing_new"])

    if slack_result is None:
        slack = {"status": STATUS_SKIPPED, "detail": "gönderim denenmedi"}
    else:
        slack = {
            "status": str(getattr(slack_result, "status", STATUS_SKIPPED)),
            "detail": sanitize(getattr(slack_result, "detail", "")),
        }

    run_summary = {
        "at": moment.isoformat(timespec="seconds"),
        "at_istanbul": _istanbul_label(moment),
        "conclusion": conclusion,
        "ok": counts[STATUS_OK],
        "failed": counts[STATUS_FAILED],
        "skipped": counts[STATUS_SKIPPED],
        "total": len(advisors),
        "duration_seconds": duration,
        "slack": slack["status"],
        "mode": mode,
        "new_findings": new_findings,
        "total_tokens": tokens["total"],
    }

    history = list(previous_history or [])
    history.append(run_summary)
    history = history[-HISTORY_LIMIT:]

    return {
        "schema_version": 1,
        "generated_at": moment.isoformat(timespec="seconds"),
        "generated_at_istanbul": _istanbul_label(moment),
        "run": {
            "conclusion": conclusion,
            "total": len(advisors),
            "ok": counts[STATUS_OK],
            "failed": counts[STATUS_FAILED],
            "skipped": counts[STATUS_SKIPPED],
            "duration_seconds": duration,
            "batch": batch,
            "tokens": tokens,
            # Run mode + how much of it was genuinely new, so the dashboard can
            # tell the flagship 10:00 briefing apart from a quiet top-up run.
            "mode": mode,
            "mode_label": mode_label(mode),
            "new_findings": new_findings,
            "nothing_new_count": quiet,
        },
        "slack": slack,
        "advisors": advisors,
        "accountability": _accountability_snapshot(),
        "history": history,
    }


def write_status_report(
    supervision: Any,
    slack_result: Any = None,
    duration_seconds: Optional[float] = None,
    path: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Write the status file, preserving history. Returns the path or ``None``.

    NEVER raises: an unwritable path, a full disk or a malformed previous file
    all end as a warning in the log and a ``None`` return, because the daily
    briefing must go out either way.
    """
    target = path or status_file_path()
    try:
        existing = _read_existing(target)
        document = build_status(
            supervision,
            slack_result=slack_result,
            duration_seconds=duration_seconds,
            previous_history=_previous_history(existing),
            now=now,
        )
        directory = os.path.dirname(target)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        return target
    except Exception as exc:
        logger.warning("durum raporu yazılamadı (%s): %s", target, exc)
        return None


__all__ = [
    "ADVISOR_META",
    "HISTORY_LIMIT",
    "build_status",
    "sanitize",
    "status_file_path",
    "write_status_report",
]
