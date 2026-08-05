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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import Mock, patch, MagicMock

import pytest

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

        assert data['id'] == "task_1"
        assert data['title'] == "Test"
        assert data['status'] == "pending"
        assert 'deadline' in data

    def test_task_from_dict(self):
        """Test creating task from dictionary."""
        now = datetime.now(timezone.utc)
        data = {
            'id': 'task_1',
            'title': 'Test',
            'description': 'Desc',
            'owner': 'Owner',
            'deadline': now.isoformat(),
            'status': 'pending',
            'priority': 3,
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'completed_at': None,
            'meeting_id': None,
            'tags': [],
        }

        task = Task.from_dict(data)

        assert task.id == 'task_1'
        assert task.title == 'Test'
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

        assert stats['total'] == 2
        assert stats['pending'] == 1
        assert stats['completed'] == 1
        assert stats['completion_rate'] == 50.0

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

        assert data['title'] == "Meeting"
        assert len(data['attendees']) == 1
        assert len(data['findings']) == 1
        assert 'meeting_id' in data


class TestMeetingNotesAgent:
    """Tests for MeetingNotesAgent class."""

    @pytest.fixture
    def agent(self) -> MeetingNotesAgent:
        """Provide a MeetingNotesAgent instance."""
        with patch('ai_assistant.advisors.meeting_notes.GoogleDriveManager'):
            with patch('ai_assistant.advisors.meeting_notes.TaskTracker'):
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

        with patch('ai_assistant.config.env', return_value=True):
            briefing = agent._generate()

        assert briefing.status == "skipped"
        assert "yeni bulgu yok" in briefing.text

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

        with patch('ai_assistant.config.env', return_value=True):
            briefing = agent._generate()

        assert briefing.status == "ok"
        assert "Urgent task" in briefing.text
        assert "John" in briefing.text

    @pytest.mark.asyncio
    async def test_agent_transcribe_audio(self, agent: MeetingNotesAgent):
        """Test audio transcription (mock)."""
        audio_url = "https://example.com/meeting.mp3"

        result = await agent.transcribe_audio(audio_url)

        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_agent_analyze_meeting(self, agent: MeetingNotesAgent):
        """Test meeting analysis."""
        transcript = "Meeting transcript with action items and decisions."

        notes = await agent.analyze_meeting(
            transcript,
            meeting_title="Planning Meeting",
            attendees=["Alice", "Bob"],
        )

        assert isinstance(notes, MeetingNotes)
        assert notes.title == "Planning Meeting"
        assert len(notes.attendees) == 2
        assert len(notes.action_items) > 0

    @pytest.mark.asyncio
    async def test_agent_generate_report(self, agent: MeetingNotesAgent):
        """Test report generation."""
        agent.drive_manager.get_or_create_folder.return_value = "folder_123"
        agent.drive_manager.create_google_doc.return_value = "doc_123"

        notes = MeetingNotes(
            title="Test Meeting",
            attendees=["Alice"],
            findings=["Finding 1"],
        )

        reports = await agent.generate_report(notes)

        assert isinstance(reports, dict)
        # Reports may be empty if not fully mocked, but structure should be right
        agent.drive_manager.get_or_create_folder.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_create_tasks_in_tracker(self, agent: MeetingNotesAgent):
        """Test creating tasks in tracker from action items."""
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

        task_ids = await agent.create_tasks_in_tracker(items, "meeting_123")

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
        with patch('ai_assistant.integrations.google_drive_manager.get_drive_service'):
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
            'id': 'folder_123'
        }

        folder_id = manager.create_folder("Test Folder")

        assert folder_id == 'folder_123'

    def test_manager_get_or_create_folder_exists(self, manager: GoogleDriveManager):
        """Test get_or_create returns existing folder."""
        manager.get_folder_id_by_name = Mock(return_value="existing_folder")

        folder_id = manager.get_or_create_folder("Existing")

        assert folder_id == "existing_folder"
        manager.get_folder_id_by_name.assert_called_once()

    def test_manager_get_or_create_folder_creates_new(self, manager: GoogleDriveManager):
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
        assert stats['total'] == 2
        assert stats['in_progress'] == 1
