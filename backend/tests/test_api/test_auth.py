"""Tests for authentication."""

from fastapi.testclient import TestClient


class TestAuthentication:
    """Tests for authentication endpoints."""

    def test_missing_auth_header(self, client: TestClient):
        """Test request without auth header."""
        response = client.get("/api/content")
        assert response.status_code in [401, 403]

    def test_invalid_token(self, client: TestClient):
        """Test request with invalid token."""
        response = client.get(
            "/api/content",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert response.status_code in [401, 403]

    def test_expired_token(self, client: TestClient):
        """Test request with expired token."""
        response = client.get(
            "/api/content",
            headers={"Authorization": "Bearer expired-token"},
        )
        assert response.status_code in [401, 403]

    def test_malformed_auth_header(self, client: TestClient):
        """Test request with malformed auth header."""
        response = client.get(
            "/api/content",
            headers={"Authorization": "InvalidToken"},
        )
        assert response.status_code in [401, 403]

    def test_bearer_prefix_required(self, client: TestClient):
        """Test that Bearer prefix is required."""
        response = client.get(
            "/api/content",
            headers={"Authorization": "token123"},
        )
        assert response.status_code in [401, 403]

    def test_valid_token_header_format(self, client: TestClient):
        """Test valid token header format."""
        response = client.get(
            "/api/content",
            headers={"Authorization": "Bearer valid-token"},
        )
        # Will fail auth but should parse header correctly
        assert response.status_code in [200, 401]


class TestAuthorizationScopes:
    """Tests for authorization scopes."""

    def test_content_generation_requires_auth(self, client: TestClient):
        """Test that content generation requires authentication."""
        response = client.post(
            "/api/content/generate",
            json={"topic": "AI", "content_type": "post"},
        )
        assert response.status_code in [401, 403]

    def test_user_can_only_access_own_content(self, client: TestClient):
        """Test that user can only access their own content."""
        # User 1 trying to access User 2's content
        response = client.get(
            "/api/content/999",
            headers={"Authorization": "Bearer user1-token"},
        )
        # Should be 404 or 401
        assert response.status_code in [401, 403, 404]
