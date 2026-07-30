"""Tests for the Slack notifier.

Run offline with no Slack credentials: the notifier must report ``skipped``
and never attempt a network call or crash.
"""

from __future__ import annotations

import pytest

from ai_assistant.advisors import Briefing
from ai_assistant.daily_digest import Digest
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ai_assistant.notifiers import slack_notifier
from ai_assistant.operations_manager import Supervision

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


def _digest(*briefings):
    return Digest(text="brifing gövdesi", supervision=Supervision(briefings=list(briefings)))


def test_run_report_lists_every_advisor_status(capsys):
    slack_notifier._print_run_report(
        _digest(
            Briefing(key="weather", title="Hava Durumu", status=STATUS_OK, text="x" * 120),
            Briefing(key="coach", title="Koç", status=STATUS_FAILED, text="LLM isteği başarısız"),
            Briefing(key="anka", title="Anka", status=STATUS_SKIPPED, text="missing env var(s)"),
        )
    )
    out = capsys.readouterr().out

    assert "Hava Durumu" in out and "120 karakter" in out
    assert "LLM isteği başarısız" in out
    assert "missing env var(s)" in out
    assert "1 ok, 1 failed, 1 skipped" in out


def test_run_report_never_prints_the_briefing_body(capsys):
    """The workflow log is public; only statuses belong there, not content."""
    secret_ish = "Bugün çocuğunuzla şunu yapın: çok özel kişisel içerik"
    slack_notifier._print_run_report(
        _digest(Briefing(key="kids", title="Çocuk", status=STATUS_OK, text=secret_ish))
    )
    out = capsys.readouterr().out

    assert secret_ish not in out
    assert f"{len(secret_ish)} karakter" in out


def test_main_reports_statuses_before_sending(no_slack, capsys):
    code = slack_notifier.main()
    assert code == 0
    out = capsys.readouterr().out
    # The per-advisor table and the summary land in the log even when Slack
    # delivery itself is skipped.
    assert "Danışman Denetimi:" in out
    assert "Operasyon Yöneticisi:" in out
