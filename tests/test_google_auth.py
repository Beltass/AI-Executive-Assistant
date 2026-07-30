"""Tests for the shared Google OAuth helper and the Google checks.

These run with NO credentials and NO network: the Google integrations must
report ``skipped`` and ``google_configured()`` must be False.

Also covered: the file-free cloud path, where ``GOOGLE_REFRESH_TOKEN`` plus the
inline client id/secret stand in for a token file (the GitHub Actions case).
The refresh call is mocked, so nothing here touches the network.
"""

from __future__ import annotations

import json

import pytest

from ai_assistant.integrations import STATUS_SKIPPED, google_auth
from ai_assistant.integrations import gmail, google_calendar, google_drive

_GOOGLE_ENV_VARS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_CREDENTIALS_FILE",
    "GOOGLE_REFRESH_TOKEN",
]


@pytest.fixture()
def no_google(monkeypatch, tmp_path):
    for var in _GOOGLE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # A token path that definitely does not exist.
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "missing_token.json"))
    yield


@pytest.fixture()
def no_refresh_network(monkeypatch):
    """Make ``Credentials.refresh`` a no-op that just marks the token valid."""
    from google.oauth2.credentials import Credentials

    def fake_refresh(self, request):  # noqa: ANN001 - signature mirrors the lib
        self.token = "fake-access-token"

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)
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


# --- the file-free cloud path (GitHub Actions) -------------------------------


@pytest.fixture()
def env_only_credentials(no_google, monkeypatch):
    """Exactly what the workflow provides: three secrets, no token file."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "abc.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret-value")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "1//refresh-token-value")
    yield


def test_credentials_source_is_none_when_nothing_configured(no_google):
    assert google_auth.credentials_source() is None


def test_credentials_source_is_env_with_a_refresh_token(env_only_credentials):
    assert google_auth.credentials_source() == "env"
    assert google_auth.google_configured() is True


def test_refresh_token_alone_is_not_enough(no_google, monkeypatch):
    """Without a client id/secret the refresh token cannot be exchanged."""
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "1//refresh-token-value")
    assert google_auth.credentials_source() is None
    assert google_auth.google_configured() is False


def test_get_credentials_builds_from_env_refresh_token(
    env_only_credentials, no_refresh_network
):
    creds = google_auth.get_credentials()

    assert creds.refresh_token == "1//refresh-token-value"
    assert creds.client_id == "abc.apps.googleusercontent.com"
    assert creds.token_uri == google_auth._TOKEN_URI
    assert set(google_auth.SCOPES).issubset(set(creds.scopes))
    # The mocked refresh ran, so a usable access token is present.
    assert creds.token == "fake-access-token"


def test_env_refresh_failure_reports_without_leaking_the_token(
    env_only_credentials, monkeypatch
):
    from google.oauth2.credentials import Credentials

    def boom(self, request):  # noqa: ANN001 - signature mirrors the lib
        raise ValueError("invalid_grant: 1//refresh-token-value rejected")

    monkeypatch.setattr(Credentials, "refresh", boom)

    with pytest.raises(google_auth.GoogleAuthError) as excinfo:
        google_auth.get_credentials()

    message = str(excinfo.value)
    assert "GOOGLE_REFRESH_TOKEN" in message
    assert "1//refresh-token-value" not in message


def test_token_file_wins_over_the_env_refresh_token(
    env_only_credentials, no_refresh_network, monkeypatch, tmp_path
):
    token = tmp_path / "token.json"
    token.write_text(
        json.dumps(
            {
                "token": "file-access-token",
                "refresh_token": "1//from-the-file",
                "token_uri": google_auth._TOKEN_URI,
                "client_id": "file.apps.googleusercontent.com",
                "client_secret": "file-secret",
                "scopes": google_auth.SCOPES,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(token))

    assert google_auth.credentials_source() == "token_file"
    creds = google_auth.get_credentials()
    assert creds.refresh_token == "1//from-the-file"


# --- the operator-facing instructions ----------------------------------------


def test_cloud_setup_instructions_name_the_secrets_without_values(
    env_only_credentials,
):
    text = google_auth.cloud_setup_instructions(has_refresh_token=True)
    for name in (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
    ):
        assert name in text
    # It points at the token file instead of echoing anything secret.
    assert google_auth.token_file_path() in text
    assert "1//refresh-token-value" not in text
    assert "client-secret-value" not in text


def test_cloud_setup_instructions_warn_without_a_refresh_token():
    text = google_auth.cloud_setup_instructions(has_refresh_token=False)
    assert "WARNING" in text


@pytest.mark.parametrize(
    "module",
    [gmail, google_calendar, google_drive],
)
def test_google_checks_skip_without_credentials(no_google, module):
    result = module.check_connection()
    assert result.status == STATUS_SKIPPED
    assert result.detail
