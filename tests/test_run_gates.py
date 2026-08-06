"""Tests for WHO runs on a given run — the two manifest-driven gates.

Every advisor used to run four times a day whatever it had to say. Two gates
now decide instead, and both exist for one reason: a model call that would
produce what the user already read this morning is pure quota.

* the TRIGGER gate (:mod:`ai_assistant.status_report` ``trigger`` field) —
  ``always`` runs every time, ``weekly`` only on the weekly slot,
  ``user_requested`` only when named in ``DIGEST_FORCE_ADVISORS``;
* the DATA gate (:mod:`ai_assistant.memory` source hashes) — a
  ``data_triggered`` advisor whose source did not move since the last DELIVERED
  run is skipped before a single token is spent.

Everything here is offline: the LLM is a counter, the ledger is a temp file.
The assertion that matters in almost every test is the SAME one — how many
model calls were made.
"""

from __future__ import annotations

import pytest

from ai_assistant import config, memory, metrics
from ai_assistant.advisors import Advisor, BatchSection
from ai_assistant.advisors._batch import SECTION_MARKER
from ai_assistant.status_report import TRIGGER_WEEKLY
from ai_assistant.integrations import STATUS_OK, STATUS_SKIPPED, llm
from ai_assistant.operations_manager import (
    SKIP_DATA_UNCHANGED,
    SKIP_NO_OUTPUT,
    SKIP_NOT_TRIGGERED,
    OperationsManager,
    forced_advisors,
    not_triggered_reason,
    skip_note,
    trigger_allows,
    weekly_due,
)

FAKE_KEY = "AQ.FAKE-secret-key-should-never-leak-123456"

# Real manifest keys, so the gates read the real trigger/data_owner metadata.
ALWAYS = "morning_operations"  # trigger: always
WEEKLY = "executive_coaching"  # trigger: weekly
DATA_A = "drive_insight"  # trigger: data_triggered, owner drive_files
DATA_B = "complaint_radar"  # trigger: data_triggered, owner complaint_feeds
ON_REQUEST = "kids_development"  # trigger: user_requested


class FakeAdvisor(Advisor):
    """An advisor whose gathered material is one string we control.

    ``payload`` IS the batch section's user prompt, which is exactly what the
    data gate hashes — so "the source changed" is expressed in a test by
    handing the advisor a different string.
    """

    def __init__(self, key: str, payload: str = "aynı veri") -> None:
        self.key = key
        self.title = key
        self.payload = payload
        self.own_calls = 0

    def batch_section(self) -> BatchSection:
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt="persona",
            user_prompt=self.payload,
        )

    def _generate(self):
        # The per-advisor path: counted so a test can prove it was NOT taken.
        self.own_calls += 1
        return self.ok(f"{self.key} tekil gövde")


@pytest.fixture()
def run_env(monkeypatch, tmp_path):
    """Configured key, empty settings, isolated ledger, no stray env gates."""
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DIGEST_BATCH_MODE", raising=False)
    monkeypatch.delenv("DIGEST_BATCH_FALLBACK_MODE", raising=False)
    monkeypatch.delenv("DIGEST_FORCE_ADVISORS", raising=False)
    monkeypatch.delenv("BRIEFING_MODE", raising=False)
    monkeypatch.setenv("DIGEST_WEEKLY_RUN", "false")
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})
    memory.reset(path=str(tmp_path / "findings.json"))
    llm.reset_call_stats()
    yield
    memory.reset()


@pytest.fixture()
def calls(monkeypatch):
    """Record every batched prompt and answer with a section per advisor."""
    recorded = []

    def fake_generate(system_prompt, user_prompt, **kwargs):
        recorded.append(user_prompt)
        parts = []
        for chunk in user_prompt.split("kimlik: ")[1:]:
            key = chunk.split(" ", 1)[0].strip()
            parts.append(f"{SECTION_MARKER} {key}\n{key} toplu gövde.\n")
        return "\n".join(parts)

    monkeypatch.setattr(llm, "generate_text", fake_generate)
    return recorded


def _run(advisors):
    return OperationsManager(advisors=advisors, use_manifest_filters=True).run()


# --- the trigger gate -------------------------------------------------------


def test_always_advisors_run_on_every_run(run_env, calls):
    always = FakeAdvisor(ALWAYS)
    other = FakeAdvisor(DATA_A)

    supervision = _run([always, other])

    assert ALWAYS in supervision.executed_advisors
    assert ALWAYS not in supervision.skipped_advisors
    assert len(calls) == 1


def test_weekly_advisor_stays_out_of_a_daily_run(run_env, calls, monkeypatch):
    monkeypatch.setenv("DIGEST_WEEKLY_RUN", "false")
    weekly = FakeAdvisor(WEEKLY)
    always = FakeAdvisor(ALWAYS)

    supervision = _run([always, weekly])

    assert supervision.skipped_advisors[WEEKLY] == "tetiklenmedi(weekly)"
    assert weekly.own_calls == 0
    assert WEEKLY not in "\n".join(calls)  # never even entered the prompt


def test_weekly_advisor_runs_on_the_weekly_slot(run_env, calls, monkeypatch):
    monkeypatch.setenv("DIGEST_WEEKLY_RUN", "true")
    weekly = FakeAdvisor(WEEKLY)
    always = FakeAdvisor(ALWAYS)

    supervision = _run([always, weekly])

    assert WEEKLY in supervision.executed_advisors
    assert WEEKLY in calls[0]


def test_user_requested_advisor_only_runs_when_named(run_env, calls, monkeypatch):
    always = FakeAdvisor(ALWAYS)
    on_request = FakeAdvisor(ON_REQUEST)

    quiet = _run([always, FakeAdvisor(ON_REQUEST)])
    assert quiet.skipped_advisors[ON_REQUEST] == "tetiklenmedi(user_requested)"

    monkeypatch.setenv("DIGEST_FORCE_ADVISORS", f"{ON_REQUEST}, birseyler")
    asked = _run([always, on_request])
    assert ON_REQUEST in asked.executed_advisors


def test_force_all_runs_the_whole_roster(run_env, monkeypatch):
    monkeypatch.setenv("DIGEST_FORCE_ADVISORS", "ALL")
    forced = forced_advisors()

    assert trigger_allows(WEEKLY, forced, weekly=False) is True
    assert trigger_allows(ON_REQUEST, forced, weekly=False) is True


def test_an_advisor_outside_the_manifest_is_never_silenced(run_env):
    assert trigger_allows("uydurma_danisman", frozenset(), weekly=False) is True


def test_weekly_slot_falls_back_to_the_weekday(monkeypatch):
    from datetime import datetime

    monkeypatch.delenv("DIGEST_WEEKLY_RUN", raising=False)
    monkeypatch.delenv("DIGEST_WEEKLY_DAY", raising=False)

    assert weekly_due(datetime(2026, 8, 3)) is True  # Monday
    assert weekly_due(datetime(2026, 8, 4)) is False  # Tuesday


# --- the weekly CADENCE gate ------------------------------------------------
#
# The weekday check above is a DAY gate: it opens on every run made that
# Monday. With four runs a day the "weekly" advisors ran four times a week
# (``ai_innovation``: 10 runs in 9 days). The ledger closes it after the first.


@pytest.fixture()
def weekday_weekly(monkeypatch):
    """No env override: the weekday + ledger path is the one under test.

    The weekly DAY is pinned to today so the day gate is open whenever the
    suite happens to run; what the tests then assert is the cadence.
    """
    from datetime import datetime

    monkeypatch.delenv("DIGEST_WEEKLY_RUN", raising=False)
    monkeypatch.setenv("DIGEST_WEEKLY_DAY", str(datetime.now().weekday()))


def test_weekly_advisor_runs_only_once_on_the_same_day(
    run_env, calls, weekday_weekly
):
    """THE bug: the second Monday run must not re-run the weekly advisor."""
    first = _run([FakeAdvisor(ALWAYS), FakeAdvisor(WEEKLY)])
    assert WEEKLY in first.executed_advisors

    again = FakeAdvisor(WEEKLY)
    second = _run([FakeAdvisor(ALWAYS), again])

    assert second.skipped_advisors[WEEKLY] == "tetiklenmedi(weekly)"
    assert WEEKLY not in second.executed_advisors
    assert again.own_calls == 0  # not one token spent on it either


def test_weekly_advisor_runs_again_after_seven_days(run_env, weekday_weekly):
    from datetime import date, timedelta

    monday = date(2026, 8, 3)
    memory.mark_weekly_run(WEEKLY, monday)

    for days in (1, 6):
        assert memory.weekly_run_due(WEEKLY, monday + timedelta(days=days)) is False
    assert memory.weekly_run_due(WEEKLY, monday + timedelta(days=7)) is True


def test_weekly_cadence_is_per_advisor(run_env, weekday_weekly):
    from datetime import date

    monday = date(2026, 8, 3)
    memory.mark_weekly_run(WEEKLY, monday)

    assert memory.weekly_run_due(WEEKLY, monday) is False
    assert memory.weekly_run_due("baska_haftalik", monday) is True


def test_forcing_beats_the_weekly_cadence_gate(run_env, calls, weekday_weekly,
                                               monkeypatch):
    first = _run([FakeAdvisor(ALWAYS), FakeAdvisor(WEEKLY)])
    assert WEEKLY in first.executed_advisors

    monkeypatch.setenv("DIGEST_FORCE_ADVISORS", WEEKLY)
    forced = _run([FakeAdvisor(ALWAYS), FakeAdvisor(WEEKLY)])

    assert WEEKLY in forced.executed_advisors


def test_weekly_run_env_still_overrides_the_cadence_gate(
    run_env, calls, weekday_weekly, monkeypatch
):
    """The scheduled/manual switch stays the switch: env answers outright."""
    monkeypatch.setenv("DIGEST_WEEKLY_RUN", "true")
    first = _run([FakeAdvisor(ALWAYS), FakeAdvisor(WEEKLY)])
    second = _run([FakeAdvisor(ALWAYS), FakeAdvisor(WEEKLY)])

    assert WEEKLY in first.executed_advisors
    assert WEEKLY in second.executed_advisors

    monkeypatch.setenv("DIGEST_WEEKLY_RUN", "false")
    quiet = _run([FakeAdvisor(ALWAYS), FakeAdvisor(WEEKLY)])
    assert WEEKLY not in quiet.executed_advisors


def test_an_unreadable_ledger_never_blocks_a_weekly_advisor(run_env, weekday_weekly):
    """Fail-safe: uncertainty means RUN, exactly like the other gates."""
    from datetime import date

    ledger = memory.shared()
    memory.mark_weekly_run(WEEKLY, date(2026, 8, 3))
    ledger._readable = False

    assert ledger.weekly_run_due(WEEKLY, date(2026, 8, 3)) is True


# --- the data gate ----------------------------------------------------------


def test_unchanged_sources_cost_no_llm_call_at_all(run_env, calls):
    first = [FakeAdvisor(DATA_A, "haber 1"), FakeAdvisor(DATA_B, "şikayet 1")]
    supervision = _run(first)
    assert len(calls) == 1
    assert supervision.executed_advisors == [DATA_A, DATA_B]

    memory.commit()  # the digest went out: the source hashes are now committed

    second = [FakeAdvisor(DATA_A, "haber 1"), FakeAdvisor(DATA_B, "şikayet 1")]
    supervision = _run(second)

    assert len(calls) == 1  # STILL one: the second run called nothing
    assert supervision.skipped_advisors == {
        DATA_A: SKIP_DATA_UNCHANGED,
        DATA_B: SKIP_DATA_UNCHANGED,
    }
    assert [a.own_calls for a in second] == [0, 0]  # no per-advisor path either
    assert all(b.status == STATUS_SKIPPED for b in supervision.briefings)


def test_a_changed_source_runs_again(run_env, calls):
    _run([FakeAdvisor(DATA_A, "haber 1"), FakeAdvisor(DATA_B, "şikayet 1")])
    memory.commit()

    supervision = _run(
        [FakeAdvisor(DATA_A, "haber 2 — yeni"), FakeAdvisor(DATA_B, "şikayet 1")]
    )

    assert supervision.executed_advisors == [DATA_A]
    assert supervision.skipped_advisors == {DATA_B: SKIP_DATA_UNCHANGED}


def test_an_undelivered_run_does_not_commit_its_source_hashes(run_env, calls):
    _run([FakeAdvisor(DATA_A, "haber 1"), FakeAdvisor(DATA_B, "şikayet 1")])
    # No commit(): the digest never reached the user.
    supervision = _run(
        [FakeAdvisor(DATA_A, "haber 1"), FakeAdvisor(DATA_B, "şikayet 1")]
    )

    assert len(calls) == 2
    assert supervision.skipped_advisors == {}


def test_an_always_advisor_is_never_data_gated(run_env, calls):
    _run([FakeAdvisor(ALWAYS, "sabah"), FakeAdvisor(DATA_A, "haber 1")])
    memory.commit()

    supervision = _run([FakeAdvisor(ALWAYS, "sabah"), FakeAdvisor(DATA_A, "haber 1")])

    assert ALWAYS in supervision.executed_advisors
    assert supervision.skipped_advisors == {DATA_A: SKIP_DATA_UNCHANGED}


def test_forcing_an_advisor_bypasses_the_data_gate(run_env, calls, monkeypatch):
    _run([FakeAdvisor(DATA_A, "haber 1"), FakeAdvisor(DATA_B, "şikayet 1")])
    memory.commit()

    monkeypatch.setenv("DIGEST_FORCE_ADVISORS", DATA_A)
    supervision = _run(
        [FakeAdvisor(DATA_A, "haber 1"), FakeAdvisor(DATA_B, "şikayet 1")]
    )

    assert DATA_A in supervision.executed_advisors
    assert supervision.skipped_advisors == {DATA_B: SKIP_DATA_UNCHANGED}


def test_an_explicit_roster_is_not_gated_at_all(run_env, calls):
    """Handing the manager a list IS the request: the gates stay out of it."""
    _run([FakeAdvisor(DATA_A, "haber 1"), FakeAdvisor(DATA_B, "şikayet 1")])
    memory.commit()

    supervision = OperationsManager(
        advisors=[FakeAdvisor(DATA_A, "haber 1"), FakeAdvisor(DATA_B, "şikayet 1")]
    ).run()

    assert supervision.skipped_advisors == {}
    assert len(calls) == 2


# --- what the ledger itself promises ----------------------------------------


def test_source_hash_ignores_cosmetic_changes():
    assert memory.source_hash("Aynı  veri\n") == memory.source_hash("aynı veri")
    assert memory.source_hash("bir") != memory.source_hash("iki")
    assert memory.source_hash("") == ""


def test_an_unseen_source_always_counts_as_changed(tmp_path):
    ledger = memory.FindingsMemory(path=str(tmp_path / "f.json"))
    assert ledger.source_changed("market_feeds", "haber") is True
    assert ledger.source_changed("", "haber") is True  # unnamed owner: run it
    assert ledger.source_changed("market_feeds", "") is True  # nothing gathered


def test_source_hashes_survive_a_new_process(tmp_path):
    path = str(tmp_path / "f.json")
    first = memory.FindingsMemory(path=path)
    first.stage_source("market_feeds", "haber")
    assert first.commit() is True

    second = memory.FindingsMemory(path=path)
    assert second.source_changed("market_feeds", "haber") is False
    assert second.source_changed("market_feeds", "başka haber") is True


def test_briefings_explain_the_skip_in_turkish(run_env, calls, monkeypatch):
    monkeypatch.setenv("DIGEST_WEEKLY_RUN", "false")
    supervision = _run([FakeAdvisor(ALWAYS), FakeAdvisor(WEEKLY)])

    weekly = [b for b in supervision.briefings if b.key == WEEKLY][0]
    assert weekly.status == STATUS_SKIPPED
    assert "tetiklenmedi" in weekly.text
    assert [b.status for b in supervision.briefings if b.key == ALWAYS] == [STATUS_OK]


# --- the counters and the rosters are ONE number -----------------------------
#
# `advisors_ok: 7` under a list of eleven names is not a rounding error, it is
# two different questions answered by two different mechanisms. The counters
# now DERIVE from the rosters, so the dashboard cannot contradict itself.


class MuteAdvisor(FakeAdvisor):
    """Runs, and reports `skipped` — no credentials, nothing gathered.

    It stays out of the batch (like every non-LLM advisor) and takes its own
    path, which is where the real "yapılandırılmadı" skips come from.
    """

    def batch_section(self):
        return None

    def _generate(self):
        self.own_calls += 1
        return self.skipped("yapılandırılmadı")


def test_the_counters_are_derived_from_the_rosters(run_env, calls, monkeypatch):
    monkeypatch.setenv("DIGEST_WEEKLY_RUN", "false")
    team = [FakeAdvisor(ALWAYS), FakeAdvisor(DATA_A), FakeAdvisor(WEEKLY)]

    supervision = _run(team)
    record = metrics.build_run_metrics(supervision)

    assert record["advisors_ok"] == len(record["executed_advisors"])
    assert record["advisors_skipped"] == len(record["skipped_advisors"])
    # Nobody falls between the two rosters.
    executed = set(record["executed_advisors"])
    assert executed | set(record["skipped_advisors"]) == {a.key for a in team}
    assert not executed & set(record["skipped_advisors"])


def test_an_advisor_that_reports_nothing_is_not_an_executed_one(run_env, calls):
    """The exact 7-vs-11 bug: it ran, it produced no section, it is a skip."""
    mute = MuteAdvisor(DATA_A)

    supervision = _run([FakeAdvisor(ALWAYS), mute])
    record = metrics.build_run_metrics(supervision)

    assert record["executed_advisors"] == [ALWAYS]
    assert record["skipped_advisors"] == {DATA_A: SKIP_NO_OUTPUT}
    assert record["advisors_ok"] == 1
    assert record["advisors_skipped"] == 1


# --- WHICH gate closed ------------------------------------------------------


def test_each_gate_names_itself_in_the_skip_reason(run_env, calls, monkeypatch):
    monkeypatch.setenv("DIGEST_WEEKLY_RUN", "false")
    _run([FakeAdvisor(DATA_A, "haber 1")])
    memory.commit()  # the digest went out: DATA_A's source hash is now known

    supervision = _run(
        [
            FakeAdvisor(ALWAYS),
            FakeAdvisor(DATA_A, "haber 1"),  # unchanged source
            FakeAdvisor(WEEKLY),  # not the weekly slot
            FakeAdvisor(ON_REQUEST),  # nobody asked for it
        ]
    )

    assert supervision.skipped_advisors == {
        DATA_A: SKIP_DATA_UNCHANGED,
        WEEKLY: "tetiklenmedi(weekly)",
        ON_REQUEST: "tetiklenmedi(user_requested)",
    }
    assert len(set(supervision.skipped_advisors.values())) == 3


def test_the_skip_note_spells_out_the_trigger_class():
    assert not_triggered_reason(TRIGGER_WEEKLY) == "tetiklenmedi(weekly)"
    assert not_triggered_reason("") == SKIP_NOT_TRIGGERED
    assert "weekly" in skip_note(not_triggered_reason(TRIGGER_WEEKLY))
    assert skip_note(SKIP_DATA_UNCHANGED).startswith("kaynak verisi")
