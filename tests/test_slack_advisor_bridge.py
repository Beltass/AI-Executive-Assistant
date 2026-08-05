"""Tests for Slack Advisor Bridge system.

Comprehensive test suite covering:
- Daily update formatting and posting
- Advisor command parsing
- Drive document handling
- Thread persistence
- Multi-turn conversations
- Error handling and retry
- Concurrent requests
- Request state management
- Scheduler reliability
"""

from __future__ import annotations

import asyncio
import json
import os
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from src.ai_assistant.integrations.slack_advisor_bridge import (
    SlackAdvisorBridge,
    AdvisorThreadManager,
    AdvisorRequestManager,
    AdvisorRequest,
    SlackUpdate,
    ADVISOR_NAMES,
    ADVISOR_DESCRIPTIONS,
)
from src.ai_assistant.integrations.advisor_daily_scheduler import (
    AdvisorDailyScheduler,
    AdvisorUpdateTask,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_state_dir(tmp_path):
    """Temporary state directory for tests."""
    state_dir = tmp_path / ".assistant_state"
    state_dir.mkdir()
    yield str(state_dir)
    # Cleanup
    import shutil
    shutil.rmtree(state_dir, ignore_errors=True)


@pytest.fixture
def mock_slack_client():
    """Mock Slack AsyncWebClient."""
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "1234567890.123456"})
    client.chat_getThreadReplies = AsyncMock(return_value={"ok": True, "messages": []})
    return client


@pytest.fixture
def mock_drive_manager():
    """Mock GoogleDriveManager."""
    manager = Mock()
    manager.upload_file = Mock(return_value="file_id_123")
    manager.create_folder = Mock(return_value="folder_id_456")
    manager.share_file = Mock(return_value=True)
    return manager


@pytest.fixture
def mock_notification_manager():
    """Mock NotificationManager."""
    manager = Mock()
    manager.send_alert = AsyncMock(return_value=True)
    return manager


@pytest.fixture
def slack_bridge(mock_slack_client, mock_drive_manager, mock_notification_manager, temp_state_dir):
    """Initialize SlackAdvisorBridge with mocks."""
    with patch.dict(os.environ, {"STATE_DIR": temp_state_dir}):
        bridge = SlackAdvisorBridge(
            slack_token="xoxb-test-token",
            slack_client=mock_slack_client,
            drive_manager=mock_drive_manager,
            notification_manager=mock_notification_manager,
        )
        bridge.thread_manager.state_file = os.path.join(temp_state_dir, "advisor_threads.json")
        bridge.request_manager.state_file = os.path.join(temp_state_dir, "advisor_requests.json")
        yield bridge


@pytest.fixture
def daily_scheduler(slack_bridge, mock_drive_manager):
    """Initialize AdvisorDailyScheduler with mocks."""
    scheduler = AdvisorDailyScheduler(
        slack_bridge=slack_bridge,
        drive_manager=mock_drive_manager,
        update_hour=7,
        advisors_to_update=["data_analyst", "social_media_coach"],
    )
    yield scheduler


# ============================================================================
# Tests: Daily Update Formatting
# ============================================================================


class TestDailyUpdateFormatting:
    """Test daily advisor update message formatting."""

    def test_build_update_blocks_basic(self, slack_bridge):
        """Test building update blocks with basic content."""
        report_data = {
            "summary": "📊 Günlük veri analiz raporu",
            "drive_links": {"report": "https://drive.google.com/file/d/123"},
            "timestamp": datetime.now(),
        }

        blocks = slack_bridge._build_update_blocks("data_analyst", report_data)

        assert len(blocks) > 0
        assert blocks[0]["type"] == "header"
        assert "Veri Analisti" in blocks[0]["text"]["text"]
        assert "Günlük Rapor" in blocks[0]["text"]["text"]

    def test_build_update_blocks_with_multiple_links(self, slack_bridge):
        """Test update blocks with multiple Drive links."""
        report_data = {
            "summary": "Multi-file report",
            "drive_links": {
                "report": "https://drive.google.com/file/d/report_123",
                "data": "https://docs.google.com/spreadsheets/d/data_456",
                "analysis": "https://drive.google.com/file/d/analysis_789",
            },
            "timestamp": datetime.now(),
        }

        blocks = slack_bridge._build_update_blocks("data_analyst", report_data)

        # Find fields section
        fields_section = next((b for b in blocks if b.get("type") == "section" and "fields" in b), None)
        assert fields_section is not None
        assert len(fields_section["fields"]) >= 3

    def test_build_update_blocks_all_advisors(self, slack_bridge):
        """Test update blocks for all advisor types."""
        report_data = {
            "summary": "Test summary",
            "drive_links": {"report": "https://example.com"},
            "timestamp": datetime.now(),
        }

        for advisor_key in ["data_analyst", "linkedin_coach", "social_media_coach", "personal_assistant"]:
            blocks = slack_bridge._build_update_blocks(advisor_key, report_data)
            advisor_name = ADVISOR_NAMES[advisor_key]

            assert any(advisor_name in str(block) for block in blocks), f"Advisor name not found for {advisor_key}"

    def test_build_result_blocks_basic(self, slack_bridge):
        """Test building result blocks for completed task."""
        result = {"summary": "✅ Analiz başarıyla tamamlandı"}
        drive_links = {"report": "https://drive.google.com/file/d/123"}

        blocks = slack_bridge._build_result_blocks("data_analyst", result, drive_links)

        assert len(blocks) > 0
        assert any("tamamlandı" in str(b).lower() for b in blocks)

    def test_build_result_blocks_empty_links(self, slack_bridge):
        """Test result blocks with no Drive links."""
        result = {"summary": "Analysis complete"}

        blocks = slack_bridge._build_result_blocks("data_analyst", result, {})

        assert len(blocks) > 0
        # Should still have result text, just no drive links section


# ============================================================================
# Tests: Advisor Request Handling
# ============================================================================


class TestAdvisorRequestHandling:
    """Test advisor request processing."""

    @pytest.mark.asyncio
    async def test_handle_advisor_request_creates_thread(self, slack_bridge):
        """Test that request handling creates or retrieves thread."""
        request_id = await slack_bridge.handle_advisor_request(
            user_id="U123456",
            advisor_key="data_analyst",
            message="Analiz yap şu CSV'yi",
        )

        assert request_id is not None
        assert "data_analyst" in request_id
        assert "U123456" in request_id

    @pytest.mark.asyncio
    async def test_handle_advisor_request_posts_status(self, slack_bridge):
        """Test that processing status message is posted."""
        await slack_bridge.handle_advisor_request(
            user_id="U123456",
            advisor_key="data_analyst",
            message="Analyze this data",
        )

        # Verify status message was posted
        slack_bridge.slack_client.chat_postMessage.assert_called()
        call_args = slack_bridge.slack_client.chat_postMessage.call_args

        assert "🔄" in call_args.kwargs["text"] or any(
            "Processing" in str(arg) or "processing" in str(arg)
            for arg in call_args.args
        )

    @pytest.mark.asyncio
    async def test_complete_advisor_request(self, slack_bridge):
        """Test completing a request and posting results."""
        # First create a request
        request_id = await slack_bridge.handle_advisor_request(
            user_id="U123456",
            advisor_key="data_analyst",
            message="Analyze data",
        )

        # Then complete it
        result = {"summary": "✅ Analysis complete", "findings": ["Item 1", "Item 2"]}
        drive_links = {
            "report": "https://drive.google.com/file/d/report_123",
            "data": "https://docs.google.com/spreadsheets/d/data_456",
        }

        success = await slack_bridge.complete_advisor_request(request_id, result, drive_links)

        assert success is True
        # Verify result was posted
        slack_bridge.slack_client.chat_postMessage.assert_called()

    @pytest.mark.asyncio
    async def test_fail_advisor_request(self, slack_bridge):
        """Test marking request as failed."""
        request_id = await slack_bridge.handle_advisor_request(
            user_id="U123456",
            advisor_key="data_analyst",
            message="Analyze data",
        )

        error_msg = "File format not supported"
        success = await slack_bridge.fail_advisor_request(request_id, error_msg)

        assert success is True


# ============================================================================
# Tests: Thread Management
# ============================================================================


class TestThreadManagement:
    """Test thread persistence and management."""

    @pytest.mark.asyncio
    async def test_get_or_create_thread(self, slack_bridge):
        """Test getting existing or creating new thread."""
        thread_ts = await slack_bridge.thread_manager.get_advisor_thread(
            advisor_key="data_analyst",
            user_id="U123456",
            slack_client=slack_bridge.slack_client,
        )

        assert thread_ts
        assert isinstance(thread_ts, str)

    @pytest.mark.asyncio
    async def test_thread_persistence(self, slack_bridge):
        """Test that thread info is persisted to file."""
        thread_ts = await slack_bridge.thread_manager.get_advisor_thread(
            advisor_key="data_analyst",
            user_id="U123456",
            slack_client=slack_bridge.slack_client,
        )

        # Load state file
        state_file = slack_bridge.thread_manager.state_file
        assert os.path.exists(state_file)

        with open(state_file, "r") as f:
            data = json.load(f)

        key = "data_analyst_U123456"
        assert key in data
        assert data[key]["ts"] == thread_ts

    @pytest.mark.asyncio
    async def test_thread_reuse(self, slack_bridge):
        """Test that existing thread is reused."""
        # Get thread first time
        thread_ts1 = await slack_bridge.thread_manager.get_advisor_thread(
            advisor_key="data_analyst",
            user_id="U123456",
            slack_client=slack_bridge.slack_client,
        )

        # Get thread second time
        thread_ts2 = await slack_bridge.thread_manager.get_advisor_thread(
            advisor_key="data_analyst",
            user_id="U123456",
        )

        assert thread_ts1 == thread_ts2

    @pytest.mark.asyncio
    async def test_different_advisors_different_threads(self, slack_bridge):
        """Test that different advisors get different threads."""
        # Setup mock to return different values for different calls
        call_count = 0
        async def get_different_ts(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return {"ok": True, "ts": f"111111111.{call_count}"}

        slack_bridge.slack_client.chat_postMessage.side_effect = get_different_ts

        thread_analyst = await slack_bridge.thread_manager.get_advisor_thread(
            advisor_key="data_analyst",
            user_id="U123456",
            slack_client=slack_bridge.slack_client,
        )

        thread_coach = await slack_bridge.thread_manager.get_advisor_thread(
            advisor_key="social_media_coach",
            user_id="U123456",
            slack_client=slack_bridge.slack_client,
        )

        assert thread_analyst != thread_coach


# ============================================================================
# Tests: Request State Management
# ============================================================================


class TestRequestManagement:
    """Test advisor request state tracking."""

    @pytest.mark.asyncio
    async def test_save_and_load_request(self, slack_bridge):
        """Test saving and loading request state."""
        request = AdvisorRequest(
            request_id="req_123",
            user_id="U123456",
            advisor_key="data_analyst",
            message="Analyze this",
            status="processing",
            thread_ts="1234567890.123456",
            created_at=datetime.now().isoformat(),
        )

        await slack_bridge.request_manager.save_request(request)

        loaded = await slack_bridge.request_manager.get_request("req_123")

        assert loaded is not None
        assert loaded.user_id == "U123456"
        assert loaded.advisor_key == "data_analyst"
        assert loaded.status == "processing"

    @pytest.mark.asyncio
    async def test_get_user_requests(self, slack_bridge):
        """Test retrieving all requests for a user."""
        user_id = "U123456"

        # Create multiple requests
        for i in range(3):
            request = AdvisorRequest(
                request_id=f"req_{i}",
                user_id=user_id,
                advisor_key="data_analyst",
                message=f"Request {i}",
                status="completed" if i < 2 else "pending",
                thread_ts=f"1234567890.{i}",
                created_at=datetime.now().isoformat(),
            )
            await slack_bridge.request_manager.save_request(request)

        # Get all requests
        all_requests = await slack_bridge.request_manager.get_user_requests(user_id)
        assert len(all_requests) == 3

        # Get only completed
        completed = await slack_bridge.request_manager.get_user_requests(
            user_id, status="completed"
        )
        assert len(completed) == 2

    @pytest.mark.asyncio
    async def test_request_sorting(self, slack_bridge):
        """Test that requests are sorted by creation time."""
        user_id = "U123456"
        now = datetime.now()

        for i in range(3):
            request = AdvisorRequest(
                request_id=f"req_{i}",
                user_id=user_id,
                advisor_key="data_analyst",
                message=f"Request {i}",
                status="completed",
                thread_ts=f"1234567890.{i}",
                created_at=(now - timedelta(days=i)).isoformat(),
            )
            await slack_bridge.request_manager.save_request(request)

        requests = await slack_bridge.request_manager.get_user_requests(user_id)

        # Should be sorted newest first
        for i in range(len(requests) - 1):
            assert requests[i].created_at >= requests[i + 1].created_at

    @pytest.mark.asyncio
    async def test_cleanup_old_requests(self, slack_bridge):
        """Test cleaning up requests older than N days."""
        user_id = "U123456"
        now = datetime.now()

        # Create old request (31 days old)
        old_request = AdvisorRequest(
            request_id="old_req",
            user_id=user_id,
            advisor_key="data_analyst",
            message="Old request",
            status="completed",
            thread_ts="1234567890.old",
            created_at=(now - timedelta(days=31)).isoformat(),
        )

        # Create recent request (5 days old)
        new_request = AdvisorRequest(
            request_id="new_req",
            user_id=user_id,
            advisor_key="data_analyst",
            message="New request",
            status="completed",
            thread_ts="1234567890.new",
            created_at=(now - timedelta(days=5)).isoformat(),
        )

        await slack_bridge.request_manager.save_request(old_request)
        await slack_bridge.request_manager.save_request(new_request)

        # Cleanup requests older than 30 days
        removed = await slack_bridge.request_manager.cleanup_old_requests(days=30)

        assert removed == 1

        # Verify old request is gone
        remaining = await slack_bridge.request_manager.get_user_requests(user_id)
        assert len(remaining) == 1
        assert remaining[0].request_id == "new_req"


# ============================================================================
# Tests: Daily Scheduler
# ============================================================================


class TestDailyScheduler:
    """Test advisor daily scheduler."""

    @pytest.mark.asyncio
    async def test_scheduler_configuration(self, daily_scheduler):
        """Test scheduler configuration."""
        config = daily_scheduler.get_update_schedule()

        assert config["update_hour"] == 7
        assert config["advisors"] == ["data_analyst", "social_media_coach"]
        assert config["slack_bridge_configured"] is True
        assert config["drive_manager_configured"] is True

    @pytest.mark.asyncio
    async def test_register_report_generator(self, daily_scheduler):
        """Test registering report generator."""
        async def mock_generator():
            return {
                "summary": "Daily report",
                "drive_links": {"report": "https://example.com"},
                "timestamp": datetime.now(),
            }

        daily_scheduler.register_report_generator("data_analyst", mock_generator)

        assert "data_analyst" in daily_scheduler.report_generators

    @pytest.mark.asyncio
    async def test_update_advisor_with_generator(self, daily_scheduler):
        """Test updating single advisor with registered generator."""
        async def mock_generator():
            return {
                "summary": "Test report",
                "drive_links": {"report": "https://example.com/report"},
                "timestamp": datetime.now(),
            }

        daily_scheduler.register_report_generator("data_analyst", mock_generator)

        result = await daily_scheduler._update_advisor("data_analyst")

        assert result is True
        daily_scheduler.slack_bridge.slack_client.chat_postMessage.assert_called()

    @pytest.mark.asyncio
    async def test_schedule_multiple_advisors(self, daily_scheduler):
        """Test scheduling updates for multiple advisors."""
        async def mock_generator():
            return {
                "summary": "Report",
                "drive_links": {},
                "timestamp": datetime.now(),
            }

        daily_scheduler.register_report_generator("data_analyst", mock_generator)
        daily_scheduler.register_report_generator("social_media_coach", mock_generator)

        results = await daily_scheduler.schedule_advisor_updates()

        assert len(results) == 2
        assert all(isinstance(v, bool) for v in results.values())

    def test_configured_advisors_from_env(self):
        """Test reading advisors from environment."""
        with patch.dict(os.environ, {"SLACK_ADVISOR_INCLUDE": "data_analyst,social_media_coach"}):
            advisors = AdvisorDailyScheduler._get_configured_advisors()
            assert advisors == ["data_analyst", "social_media_coach"]

    def test_default_advisors_when_env_empty(self):
        """Test default advisors when environment var not set."""
        with patch.dict(os.environ, {}, clear=False):
            if "SLACK_ADVISOR_INCLUDE" in os.environ:
                del os.environ["SLACK_ADVISOR_INCLUDE"]
            advisors = AdvisorDailyScheduler._get_configured_advisors()
            assert len(advisors) > 0


# ============================================================================
# Tests: Update Task Management
# ============================================================================


class TestUpdateTask:
    """Test AdvisorUpdateTask."""

    def test_task_creation(self):
        """Test creating update task."""
        scheduled_time = datetime.now() + timedelta(hours=1)
        task = AdvisorUpdateTask(
            advisor_key="data_analyst",
            scheduled_for=scheduled_time,
            max_retries=3,
        )

        assert task.advisor_key == "data_analyst"
        assert task.retry_count == 0
        assert task.last_error is None

    def test_task_retry_logic(self):
        """Test task retry logic."""
        task = AdvisorUpdateTask(
            advisor_key="data_analyst",
            scheduled_for=datetime.now(),
            max_retries=2,
        )

        assert task.should_retry() is True

        task.mark_failed("Test error")
        assert task.retry_count == 1
        assert task.should_retry() is True

        task.mark_failed("Another error")
        assert task.retry_count == 2
        assert task.should_retry() is False

    def test_task_success_mark(self):
        """Test marking task successful."""
        task = AdvisorUpdateTask(
            advisor_key="data_analyst",
            scheduled_for=datetime.now(),
        )

        task.mark_failed("Error")
        assert task.last_error is not None

        task.mark_success()
        assert task.last_error is None


# ============================================================================
# Tests: Error Handling
# ============================================================================


class TestErrorHandling:
    """Test error handling and recovery."""

    @pytest.mark.asyncio
    async def test_handle_missing_slack_client(self):
        """Test handling when Slack client not configured."""
        bridge = SlackAdvisorBridge(slack_token="test")

        request_id = await bridge.handle_advisor_request(
            user_id="U123",
            advisor_key="data_analyst",
            message="Test",
        )

        assert request_id is None

    @pytest.mark.asyncio
    async def test_handle_slack_error_gracefully(self, slack_bridge):
        """Test graceful handling of Slack API errors."""
        slack_bridge.slack_client.chat_postMessage.side_effect = Exception("Slack API error")

        request_id = await slack_bridge.handle_advisor_request(
            user_id="U123456",
            advisor_key="data_analyst",
            message="Test",
        )

        assert request_id is None

    @pytest.mark.asyncio
    async def test_invalid_advisor_key(self, slack_bridge):
        """Test handling invalid advisor key."""
        request_id = await slack_bridge.handle_advisor_request(
            user_id="U123456",
            advisor_key="invalid_advisor",
            message="Test",
        )

        # Should still create request but with generic name
        assert request_id is not None


# ============================================================================
# Tests: Concurrent Operations
# ============================================================================


class TestConcurrentOperations:
    """Test concurrent request handling."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_same_advisor(self, slack_bridge):
        """Test multiple concurrent requests to same advisor."""
        tasks = [
            slack_bridge.handle_advisor_request(
                user_id=f"U{i}",
                advisor_key="data_analyst",
                message=f"Request {i}",
            )
            for i in range(5)
        ]

        request_ids = await asyncio.gather(*tasks)

        assert len(request_ids) == 5
        assert all(rid is not None for rid in request_ids)
        assert len(set(request_ids)) == 5  # All unique

    @pytest.mark.asyncio
    async def test_concurrent_requests_different_advisors(self, slack_bridge):
        """Test concurrent requests across different advisors."""
        tasks = [
            slack_bridge.handle_advisor_request(
                user_id="U123",
                advisor_key="data_analyst" if i % 2 == 0 else "social_media_coach",
                message=f"Request {i}",
            )
            for i in range(4)
        ]

        request_ids = await asyncio.gather(*tasks)

        assert len(request_ids) == 4
        assert all(rid is not None for rid in request_ids)

    @pytest.mark.asyncio
    async def test_concurrent_completion(self, slack_bridge):
        """Test completing multiple requests concurrently."""
        # Create requests
        request_ids = []
        for i in range(3):
            rid = await slack_bridge.handle_advisor_request(
                user_id=f"U{i}",
                advisor_key="data_analyst",
                message=f"Request {i}",
            )
            request_ids.append(rid)

        # Complete concurrently
        tasks = [
            slack_bridge.complete_advisor_request(
                rid,
                {"summary": f"Result {i}"},
                {"report": f"https://example.com/{i}"},
            )
            for i, rid in enumerate(request_ids)
        ]

        results = await asyncio.gather(*tasks)

        assert all(results)
        assert slack_bridge.slack_client.chat_postMessage.call_count >= 6  # 3 requests + 3 completions


# ============================================================================
# Tests: Multi-turn Conversations
# ============================================================================


class TestMultiTurnConversations:
    """Test multi-turn conversation support."""

    @pytest.mark.asyncio
    async def test_multiple_requests_same_user_advisor(self, slack_bridge):
        """Test multiple requests from same user to same advisor in same thread."""
        user_id = "U123456"
        advisor_key = "data_analyst"

        # First request
        req_id_1 = await slack_bridge.handle_advisor_request(
            user_id=user_id,
            advisor_key=advisor_key,
            message="First request",
        )

        # Get thread
        thread_1 = await slack_bridge.thread_manager.get_advisor_thread(
            advisor_key=advisor_key,
            user_id=user_id,
        )

        # Add small delay to ensure different timestamp
        await asyncio.sleep(0.01)

        # Second request - should use same thread
        req_id_2 = await slack_bridge.handle_advisor_request(
            user_id=user_id,
            advisor_key=advisor_key,
            message="Second request",
        )

        thread_2 = await slack_bridge.thread_manager.get_advisor_thread(
            advisor_key=advisor_key,
            user_id=user_id,
        )

        assert thread_1 == thread_2
        assert req_id_1 != req_id_2

    @pytest.mark.asyncio
    async def test_follow_up_in_same_thread(self, slack_bridge):
        """Test follow-up conversations use same thread."""
        user_id = "U123456"

        # Initial request
        req_id_1 = await slack_bridge.handle_advisor_request(
            user_id=user_id,
            advisor_key="data_analyst",
            message="Show trends",
        )

        thread_ts_1 = (await slack_bridge.request_manager.get_request(req_id_1)).thread_ts

        # Complete first request
        await slack_bridge.complete_advisor_request(
            req_id_1,
            {"summary": "Trends shown"},
            {"report": "https://example.com/trends"},
        )

        # Follow-up request
        req_id_2 = await slack_bridge.handle_advisor_request(
            user_id=user_id,
            advisor_key="data_analyst",
            message="Analyze anomalies",
        )

        thread_ts_2 = (await slack_bridge.request_manager.get_request(req_id_2)).thread_ts

        # Should be in same thread
        assert thread_ts_1 == thread_ts_2


# ============================================================================
# Tests: State Persistence
# ============================================================================


class TestStatePersistence:
    """Test state file persistence."""

    @pytest.mark.asyncio
    async def test_state_survives_bridge_restart(self, slack_bridge):
        """Test that state persists across bridge initialization."""
        user_id = "U123456"

        # Create thread with first bridge
        await slack_bridge.thread_manager.get_advisor_thread(
            advisor_key="data_analyst",
            user_id=user_id,
            slack_client=slack_bridge.slack_client,
        )

        # Create new bridge with same state file
        bridge2 = SlackAdvisorBridge(
            slack_token="xoxb-test-token",
            slack_client=slack_bridge.slack_client,
        )
        bridge2.thread_manager.state_file = slack_bridge.thread_manager.state_file
        bridge2.request_manager.state_file = slack_bridge.request_manager.state_file

        # Should find thread from first bridge
        thread_ts2 = await bridge2.thread_manager.get_advisor_thread(
            advisor_key="data_analyst",
            user_id=user_id,
        )

        assert thread_ts2  # Should find existing


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_full_request_lifecycle(self, slack_bridge):
        """Test complete flow: request -> processing -> completion."""
        user_id = "U123456"
        advisor_key = "data_analyst"

        # 1. User makes request
        request_id = await slack_bridge.handle_advisor_request(
            user_id=user_id,
            advisor_key=advisor_key,
            message="Analyze Q3 trends",
        )

        assert request_id is not None

        # 2. Check request is tracked
        request = await slack_bridge.request_manager.get_request(request_id)
        assert request.status == "processing"

        # 3. Complete the request
        result = {
            "summary": "Q3 showed 15% growth in user engagement",
            "key_findings": ["Growth in mobile users", "Increased session duration"],
        }
        drive_links = {
            "report": "https://drive.google.com/file/d/report",
            "data": "https://docs.google.com/spreadsheets/d/data",
        }

        success = await slack_bridge.complete_advisor_request(
            request_id, result, drive_links
        )

        assert success is True

        # 4. Verify completion
        request = await slack_bridge.request_manager.get_request(request_id)
        assert request.status == "completed"
        assert request.result == result

    @pytest.mark.asyncio
    async def test_scheduler_end_to_end(self, daily_scheduler):
        """Test scheduler with report generator."""
        report_data = {
            "summary": "Daily update for data analyst",
            "drive_links": {"report": "https://drive.google.com/file/d/123"},
            "timestamp": datetime.now(),
        }

        async def generator():
            return report_data

        daily_scheduler.register_report_generator("data_analyst", generator)

        results = await daily_scheduler.schedule_advisor_updates()

        assert results.get("data_analyst") is True


# ============================================================================
# Run Tests
# ============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
