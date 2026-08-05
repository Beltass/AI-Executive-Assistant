# Content Creation Platform - Backend

FastAPI backend for the Content Creation Platform providing AI-powered content generation, analytics, and integrations.

## Features

- **Content Generation** - AI-powered content creation using Google Gemini
- **Multi-Platform Support** - Generate content optimized for LinkedIn, Twitter, Instagram, Email
- **Analytics** - Track engagement metrics and performance insights
- **Slack Integration** - Approve and manage content directly from Slack
- **LinkedIn Network** - Monitor job changes and engage with your network
- **Speaking Opportunities** - Discover and track speaking engagements
- **Templates** - Manage reusable content templates for different industries

## Tech Stack

- **Framework**: FastAPI 0.104
- **Database**: PostgreSQL with SQLAlchemy ORM
- **API Documentation**: Swagger UI / ReDoc
- **Testing**: pytest with async support
- **AI/LLM**: Google Generative AI (Gemini)
- **Slack**: Slack Bolt for Python
- **Authentication**: Google OAuth 2.0 + JWT

## Quick Start

See [GETTING_STARTED.md](../GETTING_STARTED.md) for detailed setup instructions.

### Basic Setup

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Set up environment
cp ../.env.burak-platform.example .env
# Edit .env with your credentials

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

## Project Structure

```
app/
├── main.py              # FastAPI application
├── config.py            # Settings and configuration
├── dependencies.py      # Shared dependencies (auth, etc.)
├── api/
│   └── routes/
│       ├── content.py       # Content endpoints
│       ├── templates.py     # Template endpoints
│       ├── network.py       # LinkedIn network
│       ├── speaking.py      # Speaking opportunities
│       ├── analytics.py     # Analytics endpoints
│       └── slack.py         # Slack integration
├── services/
│   ├── content_service.py     # Content business logic
│   ├── gemini_service.py      # LLM integration
│   ├── slack_service.py       # Slack integration logic
│   ├── linkedin_service.py    # LinkedIn API integration
│   └── analytics_service.py   # Analytics calculations
├── db/
│   ├── database.py      # Database connection
│   ├── models.py        # SQLAlchemy models
│   └── migrations/      # Alembic migrations
└── schemas/
    ├── content.py       # Content validation
    ├── user.py          # User validation
    ├── template.py      # Template validation
    └── slack.py         # Slack event validation

tests/
├── conftest.py          # Pytest configuration
├── test_api/            # Endpoint tests (65+ tests)
├── test_services/       # Service tests (60+ tests)
├── test_db/             # Model tests (20+ tests)
└── test_integration/    # Workflow tests (20+ tests)
```

## Database Models

### Core Models
- **User** - User accounts with OAuth integration
- **Content** - Generated or curated content
- **ContentVariation** - Platform-specific versions of content
- **Template** - Reusable content frameworks

### Analytics Models
- **EngagementMetric** - Views, likes, comments, shares per platform
- **ScheduledPost** - Scheduled content publishing

### Network Models
- **LinkedInNetwork** - Contact database with job change tracking
- **SpeakingOpportunity** - Speaking engagement opportunities
- **IndustryReport** - Tracked industry insights

## API Endpoints

### Content Management (`/api/content`)
- `POST /generate` - Generate new content (AI)
- `GET /` - List user's content
- `GET /{id}` - Get content details
- `PUT /{id}` - Update content
- `DELETE /{id}` - Archive content
- `POST /{id}/approve` - Approve for publishing
- `POST /{id}/publish` - Publish content

### Templates (`/api/templates`)
- `GET /` - List templates
- `GET /{id}` - Get template
- `POST /` - Create template
- `PUT /{id}` - Update template
- `DELETE /{id}` - Delete template

### Analytics (`/api/analytics`)
- `GET /content/{id}` - Content metrics
- `GET /summary` - User analytics summary
- `GET /platform-performance` - Platform breakdown
- `GET /trends` - Engagement trends

### LinkedIn (`/api/network`)
- `GET /` - List contacts
- `POST /sync` - Sync from LinkedIn
- `GET /job-changes` - Detect job changes

### Speaking (`/api/speaking`)
- `GET /` - List opportunities
- `GET /top-opportunities` - Best opportunities
- `POST /{id}/mark-interested` - Track interest
- `POST /{id}/mark-pitched` - Track pitch

### Slack (`/api/slack`)
- `POST /events` - Slack event webhook
- `POST /actions` - Action callbacks
- `POST /commands` - Slash command handler

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=html

# Run specific test file
pytest tests/test_api/test_content.py -v

# Run with asyncio
pytest tests/ -v --asyncio-mode=auto
```

Test Coverage:
- **165+ tests** total
- **API tests** (65+) - Endpoint functionality
- **Service tests** (60+) - Business logic
- **Model tests** (20+) - Database operations
- **Integration tests** (20+) - End-to-end workflows

## Development

### Code Quality

```bash
# Format code
black . && isort .

# Lint
flake8 . --max-line-length=127

# Type checking
mypy app --ignore-missing-imports
```

### Database Migrations

```bash
# Create migration
alembic revision --autogenerate -m "Add new field"

# Apply migrations
alembic upgrade head

# Revert last migration
alembic downgrade -1
```

### Adding a New Endpoint

1. Create schema in `schemas/`
2. Add database model if needed in `db/models.py`
3. Create service method in `services/`
4. Create route in `api/routes/`
5. Add tests in `tests/test_api/`
6. Update API documentation in docstrings

## Configuration

Environment variables (see `.env.example`):

```bash
# Database
DATABASE_URL=postgresql://user:password@host/db

# Google OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...

# APIs
GEMINI_API_KEY=...
LINKEDIN_CLIENT_ID=...
LINKEDIN_CLIENT_SECRET=...

# Security
SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

## Performance & Scaling

- **Connection pooling** - SQLAlchemy connection pool (10 base, 20 overflow)
- **Indexes** - Database indexes on frequently queried columns
- **Caching** - Redis support for token caching
- **Async** - Full async/await support for I/O operations
- **Rate limiting** - Ready for rate limiter middleware

## Security

- **Authentication** - Google OAuth 2.0 + JWT tokens
- **Authorization** - User-scoped access to resources
- **CORS** - Configured for frontend domains
- **Input validation** - Pydantic schemas for all inputs
- **SQL injection** - Protected via ORM parameterized queries
- **Token security** - Signed JWTs with expiration

## Deployment

### Docker

```bash
docker build -t content-platform backend/
docker run -p 8000:8000 \
  -e DATABASE_URL=... \
  -e GEMINI_API_KEY=... \
  content-platform
```

### Cloud Platforms

Ready for deployment to:
- AWS (RDS + ECS)
- Google Cloud (Cloud SQL + Cloud Run)
- Azure (Database + App Service)
- DigitalOcean (Managed DB + App Platform)

## Monitoring & Logging

- **Logging** - Python logging configured with JSON output
- **Error handling** - Comprehensive exception handling
- **Health checks** - `/health` endpoint
- **Metrics** - Ready for Prometheus integration

## Contributing

1. Create feature branch
2. Write tests for your feature
3. Run linting and tests
4. Submit pull request

## License

Proprietary - Content Creation Platform

## Support

For issues or questions:
- Check existing GitHub issues
- Create new issue with details
- Contact development team
