"""Run metrics — what every briefing COSTS, and how to spend less.

The assistant runs four times a day on a free LLM tier. Until now nothing
recorded what those runs consumed, so the only honest answer to "why did the
quota run out?" was a shrug. This module keeps a small rolling history of the
last :data:`HISTORY_LIMIT` runs — tokens, latency, retries, fallbacks, how much
text came out — and turns that history into concrete, *data-driven* Turkish
recommendations (:func:`recommendations`).

Where it is written is controlled by ``METRICS_FILE`` (default
``frontend/metrics.json``) so the file lands next to the dashboard and is served
from the same origin, exactly like ``status.json``.

PER-ADVISOR ATTRIBUTION IS AN ESTIMATE — read this before trusting a number
--------------------------------------------------------------------------
The whole team is served by ONE batched model call (see
:mod:`ai_assistant.advisors._batch`), and the provider reports tokens for the
CALL, not per section. There is no per-advisor ground truth to be had, so the
one number is split two ways:

* **input** tokens in proportion to how many characters of PROMPT that advisor
  contributed to the batch (recorded by ``BatchOutcome.prompt_chars``);
* **output** tokens in proportion to how many characters of TEXT that advisor
  produced.

That is deliberately not a single proportional split: an advisor with a huge
persona prompt and a short answer looks *cheap* under a characters-produced
split and *expensive* under this one — and the expensive reading is the true
one. The split is exact in aggregate (the shares sum to the real total) and
approximate per advisor: tokenisation is not linear in characters, and the
shared prompt boilerplate is spread proportionally rather than billed to
anyone. Every number derived from it is labelled ``tahmini`` (estimated) in the
UI. It is an accurate enough compass to answer "which agent should I trim
first?", which is the only question it exists to answer.

TWO HARD RULES, because the repository is PUBLIC:

1. **No content, ever.** Only counts and character totals — never a prompt,
   never an answer.
2. **No secrets, ever.** Nothing here reads a credential; the only strings
   written are advisor ids, Turkish labels and PUBLIC model names.

And one operational rule, shared with the status file: recording metrics must
NEVER break a run. Every error is logged and swallowed — a measurement is worth
strictly less than the thing it measures.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from .config import MODE_FULL, MODE_INCREMENTAL, mode_label
from .integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from .status_report import _istanbul_label

logger = logging.getLogger(__name__)

METRICS_FILE_ENV = "METRICS_FILE"
DEFAULT_METRICS_FILE = "frontend/metrics.json"

#: How many past runs are kept. Four runs a day means roughly a fortnight of
#: history, which is enough to see a trend and small enough to commit daily.
HISTORY_LIMIT = 60

SCHEMA_VERSION = 1

#: How many recent runs the recommendations look at.
WINDOW = 7

#: An advisor is called out as expensive when its estimated share of the tokens
#: exceeds its share of the produced text by at least this many points.
EFFICIENCY_GAP_POINTS = 8.0

#: …and only when it is actually big enough for trimming it to matter.
MIN_TOKEN_SHARE = 10.0


# --- configuration ----------------------------------------------------------


def metrics_file_path() -> str:
    """Where the metrics history is written (``METRICS_FILE`` or the default)."""
    return (os.getenv(METRICS_FILE_ENV) or "").strip() or DEFAULT_METRICS_FILE


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# --- small maths ------------------------------------------------------------


def _num(value: Any) -> float:
    """Coerce anything to a finite, non-negative float. Never raises."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return 0.0
    return number if number > 0 else 0.0


def _share(part: Any, whole: Any) -> float:
    """``part`` as a percentage of ``whole``, rounded to one decimal."""
    total = _num(whole)
    if total <= 0:
        return 0.0
    return round(_num(part) / total * 100.0, 1)


def _pct(value: float) -> str:
    """Turkish percentage label: ``%38,5`` (comma decimal, no trailing zero)."""
    rounded = round(_num(value), 1)
    if rounded == int(rounded):
        return f"%{int(rounded)}"
    return ("%" + f"{rounded:.1f}").replace(".", ",")


def chars_per_1k_tokens(characters: Any, total_tokens: Any) -> float:
    """The headline EFFICIENCY metric: text produced per 1000 tokens spent.

    Higher is better. It answers "am I getting more report for the same quota?"
    in one number, and it is comparable across runs of different sizes.
    """
    tokens = _num(total_tokens)
    if tokens <= 0:
        return 0.0
    return round(_num(characters) / (tokens / 1000.0), 1)


def tokens_per_section(total_tokens: Any, sections: Any) -> float:
    """Average token cost of ONE produced section. Lower is better."""
    count = _num(sections)
    if count <= 0:
        return 0.0
    return round(_num(total_tokens) / count, 1)


# --- per-advisor attribution ------------------------------------------------


def attribute_tokens(
    produced_chars: Dict[str, int],
    prompt_chars: Dict[str, int],
    prompt_tokens: Any,
    output_tokens: Any,
) -> List[Dict[str, Any]]:
    """Split ONE batched call's tokens across the advisors. See module docstring.

    Input tokens follow each advisor's share of the PROMPT characters, output
    tokens follow its share of the PRODUCED characters. Advisors that appear in
    either map are included, so an advisor that was asked for a section but
    produced nothing still shows its input cost — which is exactly the case
    worth spotting.

    Returns one dict per advisor, sorted by estimated total tokens (most
    expensive first). Always an ESTIMATE; never raises.
    """
    produced = {str(k): int(_num(v)) for k, v in (produced_chars or {}).items()}
    prompts = {str(k): int(_num(v)) for k, v in (prompt_chars or {}).items()}

    produced_total = sum(produced.values())
    prompt_total = sum(prompts.values())
    prompt_budget = _num(prompt_tokens)
    output_budget = _num(output_tokens)
    grand_total = prompt_budget + output_budget

    rows: List[Dict[str, Any]] = []
    for key in sorted(set(produced) | set(prompts)):
        own_prompt = prompts.get(key, 0)
        own_output = produced.get(key, 0)
        est_prompt = (
            prompt_budget * own_prompt / prompt_total if prompt_total > 0 else 0.0
        )
        est_output = (
            output_budget * own_output / produced_total if produced_total > 0 else 0.0
        )
        est_total = est_prompt + est_output
        rows.append(
            {
                "id": key,
                "prompt_chars": own_prompt,
                "output_chars": own_output,
                "est_prompt_tokens": int(round(est_prompt)),
                "est_output_tokens": int(round(est_output)),
                "est_total_tokens": int(round(est_total)),
                # The two shares whose DIVERGENCE is the whole point: how much
                # of the spend versus how much of the result.
                "token_share": _share(est_total, grand_total),
                "output_share": _share(own_output, produced_total),
            }
        )
    rows.sort(key=lambda row: row["est_total_tokens"], reverse=True)
    return rows


# --- building one run's record ----------------------------------------------


def _briefing_chars(briefings: Sequence[Any]) -> Dict[str, int]:
    """``{advisor_key: characters produced}`` for the sections that worked."""
    out: Dict[str, int] = {}
    for briefing in briefings:
        if str(getattr(briefing, "status", "")) != STATUS_OK:
            continue
        if getattr(briefing, "nothing_new", False):
            continue
        key = str(getattr(briefing, "key", "") or "unknown")
        out[key] = len(str(getattr(briefing, "text", "") or ""))
    return out


def _advisor_names(briefings: Sequence[Any]) -> Dict[str, str]:
    return {
        str(getattr(b, "key", "") or "unknown"): str(
            getattr(b, "title", "") or getattr(b, "key", "") or "?"
        )
        for b in briefings
    }


def _executed_advisors(supervision: Any) -> List[str]:
    """Keys of the advisors that really ran, in roster order. Never raises."""
    executed = getattr(supervision, "executed_advisors", None) or []
    try:
        return [str(key) for key in executed if key]
    except TypeError:  # pragma: no cover - defensive only
        return []


def _skipped_advisors(supervision: Any) -> Dict[str, str]:
    """``{advisor_key: reason_code}`` for everyone who did not run."""
    skipped = getattr(supervision, "skipped_advisors", None) or {}
    if not isinstance(skipped, dict):
        return {}
    return {str(key): str(reason) for key, reason in skipped.items() if key}


def _llm_call_count(call_stats: Any, override: Any = None) -> int:
    """How many model calls this run made.

    ``call_stats`` describes only the LAST call, so on its own it cannot tell
    ONE batched call for the whole team from fifteen per-advisor retries after
    a failed batch. The real counter lives in the LLM layer; ``override`` wins
    when a caller passes it, and the "did we call at all?" fallback keeps the
    number honest for callers that predate the counter.
    """
    if override is not None:
        return int(_num(override))
    try:
        from .integrations import llm

        counted = int(llm.call_count())
    except Exception:  # pragma: no cover - defensive only
        counted = 0
    if counted:
        return counted
    return 1 if call_stats is not None else 0


def build_run_metrics(
    supervision: Any,
    call_stats: Any = None,
    batch: Any = None,
    duration_seconds: Optional[float] = None,
    now: Optional[datetime] = None,
    llm_call_count: Optional[int] = None,
) -> Dict[str, Any]:
    """Assemble the metrics record for ONE completed run.

    Args:
        supervision: The run's ``Supervision`` (anything with ``briefings`` and
            ``counts``).
        call_stats: The :class:`~ai_assistant.integrations.llm.CallStats` of the
            batched generation, or ``None`` when no model was called at all
            (empty ``.env``, or a quiet incremental run).
        batch: The ``BatchOutcome``, which carries the per-advisor prompt sizes.
        duration_seconds: Wall clock of the whole run.
        now: Injectable clock, for tests.
        llm_call_count: How many model calls the run made; read from the LLM
            layer when omitted.
    """
    moment = now or _now_utc()
    briefings = list(getattr(supervision, "briefings", []) or [])
    counts = dict(getattr(supervision, "counts", {}) or {})
    for status in (STATUS_OK, STATUS_FAILED, STATUS_SKIPPED):
        counts.setdefault(status, 0)

    prompt_tokens = _num(getattr(call_stats, "prompt_tokens", 0))
    output_tokens = _num(getattr(call_stats, "output_tokens", 0))
    thoughts_tokens = _num(getattr(call_stats, "thoughts_tokens", 0))
    total_tokens = _num(getattr(call_stats, "total_tokens", 0)) or (
        prompt_tokens + output_tokens + thoughts_tokens
    )

    produced = _briefing_chars(briefings)
    names = _advisor_names(briefings)
    characters = sum(produced.values())
    sections = len(produced)

    prompt_chars = dict(getattr(batch, "prompt_chars", {}) or {})
    agents = attribute_tokens(produced, prompt_chars, prompt_tokens, output_tokens)
    for row in agents:
        row["name"] = names.get(row["id"], row["id"])

    mode = str(getattr(supervision, "mode", MODE_FULL) or MODE_FULL)

    return {
        "at": moment.isoformat(timespec="seconds"),
        "at_istanbul": _istanbul_label(moment),
        "mode": mode,
        "mode_label": mode_label(mode),
        "provider": str(getattr(call_stats, "provider", "") or ""),
        "model": str(getattr(call_stats, "model", "") or ""),
        "llm_called": call_stats is not None,
        "llm_ok": bool(getattr(call_stats, "ok", False)),
        # THE cost driver: one batched call, or one per advisor? A run whose
        # token count doubled without this number is unexplainable.
        "llm_call_count": _llm_call_count(call_stats, llm_call_count),
        # --- tokens ---
        "prompt_tokens": int(prompt_tokens),
        "output_tokens": int(output_tokens),
        "thoughts_tokens": int(thoughts_tokens),
        "total_tokens": int(total_tokens),
        # --- timing & resilience ---
        "latency_seconds": round(_num(getattr(call_stats, "latency_seconds", 0)), 2),
        "duration_seconds": (
            round(_num(duration_seconds), 1) if duration_seconds is not None else None
        ),
        "retries": int(_num(getattr(call_stats, "retries", 0))),
        "fallback_used": bool(getattr(call_stats, "fallback_used", False)),
        "models_tried": int(_num(getattr(call_stats, "models_tried", 0))),
        # --- what came out ---
        "advisors_ok": int(counts[STATUS_OK]),
        "advisors_failed": int(counts[STATUS_FAILED]),
        "advisors_skipped": int(counts[STATUS_SKIPPED]),
        # WHO worked and WHY the others did not. A run that suddenly costs a
        # tenth of yesterday's tokens is either the gates doing their job or a
        # silent outage, and only the reason codes tell the two apart (see the
        # ``SKIP_*`` constants in :mod:`ai_assistant.operations_manager`).
        "executed_advisors": _executed_advisors(supervision),
        "skipped_advisors": _skipped_advisors(supervision),
        "sections": sections,
        "sections_requested": int(_num(getattr(batch, "sections_requested", 0))),
        "characters": characters,
        "prompt_chars_total": int(_num(getattr(batch, "prompt_chars_total", 0))),
        "guide_saved_chars": int(_num(getattr(batch, "guide_saved_chars", 0))),
        # --- derived efficiency ---
        "chars_per_1k_tokens": chars_per_1k_tokens(characters, total_tokens),
        "tokens_per_section": tokens_per_section(total_tokens, sections),
        "thoughts_share": _share(thoughts_tokens, total_tokens),
        "prompt_share": _share(prompt_tokens, total_tokens),
        # Per-agent estimated cost. See the module docstring: this is a
        # proportional attribution of ONE batched call, not a measurement.
        "agents": agents,
        "attribution": "estimate",
    }


# --- the rolling history ----------------------------------------------------


def _read_existing(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("mevcut metrik dosyası okunamadı (%s): %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def previous_runs(existing: Dict[str, Any]) -> List[dict]:
    """The run records already on file (oldest first), ignoring junk entries."""
    runs = existing.get("runs")
    if not isinstance(runs, list):
        return []
    return [entry for entry in runs if isinstance(entry, dict)]


def prune(runs: Sequence[dict], limit: int = HISTORY_LIMIT) -> List[dict]:
    """Keep the newest ``limit`` runs. ``limit <= 0`` keeps everything."""
    kept = list(runs)
    if limit <= 0:
        return kept
    return kept[-limit:]


def build_document(
    runs: Sequence[dict], now: Optional[datetime] = None
) -> Dict[str, Any]:
    """Wrap a run history in the document the dashboard reads."""
    moment = now or _now_utc()
    history = prune(runs)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": moment.isoformat(timespec="seconds"),
        "generated_at_istanbul": _istanbul_label(moment),
        "history_limit": HISTORY_LIMIT,
        "attribution_note": (
            "Ajan başına token değerleri TAHMİNDİR: ekip tek bir toplu model "
            "çağrısıyla çalışır, sağlayıcı tokenları çağrı başına raporlar. "
            "Girdi tokenları her ajanın prompt uzunluğuna, çıktı tokenları "
            "ürettiği metin uzunluğuna göre paylaştırılır."
        ),
        "totals": totals(history),
        "recommendations": recommendations(history),
        "runs": history,
    }


def totals(runs: Sequence[dict]) -> Dict[str, Any]:
    """Aggregate headline numbers over the whole retained history."""
    scored = [r for r in runs if _num(r.get("total_tokens")) > 0]
    total_tokens = sum(_num(r.get("total_tokens")) for r in scored)
    characters = sum(_num(r.get("characters")) for r in scored)
    sections = sum(_num(r.get("sections")) for r in scored)
    latencies = [_num(r.get("latency_seconds")) for r in scored]
    return {
        "runs": len(runs),
        "runs_with_llm": len(scored),
        "total_tokens": int(total_tokens),
        "prompt_tokens": int(sum(_num(r.get("prompt_tokens")) for r in scored)),
        "output_tokens": int(sum(_num(r.get("output_tokens")) for r in scored)),
        "thoughts_tokens": int(sum(_num(r.get("thoughts_tokens")) for r in scored)),
        "characters": int(characters),
        "sections": int(sections),
        "avg_tokens_per_run": int(total_tokens / len(scored)) if scored else 0,
        "avg_latency_seconds": (
            round(sum(latencies) / len(latencies), 1) if latencies else 0.0
        ),
        "chars_per_1k_tokens": chars_per_1k_tokens(characters, total_tokens),
        "tokens_per_section": tokens_per_section(total_tokens, sections),
        "fallback_runs": sum(1 for r in scored if r.get("fallback_used")),
        "retry_total": int(sum(_num(r.get("retries")) for r in scored)),
        "guide_saved_chars": int(sum(_num(r.get("guide_saved_chars")) for r in runs)),
    }


def record_run(
    supervision: Any,
    call_stats: Any = None,
    batch: Any = None,
    duration_seconds: Optional[float] = None,
    path: Optional[str] = None,
    now: Optional[datetime] = None,
    llm_call_count: Optional[int] = None,
) -> Optional[str]:
    """Append this run to the metrics history. Returns the path, or ``None``.

    NEVER raises. An unwritable path, a full disk or a corrupt previous file all
    end as a warning in the log: the briefing must go out either way.
    """
    target = path or metrics_file_path()
    try:
        existing = _read_existing(target)
        runs = previous_runs(existing)
        runs.append(
            build_run_metrics(
                supervision,
                call_stats=call_stats,
                batch=batch,
                duration_seconds=duration_seconds,
                now=now,
                llm_call_count=llm_call_count,
            )
        )
        document = build_document(runs, now=now)
        directory = os.path.dirname(target)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        return target
    except Exception as exc:
        logger.warning("metrik dosyası yazılamadı (%s): %s", target, exc)
        return None


def load_history(path: Optional[str] = None) -> List[dict]:
    """Read the recorded runs back. An unreadable file is an empty history."""
    return previous_runs(_read_existing(path or metrics_file_path()))


# --- the optimization advisor -----------------------------------------------
#
# EVERY recommendation below is computed from the recorded numbers and quotes
# them. Nothing is templated advice: if the data does not support a suggestion,
# the suggestion is not emitted at all. That is the difference between "prompt'u
# kısaltabilirsin" (noise) and "bu ajan çıktının %31'ini üretiyor ama token'ın
# %48'ini harcıyor" (actionable).

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_GOOD = "good"


def _tip(
    severity: str, title: str, detail: str, metric: str = "", advisor: str = ""
) -> Dict[str, str]:
    return {
        "severity": severity,
        "title": title,
        "detail": detail,
        "metric": metric,
        "advisor": advisor,
    }


def _aggregate_agents(runs: Sequence[dict]) -> List[Dict[str, Any]]:
    """Sum the per-run agent estimates into one table over the window."""
    bucket: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        for row in run.get("agents") or []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("id") or "")
            if not key:
                continue
            entry = bucket.setdefault(
                key,
                {
                    "id": key,
                    "name": str(row.get("name") or key),
                    "tokens": 0,
                    "chars": 0,
                },
            )
            entry["tokens"] += _num(row.get("est_total_tokens"))
            entry["chars"] += _num(row.get("output_chars"))
            if row.get("name"):
                entry["name"] = str(row["name"])

    rows = list(bucket.values())
    token_total = sum(r["tokens"] for r in rows)
    char_total = sum(r["chars"] for r in rows)
    for row in rows:
        row["token_share"] = _share(row["tokens"], token_total)
        row["output_share"] = _share(row["chars"], char_total)
        row["gap"] = round(row["token_share"] - row["output_share"], 1)
        row["tokens"] = int(row["tokens"])
        row["chars"] = int(row["chars"])
    rows.sort(key=lambda row: row["gap"], reverse=True)
    return rows


def _efficiency_tips(runs: Sequence[dict]) -> List[Dict[str, str]]:
    """ "This agent costs more than it delivers" — the headline finding."""
    tips: List[Dict[str, str]] = []
    for row in _aggregate_agents(runs)[:3]:
        if row["gap"] < EFFICIENCY_GAP_POINTS or row["token_share"] < MIN_TOKEN_SHARE:
            continue
        tips.append(
            _tip(
                SEVERITY_WARN,
                f"{row['name']} beklenenden pahalı",
                f"Son {len(runs)} çalıştırmada bu ajan üretilen metnin "
                f"{_pct(row['output_share'])}'ini üretiyor ama tahmini token'ın "
                f"{_pct(row['token_share'])}'ini harcıyor "
                f"({row['gap']:+.1f} puan fark). Persona ve görev metnini "
                "kısaltmak, aynı çıktıyı daha az girdi tokenıyla verir.",
                metric=f"{int(row['tokens'])} tahmini token",
                advisor=row["id"],
            )
        )
    return tips


def _fallback_tips(runs: Sequence[dict]) -> List[Dict[str, str]]:
    scored = [r for r in runs if r.get("llm_called")]
    if not scored:
        return []
    tips: List[Dict[str, str]] = []
    fell_back = sum(1 for r in scored if r.get("fallback_used"))
    if fell_back:
        tips.append(
            _tip(
                SEVERITY_WARN if fell_back > len(scored) / 2 else SEVERITY_INFO,
                "Yedek modele düşülüyor",
                f"Son {len(scored)} çalıştırmanın {fell_back} tanesinde birincil "
                "model yanıt veremedi ve zincirdeki yedek model devreye girdi. "
                "Bu genellikle kota/yoğunluk demektir: çalıştırma saatlerini "
                "birbirinden uzaklaştırmak veya birincil modeli doğrudan daha "
                "hafif bir modelle değiştirmek bekleme süresini kısaltır.",
                metric=f"{fell_back}/{len(scored)} çalıştırma",
            )
        )
    retries = int(sum(_num(r.get("retries")) for r in scored))
    if retries:
        tips.append(
            _tip(
                SEVERITY_WARN if retries >= len(scored) * 2 else SEVERITY_INFO,
                "Yeniden deneme maliyeti",
                f"Son {len(scored)} çalıştırmada toplam {retries} kez istek "
                "tekrarlandı (429/5xx). Her tekrar bekleme süresidir, token "
                "değil — ama brifingi geciktirir. Tekrarlar sürüyorsa "
                "GEMINI_REQUEST_SPACING_SECONDS değerini artırmak yardımcı olur.",
                metric=f"{retries} tekrar",
            )
        )
    return tips


def _incremental_tips(runs: Sequence[dict]) -> List[Dict[str, str]]:
    """Is the cheap top-up run actually cheap?"""
    incremental = [
        r
        for r in runs
        if r.get("mode") == MODE_INCREMENTAL and _num(r.get("total_tokens")) > 0
    ]
    full = [
        r
        for r in runs
        if r.get("mode") == MODE_FULL and _num(r.get("total_tokens")) > 0
    ]
    if not incremental:
        return []

    avg_sections = sum(_num(r.get("sections")) for r in incremental) / len(incremental)
    avg_prompt = sum(_num(r.get("prompt_tokens")) for r in incremental) / len(
        incremental
    )
    tips: List[Dict[str, str]] = []

    if full:
        full_prompt = sum(_num(r.get("prompt_tokens")) for r in full) / len(full)
        # A top-up that costs nearly as much INPUT as the flagship briefing is
        # sending a full prompt to ask a small question.
        if full_prompt > 0 and avg_prompt > full_prompt * 0.6:
            tips.append(
                _tip(
                    SEVERITY_WARN,
                    "Artımlı çalıştırma tam brifing kadar girdi gönderiyor",
                    f"Artımlı modda ortalama {avg_sections:.1f} bölüm üretiliyor "
                    f"ama ortalama {int(avg_prompt)} girdi tokenı gönderiliyor — "
                    f"tam brifingin ({int(full_prompt)}) "
                    f"{_pct(avg_prompt / full_prompt * 100)}'i kadar. Artımlı "
                    "prompt daha da kısaltılabilir: yalnızca yeni bulgusu olan "
                    "bölümler ve kısa yazım kuralları gönderilmeli.",
                    metric=f"{int(avg_prompt)} vs {int(full_prompt)} girdi tokenı",
                )
            )
        elif avg_prompt > 0 and full_prompt > 0:
            tips.append(
                _tip(
                    SEVERITY_GOOD,
                    "Artımlı çalıştırma ucuz kalıyor",
                    f"Artımlı çalıştırmalar ortalama {int(avg_prompt)} girdi "
                    f"tokenı harcıyor; tam brifingin ({int(full_prompt)}) "
                    f"{_pct(avg_prompt / full_prompt * 100)}'i kadar. Kısa mod "
                    "çalışıyor.",
                    metric=f"{avg_sections:.1f} bölüm/çalıştırma",
                )
            )
    return tips


def _token_mix_tips(runs: Sequence[dict]) -> List[Dict[str, str]]:
    scored = [r for r in runs if _num(r.get("total_tokens")) > 0]
    if not scored:
        return []
    prompt = sum(_num(r.get("prompt_tokens")) for r in scored)
    output = sum(_num(r.get("output_tokens")) for r in scored)
    thoughts = sum(_num(r.get("thoughts_tokens")) for r in scored)
    total = sum(_num(r.get("total_tokens")) for r in scored)
    tips: List[Dict[str, str]] = []

    if thoughts > 0:
        share = _share(thoughts, total)
        tips.append(
            _tip(
                SEVERITY_WARN if share >= 35 else SEVERITY_INFO,
                "Düşünme (thinking) tokenı oranı",
                f"Toplam token'ın {_pct(share)}'i modelin görünmeyen iç "
                f"akıl yürütmesine gidiyor ({int(thoughts)} token). Bu kısım "
                "brifingde hiç görünmez. Oran yüksekse daha hafif bir model ya "
                "da daha net/kısa bir görev tanımı doğrudan tasarruf sağlar.",
                metric=_pct(share),
            )
        )

    if prompt > output and output > 0:
        # Averages per run, not window sums: "her çalıştırmada 14000 token
        # gönderiyorsun" is actionable, a rolling total is just a big number.
        avg_prompt = int(prompt / len(scored))
        avg_output = int(output / len(scored))
        tips.append(
            _tip(
                SEVERITY_WARN,
                "Girdi, çıktıdan pahalı",
                f"Çalıştırma başına ortalama {avg_prompt} token prompt "
                f"gönderiliyor, {avg_output} token yanıt alınıyor — girdi "
                f"toplamın {_pct(_share(prompt, total))}'i. Yani kotanın çoğu "
                "soru sormaya gidiyor, cevap almaya değil. Persona metinlerini "
                "kısaltmak buradan kazandırır.",
                metric=f"{avg_prompt} / {avg_output} token",
            )
        )
    return tips


def _saving_tips(runs: Sequence[dict]) -> List[Dict[str, str]]:
    """Report the savings already banked, so a win is visible and kept."""
    saved = sum(_num(r.get("guide_saved_chars")) for r in runs)
    if saved <= 0:
        return []
    # Turkish thousands separator is a dot, so the grouping comma is swapped on
    # the NUMBER alone — doing it on the whole sentence would eat its commas.
    pretty = f"{int(saved):,}".replace(",", ".")
    return [
        _tip(
            SEVERITY_GOOD,
            "Ortak yazım kuralları tek sefer gönderiliyor",
            f"Son {len(runs)} çalıştırmada, aynı yazım kılavuzunu her bölümde "
            f"tekrarlamak yerine bir kez göndererek yaklaşık {pretty} karakter "
            "(kabaca dört karakter = bir token) girdi tasarruf edildi.",
            metric=f"~{int(saved / 4)} token",
        )
    ]


def _efficiency_trend_tips(runs: Sequence[dict]) -> List[Dict[str, str]]:
    scored = [r for r in runs if _num(r.get("chars_per_1k_tokens")) > 0]
    if len(scored) < 4:
        return []
    half = len(scored) // 2
    older = scored[:half]
    newer = scored[half:]
    before = sum(_num(r.get("chars_per_1k_tokens")) for r in older) / len(older)
    after = sum(_num(r.get("chars_per_1k_tokens")) for r in newer) / len(newer)
    if before <= 0:
        return []
    delta = (after - before) / before * 100.0
    if abs(delta) < 10:
        return []
    improving = delta > 0
    return [
        _tip(
            SEVERITY_GOOD if improving else SEVERITY_WARN,
            "Verimlilik " + ("iyileşiyor" if improving else "geriliyor"),
            f"1000 token başına üretilen metin {int(before)} karakterden "
            f"{int(after)} karaktere "
            + ("çıktı" if improving else "düştü")
            + f" ({delta:+.0f}%). "
            + (
                "Aynı kotadan daha fazla brifing alıyorsun."
                if improving
                else "Aynı kota daha az metin üretiyor — promptlar büyümüş ya da "
                "yanıtlar kısalmış olabilir."
            ),
            metric=f"{int(after)} karakter/1K token",
        )
    ]


def recommendations(runs: Sequence[dict], window: int = WINDOW) -> List[Dict[str, str]]:
    """Turn the recorded history into concrete Turkish optimisation advice.

    Looks at the last ``window`` runs. Every sentence quotes a number that came
    out of the history — there are no generic tips, and an empty history yields
    an empty list rather than invented advice.

    Never raises: a malformed record can cost a recommendation, never a run.
    """
    try:
        recent = [r for r in (runs or []) if isinstance(r, dict)][-max(1, window) :]
        if not recent:
            return []
        tips: List[Dict[str, str]] = []
        tips.extend(_efficiency_tips(recent))
        tips.extend(_token_mix_tips(recent))
        tips.extend(_incremental_tips(recent))
        tips.extend(_fallback_tips(recent))
        tips.extend(_efficiency_trend_tips(recent))
        tips.extend(_saving_tips(recent))
        return tips
    except Exception as exc:  # pragma: no cover - defensive only
        logger.warning("optimizasyon önerileri üretilemedi: %s", exc)
        return []


__all__ = [
    "DEFAULT_METRICS_FILE",
    "HISTORY_LIMIT",
    "METRICS_FILE_ENV",
    "WINDOW",
    "attribute_tokens",
    "build_document",
    "build_run_metrics",
    "chars_per_1k_tokens",
    "load_history",
    "metrics_file_path",
    "previous_runs",
    "prune",
    "recommendations",
    "record_run",
    "tokens_per_section",
    "totals",
]
