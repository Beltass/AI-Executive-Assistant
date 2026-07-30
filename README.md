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
| Hava Durumu          | Turkish meteorologist daily summary       | Nothing — `WEATHER_CITY` defaults to `Istanbul` (override with `WEATHER_COUNTRY` / `WEATHER_LATITUDE`+`WEATHER_LONGITUDE`); Open-Meteo, **no key** |
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
| İş Avcısı & Başvuru Hazırlayıcı  | Prepares target roles, CV/cover-letter bullets & search links | An LLM key (`JOB_KEYWORDS`/`JOB_LOCATION` have defaults) |
| Sektör & Rakip İstihbaratı       | Sector technology/AI & competitor briefing           | An LLM key (`USER_SECTOR`, `SECTOR_NEWS_RSS_URL` have defaults) |
| Yapay Zeka Haberleri             | AI news roundup from a feed or LLM                    | Nothing — `AI_NEWS_RSS_URL` has a default feed; an LLM key deepens it |
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
should be verified. `SECTOR_NEWS_RSS_URL` / `AI_NEWS_RSS_URL` default to Turkish
Google News search feeds, so recent headlines (with their real links) are folded
in out of the box — fetched with `httpx` + stdlib `xml.etree` and guarded, so an
unreachable feed degrades to the LLM-only roundup instead of failing.

### Phase 3 advisors

Four more supervised agents, discovered the same way and degrading to
``skipped`` exactly like the rest.

| Advisor                              | Persona                                                            | Needs                                                     |
| ------------------------------------ | ------------------------------------------------------------------ | --------------------------------------------------------- |
| Banka & Çağrı Merkezi Proje Uzmanı   | Senior consultant on bank contact-center **outsourcing programs**   | An LLM key (`BANKING_NEWS_RSS_URL` has a default feed)     |
| Hesap Sorucu Koç                     | Behaviour-science accountability coach over the other advisors' tasks | Nothing — **no LLM call at all** (`ACCOUNTABILITY_STATE_FILE` has a default) |
| Gün Başı Operasyon Brifingi          | Chief-of-staff morning briefing from Gmail + Calendar               | The one-time **Google OAuth login** (+ an LLM key to deepen it) |
| İngilizce & Yönetici İletişimi Koçu  | Business-English + executive-presence coach                          | An LLM key (opt. `USER_SECTOR`)                            |

**Banka & Çağrı Merkezi Proje Uzmanı** is a deep *domain* expert, deliberately
distinct from the broader `sector_intel` agent: it writes like a consultant who
has run bank contact-center outsourcing programs. Every briefing covers
outsourcing projects (RFP/ihale prep, vendor selection, pricing models —
FTE / per-minute / hybrid / outcome-based —, transition risks, SLA & KPI design
around AHT, FCR, NPS, occupancy, shrinkage, abandon rate, penalty–bonus
mechanics), ⚠️ the rules a bank must respect (BDDK information-systems &
outsourcing expectations, KVKK controller/processor split, retention, data
residency & cross-border transfer, PCI-DSS, call-recording duties, audit trails,
BCP/DR), 🚨 typical traps (data leakage, SLA gaps, hidden costs, quality-decay
signals, vendor lock-in and a missing exit plan, subcontractor chains) and
🔬 the latest technology (speech/text analytics, agent assist, voice & chat bots,
CCaaS, WFM, omnichannel, generative AI in the contact center, QM automation).

*Accuracy first:* because regulation changes and models invent article numbers,
the persona is instructed to describe **principles and direction, never specific
clauses or dates**, to flag whatever must be verified, and every briefing ends
with a fixed caveat pointing at your bank's own compliance/legal team and the
official regulator sites (BDDK, KVKK, TCMB — root domains only, per the shared
anti-hallucinated-link rules). `BANKING_NEWS_RSS_URL` defaults to a Turkish
Google News search feed so it can cite REAL links; an unreachable feed silently
degrades to the LLM-only briefing.

**Hesap Sorucu Koç** reads the other advisors' `✅ Bugünün görevi` items from the
**current run**, restates them as one checkable list, and asks yesterday's
uncomfortable question — *yaptın mı?* — alongside your streak, an implementation
intention prompt and a "shrink the task" fallback. It is registered **last** so
the supervisor can hand it the briefings produced before it (via the
`Advisor.observe()` hook), and it makes **no LLM call**, so it costs nothing
against the free-tier quota and cannot invent a task you were never given. If the
other sections failed or were skipped, it degrades to a generic restart nudge.

> ⚠️ **Persistence limitation (read this).** The coach stores a small JSON file
> (`ACCOUNTABILITY_STATE_FILE`, default `.assistant_state/accountability.json`)
> with each day's tasks and the streak counter. On **GitHub Actions the runner
> filesystem is ephemeral**: every scheduled run starts from a clean checkout, so
> yesterday's file is gone. The advisor therefore treats "no prior state" as a
> legitimate fresh start — it never crashes, you still get today's consolidated
> list and a day-1 streak — but real cross-day tracking would need the state
> committed back to the repo or moved to an external store (a Gist, Notion, a KV
> service). That is deliberately **not** implemented here; locally (and within a
> single run) the file works normally.

**Gün Başı Operasyon Brifingi** uses the **existing** shared Google OAuth
(read-only Gmail/Calendar scopes — no new auth is invented). Until you complete
the one-time login it reports `skipped` with that exact instruction, which is the
expected state on a fresh checkout and on GitHub Actions:

```bash
python -m ai_assistant.integrations.google_auth
```

Once logged in it fetches a **bounded** slice of recent unread/important mail
(`OPS_BRIEFING_EMAIL_WINDOW`, default `1d`; `OPS_BRIEFING_MAX_EMAILS`, default 12)
plus today's calendar events, then produces: e-postalarda aksiyon gerektirenler /
bekleyen cevaplar, bugünkü toplantılar + her biri için kısa hazırlık notu,
çakışmalar ve derin çalışma için boş bloklar, and günün 3 kritik önceliği.
**Privacy:** only metadata (sender, subject, time) and Gmail's own short snippet
are read — never a full message body — and the snippet is truncated before it
reaches the model. Every network call is guarded; if the model is unavailable you
still get the gathered facts.

**İngilizce & Yönetici İletişimi Koçu** teaches 5 business-English patterns a day
with banking/contact-center usage examples, a "Bu cümleyi İngilizce kur" mini
exercise whose model answer is printed at the very bottom behind an explicit
*"önce kendin dene"* divider (the advisor keeps no state, so the answer travels
with the exercise), and a weekly executive-communication focus that rotates off
the ISO week number: veriyle hikâye anlatma → yönetim kuruluna sunum → ikna &
müzakere → toplantı yönetimi.

### Defaults: the whole team is active out of the box

`config.DEFAULT_SETTINGS` pre-fills the **non-secret** configuration so every
agent produces content without any setup. A non-empty environment variable or
GitHub secret always wins; an unset secret (which Actions expands to an empty
string) falls back to the default.

| Setting               | Default                                                        |
| --------------------- | -------------------------------------------------------------- |
| `WEATHER_CITY`        | `Istanbul`                                                      |
| `USER_SECTOR`         | `banka çağrı merkezleri`                                        |
| `JOB_KEYWORDS`        | `çağrı merkezi müdürü, müşteri deneyimi yöneticisi, operasyon müdürü` |
| `JOB_LOCATION`        | `İstanbul`                                                      |
| `AI_NEWS_RSS_URL`     | Google News RSS search for *yapay zeka* (Turkish)               |
| `SECTOR_NEWS_RSS_URL` | Google News RSS search for *çağrı merkezi banka* (Turkish)      |
| `BANKING_NEWS_RSS_URL` | Google News RSS search for banking / contact-center / regulation news (Turkish) |
| `ACCOUNTABILITY_STATE_FILE` | `.assistant_state/accountability.json` (git-ignored, ephemeral on CI) |

Two deliberate exceptions: **no API key is ever defaulted** (without
`GEMINI_API_KEY`/`OPENAI_API_KEY` the LLM advisors still report `skipped` and the
run exits `0`), and the **Anka Köprüsü has no default endpoint** — that URL is
specific to you, so the bridge legitimately stays `skipped` until you set it.

### One batched LLM call per run

The free Gemini tier only allows a couple of `generateContent` calls per quota
window, so asking each persona separately (nine calls) meant most sections came
back `429`/`503` no matter how patiently the client retried — retrying cannot
beat a quota ceiling. By default (`DIGEST_BATCH_MODE=true`) every LLM-backed
advisor contributes a `BatchSection` (its persona + today's brief), they are sent
as **one** request with an explicit output contract, and the response is split
back apart on `### SECTION: <advisor_key>` markers — so per-advisor
`ok`/`failed`/`skipped` statuses are unchanged.

All three LLM-backed Phase 3 advisors join that single call too: the banking
expert and the ops briefing gather their real data first (RSS feed / Gmail +
Calendar) and then contribute those facts inside their batched section, exactly
like the existing RSS advisors. The accountability coach uses no LLM at all, so
the run stays at ~1 Gemini request.

Non-LLM work stays outside the batch: the weather advisor still calls Open-Meteo
directly and the news advisors still fetch their RSS feeds themselves; only the
*summarization* is batched. If the batched call fails, or the model omits a
section, those advisors transparently fall back to their own per-advisor call.
Set `DIGEST_BATCH_MODE=false` to disable batching entirely.

### Gemini resilience

Transient failures are retried with backoff — `429` (rate limit) **and**
`500/502/503/504` (the "model is overloaded" / "service unavailable" family) —
honouring `Retry-After` when present. If a model keeps failing, the client walks
a **fallback chain** (`GEMINI_MODEL` → `gemini-flash-latest` → `gemini-2.0-flash`,
overridable via `GEMINI_FALLBACK_MODELS`) and logs which model actually served
the answer. Every request carries a timeout (`GEMINI_TIMEOUT_SECONDS`, default
120s) so a hung call can't stall the job, and every surfaced error is passed
through key redaction — **the API key can never appear in a log, an error or a
Slack message**.

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
`0 7 * * *` UTC = 10:00 İstanbul, UTC+3 — adjust the time in the workflow;
GitHub Actions cron is always UTC) and on manual
`workflow_dispatch`. It installs the package and runs the Slack notifier.

To turn on **live daily delivery**, add these GitHub repository **Secrets**
(Settings → Secrets and variables → Actions):

- `GEMINI_API_KEY` **or** `OPENAI_API_KEY` — activates the LLM personas.
- `SLACK_WEBHOOK_URL` **or** (`SLACK_BOT_TOKEN` + `SLACK_CHANNEL`) — activates Slack delivery.

Everything else is **optional** and now has a sensible default (see
[Defaults](#defaults-the-whole-team-is-active-out-of-the-box)); set a secret only
when you want to override one:

- `WEATHER_CITY` / `WEATHER_COUNTRY` — override the default city (`Istanbul`).
- `JOB_KEYWORDS` / `JOB_LOCATION` — override the default job-scout search.
- `USER_SECTOR` — tailors the sector intel & free-cert advisors (default
  "banka çağrı merkezleri").
- `SECTOR_NEWS_RSS_URL` / `AI_NEWS_RSS_URL` / `BANKING_NEWS_RSS_URL` — override
  the default Google News feeds.
- `ACCOUNTABILITY_STATE_FILE` — where the accountability coach writes its streak
  state (ephemeral on Actions — see the caveat above).
- `OPS_BRIEFING_MAX_EMAILS` / `OPS_BRIEFING_EMAIL_WINDOW` — how much recent mail
  the ops briefing looks at (defaults: 12 messages, `1d`).
- `ANKA_WEBHOOK_URL` (+ optional `ANKA_API_KEY`) — the only agent with **no**
  default: without it the Anka bridge stays `skipped`.

The **Gün Başı Operasyon Brifingi** needs the one-time Google OAuth login
(`python -m ai_assistant.integrations.google_auth`, which stores a refresh
token); until then it reports `skipped` on every scheduled run, which is
expected and never fails the job.

Any secret you omit falls back to its default (or leaves that advisor/notifier
`skipped` when there is none); the workflow still succeeds.

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
│   │   ├── _llm_base.py           # shared LLM persona base + rich guide
│   │   ├── _batch.py              # one batched LLM call for the whole team
│   │   ├── _rss.py                # shared RSS/Atom fetch + parse helper
│   │   ├── weather.py             # Open-Meteo meteorologist (no key)
│   │   ├── leadership_coach.py
│   │   ├── kids_development.py
│   │   ├── career_hr.py
│   │   ├── job_scout.py           # prepares applications + search links
│   │   ├── sector_intel.py        # sector & competitor intelligence
│   │   ├── ai_news.py             # AI news (feed or LLM roundup)
│   │   ├── free_certs.py          # free certifications & training
│   │   ├── banking_cc_projects.py # bank contact-center outsourcing expert
│   │   ├── accountability_coach.py# consolidates + chases the daily tasks
│   │   ├── daily_ops_briefing.py  # Gmail + Calendar morning briefing
│   │   ├── language_coach.py      # business English & executive presence
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
    ├── test_new_advisors.py
    ├── test_batch.py
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
