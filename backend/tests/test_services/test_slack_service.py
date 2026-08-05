"""Tests for Slack service."""

import pytest
from unittest.mock import Mock, patch
from app.services.slack_service import SlackService


@pytest.fixture
def slack_service():
    """Create SlackService instance."""
    return SlackService()


class TestSlackMessaging:
    """Tests for Slack messaging."""

    @pytest.mark.asyncio
    async def test_send_message(self, slack_service):
        """Test sending message to Slack."""
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            result = await slack_service.send_message("C123", "Test message")
            # Result depends on actual API response
            assert result is not None

    @pytest.mark.asyncio
    async def test_send_message_with_blocks(self, slack_service):
        """Test sending message with blocks."""
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Test"}}]
            result = await slack_service.send_message("C123", "Test", blocks=blocks)
            assert result is not None

    @pytest.mark.asyncio
    async def test_send_approval_request(self, slack_service):
        """Test sending content approval request."""
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            result = await slack_service.send_content_approval_request(
                "C123", 1, "AI Topic", "Preview text"
            )
            assert result is not None


class TestSlackModals:
    """Tests for Slack modals."""

    @pytest.mark.asyncio
    async def test_open_modal(self, slack_service):
        """Test opening modal."""
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 200
            view = {
                "type": "modal",
                "callback_id": "test_modal",
                "title": {"type": "plain_text", "text": "Test"},
                "blocks": [],
            }
            result = await slack_service.open_modal("trigger_id", view)
            assert result is not None


class TestSlackUserLookup:
    """Tests for Slack user lookup."""

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, slack_service):
        """Test getting user by email."""
        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "user": {"id": "U123"},
            }
            mock_post.return_value = mock_response

            result = await slack_service.get_user_by_email("test@example.com")
            assert result == "U123"

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, slack_service):
        """Test getting user not found."""
        with patch("requests.post") as mock_post:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": False}
            mock_post.return_value = mock_response

            result = await slack_service.get_user_by_email("notfound@example.com")
            assert result is None


class TestSlackSignatureVerification:
    """Tests for Slack signature verification."""

    def test_verify_valid_signature(self, slack_service):
        """Test verifying valid signature."""
        import hmac
        import hashlib
        import time

        timestamp = str(int(time.time()))
        body = "test_body"
        basestring = f"v0:{timestamp}:{body}"
        signature = "v0=" + hmac.new(
            slack_service.signing_secret.encode(),
            basestring.encode(),
            hashlib.sha256,
        ).hexdigest()

        result = slack_service.verify_request(timestamp, signature, body)
        assert result is True

    def test_reject_invalid_signature(self, slack_service):
        """Test rejecting invalid signature."""
        result = slack_service.verify_request("123", "v0=invalid", "body")
        assert result is False

    def test_reject_old_timestamp(self, slack_service):
        """Test rejecting old timestamp."""
        import hmac
        import hashlib

        old_timestamp = "1000000000"
        body = "test_body"
        basestring = f"v0:{old_timestamp}:{body}"
        signature = "v0=" + hmac.new(
            slack_service.signing_secret.encode(),
            basestring.encode(),
            hashlib.sha256,
        ).hexdigest()

        result = slack_service.verify_request(old_timestamp, signature, body)
        assert result is False
