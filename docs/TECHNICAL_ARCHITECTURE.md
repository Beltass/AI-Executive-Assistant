# Technical Architecture - Content Creation Platform
## System Design & Implementation Guide

**Version:** 1.0  
**Date:** August 2026  
**Target Deployment:** Google Cloud Platform (Cloud Run, Cloud SQL, Cloud Storage)  

---

## System Overview

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND LAYER                          │
├──────────────────────┬──────────────────────┬──────────────────┤
│  React Dashboard     │  React Native App    │  Slack Bot UI    │
│  (TypeScript)        │  (Expo)              │  (Block Kit)     │
│  Tailwind CSS        │  Mobile              │  Interactive     │
└──────────┬───────────┴──────────────┬───────┴──────────┬────────┘
           │                          │                  │
           └──────────────────────────┼──────────────────┘
                                      │
         ┌────────────────────────────▼─────────────────────────────┐
         │                    API GATEWAY / LOAD BALANCER           │
         │                  (Cloud Run + Cloud CDN)                 │
         └────────────────────────────┬─────────────────────────────┘
                                      │
         ┌────────────────────────────▼─────────────────────────────┐
         │                   API BACKEND LAYER                      │
         │                   (Python FastAPI)                       │
         ├─────────────────────────────────────────────────────────┤
         │  ├─ Content Service      ├─ Network Service             │
         │  ├─ Analytics Service    ├─ Speaking Service            │
         │  ├─ Auth Service         ├─ Reports Service             │
         │  ├─ Publishing Service   └─ Slack Service               │
         └────────────────────┬────────────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────────────────────┐
         │                    │                                     │
         │    BACKGROUND PROCESSING (Celery + Redis)               │
         │    ├─ Content generation tasks                           │
         │    ├─ Network sync jobs                                  │
         │    ├─ Opportunity detection                              │
         │    ├─ Analytics aggregation                              │
         │    └─ Report scanning                                    │
         └────────────┬──────────────────────────────┬──────────────┘
                      │                              │
    ┌─────────────────▼──────────────┐  ┌───────────▼──────────────┐
    │   DATA LAYER (PostgreSQL)      │  │   CACHE LAYER (Redis)    │
    │   ├─ User data                 │  │   ├─ Session cache       │
    │   ├─ Content & metrics         │  │   ├─ API responses      │
    │   ├─ Network intelligence      │  │   ├─ Job queue          │
    │   ├─ Opportunity pipeline      │  │   └─ Rate limiting      │
    │   └─ Audit logs                │  └──────────────────────────┘
    └────────────────────────────────┘
                                      
         ┌────────────────────────────────────────────────────────┐
         │              VECTOR DB & ML LAYER                      │
         │  ├─ Chroma (local) / Pinecone (cloud)                  │
         │  ├─ Content embeddings & similarity                    │
         │  ├─ Recommendation engine                              │
         │  └─ Fit scoring (opportunities)                        │
         └────────────────────────────────────────────────────────┘

         ┌────────────────────────────────────────────────────────┐
         │                 AI/LLM SERVICES                         │
         │  ├─ Google Gemini 2.5-Flash (content generation)       │
         │  ├─ spaCy NLP (Turkish + English)                      │
         │  ├─ all-MiniLM-L6-v2 (embeddings)                      │
         │  └─ Custom ML models (fit scoring)                     │
         └────────────────────────────────────────────────────────┘

         ┌────────────────────────────────────────────────────────┐
         │              EXTERNAL INTEGRATIONS                      │
         │  ├─ Slack API (WebHooks, Bot, App Home)                │
         │  ├─ LinkedIn API v2 (network, content)                 │
         │  ├─ Google APIs (Drive, Sheets, Calendar, Gmail)       │
         │  ├─ Twitter/X v2 API (publishing)                      │
         │  ├─ SendGrid (email)                                   │
         │  └─ Google Cloud Storage (files)                       │
         └────────────────────────────────────────────────────────┘

         ┌────────────────────────────────────────────────────────┐
         │            MONITORING & OBSERVABILITY                  │
         │  ├─ Cloud Logging (centralized logs)                   │
         │  ├─ Cloud Monitoring (metrics & alerts)                │
         │  ├─ Sentry (error tracking)                            │
         │  └─ Cloud Trace (distributed tracing)                  │
         └────────────────────────────────────────────────────────┘
```

---

## Technology Stack (Justified)

### Frontend

#### Dashboard (Web)
- **Framework:** React 18 + TypeScript
  - *Why:* Industry standard for complex dashboards, strong type safety
  - Component reusability, large ecosystem
- **Styling:** Tailwind CSS + Headless UI
  - *Why:* Utility-first CSS, rapid development, accessible components
- **State Management:** TanStack Query (React Query) + Zustand
  - *Why:* Query state separation, better performance, simpler than Redux
- **UI Components:** Recharts (analytics), React Grid Layout (calendar)
- **Build Tool:** Vite
  - *Why:* Fast HMR, small bundle, production-optimized
- **Testing:** Vitest + React Testing Library
  - *Why:* Fast, JSDOM-based, mirrors user behavior

#### Mobile App
- **Framework:** React Native (Expo)
  - *Why:* Code reuse from web, native performance, rapid iteration
- **Features:** Read-only analytics, quick actions, Slack notifications
- **Push Notifications:** Expo Notifications
- **Navigation:** React Navigation

#### Slack Bot UI
- **Format:** Block Kit JSON
  - *Why:* Native Slack experience, interactive elements (buttons, modals)
- **Framework:** Slack Bolt for Python
  - *Why:* Official SDK, handles OAuth, events, messages seamlessly

### Backend

#### API Server
- **Framework:** FastAPI (Python 3.11+)
  - *Why:* 
    - Excellent for async operations (content generation, API calls)
    - Automatic OpenAPI docs (Swagger)
    - High performance (benchmarks: 4x faster than Django)
    - Built-in dependency injection
  - Pydantic for data validation
  - Starlette for ASGI server

#### Task Queue
- **System:** Celery + Redis
  - *Why:* 
    - Distributed task processing (content generation, network sync)
    - Scheduled jobs support (daily scans, opportunity detection)
    - Result persistence (track job status)
    - Rate limiting (API quota management)

#### Caching
- **System:** Redis
  - *Why:* Fast in-memory cache, supports pub/sub, key expiration
  - Use cases:
    - User sessions (JWT tokens + metadata)
    - API response caching (engagement metrics)
    - Rate limiting counters
    - Job queue

#### Database
- **Primary:** PostgreSQL 15+
  - *Why:* 
    - ACID compliance (data integrity critical for user content)
    - JSON support (flexible metadata storage)
    - Full-text search (future search feature)
    - PostGIS extension (if adding geo-features)
    - Proven at scale

- **Deployment:** Google Cloud SQL
  - Automated backups (daily)
  - Automated failover (99.95% SLA)
  - Point-in-time recovery

#### ORM
- **Library:** SQLAlchemy 2.0
  - *Why:* Type-safe, async support, advanced query capabilities

### AI/ML Layer

#### LLM
- **Model:** Google Gemini 2.5-Flash
  - *Why:*
    - Dual-language capability (Turkish + English)
    - Cost-effective (~$0.075/1M input tokens)
    - Fast inference (suitable for user-facing generation)
    - Advanced reasoning for fit scoring
    - Native support for prompt caching (53% cost reduction)
  - Implementation: google-generativeai Python SDK

#### Embeddings
- **Model:** sentence-transformers/all-MiniLM-L6-v2
  - *Why:* 
    - Small size (22MB, can run locally)
    - Good performance on similarity tasks
    - Multilingual support
    - No API calls needed (privacy + speed)

#### Vector Database
- **Development:** Chroma (local)
  - *Why:* Embedded, no setup, suitable for MVP
- **Production:** Pinecone (serverless)
  - *Why:* Managed service, scalable, no infrastructure needed

#### NLP
- **Library:** spaCy
  - *Why:* Fast, accurate Turkish + English processing
  - Use cases:
    - Named entity recognition (contacts, companies)
    - Keyword extraction (topics, hashtags)
    - Language detection
    - Text preprocessing

### Infrastructure

#### Compute
- **Platform:** Google Cloud Run (serverless)
  - *Why:*
    - Auto-scaling (0-N instances)
    - Pay-per-request pricing
    - No infrastructure management
    - Docker-based (easy local testing)
  - Configuration: 2GB RAM, 1 vCPU, 300s timeout per request

#### Storage
- **Files:** Google Cloud Storage
  - *Why:* Scalable, integrated with GCP, CDN support
  - Buckets:
    - `user-content/` (posts, documents)
    - `generated-content/` (API responses)
    - `media/` (images, videos)

#### Secrets Management
- **Service:** Google Secret Manager
  - *Why:* Centralized, access control, audit logging
  - Rotates automatically
  - Secrets: API keys, OAuth tokens, database passwords

#### CI/CD
- **Platform:** GitHub Actions
  - *Why:* Integrated with GitHub, free for public repos, powerful workflows
  - Pipeline stages:
    1. Test (unit, integration, E2E)
    2. Lint & format check
    3. Security scanning
    4. Build Docker image
    5. Deploy to staging
    6. Run smoke tests
    7. Deploy to production

#### Containerization
- **Tool:** Docker
  - *Why:* Consistent environments, easy deployment, Cloud Run native
  - Multi-stage builds (optimized image size)
  - Docker Compose for local development

### Monitoring & Observability

#### Logging
- **Service:** Google Cloud Logging
  - *Why:* Centralized, integrated with GCP, powerful query language
  - Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
  - Structured logging (JSON format for parsing)

#### Metrics
- **Service:** Google Cloud Monitoring
  - *Why:* Native GCP integration, dashboard creation, alerting
  - Metrics:
    - API latency, error rates
    - Database query times
    - Queue depth (Celery)
    - Cache hit rate

#### Error Tracking
- **Service:** Sentry (cloud)
  - *Why:* Real-time error alerts, release tracking, session replay
  - Captures: Exceptions, performance issues, deployments

#### Distributed Tracing
- **Service:** Google Cloud Trace
  - *Why:* Track requests across services
  - Shows: API → Database, API → Gemini, etc.

#### Uptime Monitoring
- **Service:** Google Cloud Monitoring + Healthchecks
  - Endpoint: `/health` (database, Redis connectivity check)
  - SLA target: 99.9%

---

## Database Schema

### Core Tables

```sql
-- Users
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  name VARCHAR(255) NOT NULL,
  linkedin_id VARCHAR(255) UNIQUE,
  linkedin_access_token TEXT, -- encrypted
  twitter_id VARCHAR(255) UNIQUE,
  twitter_access_token TEXT, -- encrypted
  slack_id VARCHAR(255) UNIQUE,
  slack_workspace_id VARCHAR(255),
  language_preference VARCHAR(10) DEFAULT 'en',
  timezone VARCHAR(50) DEFAULT 'Europe/Istanbul',
  avatar_url TEXT,
  bio TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$')
);

-- Content
CREATE TABLE content (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title VARCHAR(500),
  topic VARCHAR(255),
  content_type VARCHAR(50) NOT NULL, -- 'post', 'article', 'thread', 'commentary'
  status VARCHAR(50) DEFAULT 'draft', -- 'draft', 'scheduled', 'published', 'archived'
  original_language VARCHAR(10) DEFAULT 'en',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  published_at TIMESTAMP,
  scheduled_time TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  metadata JSONB DEFAULT '{}',
  CONSTRAINT valid_type CHECK (content_type IN ('post', 'article', 'thread', 'commentary')),
  CONSTRAINT valid_status CHECK (status IN ('draft', 'scheduled', 'published', 'archived'))
);

CREATE INDEX idx_content_user_id ON content(user_id);
CREATE INDEX idx_content_status ON content(status);
CREATE INDEX idx_content_created_at ON content(created_at DESC);

-- Content Variations
CREATE TABLE content_variations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_id UUID NOT NULL REFERENCES content(id) ON DELETE CASCADE,
  variation_type VARCHAR(50), -- 'linkedin_post', 'twitter_thread', etc.
  platform VARCHAR(50), -- 'linkedin', 'twitter', 'threads', 'instagram'
  text TEXT NOT NULL,
  tone VARCHAR(50), -- 'executive', 'casual', 'educational', 'inspirational', 'critical'
  length VARCHAR(50), -- 'short', 'medium', 'long'
  hashtags TEXT[] DEFAULT '{}',
  optimal_posting_time TIMESTAMP,
  engagement_estimate DECIMAL(5,2),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_content_variations_content_id ON content_variations(content_id);
CREATE INDEX idx_content_variations_platform ON content_variations(platform);

-- Templates
CREATE TABLE templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  category VARCHAR(100), -- 'crisis_communication', 'industry_insights', etc.
  content_type VARCHAR(50),
  language VARCHAR(10) DEFAULT 'en',
  framework TEXT,
  system_prompt TEXT NOT NULL,
  example_output TEXT,
  is_public BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_templates_user_id ON templates(user_id);
CREATE INDEX idx_templates_category ON templates(category);

-- Scheduled Posts
CREATE TABLE scheduled_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_variation_id UUID NOT NULL REFERENCES content_variations(id) ON DELETE CASCADE,
  platform VARCHAR(50) NOT NULL,
  scheduled_time TIMESTAMP NOT NULL,
  status VARCHAR(50) DEFAULT 'scheduled', -- 'scheduled', 'published', 'failed', 'skipped'
  published_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  metadata JSONB DEFAULT '{}',
  CONSTRAINT valid_status CHECK (status IN ('scheduled', 'published', 'failed', 'skipped'))
);

CREATE INDEX idx_scheduled_posts_platform ON scheduled_posts(platform);
CREATE INDEX idx_scheduled_posts_scheduled_time ON scheduled_posts(scheduled_time);
CREATE INDEX idx_scheduled_posts_status ON scheduled_posts(status);

-- LinkedIn Network
CREATE TABLE linkedin_network (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  linkedin_contact_id VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  current_title VARCHAR(255),
  current_company VARCHAR(255),
  job_change_date TIMESTAMP,
  last_contacted TIMESTAMP,
  relationship_strength DECIMAL(3,2), -- 0-1.0
  last_interaction TEXT,
  outreach_history JSONB DEFAULT '[]',
  tags TEXT[] DEFAULT '{}',
  synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, linkedin_contact_id)
);

CREATE INDEX idx_linkedin_network_user_id ON linkedin_network(user_id);
CREATE INDEX idx_linkedin_network_synced_at ON linkedin_network(synced_at);

-- Speaking Opportunities
CREATE TABLE speaking_opportunities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  conference_name VARCHAR(500) NOT NULL,
  event_date DATE,
  submission_deadline DATE,
  event_url TEXT,
  topics TEXT[] DEFAULT '{}',
  audience_type VARCHAR(100), -- 'corporate', 'startup', 'government', 'academic'
  audience_size INT,
  geographic_location VARCHAR(255),
  fit_score DECIMAL(3,2), -- 0-10
  status VARCHAR(50) DEFAULT 'detected', -- 'detected', 'saved', 'submitted', 'accepted', 'completed'
  pitch_sent_date TIMESTAMP,
  response_received_date TIMESTAMP,
  response_notes TEXT,
  metrics JSONB DEFAULT '{}',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_speaking_opportunities_user_id ON speaking_opportunities(user_id);
CREATE INDEX idx_speaking_opportunities_status ON speaking_opportunities(status);
CREATE INDEX idx_speaking_opportunities_fit_score ON speaking_opportunities(fit_score DESC);

-- Engagement Metrics
CREATE TABLE engagement_metrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_id UUID NOT NULL REFERENCES content(id) ON DELETE CASCADE,
  platform VARCHAR(50),
  metric_date DATE DEFAULT CURRENT_DATE,
  likes INT DEFAULT 0,
  comments INT DEFAULT 0,
  shares INT DEFAULT 0,
  reposts INT DEFAULT 0,
  views INT DEFAULT 0,
  clicks INT DEFAULT 0,
  follower_growth INT DEFAULT 0,
  engagement_rate DECIMAL(5,2),
  reach INT DEFAULT 0,
  impressions INT DEFAULT 0,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_engagement_metrics_content_id ON engagement_metrics(content_id);
CREATE INDEX idx_engagement_metrics_platform ON engagement_metrics(platform);
CREATE INDEX idx_engagement_metrics_metric_date ON engagement_metrics(metric_date);

-- Industry Reports
CREATE TABLE industry_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  publisher VARCHAR(255),
  title VARCHAR(500) NOT NULL,
  topics TEXT[] DEFAULT '{}',
  published_date DATE,
  source_url TEXT,
  summary TEXT,
  key_findings JSONB DEFAULT '[]',
  relevance_score DECIMAL(3,2), -- 0-1.0
  language VARCHAR(10) DEFAULT 'en',
  scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  archived_at TIMESTAMP
);

CREATE INDEX idx_industry_reports_relevance_score ON industry_reports(relevance_score DESC);
CREATE INDEX idx_industry_reports_published_date ON industry_reports(published_date DESC);
CREATE INDEX idx_industry_reports_scanned_at ON industry_reports(scanned_at DESC);

-- Audit Log
CREATE TABLE audit_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE SET NULL,
  action VARCHAR(255) NOT NULL,
  resource_type VARCHAR(50),
  resource_id UUID,
  changes JSONB DEFAULT '{}',
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  metadata JSONB DEFAULT '{}'
);

CREATE INDEX idx_audit_log_user_id ON audit_log(user_id);
CREATE INDEX idx_audit_log_timestamp ON audit_log(timestamp DESC);

-- Slack State (conversation context)
CREATE TABLE slack_state (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  conversation_state JSONB DEFAULT '{}',
  last_message_ts VARCHAR(255),
  last_interaction_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  context JSONB DEFAULT '{}',
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id)
);
```

---

## API Endpoints Specification

### Base URL
```
https://api.content-platform.com/api
```

### Authentication
All requests require `Authorization: Bearer {jwt_token}` header.

### Content Endpoints

#### Generate Content
```http
POST /content/generate

Request:
{
  "topic": "Turkish supply chain challenges",
  "primary_platform": "linkedin",
  "language": "both",
  "tone": "executive",
  "content_type": "post"
}

Response (200):
{
  "id": "uuid",
  "topic": "Turkish supply chain challenges",
  "variations": [
    {
      "id": "uuid",
      "platform": "linkedin",
      "text": "...",
      "tone": "executive",
      "length": "medium",
      "hashtags": ["#Turkey", "#Operations"],
      "optimal_posting_time": "2026-08-05T18:00:00Z",
      "engagement_estimate": 3.2
    },
    ...
  ],
  "created_at": "2026-08-05T10:00:00Z"
}
```

#### List Content
```http
GET /content?status=draft&limit=20&offset=0

Response (200):
{
  "items": [...],
  "total": 150,
  "limit": 20,
  "offset": 0
}
```

#### Update Content
```http
PUT /content/{id}

Request:
{
  "title": "New title",
  "topic": "New topic"
}

Response (200): Updated content object
```

#### Publish Content
```http
POST /content/{id}/publish

Request:
{
  "platform": "linkedin",
  "schedule_time": "2026-08-05T18:00:00Z" // optional
}

Response (200):
{
  "status": "published",
  "published_at": "2026-08-05T18:00:00Z"
}
```

#### Get Content Analytics
```http
GET /content/{id}/analytics

Response (200):
{
  "content_id": "uuid",
  "platform": "linkedin",
  "engagement": {
    "likes": 145,
    "comments": 23,
    "shares": 8,
    "views": 3500,
    "engagement_rate": 4.8
  },
  "timeline": [
    {
      "date": "2026-08-05",
      "likes": 45,
      "comments": 8,
      "shares": 2,
      "views": 1200
    }
  ]
}
```

### Network Intelligence Endpoints

#### Get Network Opportunities
```http
GET /network/opportunities?limit=10

Response (200):
{
  "opportunities": [
    {
      "type": "job_change",
      "contact_id": "uuid",
      "name": "Ahmed Yildirim",
      "previous_title": "VP Engineering",
      "new_title": "CTO",
      "new_company": "TechCorp",
      "date": "2026-08-03",
      "priority": 8
    },
    ...
  ]
}
```

#### Generate Outreach Message
```http
POST /network/generate-outreach

Request:
{
  "contact_id": "uuid",
  "type": "congratulations" // 'congratulations', 'interview_request', 'collaborate'
}

Response (200):
{
  "variants": [
    {
      "text": "Congratulations Ahmed on your new role as CTO!...",
      "tone": "warm",
      "length": "medium"
    },
    ...
  ]
}
```

#### Sync LinkedIn Network
```http
POST /network/sync-linkedin

Response (202 Accepted):
{
  "job_id": "uuid",
  "status": "processing"
}

// Poll for status
GET /jobs/{job_id}
Response (200):
{
  "status": "completed",
  "results": {
    "synced": 2000,
    "new_changes": 45,
    "opportunities": 12
  }
}
```

### Speaking Opportunities Endpoints

#### Get Speaking Opportunities
```http
GET /speaking/opportunities?status=detected&fit_score_min=7

Response (200):
{
  "opportunities": [
    {
      "id": "uuid",
      "conference_name": "Tech Leaders Turkey 2026",
      "event_date": "2026-09-15",
      "submission_deadline": "2026-08-15",
      "topics": ["Operations", "Digital Transformation"],
      "fit_score": 9,
      "audience_size": 2000,
      "status": "detected"
    },
    ...
  ]
}
```

#### Generate Speaking Pitch
```http
POST /speaking/{id}/generate-pitch

Response (200):
{
  "email_body": "Dear Organizers,\n\nI'm excited to propose...",
  "subject": "Speaking Proposal: Operations Transformation",
  "speaker_bio": "...",
  "talk_description": "..."
}
```

### Analytics Endpoints

#### Dashboard Overview
```http
GET /analytics/dashboard?days=30

Response (200):
{
  "summary": {
    "content_published": 24,
    "total_engagement": 3450,
    "avg_engagement_rate": 3.8,
    "follower_growth": 145,
    "speaking_opportunities": 8
  },
  "top_topics": [
    { "topic": "Supply Chain", "count": 5, "engagement": 1200 }
  ],
  "platform_breakdown": {
    "linkedin": { "posts": 18, "engagement": 2800 },
    "twitter": { "posts": 6, "engagement": 650 }
  }
}
```

#### Engagement Timeline
```http
GET /analytics/timeline?platform=linkedin&days=30

Response (200):
{
  "data": [
    {
      "date": "2026-08-05",
      "likes": 145,
      "comments": 23,
      "shares": 8,
      "views": 3500
    },
    ...
  ]
}
```

### Slack Integration Endpoints

#### Slack Events
```http
POST /slack/events

Request (Slack webhook):
{
  "type": "url_verification",
  "challenge": "3eZbrw1aBc2K5Kus"
}

Response (200):
{
  "challenge": "3eZbrw1aBc2K5Kus"
}
```

#### Slack Interaction (Button/Modal)
```http
POST /slack/actions

Request:
{
  "type": "block_actions",
  "user": { "id": "U123" },
  "actions": [
    {
      "type": "button",
      "action_id": "approve_content",
      "value": "content-uuid"
    }
  ]
}

Response (200):
{
  "response_action": "update",
  "blocks": [...]
}
```

---

## Microservices Design

### Service Architecture

```
┌─────────────────────────────────────────────┐
│         API Gateway (FastAPI main)          │
└───────────────────┬─────────────────────────┘
                    │
    ┌───────────────┼───────────────┬─────────────────┐
    ▼               ▼               ▼                 ▼
┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────────┐
│ Auth        │ │ Content      │ │ Network      │ │ Speaking    │
│ Service     │ │ Service      │ │ Service      │ │ Service     │
└─────────────┘ └──────────────┘ └──────────────┘ └─────────────┘
    │               │               │                 │
    ├─────────────────────────────────────────────────┤
    │           Async Task Queue (Celery)             │
    └─────────────────────────────────────────────────┘
                    │
    ┌───────────────┼───────────────┬─────────────────┐
    ▼               ▼               ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Content Gen  │ │ Network Sync │ │ Opportunity  │ │ Report Scan  │
│ Worker       │ │ Worker       │ │ Detection    │ │ Worker       │
│              │ │              │ │ Worker       │ │              │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

### Services

#### 1. Auth Service
- User login/signup (Google OAuth)
- JWT token generation/validation
- Session management
- Permission checking

#### 2. Content Service
- Content CRUD operations
- Content generation (Gemini API calls)
- Publishing to platforms
- Scheduling

#### 3. Network Service
- LinkedIn connection tracking
- Job change detection
- Outreach generation
- Relationship analytics

#### 4. Speaking Service
- Opportunity detection
- Fit scoring
- Pitch generation
- Calendar management

#### 5. Analytics Service
- Metrics aggregation
- Report generation
- Dashboard data

#### 6. Slack Service
- Bot event handling
- Interactive workflows
- Daily message scheduling

---

## Data Flow Diagrams

### Content Generation Flow

```
User Action: Generate Content
    │
    ├─► Content Service
    │   ├─► Create content record (draft)
    │   └─► Queue async task
    │
    ├─► Celery Task: ContentGenerationWorker
    │   ├─► Retrieve topic details
    │   ├─► Build prompt with Gemini caching
    │   │   ├─► Check prompt cache (Redis)
    │   │   └─► Call Gemini API if miss
    │   ├─► Generate 5 variations
    │   ├─► Calculate optimal posting times
    │   │   └─► Analyze audience timezone/activity patterns
    │   ├─► Store variations in PostgreSQL
    │   └─► Update Redis cache
    │
    ├─► API Response
    │   └─► Return variations to frontend
    │
    ├─► Frontend
    │   ├─► Display variations
    │   └─► User approves one
    │
    └─► Publishing
        ├─► Queue publish task
        ├─► Platform-specific formatting
        ├─► Publish to LinkedIn/Twitter/etc
        └─► Track engagement
```

### Network Intelligence Flow

```
Scheduled Job: Daily LinkedIn Sync (3 AM UTC+3)
    │
    ├─► Network Service
    │   └─► Queue sync task (async)
    │
    ├─► Celery Task: LinkedInSyncWorker
    │   ├─► Fetch LinkedIn access token
    │   ├─► Get user's connections (paginated)
    │   ├─► Compare with stored data
    │   │   └─► Identify job changes, title changes, company moves
    │   ├─► Score relationship strength
    │   │   └─► Factor: message frequency, recent interaction
    │   ├─► Detect opportunities
    │   │   └─► High-value connections with job changes
    │   ├─► Generate outreach messages (Gemini)
    │   └─► Store in PostgreSQL
    │
    ├─► Morning Brief (7 AM)
    │   ├─► Query opportunities from cache
    │   ├─► Format Slack message (Block Kit)
    │   ├─► Post to Slack with interactive buttons
    │   └─► User takes action (send congratulations, etc.)
    │
    └─► Track outcomes
        ├─► Log interaction in audit trail
        ├─► Update relationship strength
        └─► Track conversion to leads
```

---

## Security Architecture

### Authentication & Authorization

```
Login Flow:
    │
    ├─► User clicks "Login with Google"
    │
    ├─► Google OAuth Flow
    │   ├─► Redirect to Google login
    │   ├─► User authorizes app
    │   └─► Google returns auth code
    │
    ├─► Backend Exchange
    │   ├─► Exchange code for tokens (server-side)
    │   ├─► Verify token signature
    │   └─► Extract user info
    │
    ├─► Session Creation
    │   ├─► Generate JWT token (RS256 signed)
    │   ├─► Set httpOnly cookie
    │   └─► Store refresh token in Redis
    │
    └─► Protected Requests
        └─► Verify JWT signature on each request
```

### API Security

```
Rate Limiting:
├─ 100 requests/minute per user (Redis-backed)
├─ 1000 requests/minute per IP
└─ Exponential backoff for failures

Input Validation:
├─ Pydantic models for all inputs
├─ Sanitization (HTML escaping)
├─ File upload scanning (file type, size)
└─ SQL injection prevention (parameterized queries)

Output Encoding:
├─ JSON serialization (safe by default)
├─ CSP headers (Content-Security-Policy)
└─ CORS validation

Secrets Management:
├─ All keys in Google Secret Manager
├─ Environment variable injection at runtime
├─ No secrets in code or logs
└─ Automatic rotation (90 days)
```

### Data Protection

```
Database:
├─ PostgreSQL pgcrypto for encrypted columns
│  ├─ API tokens (AES-256)
│  ├─ Passwords (never stored, OAuth only)
│  └─ Sensitive personal data
├─ SSL/TLS for all connections
└─ Encrypted backups

At-Rest:
├─ Google Cloud Storage encryption
├─ PostgreSQL encryption (CMEK with Google Cloud KMS)
└─ Redis encryption (Google Memorystore)

In-Transit:
├─ TLS 1.3 for all HTTPS
├─ mTLS for internal services
└─ VPC network for database connections
```

---

## Scalability Plan

### Horizontal Scaling

```
Load Balancer (Cloud Run)
    │
    ├─► Instance 1 (2GB RAM, 1 vCPU)
    ├─► Instance 2 (2GB RAM, 1 vCPU)
    ├─► Instance 3 (2GB RAM, 1 vCPU)
    └─► Instance N (auto-scale 0-100 instances)

Triggers:
├─ CPU > 80%
├─ Memory > 90%
├─ Request latency > 2s (p95)
└─ Concurrent requests > 1000
```

### Database Scaling

```
PostgreSQL (Cloud SQL)
├─ Read Replicas (3-5)
│  └─ For analytics queries
├─ Connection pooling (PgBouncer)
│  └─ Limit connections per app instance
└─ Query optimization
   ├─ Indexes on frequently queried columns
   ├─ Partitioning large tables (by date)
   └─ Query result caching (Redis)
```

### Cache Optimization

```
Redis Cluster (if needed)
├─ 3-node cluster (for high availability)
├─ Key expiration policies
│  ├─ Sessions: 24 hours
│  ├─ API responses: 1 hour
│  └─ Rate limit counters: 60 seconds
└─ Memory management
   └─ Eviction policy: LRU (Least Recently Used)
```

### Token Efficiency

```
Gemini API Optimization:
├─ Prompt Caching (reduces costs by ~53%)
│  ├─ System prompts cached (fixed templates)
│  ├─ User context cached (connection info, past content)
│  └─ Cache key: hash of prompt content
├─ Batch Processing
│  ├─ Group requests where possible
│  └─ Daily batch: report commentary, network analysis
└─ Cost Monitoring
   └─ Alert if monthly spend > $500
```

---

## Deployment Strategy

### Environments

```
Development
├─ Local Docker Compose
├─ Gemini API (free tier)
└─ Mock LinkedIn/Twitter (no real API calls)

Staging
├─ Cloud Run (us-central1)
├─ Cloud SQL (staging instance)
├─ Real Gemini API (test budget)
└─ LinkedIn/Twitter staging endpoints

Production
├─ Cloud Run (multi-region: us, eu, asia)
├─ Cloud SQL (production, 99.95% SLA)
├─ Real Gemini API (production budget)
└─ LinkedIn/Twitter production endpoints
```

### CI/CD Pipeline

```
Push to main branch
    │
    ├─► Run Tests
    │   ├─ Unit tests (pytest)
    │   ├─ Integration tests (API + mocked external services)
    │   └─ Coverage check (90%+ required)
    │
    ├─► Lint & Format
    │   ├─ Black (Python formatting)
    │   ├─ isort (import sorting)
    │   ├─ pylint (code quality)
    │   └─ mypy (type checking)
    │
    ├─► Security Scan
    │   ├─ Bandit (Python security)
    │   ├─ OWASP dependency check
    │   └─ Container scan (Trivy)
    │
    ├─► Build Docker Image
    │   ├─ Multi-stage build (optimize size)
    │   └─ Push to Container Registry
    │
    ├─► Deploy to Staging
    │   ├─ Run migrations
    │   └─ E2E tests in staging
    │
    ├─► Manual Approval (required)
    │   └─ Review pull request
    │
    └─► Deploy to Production
        ├─ Canary deployment (5% traffic)
        ├─ Monitor error rate & latency
        ├─ Gradual rollout (25%, 50%, 100%)
        └─ Automatic rollback if issues detected
```

### Deployment Checklist

- Database migrations ready and tested
- Environment variables configured in Secret Manager
- Monitoring alerts configured
- Backup strategy validated
- Rollback plan documented
- Load testing completed
- Security audit passed
- Documentation updated

---

## Monitoring & Logging

### Key Metrics

```
Application Level:
├─ API response latency (p50, p95, p99)
├─ Error rate (5xx responses)
├─ Request rate (requests/second)
├─ Active users (concurrent)
└─ Content generation latency

Business Level:
├─ Content published (daily/weekly)
├─ Engagement rate (platform averages)
├─ Speaking opportunities detected
├─ Network outreach sent
└─ Consulting leads generated

Infrastructure Level:
├─ CPU utilization (avg, max)
├─ Memory usage
├─ Disk space (database, storage)
├─ Network I/O
└─ Database connection pool usage
```

### Alerting Rules

```
Critical (immediate page):
├─ API error rate > 5% (5 min window)
├─ P99 latency > 5s (5 min window)
├─ Database unavailable (3 consecutive health checks)
└─ Deployment failure

High (within 1 hour):
├─ API error rate > 1% (15 min window)
├─ P95 latency > 2s (15 min window)
├─ Redis connectivity issues
└─ Gemini API quota exceeded

Medium (next business day):
├─ Queue depth > 10k jobs
├─ Cache hit rate < 50%
└─ Database query p99 > 500ms
```

### Logging Strategy

```
Log Levels:
├─ DEBUG: Detailed development info (not in production)
├─ INFO: Important business events
│  ├─ User login
│  ├─ Content published
│  ├─ API call to external service
│  └─ Database operation
├─ WARNING: Unexpected but recoverable
│  ├─ API rate limit approaching
│  ├─ Retry attempt
│  └─ Missing optional configuration
└─ ERROR: Serious issues
   ├─ API call failure
   ├─ Database error
   └─ Unhandled exception

Structured Logging:
{
  "timestamp": "2026-08-05T10:00:00Z",
  "level": "INFO",
  "service": "content-service",
  "message": "Content published",
  "user_id": "uuid",
  "content_id": "uuid",
  "platform": "linkedin",
  "duration_ms": 2400,
  "trace_id": "abc123"
}
```

---

## Appendix: Technology Justification

| Technology | Alternative | Why Chosen |
|------------|-------------|-----------|
| FastAPI | Django, Flask | Async support, performance, auto-docs |
| PostgreSQL | MongoDB, MySQL | ACID compliance, JSON support, full-text search |
| Celery | RQ, Bull | Distributed, reliable, proven at scale |
| React | Vue, Angular | Ecosystem, component libraries, talent pool |
| Gemini | OpenAI, Claude | Dual-language, cost-effective, caching support |
| Google Cloud | AWS, Azure | Multi-language support, integrated services |

---

**Document Control**
- Version: 1.0
- Status: FINAL
- Last Updated: August 2026
- Review Schedule: Post-launch (Month 3)
