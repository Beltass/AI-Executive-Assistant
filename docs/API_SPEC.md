# API Specification - Content Creation Platform
## RESTful API Endpoints & Integration Guide

**Version:** 1.0  
**Date:** August 2026  
**Base URL:** `https://api.content-platform.com/api`  
**Authentication:** JWT Bearer Token (Authorization header)  

---

## API Overview

### Authentication

All endpoints (except `/auth/login` and `/health`) require:

```http
Authorization: Bearer {jwt_token}
```

**Token Generation:**
```http
POST /auth/login
Content-Type: application/json

{
  "google_auth_code": "4/0AdY_f..."
}

Response (200):
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "refresh_token": "1//09a...",
  "expires_in": 3600,
  "token_type": "Bearer"
}
```

### Response Format

All responses use JSON with consistent structure:

**Success (2xx):**
```json
{
  "success": true,
  "data": { ... },
  "meta": {
    "timestamp": "2026-08-05T10:00:00Z",
    "request_id": "uuid"
  }
}
```

**Error (4xx, 5xx):**
```json
{
  "success": false,
  "error": {
    "code": "INVALID_INPUT",
    "message": "Topic is required",
    "details": {
      "field": "topic",
      "constraint": "required"
    }
  },
  "meta": {
    "timestamp": "2026-08-05T10:00:00Z",
    "request_id": "uuid"
  }
}
```

### Rate Limiting

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1691222400
```

---

## Content Endpoints

### 1. Generate Content

**Endpoint:** `POST /content/generate`

**Description:** Generate 5 content variations using Gemini AI with dual-language support.

**Request:**
```json
{
  "topic": "Turkish supply chain challenges in 2026",
  "primary_platform": "linkedin",
  "language": "both",
  "tone": "executive",
  "content_type": "post",
  "template_id": "uuid (optional)",
  "custom_context": "Focus on digital transformation angle"
}
```

**Parameters:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| topic | string | Yes | Content topic (max 255 chars) |
| primary_platform | enum | Yes | linkedin, twitter, threads, instagram, email |
| language | enum | Yes | en, tr, both |
| tone | enum | Yes | executive, casual, educational, inspirational, critical |
| content_type | enum | Yes | post, article, thread, commentary, email |
| template_id | UUID | No | Use specific template for generation |
| custom_context | string | No | Additional context/guidelines |

**Response (202 Accepted):**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "topic": "Turkish supply chain challenges in 2026",
    "variations": [
      {
        "id": "uuid",
        "variation_type": "linkedin_post",
        "platform": "linkedin",
        "text": "The Turkish supply chain landscape has transformed dramatically over the past 5 years...",
        "tone": "executive",
        "length": "medium",
        "hashtags": ["#TurkishBusiness", "#SupplyChain", "#OperationsTalk"],
        "optimal_posting_time": "2026-08-05T18:00:00Z",
        "engagement_estimate": 3.2,
        "character_count": 280,
        "word_count": 45
      },
      {
        "id": "uuid",
        "variation_type": "twitter_thread",
        "platform": "twitter",
        "text": "1/ Turkish supply chains that survived 2020-2026? 100% of them got more flexible, more local, more resilient.",
        "tone": "critical",
        "length": "short",
        "hashtags": ["#Turkey", "#Supply", "#Ops"],
        "optimal_posting_time": "2026-08-05T13:30:00Z",
        "engagement_estimate": 2.8
      }
    ],
    "generation_cost": {
      "tokens_used": 2450,
      "estimated_cost_usd": 0.18,
      "cache_hit": false
    },
    "created_at": "2026-08-05T10:00:00Z"
  }
}
```

**Status Codes:**
- `202 Accepted` - Content generation queued
- `400 Bad Request` - Invalid parameters
- `401 Unauthorized` - Invalid/expired token
- `429 Too Many Requests` - Rate limit exceeded

**Example (cURL):**
```bash
curl -X POST "https://api.content-platform.com/api/content/generate" \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Turkish supply chain challenges",
    "primary_platform": "linkedin",
    "language": "both",
    "tone": "executive",
    "content_type": "post"
  }'
```

---

### 2. List Content

**Endpoint:** `GET /content`

**Description:** List user's content with filtering and pagination.

**Query Parameters:**
```
?status=draft&platform=linkedin&limit=20&offset=0&sort=-created_at
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| status | enum | all | draft, scheduled, published, archived |
| platform | enum | all | linkedin, twitter, threads, instagram |
| language | enum | all | en, tr, both |
| content_type | enum | all | post, article, thread, commentary |
| search | string | - | Full-text search in title/topic |
| limit | int | 20 | Max 100 |
| offset | int | 0 | For pagination |
| sort | string | -created_at | created_at, published_at, engagement_rate |

**Response (200):**
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "uuid",
        "title": "Turkish Supply Chain Resilience",
        "topic": "Supply chain",
        "content_type": "post",
        "status": "published",
        "language": "both",
        "created_at": "2026-08-04T14:00:00Z",
        "published_at": "2026-08-05T18:00:00Z",
        "engagement_metrics": {
          "likes": 145,
          "comments": 23,
          "shares": 8,
          "views": 3500,
          "engagement_rate": 4.8
        }
      }
    ],
    "pagination": {
      "total": 156,
      "limit": 20,
      "offset": 0,
      "has_more": true
    }
  }
}
```

---

### 3. Get Content Details

**Endpoint:** `GET /content/{id}`

**Description:** Get single content with all variations and analytics.

**Response (200):**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "title": "Turkish Supply Chain Resilience",
    "topic": "Supply chain",
    "status": "published",
    "variations": [
      {
        "id": "uuid",
        "platform": "linkedin",
        "text": "...",
        "engagement": { "likes": 145, "comments": 23 }
      }
    ],
    "analytics": {
      "total_engagement": 3500,
      "engagement_rate": 4.8,
      "top_platform": "linkedin"
    }
  }
}
```

---

### 4. Update Content

**Endpoint:** `PUT /content/{id}`

**Description:** Update content draft (cannot modify published content).

**Request:**
```json
{
  "title": "Updated title",
  "topic": "Updated topic"
}
```

**Response (200):** Updated content object

**Restrictions:**
- Can only edit `draft` status content
- Cannot modify published content (create new version instead)

---

### 5. Publish Content

**Endpoint:** `POST /content/{id}/publish`

**Description:** Publish content immediately or schedule for later.

**Request:**
```json
{
  "variation_id": "uuid",
  "platforms": ["linkedin", "twitter"],
  "schedule_time": "2026-08-05T18:00:00Z",
  "auto_schedule": false
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "id": "uuid",
    "status": "published",
    "published_at": "2026-08-05T18:00:00Z",
    "scheduled_posts": [
      {
        "id": "uuid",
        "platform": "linkedin",
        "scheduled_time": "2026-08-05T18:00:00Z",
        "platform_post_id": "7123456789"
      }
    ]
  }
}
```

---

### 6. Delete Content

**Endpoint:** `DELETE /content/{id}`

**Description:** Soft delete content (can be restored).

**Response (204 No Content)**

---

## Templates Endpoints

### 1. List Templates

**Endpoint:** `GET /templates`

**Query Parameters:**
```
?category=industry_insights&language=tr&is_public=true&limit=50
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "uuid",
        "name": "Industry Insights Template",
        "category": "industry_insights",
        "language": "tr",
        "framework": "Analysis + Perspective + Implications",
        "example_output": "...",
        "usage_count": 42
      }
    ]
  }
}
```

---

### 2. Create Custom Template

**Endpoint:** `POST /templates`

**Request:**
```json
{
  "name": "My Custom Template",
  "category": "provocative",
  "language": "both",
  "framework": "Hook + Insight + Call-to-Action",
  "system_prompt": "You are a controversial thought leader...",
  "example_output": "..."
}
```

**Response (201 Created):** Created template object

---

## Network Intelligence Endpoints

### 1. Get Network Opportunities

**Endpoint:** `GET /network/opportunities`

**Query Parameters:**
```
?limit=20&priority_min=5&days=7
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "opportunities": [
      {
        "id": "uuid",
        "type": "job_change",
        "contact_id": "UUID",
        "name": "Ahmed Yildirim",
        "previous_title": "VP Engineering",
        "new_title": "CTO",
        "new_company": "TechCorp Istanbul",
        "date": "2026-08-03",
        "priority_score": 8,
        "relationship_strength": 0.8,
        "last_contacted": "2026-06-15",
        "suggested_action": "Send congratulations message"
      },
      {
        "type": "promotion",
        "contact_id": "UUID",
        "name": "Fatima Kaya",
        "new_title": "Chief Operations Officer",
        "company": "Global Tech",
        "date": "2026-08-02",
        "priority_score": 7
      }
    ],
    "summary": {
      "total_opportunities": 12,
      "high_priority": 3,
      "this_week": 5
    }
  }
}
```

**Opportunity Types:**
- `job_change` - Moved to new company
- `promotion` - Promoted in current role
- `relocation` - Moved to different location
- `milestone` - Work anniversary, achievement
- `reconnect` - Valuable connection, haven't contacted in 6+ months

---

### 2. Generate Outreach Message

**Endpoint:** `POST /network/generate-outreach`

**Request:**
```json
{
  "contact_id": "UUID",
  "type": "congratulations",
  "context": "Recently promoted to CTO at TechCorp"
}
```

**Outreach Types:**
- `congratulations` - Congratulate on achievement
- `interview_request` - Request to discuss opportunities
- `collaborate` - Suggest collaboration
- `reconnect` - General reconnection message

**Response (200):**
```json
{
  "success": true,
  "data": {
    "contact_name": "Ahmed Yildirim",
    "variants": [
      {
        "id": "uuid",
        "text": "Ahmed, congratulations on your new role as CTO at TechCorp! I'd love to hear about your transformation plans...",
        "tone": "warm",
        "platform": "linkedin",
        "estimated_response_rate": 0.35
      },
      {
        "id": "uuid",
        "text": "Congrats Ahmed! CTO at TechCorp - big move. Let's grab coffee and catch up on what you're building.",
        "tone": "casual",
        "platform": "linkedin",
        "estimated_response_rate": 0.28
      }
    ]
  }
}
```

---

### 3. Send Outreach Message

**Endpoint:** `POST /network/send-outreach`

**Request:**
```json
{
  "contact_id": "UUID",
  "message_variant_id": "UUID",
  "platform": "linkedin"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "id": "UUID",
    "status": "sent",
    "sent_at": "2026-08-05T10:15:00Z",
    "contact_name": "Ahmed Yildirim",
    "next_followup_date": "2026-08-19"
  }
}
```

---

### 4. Sync LinkedIn Network

**Endpoint:** `POST /network/sync-linkedin`

**Description:** Trigger full LinkedIn network sync (rate-limited, max 1x/day).

**Response (202 Accepted):**
```json
{
  "success": true,
  "data": {
    "job_id": "UUID",
    "status": "processing",
    "message": "Syncing your LinkedIn network. This typically takes 2-5 minutes."
  }
}
```

**Poll Job Status:**
```http
GET /network/sync-status/{job_id}

Response (200):
{
  "success": true,
  "data": {
    "status": "completed",
    "results": {
      "synced_connections": 2000,
      "new_changes_detected": 45,
      "opportunities_identified": 12,
      "completed_at": "2026-08-05T10:15:00Z"
    }
  }
}
```

---

### 5. Get Network Insights

**Endpoint:** `GET /network/insights`

**Description:** Analytics on your network and engagement patterns.

**Response (200):**
```json
{
  "success": true,
  "data": {
    "network_size": 2043,
    "network_growth": {
      "this_month": 45,
      "this_quarter": 128,
      "this_year": 312
    },
    "engagement_patterns": {
      "avg_response_rate": 0.28,
      "avg_response_time_hours": 24,
      "top_engagement_day": "Tuesday",
      "top_engagement_time": "14:00-16:00"
    },
    "valuable_connections": {
      "total": 145,
      "high_engagement": 23,
      "potential_leads": 8,
      "influencers": 5
    },
    "recommendations": [
      "Reconnect with 12 valuable connections not contacted in 6+ months",
      "Ahmed's promotion at TechCorp may lead to consulting opportunity"
    ]
  }
}
```

---

## Speaking Opportunities Endpoints

### 1. Get Speaking Opportunities

**Endpoint:** `GET /speaking/opportunities`

**Query Parameters:**
```
?status=detected&fit_score_min=7&region=turkey&limit=20
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "opportunities": [
      {
        "id": "UUID",
        "conference_name": "Tech Leaders Turkey Conference 2026",
        "event_date": "2026-09-15",
        "submission_deadline": "2026-08-15",
        "event_url": "https://techleadersturkey.com",
        "topics": ["Operations", "Digital Transformation", "Supply Chain"],
        "audience_type": "corporate",
        "audience_size": 2000,
        "geographic_location": "Istanbul, Turkey",
        "region": "turkey",
        "fit_score": 9,
        "fit_score_reason": "High alignment with ops expertise, strong Turkish market focus, large audience",
        "status": "detected",
        "speaking_fee": 5000,
        "travel_required": false,
        "organizer_email": "speakers@techleadersturkey.com"
      }
    ],
    "summary": {
      "total_detected": 47,
      "high_fit": 8,
      "with_fees": 12,
      "deadline_this_month": 3
    }
  }
}
```

**Statuses:**
- `detected` - Automatically found, not yet submitted
- `saved` - Saved for later review
- `submitted` - Pitch sent
- `accepted` - Confirmed speaking slot
- `completed` - Event finished

---

### 2. Get Opportunity Details

**Endpoint:** `GET /speaking/{id}`

**Response (200):**
```json
{
  "success": true,
  "data": {
    "id": "UUID",
    "conference_name": "Tech Leaders Turkey Conference 2026",
    "detailed_description": "...",
    "organizer": {
      "name": "Mehmet Aslan",
      "email": "mehmet@techleadersturkey.com",
      "phone": "+90 212 XXX XXXX",
      "linkedin": "..."
    },
    "full_details": "...",
    "similar_past_events": [
      {
        "name": "TechTurkey 2025",
        "attendance": 1800,
        "speaker_reviews": 4.8
      }
    ]
  }
}
```

---

### 3. Generate Speaking Pitch

**Endpoint:** `POST /speaking/{id}/generate-pitch`

**Description:** Auto-generate personalized pitch email for event organizer.

**Request (optional):**
```json
{
  "custom_focus": "Operations transformation in Turkish manufacturing"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "pitch_email": {
      "subject": "Speaking Proposal: Operations Excellence in Digital Transformation",
      "body": "Dear Mehmet,\n\nI'm excited to propose a speaking session for the Tech Leaders Turkey Conference 2026...",
      "speaker_bio": "Burak Eltas is an Operations Director with 15+ years of experience in business transformation...",
      "talk_title": "From Chaos to Excellence: Operations Transformation in Digital Age",
      "talk_description": "A strategic framework for redesigning operations to deliver business impact in the era of digital disruption...",
      "estimated_duration": "45 minutes"
    },
    "attachments": [
      {
        "type": "speaker_photo",
        "url": "..."
      },
      {
        "type": "past_speaking_highlights",
        "url": "..."
      }
    ]
  }
}
```

---

### 4. Send Speaking Pitch

**Endpoint:** `POST /speaking/{id}/send-pitch`

**Request:**
```json
{
  "email_body": "...",
  "include_attachments": true
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "id": "UUID",
    "status": "submitted",
    "pitch_sent_date": "2026-08-05T10:30:00Z",
    "follow_up_date": "2026-08-19",
    "message": "Pitch sent to Mehmet Aslan. Set reminder to follow up in 2 weeks if no response."
  }
}
```

---

### 5. Update Opportunity Status

**Endpoint:** `PUT /speaking/{id}/status`

**Request:**
```json
{
  "status": "accepted",
  "notes": "Confirmed for September 15, speaking at 11:00 AM",
  "speaking_fee": 5000,
  "confirmed_at": "2026-08-10T14:00:00Z"
}
```

**Response (200):** Updated opportunity object

---

### 6. Speaking Analytics

**Endpoint:** `GET /speaking/analytics`

**Response (200):**
```json
{
  "success": true,
  "data": {
    "pipeline": {
      "detected": 47,
      "saved": 12,
      "submitted": 5,
      "accepted": 2,
      "conversion_rate": 0.04
    },
    "revenue": {
      "confirmed_fees": 12000,
      "potential_fees": 45000,
      "consulting_leads": 8,
      "consulting_value": 250000
    },
    "regional_breakdown": {
      "turkey": { "detected": 20, "accepted": 2 },
      "mena": { "detected": 15, "accepted": 0 },
      "europe": { "detected": 12, "accepted": 0 }
    },
    "upcoming_events": [
      {
        "conference_name": "Tech Leaders Turkey 2026",
        "date": "2026-09-15",
        "days_until": 41
      }
    ]
  }
}
```

---

## Industry Reports Endpoints

### 1. Get Recent Reports

**Endpoint:** `GET /reports/recent`

**Query Parameters:**
```
?language=tr&relevance_min=0.6&region=turkey&limit=20
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "reports": [
      {
        "id": "UUID",
        "publisher": "McKinsey",
        "title": "The Future of Turkish Logistics: Digital Transformation 2026",
        "published_date": "2026-08-01",
        "topics": ["Logistics", "Digital Transformation"],
        "region": "turkey",
        "language": "en",
        "relevance_score": 0.92,
        "summary": "This report examines how Turkish logistics companies are adopting digital technologies...",
        "key_findings": [
          "40% of Turkish logistics companies adopted automation in 2025",
          "Supply chain visibility is top priority for 60% of companies",
          "AI-powered route optimization reduces costs by 15-25%"
        ],
        "source_url": "https://..."
      }
    ]
  }
}
```

---

### 2. Generate Report Commentary

**Endpoint:** `POST /reports/{id}/generate-commentary`

**Description:** Auto-generate insights and social media commentary on report.

**Request:**
```json
{
  "format": "multi", // "linkedin", "twitter", "article", "multi"
  "angle": "operations_focus"
}
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "report_id": "UUID",
    "commentary": {
      "linkedin_post": {
        "text": "The McKinsey report on Turkish logistics just dropped, and it confirms what many of us have observed...",
        "key_insights": [
          "Automation is no longer optional - it's table stakes",
          "Supply chain visibility driving competitive advantage"
        ],
        "length": 850,
        "estimated_engagement": 3.2
      },
      "twitter_thread": {
        "tweets": [
          "1/ McKinsey's latest on Turkish logistics: Fascinating data on digital transformation...",
          "2/ Key finding: 40% of Turkish logistics companies adopted automation in 2025..."
        ]
      },
      "article": {
        "title": "What McKinsey's Turkish Logistics Report Tells Us About Operations in 2026",
        "sections": [
          {
            "heading": "The Reality Check",
            "content": "..."
          }
        ],
        "word_count": 2100
      }
    }
  }
}
```

---

## Analytics Endpoints

### 1. Dashboard Summary

**Endpoint:** `GET /analytics/dashboard`

**Query Parameters:**
```
?days=30
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "summary": {
      "content_published": 24,
      "total_engagement": 3450,
      "avg_engagement_rate": 3.8,
      "follower_growth": 145,
      "speaking_opportunities": 8,
      "speaking_confirmed": 2
    },
    "performance_trend": "↑ 35% vs last month",
    "top_topics": [
      {
        "topic": "Supply Chain",
        "post_count": 5,
        "total_engagement": 1200,
        "avg_engagement_rate": 5.2
      }
    ],
    "platform_breakdown": {
      "linkedin": {
        "posts": 18,
        "engagement": 2800,
        "avg_engagement_rate": 4.2,
        "follower_growth": 95
      },
      "twitter": {
        "posts": 6,
        "engagement": 650,
        "avg_engagement_rate": 2.1,
        "follower_growth": 50
      }
    },
    "quick_actions": [
      "Supply Chain posts are performing 40% better - keep focus there",
      "Promote top 3 posts to boost engagement",
      "Next high-fit speaking opportunity: TechLeaders Turkey (due Aug 15)"
    ]
  }
}
```

---

### 2. Engagement Timeline

**Endpoint:** `GET /analytics/timeline`

**Query Parameters:**
```
?platform=linkedin&days=30&granularity=day
```

**Response (200):**
```json
{
  "success": true,
  "data": {
    "timeline": [
      {
        "date": "2026-08-05",
        "likes": 145,
        "comments": 23,
        "shares": 8,
        "views": 3500,
        "followers_gained": 5
      },
      {
        "date": "2026-08-04",
        "likes": 98,
        "comments": 12,
        "shares": 4,
        "views": 2100,
        "followers_gained": 2
      }
    ]
  }
}
```

---

### 3. Topic Performance

**Endpoint:** `GET /analytics/topics`

**Response (200):**
```json
{
  "success": true,
  "data": {
    "topics": [
      {
        "topic": "Supply Chain",
        "post_count": 5,
        "total_engagement": 1200,
        "avg_engagement_rate": 5.2,
        "trend": "↑ increasing",
        "recommendation": "This is your strongest topic - post more frequently"
      },
      {
        "topic": "Digital Transformation",
        "post_count": 8,
        "total_engagement": 1800,
        "avg_engagement_rate": 2.8,
        "trend": "→ stable",
        "recommendation": "Solid performer, maintain current frequency"
      }
    ]
  }
}
```

---

### 4. Competitive Positioning

**Endpoint:** `GET /analytics/competitive`

**Response (200):**
```json
{
  "success": true,
  "data": {
    "engagement_benchmarks": {
      "your_rate": 3.8,
      "category_average": 1.2,
      "percentile": 85
    },
    "growth_comparison": {
      "your_monthly_growth": 145,
      "category_average": 45,
      "rank": "top 15%"
    },
    "insights": [
      "Your engagement rate is 3.2x category average - keep your current style",
      "Growth trajectory puts you in top 15% of thought leaders in your space"
    ]
  }
}
```

---

### 5. ROI Tracking

**Endpoint:** `GET /analytics/roi`

**Response (200):**
```json
{
  "success": true,
  "data": {
    "content_roi": {
      "posts_published": 150,
      "total_engagement": 12000,
      "estimated_reach": 45000,
      "engagement_value": "$2,500 (equivalent ad spend)"
    },
    "speaking_roi": {
      "opportunities_pursued": 8,
      "engagements_secured": 2,
      "speaking_fees": 12000,
      "estimated_consulting_value": 50000
    },
    "network_roi": {
      "outreach_sent": 45,
      "meaningful_conversations": 18,
      "collaboration_leads": 3,
      "consulting_leads": 2,
      "estimated_value": 25000
    },
    "time_investment": {
      "hours_invested": 120,
      "hours_saved": 80,
      "roi_multiplier": 1.87
    }
  }
}
```

---

## Slack Integration Endpoints

### 1. Slack Events Webhook

**Endpoint:** `POST /slack/events`

**Description:** Slack sends all events to this webhook.

**Slack Verification:**
```http
POST /slack/events

{
  "type": "url_verification",
  "challenge": "3eZbrw1aBc2K5Kus"
}

Response:
{
  "challenge": "3eZbrw1aBc2K5Kus"
}
```

**Event Types Handled:**
- `message` - New messages in channel
- `app_mention` - Bot mentioned
- `reaction_added` - Emoji reaction
- `app_home_opened` - User views app home

---

### 2. Slack Interactions

**Endpoint:** `POST /slack/actions`

**Description:** Handle interactive components (buttons, modals, etc.).

**Request Example - Button Click:**
```json
{
  "type": "block_actions",
  "user": {
    "id": "U123456",
    "username": "burak.eltas",
    "name": "Burak Eltas",
    "team_id": "T123"
  },
  "actions": [
    {
      "type": "button",
      "action_id": "approve_content",
      "value": "content-uuid",
      "text": {
        "type": "plain_text",
        "text": "Approve"
      }
    }
  ],
  "response_url": "https://hooks.slack.com/..."
}
```

**Response - Update Message:**
```json
{
  "response_action": "update",
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "Content Approved ✓"
      }
    }
  ]
}
```

---

### 3. Slack Home App

**Endpoint:** `GET /slack/home-blocks`

**Description:** Return Block Kit blocks for app home tab.

**Response (200):**
```json
{
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "Executive Dashboard"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Followers*\n2,342"
        },
        {
          "type": "mrkdwn",
          "text": "*Engagement Rate*\n3.8%"
        }
      ]
    }
  ]
}
```

---

## Error Codes

| Code | HTTP | Description |
|------|------|-------------|
| INVALID_INPUT | 400 | Missing or invalid parameter |
| UNAUTHORIZED | 401 | Invalid/expired token |
| FORBIDDEN | 403 | User lacks permission |
| NOT_FOUND | 404 | Resource not found |
| CONFLICT | 409 | Resource already exists |
| RATE_LIMIT | 429 | Too many requests |
| INTERNAL_ERROR | 500 | Server error |
| SERVICE_UNAVAILABLE | 503 | Service temporarily unavailable |

---

## Pagination

All list endpoints support pagination:

```
GET /content?limit=20&offset=0

Response:
{
  "data": {
    "items": [...],
    "pagination": {
      "total": 156,
      "limit": 20,
      "offset": 0,
      "has_more": true
    }
  }
}
```

---

## Webhooks

### Content Published Webhook

**Endpoint:** User configurable  
**Event:** When content is published

```json
{
  "event": "content.published",
  "timestamp": "2026-08-05T18:00:00Z",
  "data": {
    "content_id": "uuid",
    "title": "...",
    "platforms": ["linkedin", "twitter"],
    "engagement_estimate": 3.2
  }
}
```

---

**Document Control**
- Version: 1.0
- Status: FINAL
- Last Updated: August 2026
