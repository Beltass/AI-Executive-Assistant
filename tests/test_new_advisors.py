"""Tests for the four Phase 3 advisors (offline, no network, no credentials).

Covered here:
- Banka & Çağrı Merkezi Proje Uzmanı: skipped without an LLM key, a dead feed
  degrades instead of failing, real headlines reach the batched prompt, and the
  compliance caveat is always appended.
- Hesap Sorucu Koç: the no-prior-state path, streak arithmetic (continue /
  reset / same-day re-run), task extraction from the other advisors' briefings,
  and the generic nudge when every other section failed.
- Gün Başı Operasyon Brifingi: skipped without Google OAuth, works from fetched
  Gmail/Calendar facts, and never dumps a raw e-mail body.
- İngilizce & Yönetici İletişimi Koçu: skipped without a key, rotating weekly
  focus.
- The batch parser and the batched run handle the new sections.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from ai_assistant import config
from ai_assistant.advisors import Briefing
from ai_assistant.advisors._batch import (
    SECTION_MARKER,
    collect_sections,
    parse_batch_response,
)
from ai_assistant.advisors import accountability_coach as ac_module
from ai_assistant.advisors import banking_cc_projects as banking_module
from ai_assistant.advisors import daily_ops_briefing as ops_module
from ai_assistant.advisors.accountability_coach import (
    AccountabilityCoachAdvisor,
    AccountabilityState,
    extract_task,
)
from ai_assistant.advisors.banking_cc_projects import BankingCcProjectsAdvisor
from ai_assistant.advisors.daily_ops_briefing import DailyOpsBriefingAdvisor
from ai_assistant.advisors.language_coach import (
    WEEKLY_FOCUS,
    LanguageCoachAdvisor,
    _weekly_focus,
)
from ai_assistant.advisors._rss import FeedItem
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED, llm
from ai_assistant.operations_manager import OperationsManager

FAKE_KEY = "AQ.FAKE-secret-key-should-never-leak-654321"

_ENV_VARS = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "USER_SECTOR",
    "BANKING_NEWS_RSS_URL",
    "BANKING_SECURITY_RSS_URL",
    "ACCOUNTABILITY_STATE_FILE",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_CREDENTIALS_FILE",
    "GOOGLE_TOKEN_FILE",
    "OPS_BRIEFING_MAX_EMAILS",
    "OPS_BRIEFING_EMAIL_WINDOW",
]


@pytest.fixture()
def blank_env(monkeypatch, tmp_path):
    """No env vars, no built-in defaults, and a cwd-safe state file location."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})
    # Point the Google token lookup at a path that cannot exist.
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "missing-token.json"))
    yield


# --- Banka & Çağrı Merkezi Proje Uzmanı --------------------------------------


def test_banking_skipped_without_llm_key(blank_env):
    briefing = BankingCcProjectsAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "GEMINI_API_KEY" in briefing.text


def test_banking_stays_out_of_the_batch_without_a_key(blank_env):
    assert BankingCcProjectsAdvisor().batch_section() is None


def test_banking_dead_feed_degrades_to_llm_only(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("BANKING_NEWS_RSS_URL", "https://example.invalid/feed")

    def boom(url, limit=6):
        raise RuntimeError("feed unreachable")

    monkeypatch.setattr(banking_module, "fetch_feed_items", boom)

    section = BankingCcProjectsAdvisor().batch_section()
    assert section is not None
    # No headlines, so the prompt tells the model to use root domains only.
    assert "Canlı bir haber akışı sağlanmadı" in section.user_prompt


def test_banking_prompt_carries_real_headlines(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("BANKING_NEWS_RSS_URL", "https://example.org/feed")
    monkeypatch.setattr(
        banking_module,
        "fetch_feed_items",
        lambda url, limit=6: [
            FeedItem(title="BDDK yeni düzenleme", link="https://example.org/a")
        ],
    )

    section = BankingCcProjectsAdvisor().batch_section()
    assert "https://example.org/a" in section.user_prompt
    assert "dış kaynak" in section.user_prompt.lower()


def test_banking_briefing_always_carries_the_compliance_caveat(blank_env):
    briefing = BankingCcProjectsAdvisor().briefing_from_batch("Bölüm gövdesi.")
    assert briefing.status == STATUS_OK
    assert "uyum/hukuk" in briefing.text
    assert "https://www.bddk.org.tr" in briefing.text
    assert "🔎 Bağlantıları açılışta doğrulayın." in briefing.text


def test_banking_persona_is_a_deep_domain_expert():
    prompt = banking_module.SYSTEM_PROMPT + banking_module._BRIEF
    for term in ("SLA", "KVKK", "PCI-DSS", "transition", "FCR"):
        assert term in prompt
    # It must refuse to invent regulatory specifics.
    assert "UYDURMA" in banking_module.SYSTEM_PROMPT


def test_banking_persona_names_the_real_governance_frameworks():
    """The persona is grounded in frameworks that actually exist, by name."""
    prompt = banking_module.SYSTEM_PROMPT + banking_module._BRIEF
    for framework in (
        "BDDK",
        "Destek Hizmeti",
        "Bilgi Sistemleri",
        "KVKK",
        "VERBİS",
        "ISO/IEC 27001",
        "ISO/IEC 27002",
        "SOC 2",
        "PCI-DSS",
    ):
        assert framework in prompt, framework


def test_banking_brief_covers_the_five_mandated_blocks():
    brief = banking_module._BRIEF
    for heading in (
        "📦 Dış kaynak yönetişimi",
        "🔐 Bilgi güvenliği kontrolleri",
        "⚖️ Uyum",
        "🚨 Riskler ve erken uyarı sinyalleri",
        "🔬 Teknoloji ve yeni riskler",
        "✅ Bugünün görevi",
    ):
        assert heading in brief, heading
    # The security block must be concrete about contact-center controls.
    for control in (
        "right-to-audit",
        "MFA",
        "DTMF",
        "VDI",
        "DLP",
        "SIEM",
        "alt yüklenici",
        "en az yetki",
    ):
        assert control in brief, control


def test_banking_focus_rotates_day_by_day():
    """Consecutive days must lead with a different deep-dive focus."""
    start = date(2026, 1, 1)
    focuses = [
        banking_module._daily_focus(start + timedelta(days=offset))
        for offset in range(len(banking_module.DAILY_FOCUS))
    ]
    # A full cycle visits every focus exactly once, so no two adjacent days
    # (and no day within a cycle) repeat.
    assert sorted(focuses) == sorted(banking_module.DAILY_FOCUS)
    # And the cycle then repeats predictably.
    assert (
        banking_module._daily_focus(
            start + timedelta(days=len(banking_module.DAILY_FOCUS))
        )
        == focuses[0]
    )


def test_banking_prompt_leads_with_todays_focus(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setattr(banking_module, "fetch_feed_items", lambda url, limit=5: [])
    section = BankingCcProjectsAdvisor().batch_section()
    assert "BUGÜNÜN DERİNLEŞME ODAĞI:" in section.user_prompt
    assert banking_module._daily_focus() in section.user_prompt


def test_banking_merges_both_news_feeds(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("BANKING_NEWS_RSS_URL", "https://example.org/banking")
    monkeypatch.setenv("BANKING_SECURITY_RSS_URL", "https://example.org/security")

    def fake_fetch(url, limit=5):
        if url.endswith("/security"):
            return [
                FeedItem(title="KVKK veri ihlali kararı", link="https://x.test/sec"),
                # Duplicate title across feeds must be collapsed.
                FeedItem(title="Ortak başlık", link="https://x.test/dup"),
            ]
        return [
            FeedItem(title="Dış kaynak ihalesi", link="https://x.test/bank"),
            FeedItem(title="Ortak başlık", link="https://x.test/dup"),
        ]

    monkeypatch.setattr(banking_module, "fetch_feed_items", fake_fetch)

    advisor = BankingCcProjectsAdvisor()
    prompt = advisor.batch_section().user_prompt
    assert "https://x.test/sec" in prompt
    assert "https://x.test/bank" in prompt
    assert prompt.count("Ortak başlık") == 1
    # Fetched once and reused, even across repeated prompt builds.
    assert len(advisor._fetch_items()) == 3


def test_banking_survives_one_dead_feed_of_two(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("BANKING_NEWS_RSS_URL", "https://example.org/banking")
    monkeypatch.setenv("BANKING_SECURITY_RSS_URL", "https://example.invalid/feed")

    def fake_fetch(url, limit=5):
        if "invalid" in url:
            raise RuntimeError("feed unreachable")
        return [FeedItem(title="Canlı başlık", link="https://x.test/live")]

    monkeypatch.setattr(banking_module, "fetch_feed_items", fake_fetch)

    prompt = BankingCcProjectsAdvisor().batch_section().user_prompt
    assert "https://x.test/live" in prompt


def test_banking_always_demands_official_sources(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setattr(banking_module, "fetch_feed_items", lambda url, limit=5: [])
    prompt = BankingCcProjectsAdvisor().batch_section().user_prompt
    assert "PCI Security Standards Council" in prompt
    assert "derin URL" in prompt


def test_banking_caveat_points_at_compliance_and_standards_bodies(blank_env):
    briefing = BankingCcProjectsAdvisor().briefing_from_batch("Gövde.")
    for domain in (
        "https://www.bddk.org.tr",
        "https://www.kvkk.gov.tr",
        "https://www.iso.org",
        "https://www.pcisecuritystandards.org",
    ):
        assert domain in briefing.text, domain
    assert "mevzuat detaylarını" in briefing.text


# --- Hesap Sorucu Koç ---------------------------------------------------------


def _briefing(key: str, title: str, task: str) -> Briefing:
    text = (
        "Giriş paragrafı.\n\n"
        "*Derinlemesine bölüm*\nBir şeyler.\n\n"
        "📚 *Kaynaklar*\n- https://example.org\n\n"
        f"*✅ Bugünün görevi*: {task}\n"
    )
    return Briefing(key=key, title=title, status=STATUS_OK, text=text)


def test_extract_task_same_line():
    task = extract_task("*✅ Bugünün görevi*: 20 dakika ayır ve SLA metnini oku.")
    assert task == "20 dakika ayır ve SLA metnini oku."


def test_extract_task_next_line():
    text = (
        "### ✅ Bugünün görevi\nTek bir vendor sözleşmesini gözden geçir.\n\n## Başka"
    )
    assert extract_task(text) == "Tek bir vendor sözleşmesini gözden geçir."


def test_extract_task_returns_none_without_a_marker():
    assert extract_task("Görevsiz bir brifing.") is None
    assert extract_task("") is None


def test_accountability_first_run_has_no_prior_state(monkeypatch, tmp_path, blank_env):
    state_file = tmp_path / "state" / "accountability.json"
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(state_file))

    advisor = AccountabilityCoachAdvisor()
    advisor.observe(
        [_briefing("leadership_coach", "Liderlik Koçu", "Geri bildirim ver.")]
    )
    briefing = advisor.generate_briefing()

    assert briefing.status == STATUS_OK
    # Fresh start: no crash, day-1 streak, today's list present.
    assert "Önceki güne ait kayıt bulamadım" in briefing.text
    assert "1. gün" in briefing.text
    assert "Geri bildirim ver." in briefing.text
    # And the state file was created for the next run.
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["streak"] == 1
    assert saved["last_date"] == date.today().isoformat()
    assert len(saved["last_tasks"]) == 1


def test_accountability_state_round_trips_from_a_committed_file(
    monkeypatch, tmp_path, blank_env
):
    """The CI path: yesterday's committed file is read back and grown.

    This is what makes the streak durable — the workflow commits
    ``.assistant_state/accountability.json`` back to ``main`` and the next run
    checks it out. Here the "checkout" is simulated by writing the file that a
    previous run produced, byte for byte, and re-reading it.
    """
    state_file = tmp_path / ".assistant_state" / "accountability.json"
    state_file.parent.mkdir(parents=True)
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(state_file))

    # --- run 1: nothing committed yet, a fresh start that writes the file ---
    first = AccountabilityCoachAdvisor()
    first.observe([_briefing("career_hr", "Kariyer & İK", "CV'ni güncelle.")])
    assert first.generate_briefing().status == STATUS_OK

    committed = state_file.read_text(encoding="utf-8")
    assert json.loads(committed)["streak"] == 1

    # --- the commit-back: rewrite the file exactly as git would restore it ---
    state_file.unlink()
    state_file.parent.rmdir()
    state_file.parent.mkdir()
    state_file.write_text(committed, encoding="utf-8")

    # --- run 2, one day later: the streak continues instead of restarting ---
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    data["last_date"] = yesterday
    data["history"] = {yesterday: data["last_tasks"]}
    state_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    second = AccountabilityCoachAdvisor()
    second.observe([_briefing("career_hr", "Kariyer & İK", "Bugünkü görev.")])
    briefing = second.generate_briefing()

    assert briefing.status == STATUS_OK
    assert "CV'ni güncelle." in briefing.text  # yesterday's ask, restated
    assert "*2 gün*" in briefing.text
    reloaded = json.loads(state_file.read_text(encoding="utf-8"))
    assert reloaded["streak"] == 2
    assert reloaded["last_date"] == today.isoformat()
    assert reloaded["history"][yesterday]  # earlier day kept for the next run


def test_accountability_default_state_path_is_the_committed_one():
    """The default must match the path the workflow commits back."""
    assert (
        config.DEFAULT_SETTINGS["ACCOUNTABILITY_STATE_FILE"]
        == ".assistant_state/accountability.json"
    )


def test_accountability_skipped_when_nothing_to_track(monkeypatch, tmp_path, blank_env):
    monkeypatch.setenv(
        "ACCOUNTABILITY_STATE_FILE", str(tmp_path / "accountability.json")
    )
    advisor = AccountabilityCoachAdvisor()
    advisor.observe(
        [Briefing(key="x", title="X", status=STATUS_SKIPPED, text="atlandı")]
    )
    briefing = advisor.generate_briefing()
    assert briefing.status == STATUS_SKIPPED


def test_accountability_asks_about_yesterday_and_grows_the_streak(
    monkeypatch, tmp_path, blank_env
):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    state_file = tmp_path / "accountability.json"
    state_file.write_text(
        json.dumps(
            {
                "streak": 4,
                "last_date": yesterday,
                "last_tasks": ["*Liderlik Koçu* — Dünkü görev."],
                "history": {yesterday: ["*Liderlik Koçu* — Dünkü görev."]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(state_file))

    advisor = AccountabilityCoachAdvisor()
    advisor.observe([_briefing("career_hr", "Kariyer & İK", "CV'ni güncelle.")])
    briefing = advisor.generate_briefing()

    assert briefing.status == STATUS_OK
    assert "yaptın mı?" in briefing.text
    assert "Dünkü görev." in briefing.text
    assert "*5 gün*" in briefing.text  # 4 + 1
    assert json.loads(state_file.read_text(encoding="utf-8"))["streak"] == 5


def test_accountability_generic_nudge_when_other_sections_failed(
    monkeypatch, tmp_path, blank_env
):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    state_file = tmp_path / "accountability.json"
    state_file.write_text(
        json.dumps(
            {
                "streak": 2,
                "last_date": yesterday,
                "last_tasks": ["*Liderlik Koçu* — Dünkü görev."],
                "history": {yesterday: ["*Liderlik Koçu* — Dünkü görev."]},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(state_file))

    advisor = AccountabilityCoachAdvisor()
    advisor.observe(
        [Briefing(key="ai_news", title="AI", status=STATUS_FAILED, text="hata")]
    )
    briefing = advisor.generate_briefing()

    assert briefing.status == STATUS_OK
    assert "Bugün diğer danışmanlardan görev gelmedi" in briefing.text


@pytest.mark.parametrize(
    "last_date_offset, previous_streak, expected",
    [
        (1, 4, 5),  # yesterday -> chain continues
        (3, 9, 1),  # a gap -> reset to day 1
        (0, 6, 6),  # same-day re-run -> unchanged
    ],
)
def test_streak_arithmetic(last_date_offset, previous_streak, expected):
    today = date.today()
    state = AccountabilityState(
        streak=previous_streak,
        last_date=(today - timedelta(days=last_date_offset)).isoformat(),
        last_tasks=["görev"],
    )
    assert AccountabilityCoachAdvisor._next_streak(state, today) == expected


def test_streak_starts_at_one_without_any_state():
    assert (
        AccountabilityCoachAdvisor._next_streak(AccountabilityState(), date.today())
        == 1
    )


def test_accountability_survives_a_corrupt_state_file(monkeypatch, tmp_path, blank_env):
    state_file = tmp_path / "accountability.json"
    state_file.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(state_file))

    advisor = AccountabilityCoachAdvisor()
    advisor.observe([_briefing("free_certs", "Sertifika", "Bir kursa kaydol.")])
    briefing = advisor.generate_briefing()
    assert briefing.status == STATUS_OK


def test_accountability_survives_an_unwritable_state_path(
    monkeypatch, tmp_path, blank_env
):
    """The GitHub Actions case: writing may fail; the briefing must not."""
    monkeypatch.setenv("ACCOUNTABILITY_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(
        ac_module.os,
        "makedirs",
        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only fs")),
    )

    advisor = AccountabilityCoachAdvisor()
    advisor.observe([_briefing("free_certs", "Sertifika", "Bir kursa kaydol.")])
    assert advisor.generate_briefing().status == STATUS_OK


def test_accountability_never_joins_the_batch(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    assert AccountabilityCoachAdvisor().batch_section() is None


def test_manager_feeds_the_coach_the_other_briefings(monkeypatch, tmp_path, blank_env):
    """End to end through the supervisor: the coach sees the earlier tasks."""
    monkeypatch.setenv(
        "ACCOUNTABILITY_STATE_FILE", str(tmp_path / "accountability.json")
    )

    class _TaskAdvisor(BankingCcProjectsAdvisor):
        def _generate(self):
            return self.ok("Gövde.\n\n*✅ Bugünün görevi*: SLA metnini oku.")

    supervision = OperationsManager(
        advisors=[_TaskAdvisor(), AccountabilityCoachAdvisor()]
    ).run()

    coach = supervision.briefings[-1]
    assert coach.key == "accountability_coach"
    assert coach.status == STATUS_OK
    assert "SLA metnini oku." in coach.text


# --- Gün Başı Operasyon Brifingi ---------------------------------------------


def test_ops_briefing_skipped_without_google_auth(blank_env):
    briefing = DailyOpsBriefingAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "google_auth" in briefing.text


def test_ops_briefing_stays_out_of_the_batch_without_google(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    assert DailyOpsBriefingAdvisor().batch_section() is None


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeMessages:
    def list(self, **kwargs):
        return _FakeRequest({"messages": [{"id": "m1"}]})

    def get(self, **kwargs):
        return _FakeRequest(
            {
                "labelIds": ["UNREAD", "IMPORTANT"],
                "snippet": "Gizli gövde " * 60,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "vendor@example.com"},
                        {"name": "Subject", "value": "SLA revizyonu"},
                    ]
                },
            }
        )


class _FakeUsers:
    def messages(self):
        return _FakeMessages()


class _FakeGmail:
    def users(self):
        return _FakeUsers()


class _FakeEvents:
    def list(self, **kwargs):
        return _FakeRequest(
            {
                "items": [
                    {
                        "summary": "Vendor değerlendirme",
                        "start": {"dateTime": "2026-07-30T09:00:00+03:00"},
                        "end": {"dateTime": "2026-07-30T10:00:00+03:00"},
                        "attendees": [{"email": "a@b.c"}, {"email": "d@e.f"}],
                        "location": "Toplantı Odası 3",
                    }
                ]
            }
        )


class _FakeCalendar:
    def events(self):
        return _FakeEvents()


@pytest.fixture()
def google_ready(monkeypatch, blank_env):
    """Pretend Google OAuth is configured and both APIs answer."""
    monkeypatch.setattr(ops_module.google_auth, "google_configured", lambda: True)
    monkeypatch.setattr(ops_module.google_auth, "get_credentials", lambda: object())

    import googleapiclient.discovery as discovery

    def fake_build(service, version, credentials=None, cache_discovery=False):
        return _FakeGmail() if service == "gmail" else _FakeCalendar()

    monkeypatch.setattr(discovery, "build", fake_build)
    yield


def test_ops_briefing_without_llm_returns_the_gathered_facts(google_ready):
    briefing = DailyOpsBriefingAdvisor().generate_briefing()
    assert briefing.status == STATUS_OK
    assert "SLA revizyonu" in briefing.text
    assert "Vendor değerlendirme" in briefing.text
    assert "09:00-10:00" in briefing.text


def test_ops_briefing_never_dumps_a_full_email_body(google_ready):
    briefing = DailyOpsBriefingAdvisor().generate_briefing()
    # The fake snippet is ~720 chars; it must be truncated before use.
    assert "Gizli gövde " * 60 not in briefing.text
    assert "…" in briefing.text


def test_ops_briefing_joins_the_batch_with_its_facts(monkeypatch, google_ready):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    section = DailyOpsBriefingAdvisor().batch_section()
    assert section is not None
    assert section.key == "daily_ops_briefing"
    assert "SLA revizyonu" in section.user_prompt
    assert "Vendor değerlendirme" in section.user_prompt


def test_ops_briefing_failed_when_google_calls_break(monkeypatch, blank_env):
    monkeypatch.setattr(ops_module.google_auth, "google_configured", lambda: True)
    monkeypatch.setattr(ops_module.google_auth, "get_credentials", lambda: object())

    import googleapiclient.discovery as discovery

    def boom(*args, **kwargs):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(discovery, "build", boom)

    briefing = DailyOpsBriefingAdvisor().generate_briefing()
    assert briefing.status == STATUS_FAILED
    assert "alınamadı" in briefing.text


def test_ops_briefing_bounds_are_sane(monkeypatch, blank_env):
    monkeypatch.setenv("OPS_BRIEFING_MAX_EMAILS", "999")
    assert ops_module._max_emails() == 25
    monkeypatch.setenv("OPS_BRIEFING_MAX_EMAILS", "not-a-number")
    assert ops_module._max_emails() == ops_module.DEFAULT_MAX_EMAILS
    monkeypatch.setenv("OPS_BRIEFING_EMAIL_WINDOW", "; drop table")
    assert ops_module._email_window() == ops_module.DEFAULT_EMAIL_WINDOW
    monkeypatch.setenv("OPS_BRIEFING_EMAIL_WINDOW", "12h")
    assert ops_module._email_window() == "12h"


# --- İngilizce & Yönetici İletişimi Koçu --------------------------------------


def test_language_coach_skipped_without_key(blank_env):
    briefing = LanguageCoachAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED


def test_language_coach_focus_rotates_weekly():
    seen = {_weekly_focus(date(2026, 1, 5) + timedelta(weeks=i)) for i in range(4)}
    assert seen == set(WEEKLY_FOCUS)


def test_language_coach_prompt_has_exercise_and_model_answer(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    section = LanguageCoachAdvisor().batch_section()
    assert section is not None
    assert "Bu cümleyi İngilizce kur" in section.user_prompt
    assert "önce kendin dene" in section.user_prompt
    assert "Örnek cevap" in section.user_prompt


# --- Batching with the new sections -------------------------------------------


def test_batch_parser_handles_the_new_sections():
    text = (
        f"{SECTION_MARKER} banking_cc_projects\nBanka bölümü.\n\n"
        f"{SECTION_MARKER} daily_ops_briefing\nOperasyon bölümü.\n\n"
        f"{SECTION_MARKER} language_coach\nDil bölümü.\n"
    )
    parsed = parse_batch_response(
        text, ["banking_cc_projects", "daily_ops_briefing", "language_coach"]
    )
    assert parsed == {
        "banking_cc_projects": "Banka bölümü.",
        "daily_ops_briefing": "Operasyon bölümü.",
        "language_coach": "Dil bölümü.",
    }


def test_new_llm_advisors_share_one_batched_call(monkeypatch, google_ready, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("DIGEST_BATCH_MODE", raising=False)
    monkeypatch.setenv(
        "ACCOUNTABILITY_STATE_FILE", str(tmp_path / "accountability.json")
    )
    monkeypatch.setattr(banking_module, "fetch_feed_items", lambda url, limit=6: [])

    calls = []
    response = (
        f"{SECTION_MARKER} banking_cc_projects\n"
        "Banka gövdesi.\n\n*✅ Bugünün görevi*: SLA metnini oku.\n\n"
        f"{SECTION_MARKER} daily_ops_briefing\nOperasyon gövdesi.\n\n"
        f"{SECTION_MARKER} language_coach\nDil gövdesi.\n"
    )

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        calls.append(user_prompt)
        return response

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    team = [
        BankingCcProjectsAdvisor(),
        DailyOpsBriefingAdvisor(),
        LanguageCoachAdvisor(),
        AccountabilityCoachAdvisor(),
    ]
    supervision = OperationsManager(advisors=team).run()

    assert len(calls) == 1  # ONE Gemini request for the whole team
    statuses = {b.key: b.status for b in supervision.briefings}
    assert statuses == {
        "banking_cc_projects": STATUS_OK,
        "daily_ops_briefing": STATUS_OK,
        "language_coach": STATUS_OK,
        "accountability_coach": STATUS_OK,
    }
    coach = supervision.briefings[-1]
    assert "SLA metnini oku." in coach.text  # picked the task out of the batch
    assert all(FAKE_KEY not in b.text for b in supervision.briefings)


def test_new_advisors_stay_out_of_the_batch_without_a_key(blank_env):
    assert (
        collect_sections(
            [
                BankingCcProjectsAdvisor(),
                DailyOpsBriefingAdvisor(),
                LanguageCoachAdvisor(),
                AccountabilityCoachAdvisor(),
            ]
        )
        == []
    )
