"""Tests for the Operations Manager supervisor and the daily digest.

These run offline with no credentials: every advisor should ``skip`` and the
supervisor must produce a well-formed summary without crashing. A simulated
failing advisor must be reported ``failed`` without breaking the run.
"""

from __future__ import annotations

import pytest

from ai_assistant import config
from ai_assistant.advisors import Advisor, Briefing
from ai_assistant.daily_digest import build_digest
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ai_assistant.operations_manager import OperationsManager

_ENV_VARS = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "WEATHER_CITY",
    "WEATHER_COUNTRY",
    "WEATHER_LATITUDE",
    "WEATHER_LONGITUDE",
    "JOB_KEYWORDS",
    "JOB_LOCATION",
    "USER_SECTOR",
    "AI_NEWS_RSS_URL",
    "SECTOR_NEWS_RSS_URL",
    "ANKA_WEBHOOK_URL",
    "ANKA_API_URL",
    "ANKA_API_KEY",
    "ANKA_HTTP_METHOD",
    "BANKING_NEWS_RSS_URL",
    "ACCOUNTABILITY_STATE_FILE",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_CREDENTIALS_FILE",
    "GOOGLE_TOKEN_FILE",
]


@pytest.fixture()
def no_config(monkeypatch):
    """Simulate a completely blank setup: no env vars AND no built-in defaults.

    ``config.DEFAULT_SETTINGS`` normally pre-fills non-secret settings (city,
    sector, job keywords, RSS feeds) so the whole team is active out of the
    box; clearing it here keeps these tests offline and lets them assert the
    "nothing configured at all" invariant.
    """
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})
    yield


class _CrashingAdvisor(Advisor):
    key = "boom"
    title = "Patlayan Danışman"

    def _generate(self) -> Briefing:
        raise RuntimeError("intentional boom")


def test_manager_runs_all_advisors_offline(no_config):
    supervision = OperationsManager().run()
    assert [b.key for b in supervision.briefings] == [
        "weather",
        "morning_operations",
        "communications_calendar",
        "career_development",
        "market_intelligence",
        "ai_innovation",
        "kids_development",
        "anka_bridge",
        "executive_coaching",
        "work_analyst",
    ]
    for b in supervision.briefings:
        assert b.status in {STATUS_OK, STATUS_FAILED, STATUS_SKIPPED}


def test_manager_all_skipped_offline(no_config):
    """With nothing configured every advisor skips — except the work analyst.

    It consolidates the others rather than calling out itself, so it returns a
    successful "no data yet" briefing even offline.
    """
    supervision = OperationsManager().run()
    counts = supervision.counts
    assert counts[STATUS_FAILED] == 0
    skipped = {b.key for b in supervision.briefings if b.status == STATUS_SKIPPED}
    assert skipped == {b.key for b in supervision.briefings} - {"work_analyst"}
    assert counts[STATUS_SKIPPED] == len(supervision.briefings) - 1
    assert counts[STATUS_OK] == 1
    total = counts[STATUS_OK] + counts[STATUS_FAILED] + counts[STATUS_SKIPPED]
    assert total == len(supervision.briefings)
    assert "skipped" in supervision.summary_line()


def test_failing_advisor_is_isolated(no_config):
    manager = OperationsManager(advisors=[_CrashingAdvisor()])
    supervision = manager.run()
    assert len(supervision.briefings) == 1
    assert supervision.briefings[0].status == STATUS_FAILED
    assert supervision.counts[STATUS_FAILED] == 1
    assert supervision.failures


def test_failure_does_not_break_other_advisors(no_config):
    from ai_assistant.advisors.weather import WeatherAdvisor

    manager = OperationsManager(advisors=[_CrashingAdvisor(), WeatherAdvisor()])
    supervision = manager.run()
    statuses = [b.status for b in supervision.briefings]
    assert STATUS_FAILED in statuses
    assert STATUS_SKIPPED in statuses  # weather still ran and skipped


def test_register_adds_advisor(no_config):
    manager = OperationsManager(advisors=[])
    manager.register(_CrashingAdvisor())
    assert len(manager.advisors) == 1


def test_build_digest_offline(no_config):
    digest = build_digest()
    assert digest.text
    assert "Günlük Brifing" in digest.text
    assert "Operasyon Yöneticisi" in digest.text
    assert digest.counts[STATUS_FAILED] == 0
