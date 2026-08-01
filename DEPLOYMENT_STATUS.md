# Deployment Status

**System Status: PRODUCTION-READY FOR DEPLOYMENT** ✓

The AI Executive Assistant system is fully configured and ready for production deployment. All GitHub Actions workflows are scheduled and operational.

## System Statistics

- **Total Lines of Code**: 33,849 (src/ai_assistant)
- **Total Lines of Tests**: 9,300 (tests/)
- **Python Versions Tested**: 3.11, 3.12
- **Test Framework**: pytest

## Configured Workflows

All workflows are located in `.github/workflows/` and are active:

### 1. CI Workflow (`ci.yml`)
- **Trigger**: Every push and pull request
- **Purpose**: Automated testing and linting
- **Runs on**: ubuntu-latest
- **Python versions**: 3.11, 3.12
- **Actions**:
  - Installs dependencies from setup.py
  - Runs full pytest suite
  - Both Python versions run in parallel (fail-fast: false)

### 2. Chat Poller Workflow (`chat-poller.yml`)
- **Schedule**: Every 5 minutes (*/5 * * * * UTC)
- **Purpose**: Polls Slack chat channel for report requests and processes them
- **Manual Trigger**: Via workflow_dispatch with optional channel parameter
- **Concurrency**: Sequential (cancel-in-progress: false) — no overlapping runs
- **Key Features**:
  - Cursor-based polling (remembers position between runs)
  - Resilient to individual message failures
  - Lightweight incremental processing
  - 5-minute intervals mean minimal resource usage

### 3. Daily Briefing Workflow (`daily-briefing.yml`)
- **Schedule**: 4 runs per day (UTC times):
  - 07:00 UTC (10:00 Istanbul) — **Full briefing** (flagship daily report)
  - 11:00 UTC (14:00 Istanbul) — Incremental
  - 15:00 UTC (18:00 Istanbul) — Incremental
  - 19:00 UTC (22:00 Istanbul) — Incremental
- **Purpose**: Runs the supervised advisor team and publishes Turkish digest to Slack
- **Manual Trigger**: Via workflow_dispatch with mode selection (full/incremental)
- **Concurrency**: Sequential (cancel-in-progress: false) — queues back-to-back runs
- **Key Features**:
  - Incremental runs only report new findings (reduces quota usage)
  - Quiet incremental runs skip Slack if nothing new
  - Persists state back to main: advisor memory, findings ledger, dashboard status
  - Batch LLM mode reduces API calls on free tier
  - 10-minute time budget per run (max 600 seconds total LLM time)
  - Multi-channel Slack fan-out (one section per advisor channel)

### 4. Pages Workflow (`pages.yml`)
- **Triggers**:
  - Push to main in `frontend/` or `.github/workflows/pages.yml`
  - Completion of Daily Briefing workflow (via workflow_run)
  - Manual workflow_dispatch
- **Purpose**: Publishes static dashboard to GitHub Pages
- **Published URL**: https://beltass.github.io/AI-Executive-Assistant/
- **Features**:
  - Auto-enables Pages on first run (requires repo settings permission)
  - Fallback host if Vercel disconnects
  - Always-up-to-date from daily briefing commits

## Required GitHub Secrets

### Critical Secrets (Must be set for any operation)

#### Slack Integration
- `SLACK_BOT_TOKEN` — Slack bot OAuth token (User token starting with `xoxp-`)
- `SLACK_WEBHOOK_URL` — Incoming webhook URL for digest posting
- `SLACK_MAIN_CHANNEL` — Primary channel ID (C-xxxxxxxx format)
- `SLACK_ANALYST_CHANNEL` — Chat poller target channel ID

#### LLM Providers (at least one required)
- `GEMINI_API_KEY` — Google Gemini API key (free tier available)
- `OPENAI_API_KEY` — OpenAI API key (backup provider)

### Optional Slack Advisor Channels

When set, advisors post to their own channels (fall back to main channel if unset):
- `SLACK_CHANNEL_WEATHER` — Weather advisor channel
- `SLACK_CHANNEL_MORNING_OPERATIONS` — Morning operations briefing
- `SLACK_CHANNEL_COMMUNICATIONS_CALENDAR` — Communications calendar
- `SLACK_CHANNEL_CAREER_DEVELOPMENT` — Career development advisor
- `SLACK_CHANNEL_MARKET_INTELLIGENCE` — Market intelligence advisor
- `SLACK_CHANNEL_AI_INNOVATION` — AI innovation advisor
- `SLACK_CHANNEL_KIDS_DEVELOPMENT` — Kids development advisor
- `SLACK_CHANNEL_ANKA_BRIDGE` — Anka integration channel
- `SLACK_CHANNEL_EXECUTIVE_COACHING` — Executive coaching channel
- `SLACK_CHANNEL_WORK_ANALYST` — Work analysis channel

### Dashboard & Notifier Configuration
- `DASHBOARD_BASE_URL` — Base URL for published reports (defaults to GitHub Pages URL)
- `WEATHER_CITY` — Weather advisor city (defaults to "Istanbul")
- `WEATHER_COUNTRY` — Weather advisor country (defaults to "Turkey")

### Chat Poller Channels (Optional)
- `SLACK_CHANNEL` — Legacy single-channel setting (SLACK_MAIN_CHANNEL takes precedence)
- `SLACK_CHANNEL_WORK_ANALYST` — Backup work analyst channel
- `CHAT_POLL_MAX_MESSAGES` — Max messages per poll (default: 20)

### Phase 2 Advisors (Job Market & Sector Intelligence)
- `JOB_KEYWORDS` — Keywords to filter job postings
- `JOB_LOCATION` — Geographic scope for job search
- `USER_SECTOR` — Industry sector for market intelligence
- `AI_NEWS_RSS_URL` — RSS feed for AI news
- `SECTOR_NEWS_RSS_URL` — RSS feed for sector-specific news
- `ANKA_WEBHOOK_URL` — Anka platform webhook (optional integration)
- `ANKA_API_KEY` — Anka platform API key (optional integration)

### Phase 3 Advisors (Banking & Contact Center Expert)
- `BANKING_NEWS_RSS_URL` — Banking industry news feed
- `BANKING_SECURITY_RSS_URL` — Banking security feed

### Phase 4 Advisors (AI Mastery & CX Research)
- `AI_MASTERY_LEVEL` — User's AI mastery level for skill advisor
- `AI_MASTERY_RSS_URL` — AI skills and training feed
- `CX_RESEARCH_RSS_URL` — Customer experience research feed
- `FREE_CERTS_RSS_URL` — Free certification announcements feed

### Gmail & Calendar Integration (Optional)
For "Start-of-day ops briefing" advisor:
- `GOOGLE_CLIENT_ID` — OAuth 2.0 Client ID from Google Cloud Console
- `GOOGLE_CLIENT_SECRET` — OAuth 2.0 Client Secret
- `GOOGLE_REFRESH_TOKEN` — Refresh token from one-time local login
- `OPS_BRIEFING_MAX_EMAILS` — Max recent emails to read
- `OPS_BRIEFING_EMAIL_WINDOW` — How far back to search (e.g., "1d", "7d")

### State Management (Advanced)
- `FINDINGS_MEMORY_FILE` — Alternative path for findings ledger (defaults to .assistant_state/findings.json)
- `FINDINGS_MEMORY_DAYS` — How many days to remember findings
- `ACCOUNTABILITY_STATE_FILE` — Alternative path for accountability coach state (defaults to .assistant_state/accountability.json)

## How to Trigger Workflows Manually

### Chat Poller (one-time run)
```bash
gh workflow run chat-poller.yml --ref main
# or with custom channel:
gh workflow run chat-poller.yml --ref main -f channel=C_CHANNEL_ID
```

### Daily Briefing (one-time run)
```bash
# Full briefing
gh workflow run daily-briefing.yml --ref main -f mode=full

# Incremental briefing
gh workflow run daily-briefing.yml --ref main -f mode=incremental
```

### Pages (force dashboard rebuild)
```bash
gh workflow run pages.yml --ref main
```

### CI (via git push)
```bash
git push origin main  # or any branch
```

## Initial Setup Checklist

1. **Create GitHub Secrets** (Settings → Secrets and variables → Actions):
   - [ ] `SLACK_BOT_TOKEN` (required)
   - [ ] `SLACK_WEBHOOK_URL` (required)
   - [ ] `SLACK_MAIN_CHANNEL` (required)
   - [ ] `SLACK_ANALYST_CHANNEL` (required)
   - [ ] `GEMINI_API_KEY` or `OPENAI_API_KEY` (at least one required)

2. **Create Slack Channels** (optional but recommended):
   - Run: `python -m ai_assistant.integrations.slack_setup --apply`
   - Creates advisor-specific channels if not present
   - Adds bot to channels

3. **Set Up Gmail Integration** (optional):
   - Create OAuth 2.0 credentials in Google Cloud Console
   - Run local login to get refresh token
   - Store `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`

4. **Enable GitHub Pages** (automatic on first Pages workflow run):
   - Pages will self-configure if credentials allow
   - If it fails with "Get Pages site failed", manually enable:
     - Go to Settings → Pages
     - Source: "GitHub Actions"

5. **Configure RSS Feeds** (optional for Phase 2+ advisors):
   - Set `AI_NEWS_RSS_URL`, `SECTOR_NEWS_RSS_URL`, etc. as needed

6. **Test the Setup**:
   ```bash
   # Run tests locally
   pytest -q
   
   # Run CI workflow
   gh workflow run ci.yml --ref main
   
   # Trigger a manual daily briefing
   gh workflow run daily-briefing.yml --ref main -f mode=full
   ```

## Known Limitations & Design Notes

### GitHub Actions Limitations
- **Free-tier quota**: Gemini free tier can handle ~8-10 API calls per run
  - Batch mode reduces this to 1 call; if it fails, remaining sections skip
  - Per-advisor retries space out requests with `GEMINI_REQUEST_SPACING_SECONDS`
- **Scheduled run delays**: Scheduled workflows can be delayed by several minutes if GitHub is under load
- **No workflow-to-workflow recursion**: Default `GITHUB_TOKEN` cannot trigger other workflows; this is why `pages.yml` uses `workflow_run` trigger

### Advisor Team Behavior
- **Incremental mode**: Only reports findings not already sent to user (via `findings.json`)
- **Full briefing**: Always posts to Slack (daily at 10:00 Istanbul)
- **Quiet incremental runs**: Skip Slack entirely if nothing new found (`SKIP_SLACK_WHEN_NOTHING_NEW=true`)
- **Time budget**: 600 seconds max per run (guards against runaway LLM retries)

### State Persistence
- **Ephemeral runners**: Filesystem deleted after each workflow run
- **State files persisted to main**: `.assistant_state/` directory committed after every briefing
- **Dashboard updates**: Automatic via `frontend/status.json` from daily briefing
- **Performance metrics**: Rolling history in `frontend/metrics.json` (token/latency counts only)

### Slack Integration
- **Bot token required**: Needed for multi-channel fan-out; webhooks only support a single channel
- **Channel format**: Use `C_XXXXXXXXXX` format (channel ID, not name)
- **Retry policy**: Failed channel posts don't block other channels or the digest

### Concurrency & Queueing
- **Chat poller**: Queued (cancel-in-progress: false) — prevents concurrent polls from conflicting cursors
- **Daily briefing**: Queued (cancel-in-progress: false) — prevents state file merge conflicts
- **Pages**: Queued (cancel-in-progress: false) — prevents half-updated deployments

## Production Deployment Steps

1. Fork or clone this repository to your organization
2. Set all required GitHub Secrets (see checklist above)
3. Verify Pages is enabled (Settings → Pages)
4. Run first manual briefing: `gh workflow run daily-briefing.yml --ref main -f mode=full`
5. Check dashboard: https://YOUR-ORG.github.io/AI-Executive-Assistant/
6. Monitor advisor state in Slack channels
7. Set chat poller channel with `SLACK_ANALYST_CHANNEL` secret
8. Scheduled workflows will begin on their configured times

## Monitoring & Troubleshooting

### Check Workflow Status
```bash
gh workflow list
gh run list --workflow=daily-briefing.yml
gh run view RUN_ID --log  # View logs for a specific run
```

### Common Issues

- **"Get Pages site failed"** → Enable Pages manually (Settings → Pages → Source: GitHub Actions)
- **No Slack messages** → Verify bot token has `chat:write` scope and channel ID is correct
- **"429 Too Many Requests"** → Hit LLM free-tier quota; run next briefing in incremental mode or increase `GEMINI_REQUEST_SPACING_SECONDS`
- **Missing findings** → Check `.assistant_state/findings.json` exists and is readable
- **Stale dashboard** → Force Pages redeploy: `gh workflow run pages.yml --ref main`

## Version & Compatibility

- **Python**: 3.11, 3.12 (tested in CI)
- **GitHub**: Requires Actions, Pages, Secrets support
- **Slack**: Bot token with `chat:write`, `users:read`, `channels:read` scopes
- **LLM**: Gemini API (free) or OpenAI API (paid backup)

---

**Last Updated**: 2026-08-01 (deployment documentation)
**System Status**: ✓ Production-Ready
