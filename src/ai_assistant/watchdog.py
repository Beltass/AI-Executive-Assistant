"""Teknik Nöbetçi — the ops watchdog that keeps the assistant running.

The advisor team writes the briefing. NOBODY was watching the machine that
writes it. A cron that silently stops firing, a quota that runs dry at 03:00, a
Slack webhook that starts returning 403, a state commit that loses a race and
takes the streak with it — all of those look exactly like "a quiet day" from the
outside, and the user only finds out when a briefing they were relying on never
arrives.

This module is the on-call engineer for that machine. It reads the artefacts the
run leaves behind — ``frontend/status.json``, ``frontend/metrics.json``,
``.assistant_state/`` and the report archive — runs a fixed list of TECHNICAL
checks over them, classifies each one, and writes a verdict to
``frontend/health.json`` for the dashboard.

WHY IT IS SEPARATE FROM THE ADVISORS
    An advisor produces a briefing and therefore costs a model call. This costs
    NOTHING: no LLM, no paid API, only file reads and (optionally) a cheap HEAD
    request per RSS feed. That is what lets it run every hour instead of four
    times a day, which is what makes it useful — a watchdog that checks as often
    as the thing it watches is not a watchdog.

SEVERITY, and what each one means to the reader
    🟢 ``ok``        working as designed; nothing to do.
    🟡 ``warn``      degraded but delivering; worth a look, not an emergency.
    🔴 ``critical``  the user is NOT getting what they signed up for; act now.

    Every non-green check carries a ``remedy``: one concrete thing to do. A
    diagnosis with no remedy is just anxiety.

ANTI-SPAM
    A Slack alert fires only when the overall state CHANGES (see
    :func:`should_alert`). An hourly job that re-posts "🔴 still broken" twenty
    four times a day trains the reader to ignore it, which is worse than not
    alerting at all. Recovery is announced too, once, because "is it fixed yet?"
    is the second question.

Configuration (via environment):
    HEALTH_FILE            Where the verdict is written (default
                           ``frontend/health.json``).
    WATCHDOG_CHECK_FEEDS   Whether to probe the RSS feeds (default true).
    WATCHDOG_ALERT         Whether a state change posts to Slack (default true).

Run with::

    python -m ai_assistant.watchdog

Exit code is 0 unless the watchdog ITSELF failed — a 🔴 finding is a successful
detection, not a failed job, and failing the job would only add a second, less
informative alarm.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

from .config import setting
from .status_report import ISTANBUL, _istanbul_label, sanitize

logger = logging.getLogger(__name__)

HEALTH_FILE_ENV = "HEALTH_FILE"
DEFAULT_HEALTH_FILE = "frontend/health.json"

SCHEMA_VERSION = 1

SEVERITY_OK = "ok"
SEVERITY_WARN = "warn"
SEVERITY_CRITICAL = "critical"

#: Ordered worst-first, so :func:`overall_severity` is a max over this list.
SEVERITY_RANK = {SEVERITY_OK: 0, SEVERITY_WARN: 1, SEVERITY_CRITICAL: 2}

SEVERITY_ICON = {SEVERITY_OK: "🟢", SEVERITY_WARN: "🟡", SEVERITY_CRITICAL: "🔴"}
SEVERITY_LABEL = {
    SEVERITY_OK: "sağlıklı",
    SEVERITY_WARN: "dikkat",
    SEVERITY_CRITICAL: "müdahale gerek",
}

# --- thresholds -------------------------------------------------------------
#
# Derived from the actual schedule: full at 07:00 UTC, incremental at 11:00,
# 15:00 and 19:00. The longest DESIGNED gap is 19:00 → 07:00 = 12 hours, so
# anything past 14 hours means a run was missed, and past 26 hours means a whole
# day was.

MAX_EXPECTED_GAP_HOURS = 14.0
CRITICAL_GAP_HOURS = 26.0

#: Consecutive bad runs before it stops being bad luck.
FAILURE_STREAK_WARN = 2
FAILURE_STREAK_CRITICAL = 3

#: How many recent runs the trend checks look at.
WINDOW = 8

#: Fallback incidence over the window that means the primary model is unusable.
FALLBACK_WARN_RATIO = 0.4
FALLBACK_CRITICAL_RATIO = 0.8

#: Token growth over the window's median that is worth a word.
TOKEN_GROWTH_WARN = 1.5

#: Per-feed probe timeout. Short: a slow feed is a finding, not a reason to
#: stall the watchdog.
FEED_TIMEOUT_SECONDS = 8.0

#: The feeds the advisors actually depend on, by the setting that names them.
FEED_SETTINGS = (
    ("AI_NEWS_RSS_URL", "Yapay Zeka Haberleri"),
    ("SECTOR_NEWS_RSS_URL", "Sektör İstihbaratı"),
    ("BANKING_NEWS_RSS_URL", "Bankacılık Haberleri"),
    ("CX_RESEARCH_RSS_URL", "Müşteri Deneyimi Araştırması"),
)


# --- the finding ------------------------------------------------------------


@dataclass
class Check:
    """One technical finding.

    Attributes:
        id: Stable identifier, so the dashboard and the alert can match up.
        name: Turkish name shown to the reader.
        severity: ``ok`` / ``warn`` / ``critical``.
        detail: What was observed, with the NUMBER that was observed.
        remedy: The one concrete thing to do about it. Empty when ``ok``.
    """

    id: str
    name: str
    severity: str
    detail: str
    remedy: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "severity": self.severity,
            # Belt and braces: these strings are read out of run artefacts and
            # written to a file in a PUBLIC repository.
            "detail": sanitize(self.detail, limit=0),
            "remedy": sanitize(self.remedy, limit=0),
        }


def _ok(check_id: str, name: str, detail: str) -> Check:
    return Check(id=check_id, name=name, severity=SEVERITY_OK, detail=detail)


def _warn(check_id: str, name: str, detail: str, remedy: str) -> Check:
    return Check(
        id=check_id, name=name, severity=SEVERITY_WARN, detail=detail, remedy=remedy
    )


def _critical(check_id: str, name: str, detail: str, remedy: str) -> Check:
    return Check(
        id=check_id, name=name, severity=SEVERITY_CRITICAL, detail=detail, remedy=remedy
    )


def overall_severity(checks: Sequence[Check]) -> str:
    """The worst severity present. No findings at all is ``ok``."""
    worst = SEVERITY_OK
    for check in checks:
        if SEVERITY_RANK.get(check.severity, 0) > SEVERITY_RANK[worst]:
            worst = check.severity
    return worst


# --- configuration ----------------------------------------------------------


def health_file_path() -> str:
    """Where the verdict is written (``HEALTH_FILE`` or the default)."""
    return (os.getenv(HEALTH_FILE_ENV) or "").strip() or DEFAULT_HEALTH_FILE


_TRUTHY = {"1", "true", "yes", "on", "evet"}
_FALSY = {"0", "false", "no", "off", "hayir", "hayır"}


def _flag(name: str, default: bool = True) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if raw in _FALSY:
        return False
    if raw in _TRUTHY:
        return True
    return default


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("dosya okunamadı (%s): %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _hours_since(iso: str, now: datetime) -> Optional[float]:
    if not iso:
        return None
    try:
        moment = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (now - moment).total_seconds() / 3600.0


def _num(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number else 0.0


# --- the checks -------------------------------------------------------------
#
# Each one takes what it needs and returns exactly one Check. They are pure
# functions of the artefacts, which is what makes them testable without a run.


def check_freshness(status: Dict[str, Any], now: datetime) -> Check:
    """Has a run happened when one was due?

    This is the check that catches the failure mode nothing else can: a cron
    that silently stopped firing looks identical to a quiet day.
    """
    name = "Çalıştırma tazeliği"
    if not status:
        return _critical(
            "freshness",
            name,
            "Hiç durum dosyası yok — brifing bir kez bile tamamlanmamış görünüyor.",
            "Daily Briefing iş akışını elle bir kez çalıştır (workflow_dispatch, "
            "mod: full) ve iş kaydındaki hatayı oku.",
        )

    age = _hours_since(status.get("generated_at", ""), now)
    if age is None:
        return _warn(
            "freshness",
            name,
            "Durum dosyasında okunabilir bir zaman damgası yok.",
            "status.json bozulmuş olabilir; bir sonraki çalıştırma yeniden yazar. "
            "Düzelmezse dosyayı silip iş akışını elle tetikle.",
        )

    stamp = status.get("generated_at_istanbul") or status.get("generated_at")
    if age >= CRITICAL_GAP_HOURS:
        return _critical(
            "freshness",
            name,
            f"Son çalıştırma {age:.0f} saat önce ({stamp}). Bir günden uzun "
            "süredir yeni brifing yok.",
            "GitHub Actions → Daily Briefing sayfasını aç: planlı çalıştırma "
            "devre dışı bırakılmış olabilir (60 gün hareketsiz kalan depolarda "
            "GitHub cron'u kapatır). Elle bir çalıştırma zamanlayıcıyı geri açar.",
        )
    if age >= MAX_EXPECTED_GAP_HOURS:
        return _warn(
            "freshness",
            name,
            f"Son çalıştırma {age:.0f} saat önce ({stamp}); beklenen en uzun ara "
            f"{MAX_EXPECTED_GAP_HOURS:.0f} saat.",
            "Bir planlı çalıştırma atlanmış olabilir. GitHub Actions kuyruğu "
            "yoğunsa kendiliğinden düzelir; iki periyot daha atlarsa elle tetikle.",
        )
    return _ok(
        "freshness",
        name,
        f"Son çalıştırma {age:.1f} saat önce ({stamp}) — planlı aralık içinde.",
    )


def check_last_run(status: Dict[str, Any]) -> Check:
    """Did the most recent run actually produce a briefing?"""
    name = "Son çalıştırma sonucu"
    run = status.get("run") or {}
    conclusion = str(run.get("conclusion") or "")
    ok = int(_num(run.get("ok")))
    failed = int(_num(run.get("failed")))

    if not conclusion:
        return _warn(
            "last_run", name, "Son çalıştırmanın sonucu okunamadı.", "status.json'u kontrol et."
        )
    if conclusion == "failed":
        return _critical(
            "last_run",
            name,
            f"Son çalıştırmada çalışan ajan yok, {failed} ajan hata verdi.",
            "İş kaydındaki ilk hata satırını oku. En sık nedeni dolmuş LLM "
            "kotasıdır; bu durumda bir sonraki kota penceresi sorunu kendiliğinden "
            "çözer, düzelmezse GEMINI_API_KEY'in geçerliliğini doğrula.",
        )
    if failed:
        return _warn(
            "last_run",
            name,
            f"{ok} ajan çalıştı, {failed} ajan hata verdi (kısmi başarı).",
            "Panodaki ajan kartlarında hata nedenini oku; tek bir ajanın hatası "
            "genelde o ajanın beslemesi/anahtarıyla ilgilidir, brifingi durdurmaz.",
        )
    if conclusion == "idle":
        return _warn(
            "last_run",
            name,
            "Son çalıştırmada hiçbir ajan yapılandırılmamış görünüyor (hepsi atlandı).",
            "Depo gizli anahtarlarını kontrol et: GEMINI_API_KEY yoksa tüm "
            "LLM ajanları 'skipped' olur.",
        )
    return _ok("last_run", name, f"{ok} ajan sorunsuz çalıştı, hata yok.")


def check_failure_streak(status: Dict[str, Any]) -> Check:
    """Is this one bad run, or a pattern?

    One failure is weather; three in a row is a broken system, and the two need
    different reactions.
    """
    name = "Ardışık hata"
    history = status.get("history")
    if not isinstance(history, list) or not history:
        return _ok("failure_streak", name, "Değerlendirilecek geçmiş yok.")

    streak = 0
    for entry in reversed(history):
        if not isinstance(entry, dict):
            break
        if str(entry.get("conclusion")) in {"failed", "partial"}:
            streak += 1
        else:
            break

    if streak >= FAILURE_STREAK_CRITICAL:
        return _critical(
            "failure_streak",
            name,
            f"Son {streak} çalıştırmanın hepsi hatalı ya da kısmi bitti.",
            "Tek seferlik bir aksaklık değil. İş kaydında tekrar eden hata "
            "mesajını bul; kota, süresi dolmuş bir anahtar veya kalıcı olarak "
            "erişilemeyen bir servis olma ihtimali yüksek.",
        )
    if streak >= FAILURE_STREAK_WARN:
        return _warn(
            "failure_streak",
            name,
            f"Son {streak} çalıştırma üst üste tam başarılı olmadı.",
            "Bir çalıştırma daha bozuk gelirse kalıcı bir sorun var demektir; "
            "şimdiden iş kaydına bakmakta fayda var.",
        )
    return _ok("failure_streak", name, "Ardışık hata yok.")


def check_slack_delivery(status: Dict[str, Any]) -> Check:
    """Did the briefing reach the human? That is the product."""
    name = "Slack teslimi"
    slack = status.get("slack") or {}
    state = str(slack.get("status") or "")
    detail = str(slack.get("detail") or "")

    if state == "failed":
        return _critical(
            "slack",
            name,
            f"Son brifing Slack'e teslim edilemedi: {detail}",
            "SLACK_WEBHOOK_URL hâlâ geçerli mi kontrol et (iptal edilen bir "
            "webhook 403/404 döner). Bot token kullanılıyorsa kanalın hâlâ "
            "erişilebilir olduğunu doğrula.",
        )
    if state == "skipped":
        # A quiet incremental run deliberately stays out of the channel.
        quiet = "yeni bulgu yok" in detail
        return _ok(
            "slack",
            name,
            "Sessiz artımlı çalıştırma — bilerek mesaj gönderilmedi."
            if quiet
            else f"Gönderim denenmedi: {detail}",
        ) if quiet else _warn(
            "slack",
            name,
            f"Slack gönderimi atlandı: {detail}",
            "Slack hiç yapılandırılmamışsa SLACK_WEBHOOK_URL ya da "
            "SLACK_BOT_TOKEN + SLACK_CHANNEL gizli değerlerini ekle.",
        )
    return _ok("slack", name, "Son brifing Slack'e teslim edildi.")


def check_quota(runs: Sequence[dict]) -> Check:
    """429 / 503 pressure — the free tier's normal failure mode."""
    name = "Kota ve yeniden deneme (429/5xx)"
    recent = [r for r in runs if isinstance(r, dict) and r.get("llm_called")][-WINDOW:]
    if not recent:
        return _ok("quota", name, "Değerlendirilecek model çağrısı yok.")

    retries = int(sum(_num(r.get("retries")) for r in recent))
    failed_calls = sum(1 for r in recent if not r.get("llm_ok"))

    if failed_calls >= len(recent) / 2 and failed_calls:
        return _critical(
            "quota",
            name,
            f"Son {len(recent)} çalıştırmanın {failed_calls} tanesinde model "
            f"hiç yanıt vermedi; toplam {retries} yeniden deneme yapıldı.",
            "Ücretsiz kota büyük olasılıkla tükenmiş durumda. Çalıştırma "
            "saatlerini seyrelt ya da GEMINI_REQUEST_SPACING_SECONDS değerini "
            "artır; kalıcıysa daha hafif bir birincil model seç.",
        )
    if retries >= len(recent) * 2:
        return _warn(
            "quota",
            name,
            f"Son {len(recent)} çalıştırmada {retries} yeniden deneme — "
            "çalıştırma başına ortalama "
            f"{retries / len(recent):.1f}.",
            "Her yeniden deneme brifingi geciktirir. "
            "GEMINI_REQUEST_SPACING_SECONDS değerini artırmak kota penceresine "
            "yayılmayı iyileştirir.",
        )
    return _ok(
        "quota",
        name,
        f"Son {len(recent)} çalıştırmada {retries} yeniden deneme — normal aralıkta.",
    )


def check_fallback(runs: Sequence[dict]) -> Check:
    """Is the PRIMARY model still doing its job?"""
    name = "Yedek model kullanımı"
    recent = [r for r in runs if isinstance(r, dict) and r.get("llm_called")][-WINDOW:]
    if not recent:
        return _ok("fallback", name, "Değerlendirilecek model çağrısı yok.")

    used = sum(1 for r in recent if r.get("fallback_used"))
    ratio = used / len(recent)

    if ratio >= FALLBACK_CRITICAL_RATIO:
        return _critical(
            "fallback",
            name,
            f"Son {len(recent)} çalıştırmanın {used} tanesinde birincil model "
            "hiç yanıt vermedi; brifing yedek modelden geldi.",
            "Birincil model pratikte kullanılamıyor. GEMINI_MODEL değerini "
            "zincirde gerçekten yanıt veren modele çevir — her çalıştırmada "
            "önce başarısız olan modeli denemek boşa bekleme demektir.",
        )
    if ratio >= FALLBACK_WARN_RATIO:
        return _warn(
            "fallback",
            name,
            f"Son {len(recent)} çalıştırmanın {used} tanesinde yedek modele düşüldü.",
            "Sıklaşırsa birincil modeli değiştirmek gecikmeyi kısaltır.",
        )
    return _ok(
        "fallback",
        name,
        f"Son {len(recent)} çalıştırmanın {used} tanesinde yedek model devreye girdi.",
    )


def check_token_budget(runs: Sequence[dict]) -> Check:
    """Is the run getting more expensive without producing more?"""
    name = "Token bütçesi eğilimi"
    scored = [r for r in runs if isinstance(r, dict) and _num(r.get("total_tokens")) > 0]
    if len(scored) < 4:
        return _ok("token_budget", name, "Eğilim için yeterli ölçüm yok.")

    recent = scored[-WINDOW:]
    values = sorted(_num(r.get("total_tokens")) for r in recent[:-1])
    median = values[len(values) // 2] if values else 0.0
    last = _num(recent[-1].get("total_tokens"))
    if median <= 0:
        return _ok("token_budget", name, "Karşılaştırılacak medyan yok.")

    ratio = last / median
    if ratio >= TOKEN_GROWTH_WARN:
        return _warn(
            "token_budget",
            name,
            f"Son çalıştırma {int(last)} token harcadı; son {len(recent)} "
            f"çalıştırmanın medyanı {int(median)} (%{(ratio - 1) * 100:.0f} artış).",
            "Panodaki Performans sekmesinde ajan başına token payına bak: "
            "payı çıktısından belirgin yüksek olan ajanın prompt'unu kısalt.",
        )
    return _ok(
        "token_budget",
        name,
        f"Son çalıştırma {int(last)} token; medyan {int(median)} — kararlı.",
    )


def check_dashboard(status: Dict[str, Any], now: datetime) -> Check:
    """Is the PUBLISHED dashboard showing what the repository already knows?"""
    name = "Pano tazeliği"
    reports_index = _read_json("frontend/reports/index.json")
    days = reports_index.get("days")
    if not isinstance(days, list) or not days:
        return _warn(
            "dashboard",
            name,
            "Yayınlanmış rapor arşivi boş.",
            "Bir tam brifing çalıştığında raporlar yazılır. Hemen doldurmak "
            "için: python scripts/seed_dashboard.py",
        )

    newest = str((days[0] or {}).get("date") or "")
    today = now.astimezone(ISTANBUL).date()
    try:
        newest_date = datetime.strptime(newest, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return _warn(
            "dashboard", name, "Arşiv indeksindeki tarih okunamadı.", "reports/index.json'u kontrol et."
        )

    lag = (today - newest_date).days
    if lag >= 2:
        return _warn(
            "dashboard",
            name,
            f"En yeni rapor günü {newest} — {lag} gün geride.",
            "Rapor yayınlama adımı sessizce başarısız oluyor olabilir; iş "
            "kaydında 'Yayınlanan rapor belgesi' satırına bak.",
        )
    return _ok("dashboard", name, f"En yeni rapor günü {newest} — güncel.")


def check_state_commit(status: Dict[str, Any], now: datetime) -> Check:
    """Did the run's state survive the ephemeral runner?

    The runner filesystem is thrown away, so the streak and the findings ledger
    only exist if the commit-back step won its race with the other runs.
    """
    name = "Durum kaydı (state commit)"
    accountability = status.get("accountability") or {}
    if not accountability.get("available"):
        return _warn(
            "state_commit",
            name,
            "Hesap Sorucu Koç'un durum dosyası bulunamadı — seri sıfırdan başlar.",
            ".assistant_state/accountability.json deponun içinde olmalı. "
            "ACCOUNTABILITY_STATE_FILE gizli değeri BOŞ bırakılmalı ki iş "
            "akışının geri commit'lediği yol kullanılsın.",
        )

    last_date = str(accountability.get("last_date") or "")
    try:
        recorded = datetime.strptime(last_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return _warn(
            "state_commit",
            name,
            "Durum dosyasında geçerli bir tarih yok.",
            "Bir sonraki tam brifing dosyayı yeniden yazar.",
        )

    lag = (now.astimezone(ISTANBUL).date() - recorded).days
    if lag >= 3:
        return _warn(
            "state_commit",
            name,
            f"Durum dosyasındaki son kayıt {last_date} — {lag} gün önce.",
            "Geri commit adımı sürekli kaybediyor olabilir (push yarışı). İş "
            "kaydında 'Could not persist state' satırını ara.",
        )
    return _ok(
        "state_commit",
        name,
        f"Durum dosyası güncel (son kayıt {last_date}, seri "
        f"{accountability.get('streak', 0)} gün).",
    )


def check_feeds(probe: Any = None) -> Check:
    """Are the RSS feeds the news advisors depend on actually reachable?

    Deliberately never CRITICAL: a dead feed degrades a section to an LLM-only
    roundup, which is a worse briefing, not a missing one. Off via
    ``WATCHDOG_CHECK_FEEDS=false`` — the only check here that touches the network.
    """
    name = "RSS besleme sağlığı"
    if not _flag("WATCHDOG_CHECK_FEEDS", True):
        return _ok("feeds", name, "Besleme kontrolü kapalı (WATCHDOG_CHECK_FEEDS).")

    fetch = probe or _probe_feed
    broken: List[str] = []
    checked = 0
    for key, label in FEED_SETTINGS:
        url = setting(key)
        if not url:
            continue
        checked += 1
        if not fetch(url):
            broken.append(label)

    if not checked:
        return _ok("feeds", name, "Yapılandırılmış besleme yok.")
    if len(broken) >= checked:
        return _warn(
            "feeds",
            name,
            f"{checked} beslemenin hepsi ({', '.join(broken)}) yanıt vermedi.",
            "Hepsi birden düşüyorsa sorun büyük olasılıkla ağ/çıkış tarafında. "
            "Haber ajanları bu sırada yalnızca modele dayanır; brifing durmaz.",
        )
    if broken:
        return _warn(
            "feeds",
            name,
            f"{len(broken)}/{checked} besleme yanıt vermedi: {', '.join(broken)}.",
            "İlgili *_RSS_URL gizli değerini güncelle ya da beslemenin "
            "kendiliğinden dönmesini bekle; o ajan bu sırada modele dayanır.",
        )
    return _ok("feeds", name, f"{checked} beslemenin hepsi yanıt verdi.")


def _probe_feed(url: str) -> bool:
    """One cheap reachability probe. Any error is simply 'unreachable'."""
    try:
        import httpx

        response = httpx.get(
            url,
            timeout=FEED_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": "ai-assistant-watchdog/1.0"},
        )
        return response.status_code < 400
    except Exception:
        return False


# --- assembling the verdict -------------------------------------------------


def run_checks(
    status: Optional[Dict[str, Any]] = None,
    runs: Optional[Sequence[dict]] = None,
    now: Optional[datetime] = None,
    probe: Any = None,
) -> List[Check]:
    """Run every check. One broken check can never hide the others."""
    moment = now or _now_utc()
    status = status or {}
    runs = list(runs or [])

    checks: List[Check] = []
    plan = [
        lambda: check_freshness(status, moment),
        lambda: check_last_run(status),
        lambda: check_failure_streak(status),
        lambda: check_slack_delivery(status),
        lambda: check_quota(runs),
        lambda: check_fallback(runs),
        lambda: check_token_budget(runs),
        lambda: check_dashboard(status, moment),
        lambda: check_state_commit(status, moment),
        lambda: check_feeds(probe),
    ]
    for step in plan:
        try:
            checks.append(step())
        except Exception as exc:  # a broken check must not hide the others
            logger.warning("kontrol çalıştırılamadı: %s", exc)
    return checks


def headline(checks: Sequence[Check]) -> str:
    """One line an engineer can read at a glance."""
    severity = overall_severity(checks)
    problems = [c for c in checks if c.severity != SEVERITY_OK]
    if not problems:
        return f"{len(checks)} teknik kontrolün hepsi temiz."
    critical = sum(1 for c in problems if c.severity == SEVERITY_CRITICAL)
    warn = len(problems) - critical
    bits = []
    if critical:
        bits.append(f"{critical} kritik")
    if warn:
        bits.append(f"{warn} uyarı")
    lead = problems[0].name
    return f"{' · '.join(bits)} ({len(checks)} kontrolden). En öncelikli: {lead}."


def build_health(
    status: Optional[Dict[str, Any]] = None,
    runs: Optional[Sequence[dict]] = None,
    now: Optional[datetime] = None,
    probe: Any = None,
    previous: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the document the dashboard and the alert both read."""
    moment = now or _now_utc()
    checks = run_checks(status=status, runs=runs, now=moment, probe=probe)
    severity = overall_severity(checks)
    previous_severity = str((previous or {}).get("severity") or "")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": moment.isoformat(timespec="seconds"),
        "generated_at_istanbul": _istanbul_label(moment),
        "severity": severity,
        "severity_icon": SEVERITY_ICON[severity],
        "severity_label": SEVERITY_LABEL[severity],
        "headline": headline(checks),
        # What the PREVIOUS verdict was, which is what makes the alert fire on
        # a state change instead of on every run.
        "previous_severity": previous_severity,
        "changed": bool(previous_severity) and previous_severity != severity,
        "counts": {
            SEVERITY_OK: sum(1 for c in checks if c.severity == SEVERITY_OK),
            SEVERITY_WARN: sum(1 for c in checks if c.severity == SEVERITY_WARN),
            SEVERITY_CRITICAL: sum(1 for c in checks if c.severity == SEVERITY_CRITICAL),
        },
        "checks": [check.to_dict() for check in checks],
    }


def write_health(document: Dict[str, Any], path: Optional[str] = None) -> Optional[str]:
    """Write the verdict. NEVER raises — a watchdog must not become the outage."""
    target = path or health_file_path()
    try:
        directory = os.path.dirname(target)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(document, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        return target
    except Exception as exc:
        logger.warning("sağlık dosyası yazılamadı (%s): %s", target, exc)
        return None


# --- alerting ---------------------------------------------------------------


def should_alert(previous: Optional[Dict[str, Any]], current: Dict[str, Any]) -> bool:
    """Whether THIS verdict is worth interrupting the user for.

    Only a CHANGE of overall state qualifies, and only into or out of red:

    * ``ok``/``warn`` → ``critical``  → alert: something just broke.
    * ``critical`` → anything else    → alert: it recovered, once.
    * anything → the same state       → silence.
    * ``ok`` ↔ ``warn``               → silence; a yellow is for the dashboard,
      not for a notification at 03:00.

    An hourly job that re-posts "still broken" twenty-four times a day teaches
    the reader to ignore it, which is strictly worse than not alerting at all.
    """
    now_severity = str(current.get("severity") or SEVERITY_OK)
    was = str((previous or {}).get("severity") or "")

    if not was:
        # First ever verdict: only shout if it is genuinely red.
        return now_severity == SEVERITY_CRITICAL
    if was == now_severity:
        return False
    return SEVERITY_CRITICAL in (was, now_severity)


def alert_text(document: Dict[str, Any]) -> str:
    """The short Slack message for a state change. Plain text, no blocks."""
    severity = str(document.get("severity") or SEVERITY_OK)
    icon = SEVERITY_ICON.get(severity, "🟢")
    label = SEVERITY_LABEL.get(severity, severity)
    was = str(document.get("previous_severity") or "")

    lines = [f"{icon} *Teknik Nöbetçi — sistem durumu: {label}*"]
    if was:
        lines.append(
            f"_Önceki durum: {SEVERITY_ICON.get(was, '')} {SEVERITY_LABEL.get(was, was)}_"
        )

    problems = [
        c
        for c in (document.get("checks") or [])
        if isinstance(c, dict) and c.get("severity") != SEVERITY_OK
    ]
    if not problems:
        lines.append("Tüm teknik kontroller yeniden temiz.")
    for check in problems[:4]:
        lines.append(
            f"{SEVERITY_ICON.get(check.get('severity'), '')} *{check.get('name')}* — "
            f"{check.get('detail')}"
        )
        if check.get("remedy"):
            lines.append(f"   🔧 {check['remedy']}")
    if len(problems) > 4:
        lines.append(f"… ve {len(problems) - 4} bulgu daha — ayrıntılar panoda.")
    return "\n".join(lines)


def send_alert(document: Dict[str, Any]) -> Optional[str]:
    """Post the state-change alert. Returns the notifier status, or ``None``."""
    if not _flag("WATCHDOG_ALERT", True):
        return None
    try:
        from .notifiers.slack_notifier import send_message

        result = send_message(alert_text(document))
        return str(getattr(result, "status", ""))
    except Exception as exc:  # an alert failure must not fail the watchdog
        logger.warning("nöbetçi uyarısı gönderilemedi: %s", exc)
        return None


# --- CLI --------------------------------------------------------------------


def _load_inputs() -> tuple:
    from .metrics import load_history, metrics_file_path  # local: keeps imports light
    from .status_report import status_file_path

    status = _read_json(status_file_path())
    try:
        runs = load_history(metrics_file_path())
    except Exception:
        runs = []
    return status, runs


def main() -> int:
    """CLI entrypoint. Writes health.json and alerts on a state CHANGE.

    Returns 0 even when the verdict is 🔴: a detected problem is a SUCCESSFUL
    watchdog run, and failing the job would only raise a second, less
    informative alarm next to the one we just posted.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    target = health_file_path()
    previous = _read_json(target)

    status, runs = _load_inputs()
    document = build_health(status=status, runs=runs, previous=previous)

    print(
        f"Teknik Nöbetçi: {document['severity_icon']} {document['severity_label']} — "
        f"{document['headline']}"
    )
    for check in document["checks"]:
        icon = SEVERITY_ICON.get(check["severity"], "")
        print(f"  {icon} {check['name']:<34} {check['detail']}")
        if check["remedy"]:
            print(f"     🔧 {check['remedy']}")

    path = write_health(document, target)
    if path:
        print(f"Sağlık dosyası: {path}")

    if should_alert(previous, document):
        status_label = send_alert(document)
        print(f"Durum değişti — Slack uyarısı gönderildi ({status_label or 'kapalı'}).")
    else:
        print("Durum değişmedi — Slack'e mesaj gönderilmedi (tekrar uyarı yok).")

    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "Check",
    "DEFAULT_HEALTH_FILE",
    "HEALTH_FILE_ENV",
    "SEVERITY_CRITICAL",
    "SEVERITY_OK",
    "SEVERITY_WARN",
    "alert_text",
    "build_health",
    "headline",
    "health_file_path",
    "overall_severity",
    "run_checks",
    "send_alert",
    "should_alert",
    "write_health",
]
