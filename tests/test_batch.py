"""Tests for the batched briefing mode (offline, no real network).

The free Gemini tier only allows a couple of ``generateContent`` calls per
quota window, so the whole advisor team is served by ONE batched call. These
tests cover:
- the batched response is split back apart per advisor;
- exactly one LLM call is made for the whole team;
- a failing batched call degrades to the per-advisor path;
- non-LLM advisors never join the batch.
"""

from __future__ import annotations

import pytest

from ai_assistant import config
from ai_assistant.advisors import _batch
from ai_assistant.advisors._batch import (
    SECTION_MARKER,
    batch_mode_enabled,
    build_batch_prompt,
    collect_sections,
    parse_batch_response,
    run_batch,
)
from ai_assistant.advisors.anka_bridge import AnkaBridgeAdvisor
from ai_assistant.advisors.career_hr import CareerHrAdvisor
from ai_assistant.advisors.kids_development import KidsDevelopmentAdvisor
from ai_assistant.advisors.leadership_coach import LeadershipCoachAdvisor
from ai_assistant.advisors.weather import WeatherAdvisor
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK
from ai_assistant.integrations import llm
from ai_assistant.operations_manager import OperationsManager

FAKE_KEY = "AQ.FAKE-secret-key-should-never-leak-123456"

_BATCHED_RESPONSE = f"""{SECTION_MARKER} leadership_coach
Liderlik bölümü gövdesi.
Ikinci satir.

{SECTION_MARKER} kids_development
Cocuk gelisimi bolumu.

{SECTION_MARKER} career_hr
Kariyer bolumu.
"""


@pytest.fixture()
def llm_env(monkeypatch):
    """A configured LLM key, no env-driven config, no built-in defaults.

    Clearing ``DEFAULT_SETTINGS`` keeps the RSS-backed advisors from touching
    the network; the personas under test do not need any of it.
    """
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DIGEST_BATCH_MODE", raising=False)
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})
    yield


def _personas():
    return [LeadershipCoachAdvisor(), KidsDevelopmentAdvisor(), CareerHrAdvisor()]


def test_batch_mode_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv("DIGEST_BATCH_MODE", raising=False)
    assert batch_mode_enabled() is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "HAYIR"])
def test_batch_mode_can_be_disabled(monkeypatch, value):
    monkeypatch.setenv("DIGEST_BATCH_MODE", value)
    assert batch_mode_enabled() is False


def test_parse_batch_response_splits_sections():
    parsed = parse_batch_response(
        _BATCHED_RESPONSE, ["leadership_coach", "kids_development", "career_hr"]
    )
    assert set(parsed) == {"leadership_coach", "kids_development", "career_hr"}
    assert parsed["leadership_coach"].startswith("Liderlik bölümü gövdesi.")
    assert "Ikinci satir." in parsed["leadership_coach"]
    assert parsed["career_hr"] == "Kariyer bolumu."


def test_parse_batch_response_tolerates_marker_variants_and_drops_unknowns():
    text = (
        "## SECTION: leadership_coach\nA\n"
        "###  **SECTION:** [career_hr]\nB\n"
        "### SECTION: uydurma_bolum\nC\n"
        "### SECTION: kids_development\n\n"  # empty body -> dropped
    )
    parsed = parse_batch_response(
        text, ["leadership_coach", "career_hr", "kids_development"]
    )
    assert parsed == {"leadership_coach": "A", "career_hr": "B"}


def test_build_batch_prompt_lists_every_section(llm_env):
    sections = collect_sections(_personas())
    prompt = build_batch_prompt(sections)
    for section in sections:
        assert f"{SECTION_MARKER}" in prompt
        assert section.key in prompt
        assert section.system_prompt in prompt


def test_batched_run_uses_one_call_for_the_whole_team(monkeypatch, llm_env):
    calls = []

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        calls.append(user_prompt)
        return _BATCHED_RESPONSE

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    supervision = OperationsManager(advisors=_personas()).run()

    assert len(calls) == 1  # ONE call instead of one per advisor
    statuses = {b.key: b.status for b in supervision.briefings}
    assert statuses == {
        "leadership_coach": STATUS_OK,
        "kids_development": STATUS_OK,
        "career_hr": STATUS_OK,
    }
    texts = {b.key: b.text for b in supervision.briefings}
    assert texts["kids_development"] == "Cocuk gelisimi bolumu."


def test_batch_failure_falls_back_to_per_advisor_calls(monkeypatch, llm_env):
    calls = []

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        calls.append(user_prompt)
        if SECTION_MARKER in user_prompt:
            raise RuntimeError("gemini tüm modellerde başarısız — son hata: HTTP 503")
        return "tekil brifing"

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    supervision = OperationsManager(advisors=_personas()).run()

    # 1 failed batched attempt + one call per advisor.
    assert len(calls) == 4
    assert all(b.status == STATUS_OK for b in supervision.briefings)
    assert all(b.text == "tekil brifing" for b in supervision.briefings)


def test_missing_section_falls_back_to_that_advisor_only(monkeypatch, llm_env):
    calls = []
    partial = f"{SECTION_MARKER} leadership_coach\nSadece liderlik.\n"

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        calls.append(user_prompt)
        if SECTION_MARKER in user_prompt:
            return partial
        return "tekil brifing"

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    supervision = OperationsManager(advisors=_personas()).run()

    # 1 batched call + 2 per-advisor calls for the sections the model omitted.
    assert len(calls) == 3
    texts = {b.key: b.text for b in supervision.briefings}
    assert texts["leadership_coach"] == "Sadece liderlik."
    assert texts["career_hr"] == "tekil brifing"


def test_batch_disabled_uses_one_call_per_advisor(monkeypatch, llm_env):
    monkeypatch.setenv("DIGEST_BATCH_MODE", "false")
    calls = []

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        calls.append(user_prompt)
        return "tekil brifing"

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    supervision = OperationsManager(advisors=_personas()).run()

    assert len(calls) == 3
    assert all(b.status == STATUS_OK for b in supervision.briefings)


def test_batch_uses_a_larger_token_budget(monkeypatch, llm_env):
    seen = {}

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        seen["tokens"] = max_output_tokens
        return _BATCHED_RESPONSE

    monkeypatch.setattr(llm, "generate_text", fake_generate)
    run_batch(_personas())

    assert seen["tokens"] == _batch.DEFAULT_BATCH_MAX_OUTPUT_TOKENS


def test_non_llm_advisors_stay_out_of_the_batch(llm_env):
    assert WeatherAdvisor().batch_section() is None
    assert AnkaBridgeAdvisor().batch_section() is None


def test_no_llm_key_means_no_batch(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})

    assert collect_sections(_personas()) == []
    assert run_batch(_personas()) == {}


def test_batched_error_message_never_contains_the_key(monkeypatch, llm_env):
    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        # The llm layer redacts before raising; assert nothing re-adds the key.
        raise RuntimeError("HTTP 503: model overloaded (key=REDACTED)")

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    supervision = OperationsManager(advisors=_personas()).run()

    assert all(b.status == STATUS_FAILED for b in supervision.briefings)
    assert all(FAKE_KEY not in b.text for b in supervision.briefings)
