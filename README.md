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

### Phase 2 advisors

Five additional supervised agents extend the team. They follow the exact same
`Advisor` interface, so the Operations Manager auto-discovers them, and they
degrade to `skipped` when their config/LLM key is absent.

| Advisor                          | Persona                                              | Needs                                              |
| -------------------------------- | ---------------------------------------------------- | -------------------------------------------------- |
| İş Avcısı & Başvuru Hazırlayıcı  | Prepares target roles, CV/cover-letter bullets & search links | `JOB_KEYWORDS` (+opt. `JOB_LOCATION`) **and** an LLM key |
| Sektör & Rakip İstihbaratı       | Sector technology/AI & competitor briefing           | LLM key (`USER_SECTOR`, opt. `SECTOR_NEWS_RSS_URL`) |
| Yapay Zeka Haberleri             | AI news roundup from a feed or LLM                    | `AI_NEWS_RSS_URL` **or** an LLM key                |
| Ücretsiz Sertifika & Eğitim      | Free certs/courses & language resources for your field | LLM key (opt. `USER_SECTOR`)                     |
| Anka Köprüsü                     | Generic HTTP connector to your external "Anka" assistant | `ANKA_WEBHOOK_URL` / `ANKA_API_URL`              |

**İş Avcısı compliance note.** The job scout deliberately does **not** log in to
or auto-submit applications on LinkedIn / Kariyer.net (that would breach their
Terms of Service and is irreversible). Instead it **prepares** material for you
to review and submit yourself: suggested target roles, tailored CV/cover-letter
bullet points, and plain, ready-to-use SEARCH URLs for LinkedIn Jobs and
Kariyer.net built from your keywords/location.

**Sektör & Yapay Zeka Haberleri caveats.** Because live financial/graph data and
the very latest headlines aren't reliably fetchable, these briefings are
LLM-based and carry an honest caveat that figures/links are not real-time and
should be verified. If you set `SECTOR_NEWS_RSS_URL` / `AI_NEWS_RSS_URL`, recent
headlines from those feeds are folded in (fetched with `httpx` + stdlib
`xml.etree`, guarded so a broken feed never crashes the run).

**Anka Köprüsü env contract.** Configure `ANKA_WEBHOOK_URL` (or the alias
`ANKA_API_URL`); optionally `ANKA_API_KEY` (sent as `Authorization: Bearer`) and
`ANKA_HTTP_METHOD` (default `POST`). When configured, the bridge fires a small
JSON trigger — `{"source": "ai_executive_assistant", "action": "daily_trigger"}`
— and reports a short status. Without a URL it is `skipped`
(`Anka endpoint not configured`).

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
- `GEMINI_API_KEY` **or** `OPENAI_API_KEY` — activates the LLM personas.
- `SLACK_WEBHOOK_URL` **or** (`SLACK_BOT_TOKEN` + `SLACK_CHANNEL`) — activates Slack delivery.

Optional **Phase 2** secrets (all optional; a missing one just skips its agent):

- `JOB_KEYWORDS` (+ optional `JOB_LOCATION`) — activates the job scout.
- `USER_SECTOR` — tailors the sector intel & free-cert advisors (default
  "banka çağrı merkezleri").
- `SECTOR_NEWS_RSS_URL` — folds sector news headlines into the sector briefing.
- `AI_NEWS_RSS_URL` — activates/feeds the AI news advisor.
- `ANKA_WEBHOOK_URL` (+ optional `ANKA_API_KEY`) — activates the Anka bridge.

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
│   │   ├── _rss.py                # shared RSS/Atom fetch + parse helper
│   │   ├── weather.py             # Open-Meteo meteorologist (no key)
│   │   ├── leadership_coach.py
│   │   ├── kids_development.py
│   │   ├── career_hr.py
│   │   ├── job_scout.py           # prepares applications + search links
│   │   ├── sector_intel.py        # sector & competitor intelligence
│   │   ├── ai_news.py             # AI news (feed or LLM roundup)
│   │   ├── free_certs.py          # free certifications & training
│   │   └── anka_bridge.py         # generic HTTP connector to "Anka"
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
