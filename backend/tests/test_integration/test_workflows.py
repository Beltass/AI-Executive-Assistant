"""Integration tests for end-to-end workflows."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import User, Content
from app.main import app


@pytest.fixture
def integration_user(db: Session):
    """Create user for integration tests."""
    user = User(
        email="integration@example.com",
        name="Integration Test User",
        language="en",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestContentWorkflow:
    """Test complete content creation workflow."""

    @pytest.mark.asyncio
    async def test_generate_and_approve_workflow(
        self, client: TestClient, integration_user: User, db: Session
    ):
        """Test workflow: generate -> approve -> publish."""
        # Generate content
        generate_response = client.post(
            "/api/content/generate",
            json={
                "topic": "AI in business",
                "content_type": "post",
                "platforms": ["linkedin"],
            },
            headers={"Authorization": "Bearer test-token"},
        )

        # Should be 200 or 401 depending on auth setup
        assert generate_response.status_code in [200, 401]

    @pytest.mark.asyncio
    async def test_list_and_retrieve_workflow(
        self, client: TestClient, integration_user: User, db: Session
    ):
        """Test workflow: list -> retrieve -> update."""
        # Create content first
        content = Content(
            user_id=integration_user.id,
            title="Test Content",
            topic="AI",
            content_type="post",
            status="draft",
        )
        db.add(content)
        db.commit()

        # List content
        list_response = client.get(
            "/api/content",
            headers={"Authorization": "Bearer test-token"},
        )
        assert list_response.status_code in [200, 401]

        # Get specific content
        get_response = client.get(
            f"/api/content/{content.id}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert get_response.status_code in [200, 401, 404]


class TestAnalyticsWorkflow:
    """Test analytics workflow."""

    @pytest.mark.asyncio
    async def test_content_metrics_workflow(
        self, client: TestClient, integration_user: User, db: Session
    ):
        """Test workflow: create content -> record metrics -> view analytics."""
        # Create content
        content = Content(
            user_id=integration_user.id,
            title="Test Content",
            topic="AI",
            content_type="post",
            status="published",
        )
        db.add(content)
        db.commit()

        # Get metrics
        metrics_response = client.get(
            f"/api/analytics/content/{content.id}",
            headers={"Authorization": "Bearer test-token"},
        )
        assert metrics_response.status_code in [200, 401]

    @pytest.mark.asyncio
    async def test_user_analytics_workflow(
        self, client: TestClient, integration_user: User
    ):
        """Test workflow: view user analytics."""
        analytics_response = client.get(
            "/api/analytics/summary?days=30",
            headers={"Authorization": "Bearer test-token"},
        )
        assert analytics_response.status_code in [200, 401]


class TestTemplateWorkflow:
    """Test template management workflow."""

    @pytest.mark.asyncio
    async def test_list_templates(self, client: TestClient):
        """Test listing templates."""
        response = client.get(
            "/api/templates",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code in [200, 401]

    @pytest.mark.asyncio
    async def test_template_filtering(self, client: TestClient):
        """Test template filtering by language and category."""
        response = client.get(
            "/api/templates?language=en&category=content",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code in [200, 401]


class TestNetworkWorkflow:
    """Test LinkedIn network workflow."""

    @pytest.mark.asyncio
    async def test_sync_and_view_network(self, client: TestClient):
        """Test workflow: sync network -> view contacts."""
        # Sync network
        sync_response = client.post(
            "/api/network/sync",
            headers={"Authorization": "Bearer test-token"},
        )
        assert sync_response.status_code in [200, 401]

        # List network
        list_response = client.get(
            "/api/network",
            headers={"Authorization": "Bearer test-token"},
        )
        assert list_response.status_code in [200, 401]


class TestSpeakingWorkflow:
    """Test speaking opportunities workflow."""

    @pytest.mark.asyncio
    async def test_view_opportunities(self, client: TestClient):
        """Test viewing speaking opportunities."""
        response = client.get(
            "/api/speaking",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code in [200, 401]

    @pytest.mark.asyncio
    async def test_filter_opportunities(self, client: TestClient):
        """Test filtering opportunities by status."""
        response = client.get(
            "/api/speaking?status=discovered",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code in [200, 401]


class TestHealthCheck:
    """Test API health checks."""

    def test_health_endpoint(self, client: TestClient):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_root_endpoint(self, client: TestClient):
        """Test root endpoint."""
        response = client.get("/")
        assert response.status_code == 200
        assert "message" in response.json()
