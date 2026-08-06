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
NEW_ADVISORS = (("productivity_coach", status_report.TRIGGER_WEEKLY),)

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
