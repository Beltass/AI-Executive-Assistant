# AI Executive Assistant — Integration Setup Guide

This guide walks you through setting up Slack, Asana, and Google Drive integrations for the AI Executive Assistant. Each advisor can be routed to dedicated channels for focused information delivery.

**Table of Contents**
- [1. Slack Multi-Channel Setup](#1-slack-multi-channel-setup)
- [2. Asana Setup](#2-asana-setup)
- [3. Google Drive Setup](#3-google-drive-setup)
- [4. Environment Variables Template](#4-environment-variables-template)
- [5. Troubleshooting](#5-troubleshooting)

---

## 1. Slack Multi-Channel Setup

### 1.1 Create Slack Workspace (if needed)

If you don't already have a Slack workspace:

1. Go to [slack.com](https://slack.com)
2. Click **"Create a new workspace"**
3. Follow the wizard to set up your workspace name and region
4. Skip inviting people for now (you can add them later)

### 1.2 Create Advisor Channels

Create a dedicated Slack channel for each advisor. This keeps focused intelligence separate and allows team members to subscribe only to channels they care about.

**All 16 Advisors:**

| Turkish Name | Advisor Key | Channel Name (suggested) |
|---|---|---|
| Hava Tahmini | `weather` | #ajan-hava-tahmini |
| Liderlik Koçu | `leadership_coach` | #ajan-liderlik |
| Çocuk Gelişim Danışmanı | `kids_development` | #ajan-cocuk-gelisim |
| İnsan Kaynakları ve Kariyer | `career_hr` | #ajan-insan-kaynaklari |
| İş Avcısı | `job_scout` | #ajan-is-avcisi |
| Sektör İstihbaratı | `sector_intel` | #ajan-sektor |
| Yapay Zeka Haberleri | `ai_news` | #ajan-ai-haberleri |
| Ücretsiz Sertifika & Eğitim | `free_certs` | #ajan-sertifika |
| Banka & Çağrı Merkezi Proje Uz. | `banking_cc_projects` | #ajan-banka-cc |
| Yapay Zeka Ustalığı Koçu | `ai_mastery` | #ajan-ai-ustaligi |
| Çağrı Merkezi & CX Araştırması | `cx_research` | #ajan-cx-research |
| Gün Başı Operasyon Brifingi | `daily_ops_briefing` | #ajan-ops-briefing |
| Dil Koçu | `language_coach` | #ajan-dil |
| Anka Köprüsü | `anka_bridge` | #ajan-anka |
| İnovasyon Laboratuvarı | `innovation_lab` | #ajan-inovasyon |
| Hesap Sorucu Koç | `accountability_coach` | #ajan-hesap-sorucu |

**To create channels:**

1. In Slack, click the **"+"** icon next to "Channels" in the sidebar
2. Click **"Create a channel"**
3. Name it (e.g., `ajan-hava-tahmini`)
4. Choose visibility (private recommended for sensitive content)
5. Repeat for each advisor

### 1.3 Get Channel IDs

Each channel needs a unique ID for the environment variables.

**To find a channel ID:**

1. In Slack, click on the **channel name** at the top
2. Click the **"About"** tab
3. Scroll to **"Channel details"** → **"Channel ID"**
4. Click the copy icon next to the ID (format: `C0123456789`)

### 1.4 Create Bot or Incoming Webhook

Choose **one** of these authentication methods:

#### Option A: Bot User OAuth Token (Recommended)

**Create a Slack App:**

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"** → **"From scratch"**
3. **App Name:** `AI Executive Assistant`
4. **Workspace:** Select your workspace
5. Click **"Create App"**

**Configure OAuth Scopes:**

1. Left sidebar → **"OAuth & Permissions"**
2. Under **"Scopes"** → **"Bot Token Scopes"**, add:
   - `chat:write` — Post messages to channels
   - `channels:read` — List channels (for debugging)
3. Scroll up to **"OAuth Tokens for Your Workspace"**
4. Click **"Install to Workspace"** (if not already installed)
5. Copy the **Bot User OAuth Token** (starts with `xoxb-`)
6. Add to `.env`: `SLACK_BOT_TOKEN=xoxb-...`

**Add Bot to Channels:**

For each channel:
1. Go to the channel
2. Click the **channel name** at the top
3. Click **"Integrations"** → **"Apps"** → **"Add an App"**
4. Search for your app (`AI Executive Assistant`)
5. Click **"Add"**

#### Option B: Incoming Webhook (Simpler Setup)

**Create a Webhook:**

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"** → **"From scratch"**
3. **App Name:** `AI Executive Assistant Webhook`
4. **Workspace:** Select your workspace
5. Left sidebar → **"Incoming Webhooks"**
6. Toggle **"Activate Incoming Webhooks"** to ON
7. Click **"Add New Webhook to Workspace"**
8. **Select a channel:** Choose your main channel (e.g., `#ajan-ops-briefing`)
9. Click **"Allow"**
10. Copy the **Webhook URL** (format: `https://hooks.slack.com/services/...`)
11. Add to `.env`: `SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...`

**Note:** Webhooks can only post to a single channel. For multi-channel delivery, use the **Bot Token** method instead.

### 1.5 Configure Environment Variables

Add these to your `.env` file:

```bash
# Bot Token (if using Option A)
SLACK_BOT_TOKEN=xoxb-YOUR_TOKEN_HERE

# OR Webhook URL (if using Option B)
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Main channel for briefing summaries (fallback if advisor-specific channels are not set)
SLACK_MAIN_CHANNEL=C0123456789

# Optional: Dedicated channels for each advisor
SLACK_CHANNEL_WEATHER=C0123456789
SLACK_CHANNEL_LEADERSHIP_COACH=C0987654321
SLACK_CHANNEL_KIDS_DEVELOPMENT=C1111111111
SLACK_CHANNEL_CAREER_HR=C2222222222
SLACK_CHANNEL_JOB_SCOUT=C3333333333
SLACK_CHANNEL_SECTOR_INTEL=C4444444444
SLACK_CHANNEL_AI_NEWS=C5555555555
SLACK_CHANNEL_FREE_CERTS=C6666666666
SLACK_CHANNEL_BANKING_CC_PROJECTS=C7777777777
SLACK_CHANNEL_AI_MASTERY=C8888888888
SLACK_CHANNEL_CX_RESEARCH=C9999999999
SLACK_CHANNEL_DAILY_OPS_BRIEFING=C0000000000
SLACK_CHANNEL_LANGUAGE_COACH=C1010101010
SLACK_CHANNEL_ANKA_BRIDGE=C1111111111
SLACK_CHANNEL_INNOVATION_LAB=C1212121212
SLACK_CHANNEL_ACCOUNTABILITY_COACH=C1313131313
```

### 1.6 Test Slack Integration

```bash
python -m src.ai_assistant.integrations.slack_channels
```

**Expected output:**

```
INFO: Slack Channel Notifier initialized with bot token
✓ Message posted to #ajan-hava-tahmini
✓ Message posted to #ajan-liderlik
...
```

If you see errors, check:
- Bot token/webhook URL is correct
- Bot is added to each channel
- Channel IDs are exact (no extra spaces)

---

## 2. Asana Setup

### 2.1 Create Asana Account and Workspace

1. Go to [asana.com](https://asana.com)
2. Click **"Start free"** or sign in if you have an account
3. Create or select your workspace (e.g., "AI Executive Assistant")
4. Note your **Workspace ID** (visible in the URL: `app.asana.com/0/WORKSPACE_ID/list`)

### 2.2 Generate Personal Access Token

1. Go to your **Profile Icon** (top right) → **"Settings"**
2. Left sidebar → **"Apps and Integrations"**
3. Click **"Personal access tokens"**
4. Click **"Generate token"**
5. **Name:** `AI Executive Assistant` (for reference)
6. **Permissions:** Check `tasks`, `projects`, `portfolios`, and `teams` scopes
7. Click **"Generate"**
8. **Copy the token immediately** (you won't see it again)
9. Add to `.env`: `ASANA_TOKEN=0/YOUR_TOKEN_HERE`

### 2.3 Create Main Project

Create a main project to house advisor-generated tasks:

1. Click **"Projects"** in the left sidebar
2. Click **"New project"**
3. **Project name:** `AI Executive Assistant Reports`
4. **Privacy:** Private (or shared with your team)
5. Click **"Create"**
6. Note the **Project ID** (visible in the URL or click "Copy link" and extract from the URL)

Optional: Create individual projects per advisor (e.g., `AI News Reports`, `Job Opportunities`, etc.) if you want better organization.

### 2.4 Get Workspace ID and Project IDs

**Workspace ID:**
- URL format: `app.asana.com/0/WORKSPACE_ID/...`
- Example: `app.asana.com/0/1234567890/list`
- Workspace ID: `1234567890`

**Project ID:**
- Click into a project
- URL format: `app.asana.com/0/WORKSPACE_ID/PROJECT_ID/...`
- Copy the numeric ID after the workspace ID

### 2.5 Configure Environment Variables

Add these to your `.env` file:

```bash
# Asana API token (Personal Access Token)
ASANA_TOKEN=0/1234567890abcdef...

# Workspace ID (from Asana URL)
ASANA_WORKSPACE_ID=1234567890

# Optional: Project name template for created projects
# Default: "{advisor_name}_project"
# ASANA_PROJECT_TEMPLATE={advisor_name}_project
```

### 2.6 Test Asana Integration

```bash
python -c "from src.ai_assistant.integrations.asana import AsanaClient; client = AsanaClient(); print(client.check_connection())"
```

**Expected output:**

```
✓ Asana: connected as your.email@example.com (workspace: AI Executive Assistant)
```

If you see an error:
- Verify token is correct (no extra spaces)
- Ensure workspace ID is numeric only
- Check that your Asana account has access to that workspace

---

## 3. Google Drive Setup

### 3.1 Create Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the **project selector** at the top
3. Click **"NEW PROJECT"**
4. **Project name:** `AI Executive Assistant`
5. Click **"CREATE"**
6. Wait for the project to be created
7. Click the **project selector** again and select your new project

### 3.2 Enable Google Drive API

1. In the Cloud Console, search for **"Google Drive API"** in the search bar
2. Click on **"Google Drive API"**
3. Click **"ENABLE"**
4. Wait for it to enable

### 3.3 Create OAuth 2.0 Credentials

1. Left sidebar → **"Credentials"**
2. Click **"+ CREATE CREDENTIALS"** → **"OAuth 2.0 Client IDs"**
3. If prompted, click **"CONFIGURE CONSENT SCREEN"** first:
   - **User type:** External
   - **App name:** `AI Executive Assistant`
   - **User support email:** Your email
   - **Developer contact:** Your email
   - Click **"SAVE AND CONTINUE"**
   - Under "Scopes", add:
     - `https://www.googleapis.com/auth/drive`
     - `https://www.googleapis.com/auth/spreadsheets`
     - `https://www.googleapis.com/auth/calendar`
     - `https://www.googleapis.com/auth/gmail.readonly`
   - Click **"SAVE AND CONTINUE"** → **"SAVE AND CONTINUE"** → **"BACK TO DASHBOARD"**

4. Go back to **Credentials** tab
5. Click **"+ CREATE CREDENTIALS"** → **"OAuth 2.0 Client IDs"**
6. **Application type:** `Desktop app`
7. Click **"CREATE"**
8. You'll see your credentials. Click **"DOWNLOAD JSON"**
9. Save the file as `client_secret.json` in your project root

Alternatively, if you prefer environment variables:
- Copy the `client_id` and `client_secret` from the JSON
- Add to `.env`: 
  ```bash
  GOOGLE_CLIENT_ID=YOUR_CLIENT_ID.apps.googleusercontent.com
  GOOGLE_CLIENT_SECRET=YOUR_CLIENT_SECRET
  ```

### 3.4 Authorize Your Google Account

1. Run the authentication script:
   ```bash
   python -m src.ai_assistant.integrations.google_auth
   ```

2. A browser window will open asking for permission
3. Click **"Allow"** to grant access
4. A token will be stored as `.google_token.json` (git-ignored)
5. This token refreshes automatically on every run

### 3.5 Create Shared Drive Folder for Reports

1. Go to [drive.google.com](https://drive.google.com)
2. Click **"+ New"** → **"Folder"**
3. **Folder name:** `AI Executive Assistant Reports`
4. Click **"CREATE"**
5. Right-click the folder → **"Copy link"**
6. Extract the **Folder ID** from the link:
   - Link format: `https://drive.google.com/drive/folders/FOLDER_ID`
   - Example: `https://drive.google.com/drive/folders/1abc2DEF3ghI4jKL5mnOPqr6Stu` → Folder ID: `1abc2DEF3ghI4jKL5mnOPqr6Stu`

### 3.6 Configure Environment Variables

Add these to your `.env` file:

```bash
# Option 1: Point to the downloaded credentials file
GOOGLE_CREDENTIALS_FILE=./client_secret.json

# Option 2: OR use inline credentials
# GOOGLE_CLIENT_ID=YOUR_CLIENT_ID.apps.googleusercontent.com
# GOOGLE_CLIENT_SECRET=YOUR_CLIENT_SECRET

# Where the authorized-user token is stored (git-ignored)
GOOGLE_TOKEN_FILE=.google_token.json

# Reports folder ID (from Google Drive URL)
GOOGLE_DRIVE_FOLDER_ID=1abc2DEF3ghI4jKL5mnOPqr6Stu

# Optional: Archive folder for old reports
# GOOGLE_DRIVE_ARCHIVE_FOLDER_ID=1xyz9ABC3ghI4jKL5mnOPqr6Stu

# Base URL for the public dashboard (optional)
# Default: https://beltass.github.io/AI-Executive-Assistant/
DASHBOARD_BASE_URL=https://your-domain.com/dashboard/
```

### 3.7 Test Google Drive Integration

```bash
python -c "from src.ai_assistant.integrations.google_drive import DriveClient; client = DriveClient(); print(client.list_documents_in_folder())"
```

**Expected output:**

```
✓ Google Drive: connected
Found 5 documents in Reports folder:
  - 2026-07-31_summary.md
  - 2026-07-30_summary.md
  ...
```

If you see errors:
- Run `python -m src.ai_assistant.integrations.google_auth` again to refresh the token
- Verify folder ID is correct
- Check that the Google account has access to the folder

---

## 4. Environment Variables Template

### Complete .env Template

Copy this template into your `.env` file and fill in the values:

```bash
# ============================================================================
# AI EXECUTIVE ASSISTANT — INTEGRATION ENVIRONMENT VARIABLES
# ============================================================================
#
# Copy this section to .env and fill in real credentials.
# Never commit .env to version control.
#

# --- GOOGLE DRIVE & AUTH (Gmail, Calendar, Drive share ONE OAuth consent) ---

# Downloaded OAuth 2.0 credentials file (Desktop app type)
GOOGLE_CREDENTIALS_FILE=./client_secret.json

# OR inline client ID/secret (if not using GOOGLE_CREDENTIALS_FILE)
# GOOGLE_CLIENT_ID=YOUR_CLIENT_ID.apps.googleusercontent.com
# GOOGLE_CLIENT_SECRET=YOUR_CLIENT_SECRET

# Token file (git-ignored) stores the refresh token and access token
# Default: .google_token.json
GOOGLE_TOKEN_FILE=.google_token.json

# Reports folder ID (from Google Drive URL: drive.google.com/drive/folders/FOLDER_ID)
GOOGLE_DRIVE_FOLDER_ID=1abc2DEF3ghI4jKL5mnOPqr6Stu

# Optional: Archive folder for old reports
# GOOGLE_DRIVE_ARCHIVE_FOLDER_ID=1xyz9ABC3ghI4jKL5mnOPqr6Stu

# --- SLACK INTEGRATION ---

# Bot User OAuth Token (preferred for multi-channel support)
# Create at: api.slack.com/apps → OAuth & Permissions → Bot Token
SLACK_BOT_TOKEN=xoxb-YOUR_TOKEN_HERE

# OR Incoming Webhook URL (simpler but single-channel only)
# Create at: api.slack.com/apps → Incoming Webhooks
# SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL

# Main channel ID (fallback if advisor-specific channels are not configured)
SLACK_MAIN_CHANNEL=C0123456789

# --- SLACK MULTI-CHANNEL ADVISOR ROUTING (Optional) ---
# Each advisor can have a dedicated channel. Format: SLACK_CHANNEL_<ADVISOR_KEY>
# If not set, falls back to SLACK_MAIN_CHANNEL or SLACK_CHANNEL.

SLACK_CHANNEL_WEATHER=C0123456789
SLACK_CHANNEL_LEADERSHIP_COACH=C0987654321
SLACK_CHANNEL_KIDS_DEVELOPMENT=C1111111111
SLACK_CHANNEL_CAREER_HR=C2222222222
SLACK_CHANNEL_JOB_SCOUT=C3333333333
SLACK_CHANNEL_SECTOR_INTEL=C4444444444
SLACK_CHANNEL_AI_NEWS=C5555555555
SLACK_CHANNEL_FREE_CERTS=C6666666666
SLACK_CHANNEL_BANKING_CC_PROJECTS=C7777777777
SLACK_CHANNEL_AI_MASTERY=C8888888888
SLACK_CHANNEL_CX_RESEARCH=C9999999999
SLACK_CHANNEL_DAILY_OPS_BRIEFING=C0000000000
SLACK_CHANNEL_LANGUAGE_COACH=C1010101010
SLACK_CHANNEL_ANKA_BRIDGE=C1111111111
SLACK_CHANNEL_INNOVATION_LAB=C1212121212
SLACK_CHANNEL_ACCOUNTABILITY_COACH=C1313131313

# --- ASANA INTEGRATION ---

# Personal access token from Asana account settings > Apps and integrations
# Generate at: app.asana.com → Settings → Personal access tokens
ASANA_TOKEN=0/1234567890abcdef123456789abcdef

# Workspace ID from Asana URL (app.asana.com/0/WORKSPACE_ID/...)
ASANA_WORKSPACE_ID=1234567890

# Optional: Project name template for advisor projects
# Default: "{advisor_name}_project"
# ASANA_PROJECT_TEMPLATE={advisor_name}_project

# --- OPTIONAL INTEGRATIONS (Not in this guide but available) ---

# Todoist integration (see .env.example for details)
# TODOIST_API_TOKEN=

# Notion integration
# NOTION_API_KEY=

# ============================================================================
# END INTEGRATION VARIABLES
# ============================================================================
```

### Turkish Terminology Reference

| English | Turkish | Context |
|---|---|---|
| Weather Advisor | Hava Tahmini | Daily weather briefing for Istanbul |
| Leadership Coach | Liderlik Koçu | Leadership and management insights |
| Kids Development | Çocuk Gelişim Danışmanı | Parenting and child development |
| Career & HR | İnsan Kaynakları ve Kariyer | Career growth and HR trends |
| Job Scout | İş Avcısı | Job opportunities in your field |
| Sector Intel | Sektör İstihbaratı | Industry-specific insights (banking/contact centers) |
| AI News | Yapay Zeka Haberleri | Latest AI news and breakthroughs |
| Free Certs | Ücretsiz Sertifika & Eğitim | Free courses and certifications |
| Banking/CC Projects | Banka & Çağrı Merkezi Proje Uz. | Banking and contact-center best practices |
| AI Mastery Coach | Yapay Zeka Ustalığı Koçu | AI skill development tracking |
| CX Research | Çağrı Merkezi & CX Araştırması | Customer experience and contact-center research |
| Daily Ops Briefing | Gün Başı Operasyon Brifingi | Morning operations summary (Gmail + Calendar) |
| Language Coach | Dil Koçu | Language learning and improvement |
| Anka Bridge | Anka Köprüsü | Generic HTTP connector to external systems |
| Innovation Lab | İnovasyon Laboratuvarı | Innovation and emerging technology ideas |
| Accountability Coach | Hesap Sorucu Koç | Daily task tracking and accountability |

---

## 5. Troubleshooting

### Slack Issues

#### Error: `webhook HTTP 401`
- **Cause:** Invalid or expired webhook URL
- **Fix:** Regenerate the webhook at [api.slack.com/apps](https://api.slack.com/apps) and update `.env`

#### Error: `webhook error: channel_not_found`
- **Cause:** Channel ID doesn't exist or bot is not in the channel
- **Fix:** Verify channel ID and ensure bot is added to the channel

#### Error: `chat.postMessage error: invalid_cursor`
- **Cause:** Bot token is invalid or revoked
- **Fix:** Regenerate the token at [api.slack.com/apps](https://api.slack.com/apps) → OAuth & Permissions

#### Messages not appearing but no errors
- **Cause:** Bot is not added to the channel
- **Fix:** Go to channel → Click name → Integrations → Apps → Add app → Select bot

#### Rate Limiting
- **Symptom:** Occasional `429` responses from Slack API
- **Fix:** Built-in retry logic handles this automatically; reduce advisor count or increase posting interval if persistent

### Asana Issues

#### Error: `ASANA_TOKEN not set`
- **Cause:** Missing environment variable
- **Fix:** Generate token at [asana.com](https://asana.com) → Settings → Personal access tokens
- **Verify:** `echo $ASANA_TOKEN` shows the token (no "0/" prefix needed in the environment, but it's harmless)

#### Error: `401 Unauthorized`
- **Cause:** Invalid or expired token
- **Fix:** Generate a new token and update `.env`

#### Error: `Workspace not found`
- **Cause:** Invalid workspace ID
- **Fix:** Go to [app.asana.com](https://app.asana.com), click workspace selector, verify ID in URL

#### Error: `Rate limit exceeded (429)`
- **Cause:** Too many API requests in a short time
- **Built-in fix:** Retry logic with exponential backoff (default: 3 retries, 1s base delay)
- **Workaround:** Reduce number of tasks created or spread requests over time

#### Tasks appear with wrong details
- **Cause:** Custom field mappings or project settings conflict
- **Fix:** Verify custom fields exist in Asana and are correctly mapped in code

### Google Drive Issues

#### Error: `No credentials found (run: python -m ai_assistant.integrations.google_auth)`
- **Cause:** Token file doesn't exist or credentials not configured
- **Fix:** 
  1. Run: `python -m src.ai_assistant.integrations.google_auth`
  2. Authorize in the browser window
  3. Token saved as `.google_token.json`

#### Error: `invalid_grant: Token has been revoked`
- **Cause:** Google revoked the token (e.g., after password change)
- **Fix:** Run `python -m src.ai_assistant.integrations.google_auth` again

#### Error: `notFound: File not found` or `File not found (404)`
- **Cause:** Folder ID doesn't exist or has been deleted
- **Fix:** Recreate the folder and update `GOOGLE_DRIVE_FOLDER_ID` in `.env`

#### Error: `Permission denied (403)`
- **Cause:** Google account doesn't have access to the folder
- **Fix:** 
  1. Go to [drive.google.com](https://drive.google.com)
  2. Verify folder exists and you can access it
  3. Share it with yourself if using a team account

#### Slow uploads or frequent `429` rate limit
- **Cause:** Google Drive API quota exceeded
- **Cause:** Too many large files uploaded simultaneously
- **Built-in fix:** Retry logic with exponential backoff
- **Workaround:** 
  - Reduce file size
  - Spread uploads over time
  - Request quota increase in Cloud Console if using heavily

#### Token refresh fails
- **Cause:** Refresh token expired (usually after 6 months of inactivity)
- **Cause:** `.google_token.json` deleted
- **Fix:** Run `python -m src.ai_assistant.integrations.google_auth` again

### GitHub Actions (CI/CD) Setup

If running in GitHub Actions, use **environment secrets** instead of `.env`:

1. Go to your repository → Settings → Secrets and variables → Actions
2. Create these secrets:
   - `SLACK_BOT_TOKEN` (or `SLACK_WEBHOOK_URL`)
   - `ASANA_TOKEN`
   - `ASANA_WORKSPACE_ID`
   - `GOOGLE_DRIVE_FOLDER_ID`
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REFRESH_TOKEN` (extract from `.google_token.json` after local auth)

3. In your workflow, load them:
   ```yaml
   - name: Run briefing
     env:
       SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
       ASANA_TOKEN: ${{ secrets.ASANA_TOKEN }}
       GOOGLE_CLIENT_ID: ${{ secrets.GOOGLE_CLIENT_ID }}
       GOOGLE_CLIENT_SECRET: ${{ secrets.GOOGLE_CLIENT_SECRET }}
       GOOGLE_REFRESH_TOKEN: ${{ secrets.GOOGLE_REFRESH_TOKEN }}
     run: python -m src.ai_assistant.briefing
   ```

### Graceful Degradation

All integrations are **optional** and fail gracefully:

- **Slack missing/fails:** Briefings still run, just skip Slack posting
- **Asana missing/fails:** Tasks aren't created, but advisors still generate reports
- **Google Drive missing/fails:** Reports aren't saved to Drive, but still available in the dashboard

The health check shows which services are available:

```bash
python -m src.ai_assistant.integrations
```

Output will show ✓ for working services and ✗ for missing credentials.

### Network & Proxy Issues

If behind a corporate proxy:

1. Set environment variables:
   ```bash
   export HTTP_PROXY=http://proxy.company.com:8080
   export HTTPS_PROXY=http://proxy.company.com:8080
   export NO_PROXY=localhost,127.0.0.1
   ```

2. Or configure in `.env`:
   ```bash
   # These are read by the integration modules
   HTTP_PROXY=http://proxy.company.com:8080
   HTTPS_PROXY=http://proxy.company.com:8080
   ```

### Common Setup Mistakes

| Mistake | Solution |
|---|---|
| Using channel name instead of ID | Use channel IDs (e.g., `C0123456789`), not `#channel-name` |
| Extra spaces in tokens/IDs | Copy carefully; even trailing spaces break authentication |
| Token with wrong permissions | Regenerate with correct scopes (Slack: `chat:write`; Asana: `tasks`, `projects`) |
| Folder ID instead of file ID | Google Drive: folder IDs work for `GOOGLE_DRIVE_FOLDER_ID`, not file IDs |
| .env not loaded in CI/CD | Use GitHub Secrets instead; CI runners don't read .env files |
| Mixing webhook and bot token | Choose ONE method per Slack workspace (bot token recommended) |

### Debug Mode

Enable debug logging to see detailed integration activity:

```bash
python -c "import logging; logging.basicConfig(level=logging.DEBUG); from src.ai_assistant.integrations import asana, slack_channels; print('Debug enabled')"
```

Or set in code:
```python
import logging
logging.getLogger("ai_assistant.integrations").setLevel(logging.DEBUG)
```

---

## Summary

You now have a complete, production-ready setup for Slack, Asana, and Google Drive. Here's a quick checklist:

**Slack:**
- [ ] Created workspace and channels (or using existing)
- [ ] Generated bot token or webhook URL
- [ ] Configured `SLACK_BOT_TOKEN` / `SLACK_WEBHOOK_URL` in `.env`
- [ ] Added channel IDs for advisors (or using `SLACK_MAIN_CHANNEL` fallback)
- [ ] Tested with `python -m src.ai_assistant.integrations.slack_channels`

**Asana:**
- [ ] Created account and workspace
- [ ] Generated personal access token
- [ ] Created main project
- [ ] Configured `ASANA_TOKEN` and `ASANA_WORKSPACE_ID` in `.env`
- [ ] Tested with `python -c "from src.ai_assistant.integrations.asana import AsanaClient; ..."`

**Google Drive:**
- [ ] Created Cloud project and enabled Drive API
- [ ] Generated OAuth 2.0 credentials (Desktop app)
- [ ] Ran `python -m src.ai_assistant.integrations.google_auth` to authorize
- [ ] Created reports folder and noted folder ID
- [ ] Configured `GOOGLE_DRIVE_FOLDER_ID` and credentials in `.env`
- [ ] Tested with `python -c "from src.ai_assistant.integrations.google_drive import DriveClient; ..."`

For questions or issues, see the **Troubleshooting** section above, or open an issue on GitHub.

**Enjoy your AI Executive Assistant! 🚀**
