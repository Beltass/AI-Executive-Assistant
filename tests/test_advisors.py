"""Tests for the daily advisor agents.

All tests run with NO credentials and NO network: every advisor must report
``skipped`` and never crash.
"""

from __future__ import annotations

import pytest

from ai_assistant import config
from ai_assistant.advisors import Briefing, all_advisors
from ai_assistant.advisors.career_hr import CareerHrAdvisor
from ai_assistant.advisors.kids_development import KidsDevelopmentAdvisor
from ai_assistant.advisors.leadership_coach import LeadershipCoachAdvisor
from ai_assistant.advisors.weather import WeatherAdvisor
from ai_assistant.advisors.job_scout import JobScoutAdvisor
from ai_assistant.advisors.sector_intel import SectorIntelAdvisor
from ai_assistant.advisors.ai_news import AiNewsAdvisor
from ai_assistant.advisors.free_certs import FreeCertsAdvisor
from ai_assistant.advisors.banking_cc_projects import BankingCcProjectsAdvisor
from ai_assistant.advisors.daily_ops_briefing import DailyOpsBriefingAdvisor
from ai_assistant.advisors.language_coach import LanguageCoachAdvisor
from ai_assistant.advisors.anka_bridge import AnkaBridgeAdvisor
from ai_assistant.integrations import STATUS_OK, STATUS_SKIPPED

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


def test_all_advisors_discovered():
    advisors = all_advisors()
    assert len(advisors) == 15
    keys = {a.key for a in advisors}
    assert keys == {
        "weather",
        "leadership_coach",
        "kids_development",
        "career_hr",
        "job_scout",
        "sector_intel",
        "ai_news",
        "free_certs",
        "banking_cc_projects",
        "ai_mastery",
        "cx_research",
        "daily_ops_briefing",
        "language_coach",
        "anka_bridge",
        "accountability_coach",
    }


def test_accountability_coach_runs_last():
    """It consolidates the OTHER advisors' tasks, so it must see them first."""
    assert all_advisors()[-1].key == "accountability_coach"


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


def test_job_scout_skipped_without_keywords(no_config):
    briefing = JobScoutAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "JOB_KEYWORDS" in briefing.text


def test_job_scout_skipped_without_llm_key(no_config, monkeypatch):
    monkeypatch.setenv("JOB_KEYWORDS", "veri analisti")
    briefing = JobScoutAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text


@pytest.mark.parametrize(
    "advisor_cls",
    [SectorIntelAdvisor, FreeCertsAdvisor, BankingCcProjectsAdvisor,
     LanguageCoachAdvisor],
)
def test_llm_new_personas_skipped_without_key(no_config, advisor_cls):
    briefing = advisor_cls().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text


def test_ai_news_skipped_without_feed_or_key(no_config):
    briefing = AiNewsAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text


def test_anka_bridge_skipped_without_url(no_config):
    briefing = AnkaBridgeAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "not configured" in briefing.text


# --- Built-in defaults: the whole team is active out of the box -------------
# ``config.DEFAULT_SETTINGS`` pre-fills the NON-SECRET settings, so weather,
# job scout, sector intel and the news feeds all produce content without any
# manual configuration — while a missing LLM key still means ``skipped``.


@pytest.fixture()
def defaults_only(monkeypatch):
    """Clear the env vars but KEEP the built-in defaults (the shipped state)."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


def test_defaults_activate_the_whole_team(defaults_only):
    assert config.setting("WEATHER_CITY") == "Istanbul"
    assert config.setting("USER_SECTOR") == "banka çağrı merkezleri"
    assert "çağrı merkezi müdürü" in config.setting("JOB_KEYWORDS")
    assert config.setting("JOB_LOCATION") == "İstanbul"
    assert config.setting("AI_NEWS_RSS_URL").startswith(
        "https://news.google.com/rss/search?q=yapay+zeka"
    )
    assert config.setting("SECTOR_NEWS_RSS_URL").startswith(
        "https://news.google.com/rss/search?q="
    )
    assert config.setting("BANKING_NEWS_RSS_URL").startswith(
        "https://news.google.com/rss/search?q="
    )
    assert config.setting("ACCOUNTABILITY_STATE_FILE").endswith(".json")


def test_env_var_overrides_the_default(monkeypatch, defaults_only):
    monkeypatch.setenv("WEATHER_CITY", "Ankara")
    assert config.setting("WEATHER_CITY") == "Ankara"


def test_blank_env_var_falls_back_to_the_default(monkeypatch, defaults_only):
    # GitHub Actions expands an unset secret to an empty string.
    monkeypatch.setenv("WEATHER_CITY", "   ")
    assert config.setting("WEATHER_CITY") == "Istanbul"


def test_anka_bridge_has_no_default_endpoint(defaults_only):
    """The Anka endpoint is user-specific and must never be invented."""
    assert "ANKA_WEBHOOK_URL" not in config.DEFAULT_SETTINGS
    assert "ANKA_API_URL" not in config.DEFAULT_SETTINGS
    briefing = AnkaBridgeAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED


def test_weather_runs_with_the_default_city(monkeypatch, defaults_only):
    from ai_assistant.advisors import weather as weather_module

    calls = []

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_get(url, headers=None):
        calls.append(url)
        if "geocoding" in url:
            return _FakeResponse(
                {
                    "results": [
                        {
                            "latitude": 41.0,
                            "longitude": 29.0,
                            "name": "İstanbul",
                            "country": "Türkiye",
                        }
                    ]
                }
            )
        return _FakeResponse(
            {
                "current": {"temperature_2m": 24.0, "weather_code": 0},
                "daily": {
                    "weather_code": [0],
                    "temperature_2m_max": [28.0],
                    "temperature_2m_min": [18.0],
                    "precipitation_sum": [0.0],
                    "precipitation_probability_max": [0],
                    "wind_speed_10m_max": [12.0],
                },
            }
        )

    monkeypatch.setattr(weather_module, "http_get", fake_get)

    briefing = WeatherAdvisor().generate_briefing()

    assert briefing.status == STATUS_OK
    assert "İstanbul" in briefing.text
    assert "name=Istanbul" in calls[0]  # the default city was geocoded


def test_job_scout_uses_defaults_but_still_skips_without_llm_key(defaults_only):
    """Defaults pre-fill config only — a missing LLM key still means skipped."""
    briefing = JobScoutAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "GEMINI_API_KEY" in briefing.text


@pytest.mark.parametrize(
    "advisor_cls",
    [LeadershipCoachAdvisor, KidsDevelopmentAdvisor, CareerHrAdvisor,
     SectorIntelAdvisor, FreeCertsAdvisor, BankingCcProjectsAdvisor,
     LanguageCoachAdvisor],
)
def test_llm_advisors_still_skip_with_defaults_but_no_key(defaults_only, advisor_cls):
    briefing = advisor_cls().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "GEMINI_API_KEY" in briefing.text


def test_ai_news_default_feed_failure_degrades_to_skipped(monkeypatch, defaults_only):
    """A dead default feed must not turn into a `failed` (which would exit 1)."""
    from ai_assistant.advisors import ai_news as ai_news_module

    def boom(url, limit=8):
        raise RuntimeError("feed unreachable")

    monkeypatch.setattr(ai_news_module, "fetch_feed_items", boom)

    briefing = AiNewsAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED


def test_ai_news_uses_real_feed_links_without_an_llm_key(monkeypatch, defaults_only):
    from ai_assistant.advisors import ai_news as ai_news_module
    from ai_assistant.advisors._rss import FeedItem

    monkeypatch.setattr(
        ai_news_module,
        "fetch_feed_items",
        lambda url, limit=8: [FeedItem(title="Başlık", link="https://example.org/a")],
    )

    briefing = AiNewsAdvisor().generate_briefing()
    assert briefing.status == STATUS_OK
    assert "https://example.org/a" in briefing.text


def test_sector_feed_failure_does_not_break_the_prompt(monkeypatch, defaults_only):
    from ai_assistant.advisors import sector_intel as sector_module

    def boom(url, limit=6):
        raise RuntimeError("feed unreachable")

    monkeypatch.setattr(sector_module, "fetch_feed_items", boom)
    assert SectorIntelAdvisor()._recent_headlines() == []
