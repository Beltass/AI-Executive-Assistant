"""Shared Google OAuth 2.0 authentication for Gmail, Calendar, and Drive.

These three integrations share a single Google account and a single OAuth
consent, so they share one set of credentials here. The design is a
"permanent" solution: you log in **once** (interactively) to obtain a
refresh token, which is stored to a local token file. From then on every
run can silently refresh a short-lived access token without any further
human interaction.

Configuration (all via environment variables):

* ``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET`` — OAuth *installed app*
  client credentials, OR
* ``GOOGLE_CREDENTIALS_FILE`` — path to a Google ``client_secret*.json``
  file (downloaded from the Google Cloud console). Takes precedence over
  the inline client id/secret when set.
* ``GOOGLE_TOKEN_FILE`` — where the authorized-user token (including the
  refresh token) is stored. Defaults to ``.google_token.json`` in the
  current working directory. This file is git-ignored.

Run the one-time login flow with::

    python -m ai_assistant.integrations.google_auth

Everything that imports the ``google-auth`` libraries is done lazily so
that this module can be imported (and ``google_configured()`` called) even
when those optional dependencies are not installed.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from google.oauth2.credentials import Credentials

# Read-only scopes: this assistant only ever *reads* from Google services.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]

DEFAULT_TOKEN_FILE = ".google_token.json"

# OAuth endpoints for the installed-app (desktop) flow.
_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GoogleAuthError(RuntimeError):
    """Raised when Google credentials cannot be loaded or refreshed."""


def token_file_path() -> str:
    """Return the configured path to the stored token file."""
    return os.getenv("GOOGLE_TOKEN_FILE", DEFAULT_TOKEN_FILE)


def _client_secrets_file() -> Optional[str]:
    """Return a usable client-secrets file path, if configured and present."""
    path = os.getenv("GOOGLE_CREDENTIALS_FILE")
    if path and os.path.exists(path):
        return path
    return None


def _inline_client_config() -> Optional[dict]:
    """Build an installed-app client config from inline env credentials."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": ["http://localhost"],
        }
    }


def google_configured() -> bool:
    """Return True if Google auth *could* work.

    This is the signal the Gmail/Calendar/Drive checks use to decide
    between ``skipped`` (nothing configured) and actually attempting a
    request. It is True when either a stored token file already exists, or
    client credentials are available to run/refresh the OAuth flow.
    """
    if os.path.exists(token_file_path()):
        return True
    if _client_secrets_file() is not None:
        return True
    if _inline_client_config() is not None:
        return True
    return False


def _save_credentials(creds: "Credentials") -> None:
    """Persist the authorized-user credentials (with refresh token) to disk."""
    with open(token_file_path(), "w", encoding="utf-8") as fh:
        fh.write(creds.to_json())


def get_credentials() -> "Credentials":
    """Load stored credentials, refreshing the access token if needed.

    Raises:
        GoogleAuthError: if no token is stored, the ``google-auth`` libs
            are missing, or the token is invalid and cannot be refreshed.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # optional dependency not installed
        raise GoogleAuthError(
            "google-auth libraries not installed; run "
            "`pip install -e \".[dev]\"`"
        ) from exc

    path = token_file_path()
    if not os.path.exists(path):
        raise GoogleAuthError(
            "no stored Google token; run "
            "`python -m ai_assistant.integrations.google_auth` to log in"
        )

    creds = Credentials.from_authorized_user_file(path, SCOPES)

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds)
        return creds

    raise GoogleAuthError(
        "stored Google token is invalid and cannot be refreshed; "
        "re-run the login flow"
    )


def run_login_flow() -> "Credentials":
    """Run the interactive installed-app OAuth flow and store the token.

    Opens a browser for the one-time Google consent, exchanges the code
    for a token that includes a refresh token, and writes it to the
    configured token file.
    """
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:  # optional dependency not installed
        raise GoogleAuthError(
            "google-auth-oauthlib not installed; run "
            "`pip install -e \".[dev]\"`"
        ) from exc

    secrets_file = _client_secrets_file()
    if secrets_file is not None:
        flow = InstalledAppFlow.from_client_secrets_file(secrets_file, SCOPES)
    else:
        config = _inline_client_config()
        if config is None:
            raise GoogleAuthError(
                "no Google client credentials configured; set "
                "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, or "
                "GOOGLE_CREDENTIALS_FILE"
            )
        flow = InstalledAppFlow.from_client_config(config, SCOPES)

    # ``access_type=offline`` + ``prompt=consent`` ensures we receive a
    # refresh token so future runs never need human interaction again.
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )
    _save_credentials(creds)
    return creds


def main(argv: Optional[list] = None) -> int:
    """CLI entrypoint for the one-time login flow."""
    if not google_configured() and _inline_client_config() is None and _client_secrets_file() is None:
        print(
            "No Google client credentials configured.\n"
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET (or "
            "GOOGLE_CREDENTIALS_FILE) in your environment / .env, then "
            "re-run this command.",
            file=sys.stderr,
        )
        return 1

    try:
        creds = run_login_flow()
    except GoogleAuthError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface any flow error clearly
        print(f"Login failed: {exc}", file=sys.stderr)
        return 1

    # Surface the granted account/scopes without printing the token itself.
    try:
        data = json.loads(creds.to_json())
        scopes = data.get("scopes", SCOPES)
    except Exception:  # pragma: no cover - defensive
        scopes = SCOPES

    print(f"Success! Token stored at: {token_file_path()}")
    print("Granted scopes:")
    for scope in scopes:
        print(f"  - {scope}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
