"""Tests for the Slack notifier.

Run offline with no Slack credentials: the notifier must report ``skipped``
and never attempt a network call or crash.
"""

from __future__ import annotations

import pytest

from ai_assistant.integrations import STATUS_SKIPPED
from ai_assistant.notifiers import slack_notifier

_ENV_VARS = [
    "SLACK_WEBHOOK_URL",
    "SLACK_BOT_TOKEN",
    "SLACK_CHANNEL",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "WEATHER_CITY",
    "WEATHER_LATITUDE",
    "WEATHER_LONGITUDE",
]


@pytest.fixture()
def no_slack(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


def test_send_message_skipped_when_unconfigured(no_slack):
    result = slack_notifier.send_message("hello")
    assert result.status == STATUS_SKIPPED
    assert result.detail


def test_send_daily_digest_skipped_when_unconfigured(no_slack):
    result = slack_notifier.send_daily_digest()
    assert result.status == STATUS_SKIPPED


def test_bot_mode_requires_channel(no_slack, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    # No SLACK_CHANNEL and no webhook -> still skipped (incomplete config).
    result = slack_notifier.send_message("hello")
    assert result.status == STATUS_SKIPPED


def test_main_exit_zero_when_unconfigured(no_slack, capsys):
    code = slack_notifier.main()
    assert code == 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out
