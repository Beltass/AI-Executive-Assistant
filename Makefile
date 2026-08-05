.PHONY: help install test cov run migrate lint format clean

help:
	@echo "Content Creation Platform - Development Commands"
	@echo ""
	@echo "Backend:"
	@echo "  install       Install backend dependencies"
	@echo "  test          Run backend tests"
	@echo "  cov           Run tests with coverage report"
	@echo "  run           Run FastAPI development server"
	@echo "  lint          Run linting (black, flake8)"
	@echo "  format        Format code with black and isort"
	@echo ""
	@echo "Docker:"
	@echo "  docker-build  Build Docker image"
	@echo "  docker-run    Run Docker container"
	@echo ""
	@echo "Database:"
	@echo "  migrate       Run database migrations"
	@echo "  migrate-new   Create new migration"
	@echo ""
	@echo "General:"
	@echo "  clean         Clean up cache and temporary files"

install:
	cd backend && pip install -r requirements-dev.txt

test:
	cd backend && pytest tests/ -v

cov:
	cd backend && pytest tests/ --cov=app --cov-report=html --cov-report=term-missing
	@echo "Coverage report generated in htmlcov/index.html"

run:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

lint:
	cd backend && black --check . && flake8 . && mypy app || true

format:
	cd backend && black . && isort .

docker-build:
	docker build -t content-creation-platform backend/

docker-run:
	docker run -p 8000:8000 \
		-e DATABASE_URL=postgresql://user:password@host/db \
		-e GEMINI_API_KEY=your-key \
		-e SLACK_BOT_TOKEN=your-token \
		content-creation-platform

migrate:
	cd backend && alembic upgrade head

migrate-new:
	@read -p "Enter migration name: " NAME; \
	cd backend && alembic revision --autogenerate -m "$$NAME"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name htmlcov -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name .coverage -delete
