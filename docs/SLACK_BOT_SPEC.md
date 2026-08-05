# Slack Bot Specification - Daily Workflows & Interactive Features
## Real-time Platform Intelligence & Automated Engagement

**Version:** 1.0  
**Date:** August 2026  
**Framework:** Slack Bolt for Python  
**Integration:** Cloud Run + Slack App  

---

## Overview

The Slack bot serves as Burak's "AI executive assistant" with 7 daily touchpoints, providing summarized insights, content approval workflows, and opportunity notifications without requiring dashboard access.

**Philosophy:** 
- Minimize context switching
- Provide actionable intelligence
- Make decisions in Slack (approve, send, schedule)
- Use Block Kit for rich, interactive UX

---

## Daily Workflow Schedule

### 7:00 AM - Morning Brief

**Trigger:** Scheduled Slack message (timezone-aware)  
**Channel:** Direct message to Burak  
**Message Type:** Block Kit (rich formatting)

**Structure:**
```
┌─────────────────────────────────────┐
│  ☀️ MORNING BRIEF - August 5, 2026  │
├─────────────────────────────────────┤
│                                     │
│  📊 PERFORMANCE SUMMARY             │
│  ├─ Yesterday: 245 likes, 32 cmt    │
│  ├─ This week: 1,240 total eng.     │
│  └─ Engagement rate: 3.8% ↑ 12%    │
│                                     │
│  🌐 NETWORK ACTIVITY                │
│  ├─ 3 job changes detected          │
│  ├─ 1 high-value reconnect          │
│  └─ 5 responses to recent posts     │
│                                     │
│  🎤 SPEAKING PIPELINE               │
│  ├─ 2 new high-fit opportunities    │
│  ├─ 1 deadline this week            │
│  └─ 2 awaiting responses            │
│                                     │
│  📰 INDUSTRY TRENDS                 │
│  ├─ McKinsey: Turkish logistics     │
│  ├─ BCG: Supply chain resilience    │
│  └─ Deloitte: Digital ops leaders   │
│                                     │
├─────────────────────────────────────┤
│  [Generate Content] [View Full]     │
│  [Opportunities]    [Settings]      │
└─────────────────────────────────────┘
```

**Block Kit JSON:**
```json
{
  "type": "home",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "☀️  Morning Brief - August 5, 2026",
        "emoji": true
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*📊 PERFORMANCE SUMMARY*\n• Yesterday: 245 likes, 32 comments\n• This week: 1,240 total engagement\n• Engagement rate: 3.8% ↑ 12%"
      }
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "Generate Content"
          },
          "action_id": "morning_generate",
          "style": "primary"
        },
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "View Full Report"
          },
          "action_id": "morning_report"
        }
      ]
    }
  ]
}
```

**User Actions:**
- `[Generate Content]` → Opens modal for quick generation
- `[View Full Report]` → Sends detailed analytics thread
- Auto-updates at 8:00 AM if not viewed (prevents stale info)

**Personalization:**
- Timezone-aware scheduling (Europe/Istanbul)
- Language: Turkish + English summaries
- Data from previous 24 hours

---

### 12:00 PM - Midday Pulse

**Trigger:** Scheduled (if morning brief was viewed)  
**Type:** Thread reply to morning brief  
**Frequency:** Only if morning brief viewed (don't spam)

**Structure:**
```
┌─────────────────────────────────────┐
│  📈 MIDDAY PULSE - 12:00 PM        │
├─────────────────────────────────────┤
│                                     │
│  LIVE ENGAGEMENT                    │
│  ├─ Supply Chain post: 45 → 89 ♥   │
│  ├─ Twitter thread: 23 retweets     │
│  └─ LinkedIn article: 12% click CTR │
│                                     │
│  💬 ENGAGEMENT SPIKE                │
│  └─ "What's your approach to..."    │
│    Answer suggestion:               │
│    "Based on 15 years experience..." │
│                                     │
│  🎯 ACTION ITEMS (2)                │
│  ├─ Approve pending content (3min)  │
│  └─ Respond to Ahmed's message      │
│                                     │
├─────────────────────────────────────┤
│  [View Content]  [Approve]  [Reply] │
└─────────────────────────────────────┘
```

**Features:**
- Real-time engagement updates
- Suggested responses to comments
- Time-sensitive action items
- Quick approval for pending content

---

### 5:00 PM - Speaking Opportunity Alert

**Trigger:** When high-fit speaking opportunity detected  
**Type:** Direct message (urgent)  
**Frequency:** 0-3 per week (high-quality filtering)

**Structure:**
```
┌─────────────────────────────────────┐
│  🎤 SPEAKING OPPORTUNITY ALERT      │
├─────────────────────────────────────┤
│                                     │
│  Tech Leaders Turkey Conference     │
│  📅 Sept 15, 2026 | Istanbul        │
│  👥 2,000 executives                │
│  💰 $5,000 speaking fee             │
│                                     │
│  ✨ FIT SCORE: 9/10                 │
│  Why: Supply chain + ops focus,     │
│  large Turkish audience,            │
│  premium event                      │
│                                     │
│  ⏰ DEADLINE: August 15 (10 days)   │
│                                     │
│  Topics: Operations, Digital        │
│  Transform., Supply Chain           │
│                                     │
├─────────────────────────────────────┤
│  [Generate Pitch] [Add Calendar]    │
│  [Save for Later] [Not Relevant]    │
└─────────────────────────────────────┘
```

**User Actions:**
- `[Generate Pitch]` → Auto-generates email to organizer
- `[Add Calendar]` → Syncs to Calendly/Google Calendar
- `[Save for Later]` → Saves to speaking pipeline
- `[Not Relevant]` → Trains ML fit algorithm

**Smart Filtering:**
- Only show opportunities with fit score ≥ 7
- Avoid duplicate events
- Timezone consideration (prefer accessible locations)
- Regional preference (Turkey > MENA > Europe > Global)

---

### 8:00 PM - Evening Summary

**Trigger:** Scheduled  
**Type:** Direct message  
**Includes:** Tomorrow preview + action items

**Structure:**
```
┌─────────────────────────────────────┐
│  🌙 EVENING SUMMARY - August 5      │
├─────────────────────────────────────┤
│                                     │
│  TODAY'S RESULTS                    │
│  ✓ 1 post published (Supply Chain)  │
│  ✓ 2 network connections approved   │
│  ✓ 1 speaking pitch sent             │
│  • 3 articles to review tomorrow     │
│                                     │
│  📅 TOMORROW'S PREVIEW               │
│  ├─ 2 posts ready to approve         │
│  ├─ 1 high-fit opportunity           │
│  ├─ Industry report scan results     │
│  └─ Network: 2 reconnect reminders   │
│                                     │
│  💡 RECOMMENDATION                  │
│  Publish supply chain content at     │
│  6:00 PM tomorrow (highest engagement│
│  time based on your audience)        │
│                                     │
├─────────────────────────────────────┤
│  [Schedule Week]  [Detailed Report]  │
└─────────────────────────────────────┘
```

**Intelligence:**
- Summary of day's activities
- Tomorrow's predicted workload
- Recommended actions
- Optimal posting times
- Quick access to schedule week's content

---

## Interactive Workflows

### Workflow 1: Content Generation & Approval

**Trigger:** User clicks `[Generate Content]` or types `/generate`

**Flow:**

```
1. MODAL - Quick Generation
   ┌──────────────────────────┐
   │ Generate Content         │
   ├──────────────────────────┤
   │ Topic: [text input]      │
   │ Language: [dropdown]     │
   │ Tone: [buttons]          │
   │         [Generate]       │
   └──────────────────────────┘

2. API CALL
   POST /api/content/generate
   
3. DISPLAY VARIATIONS (thread)
   [VARIATION 1: LinkedIn Post]
   └─ 345 chars | Est. engagement: 3.2%
      [✅ Approve] [✏️ Edit] [🔄 Regen]
   
   [VARIATION 2: Twitter Thread]
   └─ 8 tweets | Est. engagement: 2.8%
      [✅ Approve] [✏️ Edit] [🔄 Regen]
   
   [VARIATION 3: Short Article]
   └─ 850 words | Est. engagement: 4.1%
      [✅ Approve] [✏️ Edit] [🔄 Regen]

4. USER SELECTS ACTION
   
   IF [✅ Approve]:
   └─ Show scheduling options
      When? [Now] [Optimal] [Schedule]
      Platform? [LinkedIn] [Twitter] [Both]
      [Confirm & Publish]
   
   IF [✏️ Edit]:
   └─ Open Google Doc (shared)
   │  User edits text
   │  On save → Sync back to Slack
   └─ Return to approval message
   
   IF [🔄 Regen]:
   └─ Generate new variations
      Show in thread below

5. CONFIRMATION
   "✓ Posted to LinkedIn at 6:00 PM
    → LinkedIn post ID: 7123456789
    → View on LinkedIn: [Link]"
```

**Modal - Block Kit:**
```json
{
  "type": "modal",
  "callback_id": "generate_content_modal",
  "title": {
    "type": "plain_text",
    "text": "Generate Content"
  },
  "blocks": [
    {
      "type": "input",
      "block_id": "topic_input",
      "label": {
        "type": "plain_text",
        "text": "What's your topic?"
      },
      "element": {
        "type": "plain_text_input",
        "action_id": "topic",
        "placeholder": {
          "type": "plain_text",
          "text": "e.g., Turkish supply chain challenges"
        }
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Select tone:*"
      },
      "accessory": {
        "type": "radio_buttons",
        "action_id": "tone_select",
        "options": [
          {
            "value": "executive",
            "text": { "type": "plain_text", "text": "Executive" }
          },
          {
            "value": "provocative",
            "text": { "type": "plain_text", "text": "Provocative" }
          }
        ]
      }
    }
  ],
  "submit": {
    "type": "plain_text",
    "text": "Generate"
  }
}
```

---

### Workflow 2: Network Outreach

**Trigger:** Automatic (morning brief) or manual search

**Flow:**

```
1. MORNING BRIEF NOTIFICATION
   "Ahmed changed roles: VP → CTO at TechCorp"
   
   [Send Congratulations] [Request Interview] [Collaborate]

2. USER SELECTS ACTION
   POST /api/network/generate-outreach
   
3. DISPLAY MESSAGE VARIANTS (thread)
   "Here are 3 ways to reach out:"
   
   VARIANT 1 (Warm):
   "Ahmed, congratulations on your new role 
    as CTO at TechCorp! I'd love to hear 
    about your transformation plans..."
   [👍 Use This] [✏️ Edit] [Next]
   
   VARIANT 2 (Casual):
   "Congrats Ahmed! CTO at TechCorp - big 
    move. Let's grab coffee and catch up..."
   [👍 Use This] [✏️ Edit] [Next]

4. USER SELECTS VARIANT
   [👍 Use This]
   
5. PREVIEW & CONFIRM
   "Ready to send via LinkedIn?"
   [Send]  [Edit]  [Cancel]
   
6. CONFIRMATION
   "✓ Message sent to Ahmed Yildirim
    Follow-up in 2 weeks if no response"
```

**Key Features:**
- AI-generated message variants
- Multiple tone options
- One-click sending
- Automatic follow-up tracking
- Integration with LinkedIn

---

### Workflow 3: Speaking Opportunity Management

**Trigger:** Automatic detection or manual review

**Flow:**

```
1. OPPORTUNITY ALERT
   "🎤 Tech Leaders Turkey Conference
    Fit Score: 9/10
    Deadline: Aug 15 (10 days)"

2. USER CLICKS [Generate Pitch]
   POST /api/speaking/{id}/generate-pitch
   
3. DISPLAY PITCH PREVIEW
   "Here's your personalized pitch:"
   
   📧 SUBJECT:
   "Speaking Proposal: Operations Excellence..."
   
   BODY:
   "Dear Mehmet,
    I'm excited to propose a speaking session..."
   
   [💾 Save Draft] [✉️ Send] [✏️ Edit] [Cancel]

4. USER REVIEWS & SENDS
   POST /api/speaking/{id}/send-pitch
   
5. CONFIRMATION
   "✓ Pitch sent to speakers@techleadersturkey.com
    Following up August 19 if no response
    📅 Add to calendar"
    
6. TRACKING
   Automatic reminders:
   - 5 days before deadline
   - Follow-up if no response (2 weeks)
   - Confirmation if accepted
```

---

### Workflow 4: Industry Report Commentary

**Trigger:** Daily report scan (morning brief link) or manual command

**Flow:**

```
1. REPORT ALERT
   "📰 New McKinsey Report: Turkish Logistics"
   [Generate Commentary]

2. USER CLICKS
   POST /api/reports/{id}/generate-commentary

3. DISPLAY OPTIONS
   Which formats do you want?
   [✓] LinkedIn Post  (850 words)
   [✓] Twitter Thread (8 tweets)
   [ ] Full Article   (2000 words)
   [Generate] [Skip]

4. DISPLAY RESULTS (thread)
   
   📧 LINKEDIN VERSION:
   "The McKinsey report on Turkish logistics 
    just dropped, and it confirms what many 
    of us have observed..."
   [👍 Use] [✏️ Edit] [Schedule] [Archive]
   
   🐦 TWITTER VERSION:
   "1/ McKinsey's latest on Turkish logistics 
    confirms major trends..."
   [👍 Use] [✏️ Edit] [Schedule] [Archive]

5. USER SELECTS ACTION
   [👍 Use] → Publish or schedule
   [✏️ Edit] → Opens Google Doc
   [Schedule] → Pick date/time

6. CONFIRMATION
   "✓ Insights published across platforms"
```

---

## Message Types & Formatting

### Block Kit Components

#### 1. Performance Card
```json
{
  "type": "section",
  "fields": [
    {
      "type": "mrkdwn",
      "text": "*Engagement Rate*\n3.8%\n↑ 12% vs last week"
    },
    {
      "type": "mrkdwn",
      "text": "*Followers This Week*\n+45\n↑ 2.5x vs last week"
    }
  ]
}
```

#### 2. Action Buttons
```json
{
  "type": "actions",
  "elements": [
    {
      "type": "button",
      "text": { "type": "plain_text", "text": "Approve" },
      "action_id": "approve_action",
      "style": "primary",
      "value": "content-uuid"
    },
    {
      "type": "button",
      "text": { "type": "plain_text", "text": "Decline" },
      "action_id": "decline_action",
      "style": "danger"
    }
  ]
}
```

#### 3. Context Blocks (gray background)
```json
{
  "type": "context",
  "elements": [
    {
      "type": "mrkdwn",
      "text": "Posted 2 hours ago • 45 likes • 8 comments"
    }
  ]
}
```

---

## Notification Strategy

### Notification Types

| Type | Frequency | Channel | Priority |
|------|-----------|---------|----------|
| Morning Brief | Daily, 7 AM | DM | Normal |
| Midday Pulse | Daily (if AM viewed) | Thread | Normal |
| Speaking Alert | 0-3x/week | DM | High |
| Network Alert | Daily | DM | Normal |
| Evening Summary | Daily, 8 PM | DM | Low |
| Urgent Deadline | On trigger | DM + @mention | Critical |

### Do Not Disturb

- Respect DND hours (default: 9 PM - 7 AM)
- Skip non-critical messages if 3+ already sent today
- Batch low-priority notifications

---

## Settings & Customization

**Accessible via:** `/settings` or menu button

```
┌─────────────────────────────────────┐
│  ⚙️  PREFERENCES                   │
├─────────────────────────────────────┤
│                                     │
│  NOTIFICATIONS                      │
│  ☑ Morning Brief (7:00 AM)         │
│  ☑ Midday Pulse (12:00 PM)         │
│  ☑ Speaking Alerts (Real-time)     │
│  ☑ Evening Summary (8:00 PM)       │
│                                     │
│  LANGUAGE                           │
│  ⦿ English  ○ Turkish  ○ Both       │
│                                     │
│  NETWORK ALERTS                     │
│  Notify on: ☑ Job changes          │
│             ☑ Promotions           │
│             ☑ Reconnect opps       │
│             ☑ Milestones           │
│                                     │
│  SPEAKING OPPORTUNITIES             │
│  Min fit score: ___7___  (0-10)     │
│  Regions: ☑ Turkey ☑ MENA          │
│           ☑ Europe ☑ Global        │
│                                     │
│  INDUSTRY REPORTS                   │
│  Scan frequency: ○ Daily ○ Weekly   │
│  Min relevance: ___0.6___ (0-1)     │
│                                     │
│  Do Not Disturb: 9:00 PM - 7:00 AM  │
│                                     │
│         [Save]  [Reset Defaults]    │
└─────────────────────────────────────┘
```

---

## Technical Implementation

### Event Handling

```python
from slack_bolt import App

app = App(token=SLACK_BOT_TOKEN, signing_secret=SIGNING_SECRET)

# Morning brief scheduled
@app.message("good morning")
def morning_brief(message, say):
    blocks = build_morning_brief()
    say(blocks=blocks)

# Button clicks
@app.action("approve_action")
def handle_approve(ack, body, respond):
    ack()
    content_id = body["actions"][0]["value"]
    approve_content(content_id)
    respond("✓ Content published!")

# Modal submission
@app.view("generate_content_modal")
def handle_modal(ack, body, view, client):
    ack()
    topic = view["state"]["values"]["topic_input"]["topic"]["value"]
    generate_and_display(topic)
```

### State Management

**Store in PostgreSQL `slack_state` table:**
```python
{
  "user_id": "uuid",
  "conversation_state": {
    "current_workflow": "content_approval",
    "content_id": "uuid",
    "last_step": "variations_displayed"
  },
  "context": {
    "approval_pending": true,
    "edit_doc_url": "https://..."
  }
}
```

### Rate Limiting

- Max 100 messages per hour per user
- Max 5 buttons per message
- Max 10 options in dropdown
- Queue long-running tasks (Celery)

---

## Testing Strategy

### Unit Tests
```python
def test_morning_brief_formatting():
    """Ensure morning brief has required blocks"""
    blocks = build_morning_brief()
    assert len(blocks) > 0
    assert any(b["type"] == "header" for b in blocks)

def test_opportunity_fit_score():
    """Fit score between 0-10"""
    score = calculate_fit_score(event)
    assert 0 <= score <= 10
```

### Integration Tests
```python
def test_content_approval_flow():
    """End-to-end: Generate → Approve → Publish"""
    # Generate content
    variations = api_generate_content(topic="test")
    
    # Simulate approval button click
    response = simulate_slack_action("approve", variations[0]["id"])
    
    # Verify published
    assert response["success"] == True
    assert response["published_at"] is not None
```

### Manual Testing
- Test with real Slack workspace
- Verify timezone accuracy
- Test all button actions
- Verify message formatting on mobile

---

## Monitoring & Metrics

**Track:**
- Message delivery rate
- Button click rate
- User response time (avg time to take action)
- Most used workflows
- Error rates per action

**Alerts:**
- Bot unavailable for >5 min
- Gemini API failure
- Slack API errors
- Database connection issues

---

**Document Control**
- Version: 1.0
- Status: FINAL
- Last Updated: August 2026
