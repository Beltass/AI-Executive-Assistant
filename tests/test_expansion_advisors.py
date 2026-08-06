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
