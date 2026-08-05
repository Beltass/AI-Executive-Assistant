"""Tests for the run-metrics layer (offline, no real network).

Covers the three things that make token accounting trustworthy:

* the arithmetic — efficiency, per-advisor attribution, pruning;
* the recommendations — every sentence must come from a recorded NUMBER, and an
  empty history must produce no advice at all rather than invented advice;
* the fail-safe — a metrics failure can never break a run, and no secret can
  ever reach the file (it is committed to a PUBLIC repository).
"""

from __future__ import annotations

import json

import pytest

from ai_assistant import metrics
from ai_assistant.advisors import Briefing
from ai_assistant.advisors._batch import BatchOutcome
from ai_assistant.config import MODE_FULL, MODE_INCREMENTAL
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ai_assistant.integrations.llm import CallStats
from ai_assistant.operations_manager import Supervision

# --- helpers ----------------------------------------------------------------


def _supervision(sections: dict, mode: str = MODE_FULL, failed: int = 0) -> Supervision:
    briefings = [
        Briefing(key=key, title=key.title(), status=STATUS_OK, text="x" * chars)
        for key, chars in sections.items()
    ]
    for index in range(failed):
        briefings.append(
            Briefing(
                key=f"broken_{index}",
                title="Bozuk",
                status=STATUS_FAILED,
                text="patladı",
            )
        )
    return Supervision(briefings=briefings, mode=mode)


def _stats(**kwargs) -> CallStats:
    base = dict(
        provider="gemini",
        model="gemini-2.5-flash",
        prompt_tokens=10000,
        output_tokens=6000,
        thoughts_tokens=2000,
        total_tokens=18000,
        latency_seconds=42.5,
        retries=0,
        fallback_used=False,
        models_tried=1,
        ok=True,
    )
    base.update(kwargs)
    return CallStats(**base)


def _run(**kwargs) -> dict:
    """A synthetic run record with sane defaults, overridable per test."""
    base = {
        "mode": MODE_FULL,
        "llm_called": True,
        "llm_ok": True,
        "prompt_tokens": 10000,
        "output_tokens": 6000,
        "thoughts_tokens": 2000,
        "total_tokens": 18000,
        "characters": 24000,
        "sections": 12,
        "retries": 0,
        "fallback_used": False,
        "latency_seconds": 40.0,
        "chars_per_1k_tokens": metrics.chars_per_1k_tokens(24000, 18000),
        "guide_saved_chars": 0,
        "agents": [],
    }
    base.update(kwargs)
    return base


# --- efficiency maths -------------------------------------------------------


def test_chars_per_1k_tokens_is_text_per_thousand_tokens():
    assert metrics.chars_per_1k_tokens(24000, 12000) == 2000.0


def test_efficiency_metrics_are_zero_not_infinite_without_tokens():
    """A quiet run made no call at all — dividing by it must not blow up."""
    assert metrics.chars_per_1k_tokens(500, 0) == 0.0
    assert metrics.tokens_per_section(0, 0) == 0.0


def test_tokens_per_section_divides_the_call_across_what_it_produced():
    assert metrics.tokens_per_section(18000, 12) == 1500.0


# --- per-advisor attribution ------------------------------------------------


def test_attribution_splits_input_by_prompt_and_output_by_produced_text():
    """The whole point: an advisor's INPUT cost follows its prompt length.

    A proportional-by-output split would make ``verbose`` (a huge prompt, a tiny
    answer) look cheap. Splitting input by prompt size exposes it.
    """
    rows = metrics.attribute_tokens(
        produced_chars={"verbose": 100, "terse": 900},
        prompt_chars={"verbose": 9000, "terse": 1000},
        prompt_tokens=1000,
        output_tokens=1000,
    )
    by_id = {row["id"]: row for row in rows}

    assert by_id["verbose"]["est_prompt_tokens"] == 900  # 90% of the prompt
    assert by_id["verbose"]["est_output_tokens"] == 100  # 10% of the answer
    assert by_id["verbose"]["est_total_tokens"] == 1000

    # Spends half the tokens, produces a tenth of the text.
    assert by_id["verbose"]["token_share"] == 50.0
    assert by_id["verbose"]["output_share"] == 10.0


def test_attribution_shares_sum_to_the_real_total():
    """Approximate per advisor, exact in aggregate."""
    rows = metrics.attribute_tokens(
        produced_chars={"a": 300, "b": 500, "c": 200},
        prompt_chars={"a": 1000, "b": 2000, "c": 3000},
        prompt_tokens=6000,
        output_tokens=4000,
    )
    assert sum(row["est_total_tokens"] for row in rows) == pytest.approx(10000, abs=2)
    assert sum(row["token_share"] for row in rows) == pytest.approx(100.0, abs=0.3)


def test_attribution_keeps_an_advisor_that_cost_input_but_produced_nothing():
    """The most expensive advisor of all is one you paid for and got nothing from."""
    rows = metrics.attribute_tokens(
        produced_chars={"worked": 1000},
        prompt_chars={"worked": 500, "silent": 500},
        prompt_tokens=1000,
        output_tokens=1000,
    )
    silent = next(row for row in rows if row["id"] == "silent")
    assert silent["est_prompt_tokens"] == 500
    assert silent["est_output_tokens"] == 0
    assert silent["output_share"] == 0.0


def test_attribution_survives_an_empty_run():
    assert metrics.attribute_tokens({}, {}, 0, 0) == []


# --- building a run record --------------------------------------------------


def test_build_run_metrics_records_tokens_latency_and_counts():
    supervision = _supervision({"alpha": 1200, "beta": 800}, failed=1)
    batch = BatchOutcome(
        sections_requested=3,
        prompt_chars={"alpha": 4000, "beta": 1000},
        prompt_chars_total=9000,
        guide_saved_chars=2500,
    )
    record = metrics.build_run_metrics(
        supervision, call_stats=_stats(), batch=batch, duration_seconds=91.4
    )

    assert record["prompt_tokens"] == 10000
    assert record["output_tokens"] == 6000
    assert record["thoughts_tokens"] == 2000
    assert record["total_tokens"] == 18000
    assert record["latency_seconds"] == 42.5
    assert record["duration_seconds"] == 91.4
    assert record["model"] == "gemini-2.5-flash"
    assert record["advisors_ok"] == 2
    assert record["advisors_failed"] == 1
    assert record["sections"] == 2
    assert record["characters"] == 2000
    assert record["guide_saved_chars"] == 2500
    # Derived efficiency.
    assert record["chars_per_1k_tokens"] == pytest.approx(111.1, abs=0.1)
    assert record["tokens_per_section"] == 9000.0
    assert record["thoughts_share"] == pytest.approx(11.1, abs=0.1)
    # And the attribution is explicitly labelled an estimate.
    assert record["attribution"] == "estimate"
    assert {row["id"] for row in record["agents"]} == {"alpha", "beta"}


def test_build_run_metrics_without_any_llm_call_is_all_zeroes():
    """A quiet incremental run costs nothing and must be recorded as such."""
    record = metrics.build_run_metrics(
        _supervision({}, mode=MODE_INCREMENTAL), call_stats=None, batch=None
    )
    assert record["llm_called"] is False
    assert record["total_tokens"] == 0
    assert record["chars_per_1k_tokens"] == 0.0
    assert record["mode"] == MODE_INCREMENTAL


def test_nothing_new_sections_do_not_count_as_produced_text():
    quiet = Briefing(
        key="ai_news",
        title="Haberler",
        status=STATUS_SKIPPED,
        text="yeni bulgu yok",
        nothing_new=True,
    )
    supervision = Supervision(briefings=[quiet], mode=MODE_INCREMENTAL)
    record = metrics.build_run_metrics(supervision, call_stats=_stats(), batch=None)
    assert record["sections"] == 0
    assert record["characters"] == 0


# --- history: recording and pruning -----------------------------------------


def test_record_run_appends_to_the_history(tmp_path):
    target = tmp_path / "metrics.json"
    for _ in range(3):
        metrics.record_run(
            _supervision({"a": 500}), call_stats=_stats(), path=str(target)
        )
    document = json.loads(target.read_text(encoding="utf-8"))
    assert len(document["runs"]) == 3
    assert document["schema_version"] == metrics.SCHEMA_VERSION
    assert document["totals"]["runs"] == 3


def test_history_is_pruned_to_the_rolling_window(tmp_path):
    target = tmp_path / "metrics.json"
    old = [_run(at=str(index)) for index in range(metrics.HISTORY_LIMIT + 25)]
    target.write_text(json.dumps({"runs": old}), encoding="utf-8")

    metrics.record_run(_supervision({"a": 100}), call_stats=_stats(), path=str(target))

    document = json.loads(target.read_text(encoding="utf-8"))
    assert len(document["runs"]) == metrics.HISTORY_LIMIT
    # The NEWEST runs survive: the record just written is last.
    assert document["runs"][-1]["characters"] == 100
    # …and the oldest ones are the ones that went.
    assert document["runs"][0]["at"] == str(len(old) + 1 - metrics.HISTORY_LIMIT)


def test_prune_keeps_everything_when_the_limit_is_disabled():
    runs = [_run() for _ in range(10)]
    assert len(metrics.prune(runs, limit=0)) == 10


def test_a_corrupt_history_file_is_replaced_not_fatal(tmp_path):
    target = tmp_path / "metrics.json"
    target.write_text("{not json at all", encoding="utf-8")
    assert metrics.record_run(_supervision({"a": 10}), path=str(target)) == str(target)
    assert len(json.loads(target.read_text(encoding="utf-8"))["runs"]) == 1


def test_record_run_never_raises_on_an_unwritable_path(tmp_path):
    """Fail-safe: a metrics failure must cost a measurement, never the run."""
    blocked = tmp_path / "file.txt"
    blocked.write_text("occupied", encoding="utf-8")
    assert (
        metrics.record_run(
            _supervision({"a": 10}), path=str(blocked / "nested" / "metrics.json")
        )
        is None
    )


def test_metrics_file_path_honours_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv(metrics.METRICS_FILE_ENV, str(tmp_path / "custom.json"))
    assert metrics.metrics_file_path() == str(tmp_path / "custom.json")
    monkeypatch.setenv(metrics.METRICS_FILE_ENV, "  ")
    assert metrics.metrics_file_path() == metrics.DEFAULT_METRICS_FILE


# --- recommendations --------------------------------------------------------


def test_no_history_yields_no_recommendations():
    """An empty history must stay silent rather than invent generic advice."""
    assert metrics.recommendations([]) == []


def test_expensive_agent_is_named_with_both_of_its_real_shares():
    history = [
        _run(
            agents=[
                {
                    "id": "banking_cc_projects",
                    "name": "Bankacılık Projeleri",
                    "est_total_tokens": 5200,
                    "output_chars": 3800,
                },
                {
                    "id": "weather",
                    "name": "Hava Durumu",
                    "est_total_tokens": 4800,
                    "output_chars": 6200,
                },
            ]
        )
        for _ in range(5)
    ]
    tips = metrics.recommendations(history)
    expensive = [t for t in tips if t["advisor"] == "banking_cc_projects"]
    assert expensive, "the over-spending agent should be called out"
    detail = expensive[0]["detail"]
    # Both real shares appear, and they are the numbers actually recorded.
    assert "%52" in detail and "%38" in detail
    assert expensive[0]["severity"] == metrics.SEVERITY_WARN


def test_a_balanced_agent_is_not_called_out():
    history = [
        _run(
            agents=[
                {
                    "id": "a",
                    "name": "A",
                    "est_total_tokens": 5000,
                    "output_chars": 5000,
                },
                {
                    "id": "b",
                    "name": "B",
                    "est_total_tokens": 5000,
                    "output_chars": 5000,
                },
            ]
        )
        for _ in range(5)
    ]
    assert not [t for t in metrics.recommendations(history) if t.get("advisor")]


def test_fallback_incidence_is_counted_over_the_window():
    history = [_run(fallback_used=index < 5) for index in range(7)]
    tips = metrics.recommendations(history)
    fallback = [t for t in tips if "Yedek" in t["title"]]
    assert fallback
    assert "7 çalıştırmanın 5 tanesinde" in fallback[0]["detail"]


def test_no_fallback_means_no_fallback_advice():
    history = [_run(fallback_used=False) for _ in range(7)]
    assert not [t for t in metrics.recommendations(history) if "Yedek" in t["title"]]


def test_incremental_run_sending_a_full_prompt_is_flagged():
    history = [_run(mode=MODE_FULL, prompt_tokens=10000, sections=12)] + [
        _run(mode=MODE_INCREMENTAL, prompt_tokens=9000, sections=3) for _ in range(3)
    ]
    tips = metrics.recommendations(history)
    incremental = [t for t in tips if "Artımlı" in t["title"]]
    assert incremental
    assert "3.0 bölüm" in incremental[0]["detail"]
    assert incremental[0]["severity"] == metrics.SEVERITY_WARN


def test_a_genuinely_cheap_incremental_run_is_praised_not_flagged():
    history = [_run(mode=MODE_FULL, prompt_tokens=10000, sections=12)] + [
        _run(mode=MODE_INCREMENTAL, prompt_tokens=1500, sections=3) for _ in range(3)
    ]
    incremental = [
        t for t in metrics.recommendations(history) if "Artımlı" in t["title"]
    ]
    assert incremental and incremental[0]["severity"] == metrics.SEVERITY_GOOD


def test_thinking_token_share_is_reported_from_the_real_numbers():
    history = [_run(thoughts_tokens=9000, total_tokens=18000) for _ in range(3)]
    thinking = [t for t in metrics.recommendations(history) if "Düşünme" in t["title"]]
    assert thinking
    assert "%50" in thinking[0]["detail"]


def test_no_thinking_tokens_means_no_thinking_advice():
    history = [_run(thoughts_tokens=0) for _ in range(3)]
    assert not [t for t in metrics.recommendations(history) if "Düşünme" in t["title"]]


def test_input_heavier_than_output_is_flagged():
    history = [_run(prompt_tokens=14000, output_tokens=3000) for _ in range(3)]
    tips = [t for t in metrics.recommendations(history) if "Girdi" in t["title"]]
    assert tips and "14000" in tips[0]["detail"]


def test_every_recommendation_carries_a_severity_and_a_metric():
    history = [
        _run(
            fallback_used=True,
            retries=2,
            guide_saved_chars=26000,
            agents=[
                {
                    "id": "x",
                    "name": "X",
                    "est_total_tokens": 9000,
                    "output_chars": 1000,
                },
                {
                    "id": "y",
                    "name": "Y",
                    "est_total_tokens": 1000,
                    "output_chars": 9000,
                },
            ],
        )
        for _ in range(6)
    ]
    tips = metrics.recommendations(history)
    assert tips
    for tip in tips:
        assert tip["severity"] in {
            metrics.SEVERITY_GOOD,
            metrics.SEVERITY_INFO,
            metrics.SEVERITY_WARN,
        }
        assert tip["title"] and tip["detail"] and tip["metric"]


def test_recommendations_only_look_at_the_recent_window():
    old = [_run(fallback_used=True) for _ in range(20)]
    recent = [_run(fallback_used=False) for _ in range(metrics.WINDOW)]
    tips = metrics.recommendations(old + recent)
    assert not [t for t in tips if "Yedek" in t["title"]]


def test_recommendations_survive_malformed_records():
    assert metrics.recommendations([{"agents": "not a list"}, {}]) is not None


# --- privacy ----------------------------------------------------------------


def test_no_secret_can_reach_the_metrics_file(monkeypatch, tmp_path):
    """The file is committed to a PUBLIC repository: only numbers may land in it."""
    secret = "AIzaSyFAKEKEYFAKEKEYFAKEKEYFAKEKEY123"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/T/B/XYZ")

    supervision = _supervision({"alpha": 400})
    # Even an advisor whose FAILURE text leaked a key must not put it on file.
    supervision.briefings.append(
        Briefing(
            key="leaky",
            title="Sızdıran",
            status=STATUS_FAILED,
            text=f"HTTP 400 for key={secret}",
        )
    )
    target = tmp_path / "metrics.json"
    metrics.record_run(supervision, call_stats=_stats(), path=str(target))

    raw = target.read_text(encoding="utf-8")
    assert secret not in raw
    assert "hooks.slack.com" not in raw
    # And no free text from a briefing body either — only counts.
    assert "HTTP 400" not in raw


# --- what the run SPENT and WHO spent it ------------------------------------
#
# Tokens alone cannot explain a run: a tenth of yesterday's cost is a triumph
# when nine advisors had no new data and an outage when the batch died. These
# three fields are what tell the two apart.


def test_llm_call_count_is_read_from_the_llm_layer(monkeypatch):
    """ONE batched call or fifteen per-advisor ones — the number says which."""
    from ai_assistant.integrations import llm as llm_module

    llm_module.reset_call_count()
    monkeypatch.setattr(llm_module, "call_count", lambda: 15)

    record = metrics.build_run_metrics(
        _supervision({"alpha": 100}), call_stats=_stats()
    )

    assert record["llm_call_count"] == 15


def test_llm_call_count_is_zero_when_nothing_was_called():
    from ai_assistant.integrations import llm as llm_module

    llm_module.reset_call_count()
    record = metrics.build_run_metrics(_supervision({}), call_stats=None)

    assert record["llm_call_count"] == 0


def test_an_explicit_call_count_wins_over_the_counter():
    record = metrics.build_run_metrics(
        _supervision({"alpha": 100}), call_stats=_stats(), llm_call_count=1
    )
    assert record["llm_call_count"] == 1


def test_skipped_advisors_are_recorded_with_their_reasons():
    supervision = _supervision({"alpha": 400})
    supervision.executed_advisors = ["alpha"]
    supervision.skipped_advisors = {
        "market_intelligence": "veri_degismedi",
        "executive_coaching": "tetiklenmedi",
        "career_development": "batch_failed",
    }

    record = metrics.build_run_metrics(supervision, call_stats=_stats())

    assert record["executed_advisors"] == ["alpha"]
    assert record["skipped_advisors"] == {
        "market_intelligence": "veri_degismedi",
        "executive_coaching": "tetiklenmedi",
        "career_development": "batch_failed",
    }


def test_the_reasons_reach_the_history_file(tmp_path):
    supervision = _supervision({"alpha": 400})
    supervision.skipped_advisors = {"market_intelligence": "veri_degismedi"}
    target = tmp_path / "metrics.json"

    metrics.record_run(supervision, call_stats=_stats(), path=str(target))

    run = json.loads(target.read_text(encoding="utf-8"))["runs"][0]
    assert run["skipped_advisors"] == {"market_intelligence": "veri_degismedi"}
    assert "llm_call_count" in run


def test_a_supervision_without_the_new_fields_still_records():
    """Anything shaped like a supervision keeps working — never raises."""

    class Bare:
        briefings = []
        counts = {STATUS_OK: 0, STATUS_FAILED: 0, STATUS_SKIPPED: 0}

    record = metrics.build_run_metrics(Bare(), call_stats=None)

    assert record["executed_advisors"] == []
    assert record["skipped_advisors"] == {}
