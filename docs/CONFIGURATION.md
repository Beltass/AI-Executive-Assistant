# Configuration Guide - Environment Setup & Secrets

**Version:** 1.0  
**Date:** August 2026  

## Environment Variables

### Development
Create `.env` file (never commit):

```bash
# Application
ENVIRONMENT=development
LOG_LEVEL=DEBUG
DEBUG=True

# Database
DATABASE_URL=postgresql://user:password@localhost:5432/content_platform_dev
DATABASE_POOL_SIZE=5
DATABASE_MAX_OVERFLOW=10

# Redis
REDIS_URL=redis://localhost:6379/0

# API Keys & Tokens
GEMINI_API_KEY=sk-...
SLACK_APP_TOKEN=xapp_...
SLACK_BOT_TOKEN=xoxb_...
SLACK_SIGNING_SECRET=xxx...

# OAuth
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxx
LINKEDIN_CLIENT_ID=xxx
LINKEDIN_CLIENT_SECRET=xxx
TWITTER_API_KEY=xxx
TWITTER_API_SECRET=xxx

# JWT
JWT_SECRET_KEY=your-secret-key-min-32-chars
JWT_ALGORITHM=HS256

# Sendgrid
SENDGRID_API_KEY=SG....

# Storage
GCS_PROJECT_ID=your-project-id
GCS_BUCKET_NAME=content-platform-dev
GCS_CREDENTIALS_PATH=./credentials.json

# Features
FEATURE_SPEAKING_OPPORTUNITIES=True
FEATURE_NETWORK_INTELLIGENCE=True
FEATURE_REPORT_SCANNING=True

# Limits
MAX_CONCURRENT_USERS=1000
MAX_REQUESTS_PER_MINUTE=100
GEMINI_BUDGET_PER_USER_MONTH=10  # USD
```

### Staging
```bash
ENVIRONMENT=staging
LOG_LEVEL=INFO
DATABASE_URL=cloudsql://staging-db
GEMINI_API_KEY=production_key
# ... other staging values
```

### Production
```bash
ENVIRONMENT=production
LOG_LEVEL=WARNING
DATABASE_URL=cloudsql://production-db
GEMINI_API_KEY=production_key
# ... other production values
```

**Store in Google Secret Manager:**
```bash
gcloud secrets create database_password --data-file=-
gcloud secrets create slack_app_token --data-file=-
gcloud secrets create gemini_api_key --data-file=-
# ... etc
```

---

## Docker Configuration

### .env for Docker Compose
```bash
# .env.docker
POSTGRES_USER=postgres
POSTGRES_PASSWORD=secure_password_here
POSTGRES_DB=content_platform_dev

REDIS_PASSWORD=redis_password_here

GEMINI_API_KEY=your_key_here
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/content_platform_dev
      REDIS_URL: redis://:${REDIS_PASSWORD}@cache:6379/0
      GEMINI_API_KEY: ${GEMINI_API_KEY}
    depends_on:
      - db
      - cache
    volumes:
      - ./src:/app/src
      - ./tests:/app/tests

  db:
    image: postgres:15
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./db/schema.sql:/docker-entrypoint-initdb.d/01-schema.sql
    ports:
      - "5432:5432"

  cache:
    image: redis:7
    command: redis-server --requirepass ${REDIS_PASSWORD}
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    environment:
      REACT_APP_API_URL: http://localhost:8000
    depends_on:
      - api
    volumes:
      - ./frontend/src:/app/src

volumes:
  postgres_data:
  redis_data:
```

**Start development environment:**
```bash
docker-compose up -d
```

---

## Python Requirements

### requirements.txt (Backend)

```
# Core
fastapi==0.103.0
uvicorn[standard]==0.23.2
pydantic==2.4.2
pydantic-settings==2.0.3

# Database
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
alembic==1.12.1

# Caching
redis==5.0.1

# Task Queue
celery==5.3.4
flower==2.0.1

# External APIs
google-generativeai==0.3.0
slack-bolt==1.18.0
linkedin-api==2.1.0
tweepy==4.14.0
sendgrid==6.10.0
google-cloud-storage==2.10.0
google-cloud-sql-connector==1.4.3

# Authentication
google-auth==2.25.2
google-auth-oauthlib==1.1.0
pyjwt==2.8.1
python-jose==3.3.0
passlib==1.7.4

# Testing
pytest==7.4.3
pytest-cov==4.1.0
pytest-asyncio==0.21.1
testcontainers==3.7.1
httpx==0.25.2
faker==20.1.0

# Security
bandit==1.7.5
safety==2.3.5
cryptography==41.0.7

# Monitoring
sentry-sdk==1.38.0
python-json-logger==2.0.7

# NLP
spacy==3.7.2
sentence-transformers==2.2.2

# Vector DB
chromadb==0.4.16
pinecone-client==3.0.2

# Utilities
python-dotenv==1.0.0
requests==2.31.0
aiohttp==3.9.1
pyyaml==6.0.1
pytz==2023.3
```

### package.json (Frontend)

```json
{
  "name": "content-platform-frontend",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "lint": "eslint src --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "type-check": "tsc --noEmit",
    "test": "vitest",
    "test:ui": "vitest --ui",
    "test:coverage": "vitest --coverage"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.20.0",
    "@tanstack/react-query": "^5.0.0",
    "zustand": "^4.4.0",
    "axios": "^1.6.0",
    "recharts": "^2.10.0",
    "date-fns": "^2.30.0",
    "@headlessui/react": "^1.7.0"
  },
  "devDependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0",
    "@vitejs/plugin-react": "^4.2.0",
    "tailwindcss": "^3.3.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "eslint": "^8.55.0",
    "@typescript-eslint/eslint-plugin": "^6.13.0",
    "@typescript-eslint/parser": "^6.13.0",
    "vitest": "^1.0.0",
    "@testing-library/react": "^14.1.0",
    "@testing-library/jest-dom": "^6.1.0"
  }
}
```

---

## Database Initialization

### Local Database Setup

```bash
# Create database
createdb content_platform_dev

# Load schema
psql content_platform_dev < db/schema.sql

# Run migrations
alembic upgrade head
```

### Seed Test Data

```python
# scripts/seed_dev_database.py
from src.database import SessionLocal
from src.models import User, Template

db = SessionLocal()

# Create test user
user = User(
    email="burak@example.com",
    name="Burak Eltas",
    language_preference="both",
    timezone="Europe/Istanbul"
)
db.add(user)
db.commit()

# Create system templates
templates = [
    Template(
        name="Industry Insights",
        category="industry_insights",
        system_prompt="You are an operations expert analyzing industry reports..."
    ),
    # ... more templates
]
db.add_all(templates)
db.commit()
```

---

## Google Cloud Setup

### Project Initialization

```bash
# Create project
gcloud projects create content-platform-prod

# Set project
gcloud config set project content-platform-prod

# Enable APIs
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  cloudlogging.googleapis.com \
  monitoring.googleapis.com

# Create service account
gcloud iam service-accounts create content-api-sa

# Grant roles
gcloud projects add-iam-policy-binding content-platform-prod \
  --member=serviceAccount:content-api-sa@content-platform-prod.iam.gserviceaccount.com \
  --role=roles/cloudsql.client
```

### Cloud SQL Setup

```bash
# Create Cloud SQL instance
gcloud sql instances create content-db \
  --database-version POSTGRES_15 \
  --tier db-f1-micro \
  --region us-central1 \
  --database-flags cloudsql_iam_authentication=on

# Create database
gcloud sql databases create content_platform \
  --instance=content-db

# Create user
gcloud sql users create app \
  --instance=content-db \
  --type=CLOUD_IAM_SERVICE_ACCOUNT
```

### Cloud Storage Setup

```bash
# Create bucket
gsutil mb gs://content-platform-dev

# Set lifecycle (delete after 90 days)
gsutil lifecycle set - gs://content-platform-dev << 'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 90}
      }
    ]
  }
}
EOF
```

---

## Secrets Management

### Store Secrets

```bash
# Database password
gcloud secrets create db_password \
  --replication-policy="automatic" \
  --data-file=-

# API keys
gcloud secrets create gemini_api_key --data-file=-
gcloud secrets create slack_app_token --data-file=-
gcloud secrets create linkedin_client_secret --data-file=-

# Grant access to Cloud Run service account
gcloud secrets add-iam-policy-binding db_password \
  --member=serviceAccount:content-api-sa@project-id.iam.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor
```

### Access in Application

```python
from google.cloud import secretmanager

def access_secret_version(secret_id, version_id="latest"):
    client = secretmanager.SecretManagerServiceClient()
    project_id = os.getenv("GCP_PROJECT_ID")
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")

DATABASE_PASSWORD = access_secret_version("db_password")
GEMINI_API_KEY = access_secret_version("gemini_api_key")
```

---

## Local Development Checklist

- [ ] Python 3.11+ installed
- [ ] PostgreSQL 15 running
- [ ] Redis running
- [ ] `.env` file created with development values
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Database initialized (`psql < db/schema.sql`)
- [ ] Frontend dependencies installed (`npm install`)
- [ ] API starts (`uvicorn src.main:app --reload`)
- [ ] Frontend starts (`npm run dev`)
- [ ] Tests pass (`pytest tests/`)

---

**Document Control**
- Version: 1.0
- Status: FINAL
- Last Updated: August 2026
