"""Escalation chain tests — Slack DM first, then e-mail, then (paid) SMS.

What these lock down:
- Only P0/P1 alerts climb; P2/P3 get the DM and stop.
- Nothing escalates before ESCALATION_DELAY_MINUTES has passed.
- An acknowledged alert stops the chain dead.
- The same alert is never re-sent while its chain is open (state file).
- SMS is off unless TWILIO_ENABLED is on AND Twilio is configured — and a
  skipped SMS is reported as a failure, never as a fake success.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from ai_assistant.integrations.notification_manager import (
    AlertLevel,
    ESCALATION_CHAIN,
    EscalationManager,
    EscalationRecord,
    NotificationManager,
    normalize_alert_priority,
)


class FrozenClock:
    """A clock the test moves by hand, so no test ever sleeps."""

    def __init__(self, start: datetime | None = None):
        self.now = start or datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, minutes: int) -> None:
        self.now = self.now + timedelta(minutes=minutes)


def build_manager(tmp_path, clock=None, **kwargs) -> EscalationManager:
    """An EscalationManager with every outbound client stubbed out."""
    notifier = NotificationManager(slack_token=None)
    notifier.slack_client = Mock()
    notifier.slack_client.chat_postMessage = Mock(return_value={"ok": True})
    notifier.gmail_service = Mock()
    notifier._send_email_alert = Mock(return_value=True)
    kwargs.setdefault("delay_minutes", 30)
    return EscalationManager(
        notification_manager=notifier,
        state_file=str(tmp_path / "escalations.json"),
        clock=clock or FrozenClock(),
        **kwargs,
    )


class TestPriorityGate:
    """Only the loud alerts are allowed to make the phone ring twice."""

    def test_p0_and_p1_escalate(self, tmp_path):
        manager = build_manager(tmp_path)
        assert manager.is_escalatable("P0") is True
        assert manager.is_escalatable("P1") is True

    def test_p2_and_p3_do_not_escalate(self, tmp_path):
        manager = build_manager(tmp_path)
        assert manager.is_escalatable("P2") is False
        assert manager.is_escalatable("P3") is False

    def test_threshold_is_configurable(self, tmp_path):
        manager = build_manager(tmp_path, min_priority="P0")
        assert manager.is_escalatable("P0") is True
        assert manager.is_escalatable("P1") is False

    def test_alert_level_maps_onto_priority_codes(self):
        assert normalize_alert_priority(AlertLevel.CRITICAL) == "P0"
        assert normalize_alert_priority(AlertLevel.HIGH) == "P1"
        assert normalize_alert_priority(AlertLevel.MEDIUM) == "P2"
        assert normalize_alert_priority(AlertLevel.LOW) == "P3"

    def test_integer_scale_maps_onto_priority_codes(self):
        assert normalize_alert_priority(1) == "P0"
        assert normalize_alert_priority(4) == "P3"
        assert normalize_alert_priority("nonsense") == "P2"


class TestPrimaryChannel:
    """The Slack DM is the phone's push notification and goes out first."""

    def test_notify_sends_slack_first(self, tmp_path):
        manager = build_manager(tmp_path)
        result = asyncio.run(
            manager.notify("alert-1", "Ödeme onayı bekliyor", priority="P0")
        )
        assert result["channel"] == "slack"
        assert result["sent"] is True
        assert manager.notification_manager.slack_client.chat_postMessage.called

    def test_low_priority_stops_after_slack(self, tmp_path):
        clock = FrozenClock()
        manager = build_manager(tmp_path, clock=clock)
        asyncio.run(manager.notify("alert-low", "Haftalık özet", priority="P3"))

        record = manager.get("alert-low")
        assert record.escalatable is False
        assert record.closed is True
        assert record.closed_reason == "below_priority_threshold"

        clock.advance(120)
        assert asyncio.run(manager.run_escalations()) == []

    def test_bridge_client_is_preferred_over_own_client(self, tmp_path):
        bridge = Mock()
        bridge.slack_client = Mock()

        async def post(**kwargs):
            return {"ok": True}

        bridge.slack_client.chat_postMessage = post
        manager = build_manager(tmp_path)
        manager.slack_bridge = bridge

        result = asyncio.run(manager.notify("alert-b", "Kritik", priority="P0"))
        assert result["sent"] is True
        # The bridge answered, so NotificationManager's own client stayed idle.
        assert not manager.notification_manager.slack_client.chat_postMessage.called


class TestEscalationTiming:
    """Silence has to last ESCALATION_DELAY_MINUTES before the next rung."""

    def test_nothing_escalates_before_the_delay(self, tmp_path):
        clock = FrozenClock()
        manager = build_manager(tmp_path, clock=clock)
        asyncio.run(manager.notify("alert-2", "Kritik", priority="P0"))

        clock.advance(29)
        assert asyncio.run(manager.run_escalations()) == []

    def test_email_is_the_second_rung(self, tmp_path):
        clock = FrozenClock()
        manager = build_manager(tmp_path, clock=clock)
        asyncio.run(
            manager.notify(
                "alert-3", "Kritik", priority="P0", email_to="user@example.com"
            )
        )

        clock.advance(30)
        results = asyncio.run(manager.run_escalations())
        assert [r["channel"] for r in results] == ["email"]
        assert results[0]["sent"] is True
        assert manager.notification_manager._send_email_alert.called

    def test_sms_is_the_third_rung_and_closes_the_chain(self, tmp_path):
        clock = FrozenClock()
        manager = build_manager(tmp_path, clock=clock)
        asyncio.run(
            manager.notify(
                "alert-4",
                "Kritik",
                priority="P0",
                email_to="user@example.com",
                sms_to="+900000000",
            )
        )

        clock.advance(30)
        asyncio.run(manager.run_escalations())
        clock.advance(30)
        results = asyncio.run(manager.run_escalations())

        assert [r["channel"] for r in results] == ["sms"]
        record = manager.get("alert-4")
        assert record.closed is True
        assert record.closed_reason == "chain_exhausted"

    def test_chain_order_is_slack_email_sms(self):
        assert ESCALATION_CHAIN == ("slack", "email", "sms")

    def test_delay_comes_from_env(self, tmp_path):
        with patch.dict("os.environ", {"ESCALATION_DELAY_MINUTES": "5"}):
            manager = EscalationManager(
                notification_manager=NotificationManager(slack_token=None),
                state_file=str(tmp_path / "s.json"),
            )
        assert manager.delay_minutes == 5

    def test_unparseable_delay_falls_back_to_default(self, tmp_path):
        with patch.dict("os.environ", {"ESCALATION_DELAY_MINUTES": "yarım saat"}):
            manager = EscalationManager(
                notification_manager=NotificationManager(slack_token=None),
                state_file=str(tmp_path / "s.json"),
            )
        assert manager.delay_minutes == 30


class TestAcknowledgement:
    """A reply is the whole point: it must silence everything downstream."""

    def test_acknowledge_stops_the_chain(self, tmp_path):
        clock = FrozenClock()
        manager = build_manager(tmp_path, clock=clock)
        asyncio.run(
            manager.notify(
                "alert-5", "Kritik", priority="P0", email_to="user@example.com"
            )
        )

        assert manager.acknowledge("alert-5") is True

        clock.advance(600)
        assert asyncio.run(manager.run_escalations()) == []
        assert manager.notification_manager._send_email_alert.called is False

    def test_acknowledge_is_idempotent(self, tmp_path):
        manager = build_manager(tmp_path)
        asyncio.run(manager.notify("alert-6", "Kritik", priority="P0"))
        assert manager.acknowledge("alert-6") is True
        assert manager.acknowledge("alert-6") is False

    def test_acknowledge_unknown_alert_is_false(self, tmp_path):
        manager = build_manager(tmp_path)
        assert manager.acknowledge("never-sent") is False


class TestStatePersistence:
    """The state file is what stops the same alert firing every tick."""

    def test_repeat_notify_does_not_resend(self, tmp_path):
        manager = build_manager(tmp_path)
        asyncio.run(manager.notify("alert-7", "Kritik", priority="P0"))
        second = asyncio.run(manager.notify("alert-7", "Kritik", priority="P0"))

        assert second["status"] == "already_open"
        assert second["sent"] is False
        assert manager.notification_manager.slack_client.chat_postMessage.call_count == 1

    def test_state_survives_a_new_manager(self, tmp_path):
        clock = FrozenClock()
        first = build_manager(tmp_path, clock=clock)
        asyncio.run(first.notify("alert-8", "Kritik", priority="P0"))

        second = build_manager(tmp_path, clock=clock)
        again = asyncio.run(second.notify("alert-8", "Kritik", priority="P0"))
        assert again["status"] == "already_open"

    def test_state_file_is_readable_json(self, tmp_path):
        manager = build_manager(tmp_path)
        asyncio.run(manager.notify("alert-9", "Kritik", priority="P0"))

        payload = json.loads((tmp_path / "escalations.json").read_text("utf-8"))
        assert payload["schema_version"] == 1
        assert "alert-9" in payload["escalations"]

    def test_corrupt_state_file_does_not_crash(self, tmp_path):
        (tmp_path / "escalations.json").write_text("{ not json", encoding="utf-8")
        manager = build_manager(tmp_path)
        result = asyncio.run(manager.notify("alert-10", "Kritik", priority="P0"))
        assert result["sent"] is True

    def test_open_escalations_lists_only_live_chains(self, tmp_path):
        manager = build_manager(tmp_path)
        asyncio.run(manager.notify("open-1", "Kritik", priority="P0"))
        asyncio.run(manager.notify("done-1", "Kritik", priority="P0"))
        manager.acknowledge("done-1")

        ids = [r.alert_id for r in manager.open_escalations()]
        assert ids == ["open-1"]

    def test_record_next_channel_walks_the_chain(self):
        record = EscalationRecord(alert_id="x", title="t", stage=-1)
        assert record.next_channel == "slack"
        record.stage = 0
        assert record.next_channel == "email"
        record.stage = 1
        assert record.next_channel == "sms"
        record.stage = 2
        assert record.next_channel is None


class TestSmsGate:
    """SMS costs money, so it stays shut and says so out loud."""

    def test_sms_is_disabled_by_default(self, tmp_path):
        notifier = NotificationManager(
            slack_token=None,
            twilio_sid="AC123",
            twilio_token="secret",
            twilio_phone="+15550000",
        )
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("TWILIO_ENABLED", None)
            sent = asyncio.run(notifier.send_sms_rest("+900000000", "test"))
        assert sent is False

    def test_sms_without_credentials_is_false_not_fake_success(self, tmp_path):
        notifier = NotificationManager(
            slack_token=None, twilio_sid=None, twilio_token=None, twilio_phone=None
        )
        with patch.dict("os.environ", {"TWILIO_ENABLED": "true"}):
            sent = asyncio.run(notifier.send_sms_rest("+900000000", "test"))
        assert sent is False

    def test_sms_without_destination_is_false(self):
        notifier = NotificationManager(
            slack_token=None,
            twilio_sid="AC123",
            twilio_token="secret",
            twilio_phone="+15550000",
        )
        with patch.dict("os.environ", {"TWILIO_ENABLED": "1"}):
            sent = asyncio.run(notifier.send_sms_rest("", "test"))
        assert sent is False

    def test_sms_posts_to_twilio_rest_when_enabled(self):
        notifier = NotificationManager(
            slack_token=None,
            twilio_sid="AC123",
            twilio_token="secret",
            twilio_phone="+15550000",
        )
        captured = {}

        class FakeResponse:
            status_code = 201
            text = ""

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, auth=None, data=None):
                captured["url"] = url
                captured["auth"] = auth
                captured["data"] = data
                return FakeResponse()

        import httpx

        with patch.dict("os.environ", {"TWILIO_ENABLED": "true"}), patch.object(
            httpx, "AsyncClient", FakeClient
        ):
            sent = asyncio.run(notifier.send_sms_rest("+900000000", "acil"))

        assert sent is True
        assert captured["url"].endswith("/Accounts/AC123/Messages.json")
        assert captured["auth"] == ("AC123", "secret")
        assert captured["data"]["To"] == "+900000000"
        assert captured["data"]["From"] == "+15550000"

    def test_twilio_http_error_is_a_failure(self):
        notifier = NotificationManager(
            slack_token=None,
            twilio_sid="AC123",
            twilio_token="secret",
            twilio_phone="+15550000",
        )

        class FakeResponse:
            status_code = 401
            text = "unauthorized"

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                return FakeResponse()

        import httpx

        with patch.dict("os.environ", {"TWILIO_ENABLED": "true"}), patch.object(
            httpx, "AsyncClient", FakeClient
        ):
            sent = asyncio.run(notifier.send_sms_rest("+900000000", "acil"))
        assert sent is False

    def test_no_twilio_sdk_import_is_required(self):
        """The REST path must not depend on the `twilio` package."""
        import ai_assistant.integrations.notification_manager as module

        source = open(module.__file__, encoding="utf-8").read()
        rest = source.split("async def send_sms_rest", 1)[1].split("class Deadline")[0]
        assert "twilio.rest" not in rest


class TestChannelFailures:
    """A dead channel is recorded as dead; the chain still moves on."""

    def test_slack_failure_is_recorded(self, tmp_path):
        manager = build_manager(tmp_path)
        manager.notification_manager.slack_client.chat_postMessage = Mock(
            return_value={"ok": False, "error": "channel_not_found"}
        )
        result = asyncio.run(manager.notify("alert-11", "Kritik", priority="P0"))
        assert result["sent"] is False
        assert manager.get("alert-11").attempts["slack"].startswith("failed:")

    def test_missing_slack_client_is_not_a_crash(self, tmp_path):
        manager = build_manager(tmp_path)
        manager.notification_manager.slack_client = None
        result = asyncio.run(manager.notify("alert-12", "Kritik", priority="P0"))
        assert result["sent"] is False

    def test_email_without_recipient_is_skipped_not_faked(self, tmp_path):
        clock = FrozenClock()
        manager = build_manager(tmp_path, clock=clock)
        asyncio.run(manager.notify("alert-13", "Kritik", priority="P0"))

        clock.advance(30)
        results = asyncio.run(manager.run_escalations())
        assert results[0]["channel"] == "email"
        assert results[0]["sent"] is False
        assert manager.notification_manager._send_email_alert.called is False

    def test_slack_exception_does_not_propagate(self, tmp_path):
        manager = build_manager(tmp_path)
        manager.notification_manager.slack_client.chat_postMessage = Mock(
            side_effect=RuntimeError("boom")
        )
        result = asyncio.run(manager.notify("alert-14", "Kritik", priority="P0"))
        assert result["sent"] is False
