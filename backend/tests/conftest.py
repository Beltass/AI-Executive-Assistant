"""Pytest configuration and shared fixtures."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import Base, get_db


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


@pytest.fixture
def mock_user_id():
    """Mock user ID fixture."""
    return 1


@pytest.fixture
def mock_google_token():
    """Mock Google token fixture."""
    return "mock-google-token"
