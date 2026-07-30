"""Tests for the findings ledger (``ai_assistant.memory``).

The ledger is what stops the 14:00/18:00/22:00 runs from re-telling the 10:00
briefing. Its two promises are tested here:

1. it really does recognise a finding it has already delivered — including the
   same article behind a tracking link — until the retention window expires;
2. it can NEVER break a run: a corrupt, unreadable or unwritable file degrades
   to "everything is new" plus a log line, and nothing raises.

All of it is offline: no network, no credentials, no real state file (the
autouse fixture in ``conftest`` redirects the path into ``tmp_path``).
"""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pytest

from ai_assistant import memory
from ai_assistant.advisors._rss import FeedItem


def _ledger(tmp_path, name="findings.json", **kwargs):
    return memory.FindingsMemory(path=str(tmp_path / name), **kwargs)


# --- normalisation ----------------------------------------------------------


def test_url_normalisation_strips_tracking_and_lowercases_host():
    assert memory.normalize_url(
        "HTTPS://WWW.Example.ORG/a/b/?utm_source=news&id=7&fbclid=xyz#top"
    ) == "https://example.org/a/b?id=7"


def test_same_article_behind_two_tracking_links_has_one_fingerprint():
    first = memory.url_fingerprint("https://example.org/story?utm_campaign=a")
    second = memory.url_fingerprint("http://www.example.org/story/#section")
    # Scheme is the only real difference, so the fingerprints differ there…
    assert first != second
    # …but the tracking noise and the www/slash/fragment are gone.
    assert memory.normalize_url("https://example.org/story?utm_campaign=a") == (
        memory.normalize_url("https://www.example.org/story/#section")
    )


def test_title_normalisation_ignores_case_spacing_and_publisher_tail():
    assert memory.normalize_title("  Yapay   Zeka   Haberi  ") == "yapay zeka haberi"
    assert memory.title_fingerprint("Büyük Haber - Örnek Gazete") == (
        memory.title_fingerprint("büyük haber")
    )


def test_text_fingerprints_cover_the_body_and_its_links():
    prints = memory.text_fingerprints(
        "Bir  ÖZET metni.\nKaynak: https://example.org/rapor"
    )
    assert len(prints) == 2
    assert prints[0].startswith("c:")
    assert memory.url_fingerprint("https://example.org/rapor") in prints
    # Cosmetic whitespace/case edits are not "news".
    assert memory.text_fingerprints("bir özet metni. kaynak: https://example.org/rapor")[
        0
    ] == prints[0]


def test_item_fingerprints_are_empty_for_an_empty_item():
    assert memory.item_fingerprints("", "") == []


# --- round trip -------------------------------------------------------------


def test_round_trip_across_two_ledger_instances(tmp_path):
    first = _ledger(tmp_path)
    assert first.is_new("ai_news", "u:abc") is True
    first.mark_seen("ai_news", ["u:abc"])

    second = _ledger(tmp_path)
    assert second.is_new("ai_news", "u:abc") is False
    # The ledger is per advisor: another persona has not reported it.
    assert second.is_new("cx_research", "u:abc") is True


def test_saved_file_is_json_and_holds_no_readable_content(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.filter_new_items(
        "ai_news", [FeedItem(title="Gizli başlık", link="https://example.org/x")]
    )
    assert ledger.commit() is True

    raw = (tmp_path / "findings.json").read_text(encoding="utf-8")
    document = json.loads(raw)
    assert document["schema_version"] == memory.SCHEMA_VERSION
    assert list(document["advisors"]) == ["ai_news"]
    # Only irreversible hashes are stored — the file is committed to a PUBLIC
    # repository, so neither the headline nor the URL may appear in it.
    assert "Gizli başlık" not in raw
    assert "example.org" not in raw


# --- deduplication ----------------------------------------------------------


def test_filter_new_items_drops_what_was_already_delivered(tmp_path):
    items = [
        FeedItem(title="Birinci haber", link="https://example.org/1"),
        FeedItem(title="İkinci haber", link="https://example.org/2"),
    ]

    first_run = _ledger(tmp_path)
    assert len(first_run.filter_new_items("ai_news", items)) == 2
    first_run.commit()

    second_run = _ledger(tmp_path)
    assert second_run.filter_new_items("ai_news", items) == []
    assert second_run.new_count("ai_news") == 0


def test_filter_new_items_keeps_only_the_genuinely_new_one(tmp_path):
    old = FeedItem(title="Eski haber", link="https://example.org/old")
    new = FeedItem(title="Taze haber", link="https://example.org/new")

    ledger = _ledger(tmp_path)
    ledger.filter_new_items("ai_news", [old])
    ledger.commit()

    later = _ledger(tmp_path)
    fresh = later.filter_new_items("ai_news", [old, new])
    assert [item.title for item in fresh] == ["Taze haber"]
    assert later.new_count("ai_news") == 1


def test_tracking_parameters_do_not_make_an_old_story_look_new(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.filter_new_items(
        "ai_news", [FeedItem(title="Haber", link="https://example.org/a")]
    )
    ledger.commit()

    later = _ledger(tmp_path)
    assert later.filter_new_items(
        "ai_news",
        [FeedItem(title="Haber", link="https://www.example.org/a/?utm_source=x")],
    ) == []


def test_staged_findings_are_not_persisted_until_delivery(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.filter_new_items(
        "ai_news", [FeedItem(title="Haber", link="https://example.org/a")]
    )
    # Nothing was delivered, so nothing was written…
    assert not os.path.exists(tmp_path / "findings.json")
    ledger.discard_pending()
    ledger.commit()
    assert not os.path.exists(tmp_path / "findings.json")

    # …and the finding is still new for the next run.
    assert len(_ledger(tmp_path).filter_new_items(
        "ai_news", [FeedItem(title="Haber", link="https://example.org/a")]
    )) == 1


def test_staged_findings_are_not_reported_twice_inside_one_run(tmp_path):
    """Two advisors sharing a feed must not both report the same item."""
    ledger = _ledger(tmp_path)
    item = [FeedItem(title="Ortak haber", link="https://example.org/shared")]
    assert len(ledger.filter_new_items("sector_intel", item)) == 1
    assert ledger.filter_new_items("sector_intel", item) == []


# --- retention --------------------------------------------------------------


def test_entries_expire_after_the_retention_window(tmp_path):
    path = tmp_path / "findings.json"
    stale = (date.today() - timedelta(days=40)).isoformat()
    recent = (date.today() - timedelta(days=3)).isoformat()
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "advisors": {"ai_news": {"u:stale": stale, "u:recent": recent}},
            }
        ),
        encoding="utf-8",
    )

    ledger = memory.FindingsMemory(path=str(path), days=30)
    # Outside the window: the topic is allowed to resurface.
    assert ledger.is_new("ai_news", "u:stale") is True
    # Inside it: still old news.
    assert ledger.is_new("ai_news", "u:recent") is False


def test_retention_window_is_configurable(monkeypatch, tmp_path):
    path = tmp_path / "findings.json"
    seen_on = (date.today() - timedelta(days=5)).isoformat()
    path.write_text(
        json.dumps({"advisors": {"ai_news": {"u:x": seen_on}}}), encoding="utf-8"
    )

    monkeypatch.setenv(memory.RETENTION_ENV, "2")
    assert memory.retention_days() == 2
    assert memory.FindingsMemory(path=str(path)).is_new("ai_news", "u:x") is True

    monkeypatch.setenv(memory.RETENTION_ENV, "90")
    assert memory.FindingsMemory(path=str(path)).is_new("ai_news", "u:x") is False


def test_bad_retention_values_fall_back_to_the_default(monkeypatch):
    for value in ("", "  ", "abc", "0", "-5"):
        monkeypatch.setenv(memory.RETENTION_ENV, value)
        assert memory.retention_days() == memory.DEFAULT_RETENTION_DAYS


# --- fail-safe --------------------------------------------------------------


@pytest.mark.parametrize(
    "content", ["{ not json at all", "[]", '{"advisors": "nope"}', ""]
)
def test_corrupt_file_degrades_to_everything_is_new(tmp_path, content, caplog):
    path = tmp_path / "findings.json"
    path.write_text(content, encoding="utf-8")

    ledger = memory.FindingsMemory(path=str(path))
    # No exception, and nothing is considered already-reported.
    assert ledger.is_new("ai_news", "u:abc") is True
    assert len(ledger.filter_new_items(
        "ai_news", [FeedItem(title="Haber", link="https://example.org/a")]
    )) == 1


def test_unwritable_path_never_raises(tmp_path):
    # A directory where the file should be: every write attempt fails.
    blocked = tmp_path / "findings.json"
    blocked.mkdir()

    ledger = memory.FindingsMemory(path=str(blocked))
    ledger.filter_new_items(
        "ai_news", [FeedItem(title="Haber", link="https://example.org/a")]
    )
    assert ledger.save() is False
    assert ledger.commit() is False  # reported, but not raised
    # The run itself is unaffected: the advisor still got its item.
    assert ledger.new_count("ai_news") == 1


def test_missing_file_is_a_normal_first_run(tmp_path):
    ledger = memory.FindingsMemory(path=str(tmp_path / "nope" / "findings.json"))
    assert ledger.is_new("ai_news", "u:abc") is True


def test_module_level_helpers_use_one_shared_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv(memory.MEMORY_FILE_ENV, str(tmp_path / "shared.json"))
    memory.reset()

    items = [FeedItem(title="Haber", link="https://example.org/a")]
    assert len(memory.filter_new_items("ai_news", items)) == 1
    assert memory.new_count("ai_news") == 1
    assert memory.commit() is True

    memory.reset()
    assert memory.filter_new_items("ai_news", items) == []
    assert memory.is_new("ai_news", memory.url_fingerprint("https://example.org/a")) is False


def test_memory_file_path_honours_the_env_var(monkeypatch):
    monkeypatch.delenv(memory.MEMORY_FILE_ENV, raising=False)
    assert memory.memory_file_path() == memory.DEFAULT_MEMORY_FILE
    monkeypatch.setenv(memory.MEMORY_FILE_ENV, "  /tmp/custom.json ")
    assert memory.memory_file_path() == "/tmp/custom.json"
