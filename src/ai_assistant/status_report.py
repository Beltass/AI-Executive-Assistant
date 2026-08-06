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

# Gmail and Calendar fetch error tracking (in-memory, reset each run)
_gmail_fetch_error: Optional[str] = None
_calendar_fetch_error: Optional[str] = None

# Integration metrics constants
INTEGRATION_METRICS_FILE_ENV = "INTEGRATION_METRICS_FILE"
DEFAULT_INTEGRATION_METRICS_FILE = "frontend/integration_metrics.json"

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


# --- the advisor manifest ---------------------------------------------------
#
# ONE table describing every advisor module in ``ai_assistant/advisors/``: what
# it is called, how it is drawn, whether it is still in service, WHEN it should
# run and how much it is allowed to cost. It is kept HERE rather than on the
# advisor classes so the advisors stay purely about producing briefings.
#
# WHY IT IS THE SINGLE SOURCE OF TRUTH. The roster used to live in three places
# that could — and did — drift apart: a hand-written list of imports in
# ``advisors.all_advisors()``, this presentation table, and the Slack channel
# tuple. ``meeting_prep`` was the proof: its module, its metadata, its Slack
# route and its dashboard entry all existed, but nobody imported it, so it had
# not produced a single briefing. The roster is now DERIVED from this table
# (see :func:`live_advisor_keys`), and a test asserts the two cannot diverge.
#
# FIELDS
#   title/emoji/category  Presentation. ``category`` is what the dashboard
#       groups and filters by; ``title`` mirrors the advisor's Turkish title for
#       readability here — the value actually written to the status file comes
#       from the briefing itself, so the two cannot drift at runtime.
#   status                ``live`` (in the roster) or ``retired`` (module kept
#       on disk so a rollback is a one-line change, not a revert).
#   trigger               WHEN it runs — see the ``TRIGGER_*`` constants. This
#       is what :mod:`ai_assistant.operations_manager` filters on.
#   token_ceiling         Rough per-run token budget, used by the metrics layer
#       to say "this advisor is over its share". ``0`` = does not call an LLM.
#   data_owner            The SOURCE this advisor reads. Advisors sharing an
#       owner share one content hash, so an unchanged source skips all of them
#       at once (see :mod:`ai_assistant.memory`).
#   dashboard_order       Report/roster position; also the roster order itself.
#   slack_target          Default channel handle for the per-advisor fan-out.
#   module/advisor_class  Where the implementation lives, so the roster can be
#       built from this table instead of a parallel list of imports.
#
# Anything unknown falls back to :data:`DEFAULT_META` rather than raising.

CATEGORY_CAREER = "kariyer"
CATEGORY_FAMILY = "aile"
CATEGORY_SECTOR = "sektör"
CATEGORY_GROWTH = "kişisel gelişim"
CATEGORY_OPS = "operasyon"

#: In the live roster: instantiated by ``advisors.all_advisors()``.
ADVISOR_LIVE = "live"
#: Module kept on disk for rollback, but nobody runs it.
ADVISOR_RETIRED = "retired"

#: Runs on EVERY run. Reserve it for advisors the briefing is useless without.
TRIGGER_ALWAYS = "always"
#: Runs only when its ``data_owner`` source actually changed.
TRIGGER_DATA = "data_triggered"
#: Runs once a week — rhythm pieces whose advice does not change daily.
TRIGGER_WEEKLY = "weekly"
#: Runs only when explicitly asked for (``DIGEST_FORCE_ADVISORS``).
TRIGGER_USER_REQUESTED = "user_requested"

TRIGGERS = (TRIGGER_ALWAYS, TRIGGER_DATA, TRIGGER_WEEKLY, TRIGGER_USER_REQUESTED)


def _live(
    key: str,
    title: str,
    emoji: str,
    category: str,
    *,
    advisor_class: str,
    trigger: str,
    token_ceiling: int,
    data_owner: str,
) -> tuple:
    """One live advisor. ``dashboard_order`` is filled in from its position."""
    return key, {
        "title": title,
        "emoji": emoji,
        "category": category,
        "status": ADVISOR_LIVE,
        "trigger": trigger,
        "token_ceiling": int(token_ceiling),
        "data_owner": data_owner,
        "dashboard_order": 0,
        "slack_target": "#" + key.replace("_", "-"),
        "module": key,
        "advisor_class": advisor_class,
    }


def _retired(
    key: str, title: str, emoji: str, category: str, *, advisor_class: str
) -> tuple:
    """A module kept on disk but out of service.

    Retired advisors carry ``user_requested`` because that is the only way they
    can still run: someone naming them explicitly. They own no source, hold no
    dashboard position and route nowhere.
    """
    return key, {
        "title": title,
        "emoji": emoji,
        "category": category,
        "status": ADVISOR_RETIRED,
        "trigger": TRIGGER_USER_REQUESTED,
        "token_ceiling": 0,
        "data_owner": "",
        "dashboard_order": 0,
        "slack_target": "",
        "module": key,
        "advisor_class": advisor_class,
    }


#: The live roster, IN REPORT ORDER. The order of this tuple is the order the
#: advisors run in, so the ordering rules live here: the two "before the day
#: starts" sections and meeting prep open it; the work analyst consolidates the
#: others so it comes late; the operations director synthesises everything
#: including the analyst; the SRE watchdog reports on the MACHINE and closes.
_LIVE_ROSTER = (
    _live(
        "morning_operations",
        "Sabah İşletme Brifingi",
        "📋",
        CATEGORY_OPS,
        advisor_class="MorningOperationsAdvisor",
        trigger=TRIGGER_ALWAYS,
        token_ceiling=1600,
        data_owner="gmail_calendar",
    ),
    _live(
        "communications_calendar",
        "İletişim & Takvim Danışmanı",
        "📬",
        CATEGORY_OPS,
        advisor_class="CommunicationsCalendarAdvisor",
        trigger=TRIGGER_ALWAYS,
        token_ceiling=1400,
        data_owner="gmail_calendar",
    ),
    _live(
        "meeting_prep",
        "Toplantı Hazırlık & Takip",
        "🤝",
        CATEGORY_OPS,
        advisor_class="MeetingPrepAdvisor",
        trigger=TRIGGER_DATA,
        token_ceiling=1200,
        data_owner="calendar",
    ),
    _live(
        "drive_insight",
        "Drive Dosya Analisti (Yeni Dosya · Özet · Sunum Taslağı)",
        "🗂️",
        CATEGORY_OPS,
        advisor_class="DriveInsightAdvisor",
        # Konusu KLASÖRÜN KENDİSİ: yeni dosya yoksa anlatacak bir şey de yok,
        # o yüzden günlük değil veri tetiklemeli. Kaynak sahibi ``drive_files``
        # olduğu için klasör değişmediğinde model hiç çağrılmaz.
        trigger=TRIGGER_DATA,
        token_ceiling=1400,
        data_owner="drive_files",
    ),
    _live(
        "career_development",
        "Kariyer Gelişimi (İK · İlanlar · İngilizce · Sertifika)",
        "💼",
        CATEGORY_CAREER,
        advisor_class="CareerDevelopmentAdvisor",
        trigger=TRIGGER_DATA,
        token_ceiling=1200,
        data_owner="career_feeds",
    ),
    _live(
        "market_intelligence",
        "Pazar İstihbaratı (Sektör · YZ · CX · Bankacılık)",
        "📊",
        CATEGORY_SECTOR,
        advisor_class="MarketIntelligenceAdvisor",
        trigger=TRIGGER_DATA,
        token_ceiling=1400,
        data_owner="market_feeds",
    ),
    _live(
        "complaint_radar",
        "Kapsamlı Pazar & Sentiment Analizi (Müşteri Şikayet · Trendler · Rekabet)",
        "📊",
        CATEGORY_SECTOR,
        advisor_class="ComplaintRadarAdvisor",
        trigger=TRIGGER_DATA,
        token_ceiling=1200,
        data_owner="complaint_feeds",
    ),
    _live(
        "linkedin_coach",
        "LinkedIn İmaj Koçu (Profil · Post · Engagement)",
        "💼",
        CATEGORY_GROWTH,
        advisor_class="LinkedInCoach",
        trigger=TRIGGER_DATA,
        token_ceiling=1000,
        data_owner="linkedin",
    ),
    _live(
        "social_media_coach",
        "Sosyal Medya İmaj Koçu (Instagram · Twitter · Marka)",
        "📱",
        CATEGORY_GROWTH,
        advisor_class="SocialMediaCoachAdvisor",
        trigger=TRIGGER_WEEKLY,
        token_ceiling=900,
        data_owner="social",
    ),
    _live(
        "personal_assistant",
        "Kişisel Asistan (Takvim · Hedefler · Ağ · Fırsatlar)",
        "📅",
        CATEGORY_OPS,
        advisor_class="PersonalAssistantAdvisor",
        trigger=TRIGGER_WEEKLY,
        token_ceiling=1000,
        data_owner="calendar_tasks",
    ),
    _live(
        "data_analyst",
        "Raporlama & Veri Analisti (Excel · Sunum Taslağı · Yazılı Rapor)",
        "🔬",
        CATEGORY_OPS,
        advisor_class="DataAnalystAdvisor",
        trigger=TRIGGER_DATA,
        token_ceiling=1600,
        data_owner="analysis_dataset",
    ),
    _live(
        "ai_innovation",
        "Yapay Zeka & İnovasyon (Ustalaşma · Fikirler)",
        "🧠",
        CATEGORY_GROWTH,
        advisor_class="AiInnovationAdvisor",
        trigger=TRIGGER_WEEKLY,
        token_ceiling=1000,
        data_owner="ai_feeds",
    ),
    _live(
        "kids_development",
        "Çocuk Gelişimi Danışmanı",
        "👨‍👩‍👧",
        CATEGORY_FAMILY,
        advisor_class="KidsDevelopmentAdvisor",
        # No feed, no cadence: it is timeless coaching, so it runs when asked
        # rather than burning a slice of every quota window.
        trigger=TRIGGER_USER_REQUESTED,
        token_ceiling=800,
        data_owner="",
    ),
    _live(
        "executive_coaching",
        "Yönetici Koçu (Gelişim + Hesap Verebilirlik)",
        "🧭",
        CATEGORY_GROWTH,
        advisor_class="ExecutiveCoachingAdvisor",
        trigger=TRIGGER_WEEKLY,
        token_ceiling=900,
        data_owner="",
    ),
    _live(
        "productivity_coach",
        "Verimlilik Koçu (Odak Blokları · Enerji Yönetimi)",
        "⏱️",
        CATEGORY_GROWTH,
        advisor_class="ProductivityCoachAdvisor",
        # Gün mimarisi günden güne değişmez: haftada bir kurulur, hafta boyunca
        # uygulanır. Her sabah tekrarlamak kotayı da dikkati de boşa harcardı.
        trigger=TRIGGER_WEEKLY,
        token_ceiling=900,
        data_owner="",
    ),
    _live(
        "risk_sentinel",
        "Risk Nöbetçisi (Erken Uyarı · Eşik Aşımı)",
        "📉",
        CATEGORY_OPS,
        advisor_class="RiskSentinelAdvisor",
        # Konusu koşu GEÇMİŞİ: yeni koşu kaydı yoksa trend de değişmez, o yüzden
        # veri tetiklemeli. ``run_history`` sahibi olduğu için geçmiş
        # büyümediğinde model hiç çağrılmaz.
        trigger=TRIGGER_DATA,
        token_ceiling=1200,
        data_owner="run_history",
    ),
    _live(
        "decision_intelligence",
        "Karar Zekâsı (Sonuç Takibi · Karar Kalitesi)",
        "⚖️",
        CATEGORY_OPS,
        advisor_class="DecisionIntelligenceAdvisor",
        # Bir kararın sonucu bir günde belli olmaz: haftalık ritim, hem tekrarı
        # hem kota israfını engeller.
        trigger=TRIGGER_WEEKLY,
        token_ceiling=1000,
        data_owner="",
    ),
    _live(
        "social_guardian",
        "İtibar Muhafızı (Kriz Erken Uyarısı)",
        "🛟",
        CATEGORY_SECTOR,
        advisor_class="SocialGuardianAdvisor",
        # Konusu izleme AKIŞI: yeni başlık yoksa uyarı da yok. ``reputation_feeds``
        # sahibi olduğu için akış değişmediğinde model hiç çağrılmaz.
        trigger=TRIGGER_DATA,
        token_ceiling=1200,
        data_owner="reputation_feeds",
    ),
    _live(
        "work_analyst",
        "İş Analisti Danışmanı",
        "📈",
        CATEGORY_OPS,
        advisor_class="WorkAnalystAdvisor",
        # Consolidates the SYSTEM's health from the run itself, so it has to see
        # every run — and it costs no model call to do it.
        trigger=TRIGGER_ALWAYS,
        token_ceiling=0,
        data_owner="run_briefings",
    ),
    _live(
        "operations_director",
        "Operasyon Direktörü (Günün Kararları)",
        "🚦",
        CATEGORY_OPS,
        advisor_class="OperationsDirectorAdvisor",
        trigger=TRIGGER_ALWAYS,
        token_ceiling=1600,
        data_owner="run_briefings",
    ),
    _live(
        "sre_watchdog",
        "Teknik Gözetim (7/24 SRE)",
        "🛡️",
        CATEGORY_OPS,
        advisor_class="SreWatchdogAdvisor",
        trigger=TRIGGER_ALWAYS,
        token_ceiling=0,
        data_owner="system_health",
    ),
)

#: Retired modules. Kept in the manifest — rather than deleted from it — so
#: "which advisors exist?" has ONE answer and a rollback is a status change.
_RETIRED_ROSTER = (
    # PHASE 1A: folded into MorningOperationsAdvisor
    _retired(
        "morning_briefing",
        "Sabah Performans Brifingi",
        "🌅",
        CATEGORY_OPS,
        advisor_class="MorningBriefingAdvisor",
    ),
    _retired(
        "mail_analyst",
        "E-posta Analiz Danışmanı",
        "📧",
        CATEGORY_OPS,
        advisor_class="MailAnalystAdvisor",
    ),
    _retired(
        "day_planner",
        "Günlük Planlayıcı",
        "🗓️",
        CATEGORY_OPS,
        advisor_class="DayPlannerAdvisor",
    ),
    # PHASE 1A: folded into ExecutiveCoachingAdvisor
    _retired(
        "leadership_coach",
        "Liderlik Koçu",
        "🎯",
        CATEGORY_GROWTH,
        advisor_class="LeadershipCoachAdvisor",
    ),
    _retired(
        "accountability_coach",
        "Hesap Sorucu Koç",
        "✅",
        CATEGORY_GROWTH,
        advisor_class="AccountabilityCoachAdvisor",
    ),
    # PHASE 1B: folded into CareerDevelopmentAdvisor
    _retired(
        "career_hr",
        "Kariyer & İK Danışmanı",
        "💼",
        CATEGORY_CAREER,
        advisor_class="CareerHrAdvisor",
    ),
    _retired(
        "job_scout",
        "İş Avcısı & Başvuru Hazırlayıcı",
        "🎯",
        CATEGORY_CAREER,
        advisor_class="JobScoutAdvisor",
    ),
    _retired(
        "language_coach",
        "İngilizce & Yönetici İletişimi Koçu",
        "🗣️",
        CATEGORY_CAREER,
        advisor_class="LanguageCoachAdvisor",
    ),
    _retired(
        "free_certs",
        "Ücretsiz Sertifika & Eğitim Araştırmacısı",
        "🎓",
        CATEGORY_CAREER,
        advisor_class="FreeCertsAdvisor",
    ),
    # PHASE 1B: folded into MarketIntelligenceAdvisor
    _retired(
        "sector_intel",
        "Sektör & Rakip İstihbaratı",
        "🛰️",
        CATEGORY_SECTOR,
        advisor_class="SectorIntelAdvisor",
    ),
    _retired(
        "ai_news",
        "Yapay Zeka Haberleri",
        "📰",
        CATEGORY_SECTOR,
        advisor_class="AiNewsAdvisor",
    ),
    _retired(
        "cx_research",
        "Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı",
        "🎧",
        CATEGORY_SECTOR,
        advisor_class="CxResearchAdvisor",
    ),
    _retired(
        "banking_cc_projects",
        "Banka & Çağrı Merkezi Proje Uzmanı",
        "🏦",
        CATEGORY_SECTOR,
        advisor_class="BankingCcProjectsAdvisor",
    ),
    # PHASE 1B: folded into AiInnovationAdvisor
    _retired(
        "ai_mastery",
        "Yapay Zeka Ustalığı Koçu",
        "🤖",
        CATEGORY_GROWTH,
        advisor_class="AiMasteryAdvisor",
    ),
    _retired(
        "innovation_lab",
        "İnovasyon Laboratuvarı",
        "🧪",
        CATEGORY_GROWTH,
        advisor_class="InnovationLabAdvisor",
    ),
    # PHASE 1B: superseded by MorningOperationsAdvisor
    _retired(
        "daily_ops_briefing",
        "Gün Başı Operasyon Brifingi",
        "📋",
        CATEGORY_OPS,
        advisor_class="DailyOpsBriefingAdvisor",
    ),
    # PHASE 1C: retired outright
    _retired(
        "weather",
        "Hava Durumu Meteoroloğu",
        "☀️",
        CATEGORY_OPS,
        advisor_class="WeatherAdvisor",
    ),
    _retired(
        "anka_bridge",
        "Anka Köprüsü",
        "🌉",
        CATEGORY_OPS,
        advisor_class="AnkaBridgeAdvisor",
    ),
    # Driven by the meeting-notes pipeline, not by the daily roster.
    _retired(
        "meeting_notes",
        "Toplantı Notları",
        "📝",
        CATEGORY_OPS,
        advisor_class="MeetingNotesAgent",
    ),
)


def _build_manifest() -> Dict[str, Dict[str, Any]]:
    manifest: Dict[str, Dict[str, Any]] = {}
    for order, (key, record) in enumerate(_LIVE_ROSTER, start=1):
        record["dashboard_order"] = order
        manifest[key] = record
    for key, record in _RETIRED_ROSTER:
        manifest[key] = record
    return manifest


ADVISOR_META: Dict[str, Dict[str, Any]] = _build_manifest()

DEFAULT_META: Dict[str, Any] = {
    "title": "",
    "emoji": "🧩",
    "category": CATEGORY_OPS,
    "status": ADVISOR_RETIRED,
    "trigger": TRIGGER_USER_REQUESTED,
    "token_ceiling": 0,
    "data_owner": "",
    "dashboard_order": 0,
    "slack_target": "",
    "module": "",
    "advisor_class": "",
}


# --- reading the manifest ---------------------------------------------------


def advisor_meta(key: str) -> Dict[str, Any]:
    """The manifest record for ``key``, or :data:`DEFAULT_META` if unknown."""
    return ADVISOR_META.get(key, DEFAULT_META)


def is_live(key: str) -> bool:
    """Whether ``key`` is in the CURRENT roster (not retired, not unknown)."""
    return advisor_meta(key).get("status") == ADVISOR_LIVE


def live_advisor_keys() -> tuple:
    """Every live advisor key, in roster (``dashboard_order``) order.

    This is what ``ai_assistant.advisors.all_advisors()`` builds the team from,
    so adding an advisor here — and only here — puts it on the roster, in the
    dashboard, and on its own Slack route.
    """
    live = [(m["dashboard_order"], k) for k, m in ADVISOR_META.items() if is_live(k)]
    return tuple(key for _order, key in sorted(live))


def retired_advisor_keys() -> tuple:
    """Every retired advisor key, alphabetically."""
    return tuple(sorted(k for k in ADVISOR_META if not is_live(k)))


def advisor_trigger(key: str) -> str:
    """WHEN this advisor runs — one of :data:`TRIGGERS`."""
    return str(advisor_meta(key).get("trigger") or TRIGGER_USER_REQUESTED)


def advisor_data_owner(key: str) -> str:
    """The source whose content decides whether this advisor has work to do."""
    return str(advisor_meta(key).get("data_owner") or "")


def advisor_token_ceiling(key: str) -> int:
    """Rough per-run token budget; ``0`` means "makes no model call"."""
    try:
        return int(advisor_meta(key).get("token_ceiling") or 0)
    except (TypeError, ValueError):  # pragma: no cover - defensive only
        return 0


def advisors_with_trigger(trigger: str) -> tuple:
    """Live advisor keys whose trigger is ``trigger``, in roster order."""
    return tuple(k for k in live_advisor_keys() if advisor_trigger(k) == trigger)


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
    re.compile(r"AIza[0-9A-Za-z\-_]{10,}"),  # Google / Gemini
    re.compile(r"sk-[A-Za-z0-9\-_]{16,}"),  # OpenAI
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{8,}"),  # Slack tokens
    re.compile(r"ghp_[A-Za-z0-9]{16,}"),  # GitHub PAT
    re.compile(r"hooks\.slack\.com/services/\S+"),  # Slack webhook path
    re.compile(r"(?i)(api[-_]?key|token|secret|password)=[^\s&\"']+"),
)

REDACTED = "***"


# --- integration metrics tracking ------------------------------------------


class IntegrationMetrics:
    """Track health and performance metrics for external integrations.

    This class manages persistent tracking of:
    - Slack: channel messages sent, failed deliveries
    - Asana: projects/tasks created, tasks completed, failed operations
    - Drive: documents uploaded, archives stored, failed uploads

    Metrics are accumulated throughout a calendar day (UTC) and reset at midnight.
    """

    def __init__(self) -> None:
        """Initialize metrics, loading any existing data from today."""
        self.data = self._load_todays_metrics()
        self._ensure_integration_sections()

    def _ensure_integration_sections(self) -> None:
        """Ensure all required integration sections exist in the data."""
        if "integrations" not in self.data:
            self.data["integrations"] = {}

        integrations = self.data["integrations"]
        for integration in ("slack", "asana", "drive"):
            if integration not in integrations:
                integrations[integration] = self._empty_integration_state(integration)

    def _empty_integration_state(self, integration: str) -> Dict[str, Any]:
        """Return the template for a fresh integration state."""
        base = {
            "enabled": True,
            "last_health_check": None,
            "health_status": "unknown",
        }

        if integration == "slack":
            return {
                **base,
                "channels_configured": 0,
                "messages_sent_today": 0,
                "failed_sends": [],
                "last_post_time": None,
            }
        elif integration == "asana":
            return {
                **base,
                "projects_created": 0,
                "tasks_created": 0,
                "tasks_completed": 0,
                "failed_operations": [],
                "last_sync_time": None,
            }
        elif integration == "drive":
            return {
                **base,
                "documents_uploaded": 0,
                "archive_count": 0,
                "failed_uploads": [],
                "last_sync_time": None,
            }
        return base

    def _load_todays_metrics(self) -> Dict[str, Any]:
        """Load metrics from today, or start fresh if none exist or date changed."""
        path = integration_metrics_file_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except FileNotFoundError:
            return {"date": self._today_date(), "integrations": {}}
        except Exception as exc:
            logger.warning("entegrasyon metrik dosyası okunamadı (%s): %s", path, exc)
            return {"date": self._today_date(), "integrations": {}}

        if not isinstance(existing, dict):
            return {"date": self._today_date(), "integrations": {}}

        # If the date has changed, reset metrics for the new day
        stored_date = existing.get("date", "")
        today = self._today_date()
        if stored_date != today:
            return {"date": today, "integrations": {}}

        return existing

    def _today_date(self) -> str:
        """Return today's date in ISO format (UTC)."""
        return _now_utc().date().isoformat()

    def record_slack_send(
        self, channel: str, success: bool, timestamp: Optional[datetime] = None
    ) -> None:
        """Record a Slack message send attempt.

        Args:
            channel: Slack channel name or ID.
            success: True if send succeeded, False if failed.
            timestamp: When the send occurred (defaults to now).
        """
        if "slack" not in self.data["integrations"]:
            self.data["integrations"]["slack"] = self._empty_integration_state("slack")

        slack = self.data["integrations"]["slack"]
        when = (timestamp or _now_utc()).isoformat(timespec="seconds")

        if success:
            slack["messages_sent_today"] = int(slack.get("messages_sent_today", 0)) + 1
            slack["last_post_time"] = when
        else:
            failed = slack.get("failed_sends", [])
            if isinstance(failed, list):
                failed.append({"channel": channel, "timestamp": when})
                # Keep only recent failures (last 50)
                slack["failed_sends"] = failed[-50:]

    def record_asana_operation(
        self, operation_type: str, success: bool, timestamp: Optional[datetime] = None
    ) -> None:
        """Record an Asana operation (project/task create/complete).

        Args:
            operation_type: One of "project_created", "task_created", "task_completed".
            success: True if operation succeeded.
            timestamp: When the operation occurred (defaults to now).
        """
        if "asana" not in self.data["integrations"]:
            self.data["integrations"]["asana"] = self._empty_integration_state("asana")

        asana = self.data["integrations"]["asana"]
        when = (timestamp or _now_utc()).isoformat(timespec="seconds")

        if success:
            if operation_type == "project_created":
                asana["projects_created"] = int(asana.get("projects_created", 0)) + 1
            elif operation_type == "task_created":
                asana["tasks_created"] = int(asana.get("tasks_created", 0)) + 1
            elif operation_type == "task_completed":
                asana["tasks_completed"] = int(asana.get("tasks_completed", 0)) + 1
            asana["last_sync_time"] = when
        else:
            failed = asana.get("failed_operations", [])
            if isinstance(failed, list):
                failed.append({"operation": operation_type, "timestamp": when})
                # Keep only recent failures (last 50)
                asana["failed_operations"] = failed[-50:]

    def record_drive_upload(
        self, filename: str, success: bool, timestamp: Optional[datetime] = None
    ) -> None:
        """Record a Google Drive upload.

        Args:
            filename: Name of the uploaded file.
            success: True if upload succeeded.
            timestamp: When the upload occurred (defaults to now).
        """
        if "drive" not in self.data["integrations"]:
            self.data["integrations"]["drive"] = self._empty_integration_state("drive")

        drive = self.data["integrations"]["drive"]
        when = (timestamp or _now_utc()).isoformat(timespec="seconds")

        if success:
            if filename.startswith("archive_") or filename.endswith("_archive.zip"):
                drive["archive_count"] = int(drive.get("archive_count", 0)) + 1
            else:
                drive["documents_uploaded"] = (
                    int(drive.get("documents_uploaded", 0)) + 1
                )
            drive["last_sync_time"] = when
        else:
            failed = drive.get("failed_uploads", [])
            if isinstance(failed, list):
                failed.append({"filename": filename, "timestamp": when})
                # Keep only recent failures (last 50)
                drive["failed_uploads"] = failed[-50:]

    def record_health_check(
        self, integration: str, healthy: bool, timestamp: Optional[datetime] = None
    ) -> None:
        """Record an integration health check result.

        Args:
            integration: One of "slack", "asana", "drive".
            healthy: True if health check passed.
            timestamp: When the check occurred (defaults to now).
        """
        if integration not in self.data.get("integrations", {}):
            return

        when = (timestamp or _now_utc()).isoformat(timespec="seconds")
        self.data["integrations"][integration]["last_health_check"] = when
        self.data["integrations"][integration]["health_status"] = (
            "healthy" if healthy else "unhealthy"
        )

    def get_integration_summary(self) -> Dict[str, Any]:
        """Return the complete integration metrics summary."""
        return {
            "date": self.data.get("date", self._today_date()),
            "integrations": self.data.get("integrations", {}),
        }

    def persist(self, path: Optional[str] = None) -> bool:
        """Write metrics to disk. Returns True on success, False on error."""
        target = path or integration_metrics_file_path()
        try:
            directory = os.path.dirname(target)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            return True
        except Exception as exc:
            logger.warning(
                "entegrasyon metrik dosyası yazılamadı (%s): %s", target, exc
            )
            return False


def integration_metrics_file_path() -> str:
    """Where integration metrics are persisted."""
    return (
        os.getenv(INTEGRATION_METRICS_FILE_ENV) or ""
    ).strip() or DEFAULT_INTEGRATION_METRICS_FILE


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


#: Longest task text published to the dashboard. The coach already truncates,
#: this is the belt-and-braces cap.
MAX_TASK_CHARS = 400


def _private_titles(briefings: Any) -> set:
    """Titles of the advisors whose content must never be published.

    The accountability coach collects every advisor's ``✅ Bugünün görevi``,
    INCLUDING the private Gmail/Calendar briefing's. Its tasks are prefixed
    ``*Advisor Title* — …``, so the titles are what the filter below needs.
    """
    from .reports import is_private

    titles = set()
    for briefing in briefings or []:
        if is_private(briefing):
            titles.add(str(getattr(briefing, "title", "") or ""))
    return {title for title in titles if title}


def _publishable_tasks(tasks: Any, private_titles: set) -> List[str]:
    """The task list minus anything a PRIVATE advisor contributed.

    The dashboard is public. A task lifted out of the Gmail/Calendar briefing
    can name a person or a meeting, so it is dropped here rather than trusted to
    stay short. Everything else already lives in ``frontend/reports/``, so
    publishing it reveals nothing new.
    """
    out: List[str] = []
    for task in tasks or []:
        text = sanitize(str(task or ""), limit=MAX_TASK_CHARS)
        if not text:
            continue
        if any(title and title in text[:120] for title in private_titles):
            continue
        out.append(text)
    return out


def _accountability_snapshot(briefings: Any = None) -> Dict[str, Any]:
    """Streak + today's tasks from the coach's state file, if present."""
    snapshot: Dict[str, Any] = {
        "available": False,
        "streak": 0,
        "today_task_count": 0,
        "last_date": "",
        "tasks": [],
        "history_days": 0,
    }
    try:
        from .advisors.accountability_coach import DEFAULT_STATE_FILE

        path = (
            os.getenv("ACCOUNTABILITY_STATE_FILE") or ""
        ).strip() or DEFAULT_STATE_FILE
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return snapshot
        private_titles = _private_titles(briefings)
        tasks = _publishable_tasks(data.get("last_tasks"), private_titles)
        history = data.get("history")
        snapshot["available"] = True
        snapshot["streak"] = int(data.get("streak") or 0)
        snapshot["last_date"] = str(data.get("last_date") or "")
        snapshot["today_task_count"] = len(tasks)
        snapshot["tasks"] = tasks
        snapshot["history_days"] = len(history) if isinstance(history, dict) else 0
    except Exception:
        # No state yet is the normal day-one case, not an error.
        return snapshot
    return snapshot


def _integrations_snapshot() -> Dict[str, Any]:
    """Integration health and performance metrics from connected services.

    Loads persisted metrics from today's activities across Slack, Asana, and
    Google Drive. Returns a dictionary with:
    - Slack: channels_configured, messages_sent_today, failed_sends, last_post_time
    - Asana: projects_created, tasks_created, tasks_completed, failed_operations
    - Drive: documents_uploaded, archive_count, failed_uploads, last_sync_time
    """
    try:
        metrics = IntegrationMetrics()
        summary = metrics.get_integration_summary()

        # Get integration data from metrics
        integrations = summary.get("integrations", {})

        # Build the snapshot with the tracked metrics
        snapshot = {
            "slack": integrations.get(
                "slack",
                {
                    "enabled": True,
                    "channels_configured": 0,
                    "messages_sent_today": 0,
                    "failed_sends": [],
                    "last_post_time": None,
                },
            ),
            "asana": integrations.get(
                "asana",
                {
                    "enabled": True,
                    "projects_created": 0,
                    "tasks_created": 0,
                    "tasks_completed": 0,
                    "failed_operations": [],
                    "last_sync_time": None,
                },
            ),
            "drive": integrations.get(
                "drive",
                {
                    "enabled": True,
                    "documents_uploaded": 0,
                    "archive_count": 0,
                    "failed_uploads": [],
                    "last_sync_time": None,
                },
            ),
        }

        # Count configured Slack channels from environment
        slack_channels = [
            os.getenv("SLACK_CHANNEL_MAIL_ANALYST", "").strip(),
            os.getenv("SLACK_CHANNEL_LEADERSHIP", "").strip(),
            os.getenv("SLACK_CHANNEL_CAREER", "").strip(),
            os.getenv("SLACK_CHANNEL_SECTOR", "").strip(),
            os.getenv("SLACK_CHANNEL_OPS", "").strip(),
            os.getenv("SLACK_CHANNEL_FAMILY", "").strip(),
            os.getenv("SLACK_CHANNEL_GROWTH", "").strip(),
            os.getenv("SLACK_CHANNEL_MAIN", "").strip(),
        ]
        snapshot["slack"]["channels_configured"] = sum(1 for ch in slack_channels if ch)

        return snapshot
    except Exception as exc:
        logger.warning("entegrasyon durumu toplanırken hata: %s", exc)
        # Return safe defaults if metrics fail
        return {
            "slack": {
                "enabled": True,
                "channels_configured": 0,
                "messages_sent_today": 0,
                "failed_sends": [],
                "last_post_time": None,
            },
            "asana": {
                "enabled": True,
                "projects_created": 0,
                "tasks_created": 0,
                "tasks_completed": 0,
                "failed_operations": [],
                "last_sync_time": None,
            },
            "drive": {
                "enabled": True,
                "documents_uploaded": 0,
                "archive_count": 0,
                "failed_uploads": [],
                "last_sync_time": None,
            },
        }


def _gmail_snapshot(briefings: Any = None) -> Dict[str, Any]:
    """Gmail metrics from Mail Analyst advisor.

    Collects email statistics from the Mail Analyst briefing if available.
    Gracefully handles missing data by returning empty metrics.

    Returns:
        Dictionary with Gmail metrics: unread_count, total_emails_24h,
        urgent_count, action_items, vip_emails, last_update, and any fetch errors.
    """
    snapshot: Dict[str, Any] = {
        "enabled": True,
        "unread_count": 0,
        "total_emails_24h": 0,
        "urgent_count": 0,
        "action_items": 0,
        "vip_emails": 0,
        "last_update": _now_utc().isoformat(timespec="seconds"),
        "last_fetch_error": None,
    }

    try:
        # Look for mail_analyst briefing in the provided briefings
        if briefings:
            for briefing in briefings:
                key = str(getattr(briefing, "key", "") or "")
                if key == "mail_analyst":
                    status = str(getattr(briefing, "status", "") or STATUS_SKIPPED)
                    # Only process if the advisor ran successfully
                    if status == STATUS_OK:
                        # For now, store flag that data is available
                        # Actual metrics extraction would happen from parsed briefing text
                        # or structured metrics passed by the advisor
                        snapshot["enabled"] = True
                    elif status == STATUS_SKIPPED:
                        snapshot["enabled"] = False
                    break

        # Record any fetch error that was set via record_gmail_fetch()
        if _gmail_fetch_error:
            snapshot["last_fetch_error"] = sanitize(_gmail_fetch_error)

    except Exception as exc:
        logger.warning("gmail durumu toplanırken hata: %s", exc)
        snapshot["last_fetch_error"] = sanitize(str(exc))

    return snapshot


def _calendar_snapshot(briefings: Any = None) -> Dict[str, Any]:
    """Calendar metrics from Day Planner advisor.

    Collects meeting and availability statistics from the Day Planner briefing
    if available. Gracefully handles missing data by returning empty metrics.

    Returns:
        Dictionary with Calendar metrics: today_meetings, total_meeting_time_hours,
        focus_blocks_available, next_meeting, available_slots, last_update,
        and any fetch errors.
    """
    snapshot: Dict[str, Any] = {
        "enabled": True,
        "today_meetings": 0,
        "total_meeting_time_hours": 0.0,
        "focus_blocks_available": 0,
        "next_meeting": {
            "summary": None,
            "time": None,
            "duration_minutes": None,
        },
        "available_slots": [],
        "last_update": _now_utc().isoformat(timespec="seconds"),
        "last_fetch_error": None,
    }

    try:
        # Look for day_planner briefing in the provided briefings
        if briefings:
            for briefing in briefings:
                key = str(getattr(briefing, "key", "") or "")
                if key == "day_planner":
                    status = str(getattr(briefing, "status", "") or STATUS_SKIPPED)
                    # Only process if the advisor ran successfully
                    if status == STATUS_OK:
                        snapshot["enabled"] = True
                    elif status == STATUS_SKIPPED:
                        snapshot["enabled"] = False
                    break

        # Record any fetch error that was set via record_calendar_fetch()
        if _calendar_fetch_error:
            snapshot["last_fetch_error"] = sanitize(_calendar_fetch_error)

    except Exception as exc:
        logger.warning("takvim durumu toplanırken hata: %s", exc)
        snapshot["last_fetch_error"] = sanitize(str(exc))

    return snapshot


def record_gmail_fetch(success: bool, error_msg: Optional[str] = None) -> None:
    """Record the result of a Gmail fetch operation.

    Args:
        success: True if fetch succeeded, False otherwise.
        error_msg: Optional error message if fetch failed.
    """
    global _gmail_fetch_error

    if not success and error_msg:
        _gmail_fetch_error = error_msg
        logger.warning("gmail getirme hatası: %s", error_msg)
    elif success:
        _gmail_fetch_error = None


def record_calendar_fetch(success: bool, error_msg: Optional[str] = None) -> None:
    """Record the result of a Calendar fetch operation.

    Args:
        success: True if fetch succeeded, False otherwise.
        error_msg: Optional error message if fetch failed.
    """
    global _calendar_fetch_error

    if not success and error_msg:
        _calendar_fetch_error = error_msg
        logger.warning("takvim getirme hatası: %s", error_msg)
    elif success:
        _calendar_fetch_error = None


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


# --- performance metrics ---------------------------------------------------


def _calculate_completion_rate(advisors: List[Dict[str, Any]]) -> float:
    """Calculate completion rate from advisor results (0-100).

    Completion rate = (total advisors - skipped) / total advisors * 100
    Measures how many advisors actually ran (ok or failed).
    """
    if not advisors:
        return 0.0
    total = len(advisors)
    skipped = sum(1 for a in advisors if a.get("status") == STATUS_SKIPPED)
    if total == 0:
        return 0.0
    return round((total - skipped) / total * 100, 1)


def _calculate_deadline_adherence(counts: Dict[str, int]) -> float:
    """Calculate deadline adherence from advisor statuses (0-100).

    Deadline adherence = successful advisors / total advisors * 100
    Measures how many advisors ran successfully (STATUS_OK).
    """
    total = sum(counts.values())
    if total == 0:
        return 0.0
    ok_count = counts.get(STATUS_OK, 0)
    return round(ok_count / total * 100, 1)


def _calculate_success_rate(counts: Dict[str, int]) -> float:
    """Calculate success rate from advisor statuses (0-100).

    Success rate = successful advisors / (successful + failed) * 100
    Measures quality of runs that actually executed.
    """
    ok_count = counts.get(STATUS_OK, 0)
    failed_count = counts.get(STATUS_FAILED, 0)
    executed = ok_count + failed_count
    if executed == 0:
        return 100.0  # No failures means 100% success
    return round(ok_count / executed * 100, 1)


def _calculate_token_efficiency(
    tokens: Dict[str, Any], advisors: List[Dict[str, Any]]
) -> float:
    """Calculate token efficiency: output tokens per advisor (0-∞).

    Token efficiency = output tokens / number of advisors that ran
    Measures how efficiently we're generating content.
    """
    output_tokens = tokens.get("output", 0)
    ran_count = sum(
        1 for a in advisors if a.get("status") in (STATUS_OK, STATUS_FAILED)
    )
    if ran_count == 0:
        return 0.0
    return round(output_tokens / ran_count, 1)


def _collect_7day_trends(
    history: List[dict],
    metric_key: str,
    advisors: List[Dict[str, Any]],
    counts: Dict[str, int],
) -> List[float]:
    """Collect 7-day rolling trend data for a performance metric.

    Args:
        history: Previous run summaries (oldest first).
        metric_key: One of 'completion', 'deadline', 'success'.
        advisors: Current run's advisors.
        counts: Current run's status counts.

    Returns:
        List of up to 7 metric values (oldest to newest).
    """
    trends = []

    # Extract historical values
    for run in history[-6:]:  # Keep last 6 runs
        if metric_key == "completion":
            # Reconstruct from historical run data if available
            total = run.get("total", 0)
            skipped = sum(
                1 for a in run.get("advisors", []) if a.get("status") == STATUS_SKIPPED
            )
            if total > 0:
                value = round((total - skipped) / total * 100, 1)
            else:
                value = 0.0
        elif metric_key == "deadline":
            ok = run.get("ok", 0)
            total = run.get("total", 0)
            if total > 0:
                value = round(ok / total * 100, 1)
            else:
                value = 0.0
        elif metric_key == "success":
            ok = run.get("ok", 0)
            failed = run.get("failed", 0)
            executed = ok + failed
            if executed > 0:
                value = round(ok / executed * 100, 1)
            else:
                value = 100.0
        else:
            value = 0.0

        if value is not None:
            trends.append(value)

    # Add current run's metric
    if metric_key == "completion":
        current = _calculate_completion_rate(advisors)
    elif metric_key == "deadline":
        current = _calculate_deadline_adherence(counts)
    elif metric_key == "success":
        current = _calculate_success_rate(counts)
    else:
        current = 0.0

    trends.append(current)

    # Pad with the current value if less than 7 days
    while len(trends) < 7:
        trends.insert(0, trends[0] if trends else 0.0)

    return trends[-7:]  # Return only last 7


def _extract_alerts(briefings: Any = None) -> List[Dict[str, Any]]:
    """Extract alerts and issues from advisor runs.

    Looks for failed advisors and extracts their diagnostics.
    Returns a list of alert objects with details.
    """
    alerts = []
    try:
        if not briefings:
            return alerts

        for briefing in briefings:
            status = str(getattr(briefing, "status", "") or STATUS_SKIPPED)
            if status == STATUS_FAILED:
                key = str(getattr(briefing, "key", "") or "unknown")
                detail = sanitize(getattr(briefing, "text", "") or "")
                if detail:
                    alerts.append(
                        {
                            "type": "advisor_failed",
                            "advisor": key,
                            "detail": detail[:200],
                            "timestamp": _now_utc().isoformat(timespec="seconds"),
                        }
                    )

    except Exception as exc:
        logger.warning("uyarılar çıkarılırken hata: %s", exc)

    return alerts


def _extract_feedback(briefings: Any = None) -> str:
    """Extract AI-driven feedback from Work Analyst or similar advisors.

    Looks for a work_analyst or similar advisor and extracts feedback.
    Returns feedback string or empty string if not available.
    """
    feedback = ""
    try:
        if not briefings:
            return feedback

        # Look for work_analyst, accountability_coach, or leadership_coach briefings
        for briefing in briefings:
            key = str(getattr(briefing, "key", "") or "")
            status = str(getattr(briefing, "status", "") or STATUS_SKIPPED)

            if key in ("work_analyst", "accountability_coach", "leadership_coach"):
                if status == STATUS_OK:
                    text = getattr(briefing, "text", "") or ""
                    # Extract first 400 chars as feedback
                    if text:
                        feedback = sanitize(text[:400])
                        break

    except Exception as exc:
        logger.warning("geri bildirim çıkarılırken hata: %s", exc)

    return feedback


def _performance_snapshot(
    advisors: List[Dict[str, Any]],
    counts: Dict[str, int],
    tokens: Dict[str, Any],
    history: List[dict],
    briefings: Any = None,
) -> Dict[str, Any]:
    """Build the performance metrics section for status.json.

    Aggregates daily metrics, work status, 7-day trends, alerts, and feedback.
    Gracefully handles missing data by providing defaults.

    Args:
        advisors: List of advisor entries from the current run.
        counts: Status counts from current run.
        tokens: Token usage from current run.
        history: Previous run summaries (oldest first, not including current).
        briefings: The briefing objects from supervision (for alerts/feedback).

    Returns:
        Dictionary with performance section ready for status.json.
    """
    now = _now_utc()

    # Calculate daily metrics for this run
    completion_rate = _calculate_completion_rate(advisors)
    deadline_adherence = _calculate_deadline_adherence(counts)
    success_rate = _calculate_success_rate(counts)
    token_efficiency = _calculate_token_efficiency(tokens, advisors)

    # Collect 7-day trends (history doesn't include current run yet)
    completion_7d = _collect_7day_trends(history, "completion", advisors, counts)
    deadline_7d = _collect_7day_trends(history, "deadline", advisors, counts)
    success_7d = _collect_7day_trends(history, "success", advisors, counts)

    # Extract alerts and feedback
    alerts = _extract_alerts(briefings)
    feedback = _extract_feedback(briefings)

    return {
        "daily_metrics": {
            "completion_rate": completion_rate,
            "deadline_adherence": deadline_adherence,
            "success_rate": success_rate,
            "token_efficiency": token_efficiency,
            "last_update": now.isoformat(timespec="seconds"),
        },
        "work_status": {
            "meeting_hours": 0.0,  # Extracted from calendar if available
            "focus_time_hours": 0.0,  # Calculated from available slots
            "email_response_time_hours": 0.0,  # From gmail metrics if available
            "critical_alerts": len(alerts),
        },
        "trends": {
            "completion_7d": completion_7d,
            "deadline_7d": deadline_7d,
            "success_7d": success_7d,
        },
        "alerts": alerts,
        "feedback": feedback,
    }


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
    duration = (
        round(float(duration_seconds), 1) if duration_seconds is not None else None
    )
    batch = _batch_snapshot()
    tokens = _tokens_snapshot()

    # How this run was asked to work, and how much of it was actually new.
    mode = str(getattr(supervision, "mode", MODE_FULL) or MODE_FULL)
    new_findings = sum(entry["new_findings"] or 0 for entry in advisors)
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
    # Note: performance metrics use history before we append current run
    performance = _performance_snapshot(advisors, counts, tokens, history, briefings)

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
        "accountability": _accountability_snapshot(briefings),
        "gmail": _gmail_snapshot(briefings),
        "calendar": _calendar_snapshot(briefings),
        "integrations": _integrations_snapshot(),
        "performance": performance,
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
    "ADVISOR_LIVE",
    "ADVISOR_META",
    "ADVISOR_RETIRED",
    "DEFAULT_META",
    "HISTORY_LIMIT",
    "TRIGGERS",
    "TRIGGER_ALWAYS",
    "TRIGGER_DATA",
    "TRIGGER_USER_REQUESTED",
    "TRIGGER_WEEKLY",
    "advisor_data_owner",
    "advisor_meta",
    "advisor_token_ceiling",
    "advisor_trigger",
    "advisors_with_trigger",
    "is_live",
    "live_advisor_keys",
    "retired_advisor_keys",
    "IntegrationMetrics",
    "build_status",
    "integration_metrics_file_path",
    "record_gmail_fetch",
    "record_calendar_fetch",
    "sanitize",
    "status_file_path",
    "write_status_report",
    # Performance metrics functions
    "_calculate_completion_rate",
    "_calculate_deadline_adherence",
    "_calculate_success_rate",
    "_calculate_token_efficiency",
    "_collect_7day_trends",
    "_extract_alerts",
    "_extract_feedback",
    "_performance_snapshot",
]
