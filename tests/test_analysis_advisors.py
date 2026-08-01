"""Tests for the two analysis-engine personas.

``DataAnalystAdvisor`` reads the operation's own numbers and interprets them;
``OperationsDirectorAdvisor`` runs LAST and turns the whole run into a decision
list. Both must:

* degrade to ``skipped`` with a TURKISH explanation when nothing is configured
  — never a traceback;
* emit the structured report schema (``ai_assistant.reports``) so the reading
  view, the Excel export and the Markdown export all get the same document;
* stay inside their own scope: the director never repeats the work analyst.

Everything here runs OFFLINE: no LLM key, no network, no Google credentials.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from ai_assistant import config, reports
from ai_assistant.advisors import Briefing, all_advisors
from ai_assistant.advisors import data_analyst as analyst_module
from ai_assistant.advisors import operations_director as director_module
from ai_assistant.advisors.data_analyst import DataAnalystAdvisor
from ai_assistant.advisors.operations_director import OperationsDirectorAdvisor
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ai_assistant.status_report import ISTANBUL

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "cagri_merkezi.csv")
NOW = datetime(2026, 8, 1, 9, 30, tzinfo=ISTANBUL)

_ENV_VARS = (
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "DATA_ANALYST_SOURCE",
    "DATA_ANALYST_DRIVE_FOLDER_ID",
    "DATA_ANALYST_SHEET",
    "DATA_ANALYST_LAST_DAYS",
    "DATA_ANALYST_SLA_TARGET",
    "DATA_ANALYST_TOP_N",
    "DATA_ANALYST_QUESTION",
    "OPERATIONS_DIRECTOR_BUSINESS",
    "OPERATIONS_DIRECTOR_FORECAST",
    "OPERATIONS_DIRECTOR_SLA_TARGET",
)


@pytest.fixture()
def blank_env(monkeypatch):
    """No provider key, no data source, no built-in defaults."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})
    yield


@pytest.fixture()
def local_dataset(blank_env, monkeypatch):
    """The synthetic call-centre CSV wired in as the analyst's source."""
    monkeypatch.setenv("DATA_ANALYST_SOURCE", FIXTURE)
    yield FIXTURE


def _document(briefing):
    """The published document a briefing would produce, as a plain dict."""
    return reports.build_report(briefing, "2026-08-01", NOW).document()


# --- data analyst: offline behaviour ----------------------------------------


def test_data_analyst_skipped_without_a_source(blank_env):
    briefing = DataAnalystAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    # The skip must TEACH: both configuration routes are named, in Turkish.
    assert "DATA_ANALYST_SOURCE" in briefing.text
    assert "DATA_ANALYST_DRIVE_FOLDER_ID" in briefing.text
    assert "yapılandırılmadı" in briefing.text


def test_data_analyst_stays_out_of_the_batch_without_a_key(blank_env):
    assert DataAnalystAdvisor().batch_section() is None


def test_data_analyst_is_private():
    assert DataAnalystAdvisor.private is True
    assert "data_analyst" in reports.PRIVATE_ADVISOR_KEYS


def test_data_analyst_fails_cleanly_on_an_unreadable_source(blank_env, monkeypatch):
    """A configured but broken source is ``failed`` with a sentence, not a stack."""
    monkeypatch.setenv("DATA_ANALYST_SOURCE", "/tmp/kesinlikle-olmayan-dosya.xlsx")
    briefing = DataAnalystAdvisor().generate_briefing()
    assert briefing.status == STATUS_FAILED
    assert briefing.text
    assert "Traceback" not in briefing.text


# --- data analyst: with real data -------------------------------------------


def test_data_analyst_reads_the_dataset_without_an_llm(local_dataset):
    """Numbers exist even with no model: the section reports them, and says so."""
    briefing = DataAnalystAdvisor().generate_briefing()
    assert briefing.status == STATUS_OK
    assert briefing.text.startswith("**Öne çıkan:**")
    # Every claim rests on a figure that came out of the engine.
    assert "%84,2" in briefing.text  # SLA
    assert "4 dk 55 sn" in briefing.text  # AHT
    # …and the briefing is explicit that this is not an interpretation.
    assert "analist YORUMU değil" in briefing.text


def test_data_analyst_names_what_the_data_cannot_support(local_dataset):
    briefing = DataAnalystAdvisor().generate_briefing()
    assert "Verinin desteklemediği şeyler" in briefing.text
    assert "nedensellik kanıtı değildir" in briefing.text


def test_data_analyst_never_asserts_causation_for_a_correlation(local_dataset):
    briefing = DataAnalystAdvisor().generate_briefing()
    assert "Birlikte hareket ediyorlar" in briefing.text
    assert "hangisinin diğerini doğurduğu bu veriden söylenemez" in briefing.text


def test_findings_are_ranked_by_operational_impact_not_column_order(local_dataset):
    advisor = DataAnalystAdvisor()
    advisor._prepare()

    engine_order = [f.key for f in advisor._result.findings]
    ranked = [f.key for f in advisor._findings]

    assert set(engine_order) == set(ranked)
    assert ranked != engine_order
    # The engine emits total volume first; a director reads the warning first.
    assert engine_order[0] == "calls_total"
    assert ranked[0] == "aht"  # the only "warn" finding in the fixture
    assert ranked.index("sla") < ranked.index("calls_total")


def test_impact_rank_puts_bad_before_good_and_big_moves_first():
    class F:
        def __init__(self, key, tone, delta):
            self.key, self.tone, self.delta_pct = key, tone, delta

    bad_small = F("csat", "bad", 1.0)
    good_big = F("sla", "good", 40.0)
    assert analyst_module.impact_rank(bad_small) < analyst_module.impact_rank(good_big)

    sla = F("sla", "warn", 2.0)
    volume = F("calls_total", "warn", 2.0)
    assert analyst_module.impact_rank(sla) < analyst_module.impact_rank(volume)

    big = F("sla", "warn", 30.0)
    small = F("sla", "warn", 3.0)
    assert analyst_module.impact_rank(big) < analyst_module.impact_rank(small)


def test_unsupported_notes_list_the_missing_metrics(local_dataset):
    advisor = DataAnalystAdvisor()
    advisor._prepare()
    missing_line = next(
        note for note in advisor._limits if "hüküm kurulamaz" in note
    )
    # The fixture has no first-contact-resolution column…
    assert "ilk temasta çözüm (FCR)" in missing_line
    # …but it DOES have abandonment (as a derived rate), so claiming it is
    # missing would be a false limitation.
    assert "terk oranı" not in missing_line


def test_evidence_block_carries_only_computed_numbers(local_dataset):
    advisor = DataAnalystAdvisor()
    advisor._prepare()
    block = analyst_module.evidence_block(advisor._result, advisor._findings)
    assert "BULGULAR (ETKİ SIRASIYLA" in block
    assert "%84,2" in block
    # Correlations are labelled as co-movement, never as cause.
    assert "neden-sonuç DEĞİL" in block


def test_data_analyst_joins_the_batch_with_a_key(local_dataset, monkeypatch):
    monkeypatch.setattr(analyst_module.llm, "is_configured", lambda: True)
    section = DataAnalystAdvisor().batch_section()
    assert section is not None
    assert section.key == "data_analyst"
    assert "KANIT" in section.user_prompt
    assert "SAYI UYDURMA" in section.system_prompt


def test_data_analyst_batch_answer_becomes_a_structured_briefing(local_dataset, monkeypatch):
    monkeypatch.setattr(analyst_module.llm, "is_configured", lambda: True)
    advisor = DataAnalystAdvisor()
    advisor.batch_section()
    briefing = advisor.briefing_from_batch("**Öne çıkan:** SLA %84,2 ile hedefin üzerinde.")
    assert briefing.status == STATUS_OK
    assert briefing.report["key_metrics"]


# --- data analyst: structured schema ----------------------------------------


def test_data_analyst_emits_the_structured_report_schema(local_dataset):
    briefing = DataAnalystAdvisor().generate_briefing()
    payload = briefing.report
    assert set(payload) == {
        "headline",
        "key_metrics",
        "sections",
        "action_items",
        "sources",
    }

    document = _document(briefing)
    assert document["schema_version"] == reports.SCHEMA_VERSION
    assert document["headline"]
    # The metric strip is the impact ranking, not the engine's column order.
    assert document["key_metrics"][0]["label"].startswith("Ortalama görüşme")
    # The analyst's own words come first, then the engine's tables.
    titles = [section["title"] for section in document["sections"]]
    assert titles[0] == "Analist yorumu"
    assert "Verinin desteklemediği şeyler" in titles
    assert any(section.get("table") for section in document["sections"])
    assert any(section.get("chart") for section in document["sections"])


def test_data_analyst_actions_carry_an_owner(local_dataset):
    document = _document(DataAnalystAdvisor().generate_briefing())
    actions = document["action_items"]
    assert actions
    assert all(item["owner"] for item in actions)
    # Every action names the figure it rests on.
    assert any("Dayanak:" in item["text"] for item in actions)


def test_data_analyst_document_renders_to_markdown(local_dataset):
    report = reports.build_report(DataAnalystAdvisor().generate_briefing(), "2026-08-01", NOW)
    markdown = report.to_markdown()
    assert "## Analist yorumu" in markdown
    assert "## Aksiyonlar" in markdown
    assert "| Gösterge | Değer | Eğilim |" in markdown


# --- data analyst: Drive discovery ------------------------------------------


class _FakeDrive:
    def __init__(self, files):
        self.files = files
        self.asked = []

    def list_documents_in_folder(self, folder_id, **kwargs):
        self.asked.append(folder_id)
        return self.files


def test_newest_drive_spreadsheet_picks_the_most_recent(blank_env):
    client = _FakeDrive(
        [
            {
                "id": "eski",
                "name": "Haziran.xlsx",
                "modifiedTime": "2026-06-30T10:00:00Z",
                "mimeType": "application/vnd.google-apps.spreadsheet",
            },
            {
                "id": "yeni",
                "name": "Temmuz.xlsx",
                "modifiedTime": "2026-07-31T10:00:00Z",
                "mimeType": "application/vnd.google-apps.spreadsheet",
            },
            {
                "id": "belge",
                "name": "Not.docx",
                "modifiedTime": "2026-08-01T10:00:00Z",
                "mimeType": "application/vnd.google-apps.document",
            },
        ]
    )
    found = analyst_module.newest_drive_spreadsheet("KLASOR", client=client)
    assert found["id"] == "yeni"
    assert client.asked == ["KLASOR"]


def test_newest_drive_spreadsheet_explains_an_empty_folder(blank_env):
    with pytest.raises(analyst_module.SourceBroken) as excinfo:
        analyst_module.newest_drive_spreadsheet("BOS", client=_FakeDrive([]))
    assert "e-tablo bulunamadı" in str(excinfo.value)


# --- operations director: ordering and scope --------------------------------


def test_operations_director_runs_last_in_the_roster():
    """Last of the CONTENT advisors; only the SRE watchdog follows it."""
    keys = [advisor.key for advisor in all_advisors()]
    assert keys[-2] == "operations_director"
    assert keys[-1] == "sre_watchdog"


def test_operations_director_never_joins_the_batch(blank_env, monkeypatch):
    """Its prompt is built from the OTHERS' output, which the batch cannot know."""
    monkeypatch.setattr(director_module.llm, "is_configured", lambda: True)
    assert OperationsDirectorAdvisor().batch_section() is None


def test_operations_director_is_private():
    assert OperationsDirectorAdvisor.private is True
    assert "operations_director" in reports.PRIVATE_ADVISOR_KEYS


def test_operations_director_skipped_when_it_saw_nothing(blank_env):
    briefing = OperationsDirectorAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "BRIEFING_MODE=full" in briefing.text


def test_operations_director_skipped_when_nobody_produced_business_content(blank_env):
    advisor = OperationsDirectorAdvisor()
    advisor.observe(
        [
            Briefing(key="weather", title="Hava", status=STATUS_SKIPPED, text="yok"),
            Briefing(key="market_intelligence", title="Pazar", status=STATUS_SKIPPED, text="yok"),
        ]
    )
    briefing = advisor.generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "DATA_ANALYST_SOURCE" in briefing.text


def test_operations_director_ignores_the_work_analysts_system_health(blank_env):
    """The system's technical health belongs to work_analyst, not here."""
    advisor = OperationsDirectorAdvisor()
    advisor.observe(
        [
            Briefing(
                key="work_analyst",
                title="İş Analisti Danışmanı",
                status=STATUS_OK,
                text="**Öne çıkan:** 9/10 danışman başarılı, token tüketimi normal.",
            )
        ]
    )
    briefing = advisor.generate_briefing()
    # The ONLY ok section was system health, so there is no business decision.
    assert briefing.status == STATUS_SKIPPED
    assert "work_analyst" in director_module.SYSTEM_HEALTH_KEYS


# --- operations director: the decision list ---------------------------------


def _analyst_briefing():
    briefing = Briefing(
        key="data_analyst",
        title="Veri Analisti (Çağrı Merkezi Operasyonu)",
        status=STATUS_OK,
        text="**Öne çıkan:** AHT 4 dk 55 sn; ilk yarıya göre 48 sn uzadı.",
        private=True,
    )
    briefing.report = {
        "headline": "AHT uzuyor",
        "key_metrics": [{"label": "AHT", "value": "4 dk 55 sn", "note": "48 sn uzun"}],
        "sections": [],
        "action_items": [
            {
                "text": "AHT uzaması: en uzun görüşme konularını ayıkla.",
                "owner": "Operasyon",
                "deadline": "bugün",
            }
        ],
        "sources": [],
    }
    return briefing


def _run_director(extra=()):
    advisor = OperationsDirectorAdvisor()
    advisor.observe(
        [
            _analyst_briefing(),
            Briefing(
                key="morning_operations",
                title="Sabah İşletme Brifingi",
                status=STATUS_OK,
                text="**Öne çıkan:** Bugün üç toplantı ve iki eskalasyon var.",
            ),
            Briefing(
                key="work_analyst",
                title="İş Analisti Danışmanı",
                status=STATUS_OK,
                text="**Öne çıkan:** Sistem sağlıklı, token tüketimi normal.",
            ),
            *extra,
        ]
    )
    return advisor, advisor.generate_briefing()


def test_operations_director_produces_a_decision_list_without_an_llm(blank_env):
    _, briefing = _run_director()
    assert briefing.status == STATUS_OK
    assert briefing.text.startswith("**Öne çıkan:**")
    assert "Bugünün kararları" in briefing.text
    assert "(Sorumlu:" in briefing.text and "(Son tarih:" in briefing.text


def test_operations_director_states_its_boundary_in_the_report(blank_env):
    _, briefing = _run_director()
    assert "İş Analisti bölümündedir" in briefing.text


def test_operations_director_decisions_carry_owner_and_deadline(blank_env):
    _, briefing = _run_director()
    document = _document(briefing)
    actions = document["action_items"]
    assert actions
    for item in actions:
        assert item["owner"]
        assert item["deadline"]
    # The consequence of NOT acting travels with the decision.
    assert any("Aksiyon alınmazsa" in item["text"] for item in actions)


def test_operations_director_leans_on_the_analysts_own_actions(blank_env):
    _, briefing = _run_director()
    joined = " ".join(item["text"] for item in briefing.report["action_items"])
    assert "en uzun görüşme konularını ayıkla" in joined


def test_operations_director_emits_the_structured_report_schema(blank_env):
    _, briefing = _run_director()
    assert set(briefing.report) == {
        "headline",
        "key_metrics",
        "sections",
        "action_items",
        "sources",
    }
    document = _document(briefing)
    assert document["schema_version"] == reports.SCHEMA_VERSION
    titles = [section["title"] for section in document["sections"]]
    assert titles[0] == "Karar listesi"
    assert "Kaynak bulgular" in titles
    labels = [metric["label"] for metric in document["key_metrics"]]
    assert "Karar sayısı" in labels


def test_operations_director_source_table_excludes_the_work_analyst(blank_env):
    _, briefing = _run_director()
    table = briefing.report["sections"][1]["table"]
    advisors = [row["advisor"] for row in table["rows"]]
    assert "Veri Analisti (Çağrı Merkezi Operasyonu)" in advisors
    assert "İş Analisti Danışmanı" not in advisors


def test_operations_director_prompt_excludes_system_health(blank_env):
    advisor, _ = _run_director()
    prompt = director_module.user_prompt(advisor._business_inputs())
    assert "Sabah İşletme Brifingi" in prompt
    assert "token tüketimi normal" not in prompt


def test_operations_director_falls_back_when_the_model_call_fails(blank_env, monkeypatch):
    monkeypatch.setattr(director_module.llm, "is_configured", lambda: True)

    def boom(*args, **kwargs):
        raise RuntimeError("429 quota")

    monkeypatch.setattr(director_module.llm, "generate_text", boom)
    _, briefing = _run_director()
    assert briefing.status == STATUS_OK
    assert briefing.report["action_items"]


def test_operations_director_uses_the_models_decision_list(blank_env, monkeypatch):
    answer = (
        "**Öne çıkan:** Akşam vardiyasına iki kişi eklenmeli.\n\n"
        "## 🚦 Bugünün kararları (öncelik sırasıyla)\n"
        "- **⏱️ BUGÜN: Akşam vardiyasına 2 temsilci kaydır** — Dayanak: AHT 4 dk "
        "55 sn. Aksiyon alınmazsa: yarın akşam SLA %80'in altına iner. "
        "(Son tarih: bugün 17:00) (Sorumlu: Ekip Lideri)\n"
    )
    monkeypatch.setattr(director_module.llm, "is_configured", lambda: True)
    monkeypatch.setattr(director_module.llm, "generate_text", lambda *a, **k: answer)

    _, briefing = _run_director()
    assert briefing.status == STATUS_OK
    action = briefing.report["action_items"][0]
    assert action["owner"] == "Ekip Lideri"
    assert action["deadline"] == "bugün 17:00"
    assert "Aksiyon alınmazsa" in action["text"]


def test_parse_decisions_survives_a_model_that_breaks_the_format():
    text = (
        "## Bugünün kararları\n"
        "- Kadroyu gözden geçir\n"
        "- İkinci madde (Son tarih: bu hafta)\n"
    )
    decisions = director_module.parse_decisions(text)
    assert [item["text"] for item in decisions] == [
        "Kadroyu gözden geçir",
        "İkinci madde",
    ]
    assert decisions[1]["deadline"] == "bu hafta"


def test_compact_input_is_capped(blank_env):
    briefing = Briefing(
        key="x",
        title="X",
        status=STATUS_OK,
        text="**Öne çıkan:** Başlık cümlesi.\n\n" + ("uzun metin " * 400),
    )
    compact = director_module.compact_input(briefing)
    assert len(compact) <= director_module.MAX_INPUT_CHARS + 200
    assert compact.startswith("Başlık cümlesi.")
