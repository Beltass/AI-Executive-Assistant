"""Pytest configuration and shared fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.config import settings
from app.db.database import Base, get_db

# The suite configures its own signing secret instead of inheriting whatever is
# in the ambient environment. app/security.py refuses to verify tokens against
# the placeholder secret shipped in config.py, so without this the whole API
# would answer 500 "authentication is not configured" and the auth tests below
# would be measuring the wrong failure.
TEST_SECRET_KEY = "test-only-secret-not-for-production"


# Test database
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    """Override database dependency for tests."""
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def db():
    """Database session fixture."""
    # Create tables for each test
    Base.metadata.create_all(bind=engine)

    session = TestingSessionLocal()
    yield session
    session.close()

    # Clean up tables after test
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client():
    """Test client fixture."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    """Give every test a real (non-placeholder) JWT signing secret."""
    monkeypatch.setattr(settings, "SECRET_KEY", TEST_SECRET_KEY)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256")
    return TEST_SECRET_KEY


@pytest.fixture
def mock_user_id():
    """Mock user ID fixture."""
    return 1


@pytest.fixture
def mock_google_token():
    """Mock Google token fixture."""
    return "mock-google-token"
