"""The advisor manifest is the single source of truth — these tests enforce it.

``status_report.ADVISOR_META`` describes every advisor module on disk: whether
it is live or retired, when it runs, what it costs and where it is delivered.
Three things used to be maintained in parallel — the import list in
``advisors.all_advisors()``, this table, and the Slack channel tuple — and they
drifted: ``meeting_prep`` had metadata, a Slack route, a dashboard entry and a
module, but nobody imported it, so it had never produced a briefing.

So the rules asserted here are:

* every module under ``advisors/`` is in the manifest, live or retired;
* every manifest record is complete and internally valid;
* every declared class really exists and really is that advisor.

The manifest-vs-roster equality itself lives in ``test_advisors.py``, next to
the roster it guards.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

from ai_assistant import advisors as advisors_pkg
from ai_assistant import status_report
from ai_assistant.advisors import Advisor


def _modules_on_disk() -> set:
    """Every PUBLIC advisor module name (``_batch``, ``_rss``… excluded)."""
    return {
        info.name
        for info in pkgutil.iter_modules(advisors_pkg.__path__)
        if not info.name.startswith("_")
    }


ALL_KEYS = sorted(status_report.ADVISOR_META)
LIVE_KEYS = list(status_report.live_advisor_keys())


# --- coverage ---------------------------------------------------------------


def test_every_advisor_module_on_disk_is_in_the_manifest():
    """A module nobody catalogued is a module nobody can decide about."""
    missing = _modules_on_disk() - set(status_report.ADVISOR_META)
    assert not missing, f"manifeste eklenmemiş modüller: {sorted(missing)}"


def test_the_manifest_invents_no_advisors():
    """…and the reverse: every catalogued key has a module behind it."""
    phantom = set(status_report.ADVISOR_META) - _modules_on_disk()
    assert not phantom, f"modülü olmayan manifest kayıtları: {sorted(phantom)}"


def test_every_advisor_is_either_live_or_retired():
    assert set(status_report.live_advisor_keys()) | set(
        status_report.retired_advisor_keys()
    ) == set(status_report.ADVISOR_META)
    assert not set(status_report.live_advisor_keys()) & set(
        status_report.retired_advisor_keys()
    )


# --- record shape -----------------------------------------------------------


@pytest.mark.parametrize("key", ALL_KEYS)
def test_every_record_has_every_field(key):
    record = status_report.ADVISOR_META[key]
    assert set(record) == set(status_report.DEFAULT_META), key


@pytest.mark.parametrize("key", ALL_KEYS)
def test_every_record_is_internally_valid(key):
    record = status_report.ADVISOR_META[key]
    assert record["title"], key
    assert record["emoji"], key
    assert record["category"] in {
        status_report.CATEGORY_CAREER,
        status_report.CATEGORY_FAMILY,
        status_report.CATEGORY_SECTOR,
        status_report.CATEGORY_GROWTH,
        status_report.CATEGORY_OPS,
    }, key
    assert record["status"] in {
        status_report.ADVISOR_LIVE,
        status_report.ADVISOR_RETIRED,
    }, key
    assert record["trigger"] in status_report.TRIGGERS, key
    assert isinstance(record["token_ceiling"], int) and record["token_ceiling"] >= 0
    assert record["module"] == key, key
    assert record["advisor_class"], key


def test_live_advisors_hold_a_dashboard_position_and_a_slack_route():
    orders = [status_report.ADVISOR_META[k]["dashboard_order"] for k in LIVE_KEYS]
    assert orders == list(range(1, len(LIVE_KEYS) + 1))
    for key in LIVE_KEYS:
        assert status_report.ADVISOR_META[key]["slack_target"], key


def test_retired_advisors_hold_no_position_and_no_route():
    for key in status_report.retired_advisor_keys():
        record = status_report.ADVISOR_META[key]
        assert record["dashboard_order"] == 0, key
        assert record["slack_target"] == "", key
        assert record["token_ceiling"] == 0, key
        assert record["trigger"] == status_report.TRIGGER_USER_REQUESTED, key


# --- the classes really exist -----------------------------------------------


@pytest.mark.parametrize("key", LIVE_KEYS)
def test_every_live_record_can_be_imported_and_instantiated(key):
    """A live record that cannot be built would break the whole run."""
    record = status_report.ADVISOR_META[key]
    module = importlib.import_module(f"ai_assistant.advisors.{record['module']}")
    cls = getattr(module, record["advisor_class"])

    assert issubclass(cls, Advisor), key
    assert cls.key == key, f"{key}: sınıf anahtarı {cls.key}"


@pytest.mark.parametrize("key", sorted(status_report.retired_advisor_keys()))
def test_every_retired_record_still_points_at_a_real_class(key):
    """Retired means "not running", not "not there": rollback must stay cheap."""
    record = status_report.ADVISOR_META[key]
    module = importlib.import_module(f"ai_assistant.advisors.{record['module']}")
    cls = getattr(module, record["advisor_class"])

    assert issubclass(cls, Advisor), key
    assert cls.key == key, f"{key}: sınıf anahtarı {cls.key}"


# --- the trigger plan -------------------------------------------------------
#
# Written out in full on purpose: which advisor runs how often is a COST
# decision, so moving one between groups should have to be an explicit edit.


def test_the_trigger_plan_is_the_one_that_was_agreed():
    assert status_report.advisors_with_trigger(status_report.TRIGGER_ALWAYS) == (
        "morning_operations",
        "communications_calendar",
        "work_analyst",
        "operations_director",
        "sre_watchdog",
    )
    assert status_report.advisors_with_trigger(status_report.TRIGGER_DATA) == (
        "meeting_prep",
        "drive_insight",
        "career_development",
        "market_intelligence",
        "complaint_radar",
        "linkedin_coach",
        "data_analyst",
        "risk_sentinel",
    )
    assert status_report.advisors_with_trigger(status_report.TRIGGER_WEEKLY) == (
        "social_media_coach",
        "personal_assistant",
        "ai_innovation",
        "executive_coaching",
        "productivity_coach",
        "decision_intelligence",
    )
    assert status_report.advisors_with_trigger(
        status_report.TRIGGER_USER_REQUESTED
    ) == ("kids_development",)


def test_data_triggered_advisors_all_own_a_source():
    """The trigger is meaningless without something to hash."""
    for key in status_report.advisors_with_trigger(status_report.TRIGGER_DATA):
        assert status_report.advisor_data_owner(key), key


# --- accessors --------------------------------------------------------------


def test_unknown_keys_fall_back_instead_of_raising():
    assert status_report.advisor_meta("uydurma") is status_report.DEFAULT_META
    assert status_report.is_live("uydurma") is False
    assert status_report.advisor_trigger("uydurma") == (
        status_report.TRIGGER_USER_REQUESTED
    )
    assert status_report.advisor_data_owner("uydurma") == ""
    assert status_report.advisor_token_ceiling("uydurma") == 0


def test_live_keys_come_back_in_dashboard_order():
    keys = status_report.live_advisor_keys()
    assert keys[0] == "morning_operations"
    assert keys[-1] == "sre_watchdog"
    assert len(set(keys)) == len(keys)
