"""Tests for the shared Google OAuth helper and the Google checks.

These run with NO credentials and NO network: the Google integrations must
report ``skipped`` and ``google_configured()`` must be False.
"""

from __future__ import annotations

import pytest

from ai_assistant.integrations import STATUS_SKIPPED, google_auth
from ai_assistant.integrations import gmail, google_calendar, google_drive

_GOOGLE_ENV_VARS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_CREDENTIALS_FILE",
]


@pytest.fixture()
def no_google(monkeypatch, tmp_path):
    for var in _GOOGLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # A token path that definitely does not exist.
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "missing_token.json"))
    yield


def test_google_configured_false_without_anything(no_google):
    assert google_auth.google_configured() is False


def test_google_configured_true_with_inline_client(no_google, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "shhh")
    assert google_auth.google_configured() is True


def test_google_configured_true_with_existing_token(no_google, monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(token))
    assert google_auth.google_configured() is True


def test_get_credentials_without_token_raises(no_google):
    with pytest.raises(google_auth.GoogleAuthError):
        google_auth.get_credentials()


@pytest.mark.parametrize(
    "module",
    [gmail, google_calendar, google_drive],
)
def test_google_checks_skip_without_credentials(no_google, module):
    result = module.check_connection()
    assert result.status == STATUS_SKIPPED
    assert result.detail


def test_create_draft_without_credentials_raises(no_google):
    with pytest.raises(google_auth.GoogleAuthError):
        gmail.create_draft("Subject", "Body", to="someone@example.com")
