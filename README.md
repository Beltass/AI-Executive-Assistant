# AI-Executive-Assistant

A production-ready **AI Executive Assistant** — your personal digital chief of
staff. This repository currently contains the project skeleton and a runnable
**connection check** that verifies whether each integration the assistant
relies on is configured and reachable.

## Integrations covered

| Integration      | Purpose                    | Required env var(s)                          |
| ---------------- | -------------------------- | -------------------------------------------- |
| Gmail            | Email                      | Google OAuth (see below)                     |
| Google Calendar  | Scheduling                 | Google OAuth (see below)                     |
| Google Drive     | Documents / files          | Google OAuth (see below)                     |
| Slack            | Messaging                  | `SLACK_BOT_TOKEN`                            |
| Todoist          | Tasks                      | `TODOIST_API_TOKEN`                          |
| Notion           | Notes / knowledge base     | `NOTION_API_KEY`                             |
| LLM (Gemini/OpenAI) | Reasoning engine        | `GEMINI_API_KEY` or `OPENAI_API_KEY`         |

Gmail, Calendar and Drive share a single Google account and one OAuth consent
via a **permanent** login: you authorize once, a refresh token is stored, and
every subsequent run refreshes the short-lived access token automatically. See
[Google OAuth login](#google-oauth-login) below.

Each check **skips** gracefully when its credentials are missing, so the tool
runs cleanly out of the box before you have configured anything.

## Daily advisor team

On top of the connection checks the assistant ships a **supervised team of
daily advisor agents** that produce a single Turkish morning briefing.

| Advisor              | Persona                                   | Needs                                            |
| -------------------- | ----------------------------------------- | ------------------------------------------------ |
| Hava Durumu          | Turkish meteorologist daily summary       | `WEATHER_CITY` (+opt. `WEATHER_COUNTRY`) or `WEATHER_LATITUDE`/`WEATHER_LONGITUDE` — Open-Meteo, **no key** |
| Liderlik Koçu        | Senior leadership coach                    | `GEMINI_API_KEY` or `OPENAI_API_KEY`             |
| Çocuk Gelişimi       | Child development & education advisor       | `GEMINI_API_KEY` or `OPENAI_API_KEY`             |
| Kariyer & İK         | Senior HR director / career mentor          | `GEMINI_API_KEY` or `OPENAI_API_KEY`             |

Each advisor exposes one interface — `generate_briefing()` — returning a
structured `Briefing` (title, status `ok`/`failed`/`skipped`, text). All
network/LLM calls are guarded, so a missing key means `skipped` and a broken
call means `failed`; neither crashes the run.

### Operations Manager (the supervising agent)

`ai_assistant.operations_manager.OperationsManager` is the single orchestration
entry point. It auto-discovers every advisor, runs each one, isolates per-advisor
failures so one broken advisor never breaks the others, and returns a
supervision summary (who ran, each status, failure reasons, counts like
`3 ok, 0 failed, 1 skipped`).

```bash
python -m ai_assistant.operations_manager
```

Exits `0` even when advisors are skipped; non-zero only if a *configured*
advisor actually failed (mirroring `health.py`).

### Daily digest

`ai_assistant.daily_digest.build_digest()` runs the Operations Manager and
assembles one dated Turkish report — a header, one section per advisor, and a
short supervision line (`Operasyon Yöneticisi: 3 ok, 1 skipped`).

```bash
python -m ai_assistant.daily_digest
```

### Slack notifier

`ai_assistant.notifiers.slack_notifier` builds the digest and posts it to Slack
via an Incoming Webhook (`SLACK_WEBHOOK_URL`) or a bot token
(`SLACK_BOT_TOKEN` + `SLACK_CHANNEL`, `chat.postMessage`). With neither set it
reports `skipped` and exits `0`.

```bash
python -m ai_assistant.notifiers.slack_notifier
```

### Scheduled daily delivery

`.github/workflows/daily-briefing.yml` runs on a daily `schedule` (cron
`0 6 * * *` UTC — adjust the time/timezone in the workflow) and on manual
`workflow_dispatch`. It installs the package and runs the Slack notifier.

To turn on **live daily delivery**, add these GitHub repository **Secrets**
(Settings → Secrets and variables → Actions):

- `WEATHER_CITY` (and optionally `WEATHER_COUNTRY`) — activates the weather advisor.
- `GEMINI_API_KEY` **or** `OPENAI_API_KEY` — activates the three LLM personas.
- `SLACK_WEBHOOK_URL` **or** (`SLACK_BOT_TOKEN` + `SLACK_CHANNEL`) — activates Slack delivery.

Any secret you omit simply leaves that advisor/notifier `skipped`; the workflow
still succeeds.

## Project layout

```
.
├── pyproject.toml                 # deps + packaging + pytest config
├── .env.example                   # every expected env var, documented
├── .github/workflows/ci.yml       # GitHub Actions: install + pytest
├── .github/workflows/daily-briefing.yml  # scheduled Slack daily digest
├── src/ai_assistant/
│   ├── __init__.py
│   ├── config.py                  # loads .env, defines integration specs
│   ├── health.py                  # run_all_checks() + CLI entrypoint
│   ├── operations_manager.py      # supervising agent over the advisors
│   ├── daily_digest.py            # build_digest() + CLI entrypoint
│   ├── advisors/
│   │   ├── __init__.py            # Advisor/Briefing base + discovery
│   │   ├── _llm_base.py           # shared LLM persona base
│   │   ├── weather.py             # Open-Meteo meteorologist (no key)
│   │   ├── leadership_coach.py
│   │   ├── kids_development.py
│   │   └── career_hr.py
│   ├── notifiers/
│   │   ├── __init__.py
│   │   └── slack_notifier.py      # webhook / chat.postMessage delivery
│   └── integrations/
│       ├── __init__.py            # CheckResult + status constants
│       ├── _common.py             # shared HTTP helpers
│       ├── google_auth.py         # shared Google OAuth 2.0 flow + CLI
│       ├── gmail.py
│       ├── google_calendar.py
│       ├── google_drive.py
│       ├── slack.py
│       ├── todoist.py
│       ├── notion.py
│       └── llm.py                 # check + generate_text() for advisors
└── tests/
    ├── test_health.py
    ├── test_google_auth.py
    ├── test_advisors.py
    ├── test_operations_manager.py
    └── test_slack_notifier.py
```

## Setup

Requires Python 3.9+.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install the package (plus dev tools for tests)
pip install -e ".[dev]"

# 3. Configure credentials
cp .env.example .env
# then edit .env and fill in the tokens you have
```

## Google OAuth login

Gmail, Google Calendar and Google Drive authenticate through a single shared
Google OAuth 2.0 flow (read-only scopes). You log in **once**:

1. In the [Google Cloud console](https://console.cloud.google.com/), create an
   OAuth client of type **Desktop app** and enable the Gmail, Calendar and
   Drive APIs. Either copy the client id/secret into `.env`
   (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) or download the
   `client_secret*.json` and point `GOOGLE_CREDENTIALS_FILE` at it.
2. Run the one-time login flow:

   ```bash
   python -m ai_assistant.integrations.google_auth
   ```

   A browser opens for consent; on success a token (including the refresh
   token) is written to `GOOGLE_TOKEN_FILE` (default `.google_token.json`,
   which is git-ignored). From then on the connection checks refresh the
   access token automatically — no further interaction required.

If no Google client credentials and no token file are present, the three
Google checks simply report **SKIPPED**.

## Run the connection check

```bash
python -m ai_assistant.health
# or, equivalently:
python scripts/check_connections.py
```

You'll get a table of every integration with a status of **OK**, **FAILED**, or
**SKIPPED**, followed by a summary line. The process exits:

- **0** — no configured integration failed (skipped ones are fine)
- **1** — at least one configured integration failed its health check

With an empty `.env`, every integration reports `SKIPPED` and the command
exits `0`.

## Run the tests

```bash
pytest
```

The test suite runs without any credentials and verifies that missing-credential
integrations report `skipped` and that the aggregation never crashes.
