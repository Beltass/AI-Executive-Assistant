"""Tests for LinkedIn service."""

import pytest
from unittest.mock import Mock, patch
from app.services.linkedin_service import LinkedInService


@pytest.fixture
def linkedin_service():
    """Create LinkedInService instance."""
    return LinkedInService()


class TestLinkedInNetworkRetrieval:
    """Tests for LinkedIn network retrieval."""

    @pytest.mark.asyncio
    async def test_get_network_contacts(self, linkedin_service):
        """Test getting network contacts."""
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "elements": [
                    {
                        "id": "contact1",
                        "firstName": "John",
                        "lastName": "Doe",
                    }
                ]
            }
            mock_get.return_value = mock_response

            result = await linkedin_service.get_network_contacts("token")
            assert len(result) > 0

    @pytest.mark.asyncio
    async def test_get_network_contacts_empty(self, linkedin_service):
        """Test getting empty network."""
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"elements": []}
            mock_get.return_value = mock_response

            result = await linkedin_service.get_network_contacts("token")
            assert len(result) == 0

    @pytest.mark.asyncio
    async def test_get_network_contacts_api_error(self, linkedin_service):
        """Test handling API error when getting contacts."""
        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 401
            result = await linkedin_service.get_network_contacts("invalid_token")
            assert len(result) == 0


class TestLinkedInPosting:
    """Tests for LinkedIn posting."""

    @pytest.mark.asyncio
    async def test_post_content(self, linkedin_service):
        """Test posting content to LinkedIn."""
        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": "post123"}
            mock_post.return_value = mock_response

            result = await linkedin_service.post_content("token", "Test content")
            assert result == "post123"

    @pytest.mark.asyncio
    async def test_post_content_with_media(self, linkedin_service):
        """Test posting content with media."""
        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 201
            mock_response.json.return_value = {"id": "post123"}
            mock_post.return_value = mock_response

            result = await linkedin_service.post_content(
                "token", "Test content", media_url="https://example.com/image.jpg"
            )
            assert result == "post123"

    @pytest.mark.asyncio
    async def test_post_content_api_error(self, linkedin_service):
        """Test handling API error when posting."""
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 400
            result = await linkedin_service.post_content("token", "Test")
            assert result is None


class TestLinkedInAnalytics:
    """Tests for LinkedIn analytics."""

    @pytest.mark.asyncio
    async def test_get_post_analytics(self, linkedin_service):
        """Test getting post analytics."""
        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "lifecycleState": {
                    "views": 100,
                    "comments": 10,
                    "likes": 50,
                    "shares": 5,
                }
            }
            mock_get.return_value = mock_response

            result = await linkedin_service.get_post_analytics("token", "post123")
            assert result["views"] == 100

    @pytest.mark.asyncio
    async def test_get_post_analytics_api_error(self, linkedin_service):
        """Test handling API error when getting analytics."""
        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 404
            result = await linkedin_service.get_post_analytics("token", "notfound")
            assert result is None


class TestLinkedInIndustryNews:
    """Tests for LinkedIn industry news search."""

    @pytest.mark.asyncio
    async def test_search_industry_news(self, linkedin_service):
        """Test searching industry news."""
        result = await linkedin_service.search_industry_news(
            ["AI", "machine learning"]
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_search_industry_news_empty(self, linkedin_service):
        """Test searching with empty keywords."""
        result = await linkedin_service.search_industry_news([])
        assert isinstance(result, list)


class TestLinkedInJobChanges:
    """Tests for job change detection."""

    @pytest.mark.asyncio
    async def test_get_job_changes(self, linkedin_service):
        """Test detecting job changes."""
        contacts = [
            {
                "id": "contact1",
                "firstName": "John",
                "position": {
                    "title": "Senior Engineer",
                    "company": "TechCorp",
                },
            }
        ]

        result = await linkedin_service.get_job_changes(contacts)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_get_job_changes_empty(self, linkedin_service):
        """Test job changes detection with empty contacts."""
        result = await linkedin_service.get_job_changes([])
        assert len(result) == 0
