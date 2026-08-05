-- Content Creation Platform Database Schema
-- Version: 1.0
-- Last Updated: August 2026

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pgtrgm"; -- for full-text search

-- ============================================================================
-- USERS TABLE
-- ============================================================================
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE NOT NULL,
  name VARCHAR(255) NOT NULL,
  linkedin_id VARCHAR(255) UNIQUE,
  linkedin_access_token TEXT, -- encrypted with pgcrypto
  twitter_id VARCHAR(255) UNIQUE,
  twitter_access_token TEXT, -- encrypted
  slack_id VARCHAR(255) UNIQUE,
  slack_workspace_id VARCHAR(255),
  language_preference VARCHAR(10) DEFAULT 'en', -- 'en', 'tr', 'both'
  timezone VARCHAR(50) DEFAULT 'Europe/Istanbul',
  avatar_url TEXT,
  bio TEXT,
  is_active BOOLEAN DEFAULT TRUE,
  last_login_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  CONSTRAINT valid_email CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$'),
  CONSTRAINT valid_language CHECK (language_preference IN ('en', 'tr', 'both'))
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_linkedin_id ON users(linkedin_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_slack_id ON users(slack_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_created_at ON users(created_at DESC);

-- ============================================================================
-- CONTENT TABLE
-- ============================================================================
CREATE TABLE content (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title VARCHAR(500),
  topic VARCHAR(255),
  content_type VARCHAR(50) NOT NULL,
  status VARCHAR(50) DEFAULT 'draft',
  original_language VARCHAR(10) DEFAULT 'en',
  source_type VARCHAR(50), -- 'manual', 'ai_generated', 'report_commentary'
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  published_at TIMESTAMP,
  scheduled_time TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  deleted_at TIMESTAMP,
  metadata JSONB DEFAULT '{}',
  CONSTRAINT valid_content_type CHECK (content_type IN ('post', 'article', 'thread', 'commentary', 'email')),
  CONSTRAINT valid_status CHECK (status IN ('draft', 'scheduled', 'published', 'archived', 'deleted')),
  CONSTRAINT valid_source CHECK (source_type IN ('manual', 'ai_generated', 'report_commentary'))
);

CREATE INDEX idx_content_user_id ON content(user_id);
CREATE INDEX idx_content_status ON content(status);
CREATE INDEX idx_content_created_at ON content(created_at DESC);
CREATE INDEX idx_content_published_at ON content(published_at DESC) WHERE published_at IS NOT NULL;
CREATE INDEX idx_content_scheduled_time ON content(scheduled_time) WHERE status = 'scheduled';

-- ============================================================================
-- CONTENT VARIATIONS TABLE
-- ============================================================================
CREATE TABLE content_variations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_id UUID NOT NULL REFERENCES content(id) ON DELETE CASCADE,
  variation_type VARCHAR(50),
  platform VARCHAR(50),
  text TEXT NOT NULL,
  tone VARCHAR(50),
  length VARCHAR(50),
  hashtags TEXT[] DEFAULT '{}',
  optimal_posting_time TIMESTAMP,
  engagement_estimate DECIMAL(5,2),
  is_approved BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  metadata JSONB DEFAULT '{}',
  CONSTRAINT valid_platform CHECK (platform IN ('linkedin', 'twitter', 'threads', 'instagram', 'email')),
  CONSTRAINT valid_tone CHECK (tone IN ('executive', 'casual', 'educational', 'inspirational', 'critical')),
  CONSTRAINT valid_length CHECK (length IN ('short', 'medium', 'long'))
);

CREATE INDEX idx_content_variations_content_id ON content_variations(content_id);
CREATE INDEX idx_content_variations_platform ON content_variations(platform);
CREATE INDEX idx_content_variations_optimal_time ON content_variations(optimal_posting_time);

-- ============================================================================
-- TEMPLATES TABLE
-- ============================================================================
CREATE TABLE templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  name VARCHAR(255) NOT NULL,
  category VARCHAR(100),
  content_type VARCHAR(50),
  language VARCHAR(10) DEFAULT 'en',
  framework TEXT,
  system_prompt TEXT NOT NULL,
  example_output TEXT,
  is_public BOOLEAN DEFAULT FALSE,
  usage_count INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT valid_category CHECK (category IN ('crisis_communication', 'industry_insights', 'personal_wins', 'lessons_learned', 'provocative', 'technical', 'announcement'))
);

CREATE INDEX idx_templates_user_id ON templates(user_id);
CREATE INDEX idx_templates_category ON templates(category);
CREATE INDEX idx_templates_is_public ON templates(is_public) WHERE is_public = TRUE;

-- ============================================================================
-- SCHEDULED POSTS TABLE
-- ============================================================================
CREATE TABLE scheduled_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_variation_id UUID NOT NULL REFERENCES content_variations(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  platform VARCHAR(50) NOT NULL,
  platform_post_id VARCHAR(500), -- LinkedIn post ID, Twitter tweet ID, etc.
  scheduled_time TIMESTAMP NOT NULL,
  status VARCHAR(50) DEFAULT 'scheduled',
  published_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  metadata JSONB DEFAULT '{}',
  CONSTRAINT valid_platform CHECK (platform IN ('linkedin', 'twitter', 'threads', 'instagram', 'email')),
  CONSTRAINT valid_status CHECK (status IN ('scheduled', 'published', 'failed', 'skipped', 'cancelled'))
);

CREATE INDEX idx_scheduled_posts_user_id ON scheduled_posts(user_id);
CREATE INDEX idx_scheduled_posts_platform ON scheduled_posts(platform);
CREATE INDEX idx_scheduled_posts_scheduled_time ON scheduled_posts(scheduled_time);
CREATE INDEX idx_scheduled_posts_status ON scheduled_posts(status);
CREATE INDEX idx_scheduled_posts_published_at ON scheduled_posts(published_at DESC);

-- ============================================================================
-- LINKEDIN NETWORK TABLE
-- ============================================================================
CREATE TABLE linkedin_network (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  linkedin_contact_id VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  headline VARCHAR(500),
  current_title VARCHAR(255),
  current_company VARCHAR(255),
  previous_company VARCHAR(255),
  previous_title VARCHAR(255),
  job_change_date TIMESTAMP,
  location VARCHAR(255),
  last_contacted TIMESTAMP,
  relationship_strength DECIMAL(3,2), -- 0-1.0
  last_interaction TEXT,
  outreach_history JSONB DEFAULT '[]',
  tags TEXT[] DEFAULT '{}',
  is_valuable_connection BOOLEAN DEFAULT FALSE, -- high engagement, influential, etc.
  synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, linkedin_contact_id),
  CONSTRAINT valid_strength CHECK (relationship_strength >= 0 AND relationship_strength <= 1)
);

CREATE INDEX idx_linkedin_network_user_id ON linkedin_network(user_id);
CREATE INDEX idx_linkedin_network_synced_at ON linkedin_network(synced_at);
CREATE INDEX idx_linkedin_network_job_change ON linkedin_network(job_change_date DESC);
CREATE INDEX idx_linkedin_network_valuable ON linkedin_network(is_valuable_connection);

-- ============================================================================
-- SPEAKING OPPORTUNITIES TABLE
-- ============================================================================
CREATE TABLE speaking_opportunities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  conference_name VARCHAR(500) NOT NULL,
  event_url TEXT,
  event_date DATE,
  submission_deadline DATE,
  organizer_email VARCHAR(255),
  organizer_name VARCHAR(255),
  topics TEXT[] DEFAULT '{}',
  audience_type VARCHAR(100),
  audience_size INT,
  geographic_location VARCHAR(255),
  region VARCHAR(100), -- 'turkey', 'mena', 'europe', 'asia', 'global'
  event_type VARCHAR(100), -- 'conference', 'workshop', 'webinar', 'panel', 'summit'
  fit_score DECIMAL(3,2), -- 0-10
  fit_score_reason TEXT,
  status VARCHAR(50) DEFAULT 'detected',
  pitch_sent_date TIMESTAMP,
  response_received_date TIMESTAMP,
  response_notes TEXT,
  response_status VARCHAR(50), -- 'accepted', 'rejected', 'pending', 'maybe'
  speaking_fee INT, -- in USD
  travel_required BOOLEAN DEFAULT TRUE,
  metrics JSONB DEFAULT '{}', -- attendance, leads generated, etc.
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT valid_status CHECK (status IN ('detected', 'saved', 'submitted', 'accepted', 'rejected', 'completed', 'cancelled')),
  CONSTRAINT valid_region CHECK (region IN ('turkey', 'mena', 'europe', 'asia', 'north_america', 'global'))
);

CREATE INDEX idx_speaking_opportunities_user_id ON speaking_opportunities(user_id);
CREATE INDEX idx_speaking_opportunities_status ON speaking_opportunities(status);
CREATE INDEX idx_speaking_opportunities_fit_score ON speaking_opportunities(fit_score DESC);
CREATE INDEX idx_speaking_opportunities_event_date ON speaking_opportunities(event_date);

-- ============================================================================
-- ENGAGEMENT METRICS TABLE
-- ============================================================================
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
  save_count INT DEFAULT 0,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT valid_platform CHECK (platform IN ('linkedin', 'twitter', 'threads', 'instagram', 'email'))
);

CREATE INDEX idx_engagement_metrics_content_id ON engagement_metrics(content_id);
CREATE INDEX idx_engagement_metrics_platform ON engagement_metrics(platform);
CREATE INDEX idx_engagement_metrics_metric_date ON engagement_metrics(metric_date DESC);
CREATE INDEX idx_engagement_metrics_timestamp ON engagement_metrics(timestamp DESC);

-- ============================================================================
-- INDUSTRY REPORTS TABLE
-- ============================================================================
CREATE TABLE industry_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  publisher VARCHAR(255),
  title VARCHAR(500) NOT NULL,
  report_url TEXT,
  topics TEXT[] DEFAULT '{}',
  published_date DATE,
  source_url TEXT,
  summary TEXT,
  key_findings JSONB DEFAULT '[]',
  relevance_score DECIMAL(3,2), -- 0-1.0
  relevance_to_burak DECIMAL(3,2), -- ML model score
  language VARCHAR(10) DEFAULT 'en',
  region VARCHAR(100), -- 'turkey', 'mena', 'global'
  industry VARCHAR(100),
  scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  archived_at TIMESTAMP,
  CONSTRAINT valid_region CHECK (region IN ('turkey', 'mena', 'europe', 'asia', 'north_america', 'global'))
);

CREATE INDEX idx_industry_reports_relevance_score ON industry_reports(relevance_score DESC);
CREATE INDEX idx_industry_reports_published_date ON industry_reports(published_date DESC);
CREATE INDEX idx_industry_reports_scanned_at ON industry_reports(scanned_at DESC);
CREATE INDEX idx_industry_reports_language ON industry_reports(language);

-- ============================================================================
-- REPORT COMMENTARY TABLE
-- ============================================================================
CREATE TABLE report_commentary (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  report_id UUID NOT NULL REFERENCES industry_reports(id) ON DELETE CASCADE,
  content_id UUID REFERENCES content(id) ON DELETE SET NULL,
  commentary_text TEXT,
  insights TEXT[],
  linkedin_angle TEXT,
  twitter_angle TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  published_at TIMESTAMP
);

CREATE INDEX idx_report_commentary_user_id ON report_commentary(user_id);
CREATE INDEX idx_report_commentary_report_id ON report_commentary(report_id);
CREATE INDEX idx_report_commentary_content_id ON report_commentary(content_id);

-- ============================================================================
-- AUDIT LOG TABLE
-- ============================================================================
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
CREATE INDEX idx_audit_log_resource ON audit_log(resource_type, resource_id);

-- ============================================================================
-- SLACK STATE TABLE (persistent conversation context)
-- ============================================================================
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

CREATE INDEX idx_slack_state_user_id ON slack_state(user_id);

-- ============================================================================
-- API USAGE TRACKING TABLE
-- ============================================================================
CREATE TABLE api_usage (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  endpoint VARCHAR(255),
  method VARCHAR(10),
  status_code INT,
  response_time_ms INT,
  tokens_used INT,
  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_api_usage_user_id ON api_usage(user_id);
CREATE INDEX idx_api_usage_timestamp ON api_usage(timestamp DESC);
CREATE INDEX idx_api_usage_endpoint ON api_usage(endpoint);

-- ============================================================================
-- GEMINI API CACHE TABLE
-- ============================================================================
CREATE TABLE gemini_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  prompt_hash VARCHAR(255) UNIQUE NOT NULL,
  prompt_text TEXT,
  response TEXT,
  model VARCHAR(100) DEFAULT 'gemini-2.5-flash',
  tokens_used INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP, -- cache expiration
  hit_count INT DEFAULT 0,
  last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_gemini_cache_prompt_hash ON gemini_cache(prompt_hash);
CREATE INDEX idx_gemini_cache_expires_at ON gemini_cache(expires_at);
CREATE INDEX idx_gemini_cache_hit_count ON gemini_cache(hit_count DESC);

-- ============================================================================
-- CONTENT SIMILARITY EMBEDDINGS TABLE
-- ============================================================================
CREATE TABLE content_embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content_id UUID NOT NULL REFERENCES content(id) ON DELETE CASCADE,
  embedding VECTOR(384), -- all-MiniLM-L6-v2 has 384 dimensions
  language VARCHAR(10),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_content_embeddings_content_id ON content_embeddings(content_id);
CREATE INDEX idx_content_embeddings_embedding ON content_embeddings USING ivfflat (embedding vector_cosine_ops);

-- ============================================================================
-- NOTIFICATION PREFERENCES TABLE
-- ============================================================================
CREATE TABLE notification_preferences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  slack_enabled BOOLEAN DEFAULT TRUE,
  email_enabled BOOLEAN DEFAULT TRUE,
  morning_brief_enabled BOOLEAN DEFAULT TRUE,
  speaking_alerts_enabled BOOLEAN DEFAULT TRUE,
  network_alerts_enabled BOOLEAN DEFAULT TRUE,
  engagement_summary_enabled BOOLEAN DEFAULT TRUE,
  frequency VARCHAR(50) DEFAULT 'daily', -- 'daily', 'weekly', 'off'
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id)
);

-- ============================================================================
-- FUNCTION: Update updated_at timestamp
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = CURRENT_TIMESTAMP;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger to tables with updated_at
CREATE TRIGGER users_updated_at_trigger
BEFORE UPDATE ON users
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER content_updated_at_trigger
BEFORE UPDATE ON content
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER templates_updated_at_trigger
BEFORE UPDATE ON templates
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER linkedin_network_updated_at_trigger
BEFORE UPDATE ON linkedin_network
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER slack_state_updated_at_trigger
BEFORE UPDATE ON slack_state
FOR EACH ROW
EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- VIEWS
-- ============================================================================

-- User dashboard stats
CREATE VIEW v_user_stats AS
SELECT
  u.id,
  u.email,
  u.name,
  COUNT(DISTINCT c.id) as total_content,
  COUNT(DISTINCT c.id) FILTER (WHERE c.status = 'published') as published_content,
  COUNT(DISTINCT so.id) FILTER (WHERE so.status IN ('detected', 'submitted', 'accepted')) as active_opportunities,
  COUNT(DISTINCT ln.id) as network_size,
  COALESCE(SUM(em.likes), 0) as total_likes,
  COALESCE(AVG(em.engagement_rate), 0) as avg_engagement_rate
FROM users u
LEFT JOIN content c ON u.id = c.user_id
LEFT JOIN speaking_opportunities so ON u.id = so.user_id
LEFT JOIN linkedin_network ln ON u.id = ln.user_id
LEFT JOIN engagement_metrics em ON c.id = em.content_id
WHERE u.deleted_at IS NULL
GROUP BY u.id, u.email, u.name;

-- Top performing content
CREATE VIEW v_top_content AS
SELECT
  c.id,
  c.user_id,
  c.title,
  c.topic,
  SUM(em.likes) as total_likes,
  SUM(em.comments) as total_comments,
  SUM(em.shares) as total_shares,
  AVG(em.engagement_rate) as avg_engagement_rate,
  c.published_at
FROM content c
LEFT JOIN engagement_metrics em ON c.id = em.content_id
WHERE c.status = 'published'
GROUP BY c.id, c.user_id, c.title, c.topic, c.published_at
ORDER BY total_likes DESC;

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Insert default system templates (English)
INSERT INTO templates (name, category, content_type, language, framework, system_prompt, example_output, is_public)
VALUES
(
  'Crisis Communication Template',
  'crisis_communication',
  'post',
  'en',
  'Empathy + Clarity + Action',
  'You are an expert business communicator. Generate a thoughtful, transparent response to a business crisis that acknowledges concerns and outlines concrete steps to address them.',
  'During challenging times, transparency and decisive action matter most...',
  TRUE
),
(
  'Industry Insights Template',
  'industry_insights',
  'article',
  'en',
  'Analysis + Perspective + Implications',
  'Analyze the following industry report and provide insights for operations leaders in Turkey. Highlight key findings, implications for Turkish businesses, and actionable recommendations.',
  'The McKinsey supply chain report reveals...',
  TRUE
);

-- ============================================================================
-- PERMISSIONS & SECURITY
-- ============================================================================

-- Grant appropriate permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;

-- Revoke default permissions and grant specific ones for app user (if using separate app user)
-- CREATE USER app_user WITH PASSWORD 'secure_password';
-- GRANT CONNECT ON DATABASE content_platform TO app_user;
-- GRANT USAGE ON SCHEMA public TO app_user;
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
-- GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app_user;

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
