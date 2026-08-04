"""Tests for Slack Direct Messaging."""

import pytest
from ai_assistant.chat.direct_messaging import (
    DirectMessenger,
    DirectMessage,
    DirectMessageResponse,
    NOTIFICATION_PUSH,
    NOTIFICATION_EMAIL,
    NOTIFICATION_SMS,
)


class TestDirectMessenger:
    """Test Direct Messenger for Slack DM handling."""

    def test_direct_messenger_init(self):
        """Test DirectMessenger initialization."""
        messenger = DirectMessenger()
        assert messenger is not None
        assert hasattr(messenger, "timeout")
        assert hasattr(messenger, "notification_method")

    def test_timeout_default(self):
        """Test default timeout is set."""
        messenger = DirectMessenger()
        assert messenger.timeout > 0
        assert messenger.timeout == 30  # DEFAULT_TIMEOUT

    def test_notification_method_default(self):
        """Test default notification method is push."""
        messenger = DirectMessenger()
        assert messenger.notification_method == NOTIFICATION_PUSH

    def test_direct_message_dataclass(self):
        """Test DirectMessage dataclass."""
        msg = DirectMessage(
            user_id="U123456",
            text="Test message",
            timestamp="1234567890",
            channel_id="D123456",
        )
        assert msg.user_id == "U123456"
        assert msg.text == "Test message"
        assert msg.timestamp == "1234567890"
        assert msg.channel_id == "D123456"

    def test_direct_message_response_dataclass(self):
        """Test DirectMessageResponse dataclass."""
        response = DirectMessageResponse(
            advisor_key="personal_assistant",
            response_text="Test response",
            generated_at="2024-08-04T10:00:00",
        )
        assert response.advisor_key == "personal_assistant"
        assert response.response_text == "Test response"
        assert response.generated_at is not None

    def test_detect_advisor_personal(self):
        """Test advisor detection for personal keywords."""
        messenger = DirectMessenger()
        result = messenger._detect_advisor("Bu hafta hedeflerim nelerdir?")
        assert result is not None  # Should detect personal assistant

    def test_detect_advisor_social(self):
        """Test advisor detection for social media keywords."""
        messenger = DirectMessenger()
        result = messenger._detect_advisor("Instagram profilimi analiz et")
        assert result == "social_media_coach"

    def test_detect_advisor_linkedin(self):
        """Test advisor detection for LinkedIn keywords."""
        messenger = DirectMessenger()
        result = messenger._detect_advisor("LinkedIn'i optimize et")
        assert result == "linkedin_coach"

    def test_detect_advisor_data(self):
        """Test advisor detection for data analysis keywords."""
        messenger = DirectMessenger()
        result = messenger._detect_advisor("Veri analizi yap")
        assert result == "data_analyst"

    def test_detect_advisor_fallback(self):
        """Test advisor detection fallback to personal assistant."""
        messenger = DirectMessenger()
        result = messenger._detect_advisor("Anlamadığım rastgele metin")
        assert result is not None

    def test_advisor_keywords_mapping(self):
        """Test ADVISOR_KEYWORDS mapping exists."""
        messenger = DirectMessenger()
        assert hasattr(messenger, "ADVISOR_KEYWORDS")
        assert isinstance(messenger.ADVISOR_KEYWORDS, dict)
        assert len(messenger.ADVISOR_KEYWORDS) > 0

    def test_has_unknown_intent_response(self):
        """Test unknown intent response method exists."""
        messenger = DirectMessenger()
        assert hasattr(messenger, "_unknown_intent_response")
        assert callable(messenger._unknown_intent_response)

    def test_has_send_notification_methods(self):
        """Test notification sending methods exist."""
        messenger = DirectMessenger()
        assert hasattr(messenger, "_send_push_notification")
        assert hasattr(messenger, "_send_email_notification")
        assert hasattr(messenger, "_send_sms_notification")
        assert callable(messenger._send_push_notification)
        assert callable(messenger._send_email_notification)
        assert callable(messenger._send_sms_notification)

    def test_direct_message_has_optional_thread(self):
        """Test DirectMessage has optional thread_ts."""
        msg = DirectMessage(
            user_id="U123456",
            text="Reply",
            timestamp="1234567890",
            channel_id="D123456",
            thread_ts="1234567800",
        )
        assert msg.thread_ts == "1234567800"

    def test_direct_message_response_has_sources(self):
        """Test DirectMessageResponse has optional sources."""
        response = DirectMessageResponse(
            advisor_key="data_analyst",
            response_text="Analysis",
            generated_at="2024-08-04T10:00:00",
            sources=["source1", "source2"],
        )
        assert response.sources == ["source1", "source2"]
