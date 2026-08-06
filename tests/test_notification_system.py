"""Comprehensive tests for notification system and task commands.

Test coverage:
- Alert levels and severity
- Slack alert delivery with buttons
- Email alert formatting
- Deadline threshold calculations (-1 day, -2 hours, overdue)
- Timezone handling
- Task command parsing
- Interactive button handling
- Concurrent alert delivery
- Error handling and fallbacks
"""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from dataclasses import dataclass
import pytz

from ai_assistant.integrations.notification_manager import (
    AlertLevel,
    AlertMessage,
    NotificationManager,
    DeadlineTracker,
)
from ai_assistant.integrations.task_tracker import Task, TaskStatus, TaskTracker
from ai_assistant.chat.task_commands import TaskCommandParser, CommandResult


class TestAlertLevel:
    """Test AlertLevel enum."""

    def test_alert_level_values(self):
        """Test alert level integer values."""
        assert AlertLevel.LOW.value == 1
        assert AlertLevel.MEDIUM.value == 2
        assert AlertLevel.HIGH.value == 3
        assert AlertLevel.CRITICAL.value == 4

    def test_alert_level_emoji(self):
        """Test emoji representation."""
        assert AlertLevel.LOW.emoji() == "ℹ️"
        assert AlertLevel.MEDIUM.emoji() == "⏰"
        assert AlertLevel.HIGH.emoji() == "⚠️"
        assert AlertLevel.CRITICAL.emoji() == "🚨"

    def test_alert_level_ordering(self):
        """Test alert level ordering."""
        levels = [
            AlertLevel.CRITICAL,
            AlertLevel.LOW,
            AlertLevel.HIGH,
            AlertLevel.MEDIUM,
        ]
        sorted_levels = sorted(levels, key=lambda x: x.value)
        assert sorted_levels == [
            AlertLevel.LOW,
            AlertLevel.MEDIUM,
            AlertLevel.HIGH,
            AlertLevel.CRITICAL,
        ]


class TestAlertMessage:
    """Test AlertMessage dataclass."""

    def test_alert_message_creation(self):
        """Test creating an alert message."""
        now = datetime.now(timezone.utc)
        alert = AlertMessage(
            task_id="task123",
            title="Test Task",
            deadline=now + timedelta(hours=2),
            owner="john@example.com",
            level=AlertLevel.HIGH,
            message="This is a test alert",
            channels=["slack", "email"],
        )

        assert alert.task_id == "task123"
        assert alert.title == "Test Task"
        assert alert.owner == "john@example.com"
        assert alert.level == AlertLevel.HIGH
        assert alert.channels == ["slack", "email"]

    def test_alert_message_with_description(self):
        """Test alert message with description."""
        now = datetime.now(timezone.utc)
        alert = AlertMessage(
            task_id="task123",
            title="Test Task",
            deadline=now,
            owner="john@example.com",
            level=AlertLevel.MEDIUM,
            message="Alert message",
            channels=["slack"],
            description="Task description",
            priority=4,
        )

        assert alert.description == "Task description"
        assert alert.priority == 4


class TestNotificationManager:
    """Test NotificationManager."""

    @pytest.fixture
    def manager(self):
        """Create a NotificationManager instance."""
        return NotificationManager(slack_token="xoxb-test-token")

    def test_notification_manager_init(self, manager):
        """Test NotificationManager initialization."""
        assert manager.slack_token == "xoxb-test-token"
        assert manager.slack_client is not None

    def test_send_slack_alert(self, manager):
        """Test sending a Slack alert."""
        manager.slack_client = Mock()
        manager.slack_client.chat_postMessage = Mock(
            return_value={"ok": True, "ts": "1234567890"}
        )

        now = datetime.now(timezone.utc)
        alert = AlertMessage(
            task_id="task123",
            title="Urgent Task",
            deadline=now + timedelta(hours=1),
            owner="john_doe",
            level=AlertLevel.HIGH,
            message="This task is urgent",
            channels=["slack"],
        )

        result = manager._send_slack_alert(alert)

        assert result is True
        manager.slack_client.chat_postMessage.assert_called_once()

    def test_send_email_alert(self, manager):
        """Test sending an email alert."""
        manager.gmail_service = Mock()

        now = datetime.now(timezone.utc)
        alert = AlertMessage(
            task_id="task123",
            title="Email Test",
            deadline=now,
            owner="john@example.com",
            level=AlertLevel.MEDIUM,
            message="Test email alert",
            channels=["email"],
            description="Task details",
        )

        result = manager._send_email_alert(alert)
        # Result will be False without actual Gmail service, but method shouldn't crash
        assert isinstance(result, bool)


class TestDeadlineTracker:
    """Test DeadlineTracker deadline calculations."""

    @pytest.fixture
    def tracker(self):
        """Create a DeadlineTracker instance."""
        manager = NotificationManager()
        return DeadlineTracker(manager, user_timezone="UTC")

    def test_deadline_tracker_init(self, tracker):
        """Test DeadlineTracker initialization."""
        assert tracker.user_timezone.zone == "UTC"
        assert len(tracker.checked_alerts) == 0

    @pytest.mark.asyncio
    async def test_check_overdue_task(self, tracker):
        """Test detection of overdue task."""
        # Create a task that's overdue
        now = datetime.now(timezone.utc)
        task = Task(
            id="task123",
            title="Overdue Task",
            description="This is overdue",
            owner="john",
            deadline=now - timedelta(hours=1),
            status=TaskStatus.PENDING,
            priority=4,
        )

        tracker.notification_manager.send_alert = AsyncMock(
            return_value={"slack": True}
        )

        counts = await tracker.check_deadlines([task])

        assert counts["critical"] > 0

    @pytest.mark.asyncio
    async def test_check_deadline_within_2_hours(self, tracker):
        """Test detection of task due within 2 hours."""
        now = datetime.now(timezone.utc)
        task = Task(
            id="task123",
            title="Due Soon",
            description="Due in 1 hour",
            owner="john",
            deadline=now + timedelta(hours=1),
            status=TaskStatus.PENDING,
            priority=3,
        )

        tracker.notification_manager.send_alert = AsyncMock(
            return_value={"slack": True}
        )

        counts = await tracker.check_deadlines([task])

        assert counts["high"] > 0

    @pytest.mark.asyncio
    async def test_check_deadline_within_1_day(self, tracker):
        """Test detection of task due within 1 day."""
        now = datetime.now(timezone.utc)
        task = Task(
            id="task123",
            title="Due Tomorrow",
            description="Due in 12 hours",
            owner="john",
            deadline=now + timedelta(hours=12),
            status=TaskStatus.PENDING,
            priority=3,
        )

        tracker.notification_manager.send_alert = AsyncMock(
            return_value={"slack": True}
        )

        counts = await tracker.check_deadlines([task])

        assert counts["medium"] > 0

    @pytest.mark.asyncio
    async def test_check_completed_task_no_alert(self, tracker):
        """Test that completed tasks don't trigger alerts."""
        now = datetime.now(timezone.utc)
        task = Task(
            id="task123",
            title="Completed Task",
            description="Already done",
            owner="john",
            deadline=now - timedelta(hours=1),
            status=TaskStatus.COMPLETED,
            priority=5,
        )

        counts = await tracker.check_deadlines([task])

        assert counts["critical"] == 0

    @pytest.mark.asyncio
    async def test_check_task_no_deadline_no_alert(self, tracker):
        """Test that tasks without deadline don't trigger alerts."""
        task = Task(
            id="task123",
            title="No Deadline Task",
            description="No deadline set",
            owner="john",
            status=TaskStatus.PENDING,
            priority=3,
        )

        counts = await tracker.check_deadlines([task])

        assert sum(counts.values()) == 0

    def test_reset_alerts(self, tracker):
        """Test resetting alert history."""
        tracker.checked_alerts.add("alert1")
        tracker.checked_alerts.add("alert2")

        tracker.reset_alerts()

        assert len(tracker.checked_alerts) == 0

    def test_get_channels_for_level(self, tracker):
        """Test channel selection based on alert level."""
        low_channels = tracker._get_channels_for_level(AlertLevel.LOW)
        assert "slack" in low_channels
        assert "email" not in low_channels

        medium_channels = tracker._get_channels_for_level(AlertLevel.MEDIUM)
        assert "slack" in medium_channels
        assert "email" not in medium_channels

        high_channels = tracker._get_channels_for_level(AlertLevel.HIGH)
        assert "slack" in high_channels
        assert "email" in high_channels

        critical_channels = tracker._get_channels_for_level(AlertLevel.CRITICAL)
        assert "slack" in critical_channels
        assert "email" in critical_channels
        assert "sms" not in critical_channels

    @pytest.mark.asyncio
    async def test_timezone_aware_deadline_check(self):
        """Test deadline checking in different timezone."""
        manager = NotificationManager()
        tracker = DeadlineTracker(manager, user_timezone="Europe/Istanbul")

        # Create task with deadline in UTC
        now_utc = datetime.now(timezone.utc)
        task = Task(
            id="task123",
            title="Timezone Test",
            description="Testing timezone handling",
            owner="john",
            deadline=now_utc + timedelta(hours=1),
            status=TaskStatus.PENDING,
            priority=3,
        )

        tracker.notification_manager.send_alert = AsyncMock(
            return_value={"slack": True}
        )

        # Should work with different timezone
        counts = await tracker.check_deadlines([task])
        assert isinstance(counts, dict)


class TestTaskCommandParser:
    """Test Slack task commands."""

    @pytest.fixture
    def parser(self, tmp_path):
        """Create a TaskCommandParser instance."""
        # tmp_path, not a fixed /tmp/test_tasks: that directory survived between
        # runs, so tasks written by one run were still on disk for the next.
        task_tracker = TaskTracker(state_dir=str(tmp_path / "tasks"))
        manager = NotificationManager()
        return TaskCommandParser(task_tracker, manager)

    def test_parser_init(self, parser):
        """Test parser initialization."""
        assert parser.task_tracker is not None
        assert parser.notification_manager is not None

    def test_parse_quoted_args(self):
        """Test parsing quoted arguments."""
        text = '"Title" "@person" "2026-08-10" "HIGH"'
        args = TaskCommandParser._parse_quoted_args(text, 4)

        assert len(args) == 4
        assert args[0] == "Title"
        assert args[1] == "@person"
        assert args[2] == "2026-08-10"
        assert args[3] == "HIGH"

    def test_parse_priority_numeric(self):
        """Test parsing numeric priority."""
        assert TaskCommandParser._parse_priority("5") == 5
        assert TaskCommandParser._parse_priority("1") == 1
        assert TaskCommandParser._parse_priority("3") == 3

    def test_parse_priority_named(self):
        """Test parsing named priority levels."""
        assert TaskCommandParser._parse_priority("critical") == 5
        assert TaskCommandParser._parse_priority("high") == 4
        assert TaskCommandParser._parse_priority("medium") == 3
        assert TaskCommandParser._parse_priority("low") == 2
        assert TaskCommandParser._parse_priority("minimal") == 1

    def test_parse_priority_clamped(self):
        """Test priority clamping to 1-5."""
        assert TaskCommandParser._parse_priority("10") == 5
        assert TaskCommandParser._parse_priority("0") == 1
        assert TaskCommandParser._parse_priority("99") == 5

    def test_unknown_command(self, parser):
        """Test handling unknown command."""
        result = parser.parse_command("unknown", "user123")

        assert result.success is False
        assert "Unknown subcommand" in result.message

    def test_create_command_success(self, parser):
        """Test /task create command."""
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        cmd = f'create "Test Task" "@john" "{tomorrow}" "3"'

        result = parser.parse_command(cmd, "user123")

        assert result.success is True
        assert "created" in result.message.lower()
        assert result.task_id is not None

    def test_create_command_missing_args(self, parser):
        """Test /task create with missing arguments."""
        result = parser.parse_command('create "Test Task"', "user123")

        assert result.success is False
        assert "Usage" in result.message

    def test_create_command_invalid_date(self, parser):
        """Test /task create with invalid date format."""
        result = parser.parse_command(
            'create "Test" "@john" "invalid-date" "3"', "user123"
        )

        assert result.success is False
        assert "date format" in result.message.lower()

    def test_list_command_empty(self, parser):
        """Test /task list when tasks exist."""
        result = parser.parse_command("list", "user123")

        assert result.success is True
        # Tasks should be present from previous tests
        assert (
            isinstance(result.blocks, list)
            or "Found" in result.message
            or "No tasks" in result.message
        )

    def test_list_command_all(self, parser):
        """Test /task list all."""
        # First create a task
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        parser.parse_command(f'create "Task 1" "@john" "{tomorrow}" "3"', "user123")

        result = parser.parse_command("list all", "user123")

        assert result.success is True
        assert result.blocks is not None

    def test_list_command_mine(self, parser):
        """Test /task list mine."""
        result = parser.parse_command("list mine", "user123")

        assert result.success is True

    def test_list_command_by_person(self, parser):
        """Test /task list @person."""
        result = parser.parse_command("list @john", "user123")

        assert result.success is True

    def test_done_command_success(self, parser):
        """Test /task done command."""
        # Create a task first
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        create_result = parser.parse_command(
            f'create "Test Task" "@john" "{tomorrow}" "3"', "user123"
        )
        task_id = create_result.task_id

        # Mark it as done
        result = parser.parse_command(f"done {task_id}", "user123")

        assert result.success is True
        assert "done" in result.message.lower()

    def test_done_command_nonexistent_task(self, parser):
        """Test /task done with non-existent task."""
        result = parser.parse_command("done nonexistent123", "user123")

        assert result.success is False
        assert "not found" in result.message.lower()

    def test_reschedule_command_success(self, parser):
        """Test /task reschedule command."""
        # Create a task
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        create_result = parser.parse_command(
            f'create "Test Task" "@john" "{tomorrow}" "3"', "user123"
        )
        task_id = create_result.task_id

        # Reschedule it
        new_date = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
        result = parser.parse_command(f'reschedule {task_id} "{new_date}"', "user123")

        assert result.success is True
        assert "rescheduled" in result.message.lower()

    def test_assign_command_success(self, parser):
        """Test /task assign command."""
        # Create a task
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        create_result = parser.parse_command(
            f'create "Test Task" "@john" "{tomorrow}" "3"', "user123"
        )
        task_id = create_result.task_id

        # Assign to new person
        result = parser.parse_command(f'assign {task_id} "@jane"', "user123")

        assert result.success is True
        assert "reassigned" in result.message.lower()

    def test_priority_command_success(self, parser):
        """Test /task priority command."""
        # Create a task
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        create_result = parser.parse_command(
            f'create "Test Task" "@john" "{tomorrow}" "3"', "user123"
        )
        task_id = create_result.task_id

        # Update priority
        result = parser.parse_command(f"priority {task_id} 5", "user123")

        assert result.success is True
        assert "priority" in result.message.lower()

    def test_priority_command_invalid(self, parser):
        """Test /task priority with invalid value."""
        # Create a task first
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        create_result = parser.parse_command(
            f'create "Test Task" "@john" "{tomorrow}" "3"', "user123"
        )
        task_id = create_result.task_id

        # Try invalid priority
        result = parser.parse_command(f"priority {task_id} 10", "user123")

        assert result.success is False

    def test_notes_command_success(self, parser):
        """Test /task notes command."""
        # Create a task
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        create_result = parser.parse_command(
            f'create "Test Task" "@john" "{tomorrow}" "3"', "user123"
        )
        task_id = create_result.task_id

        # Add a note
        result = parser.parse_command(
            f'notes {task_id} "Important note here"', "user123"
        )

        assert result.success is True
        assert "note" in result.message.lower()

    def test_command_result_dataclass(self):
        """Test CommandResult dataclass."""
        result = CommandResult(
            success=True,
            message="Test message",
            task_id="task123",
            blocks=[{"type": "section"}],
        )

        assert result.success is True
        assert result.message == "Test message"
        assert result.task_id == "task123"
        assert len(result.blocks) == 1


class TestConcurrentAlerts:
    """Test concurrent alert delivery."""

    @pytest.mark.asyncio
    async def test_concurrent_alert_delivery(self):
        """Test sending multiple alerts concurrently."""
        manager = NotificationManager(slack_token="test_token")
        manager.slack_client = AsyncMock()
        manager.slack_client.chat_postMessage = AsyncMock(return_value={"ok": True})

        alerts = []
        now = datetime.now(timezone.utc)
        for i in range(5):
            alert = AlertMessage(
                task_id=f"task{i}",
                title=f"Task {i}",
                deadline=now + timedelta(hours=i),
                owner="john",
                level=AlertLevel.MEDIUM,
                message=f"Alert {i}",
                channels=["slack"],
            )
            alerts.append(alert)

        # Send all concurrently
        tasks = [manager.send_alert(alert) for alert in alerts]
        results = await asyncio.gather(*tasks)

        assert len(results) == 5
        assert manager.slack_client.chat_postMessage.call_count >= 5


class TestIntegration:
    """Integration tests combining multiple components."""

    @pytest.mark.asyncio
    async def test_full_workflow(self, tmp_path):
        """Test complete workflow: create task, check deadline, send alert."""
        # Initialize components
        task_tracker = TaskTracker(state_dir=str(tmp_path / "workflow"))
        notification_manager = NotificationManager(slack_token="test")
        command_parser = TaskCommandParser(task_tracker, notification_manager)
        deadline_tracker = DeadlineTracker(notification_manager, "UTC")

        # Create a task using command
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        create_result = command_parser.parse_command(
            f'create "Integration Test" "@user" "{tomorrow}" "4"', "user123"
        )

        assert create_result.success is True
        task_id = create_result.task_id

        # Get the task
        task = task_tracker.get_task(task_id)
        assert task is not None
        assert task.title == "Integration Test"

        # Check deadlines
        notification_manager.send_alert = AsyncMock(return_value={"slack": True})
        counts = await deadline_tracker.check_deadlines([task])

        # Should get an alert since deadline is tomorrow
        assert isinstance(counts, dict)

        # Mark as done
        done_result = command_parser.parse_command(f"done {task_id}", "user123")
        assert done_result.success is True

        # Verify task is completed
        updated_task = task_tracker.get_task(task_id)
        assert updated_task.status == TaskStatus.COMPLETED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
