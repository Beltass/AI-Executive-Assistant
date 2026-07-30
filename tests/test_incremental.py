"""Tests for incremental runs and the two Phase 4 advisors (fully offline).

Covered here:

* run modes: ``full`` (the 10:00 İstanbul flagship) vs ``incremental`` (the
  14:00/18:00/22:00 top-ups);
* the quiet-run contract: an incremental run with nothing new writes
  ``status.json`` but sends NOTHING to Slack, while a full run always sends;
* the ledger is only written after a SUCCESSFUL delivery;
* Yapay Zeka Ustalığı Koçu and Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı:
  skipped without an LLM key, feed items deduplicated, personas grounded;
* the batch parser and ``collect_sections`` handle the new sections and skip
  the advisors that have nothing new (so a quiet run costs no model call).
"""

from __future__ import annotations

import json

import pytest

from ai_assistant import config, memory
from ai_assistant.advisors import Advisor, Briefing, all_advisors, is_quiet
from ai_assistant.advisors import ai_mastery as mastery_module
from ai_assistant.advisors import cx_research as cx_module
from ai_assistant.advisors._batch import (
    SECTION_MARKER,
    collect_sections,
    parse_batch_response,
    run_batch,
)
from ai_assistant.advisors._rss import FeedItem
from ai_assistant.advisors.ai_mastery import AiMasteryAdvisor
from ai_assistant.advisors.cx_research import CxResearchAdvisor
from ai_assistant.daily_digest import Digest, build_digest
from ai_assistant.integrations import STATUS_OK, STATUS_SKIPPED, llm
from ai_assistant.notifiers import slack_notifier
from ai_assistant.operations_manager import OperationsManager, Supervision
from ai_assistant.status_report import build_status

FAKE_KEY = "AQ.FAKE-secret-key-should-never-leak-654321"

_ENV_VARS = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "BRIEFING_MODE",
    "SKIP_SLACK_WHEN_NOTHING_NEW",
    "SLACK_WEBHOOK_URL",
    "SLACK_BOT_TOKEN",
    "SLACK_CHANNEL",
    "AI_MASTERY_RSS_URL",
    "AI_MASTERY_LEVEL",
    "CX_RESEARCH_RSS_URL",
    "USER_SECTOR",
]


@pytest.fixture()
def blank_env(monkeypatch, tmp_path):
    """No env vars, no built-in defaults, no credentials of any kind."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "missing-token.json"))
    yield


# --- run mode ---------------------------------------------------------------


def test_default_mode_is_full(blank_env):
    assert config.briefing_mode() == config.MODE_FULL
    assert config.is_incremental() is False
    assert config.mode_label() == "tam brifing"


def test_incremental_mode_is_opt_in(blank_env, monkeypatch):
    monkeypatch.setenv("BRIEFING_MODE", "incremental")
    assert config.is_incremental() is True
    assert config.mode_label() == "artımlı"


def test_unknown_mode_never_downgrades_the_daily_briefing(blank_env, monkeypatch):
    """A typo must not silently turn the flagship run into a quiet one."""
    monkeypatch.setenv("BRIEFING_MODE", "artimli")
    assert config.briefing_mode() == config.MODE_FULL


# --- who works on an incremental run ----------------------------------------


class _Quiet(Advisor):
    key = "quiet_persona"
    title = "Sessiz Danışman"

    def _generate(self) -> Briefing:  # pragma: no cover - never reached quietly
        return self.ok("gövde")


class _Noisy(Advisor):
    key = "noisy_source"
    title = "Bulgu Kaynağı"
    incremental_source = True

    def __init__(self, count: int = 2) -> None:
        self._count = count

    def new_finding_count(self) -> int:
        return self._count

    def _generate(self) -> Briefing:
        return self.ok("yeni bulgular")


def test_nobody_is_quiet_on_a_full_run(blank_env):
    assert is_quiet(_Quiet()) is False
    assert is_quiet(_Noisy(0)) is False


def test_incremental_silences_the_timeless_personas(blank_env, monkeypatch):
    monkeypatch.setenv("BRIEFING_MODE", "incremental")
    assert is_quiet(_Quiet()) is True
    assert is_quiet(_Noisy(0)) is True  # feed-driven, but nothing new
    assert is_quiet(_Noisy(3)) is False


def test_incremental_run_collapses_quiet_advisors(blank_env, monkeypatch):
    monkeypatch.setenv("BRIEFING_MODE", "incremental")
    supervision = OperationsManager(advisors=[_Quiet(), _Noisy(2)]).run()

    quiet, noisy = supervision.briefings
    assert quiet.nothing_new is True
    assert quiet.status == STATUS_SKIPPED
    assert quiet.text == "yeni bulgu yok"
    assert noisy.status == STATUS_OK
    assert noisy.new_findings == 2

    assert supervision.mode == config.MODE_INCREMENTAL
    assert supervision.new_findings == 2
    assert supervision.has_new_findings is True


def test_a_quiet_incremental_run_makes_no_model_call(blank_env, monkeypatch):
    monkeypatch.setenv("BRIEFING_MODE", "incremental")
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)

    def explode(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("the LLM must not be called when nothing is new")

    monkeypatch.setattr(llm, "generate_text", explode)

    # Even LLM-backed advisors are kept out of the batch when they are quiet.
    assert collect_sections([_Quiet(), _Noisy(0)]) == []
    assert run_batch([_Quiet(), _Noisy(0)]) == {}
    supervision = OperationsManager(advisors=[_Quiet(), _Noisy(0)]).run()
    assert all(b.nothing_new for b in supervision.briefings)
    assert supervision.new_findings == 0


def test_digest_collapses_the_quiet_advisors_into_one_line(blank_env, monkeypatch):
    monkeypatch.setenv("BRIEFING_MODE", "incremental")
    supervision = OperationsManager(advisors=[_Quiet(), _Noisy(1)]).run()
    digest = build_digest(supervision)

    assert "🔄 Ara Brifing" in digest.text
    assert "🟰 yeni bulgu yok: Sessiz Danışman" in digest.text
    # The quiet advisor gets ONE line, not a section of its own.
    assert "## Sessiz Danışman" not in digest.text
    assert "## Bulgu Kaynağı [OK]" in digest.text


def test_full_digest_still_lists_every_advisor(blank_env):
    supervision = OperationsManager(advisors=[_Quiet(), _Noisy(1)]).run()
    digest = build_digest(supervision)
    assert "🗓️ Günlük Brifing" in digest.text
    assert "## Sessiz Danışman [OK]" in digest.text


# --- Slack: when do we actually interrupt the user? -------------------------


def _digest(mode, briefings):
    return Digest(
        text="brifing gövdesi", supervision=Supervision(briefings=briefings, mode=mode)
    )


def test_full_mode_always_sends(blank_env):
    quiet = Briefing(
        key="q", title="Q", status=STATUS_SKIPPED, new_findings=0, nothing_new=True
    )
    assert slack_notifier.should_send(_digest(config.MODE_FULL, [quiet])) is True


def test_incremental_sends_only_when_something_is_new(blank_env):
    quiet = Briefing(
        key="q", title="Q", status=STATUS_SKIPPED, new_findings=0, nothing_new=True
    )
    fresh = Briefing(key="n", title="N", status=STATUS_OK, text="x", new_findings=2)

    assert slack_notifier.should_send(_digest(config.MODE_INCREMENTAL, [quiet])) is False
    assert slack_notifier.should_send(
        _digest(config.MODE_INCREMENTAL, [quiet, fresh])
    ) is True


def test_quiet_incremental_can_be_forced_to_send(blank_env, monkeypatch):
    monkeypatch.setenv("SKIP_SLACK_WHEN_NOTHING_NEW", "false")
    quiet = Briefing(
        key="q", title="Q", status=STATUS_SKIPPED, new_findings=0, nothing_new=True
    )
    assert slack_notifier.should_send(_digest(config.MODE_INCREMENTAL, [quiet])) is True


def _capture_sends(monkeypatch):
    sent = []

    def fake_send(text, blocks=None):
        sent.append(text)
        from ai_assistant.integrations._common import ok

        return ok(slack_notifier.NAME, "test")

    monkeypatch.setattr(slack_notifier, "send_message", fake_send)
    return sent


def test_quiet_incremental_run_skips_slack_but_still_writes_status(
    blank_env, monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("BRIEFING_MODE", "incremental")
    status_path = tmp_path / "status.json"
    monkeypatch.setenv("STATUS_REPORT_FILE", str(status_path))
    sent = _capture_sends(monkeypatch)

    assert slack_notifier.main() == 0

    assert sent == []  # the channel is left alone
    out = capsys.readouterr().out
    assert slack_notifier.NOTHING_NEW_DETAIL in out

    document = json.loads(status_path.read_text(encoding="utf-8"))
    assert document["run"]["mode"] == "incremental"
    assert document["run"]["mode_label"] == "artımlı"
    assert document["run"]["new_findings"] == 0
    assert document["run"]["nothing_new_count"] > 0
    assert document["slack"]["status"] == STATUS_SKIPPED


def test_full_run_sends_even_with_nothing_new(blank_env, monkeypatch, tmp_path):
    status_path = tmp_path / "status.json"
    monkeypatch.setenv("STATUS_REPORT_FILE", str(status_path))
    sent = _capture_sends(monkeypatch)

    assert slack_notifier.main() == 0

    assert len(sent) == 1
    document = json.loads(status_path.read_text(encoding="utf-8"))
    assert document["run"]["mode"] == "full"
    assert document["slack"]["status"] == STATUS_OK


# --- the ledger is only written after a successful delivery -----------------


def test_findings_are_remembered_only_after_a_successful_send(blank_env, tmp_path):
    memory.reset(path=str(tmp_path / "findings.json"))
    memory.filter_new_items(
        "ai_news", [FeedItem(title="Haber", link="https://example.org/a")]
    )

    from ai_assistant.integrations._common import failed, ok

    slack_notifier._remember_delivered(failed(slack_notifier.NAME, "HTTP 500"))
    assert not (tmp_path / "findings.json").exists()
    # Not delivered -> still new next time.
    assert memory.shared().is_new(
        "ai_news", memory.url_fingerprint("https://example.org/a")
    )

    memory.filter_new_items(
        "ai_news", [FeedItem(title="Haber", link="https://example.org/a")]
    )
    slack_notifier._remember_delivered(ok(slack_notifier.NAME, "webhook — HTTP 200"))
    assert (tmp_path / "findings.json").exists()
    assert not memory.shared().is_new(
        "ai_news", memory.url_fingerprint("https://example.org/a")
    )


# --- the two new advisors ---------------------------------------------------


@pytest.mark.parametrize("advisor_cls", [AiMasteryAdvisor, CxResearchAdvisor])
def test_new_advisors_skipped_without_llm_key(blank_env, advisor_cls):
    briefing = advisor_cls().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "GEMINI_API_KEY" in briefing.text


@pytest.mark.parametrize("advisor_cls", [AiMasteryAdvisor, CxResearchAdvisor])
def test_new_advisors_stay_out_of_the_batch_without_a_key(blank_env, advisor_cls):
    assert advisor_cls().batch_section() is None


def test_new_advisors_are_registered_last_but_one(blank_env):
    keys = [advisor.key for advisor in all_advisors()]
    assert "ai_mastery" in keys and "cx_research" in keys
    # The accountability coach must still see everyone else first.
    assert keys[-1] == "accountability_coach"


@pytest.mark.parametrize(
    "advisor_cls, module, env",
    [
        (AiMasteryAdvisor, mastery_module, "AI_MASTERY_RSS_URL"),
        (CxResearchAdvisor, cx_module, "CX_RESEARCH_RSS_URL"),
    ],
)
def test_new_advisors_deduplicate_their_feed(
    blank_env, monkeypatch, tmp_path, advisor_cls, module, env
):
    memory.reset(path=str(tmp_path / "findings.json"))
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv(env, "https://example.org/feed")
    monkeypatch.setattr(
        module,
        "fetch_feed_items",
        lambda url, limit=8: [
            FeedItem(title="Ücretsiz eğitim duyurusu", link="https://example.org/a"),
            FeedItem(title="İkinci duyuru", link="https://example.org/b"),
        ],
    )

    first = advisor_cls()
    assert first.new_finding_count() == 2
    assert "https://example.org/a" in first.batch_section().user_prompt
    memory.commit()

    # A later run in the day sees the same feed and has nothing to add.
    memory.reset(path=str(tmp_path / "findings.json"))
    second = advisor_cls()
    assert second.new_finding_count() == 0
    assert "BUGÜN İLK KEZ" not in second.batch_section().user_prompt


@pytest.mark.parametrize(
    "advisor_cls, module, env",
    [
        (AiMasteryAdvisor, mastery_module, "AI_MASTERY_RSS_URL"),
        (CxResearchAdvisor, cx_module, "CX_RESEARCH_RSS_URL"),
    ],
)
def test_new_advisors_survive_a_dead_feed(
    blank_env, monkeypatch, advisor_cls, module, env
):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv(env, "https://example.invalid/feed")

    def boom(url, limit=8):
        raise RuntimeError("feed unreachable")

    monkeypatch.setattr(module, "fetch_feed_items", boom)

    section = advisor_cls().batch_section()
    assert section is not None and section.user_prompt


def test_ai_mastery_teaches_a_rotating_curriculum_at_a_level(blank_env, monkeypatch):
    from datetime import date

    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("AI_MASTERY_LEVEL", "ileri")

    prompt = AiMasteryAdvisor().batch_section().user_prompt
    assert "ileri" in prompt
    assert "💊 Hap bilgi" in prompt
    assert "🎬 Eğitim videoları" in prompt
    assert "🎓 Ücretsiz sertifikalı eğitimler" in prompt
    assert "✅ Bugünün görevi" in prompt
    # Stable providers by root domain only, never an invented deep URL.
    assert "https://learn.microsoft.com" in prompt
    assert "UYDURMA" in prompt

    # Consecutive days teach different topics.
    topics = {
        mastery_module._daily_topic(date(2026, 7, day)) for day in (1, 2, 3, 4)
    }
    assert len(topics) == 4


def test_ai_mastery_level_falls_back_to_temel(blank_env, monkeypatch):
    monkeypatch.setenv("AI_MASTERY_LEVEL", "uzman")
    assert mastery_module._level() == "temel"


def test_ai_mastery_briefing_carries_the_verify_caveat(blank_env):
    briefing = AiMasteryAdvisor().briefing_from_batch("Ders gövdesi.")
    assert briefing.status == STATUS_OK
    assert "🔎 Bağlantıları açılışta doğrulayın." in briefing.text


def test_cx_research_persona_enforces_evidence_discipline(blank_env, monkeypatch):
    from datetime import date

    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("USER_SECTOR", "banka çağrı merkezleri")

    prompt = CxResearchAdvisor().batch_section().user_prompt
    for marker in ("📊 Kanıt", "🏆 Başarı hikâyesi", "🧪 Metodoloji", "✅ Bugünün görevi"):
        assert marker in prompt
    assert "banka çağrı merkezleri" in prompt
    for metric in ("NPS", "CSAT", "CES", "FCR", "churn"):
        assert metric in prompt
    assert "https://hbr.org" in prompt

    # The system prompt is where the "never fabricate a number" rule lives.
    assert "uydurma" in cx_module.SYSTEM_PROMPT.lower()
    assert "kaynağın adını" in cx_module.SYSTEM_PROMPT

    focuses = {cx_module._daily_focus(date(2026, 7, day)) for day in (1, 2, 3, 4)}
    assert len(focuses) == 4


def test_cx_research_briefing_carries_the_evidence_caveat(blank_env):
    briefing = CxResearchAdvisor().briefing_from_batch("Araştırma gövdesi.")
    assert briefing.status == STATUS_OK
    assert "📌 Kanıt notu" in briefing.text
    assert "🔎 Bağlantıları açılışta doğrulayın." in briefing.text


# --- batching + status report ------------------------------------------------


def test_batch_parser_handles_the_new_sections():
    text = (
        f"{SECTION_MARKER} ai_mastery\nUstalık gövdesi.\n\n"
        f"{SECTION_MARKER} cx_research\nAraştırma gövdesi.\n"
    )
    assert parse_batch_response(text, ["ai_mastery", "cx_research"]) == {
        "ai_mastery": "Ustalık gövdesi.",
        "cx_research": "Araştırma gövdesi.",
    }


def test_new_advisors_share_the_single_batched_call(blank_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("DIGEST_BATCH_MODE", raising=False)
    for module in (mastery_module, cx_module):
        monkeypatch.setattr(module, "fetch_feed_items", lambda url, limit=8: [])

    calls = []
    response = (
        f"{SECTION_MARKER} ai_mastery\nUstalık gövdesi.\n\n"
        f"{SECTION_MARKER} cx_research\nAraştırma gövdesi.\n"
    )

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        calls.append(user_prompt)
        return response

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    supervision = OperationsManager(
        advisors=[AiMasteryAdvisor(), CxResearchAdvisor()]
    ).run()

    assert len(calls) == 1  # ONE Gemini request for both new personas
    assert {b.key: b.status for b in supervision.briefings} == {
        "ai_mastery": STATUS_OK,
        "cx_research": STATUS_OK,
    }
    assert all(FAKE_KEY not in b.text for b in supervision.briefings)


def test_status_report_records_mode_and_new_findings(blank_env):
    supervision = Supervision(
        briefings=[
            Briefing(key="ai_news", title="Haberler", status=STATUS_OK, text="x" * 40,
                     new_findings=3),
            Briefing(key="ai_mastery", title="Ustalık", status=STATUS_SKIPPED,
                     text="yeni bulgu yok", new_findings=0, nothing_new=True),
        ],
        mode=config.MODE_INCREMENTAL,
    )
    document = build_status(supervision)

    assert document["run"]["mode"] == "incremental"
    assert document["run"]["new_findings"] == 3
    assert document["run"]["nothing_new_count"] == 1
    entries = {entry["id"]: entry for entry in document["advisors"]}
    assert entries["ai_news"]["new_findings"] == 3
    assert entries["ai_news"]["nothing_new"] is False
    assert entries["ai_mastery"]["nothing_new"] is True
    assert entries["ai_mastery"]["emoji"] == "🧠"
    assert entries["ai_news"]["category"]
    # History carries the mode too, so the dashboard can label past runs.
    assert document["history"][-1]["mode"] == "incremental"
    assert document["history"][-1]["new_findings"] == 3
