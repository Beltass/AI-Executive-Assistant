# AI-Executive-Assistant

A production-ready **AI Executive Assistant** — your personal digital chief of
staff. This repository currently contains the project skeleton and a runnable
**connection check** that verifies whether each integration the assistant
relies on is configured and reachable.

## Integrations covered

| Integration      | Purpose                    | Required env var(s)                    |
| ---------------- | -------------------------- | -------------------------------------- |
| Gmail            | Email                      | `GOOGLE_OAUTH_ACCESS_TOKEN`            |
| Google Calendar  | Scheduling                 | `GOOGLE_OAUTH_ACCESS_TOKEN`            |
| Google Drive     | Documents / files          | `GOOGLE_OAUTH_ACCESS_TOKEN`            |
| Slack            | Messaging                  | `SLACK_BOT_TOKEN`                      |
| Todoist          | Tasks                      | `TODOIST_API_TOKEN`                    |
| Notion           | Notes / knowledge base     | `NOTION_API_KEY`                       |
| LLM (Gemini/OpenAI) | Reasoning engine        | `GEMINI_API_KEY` or `OPENAI_API_KEY`   |

Each check **skips** gracefully when its credentials are missing, so the tool
runs cleanly out of the box before you have configured anything.

## Project layout

```
.
├── pyproject.toml                 # deps + packaging + pytest config
├── .env.example                   # every expected env var, documented
├── scripts/
│   └── check_connections.py       # convenience CLI wrapper
├── src/ai_assistant/
│   ├── __init__.py
│   ├── config.py                  # loads .env, defines integration specs
│   ├── health.py                  # run_all_checks() + CLI entrypoint
│   └── integrations/
│       ├── __init__.py            # CheckResult + status constants
│       ├── _common.py             # shared HTTP helpers
│       ├── gmail.py
│       ├── google_calendar.py
│       ├── google_drive.py
│       ├── slack.py
│       ├── todoist.py
│       ├── notion.py
│       └── llm.py
└── tests/
    └── test_health.py
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
