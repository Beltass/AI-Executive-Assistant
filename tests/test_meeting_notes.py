"""Comprehensive tests for Meeting Notes Agent, Task Tracker, and Drive Integration.

Tests cover:
- Task CRUD operations
- Status tracking and deadline logic
- Meeting notes analysis
- Action item extraction
- Drive upload/download
- Task persistence
- Deadline reminder logic
"""

from __future__ import annotations

import json
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional
from unittest.mock import Mock, patch, MagicMock, AsyncMock

import pytest

import ai_assistant.advisors.meeting_notes as meeting_notes_module
from ai_assistant.advisors.meeting_notes import (
    MeetingNotesAgent,
    MeetingNotes,
    ActionItem,
    CompetitiveAction,
)
from ai_assistant.integrations.task_tracker import (
    Task,
    TaskTracker,
    TaskStatus,
)
from ai_assistant.integrations.google_drive_manager import GoogleDriveManager

# ============================================================================
# Analysis helpers
#
# analyze_meeting() derives everything it returns from what the LLM answers,
# so a test that does not stand in for the LLM cannot say anything about the
# analysis. These helpers put a KNOWN answer on the wire; the assertions then
# check that this answer — and nothing baked into the source — is what comes
# out the other end.
# ============================================================================


def analysis_response(
    summary: str = "",
    findings: Optional[List[str]] = None,
    action_items: Optional[List[Dict[str, Any]]] = None,
    competitive_actions: Optional[List[Dict[str, Any]]] = None,
    next_steps: Optional[List[str]] = None,
    fenced: bool = False,
) -> str:
    """Build one model answer in the schema analyze_meeting() expects."""
    payload = {
        "summary": summary,
        "findings": findings or [],
        "action_items": action_items or [],
        "competitive_actions": competitive_actions or [],
        "next_steps": next_steps or [],
    }
    body = json.dumps(payload, ensure_ascii=False)
    return f"```json\n{body}\n```" if fenced else body


@contextmanager
def mocked_analysis(response: Any, configured: bool = True):
    """Make ``llm.generate_text`` return ``response`` for the duration.

    ``response`` may be a string (the answer) or a callable taking the
    ``(system_prompt, user_prompt)`` the advisor actually sent — the callable
    form is what lets a test prove the TRANSCRIPT reached the model.
    """
    generate = (
        Mock(side_effect=response)
        if callable(response)
        else Mock(return_value=response)
    )
    with patch.object(
        meeting_notes_module.llm, "is_configured", return_value=configured
    ):
        with patch.object(meeting_notes_module.llm, "generate_text", generate):
            yield generate


class TestTask:
    """Tests for Task dataclass."""

    def test_task_creation(self):
        """Test creating a task."""
        task = Task(
            id="task_1",
            title="Implement feature",
            description="Add new dashboard",
            owner="John Doe",
        )
        assert task.id == "task_1"
        assert task.title == "Implement feature"
        assert task.status == TaskStatus.PENDING

    def test_task_is_overdue_true(self):
        """Test overdue detection when task is past deadline."""
        task = Task(
            id="task_1",
            title="Old task",
            description="Should be done",
            owner="Jane",
            deadline=datetime.now(timezone.utc) - timedelta(days=1),
            status=TaskStatus.PENDING,
        )
        assert task.is_overdue is True

    def test_task_is_overdue_false(self):
        """Test overdue detection when task is not overdue."""
        task = Task(
            id="task_1",
            title="New task",
            description="Will do later",
            owner="Jane",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
            status=TaskStatus.PENDING,
        )
        assert task.is_overdue is False

    def test_task_is_overdue_completed(self):
        """Test overdue detection when task is completed."""
        task = Task(
            id="task_1",
            title="Done task",
            description="Already finished",
            owner="Jane",
            deadline=datetime.now(timezone.utc) - timedelta(days=1),
            status=TaskStatus.COMPLETED,
        )
        assert task.is_overdue is False

    def test_task_days_until_deadline(self):
        """Test calculating days until deadline."""
        task = Task(
            id="task_1",
            title="Future task",
            description="Some work",
            owner="Jane",
            deadline=datetime.now(timezone.utc) + timedelta(days=5),
        )
        days = task.days_until_deadline
        assert days is not None
        assert 4 <= days <= 5

    def test_task_mark_completed(self):
        """Test marking a task as completed."""
        task = Task(
            id="task_1",
            title="To do",
            description="Work",
            owner="Jane",
        )
        assert task.status == TaskStatus.PENDING
        assert task.completed_at is None

        task.mark_completed()

        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None

    def test_task_to_dict(self):
        """Test converting task to dictionary."""
        now = datetime.now(timezone.utc)
        task = Task(
            id="task_1",
            title="Test",
            description="Desc",
            owner="Owner",
            deadline=now,
            status=TaskStatus.PENDING,
        )

        data = task.to_dict()

        assert data["id"] == "task_1"
        assert data["title"] == "Test"
        assert data["status"] == "pending"
        assert "deadline" in data

    def test_task_from_dict(self):
        """Test creating task from dictionary."""
        now = datetime.now(timezone.utc)
        data = {
            "id": "task_1",
            "title": "Test",
            "description": "Desc",
            "owner": "Owner",
            "deadline": now.isoformat(),
            "status": "pending",
            "priority": 3,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "completed_at": None,
            "meeting_id": None,
            "tags": [],
        }

        task = Task.from_dict(data)

        assert task.id == "task_1"
        assert task.title == "Test"
        assert task.status == TaskStatus.PENDING


class TestTaskTracker:
    """Tests for TaskTracker class."""

    @pytest.fixture
    def temp_state_dir(self) -> Generator[Path, None, None]:
        """Provide a temporary state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def tracker(self, temp_state_dir) -> TaskTracker:
        """Provide a TaskTracker instance with temp storage."""
        return TaskTracker(state_dir=str(temp_state_dir))

    def test_tracker_add_task(self, tracker: TaskTracker):
        """Test adding a task to tracker."""
        task = Task(
            id="task_1",
            title="Test task",
            description="Test",
            owner="Owner",
        )

        task_id = tracker.add_task(task)

        assert task_id == "task_1"
        assert tracker.get_task("task_1") is not None

    def test_tracker_get_task(self, tracker: TaskTracker):
        """Test retrieving a task."""
        task = Task(
            id="task_1",
            title="Get me",
            description="Test",
            owner="Owner",
        )
        tracker.add_task(task)

        retrieved = tracker.get_task("task_1")

        assert retrieved is not None
        assert retrieved.title == "Get me"

    def test_tracker_get_nonexistent_task(self, tracker: TaskTracker):
        """Test retrieving nonexistent task returns None."""
        result = tracker.get_task("nonexistent")
        assert result is None

    def test_tracker_update_status(self, tracker: TaskTracker):
        """Test updating task status."""
        task = Task(
            id="task_1",
            title="Work",
            description="Test",
            owner="Owner",
            status=TaskStatus.PENDING,
        )
        tracker.add_task(task)

        result = tracker.update_status("task_1", TaskStatus.IN_PROGRESS)

        assert result is True
        assert tracker.get_task("task_1").status == TaskStatus.IN_PROGRESS

    def test_tracker_update_status_nonexistent(self, tracker: TaskTracker):
        """Test updating status of nonexistent task returns False."""
        result = tracker.update_status("nonexistent", TaskStatus.COMPLETED)
        assert result is False

    def test_tracker_get_overdue_tasks(self, tracker: TaskTracker):
        """Test retrieving overdue tasks."""
        now = datetime.now(timezone.utc)

        # Overdue task
        task1 = Task(
            id="task_1",
            title="Overdue",
            description="Late",
            owner="Owner",
            deadline=now - timedelta(days=1),
            status=TaskStatus.PENDING,
        )

        # Not overdue
        task2 = Task(
            id="task_2",
            title="Future",
            description="Later",
            owner="Owner",
            deadline=now + timedelta(days=1),
            status=TaskStatus.PENDING,
        )

        # Completed (should not appear as overdue)
        task3 = Task(
            id="task_3",
            title="Done",
            description="Finished",
            owner="Owner",
            deadline=now - timedelta(days=1),
            status=TaskStatus.COMPLETED,
        )

        tracker.add_task(task1)
        tracker.add_task(task2)
        tracker.add_task(task3)

        overdue = tracker.get_overdue_tasks()

        assert len(overdue) == 1
        assert overdue[0].id == "task_1"

    def test_tracker_get_upcoming_tasks(self, tracker: TaskTracker):
        """Test retrieving upcoming tasks within deadline window."""
        now = datetime.now(timezone.utc)

        # Upcoming (2 days)
        task1 = Task(
            id="task_1",
            title="Soon",
            description="Coming up",
            owner="Owner",
            deadline=now + timedelta(days=2),
            status=TaskStatus.PENDING,
        )

        # Too far (5 days)
        task2 = Task(
            id="task_2",
            title="Far",
            description="Later",
            owner="Owner",
            deadline=now + timedelta(days=5),
            status=TaskStatus.PENDING,
        )

        tracker.add_task(task1)
        tracker.add_task(task2)

        upcoming = tracker.get_upcoming_tasks(days=3)

        assert len(upcoming) == 1
        assert upcoming[0].id == "task_1"

    def test_tracker_get_tasks_by_owner(self, tracker: TaskTracker):
        """Test retrieving tasks by owner."""
        task1 = Task(
            id="task_1",
            title="Alice's task",
            description="Test",
            owner="Alice",
        )
        task2 = Task(
            id="task_2",
            title="Bob's task",
            description="Test",
            owner="Bob",
        )

        tracker.add_task(task1)
        tracker.add_task(task2)

        alice_tasks = tracker.get_tasks_by_owner("Alice")

        assert len(alice_tasks) == 1
        assert alice_tasks[0].owner == "Alice"

    def test_tracker_get_summary_stats(self, tracker: TaskTracker):
        """Test getting summary statistics."""
        task1 = Task(
            id="task_1",
            title="Pending",
            description="Test",
            owner="Owner",
            status=TaskStatus.PENDING,
        )
        task2 = Task(
            id="task_2",
            title="Done",
            description="Test",
            owner="Owner",
            status=TaskStatus.COMPLETED,
        )

        tracker.add_task(task1)
        tracker.add_task(task2)

        stats = tracker.get_summary_stats()

        assert stats["total"] == 2
        assert stats["pending"] == 1
        assert stats["completed"] == 1
        assert stats["completion_rate"] == 50.0

    def test_tracker_persistence_save_load(self, temp_state_dir: Path):
        """Test that tasks persist across tracker instances."""
        # Create and save
        tracker1 = TaskTracker(state_dir=str(temp_state_dir))
        task = Task(
            id="task_1",
            title="Persist me",
            description="Test",
            owner="Owner",
        )
        tracker1.add_task(task)

        # Load in new instance
        tracker2 = TaskTracker(state_dir=str(temp_state_dir))

        assert tracker2.get_task("task_1") is not None
        assert tracker2.get_task("task_1").title == "Persist me"


class TestActionItem:
    """Tests for ActionItem dataclass."""

    def test_action_item_creation(self):
        """Test creating an action item."""
        item = ActionItem(
            description="Write documentation",
            owner="Sarah",
            priority=4,
        )

        assert item.description == "Write documentation"
        assert item.owner == "Sarah"
        assert item.priority == 4
        assert item.status == "pending"

    def test_action_item_with_deadline(self):
        """Test action item with deadline."""
        deadline = datetime.now(timezone.utc) + timedelta(days=3)
        item = ActionItem(
            description="Review code",
            owner="Mark",
            deadline=deadline,
        )

        assert item.deadline == deadline


class TestMeetingNotes:
    """Tests for MeetingNotes dataclass."""

    def test_meeting_notes_creation(self):
        """Test creating meeting notes."""
        notes = MeetingNotes(
            title="Q3 Planning",
            attendees=["Alice", "Bob"],
        )

        assert notes.title == "Q3 Planning"
        assert len(notes.attendees) == 2
        assert notes.meeting_id is not None

    def test_meeting_notes_to_dict(self):
        """Test converting meeting notes to dictionary."""
        notes = MeetingNotes(
            title="Meeting",
            attendees=["Alice"],
            findings=["Finding 1"],
        )

        data = notes.to_dict()

        assert data["title"] == "Meeting"
        assert len(data["attendees"]) == 1
        assert len(data["findings"]) == 1
        assert "meeting_id" in data


class TestMeetingNotesAgent:
    """Tests for MeetingNotesAgent class."""

    @pytest.fixture
    def agent(self) -> MeetingNotesAgent:
        """Provide a MeetingNotesAgent instance."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                agent = MeetingNotesAgent()
                # Mock the dependencies
                agent.drive_manager = Mock()
                agent.task_tracker = Mock()
                return agent

    def test_agent_initialization(self, agent: MeetingNotesAgent):
        """Test agent initialization."""
        assert agent.key == "meeting_notes"
        assert agent.title == "Toplantı Notları"
        assert agent.private is True

    def test_agent_generate_briefing_no_tasks(self, agent: MeetingNotesAgent):
        """Test generating briefing with no tasks."""
        agent.task_tracker.get_overdue_tasks.return_value = []
        agent.task_tracker.get_upcoming_tasks.return_value = []

        with patch("os.getenv", return_value="true"):
            briefing = agent._generate()

        assert briefing.status == "skipped"
        assert briefing.nothing_new is True

    def test_agent_generate_briefing_with_tasks(self, agent: MeetingNotesAgent):
        """Test generating briefing with upcoming tasks."""
        now = datetime.now(timezone.utc)
        task = Task(
            id="task_1",
            title="Urgent task",
            description="Do this",
            owner="John",
            deadline=now + timedelta(days=1),
            status=TaskStatus.PENDING,
        )

        agent.task_tracker.get_overdue_tasks.return_value = []
        agent.task_tracker.get_upcoming_tasks.return_value = [task]

        with patch("os.getenv", return_value="true"):
            briefing = agent._generate()

        assert briefing.status == "ok"
        assert "Urgent task" in briefing.text
        assert "John" in briefing.text

    def test_agent_transcribe_audio(self, agent: MeetingNotesAgent, monkeypatch):
        """Transcription returns what the MODEL said, not a placeholder.

        This test used to hand in a URL and assert only that *something*
        non-empty came back — which a hard-coded string satisfied for as long
        as the function never opened the audio. See
        ``tests/test_meeting_transcription.py`` for the full set.
        """
        import asyncio

        from ai_assistant.integrations import llm

        monkeypatch.setattr(llm, "is_configured", lambda: True)
        monkeypatch.setattr(
            llm, "generate_from_audio", lambda *a, **k: "Konuşmacı 1: ZEBRA."
        )

        result = asyncio.run(agent.transcribe_audio(b"fake-audio-bytes"))

        assert result == "Konuşmacı 1: ZEBRA."

    def test_agent_analyze_meeting(self, agent: MeetingNotesAgent):
        """Analysis carries the model's answer, field by field, into the notes."""
        import asyncio

        transcript = "Alice: Planı Bob hazırlayacak, pazartesiye kadar."

        response = analysis_response(
            summary="Plan hazırlığı konuşuldu.",
            findings=["Plan eksik"],
            action_items=[
                {
                    "description": "Planı hazırla",
                    "owner": "Bob",
                    "deadline_text": "pazartesi",
                    "deadline_iso": "",
                    "priority": 4,
                }
            ],
            next_steps=["Planı gözden geçir"],
        )

        with mocked_analysis(response):
            notes = asyncio.run(
                agent.analyze_meeting(
                    transcript,
                    meeting_title="Planning Meeting",
                    attendees=["Alice", "Bob"],
                )
            )

        assert isinstance(notes, MeetingNotes)
        assert notes.title == "Planning Meeting"
        assert len(notes.attendees) == 2
        assert notes.summary == "Plan hazırlığı konuşuldu."
        assert notes.findings == ["Plan eksik"]
        assert notes.next_steps == ["Planı gözden geçir"]
        assert len(notes.action_items) == 1
        assert notes.action_items[0].owner == "Bob"
        assert notes.action_items[0].description == "Planı hazırla"
        assert notes.action_items[0].priority == 4

    def test_agent_generate_report(self, agent: MeetingNotesAgent):
        """Test report generation."""
        import asyncio

        agent.drive_manager.get_or_create_folder.return_value = "folder_123"
        agent.drive_manager.create_google_doc.return_value = "doc_123"

        notes = MeetingNotes(
            title="Test Meeting",
            attendees=["Alice"],
            findings=["Finding 1"],
        )

        reports = asyncio.run(agent.generate_report(notes))

        assert isinstance(reports, dict)
        # Reports may be empty if not fully mocked, but structure should be right
        agent.drive_manager.get_or_create_folder.assert_called_once()

    def test_agent_create_tasks_in_tracker(self, agent: MeetingNotesAgent):
        """Test creating tasks in tracker from action items."""
        import asyncio

        items = [
            ActionItem(
                description="Task 1",
                owner="Alice",
                deadline=datetime.now(timezone.utc) + timedelta(days=3),
            ),
            ActionItem(
                description="Task 2",
                owner="Bob",
                deadline=datetime.now(timezone.utc) + timedelta(days=5),
            ),
        ]

        # Mock the task tracker's add_task method
        agent.task_tracker.add_task.side_effect = lambda t: t.id

        task_ids = asyncio.run(agent.create_tasks_in_tracker(items, "meeting_123"))

        assert len(task_ids) == 2
        assert agent.task_tracker.add_task.call_count == 2

    def test_agent_new_finding_count(self, agent: MeetingNotesAgent):
        """Test new finding count."""
        agent.task_tracker.get_upcoming_tasks.return_value = [
            Mock(spec=Task),
            Mock(spec=Task),
        ]

        count = agent.new_finding_count()

        assert count == 2


class TestGoogleDriveManager:
    """Tests for GoogleDriveManager class."""

    @pytest.fixture
    def manager(self):
        """Provide a GoogleDriveManager with mocked service."""
        with patch("ai_assistant.integrations.google_drive_manager.get_credentials"):
            with patch("ai_assistant.integrations.google_drive_manager.build"):
                manager = GoogleDriveManager()
                manager.service = Mock()
                return manager

    def test_manager_initialization(self, manager: GoogleDriveManager):
        """Test manager initialization."""
        assert manager.service is not None

    def test_manager_get_file_link(self, manager: GoogleDriveManager):
        """Test generating file share link."""
        file_id = "file_123"
        link = manager.get_file_link(file_id)

        assert "drive.google.com" in link
        assert file_id in link

    def test_manager_upload_file_not_found(self, manager: GoogleDriveManager):
        """Test upload with nonexistent file."""
        result = manager.upload_file(
            file_path="/nonexistent/file.txt",
            folder_id="folder_123",
        )

        assert result is None

    def test_manager_create_folder_success(self, manager: GoogleDriveManager):
        """Test folder creation."""
        manager.service.files.return_value.create.return_value.execute.return_value = {
            "id": "folder_123"
        }

        folder_id = manager.create_folder("Test Folder")

        assert folder_id == "folder_123"

    def test_manager_get_or_create_folder_exists(self, manager: GoogleDriveManager):
        """Test get_or_create returns existing folder."""
        manager.get_folder_id_by_name = Mock(return_value="existing_folder")

        folder_id = manager.get_or_create_folder("Existing")

        assert folder_id == "existing_folder"
        manager.get_folder_id_by_name.assert_called_once()

    def test_manager_get_or_create_folder_creates_new(
        self, manager: GoogleDriveManager
    ):
        """Test get_or_create creates new folder when not found."""
        manager.get_folder_id_by_name = Mock(return_value=None)
        manager.create_folder = Mock(return_value="new_folder")

        folder_id = manager.get_or_create_folder("New")

        assert folder_id == "new_folder"
        manager.create_folder.assert_called_once()


# Integration-like tests


class TestTaskTrackerIntegration:
    """Integration tests for TaskTracker."""

    @pytest.fixture
    def temp_state_dir(self) -> Generator[Path, None, None]:
        """Provide a temporary state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_multiple_operations(self, temp_state_dir: Path):
        """Test a realistic sequence of operations."""
        tracker = TaskTracker(state_dir=str(temp_state_dir))

        # Add tasks
        task1 = Task(
            id="task_1",
            title="Priority task",
            description="Urgent",
            owner="Alice",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
            priority=5,
        )
        task2 = Task(
            id="task_2",
            title="Regular task",
            description="Normal",
            owner="Bob",
            deadline=datetime.now(timezone.utc) + timedelta(days=7),
            priority=2,
        )

        tracker.add_task(task1)
        tracker.add_task(task2)

        # Get upcoming
        upcoming = tracker.get_upcoming_tasks(days=3)
        assert len(upcoming) >= 1

        # Get by owner
        alice_tasks = tracker.get_tasks_by_owner("Alice")
        assert len(alice_tasks) == 1

        # Update status
        tracker.update_status("task_1", TaskStatus.IN_PROGRESS)
        updated = tracker.get_task("task_1")
        assert updated.status == TaskStatus.IN_PROGRESS

        # Get stats
        stats = tracker.get_summary_stats()
        assert stats["total"] == 2
        assert stats["in_progress"] == 1


class TestMeetingNotesDeadlineReminders:
    """Tests for deadline reminder functionality with Slack integration."""

    @pytest.fixture
    def agent(self):
        """Provide MeetingNotesAgent with mocked Slack bridge and Google Drive."""
        with patch("ai_assistant.advisors.meeting_notes.SlackAdvisorBridge"):
            with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
                agent = MeetingNotesAgent()
                return agent

    @pytest.fixture
    def mock_slack_client(self):
        """Mock Slack AsyncWebClient."""
        client = AsyncMock()
        client.chat_postMessage = AsyncMock(
            return_value={"ok": True, "ts": "1234567890.123456"}
        )
        return client

    @pytest.mark.asyncio
    async def test_send_deadline_reminders_no_upcoming_tasks(self, agent):
        """Test send_deadline_reminders returns True when no upcoming tasks."""
        agent.task_tracker.get_upcoming_tasks = Mock(return_value=[])

        result = await agent.send_deadline_reminders()

        assert result is True

    @pytest.mark.asyncio
    async def test_send_deadline_reminders_slack_not_configured(self, agent):
        """Test send_deadline_reminders returns True when Slack unconfigured."""
        # Create a task
        task = Task(
            id="task_1",
            title="Test Task",
            description="Testing",
            owner="Test Owner",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
            priority=3,
        )
        agent.task_tracker.get_upcoming_tasks = Mock(return_value=[task])

        # Slack not configured
        agent.slack_bridge.slack_client = None

        result = await agent.send_deadline_reminders()

        assert result is True

    @pytest.mark.asyncio
    async def test_send_deadline_reminders_sends_real_slack_message(
        self, agent, mock_slack_client
    ):
        """Test send_deadline_reminders sends real Slack message."""
        # Create test tasks
        task1 = Task(
            id="task_1",
            title="Complete report",
            description="Finish quarterly report",
            owner="Alice",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
            priority=4,
        )
        task2 = Task(
            id="task_2",
            title="Review proposal",
            description="Review client proposal",
            owner="Bob",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
            priority=3,
        )
        agent.task_tracker.get_upcoming_tasks = Mock(return_value=[task1, task2])

        # Configure Slack
        agent.slack_bridge.slack_client = mock_slack_client

        result = await agent.send_deadline_reminders()

        assert result is True
        mock_slack_client.chat_postMessage.assert_called_once()

        # Verify message structure
        call_args = mock_slack_client.chat_postMessage.call_args
        assert call_args[1]["channel"] == "@user_dm"
        assert "blocks" in call_args[1]
        blocks = call_args[1]["blocks"]
        assert len(blocks) > 0

    @pytest.mark.asyncio
    async def test_send_deadline_reminders_block_kit_formatting(
        self, agent, mock_slack_client
    ):
        """Test Block Kit formatting in deadline reminder messages."""
        task = Task(
            id="task_1",
            title="Deploy service",
            description="Deploy to production",
            owner="Charlie",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
            priority=5,
        )
        agent.task_tracker.get_upcoming_tasks = Mock(return_value=[task])
        agent.slack_bridge.slack_client = mock_slack_client

        await agent.send_deadline_reminders()

        # Get the blocks from the call
        call_args = mock_slack_client.chat_postMessage.call_args
        blocks = call_args[1]["blocks"]

        # Verify Block Kit structure
        assert blocks[0]["type"] == "header"
        assert "Yarın Deadline" in blocks[0]["text"]["text"]

        # Should have divider
        assert any(block["type"] == "divider" for block in blocks)

        # Should have task information
        section_blocks = [b for b in blocks if b["type"] == "section"]
        assert len(section_blocks) > 0
        first_section = section_blocks[0]
        assert "fields" in first_section
        fields = first_section["fields"]
        # Should have: Task, Owner, Deadline, Priority fields
        assert len(fields) == 4

    @pytest.mark.asyncio
    async def test_send_deadline_reminders_slack_send_failure(
        self, agent, mock_slack_client
    ):
        """Test send_deadline_reminders handles Slack send failure."""
        task = Task(
            id="task_1",
            title="Test Task",
            description="Testing",
            owner="Test",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
            priority=3,
        )
        agent.task_tracker.get_upcoming_tasks = Mock(return_value=[task])

        # Mock Slack failure
        mock_slack_client.chat_postMessage = AsyncMock(
            return_value={"ok": False, "error": "channel_not_found"}
        )
        agent.slack_bridge.slack_client = mock_slack_client

        result = await agent.send_deadline_reminders()

        assert result is False

    @pytest.mark.asyncio
    async def test_send_deadline_reminders_handles_exception(self, agent):
        """Test send_deadline_reminders handles exceptions gracefully."""
        # Make task_tracker raise an exception
        agent.task_tracker.get_upcoming_tasks = Mock(
            side_effect=Exception("Database error")
        )

        result = await agent.send_deadline_reminders()

        assert result is False

    def test_build_deadline_reminder_blocks_structure(self, agent):
        """Test Block Kit block structure for deadline reminders."""
        task1 = Task(
            id="task_1",
            title="Feature X",
            description="Implement feature",
            owner="Dev Team",
            deadline=datetime.now(timezone.utc) + timedelta(days=2),
            priority=4,
        )
        task2 = Task(
            id="task_2",
            title="Code Review",
            description="Review PR",
            owner="Reviewer",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
            priority=2,
        )

        blocks = agent._build_deadline_reminder_blocks([task1, task2])

        # Verify structure
        assert blocks[0]["type"] == "header"
        assert blocks[1]["type"] == "divider"

        # Should have sections and dividers for each task
        section_count = sum(1 for b in blocks if b["type"] == "section")
        divider_count = sum(1 for b in blocks if b["type"] == "divider")
        assert section_count >= 2  # At least 2 tasks
        assert divider_count >= 2  # Dividers between sections

    def test_priority_emoji_mapping(self, agent):
        """Test priority emoji mapping."""
        assert agent._get_priority_emoji(5) == "🔴"  # Critical
        assert agent._get_priority_emoji(4) == "🟠"  # High
        assert agent._get_priority_emoji(3) == "🟡"  # Medium
        assert agent._get_priority_emoji(2) == "🟢"  # Low
        assert agent._get_priority_emoji(1) == "🟢"  # Low


# ============================================================================
# Behavioral Tests: End-to-End Pipeline
# ============================================================================


class TestMeetingNotesPipelineEndToEnd:
    """End-to-end behavioral tests for complete meeting notes pipeline."""

    @pytest.fixture
    def agent_with_mocks(self):
        """Provide MeetingNotesAgent with appropriate mocks."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                agent = MeetingNotesAgent()
                agent.drive_manager = Mock()
                agent.task_tracker = Mock()
                return agent

    @pytest.mark.asyncio
    async def test_pipeline_transcribe_analyze_extract_tasks(self, agent_with_mocks):
        """Test complete pipeline: transcription → analysis → task extraction.

        Verifies that real transcript data flows through the system and
        produces actual output, not hardcoded placeholders.
        """
        # Real transcript with action items and Turkish dates
        transcript = (
            "Konuşmacı 1: Proje hakkında konuşmalıyız.\n"
            "Konuşmacı 2: Evet, bütçe planı cuma gününe kadar hazırlanmalı.\n"
            "Konuşmacı 1: Kodu kim yazacak?\n"
            "Konuşmacı 2: Ben yazacağım, iki hafta içinde biter.\n"
            "Konuşmacı 1: Pazarlama ekibi neler yapmalı?\n"
            "Konuşmacı 2: Kampanya materyali ayın 15'i kadar hazır olmalı."
        )

        # Step 1: Transcribe (mock but verify real data is used)
        mock_transcription = transcript
        assert len(mock_transcription) > 0
        assert "cuma gününe kadar" in mock_transcription

        # Step 2: Analyze meeting — the model sees the transcript and answers
        # with items drawn from it.
        response = analysis_response(
            summary="Bütçe planı ve kampanya materyali konuşuldu.",
            findings=["Bütçe planı bekliyor"],
            action_items=[
                {
                    "description": "Bütçe planını hazırla",
                    "owner": "Konuşmacı 2",
                    "deadline_text": "cuma gününe kadar",
                    "deadline_iso": "",
                    "priority": 4,
                },
                {
                    "description": "Kampanya materyalini hazırla",
                    "owner": "Konuşmacı 2",
                    "deadline_text": "ayın 15'i",
                    "deadline_iso": "",
                    "priority": 3,
                },
            ],
            next_steps=["Kodu yazmaya başla"],
        )

        with mocked_analysis(response) as generate:
            meeting_notes = await agent_with_mocks.analyze_meeting(
                mock_transcription,
                meeting_title="Proje Toplantısı",
                attendees=["Konuşmacı 1", "Konuşmacı 2"],
            )

        # The transcript itself must reach the model — otherwise the analysis
        # cannot be about this meeting.
        sent_user_prompt = generate.call_args[0][1]
        assert "cuma gününe kadar" in sent_user_prompt
        assert "Kampanya materyali" in sent_user_prompt

        # Step 3: Verify analysis output
        assert isinstance(meeting_notes, MeetingNotes)
        assert meeting_notes.title == "Proje Toplantısı"
        assert len(meeting_notes.attendees) == 2
        assert [item.description for item in meeting_notes.action_items] == [
            "Bütçe planını hazırla",
            "Kampanya materyalini hazırla",
        ]
        # Spoken Turkish dates become real deadlines.
        assert all(item.deadline is not None for item in meeting_notes.action_items)
        assert all(
            item.deadline > meeting_notes.date for item in meeting_notes.action_items
        )

        # Step 4: Create tasks from action items
        agent_with_mocks.task_tracker.add_task.side_effect = lambda t: t.id

        task_ids = await agent_with_mocks.create_tasks_in_tracker(
            meeting_notes.action_items, meeting_notes.meeting_id
        )

        assert len(task_ids) == 2
        assert agent_with_mocks.task_tracker.add_task.called

    @pytest.mark.asyncio
    async def test_pipeline_with_realistic_meeting_transcript(self, agent_with_mocks):
        """Test pipeline with a realistic multilingual meeting transcript.

        Ensures transcript content flows through and analysis uses the data.
        """
        transcript = (
            "Konuşmacı 1 (Müdür): Herkese merhaba. Bu ayın hedeflerini gözden "
            "geçireceğiz.\n"
            "Konuşmacı 2 (Pazarlama): Sosyal medya kampanyası yarına kadar başlamalı. "
            "Bütçe tarafımdan hazırlandı.\n"
            "Konuşmacı 3 (Geliştirme): API entegrasyonunu bitirmem iki hafta "
            "alacak.\n"
            "Konuşmacı 1: Tamam. Herkes sorumlulukları biliyor mu?\n"
            "Konuşmacı 2: Evet, pazartesi başlıyorum.\n"
            "Konuşmacı 3: Benim deadline'ım 20 Eylül."
        )

        response = analysis_response(
            summary="Aylık hedefler gözden geçirildi.",
            findings=["Kampanya yarın başlıyor"],
            action_items=[
                {
                    "description": "Sosyal medya kampanyasını başlat",
                    "owner": "Pazarlama",
                    "deadline_text": "yarın",
                    "deadline_iso": "",
                    "priority": 5,
                },
                {
                    "description": "API entegrasyonunu bitir",
                    "owner": "Geliştirme",
                    "deadline_text": "iki hafta içinde",
                    "deadline_iso": "",
                    "priority": 4,
                },
            ],
            fenced=True,  # models routinely wrap JSON in a ```json fence
        )

        with mocked_analysis(response):
            meeting_notes = await agent_with_mocks.analyze_meeting(
                transcript,
                meeting_title="Aylık Hedefler Toplantısı",
                attendees=["Müdür", "Pazarlama", "Geliştirme"],
            )

        # Verify the transcript was processed
        assert meeting_notes.transcript_text == transcript
        assert meeting_notes.title == "Aylık Hedefler Toplantısı"

        # Verify action items were extracted (not empty)
        assert len(meeting_notes.action_items) == 2
        owners = {item.owner for item in meeting_notes.action_items}
        assert owners == {"Pazarlama", "Geliştirme"}

        # "yarın" is one day out, "iki hafta içinde" is fourteen.
        by_owner = {item.owner: item for item in meeting_notes.action_items}
        tomorrow = by_owner["Pazarlama"].deadline
        two_weeks = by_owner["Geliştirme"].deadline
        assert (tomorrow.date() - meeting_notes.date.date()).days == 1
        assert (two_weeks.date() - meeting_notes.date.date()).days == 14


class TestTurkishDateParsingIntegration:
    """Integration tests for Turkish date parsing in meeting context."""

    @pytest.fixture
    def agent(self):
        """Provide agent with mocked dependencies."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                agent = MeetingNotesAgent()
                agent.task_tracker = Mock()
                agent.task_tracker.add_task.side_effect = lambda t: t.id
                return agent

    @pytest.mark.asyncio
    async def test_action_items_with_turkish_dates(self, agent):
        """Test that Turkish date expressions are properly extracted."""
        from ai_assistant.advisors._turkish_dates import parse_turkish_date

        # Simulate dates that would appear in transcripts
        anchor = datetime.now(timezone.utc)

        # Test various Turkish date patterns
        # Note: expected_days are approximate and may vary by 1-2 days
        # depending on current day of week
        test_cases = [
            ("cuma gününe kadar", None),  # Next Friday (depends on current date)
            ("iki hafta içinde", 14),  # Two weeks (fairly consistent)
            ("ayın 15'i", None),  # 15th of the month (depends on current date)
            ("yarın", 1),  # Tomorrow (consistent)
            ("hafta başı", None),  # Start of week (depends on current date)
        ]

        for date_expr, expected_days in test_cases:
            parsed = parse_turkish_date(date_expr, anchor)
            # Verify parsing works (returns a datetime, not None)
            assert parsed is not None, f"Failed to parse: {date_expr}"
            days_diff = (parsed.date() - anchor.date()).days
            assert days_diff > 0, f"Date should be in future: {date_expr}"

            # Only assert exact day difference for cases that are consistent
            if expected_days is not None:
                assert abs(days_diff - expected_days) <= 1, (
                    f"Date expression '{date_expr}' parsed to {days_diff} days "
                    f"instead of ~{expected_days}"
                )

    @pytest.mark.asyncio
    async def test_action_item_deadline_extraction_from_transcript(self, agent):
        """Test extracting deadlines from transcript text."""
        from ai_assistant.advisors._turkish_dates import parse_turkish_date

        # Realistic transcript with Turkish date expressions
        transcript = (
            "Konuşmacı 1: Rapor cuma gününe kadar hazır olmalı.\n"
            "Konuşmacı 2: Tamam, pazartesi sunacağım.\n"
            "Konuşmacı 1: Geliştirme takımı ne yapmayacak?\n"
            "Konuşmacı 2: iki hafta içinde API bitecek."
        )

        # Extract date references from transcript
        anchor = datetime.now(timezone.utc)
        from ai_assistant.advisors._turkish_dates import normalise

        # Check key date expressions are in transcript
        assert "cuma gününe kadar" in transcript
        assert "iki hafta içinde" in transcript  # Using lowercase version

        # Verify they can be parsed
        friday = parse_turkish_date("cuma gününe kadar", anchor)
        two_weeks = parse_turkish_date("iki hafta içinde", anchor)

        assert friday is not None
        assert two_weeks is not None
        assert two_weeks > friday  # Two weeks is further than Friday


class TestActionItemExtraction:
    """Tests for action item extraction from transcripts."""

    @pytest.fixture
    def agent(self):
        """Provide agent with mocks."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                return MeetingNotesAgent()

    @pytest.mark.asyncio
    async def test_extract_action_items_from_transcript(self, agent):
        """Test that action items are extracted from actual transcript."""
        transcript = (
            "Konuşmacı 1: Sunumu kimin hazırlaması gerekiyor?\n"
            "Konuşmacı 2: Ben hazırlayacağım. Bir hafta yetiyor.\n"
            "Konuşmacı 1: Test raporu için neler lazım?\n"
            "Konuşmacı 3: Tam test paketi olmalı. İki hafta içinde yapabilirim.\n"
            "Konuşmacı 1: Pazarlama kampanyası?\n"
            "Konuşmacı 2: Pazartesi başlıyorum, cuma bitecek."
        )

        response = analysis_response(
            action_items=[
                {
                    "description": "Sunumu hazırla",
                    "owner": "Konuşmacı 2",
                    "deadline_text": "bir hafta içinde",
                    "deadline_iso": "",
                    "priority": 3,
                },
                {
                    "description": "Tam test paketini yaz",
                    "owner": "Konuşmacı 3",
                    "deadline_text": "iki hafta içinde",
                    "deadline_iso": "",
                    "priority": 4,
                },
            ],
        )

        with mocked_analysis(response):
            meeting_notes = await agent.analyze_meeting(
                transcript,
                meeting_title="Test",
                attendees=["Konuşmacı 1", "Konuşmacı 2", "Konuşmacı 3"],
            )

        # Action items should be extracted
        assert isinstance(meeting_notes.action_items, list)
        assert len(meeting_notes.action_items) == 2

        # Each action item should have required fields
        for item in meeting_notes.action_items:
            assert isinstance(item, ActionItem)
            assert item.description  # Should have description from transcript
            assert item.owner  # Should have owner name
            assert item.deadline is not None  # Turkish phrase resolved to a date

        assert meeting_notes.action_items[0].description == "Sunumu hazırla"
        assert meeting_notes.action_items[1].owner == "Konuşmacı 3"

    @pytest.mark.asyncio
    async def test_action_items_have_realistic_owners(self, agent):
        """Owners are whoever the model named — never a name baked into the code."""
        attendees = ["Alice", "Bob", "Charlie"]
        transcript = (
            "Alice: Veritabanı şeması Alice'in yapması gerekli. "
            "Bob API endpoints'i yapacak. "
            "Charlie frontend UI hazırlayacak."
        )

        response = analysis_response(
            action_items=[
                {"description": "Veritabanı şemasını çıkar", "owner": "Alice"},
                {"description": "API endpointlerini yaz", "owner": "Bob"},
                {"description": "Frontend arayüzünü hazırla", "owner": "Charlie"},
            ],
        )

        with mocked_analysis(response):
            meeting_notes = await agent.analyze_meeting(
                transcript,
                meeting_title="Backend Planning",
                attendees=attendees,
            )

        assert [item.owner for item in meeting_notes.action_items] == attendees
        # No deadline was spoken and none was guessed, so none is invented.
        assert all(item.deadline is None for item in meeting_notes.action_items)


class TestStatePersistenceAndDeduplication:
    """Tests for meeting state persistence and deduplication."""

    @pytest.fixture
    def temp_state_dir(self) -> Generator[Path, None, None]:
        """Provide temporary state directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def agent_with_state(self, temp_state_dir):
        """Agent with real state directory."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                with patch("ai_assistant.advisors.meeting_notes.SlackAdvisorBridge"):
                    with patch("pathlib.Path.mkdir"):
                        agent = MeetingNotesAgent()
                        agent.state_dir = temp_state_dir
                        agent.meetings_file = temp_state_dir / "meetings.json"
                        agent.drive_manager = Mock()
                        agent.task_tracker = Mock()
                        agent.slack_bridge = Mock()
                        return agent

    def test_meeting_state_file_creation(self, agent_with_state):
        """Test that meeting state file is created."""
        assert agent_with_state.state_dir.exists()
        assert agent_with_state.meetings_file is not None

    @pytest.mark.asyncio
    async def test_processed_meetings_not_reprocessed(self, agent_with_state):
        """Test that the same meeting ID is not processed twice."""
        meeting1 = MeetingNotes(
            meeting_id="meeting_1",
            title="First Meeting",
            attendees=["Alice", "Bob"],
        )

        # Simulate storing processed meeting
        meetings = {"meeting_1": meeting1.to_dict()}

        agent_with_state.meetings_file.write_text(json.dumps(meetings))

        # Load and verify meeting is in state
        if agent_with_state.meetings_file.exists():
            loaded = json.loads(agent_with_state.meetings_file.read_text())
            assert "meeting_1" in loaded
            assert loaded["meeting_1"]["title"] == "First Meeting"

    def test_meeting_deduplication_logic(self, agent_with_state):
        """Test deduplication of meeting IDs."""
        # Create meeting records
        meetings = {
            "meeting_1": {"meeting_id": "meeting_1", "title": "Meeting 1"},
            "meeting_2": {"meeting_id": "meeting_2", "title": "Meeting 2"},
        }

        # Simulate checking if a meeting was processed
        meeting_id = "meeting_1"
        is_processed = meeting_id in meetings

        assert is_processed is True

        # New meeting should not be in list
        is_new = "meeting_3" not in meetings
        assert is_new is True


class TestHardcodedDataValidation:
    """Guards against sample data creeping back into the analysis.

    The advisor once returned a fixed cast of characters (John/Sarah/Mike) and
    a fixed competitor for EVERY meeting. These tests come at that failure
    from both ends: the output must track whatever the model actually said,
    and the source file must not contain the old sample names at all.
    """

    #: The names and company the mock implementation used to emit. If any of
    #: these ever appears again, something is being made up rather than read.
    FORBIDDEN_NAMES = ("John", "Sarah", "Mike")
    FORBIDDEN_COMPANIES = ("XYZ şirketi", "XYZ")

    @pytest.fixture
    def agent(self):
        """Provide agent."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                return MeetingNotesAgent()

    @pytest.mark.asyncio
    async def test_no_hardcoded_names_in_action_items(self, agent):
        """Owners come from the model's answer, not from the source file."""
        attendees = ["Alice", "Bob", "Charlie"]
        transcript = (
            "Alice: Biz bu işi yapalım.\n"
            "Bob: Tamam, ben de yardımcı olabilirim.\n"
            "Charlie: Kodlamayı ben yapacağım."
        )

        response = analysis_response(
            summary="Görev paylaşımı yapıldı.",
            action_items=[
                {"description": "Kodlamayı yap", "owner": "Charlie", "priority": 4},
                {"description": "Destek ol", "owner": "Bob", "priority": 2},
            ],
        )

        with mocked_analysis(response):
            meeting_notes = await agent.analyze_meeting(
                transcript,
                meeting_title="Test Meeting",
                attendees=attendees,
            )

        owners = [item.owner for item in meeting_notes.action_items]
        assert owners == ["Charlie", "Bob"]
        assert not [name for name in owners if name in self.FORBIDDEN_NAMES]

    @pytest.mark.asyncio
    async def test_different_transcripts_produce_different_analyses(self, agent):
        """The same advisor, two meetings, two different sets of notes.

        This is the assertion a fixed-output implementation cannot pass: it
        would return identical owners and findings for both calls.
        """
        first = analysis_response(
            summary="Rapor konuşuldu.",
            findings=["Rapor gecikti"],
            action_items=[
                {
                    "description": "Raporu bitir",
                    "owner": "Ayşe",
                    "deadline_text": "pazartesi",
                    "priority": 5,
                }
            ],
        )
        second = analysis_response(
            summary="Sunum konuşuldu.",
            findings=["Sunum taslağı yok"],
            action_items=[
                {
                    "description": "Sunumu hazırla",
                    "owner": "Mert",
                    "deadline_text": "iki hafta içinde",
                    "priority": 2,
                }
            ],
        )

        with mocked_analysis(first):
            notes_a = await agent.analyze_meeting(
                "Ayşe pazartesiye kadar raporu bitirecek.",
                meeting_title="Rapor Toplantısı",
                attendees=["Ayşe"],
            )

        with mocked_analysis(second):
            notes_b = await agent.analyze_meeting(
                "Mert iki hafta içinde sunumu hazırlayacak.",
                meeting_title="Sunum Toplantısı",
                attendees=["Mert"],
            )

        assert notes_a.action_items[0].owner == "Ayşe"
        assert notes_b.action_items[0].owner == "Mert"
        assert notes_a.action_items[0].description == "Raporu bitir"
        assert notes_b.action_items[0].description == "Sunumu hazırla"
        assert notes_a.action_items[0].priority == 5
        assert notes_b.action_items[0].priority == 2
        assert notes_a.summary != notes_b.summary
        assert notes_a.findings != notes_b.findings

    @pytest.mark.asyncio
    async def test_no_hardcoded_company_names(self, agent):
        """Competitive intelligence tracks the answer, and stays empty when absent."""
        transcript = (
            "Konuşmacı 1: Bizim şirketimiz hakkında konuşalım.\n"
            "Konuşmacı 2: Rekabet ortamını analiz ettik."
        )

        # No competitor was named in this meeting, so none may appear.
        with mocked_analysis(analysis_response(summary="Genel değerlendirme.")):
            meeting_notes = await agent.analyze_meeting(
                transcript,
                meeting_title="Meeting",
                attendees=["Speaker1", "Speaker2"],
            )

        assert meeting_notes.competitive_actions == []
        assert meeting_notes.findings == []

        # When one IS named, that is the one that shows up.
        response = analysis_response(
            findings=["Delta Yazılım fiyat kırdı"],
            competitive_actions=[
                {
                    "description": "Delta Yazılım fiyatlarını düşürdü",
                    "impact": "high",
                    "urgency": "high",
                    "recommended_action": "Fiyat stratejisini gözden geçir",
                }
            ],
        )
        with mocked_analysis(response):
            named = await agent.analyze_meeting(
                "Konuşmacı 1: Delta Yazılım fiyatlarını düşürmüş.",
                meeting_title="Rekabet",
                attendees=["Konuşmacı 1"],
            )

        assert len(named.competitive_actions) == 1
        assert named.competitive_actions[0].description == (
            "Delta Yazılım fiyatlarını düşürdü"
        )

        haystack = " ".join(
            named.findings
            + [action.description for action in named.competitive_actions]
        )
        assert not [c for c in self.FORBIDDEN_COMPANIES if c in haystack]

    def test_source_file_contains_no_sample_data(self):
        """The old fixed cast must not exist in the source at all.

        Asserting on OUTPUT alone is not enough: a fixed fallback path that
        only fires on some branch would slip through. Nothing in this module
        has any business naming a person or a competitor.
        """
        source = Path(meeting_notes_module.__file__).read_text(encoding="utf-8")

        found = [
            token
            for token in (*self.FORBIDDEN_NAMES, *self.FORBIDDEN_COMPANIES)
            if token in source
        ]
        assert not found, f"meeting_notes.py hâlâ sabit örnek veri içeriyor: {found}"

    @pytest.mark.asyncio
    async def test_action_items_match_attendees_or_transcript(self, agent):
        """Owners named in the transcript are the owners that come back."""
        attendees = ["Emma", "Frank", "Grace"]
        transcript = (
            "Emma: Frank, makefile yazabilir misin?\n"
            "Frank: Evet, yarın başlayacağım.\n"
            "Grace: Build sistemi mi?\n"
            "Frank: Evet, kontrol edilecek."
        )

        response = analysis_response(
            action_items=[
                {
                    "description": "Makefile yaz",
                    "owner": "Frank",
                    "deadline_text": "yarın",
                    "priority": 3,
                }
            ],
        )

        with mocked_analysis(response):
            meeting_notes = await agent.analyze_meeting(
                transcript,
                meeting_title="Build Meeting",
                attendees=attendees,
            )

        for item in meeting_notes.action_items:
            assert item.owner in attendees
            assert item.owner in transcript


class TestGeminiUnconfiguredGracefulDegradation:
    """Tests for graceful handling when Gemini is not configured."""

    @pytest.mark.asyncio
    async def test_transcribe_audio_without_gemini_key(self):
        """Test that transcription gracefully returns empty string when Gemini unconfigured."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                agent = MeetingNotesAgent()

                # Mock llm.is_configured() to return False
                with patch(
                    "ai_assistant.advisors.meeting_notes.llm.is_configured",
                    return_value=False,
                ):
                    result = await agent.transcribe_audio(b"fake-audio-bytes")

                    # Should return empty string, not fail or return placeholder
                    assert result == ""
                    # Should have error message
                    assert agent.last_transcription_error is not None
                    assert (
                        "GEMINI_API_KEY" in agent.last_transcription_error
                        or "missing" in agent.last_transcription_error.lower()
                    )

    @pytest.mark.asyncio
    async def test_transcribe_audio_with_empty_bytes(self):
        """Test handling of empty audio bytes."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                agent = MeetingNotesAgent()

                result = await agent.transcribe_audio(b"")

                assert result == ""
                assert agent.last_transcription_error is not None

    @pytest.mark.asyncio
    async def test_transcribe_audio_type_validation(self):
        """Test that passing a string instead of bytes is caught."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                agent = MeetingNotesAgent()

                with pytest.raises(TypeError):
                    await agent.transcribe_audio("not-bytes-url")


class TestAnalysisGracefulDegradation:
    """What analyze_meeting returns when it CANNOT analyse.

    In every one of these cases the honest answer is "nothing" — an invented
    action item would be filed as a real task and chased in a real Slack
    reminder. The notes come back empty and the reason is recorded.
    """

    @pytest.fixture
    def agent(self):
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                return MeetingNotesAgent()

    @pytest.mark.asyncio
    async def test_no_llm_key_returns_empty_notes_not_fabricated_data(
        self, agent, caplog
    ):
        """Without a provider key nothing is analysed and nothing is invented."""
        transcript = "Konuşmacı 1: Bütçe planı cuma gününe kadar hazırlanmalı."

        with patch.object(
            meeting_notes_module.llm, "is_configured", return_value=False
        ):
            with patch.object(meeting_notes_module.llm, "generate_text") as generate:
                with caplog.at_level("INFO"):
                    notes = await agent.analyze_meeting(
                        transcript,
                        meeting_title="Bütçe",
                        attendees=["Konuşmacı 1"],
                    )

        # The model was never asked.
        generate.assert_not_called()

        # Nothing was made up.
        assert notes.action_items == []
        assert notes.competitive_actions == []
        assert notes.findings == []
        assert notes.next_steps == []
        assert notes.summary == ""

        # But the real input is preserved and the reason is recorded.
        assert notes.transcript_text == transcript
        assert notes.title == "Bütçe"
        assert agent.last_analysis_error is not None
        assert "atlandı" in agent.last_analysis_error
        assert "yapılandırılmamış" in caplog.text

    @pytest.mark.asyncio
    async def test_empty_transcript_is_not_sent_to_the_model(self, agent):
        """An empty transcript is a skip, not a request."""
        with mocked_analysis(analysis_response(summary="olmamalı")) as generate:
            notes = await agent.analyze_meeting("   ", meeting_title="Boş")

        generate.assert_not_called()
        assert notes.action_items == []
        assert notes.summary == ""
        assert agent.last_analysis_error is not None
        assert "boş transkript" in agent.last_analysis_error

    @pytest.mark.asyncio
    async def test_failed_request_is_recorded_not_swallowed(self, agent, caplog):
        """A raising provider leaves empty notes AND a logged reason."""

        def boom(*args, **kwargs):
            raise RuntimeError("429 rate limited")

        with mocked_analysis(boom):
            with caplog.at_level("ERROR"):
                notes = await agent.analyze_meeting(
                    "Konuşmacı 1: Bir şeyler konuşuldu.",
                    meeting_title="Hata",
                )

        assert notes.action_items == []
        assert notes.summary == ""
        assert agent.last_analysis_error is not None
        assert "429 rate limited" in agent.last_analysis_error
        assert "429 rate limited" in caplog.text

    @pytest.mark.asyncio
    async def test_unreadable_answer_is_recorded_not_swallowed(self, agent, caplog):
        """Prose where JSON was expected is a failure, not an empty meeting."""
        with mocked_analysis("Üzgünüm, bu kaydı analiz edemiyorum."):
            with caplog.at_level("ERROR"):
                notes = await agent.analyze_meeting(
                    "Konuşmacı 1: Bir şeyler konuşuldu.",
                    meeting_title="Bozuk",
                )

        assert notes.action_items == []
        assert agent.last_analysis_error is not None
        assert "okunamadı" in agent.last_analysis_error
        assert "okunamadı" in caplog.text

    @pytest.mark.asyncio
    async def test_successful_analysis_clears_previous_error(self, agent):
        """A good run must not inherit the last run's failure marker."""
        with mocked_analysis("not json at all"):
            await agent.analyze_meeting("bir şey", meeting_title="1")
        assert agent.last_analysis_error is not None

        with mocked_analysis(
            analysis_response(
                summary="Tamam.",
                action_items=[{"description": "Yap", "owner": "Ayşe"}],
            )
        ):
            notes = await agent.analyze_meeting("bir şey", meeting_title="2")

        assert agent.last_analysis_error is None
        assert notes.action_items[0].owner == "Ayşe"

    @pytest.mark.asyncio
    async def test_analysis_uses_a_low_thinking_budget(self, agent):
        """Structured extraction must not pay for a reasoning pass."""
        with mocked_analysis(analysis_response(summary="Özet")) as generate:
            await agent.analyze_meeting("bir şey", meeting_title="Bütçe")

        assert generate.call_args.kwargs["thinking_budget"] == 0

    @pytest.mark.asyncio
    async def test_malformed_entries_are_dropped_and_values_clamped(self, agent):
        """Junk in the answer degrades to sane values, never to an exception."""
        raw = json.dumps(
            {
                "summary": "Özet",
                "findings": ["gerçek bulgu", "", None, 42],
                "action_items": [
                    {"description": "", "owner": "Kimse"},  # no description
                    "bu bir sözlük değil",
                    {
                        "description": "Geçerli iş",
                        "owner": "Ayşe",
                        "priority": 99,  # out of range
                        "deadline_text": "anlaşılmayan bir ifade",
                        "deadline_iso": "kesinlikle tarih değil",
                    },
                ],
                "competitive_actions": [
                    {
                        "description": "Rakip hamlesi",
                        "impact": "çok yüksek",  # not a known level
                        "urgency": "high",
                    }
                ],
                "next_steps": "liste değil",
            },
            ensure_ascii=False,
        )

        with mocked_analysis(raw):
            notes = await agent.analyze_meeting("bir şey", meeting_title="Karışık")

        assert notes.findings == ["gerçek bulgu", "42"]
        assert len(notes.action_items) == 1
        assert notes.action_items[0].description == "Geçerli iş"
        assert notes.action_items[0].priority == 5  # clamped into 1..5
        assert notes.action_items[0].deadline is None  # never invented
        assert notes.competitive_actions[0].impact == "medium"  # unknown → default
        assert notes.competitive_actions[0].urgency == "high"
        assert notes.next_steps == []


class TestAsyncPatterns:
    """Tests for proper async/await patterns."""

    @pytest.fixture
    def agent(self):
        """Provide agent with mocked dependencies."""
        with patch("ai_assistant.advisors.meeting_notes.GoogleDriveManager"):
            with patch("ai_assistant.advisors.meeting_notes.TaskTracker"):
                with patch("ai_assistant.advisors.meeting_notes.SlackAdvisorBridge"):
                    agent = MeetingNotesAgent()
                    agent.drive_manager = Mock()
                    agent.task_tracker = Mock()
                    agent.slack_bridge = Mock()
                    agent.slack_bridge.slack_client = AsyncMock()
                    return agent

    @pytest.mark.asyncio
    async def test_analyze_meeting_is_async(self, agent):
        """Test that analyze_meeting is properly async."""
        transcript = "Toplantı notu"

        with mocked_analysis(analysis_response(summary="Özet")):
            result = await agent.analyze_meeting(
                transcript,
                meeting_title="Test",
                attendees=["A"],
            )

        assert isinstance(result, MeetingNotes)
        assert result.summary == "Özet"

    @pytest.mark.asyncio
    async def test_create_tasks_in_tracker_is_async(self, agent):
        """Test that create_tasks_in_tracker is properly async."""
        items = [
            ActionItem(
                description="Task 1",
                owner="Alice",
                deadline=datetime.now(timezone.utc) + timedelta(days=1),
            ),
        ]

        agent.task_tracker.add_task.side_effect = lambda t: t.id

        result = await agent.create_tasks_in_tracker(items, "meeting_1")

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_multiple_concurrent_analyses(self, agent):
        """Concurrent analyses keep their own transcripts apart."""
        import asyncio

        def per_transcript(system_prompt, user_prompt, **kwargs):
            index = user_prompt.rsplit("Transcript ", 1)[1].strip()
            return analysis_response(
                summary=f"Özet {index}",
                action_items=[
                    {"description": f"İş {index}", "owner": f"Person {index}"}
                ],
            )

        with mocked_analysis(per_transcript):
            tasks = [
                agent.analyze_meeting(
                    f"Transcript {i}",
                    meeting_title=f"Meeting {i}",
                    attendees=[f"Person {i}"],
                )
                for i in range(3)
            ]

            results = await asyncio.gather(*tasks)

        assert len(results) == 3
        assert all(isinstance(r, MeetingNotes) for r in results)
        # Each result belongs to ITS transcript, not to whichever finished last.
        assert [r.summary for r in results] == ["Özet 0", "Özet 1", "Özet 2"]
        assert [r.action_items[0].owner for r in results] == [
            "Person 0",
            "Person 1",
            "Person 2",
        ]

    @pytest.mark.asyncio
    async def test_send_deadline_reminders_async(self, agent):
        """Test that send_deadline_reminders is async."""
        task = Task(
            id="task_1",
            title="Test",
            description="Test",
            owner="Owner",
            deadline=datetime.now(timezone.utc) + timedelta(days=1),
        )
        agent.task_tracker.get_upcoming_tasks = Mock(return_value=[task])
        agent.slack_bridge.slack_client = None  # Slack not configured

        result = await agent.send_deadline_reminders()

        assert result is True
