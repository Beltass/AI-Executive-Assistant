"""Tests for the per-advisor Slack fan-out.

The workspace layout under test: ONE main channel with the summary, ONE
sub-channel per advisor with that advisor's own section. These tests pin the
routing — WHICH message goes to WHICH channel — and the two ways it used to go
wrong: a webhook silently ignoring the channel field, and a private section
being repeated in the main channel after it already had a room of its own.

No network: every test replaces the module's single HTTP seam.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ai_assistant.advisors import Briefing
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ai_assistant.integrations import channel_config, slack_channels
from ai_assistant.notifiers import slack_notifier
from ai_assistant.operations_manager import Supervision
from ai_assistant import reports
from ai_assistant.status_report import ISTANBUL

NOW = datetime(2026, 7, 31, 8, 30, tzinfo=ISTANBUL)

_SLACK_ENV = [
    "SLACK_WEBHOOK_URL",
    "SLACK_BOT_TOKEN",
    "SLACK_CHANNEL",
    "SLACK_MAIN_CHANNEL",
] + [channel_config.advisor_channel_env(k) for k in channel_config.ADVISOR_KEYS]


@pytest.fixture(autouse=True)
def _clean_slack_env(monkeypatch):
    """No Slack configuration leaks in, and the config singleton is fresh."""
    for var in _SLACK_ENV:
        monkeypatch.delenv(var, raising=False)
    channel_config.reset_channel_config()
    yield
    channel_config.reset_channel_config()


class FakeSlack:
    """Records every chat.postMessage instead of sending it."""

    def __init__(self, ok=True, error="channel_not_found"):
        self.calls = []
        self.ok = ok
        self.error = error

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        return FakeResponse(self._body(url, json or {}))

    def _body(self, url, payload):
        if url.endswith("chat.getPermalink"):
            return {
                "ok": True,
                "permalink": f"https://acme.slack.com/archives/"
                f"{payload.get('channel')}/p{str(payload.get('message_ts', '')).replace('.', '')}",
            }
        if self.ok:
            return {"ok": True, "ts": "1722400000.000100", "channel": payload.get("channel")}
        return {"ok": False, "error": self.error}

    @property
    def posts(self):
        """Only the chat.postMessage calls, as ``(channel, payload)``."""
        return [
            (c["json"].get("channel"), c["json"])
            for c in self.calls
            if c["url"].endswith("chat.postMessage")
        ]

    @property
    def channels(self):
        return [channel for channel, _ in self.posts]


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.text = str(payload)

    def json(self):
        return self._payload


def _briefing(key, title, text="**Öne çıkan:** Bugünün tek cümlesi.\n\nGövde.", **kw):
    return Briefing(key=key, title=title, status=STATUS_OK, text=text, **kw)


def _supervision(*briefings):
    return Supervision(briefings=list(briefings))


def _publish(supervision, tmp_path):
    return reports.publish(supervision, root=str(tmp_path / "reports"), now=NOW)


# --- the roster -------------------------------------------------------------


def test_channel_config_roster_matches_the_live_advisor_team():
    """A new advisor with no entry here would silently lose its own channel."""
    from ai_assistant.advisors import all_advisors

    assert tuple(a.key for a in all_advisors()) == channel_config.ADVISOR_KEYS


def test_env_var_names_follow_the_documented_pattern():
    assert channel_config.advisor_channel_env("meeting_prep") == "SLACK_CHANNEL_MEETING_PREP"
    assert (
        channel_config.advisor_channel_env("market_intelligence")
        == "SLACK_CHANNEL_MARKET_INTELLIGENCE"
    )


# --- routing ----------------------------------------------------------------


def test_each_advisor_lands_in_its_own_channel(monkeypatch, tmp_path):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    monkeypatch.setenv("SLACK_CHANNEL_MORNING_OPERATIONS", "CMORNING")
    monkeypatch.setenv("SLACK_CHANNEL_KIDS_DEVELOPMENT", "CKIDS")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_channels, "http_post", fake)

    supervision = _supervision(
        _briefing("morning_operations", "Sabah İşletme Brifingi"),
        _briefing("kids_development", "Çocuk Gelişimi Danışmanı"),
    )
    publication = _publish(supervision, tmp_path)

    dist = slack_channels.distribute(supervision, publication, base_url="https://pano/")

    assert dist.delivered == 2
    assert sorted(fake.channels) == ["CKIDS", "CMORNING"]
    # ...and the message carries the deep link to that advisor's document.
    by_channel = dict(fake.posts)
    blob = str(by_channel["CMORNING"]["blocks"])
    assert "https://pano/#/rapor/2026-07-31/morning_operations" in blob


def test_unconfigured_advisor_falls_back_to_the_main_channel(monkeypatch, tmp_path):
    """The documented fallback survives: no own channel -> main channel."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    monkeypatch.setenv("SLACK_CHANNEL_MORNING_OPERATIONS", "CMORNING")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_channels, "http_post", fake)

    supervision = _supervision(
        _briefing("morning_operations", "Sabah İşletme Brifingi"),
        _briefing("career_development", "Kariyer Gelişimi"),
    )
    dist = slack_channels.distribute(
        supervision, _publish(supervision, tmp_path), base_url="https://pano/"
    )

    assert sorted(fake.channels) == ["CMAIN", "CMORNING"]
    # Only the advisor with a room of its own counts as "delivered elsewhere",
    # so the summary keeps treating the fallback one as a plain index line.
    assert dist.delivered_keys == {"morning_operations"}


def test_fanout_stays_off_when_no_advisor_has_its_own_channel(monkeypatch, tmp_path):
    """Otherwise every advisor would repeat the summary in the one main room."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_channels, "http_post", fake)

    supervision = _supervision(_briefing("morning_operations", "Sabah İşletme Brifingi"))
    dist = slack_channels.distribute(supervision, _publish(supervision, tmp_path))

    assert fake.calls == []
    assert dist.posts == []
    assert "özel kanal" in dist.skipped_reason


def test_webhook_alone_cannot_fan_out_and_says_so(monkeypatch, tmp_path):
    """The old bug: a webhook ignores `channel` and dumps everything in one room."""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/X/Y/Z")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    monkeypatch.setenv("SLACK_CHANNEL_MORNING_OPERATIONS", "CMORNING")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_channels, "http_post", fake)

    supervision = _supervision(_briefing("morning_operations", "Sabah İşletme Brifingi"))
    dist = slack_channels.distribute(supervision, _publish(supervision, tmp_path))

    assert fake.calls == [], "no webhook call may pretend to be per-channel routing"
    assert dist.delivered == 0
    assert "SLACK_BOT_TOKEN" in dist.skipped_reason


def test_private_advisor_gets_its_body_in_its_own_channel(monkeypatch, tmp_path):
    """A private section has no public document, so the channel carries it whole."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    monkeypatch.setenv("SLACK_CHANNEL_COMMUNICATIONS_CALENDAR", "CMAIL")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_channels, "http_post", fake)

    secret = "Ahmet Yılmaz ile 14:00 toplantı"
    supervision = _supervision(
        Briefing(
            key="communications_calendar",
            title="İletişim & Takvim Danışmanı",
            status=STATUS_OK,
            text=f"**Öne çıkan:** Yoğun bir gün.\n\n{secret}",
            private=True,
        )
    )
    publication = _publish(supervision, tmp_path)
    assert publication.reports == [], "private sections are never published"

    dist = slack_channels.distribute(supervision, publication)

    assert fake.channels == ["CMAIL"]
    assert secret in str(dict(fake.posts)["CMAIL"]["blocks"])
    assert dist.delivered_keys == {"communications_calendar"}


def test_quiet_and_failed_advisors_are_not_posted(monkeypatch, tmp_path):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL_MORNING_OPERATIONS", "CMORNING")
    monkeypatch.setenv("SLACK_CHANNEL_CAREER_DEVELOPMENT", "CCAREER")
    monkeypatch.setenv("SLACK_CHANNEL_KIDS_DEVELOPMENT", "CKIDS")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_channels, "http_post", fake)

    supervision = _supervision(
        _briefing("morning_operations", "Sabah İşletme Brifingi"),
        Briefing(key="career_development", title="Kariyer", status=STATUS_FAILED, text="patladı"),
        Briefing(
            key="kids_development",
            title="Çocuk",
            status=STATUS_OK,
            text="yeni bulgu yok",
            nothing_new=True,
        ),
    )
    slack_channels.distribute(supervision, _publish(supervision, tmp_path))

    assert fake.channels == ["CMORNING"]


def test_one_failing_channel_does_not_stop_the_others(monkeypatch, tmp_path):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL_MORNING_OPERATIONS", "CMORNING")
    monkeypatch.setenv("SLACK_CHANNEL_CAREER_DEVELOPMENT", "CCAREER")
    channel_config.reset_channel_config()

    calls = []

    def flaky(url, headers=None, json=None, timeout=None):
        calls.append(json or {})
        if (json or {}).get("channel") == "CMORNING":
            return FakeResponse({"ok": False, "error": "channel_not_found"})
        return FakeResponse({"ok": True, "ts": "1.2"})

    monkeypatch.setattr(slack_channels, "http_post", flaky)

    supervision = _supervision(
        _briefing("morning_operations", "Sabah İşletme Brifingi"),
        _briefing("career_development", "Kariyer Gelişimi"),
    )
    dist = slack_channels.distribute(supervision, _publish(supervision, tmp_path))

    assert dist.delivered == 1
    assert len(dist.failures) == 1
    assert "channel_not_found" in dist.failures[0].result.detail


def test_transport_error_is_caught_not_raised(monkeypatch, tmp_path):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL_MORNING_OPERATIONS", "CMORNING")
    channel_config.reset_channel_config()

    def boom(*args, **kwargs):
        raise RuntimeError("ağ yok")

    monkeypatch.setattr(slack_channels, "http_post", boom)

    supervision = _supervision(_briefing("morning_operations", "Sabah İşletme Brifingi"))
    dist = slack_channels.distribute(supervision, _publish(supervision, tmp_path))

    assert dist.delivered == 0
    assert dist.failures


# --- the main-channel summary ----------------------------------------------


def test_summary_links_to_the_report_and_to_the_advisor_channel(monkeypatch, tmp_path):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    monkeypatch.setenv("SLACK_CHANNEL_MORNING_OPERATIONS", "CMORNING")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_channels, "http_post", fake)

    supervision = _supervision(_briefing("morning_operations", "Sabah İşletme Brifingi"))
    publication = _publish(supervision, tmp_path)
    dist = slack_channels.distribute(supervision, publication, base_url="https://pano/")

    _, blocks = slack_notifier.build_index_message(
        supervision,
        publication,
        base_url="https://pano/",
        now=NOW,
        channel_links=dist.links,
        own_channel_keys=dist.delivered_keys,
    )
    blob = str(blocks)

    assert "https://pano/#/rapor/2026-07-31/morning_operations" in blob
    assert "💬 Kendi kanalı" in blob
    assert "CMORNING" in blob or "acme.slack.com" in blob


def test_summary_does_not_repeat_a_private_body_that_has_its_own_channel(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    monkeypatch.setenv("SLACK_CHANNEL_COMMUNICATIONS_CALENDAR", "CMAIL")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_channels, "http_post", fake)

    secret = "Ahmet Yılmaz ile 14:00 toplantı"
    supervision = _supervision(
        Briefing(
            key="communications_calendar",
            title="İletişim & Takvim Danışmanı",
            status=STATUS_OK,
            text=f"**Öne çıkan:** Yoğun bir gün.\n\n{secret}",
            private=True,
        )
    )
    publication = _publish(supervision, tmp_path)
    dist = slack_channels.distribute(supervision, publication)

    _, blocks = slack_notifier.build_index_message(
        supervision,
        publication,
        now=NOW,
        channel_links=dist.links,
        own_channel_keys=dist.delivered_keys,
    )
    blob = str(blocks)

    assert secret not in blob, "the body belongs in the advisor's channel, once"
    assert "Yoğun bir gün" in blob, "the headline still belongs in the summary"
    assert "Kendi kanalında tam bölüm" in blob


def test_summary_still_inlines_a_private_section_with_no_channel_of_its_own(tmp_path):
    """Without a room of its own the body has nowhere else to go — keep it inline."""
    secret = "Ahmet Yılmaz ile 14:00 toplantı"
    supervision = _supervision(
        Briefing(
            key="communications_calendar",
            title="İletişim & Takvim Danışmanı",
            status=STATUS_OK,
            text=f"**Öne çıkan:** Yoğun bir gün.\n\n{secret}",
            private=True,
        )
    )
    publication = _publish(supervision, tmp_path)

    _, blocks = slack_notifier.build_index_message(supervision, publication, now=NOW)

    assert secret in str(blocks)


def test_summary_goes_to_the_main_channel_not_the_legacy_one(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL", "CLEGACY")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_notifier, "http_post", fake)

    result = slack_notifier.send_message("merhaba", blocks=[])

    assert result.status == STATUS_OK
    assert fake.channels == ["CMAIN"]


def test_summary_falls_back_to_the_legacy_channel(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL", "CLEGACY")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_notifier, "http_post", fake)

    slack_notifier.send_message("merhaba", blocks=[])

    assert fake.channels == ["CLEGACY"]


# --- end to end -------------------------------------------------------------


def test_full_delivery_puts_sections_in_sub_channels_and_summary_in_main(
    monkeypatch, tmp_path
):
    """The whole point, in one test: 2 sub-channel posts + 1 main summary."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    monkeypatch.setenv("SLACK_CHANNEL_MORNING_OPERATIONS", "CMORNING")
    monkeypatch.setenv("SLACK_CHANNEL_CAREER_DEVELOPMENT", "CCAREER")
    channel_config.reset_channel_config()

    fake = FakeSlack()
    monkeypatch.setattr(slack_channels, "http_post", fake)
    monkeypatch.setattr(slack_notifier, "http_post", fake)

    supervision = _supervision(
        _briefing("morning_operations", "Sabah İşletme Brifingi"),
        _briefing("career_development", "Kariyer Gelişimi"),
    )
    publication = _publish(supervision, tmp_path)

    from ai_assistant.daily_digest import distribute_digest_by_channel

    result = distribute_digest_by_channel(supervision, publication)

    assert fake.channels == ["CMORNING", "CCAREER", "CMAIN"]
    assert result["main_channel"].status == STATUS_OK
    assert set(result["advisor_channels"]) == {"morning_operations", "career_development"}
    assert all(r.status == STATUS_OK for r in result["advisor_channels"].values())


def test_distribution_is_skipped_cleanly_with_no_slack_configured(tmp_path):
    supervision = _supervision(_briefing("morning_operations", "Sabah İşletme Brifingi"))
    publication = _publish(supervision, tmp_path)

    from ai_assistant.daily_digest import distribute_digest_by_channel

    result = distribute_digest_by_channel(supervision, publication)

    assert result["main_channel"].status == STATUS_SKIPPED
    assert result["advisor_channels"] == {}
    assert result["summary"]


# --- operations manager routing status --------------------------------------


def test_operations_manager_records_where_each_advisor_is_routed(monkeypatch):
    """It resolves the route; the notifier does the sending (exactly once)."""
    from ai_assistant.operations_manager import OperationsManager

    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_MAIN_CHANNEL", "CMAIN")
    monkeypatch.setenv("SLACK_CHANNEL_MORNING_OPERATIONS", "CMORNING")
    channel_config.reset_channel_config()

    manager = OperationsManager(advisors=[])
    briefing = _briefing("morning_operations", "Sabah İşletme Brifingi")

    assert manager._distribute_to_slack("morning_operations", "Sabah", briefing) == "routed: CMORNING"
    assert (
        manager._distribute_to_slack("career_development", "Kariyer", briefing)
        == "routed (fallback): CMAIN"
    )
