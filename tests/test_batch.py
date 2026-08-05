"""Tests for the batched briefing mode (offline, no real network).

The free Gemini tier only allows a couple of ``generateContent`` calls per
quota window, so the whole advisor team is served by ONE batched call. These
tests cover:
- the batched response is split back apart per advisor;
- exactly one LLM call is made for the whole team;
- a failing batched call says WHY it failed and, by default, makes no
  per-advisor calls at all (``DIGEST_BATCH_FALLBACK_MODE``);
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
from ai_assistant.integrations import STATUS_OK, STATUS_SKIPPED
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


# --- the fallback gate (DIGEST_BATCH_FALLBACK_MODE) -------------------------
#
# The batch normally fails because the free-tier quota is gone. Re-asking every
# advisor on its own then spends one dead call per advisor discovering that,
# which is the single most expensive thing this codebase can do — hence the
# fallback is opt-in and OFF by default.


def test_batch_failure_makes_no_per_advisor_calls_by_default(monkeypatch, llm_env):
    calls = []

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        calls.append(user_prompt)
        if SECTION_MARKER in user_prompt:
            raise RuntimeError("gemini tüm modellerde başarısız — son hata: HTTP 503")
        return "tekil brifing"

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    supervision = OperationsManager(advisors=_personas()).run()

    # ONE failed batched attempt, and nothing after it.
    assert len(calls) == 1
    assert all(b.status == STATUS_SKIPPED for b in supervision.briefings)
    assert all("DIGEST_BATCH_FALLBACK_MODE" in b.text for b in supervision.briefings)
    assert set(supervision.skipped_advisors) == {
        "leadership_coach",
        "kids_development",
        "career_hr",
    }
    assert set(supervision.skipped_advisors.values()) == {"batch_failed"}


def test_batch_failure_falls_back_per_advisor_when_asked(monkeypatch, llm_env):
    monkeypatch.setenv("DIGEST_BATCH_FALLBACK_MODE", "per_advisor")
    calls = []

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        calls.append(user_prompt)
        if SECTION_MARKER in user_prompt:
            raise RuntimeError("gemini tüm modellerde başarısız — son hata: HTTP 503")
        return "tekil brifing"

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    supervision = OperationsManager(advisors=_personas()).run()

    # 1 failed batched attempt + one call per advisor — the pre-gate behaviour.
    assert len(calls) == 4
    assert all(b.status == STATUS_OK for b in supervision.briefings)
    assert all(b.text == "tekil brifing" for b in supervision.briefings)
    assert supervision.skipped_advisors == {}


def test_failed_batch_records_why_it_failed(monkeypatch, llm_env):
    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        raise RuntimeError("HTTP 429: quota exceeded")

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    assert run_batch(_personas()) == {}

    outcome = _batch.last_outcome()
    assert outcome.failed is True
    assert outcome.failure_reason == _batch.REASON_LLM_ERROR
    assert "429" in outcome.failure_detail
    assert set(outcome.participants) == {
        "leadership_coach",
        "kids_development",
        "career_hr",
    }


def test_disabled_batch_is_reported_as_disabled_not_as_a_failure(monkeypatch, llm_env):
    monkeypatch.setenv("DIGEST_BATCH_MODE", "false")

    assert run_batch(_personas()) == {}

    outcome = _batch.last_outcome()
    assert outcome.failed is False
    assert outcome.failure_reason == _batch.REASON_DISABLED
    # Nobody was in the batch, so nobody may be skipped because of it.
    assert outcome.participants == ()
    assert outcome.missing("leadership_coach") is False


def test_unparsable_response_is_reported_as_such(monkeypatch, llm_env):
    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        return "Bölüm işaretçisi olmayan bir yanıt."

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    assert run_batch(_personas()) == {}
    assert _batch.last_outcome().failure_reason == _batch.REASON_UNPARSABLE


def test_missing_section_skips_only_that_advisor(monkeypatch, llm_env):
    calls = []
    partial = f"{SECTION_MARKER} leadership_coach\nSadece liderlik.\n"

    def fake_generate(system_prompt, user_prompt, max_output_tokens=None):
        calls.append(user_prompt)
        if SECTION_MARKER in user_prompt:
            return partial
        return "tekil brifing"

    monkeypatch.setattr(llm, "generate_text", fake_generate)

    supervision = OperationsManager(advisors=_personas()).run()

    # ONE batched call: the two omitted sections are skipped, not re-asked.
    assert len(calls) == 1
    texts = {b.key: b.text for b in supervision.briefings}
    assert texts["leadership_coach"] == "Sadece liderlik."
    assert set(supervision.skipped_advisors) == {"kids_development", "career_hr"}


def test_missing_section_falls_back_to_that_advisor_only_when_asked(
    monkeypatch, llm_env
):
    monkeypatch.setenv("DIGEST_BATCH_FALLBACK_MODE", "per_advisor")
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

    assert all(b.status == STATUS_SKIPPED for b in supervision.briefings)
    assert all(FAKE_KEY not in b.text for b in supervision.briefings)
    assert FAKE_KEY not in _batch.last_outcome().failure_detail


def test_batch_prompt_demands_the_headline_first_line():
    """The compact Slack index is built from that line, so it must be asked for."""
    from ai_assistant.advisors._batch import HEADLINE_LABEL, build_batch_prompt
    from ai_assistant.advisors import BatchSection

    prompt = build_batch_prompt(
        [
            BatchSection(key="a", title="A", system_prompt="s", user_prompt="u"),
            BatchSection(key="b", title="B", system_prompt="s", user_prompt="u"),
        ]
    )
    assert HEADLINE_LABEL == "Öne çıkan"
    assert f"**{HEADLINE_LABEL}:**" in prompt
    assert "200" in prompt


def test_the_headline_the_prompt_asks_for_is_the_one_the_extractor_finds():
    """The prompt and the parser must not drift apart."""
    from ai_assistant.advisors._batch import HEADLINE_LABEL
    from ai_assistant.reports import extract_headline

    section = f"**{HEADLINE_LABEL}:** Tek cümlelik bulgu.\n\nGerisi burada."
    assert extract_headline(section) == "Tek cümlelik bulgu."


# --- prompt token efficiency ------------------------------------------------
#
# Twelve personas append the identical ~2.4 KB writing guide to their user
# prompt. That was free when each advisor made its own call; in ONE batched
# request it is the same essay transmitted a dozen times. These tests pin the
# fix: the guide is stated once, the instructions are unchanged, and the saving
# is measured rather than asserted by hand.

from ai_assistant.advisors import BatchSection  # noqa: E402
from ai_assistant.advisors._llm_base import (  # noqa: E402
    COMPACT_BRIEFING_GUIDE,
    LLMAdvisor,
    RICH_BRIEFING_GUIDE,
    SHARED_GUIDE_POINTER,
)


def _advisor(key: str, user_prompt: str) -> LLMAdvisor:
    """A minimal LLM persona whose prompt length the test controls."""
    advisor = LLMAdvisor()
    advisor.key = key
    advisor.title = key
    advisor.system_prompt = "sen bir uzmansın"
    advisor.user_prompt = user_prompt
    return advisor


def _guided_sections(count: int = 3):
    return [
        BatchSection(
            key=f"advisor_{index}",
            title=f"Danışman {index}",
            system_prompt=f"sen {index} numaralı uzmansın",
            user_prompt=f"bugünkü görev {index}\n\n" + RICH_BRIEFING_GUIDE,
        )
        for index in range(count)
    ]


def test_shared_guide_is_sent_once_not_once_per_section():
    prompt = _batch.build_batch_prompt(_guided_sections(4))
    assert prompt.count(RICH_BRIEFING_GUIDE) == 1
    # Every section still points at it, so no persona loses its instructions.
    assert prompt.count(SHARED_GUIDE_POINTER) == 4


def test_deduping_the_guide_saves_the_repeated_bytes():
    sections = _guided_sections(12)
    trimmed, shared, saved = _batch.split_shared_guide(sections)
    assert shared == RICH_BRIEFING_GUIDE
    # 11 of the 12 copies are gone, minus the small pointer left behind.
    assert saved > len(RICH_BRIEFING_GUIDE) * 10
    assert all(RICH_BRIEFING_GUIDE not in s.user_prompt for s in trimmed)


def test_deduping_actually_shrinks_the_prompt_that_gets_sent(monkeypatch):
    """The saving is measured on the real prompt, not on the helper alone."""
    sections = _guided_sections(12)
    deduped = len(_batch.build_batch_prompt(sections))

    # Rebuild with the dedup disabled to get the "before" size.
    monkeypatch.setattr(
        _batch, "split_shared_guide", lambda secs, inc=False: (list(secs), "", 0)
    )
    naive = len(_batch.build_batch_prompt(sections))

    assert deduped < naive
    # A third of the whole prompt is repeated boilerplate at this team size.
    assert (naive - deduped) / naive > 0.3


def test_incremental_mode_sends_the_short_guide():
    """A top-up reporting two new items does not need the depth coaching."""
    prompt = _batch.build_batch_prompt(_guided_sections(3), incremental=True)
    assert COMPACT_BRIEFING_GUIDE in prompt
    assert RICH_BRIEFING_GUIDE not in prompt
    assert len(prompt) < len(_batch.build_batch_prompt(_guided_sections(3)))


def test_a_single_guide_carrier_is_left_completely_alone():
    """Nothing to dedupe: one copy is already one copy."""
    sections = _guided_sections(1)
    trimmed, shared, saved = _batch.split_shared_guide(sections)
    assert (shared, saved) == ("", 0)
    assert trimmed[0].user_prompt == sections[0].user_prompt


def test_sections_without_the_guide_are_untouched():
    sections = _guided_sections(2) + [
        BatchSection(key="plain", title="Düz", system_prompt="s", user_prompt="p")
    ]
    trimmed, _shared, _saved = _batch.split_shared_guide(sections)
    assert trimmed[-1].user_prompt == "p"


def test_the_output_contract_survives_deduping():
    """The response-format rules must be intact, or nothing parses."""
    prompt = _batch.build_batch_prompt(_guided_sections(3))
    assert _batch.SECTION_MARKER in prompt
    assert _batch.HEADLINE_LABEL in prompt
    for index in range(3):
        assert f"advisor_{index}" in prompt


def test_run_batch_records_per_advisor_prompt_sizes(monkeypatch, llm_env):
    """Metrics needs these to split one call's input tokens across advisors."""
    advisors = [
        _advisor(f"advisor_{index}", user_prompt="x" * (100 * (index + 1)))
        for index in range(3)
    ]
    monkeypatch.setattr(
        _batch.llm,
        "generate_text",
        lambda *a, **k: "\n".join(
            f"### SECTION: advisor_{index}\ngövde {index}" for index in range(3)
        ),
    )

    _batch.run_batch(advisors)

    outcome = _batch.last_outcome()
    assert set(outcome.prompt_chars) == {"advisor_0", "advisor_1", "advisor_2"}
    assert outcome.prompt_chars["advisor_2"] > outcome.prompt_chars["advisor_0"]
    assert outcome.prompt_chars_total > sum(outcome.prompt_chars.values())
