"""Configuration and settings loading.

Loads environment variables from a local ``.env`` file (via
``python-dotenv``) and describes which integrations exist and which
environment variables each one needs.

No secrets are hard-coded here; everything comes from the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

# Load variables from a .env file in the current working directory (if any).
# Existing real environment variables always take precedence.
load_dotenv(override=False)


@dataclass(frozen=True)
class IntegrationSpec:
    """Static description of an integration and the env vars it needs.

    Attributes:
        key: Stable identifier used to look up the check function.
        name: Human-readable name shown in the CLI table.
        required_env: Env vars that MUST all be present for the check to run.
        optional_env: Env vars that are used if present but not required.
    """

    key: str
    name: str
    required_env: List[str] = field(default_factory=list)
    optional_env: List[str] = field(default_factory=list)

    def missing_env(self) -> List[str]:
        """Return the list of required env vars that are absent/empty."""
        return [var for var in self.required_env if not os.getenv(var)]


# The canonical registry of integrations this assistant is meant to use.
INTEGRATIONS: List[IntegrationSpec] = [
    # Gmail, Calendar and Drive share a single Google OAuth consent. Whether
    # they are "configured" is decided by
    # ``integrations.google_auth.google_configured()`` (a stored token file or
    # client credentials), not by a simple required-env list, so these specs
    # only document the relevant optional variables.
    IntegrationSpec(
        key="gmail",
        name="Gmail (Google)",
        optional_env=[
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_CREDENTIALS_FILE",
            "GOOGLE_TOKEN_FILE",
        ],
    ),
    IntegrationSpec(
        key="google_calendar",
        name="Google Calendar",
        optional_env=[
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_CREDENTIALS_FILE",
            "GOOGLE_TOKEN_FILE",
        ],
    ),
    IntegrationSpec(
        key="google_drive",
        name="Google Drive",
        optional_env=[
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_CREDENTIALS_FILE",
            "GOOGLE_TOKEN_FILE",
        ],
    ),
    IntegrationSpec(
        key="slack",
        name="Slack",
        required_env=["SLACK_BOT_TOKEN"],
    ),
    IntegrationSpec(
        key="todoist",
        name="Todoist",
        required_env=["TODOIST_API_TOKEN"],
    ),
    IntegrationSpec(
        key="notion",
        name="Notion",
        required_env=["NOTION_API_KEY"],
    ),
    IntegrationSpec(
        key="llm",
        name="LLM (Gemini / OpenAI)",
        # Either provider is acceptable; the check decides which to ping.
        optional_env=["GEMINI_API_KEY", "OPENAI_API_KEY"],
    ),
]

# Shared timeout (seconds) for outbound health requests.
REQUEST_TIMEOUT = float(os.getenv("AI_ASSISTANT_HTTP_TIMEOUT", "10"))


def get_integration(key: str) -> IntegrationSpec:
    """Return the IntegrationSpec for a given key, or raise KeyError."""
    for spec in INTEGRATIONS:
        if spec.key == key:
            return spec
    raise KeyError(f"Unknown integration: {key}")
