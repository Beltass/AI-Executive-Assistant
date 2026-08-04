"""Tests for the Müşteri Şikâyet & İtibar Radarı advisor.

``ComplaintRadarAdvisor`` reads one or two complaint/reputation feeds, merges
them into ONE pool, drops what the user has already been told (the findings
ledger) and then asks the model to interpret what is left. It must:

* ship CONFIGURED out of the box — the built-in Google News defaults are what
  keep the section from being ``skipped`` on every real run;
* merge the two feeds and count a headline that appears in BOTH only once;
* stay quiet the second time the same headline comes round (memory dedup);
* still deliver the real headlines when there is no LLM key, and when the LLM
  call throws;
* degrade to ``skipped`` — never to a crash — when no feed is configured.

Everything here runs OFFLINE: the feed fetcher is stubbed in every test that
reaches it, so no test touches the network.
"""

from __future__ import annotations

import pytest

from ai_assistant import config
from ai_assistant.advisors import complaint_radar as radar_module
from ai_assistant.advisors._rss import FeedItem
from ai_assistant.advisors.complaint_radar import (
    CAVEAT,
    NO_FEED_HELP,
    ComplaintRadarAdvisor,
)
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED

FAKE_KEY = "AQ.FAKE-secret-key-should-never-leak-654321"

_ENV_VARS = [
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "COMPLAINT_RADAR_RSS_URL",
    "COMPLAINT_RADAR_SECTOR_RSS_URL",
    "COMPLAINT_RADAR_BRANDS",
    "COMPLAINT_RADAR_COMPETITORS",
]


@pytest.fixture()
def blank_env(monkeypatch):
    """No env vars AND no built-in defaults: nothing is configured at all."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(config, "DEFAULT_SETTINGS", {})
    yield


@pytest.fixture()
def defaults_only(monkeypatch):
    """The shipped state: no secrets set, built-in feed defaults in place."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


def _feed(monkeypatch, mapping):
    """Serve canned items per feed URL; anything else raises (dead feed)."""
    calls = []

    def fake_fetch(url, limit=8):
        calls.append(url)
        if url not in mapping:
            raise RuntimeError(f"feed unreachable: {url}")
        return list(mapping[url])

    monkeypatch.setattr(radar_module, "fetch_feed_items", fake_fetch)
    return calls


@pytest.fixture()
def two_feeds(monkeypatch, blank_env):
    """Two configured feeds that share one headline."""
    monkeypatch.setenv("COMPLAINT_RADAR_RSS_URL", "https://example.org/brand")
    monkeypatch.setenv("COMPLAINT_RADAR_SECTOR_RSS_URL", "https://example.org/sector")
    _feed(
        monkeypatch,
        {
            "https://example.org/brand": [
                FeedItem(title="IVR kuyruğu 20 dakika", link="https://example.org/a"),
                FeedItem(title="Komisyon iadesi gecikti", link="https://example.org/b"),
            ],
            "https://example.org/sector": [
                # The same story from the sector desk: merged, not counted twice.
                FeedItem(title="IVR kuyruğu 20 dakika", link="https://example.org/a"),
                FeedItem(title="Mobil şubede giriş hatası", link="https://example.org/c"),
            ],
        },
    )
    yield


# --- configuration ----------------------------------------------------------


def test_the_radar_is_registered_in_the_live_roster():
    from ai_assistant.advisors import all_advisors

    assert "complaint_radar" in [advisor.key for advisor in all_advisors()]


def test_not_configured_without_a_single_feed(blank_env):
    assert ComplaintRadarAdvisor._configured() is False


def test_configured_with_only_the_sector_feed(blank_env, monkeypatch):
    """EITHER feed is enough; the radar never needs both."""
    monkeypatch.setenv("COMPLAINT_RADAR_SECTOR_RSS_URL", "https://example.org/sector")
    assert ComplaintRadarAdvisor._configured() is True


def test_the_built_in_defaults_activate_the_radar(defaults_only):
    """The bug this default fixes: no secret meant `skipped` on EVERY real run."""
    assert ComplaintRadarAdvisor._configured() is True
    assert config.setting("COMPLAINT_RADAR_RSS_URL").startswith(
        "https://news.google.com/rss/search?q="
    )


def test_skipped_with_a_turkish_note_when_no_feed_is_configured(blank_env):
    briefing = ComplaintRadarAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert briefing.text == NO_FEED_HELP
    assert "COMPLAINT_RADAR_RSS_URL" in briefing.text


def test_no_feed_means_no_batch_section(blank_env, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    assert ComplaintRadarAdvisor().batch_section() is None


def test_no_llm_key_means_no_batch_section(two_feeds):
    assert ComplaintRadarAdvisor().batch_section() is None


# --- feed merging and dedup -------------------------------------------------


def test_both_feeds_are_merged_into_one_pool(two_feeds):
    items = ComplaintRadarAdvisor()._fetch_items()
    titles = [item.title for item in items]
    assert titles == [
        "IVR kuyruğu 20 dakika",
        "Komisyon iadesi gecikti",
        "Mobil şubede giriş hatası",
    ]


def test_a_headline_in_both_feeds_is_counted_once(two_feeds):
    advisor = ComplaintRadarAdvisor()
    items = advisor._fetch_items()
    assert [item.title for item in items].count("IVR kuyruğu 20 dakika") == 1
    # ...and the source grouping survives the merge.
    labels = [label for label, _group in advisor._groups]
    assert labels == ["Şikâyet & itibar akışı", "Sektör / finans kurumları akışı"]
    sector_group = dict(advisor._groups)["Sektör / finans kurumları akışı"]
    assert [item.title for item in sector_group] == ["Mobil şubede giriş hatası"]


def test_the_feeds_are_fetched_only_once_per_run(monkeypatch, blank_env):
    monkeypatch.setenv("COMPLAINT_RADAR_RSS_URL", "https://example.org/brand")
    calls = _feed(
        monkeypatch,
        {"https://example.org/brand": [FeedItem(title="Tek başlık", link="")]},
    )

    advisor = ComplaintRadarAdvisor()
    advisor._fetch_items()
    advisor._fetch_items()
    assert calls == ["https://example.org/brand"]


def test_a_dead_feed_never_takes_the_section_down(monkeypatch, blank_env):
    monkeypatch.setenv("COMPLAINT_RADAR_RSS_URL", "https://example.invalid/feed")
    monkeypatch.setenv("COMPLAINT_RADAR_SECTOR_RSS_URL", "https://example.org/sector")
    _feed(
        monkeypatch,
        {"https://example.org/sector": [FeedItem(title="Sektör başlığı", link="")]},
    )

    items = ComplaintRadarAdvisor()._fetch_items()
    assert [item.title for item in items] == ["Sektör başlığı"]


def test_a_headline_already_reported_is_not_reported_again(two_feeds):
    """The memory ledger: the second run of the day has nothing new to say."""
    first = ComplaintRadarAdvisor()._fetch_items()
    assert len(first) == 3

    second = ComplaintRadarAdvisor()._fetch_items()
    assert second == []


def test_new_finding_count_reports_the_fresh_items(two_feeds):
    advisor = ComplaintRadarAdvisor()
    assert advisor.new_finding_count() == 3
    # A second advisor in the same run sees the staged fingerprints.
    assert ComplaintRadarAdvisor().new_finding_count() == 0


def test_the_radar_declares_itself_an_incremental_source():
    assert ComplaintRadarAdvisor.incremental_source is True


# --- the non-LLM fallback ---------------------------------------------------


def test_without_an_llm_key_the_real_headlines_are_still_delivered(two_feeds):
    briefing = ComplaintRadarAdvisor().generate_briefing()
    assert briefing.status == STATUS_OK
    assert "Bugünün yeni şikâyet başlıkları" in briefing.text
    assert "IVR kuyruğu 20 dakika" in briefing.text
    assert "https://example.org/c" in briefing.text
    assert briefing.text.endswith(CAVEAT)


def test_without_an_llm_key_and_without_headlines_it_skips(monkeypatch, blank_env):
    monkeypatch.setenv("COMPLAINT_RADAR_RSS_URL", "https://example.org/brand")
    _feed(monkeypatch, {"https://example.org/brand": []})

    briefing = ComplaintRadarAdvisor().generate_briefing()
    assert briefing.status == STATUS_SKIPPED
    assert "GEMINI_API_KEY" in briefing.text


def test_a_failing_llm_falls_back_to_the_headline_list(monkeypatch, two_feeds):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)

    def boom(*_args, **_kwargs):
        raise RuntimeError("kota doldu")

    monkeypatch.setattr(radar_module.llm, "generate_text", boom)

    briefing = ComplaintRadarAdvisor().generate_briefing()
    assert briefing.status == STATUS_OK
    assert "Mobil şubede giriş hatası" in briefing.text
    assert briefing.text.endswith(CAVEAT)


def test_a_failing_llm_without_headlines_is_a_failure(monkeypatch, blank_env):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("COMPLAINT_RADAR_RSS_URL", "https://example.org/brand")
    _feed(monkeypatch, {"https://example.org/brand": []})
    monkeypatch.setattr(
        radar_module.llm,
        "generate_text",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("kota doldu")),
    )

    briefing = ComplaintRadarAdvisor().generate_briefing()
    assert briefing.status == STATUS_FAILED
    assert "kota doldu" in briefing.text


# --- the prompt -------------------------------------------------------------


def test_the_prompt_carries_the_real_headlines_and_their_source(monkeypatch, two_feeds):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)

    section = ComplaintRadarAdvisor().batch_section()
    assert section is not None
    assert section.key == "complaint_radar"
    assert "[Şikâyet & itibar akışı]" in section.user_prompt
    assert "https://example.org/b" in section.user_prompt


def test_brands_and_competitors_reach_the_prompt(monkeypatch, two_feeds):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("COMPLAINT_RADAR_BRANDS", "Örnek Bank, Örnek Yatırım")
    monkeypatch.setenv("COMPLAINT_RADAR_COMPETITORS", "Rakip Bank")

    section = ComplaintRadarAdvisor().batch_section()
    assert "Örnek Bank, Örnek Yatırım" in section.user_prompt
    assert "Rakip Bank" in section.user_prompt


def test_without_competitors_the_model_is_told_not_to_invent_any(monkeypatch, two_feeds):
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)

    section = ComplaintRadarAdvisor().batch_section()
    assert "COMPLAINT_RADAR_COMPETITORS" in section.user_prompt
    assert "kurum adı" in section.user_prompt


def test_the_batched_answer_always_carries_the_caveat(two_feeds):
    briefing = ComplaintRadarAdvisor().briefing_from_batch("  Model yanıtı  ")
    assert briefing.status == STATUS_OK
    assert briefing.text.startswith("Model yanıtı")
    assert briefing.text.endswith(CAVEAT)
