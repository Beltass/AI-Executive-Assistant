"""Tests for the daily advisor agents.

All tests run with NO credentials and NO network: every advisor must report
``skipped`` and never crash.
"""

from __future__ import annotations

import pytest

from ai_assistant.advisors import Briefing, all_advisors
from ai_assistant.advisors.career_hr import CareerHrAdvisor
from ai_assistant.advisors.kids_development import KidsDevelopmentAdvisor
from ai_assistant.advisors.leadership_coach import LeadershipCoachAdvisor
from ai_assistant.advisors.weather import WeatherAdvisor
from ai_assistant.integrations import STATUS_OK, STATUS_SKIPPED

_ENV_VARS = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "WEATHER_CITY",
    "WEATHER_COUNTRY",
    "WEATHER_LATITUDE",
    "WEATHER_LONGITUDE",
]


@pytest.fixture()
def no_config(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


def test_all_advisors_discovered():
    advisors = all_advisors()
    assert len(advisors) == 4
    keys = {a.key for a in advisors}
    assert keys == {"weather", "leadership_coach", "kids_development", "career_hr"}


def test_weather_skipped_without_city(no_config):
    briefing = WeatherAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text


@pytest.mark.parametrize(
    "advisor_cls",
    [LeadershipCoachAdvisor, KidsDevelopmentAdvisor, CareerHrAdvisor],
)
def test_llm_personas_skipped_without_key(no_config, advisor_cls):
    briefing = advisor_cls().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text


def test_all_advisors_skipped_offline(no_config):
    for advisor in all_advisors():
        briefing = advisor.generate_briefing()
        assert isinstance(briefing, Briefing)
        assert briefing.status == STATUS_SKIPPED, f"{briefing.key}: {briefing.text}"
        assert briefing.key and briefing.title


def test_llm_personas_have_turkish_system_prompt():
    for advisor_cls in (LeadershipCoachAdvisor, KidsDevelopmentAdvisor, CareerHrAdvisor):
        assert advisor_cls.system_prompt.strip()
        assert advisor_cls.user_prompt.strip()
