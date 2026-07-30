"""Configuration and settings loading.

Loads environment variables from a local ``.env`` file (via
``python-dotenv``) and describes which integrations exist and which
environment variables each one needs.

No secrets are hard-coded here; everything comes from the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List
from urllib.parse import quote_plus

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
    # ``integrations.google_auth.google_configured()`` (a stored token file, an
    # environment refresh token, or client credentials), not by a simple
    # required-env list, so these specs only document the optional variables.
    IntegrationSpec(
        key="gmail",
        name="Gmail (Google)",
        optional_env=[
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_CREDENTIALS_FILE",
            "GOOGLE_TOKEN_FILE",
            "GOOGLE_REFRESH_TOKEN",
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
            "GOOGLE_REFRESH_TOKEN",
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
            "GOOGLE_REFRESH_TOKEN",
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


def _google_news_rss(query: str) -> str:
    """Build a Turkish Google News RSS search feed URL for ``query``."""
    return (
        "https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl=tr&gl=TR&ceid=TR:tr"
    )


# --- Non-secret defaults ----------------------------------------------------
# Sensible out-of-the-box values so the WHOLE advisor team produces content
# without any manual setup. Every entry is overridable: a non-empty environment
# variable (or GitHub secret) always wins, and an empty/unset secret — which
# GitHub Actions passes through as an empty string — falls back to the default
# here.
#
# SAFETY: only NON-SECRET configuration lives here. API keys and tokens are
# never defaulted, so a missing LLM key still yields a ``skipped`` briefing and
# a zero exit code. The Anka bridge is deliberately absent too: its endpoint is
# user-specific and must never be invented.
DEFAULT_SETTINGS: Dict[str, str] = {
    "WEATHER_CITY": "Istanbul",
    "USER_SECTOR": "banka çağrı merkezleri",
    "JOB_KEYWORDS": "çağrı merkezi müdürü, müşteri deneyimi yöneticisi, operasyon müdürü",
    "JOB_LOCATION": "İstanbul",
    # Real, verifiable feeds so the news advisors link to actual articles even
    # when no RSS secret is configured.
    "AI_NEWS_RSS_URL": _google_news_rss("yapay zeka"),
    "SECTOR_NEWS_RSS_URL": _google_news_rss("çağrı merkezi banka"),
    # Banking / contact-center project expert: regulation + outsourcing news, so
    # the deep-domain briefing can cite REAL links instead of inventing them.
    "BANKING_NEWS_RSS_URL": _google_news_rss(
        '"çağrı merkezi" bankacılık OR BDDK OR "dış kaynak"'
    ),
    # Second, security/compliance-flavoured feed for the same advisor: KVKK,
    # data breaches and information security in banking. Free Google News search
    # again, so the outsourcing-governance briefing has current, REAL links for
    # its compliance and security blocks too.
    "BANKING_SECURITY_RSS_URL": _google_news_rss(
        'KVKK OR "bilgi güvenliği" OR "veri ihlali" banka OR bankacılık'
    ),
    # Accountability coach state. On GitHub Actions the runner filesystem is
    # ephemeral, so the daily-briefing workflow commits this file back to the
    # repository after each run; that is what makes the streak durable. A
    # missing file is still a legitimate fresh start (see the advisor docstring).
    "ACCOUNTABILITY_STATE_FILE": ".assistant_state/accountability.json",
}


def setting(name: str, default: str = "") -> str:
    """Return a non-secret setting: env var if set, else the built-in default.

    Whitespace-only environment values count as unset (GitHub Actions expands a
    missing secret to an empty string), so the default takes over.
    """
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    return DEFAULT_SETTINGS.get(name, default)


def get_integration(key: str) -> IntegrationSpec:
    """Return the IntegrationSpec for a given key, or raise KeyError."""
    for spec in INTEGRATIONS:
        if spec.key == key:
            return spec
    raise KeyError(f"Unknown integration: {key}")
