# Getting Started - Content Creation Platform

Welcome to the Content Creation Platform! This guide will help you set up and start developing.

## Prerequisites

- Python 3.11 or higher
- PostgreSQL 15
- Node.js 18+ (for frontend)
- Docker (optional)
- Git

## Quick Start

### 1. Clone the Repository

```bash
git clone <repository-url>
cd AI-Executive-Assistant
```

### 2. Set Up Environment Variables

Copy the example environment file and update it with your credentials:

```bash
cp .env.burak-platform.example .env
```

Required environment variables:

```bash
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/content_creation

# Google OAuth
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# Slack
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_APP_ID=your-app-id

# Gemini API
GEMINI_API_KEY=your-api-key

# LinkedIn
LINKEDIN_CLIENT_ID=your-client-id
LINKEDIN_CLIENT_SECRET=your-secret

# JWT
SECRET_KEY=your-secret-key-for-jwt
```

### 3. Install Backend Dependencies

```bash
make install
```

Or manually:

```bash
cd backend
pip install -r requirements-dev.txt
```

### 4. Set Up Database

```bash
# Start PostgreSQL (if not running)
docker run -d \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=content_creation \
  -p 5432:5432 \
  postgres:15

# Run migrations
make migrate
```

### 5. Run the Application

Start the FastAPI development server:

```bash
make run
```

The API will be available at:
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### 6. Run Tests

```bash
# Run all tests
make test

# Run with coverage
make cov
```

## Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py              # Configuration settings
│   ├── dependencies.py        # Shared dependencies
│   ├── api/
│   │   └── routes/            # API endpoint routes
│   ├── services/              # Business logic services
│   ├── db/
│   │   ├── database.py        # Database connection
│   │   └── models.py          # SQLAlchemy models
│   └── schemas/               # Pydantic validation schemas
├── tests/
│   ├── conftest.py           # Pytest configuration
│   ├── test_api/             # API endpoint tests
│   ├── test_services/        # Service tests
│   ├── test_db/              # Database model tests
│   └── test_integration/     # End-to-end tests
├── requirements.txt          # Production dependencies
├── requirements-dev.txt      # Development dependencies
└── Dockerfile               # Docker configuration

slack/
├── bot/
│   ├── app.py               # Slack bot setup
│   └── handlers/            # Event/command handlers

.github/workflows/
└── ci.yml                   # CI/CD pipeline
```

## API Endpoints

### Content Management

- `POST /api/content/generate` - Generate new content
- `GET /api/content` - List user's content
- `GET /api/content/{id}` - Get specific content
- `PUT /api/content/{id}` - Update content
- `DELETE /api/content/{id}` - Delete content
- `POST /api/content/{id}/approve` - Approve content
- `POST /api/content/{id}/publish` - Publish content

### Templates

- `GET /api/templates` - List templates
- `GET /api/templates/{id}` - Get template
- `POST /api/templates` - Create template
- `PUT /api/templates/{id}` - Update template
- `DELETE /api/templates/{id}` - Delete template

### Analytics

- `GET /api/analytics/content/{id}` - Get content metrics
- `GET /api/analytics/summary` - Get user summary
- `GET /api/analytics/platform-performance` - Platform breakdown
- `GET /api/analytics/trends` - Engagement trends

### LinkedIn Network

- `GET /api/network` - List contacts
- `POST /api/network/sync` - Sync from LinkedIn
- `GET /api/network/job-changes` - Detect job changes

### Speaking Opportunities

- `GET /api/speaking` - List opportunities
- `GET /api/speaking/top-opportunities` - Top recommendations
- `POST /api/speaking/{id}/mark-interested` - Mark as interested
- `POST /api/speaking/{id}/mark-pitched` - Mark as pitched

### Slack Integration

- `POST /api/slack/events` - Receive Slack events
- `POST /api/slack/actions` - Handle Slack actions
- `POST /api/slack/commands` - Handle slash commands

## Development Workflow

### Creating a New Feature

1. Create a feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Implement your feature with tests:
   ```bash
   # Write code in app/
   # Write tests in tests/
   ```

3. Run tests and linting:
   ```bash
   make test
   make lint
   ```

4. Commit your changes:
   ```bash
   git add .
   git commit -m "Add your feature description"
   git push origin feature/your-feature-name
   ```

5. Create a pull request on GitHub

### Writing Tests

Tests are organized by component:

- `tests/test_api/` - API endpoint tests
- `tests/test_services/` - Service/business logic tests
- `tests/test_db/` - Database model tests
- `tests/test_integration/` - End-to-end workflow tests

Example test:

```python
@pytest.mark.asyncio
async def test_generate_content(client: TestClient):
    response = client.post(
        "/api/content/generate",
        json={"topic": "AI", "content_type": "post"},
        headers={"Authorization": "Bearer token"},
    )
    assert response.status_code == 200
```

## Database Migrations

### Create a New Migration

```bash
make migrate-new
```

This will prompt you for a migration name and create an Alembic migration file.

### Apply Migrations

```bash
make migrate
```

## Docker

### Build Docker Image

```bash
make docker-build
```

### Run with Docker

```bash
make docker-run
```

Or use docker-compose:

```bash
docker-compose up
```

## Troubleshooting

### Database Connection Error

Ensure PostgreSQL is running and the DATABASE_URL is correct:

```bash
psql postgresql://user:password@localhost:5432/content_creation
```

### API Tests Failing

1. Check environment variables are set
2. Ensure database migrations have run
3. Verify all dependencies are installed

### Slack Integration Not Working

1. Verify `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` are correct
2. Check Slack bot is installed in your workspace
3. Verify bot has necessary permissions

## Next Steps

- Review API documentation at `/docs`
- Check out example requests in `examples/`
- Read the full project README
- Join the team discussions

## Support

For issues or questions:
1. Check existing GitHub issues
2. Create a new issue with detailed description
3. Contact the development team

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [Slack Bolt Documentation](https://slack.dev/bolt-python/)
- [Google Generative AI](https://ai.google.dev/)
