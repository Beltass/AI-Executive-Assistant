"""Kadro genişlemesi — beş yeni danışmanın ortak sözleşmesi.

Bu dosya, 17 kişilik kadroya eklenen beş danışmanı test eder:
``productivity_coach``, ``risk_sentinel``, ``decision_intelligence``,
``social_guardian`` ve ``learning_curator``.

Hepsinin uyması gereken ORTAK kurallar:

* manifestte canlı bir kaydı, doğru bir tetikleyicisi ve bir Slack rotası var;
* model anahtarı yokken ``skipped`` döner — SAHTE VERİ ÜRETMEZ. Bir danışmanın
  uydurduğu sayı, hiç yazılmamış bir bölümden kötüdür;
* model anahtarı yokken toplu çağrıya (``batch_section``) katılmaz;
* veri tetiklemeli olanlar bir ``data_owner`` sahibidir ve kaynağı boşken
  Türkçe bir açıklamayla devreder.

Her şey OFFLINE çalışır: ne ağ, ne kimlik, ne model çağrısı.
"""

from __future__ import annotations

import pytest

from ai_assistant import status_report
from ai_assistant.integrations import STATUS_SKIPPED

#: (manifest anahtarı, beklenen tetikleyici)
NEW_ADVISORS = (
    ("productivity_coach", status_report.TRIGGER_WEEKLY),
    ("risk_sentinel", status_report.TRIGGER_DATA),
    ("decision_intelligence", status_report.TRIGGER_WEEKLY),
    ("social_guardian", status_report.TRIGGER_DATA),
    ("learning_curator", status_report.TRIGGER_WEEKLY),
)

_LLM_ENV = ("GEMINI_API_KEY", "OPENAI_API_KEY")


@pytest.fixture()
def no_llm(monkeypatch):
    """Hiçbir model sağlayıcısı yapılandırılmamış."""
    for var in _LLM_ENV:
        monkeypatch.delenv(var, raising=False)
    yield


def _build(key: str):
    """Manifestteki kaydından bir danışman örneği kurar."""
    import importlib

    record = status_report.ADVISOR_META[key]
    module = importlib.import_module(f"ai_assistant.advisors.{record['module']}")
    return getattr(module, record["advisor_class"])()


# --- the shared contract ----------------------------------------------------


@pytest.mark.parametrize("key,trigger", NEW_ADVISORS)
def test_new_advisor_is_live_with_the_agreed_trigger(key, trigger):
    """Tetikleyici bir MALİYET kararı: değişmesi açık bir düzenleme olmalı."""
    record = status_report.ADVISOR_META[key]
    assert record["status"] == status_report.ADVISOR_LIVE
    assert record["trigger"] == trigger
    assert record["slack_target"], key
    assert record["dashboard_order"] > 0, key
    if trigger == status_report.TRIGGER_DATA:
        assert record["data_owner"], key


@pytest.mark.parametrize("key,_trigger", NEW_ADVISORS)
def test_new_advisor_invents_nothing_without_a_model(key, _trigger, no_llm):
    """Model yoksa bölüm SESSİZ kalır; uydurulmuş bir brifing yazmaz."""
    briefing = _build(key).generate_briefing()
    assert briefing.status == STATUS_SKIPPED, briefing.text
    assert briefing.text.strip()


@pytest.mark.parametrize("key,_trigger", NEW_ADVISORS)
def test_new_advisor_stays_out_of_the_batch_without_a_model(key, _trigger, no_llm):
    assert _build(key).batch_section() is None


# --- productivity_coach: zaman mimarisi, taahhüt takibi DEĞİL ---------------


def test_productivity_coach_admits_it_has_no_calendar(monkeypatch):
    """Zirve saat bilinmiyorsa uydurmaz: varsayım olduğunu söyler."""
    from ai_assistant.advisors import productivity_coach as module

    monkeypatch.delenv(module.PEAK_HOURS_ENV, raising=False)
    monkeypatch.delenv(module.CONSTRAINTS_ENV, raising=False)

    block = module.context_block()
    assert "BİLİNMİYOR" in block
    assert "VARSAYIM" in block


def test_productivity_coach_uses_the_configured_hours_and_limits(monkeypatch):
    from ai_assistant.advisors import productivity_coach as module

    monkeypatch.setenv(module.PEAK_HOURS_ENV, "07:30-11:00")
    monkeypatch.setenv(module.CONSTRAINTS_ENV, "10:00 ekip toplantısı, cuma izin")

    assert module.constraints() == ["10:00 ekip toplantısı", "cuma izin"]
    block = module.context_block()
    assert "07:30-11:00" in block
    assert "10:00 ekip toplantısı" in block


def test_productivity_coach_prompt_draws_the_line_at_accountability(monkeypatch):
    """``executive_coaching`` ile örtüşme prompt düzeyinde YASAKLANMIŞ olmalı."""
    from ai_assistant.advisors import productivity_coach as module

    monkeypatch.delenv(module.PEAK_HOURS_ENV, raising=False)
    monkeypatch.delenv(module.CONSTRAINTS_ENV, raising=False)

    advisor = module.ProductivityCoachAdvisor()
    assert "Taahhüt takibi" in advisor.user_prompt
    assert "odak" in advisor.user_prompt.lower()
    assert "SENİN İŞİN DEĞİL" in module.SYSTEM_PROMPT


# --- risk_sentinel: TREND, anlık kontrol DEĞİL ------------------------------


def _runs(count: int, **series) -> list:
    """``count`` adet koşu kaydı; her seri için verilen değer listesi kullanılır."""
    records = []
    for index in range(count):
        record = {"at": f"2026-08-{index + 1:02d}T07:00:00+00:00"}
        for field, values in series.items():
            record[field] = values[index]
        records.append(record)
    return records


def test_risk_sentinel_needs_two_windows_before_it_speaks(monkeypatch):
    """Tek bir kötü koşu trend değildir: az veriden 'trend' uydurmaz."""
    from ai_assistant.advisors import risk_sentinel as module

    short = _runs(3, advisors_failed=[0, 1, 2])
    monkeypatch.setattr(module.RiskSentinelAdvisor, "_history", lambda self: short)

    briefing = module.RiskSentinelAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "yeterli koşu yok" in briefing.text


def test_risk_sentinel_stays_quiet_when_nothing_is_getting_worse(monkeypatch):
    from ai_assistant.advisors import risk_sentinel as module

    steady = _runs(6, advisors_failed=[0] * 6, total_tokens=[1000] * 6)
    monkeypatch.setattr(module.RiskSentinelAdvisor, "_history", lambda self: steady)

    briefing = module.RiskSentinelAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "erken uyarı sinyali yok" in briefing.text


def test_risk_sentinel_reads_no_history_as_no_history(monkeypatch):
    from ai_assistant.advisors import risk_sentinel as module

    monkeypatch.setattr(module.RiskSentinelAdvisor, "_history", lambda self: [])
    briefing = module.RiskSentinelAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text == module.SKIP_NO_HISTORY


def test_risk_sentinel_catches_a_slow_climb():
    """Sessizce büyüyen token maliyeti bir sinyaldir."""
    from ai_assistant.advisors import risk_sentinel as module

    runs = _runs(6, total_tokens=[1000, 1100, 1050, 1800, 1900, 2000])
    signals = module.detect(runs, module.DEFAULT_WINDOW)
    labels = [signal.label for signal in signals]
    assert "Koşu başına token" in labels
    climbing = [s for s in signals if s.label == "Koşu başına token"][0]
    assert climbing.recent > climbing.older
    assert climbing.drift >= module.WORSENING_RATIO


def test_risk_sentinel_knows_which_direction_is_bad():
    """Başarılı danışman sayısı DÜŞERSE kötüdür; artarsa sinyal değildir."""
    from ai_assistant.advisors import risk_sentinel as module

    falling = _runs(6, advisors_ok=[10, 10, 10, 5, 4, 4])
    rising = _runs(6, advisors_ok=[4, 4, 5, 10, 10, 10])

    assert any(
        s.label == "Başarılı danışman sayısı"
        for s in module.detect(falling, module.DEFAULT_WINDOW)
    )
    assert not any(
        s.label == "Başarılı danışman sayısı"
        for s in module.detect(rising, module.DEFAULT_WINDOW)
    )


def test_risk_sentinel_reports_a_threshold_breach_before_a_trend():
    """Eşik aşımı listenin başında durur; trend arkasından gelir."""
    from ai_assistant.advisors import risk_sentinel as module

    runs = _runs(
        6,
        advisors_failed=[0, 0, 0, 2, 2, 2],
        duration_seconds=[10, 10, 10, 14, 15, 15],
    )
    signals = module.detect(runs, module.DEFAULT_WINDOW)
    assert signals[0].label == "Başarısız danışman sayısı"
    assert signals[0].breach
    assert "EŞİK AŞIMI" in signals[0].describe()


def test_risk_sentinel_token_ceiling_is_off_until_configured(monkeypatch):
    from ai_assistant.advisors import risk_sentinel as module

    monkeypatch.delenv(module.TOKEN_LIMIT_ENV, raising=False)
    assert module.token_limit() == 0

    monkeypatch.setenv(module.TOKEN_LIMIT_ENV, "1500")
    assert module.token_limit() == 1500
    runs = _runs(6, total_tokens=[1400, 1400, 1400, 1600, 1600, 1600])
    breaching = module.detect(runs, module.DEFAULT_WINDOW)
    assert breaching and breaching[0].breach


def test_risk_sentinel_prompt_refuses_the_watchdogs_job(monkeypatch):
    """``sre_watchdog`` anlık kontrol yapar; bu bölüm yalnızca eğilim anlatır."""
    from ai_assistant.advisors import risk_sentinel as module

    runs = _runs(6, advisors_failed=[0, 0, 0, 1, 2, 2])
    monkeypatch.setattr(module.RiskSentinelAdvisor, "_history", lambda self: runs)
    monkeypatch.setattr(module.llm, "is_configured", lambda: True)

    advisor = module.RiskSentinelAdvisor()
    section = advisor.batch_section()
    assert section is not None
    assert "Anlık sistem sağlığı kontrolü" in section.user_prompt
    assert "Başarısız danışman sayısı" in section.user_prompt
    assert advisor.new_finding_count() >= 1


# --- decision_intelligence: SONUÇ, yeni karar DEĞİL -------------------------


def test_decision_intelligence_invents_no_decisions_when_none_are_logged(
    monkeypatch,
):
    """Kayıt yoksa karar UYDURULMAZ; onun yerine günlük protokolü verilir."""
    from ai_assistant.advisors import decision_intelligence as module

    monkeypatch.delenv(module.DECISIONS_ENV, raising=False)

    assert module.recent_decisions() == []
    block = module.decisions_block()
    assert block == module.NO_LOG_INSTRUCTION
    assert "UYDURMA" in block
    assert module.DECISIONS_ENV in block


def test_decision_intelligence_reads_the_logged_decisions(monkeypatch):
    from ai_assistant.advisors import decision_intelligence as module

    monkeypatch.setenv(
        module.DECISIONS_ENV,
        "Vendor A ile devam | beklenen: SLA %98\nEkip büyütme ertelendi",
    )

    entries = module.recent_decisions()
    assert entries == [
        "Vendor A ile devam | beklenen: SLA %98",
        "Ekip büyütme ertelendi",
    ]
    block = module.decisions_block()
    assert "[KARAR 1] Vendor A ile devam" in block
    assert "[KARAR 2] Ekip büyütme ertelendi" in block


def test_decision_intelligence_caps_how_many_decisions_it_reviews(monkeypatch):
    from ai_assistant.advisors import decision_intelligence as module

    monkeypatch.setenv(
        module.DECISIONS_ENV,
        ";".join(f"karar {index}" for index in range(module.MAX_DECISIONS + 4)),
    )
    assert len(module.recent_decisions()) == module.MAX_DECISIONS


def test_decision_intelligence_refuses_the_directors_job(monkeypatch):
    """``operations_director`` bugünü kurar; bu bölüm dünü okur."""
    from ai_assistant.advisors import decision_intelligence as module

    monkeypatch.delenv(module.DECISIONS_ENV, raising=False)
    advisor = module.DecisionIntelligenceAdvisor()

    assert "Yeni karar ÖNERME" in advisor.user_prompt
    assert "SENİN İŞİN DEĞİL" in module.SYSTEM_PROMPT
    assert advisor.private is True


def test_decision_intelligence_appends_its_caveat_to_the_batched_text():
    from ai_assistant.advisors import decision_intelligence as module

    briefing = module.DecisionIntelligenceAdvisor().briefing_from_batch("gövde")
    assert briefing.text.startswith("gövde")
    assert module.CAVEAT in briefing.text


# --- learning_curator: SIRA, iş fırsatı DEĞİL -------------------------------


def test_learning_curator_admits_it_does_not_know_the_starting_point(monkeypatch):
    """Beceri bildirilmediyse sıfır noktasını uydurmaz."""
    from ai_assistant.advisors import learning_curator as module

    for var in (module.SKILLS_ENV, module.TARGET_ROLE_ENV, module.WEEKLY_HOURS_ENV):
        monkeypatch.delenv(var, raising=False)

    block = module.context_block()
    assert "BİLDİRİLMEDİ" in block
    assert module.current_skills() == []
    assert module.target_role() == ""
    # Hedef rol yoksa bir rol UYDURULMAZ, varsayım olduğu söylenir.
    assert "VARSAYIM" in block


def test_learning_curator_uses_the_configured_skills_and_budget(monkeypatch):
    from ai_assistant.advisors import learning_curator as module

    monkeypatch.setenv(module.SKILLS_ENV, "SQL, Excel , ekip yönetimi")
    monkeypatch.setenv(module.TARGET_ROLE_ENV, "veri analitiği yöneticisi")
    monkeypatch.setenv(module.WEEKLY_HOURS_ENV, "5")

    assert module.current_skills() == ["SQL", "Excel", "ekip yönetimi"]
    assert module.weekly_hours() == 5
    block = module.context_block()
    assert "SQL" in block
    assert "veri analitiği yöneticisi" in block
    assert "5 saat" in block


def test_learning_curator_weekly_hours_falls_back_on_nonsense(monkeypatch):
    from ai_assistant.advisors import learning_curator as module

    monkeypatch.setenv(module.WEEKLY_HOURS_ENV, "haftada bolca")
    assert module.weekly_hours() == module.DEFAULT_WEEKLY_HOURS
    monkeypatch.setenv(module.WEEKLY_HOURS_ENV, "0")
    assert module.weekly_hours() == module.DEFAULT_WEEKLY_HOURS


def test_learning_curator_prompt_draws_the_line_at_career_development(monkeypatch):
    """``career_development`` ile örtüşme prompt düzeyinde YASAKLANMIŞ olmalı.

    Kariyer danışmanı FIRSAT sunar (ilan, başvuru, sertifika duyurusu);
    küratör SIRA kurar. İkisi bir maddede buluşmamalı.
    """
    from ai_assistant.advisors import learning_curator as module

    for var in (module.SKILLS_ENV, module.TARGET_ROLE_ENV, module.WEEKLY_HOURS_ENV):
        monkeypatch.delenv(var, raising=False)

    advisor = module.LearningCuratorAdvisor()
    prompt = advisor.user_prompt
    assert "İş ilanı" in prompt
    assert "YAZMA" in prompt
    assert "sıra" in prompt.lower()
    assert "ön koşul" in prompt.lower()
    assert "SENİN İŞİN DEĞİL" in module.SYSTEM_PROMPT
    # Panoya yazılabilir: kişisel veri okumaz.
    assert advisor.private is False
    assert advisor.incremental_source is False


def test_learning_curator_manifest_record_is_complete():
    """Manifest bütünlüğü: kayıt, modül, sınıf ve Slack rotası birlikte var."""
    from ai_assistant.advisors import all_advisors
    from ai_assistant.integrations.slack_setup import ADVISOR_CHANNELS

    record = status_report.ADVISOR_META["learning_curator"]
    assert record["status"] == status_report.ADVISOR_LIVE
    assert record["trigger"] == status_report.TRIGGER_WEEKLY
    assert record["token_ceiling"] > 0
    # Kendi verisi yok: haftalık ritim parçası, veri tetiklemeli değil.
    assert record["data_owner"] == ""
    assert record["dashboard_order"] > 0
    assert record["slack_target"] == "#learning-curator"

    advisor = _build("learning_curator")
    assert advisor.key == "learning_curator"
    assert advisor.title == record["title"]
    assert "learning_curator" in [a.key for a in all_advisors()]
    assert any(
        spec.advisor_key == "learning_curator" for spec in ADVISOR_CHANNELS
    )
