"""Task tracking system with deadline management and Drive sync.

Provides Task and TaskTracker classes for managing action items with:
- Task CRUD operations
- Status tracking (pending, in_progress, completed, overdue)
- Deadline reminders
- Drive synchronization
- Persistent state (.assistant_state/tasks.json)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task status enum."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"


@dataclass
class Task:
    """Represents a single task/action item.

    Attributes:
        id: Unique task identifier (UUID or auto-generated)
        title: Short task title
        description: Detailed task description
        owner: Person responsible for the task
        deadline: Due date (datetime or None)
        status: Current task status
        priority: Priority level (1-5, 5 highest)
        created_at: When the task was created
        updated_at: When the task was last updated
        completed_at: When the task was completed (if applicable)
        meeting_id: Reference to source meeting (if from meeting notes)
        tags: List of tags for categorization
    """

    id: str
    title: str
    description: str
    owner: str
    deadline: Optional[datetime] = None
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    meeting_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        # Convert datetime objects to ISO format strings
        for key in ('deadline', 'created_at', 'updated_at', 'completed_at'):
            if data[key]:
                data[key] = data[key].isoformat()
        data['status'] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Task:
        """Create Task from dictionary."""
        # Convert ISO format strings back to datetime objects
        for key in ('deadline', 'created_at', 'updated_at', 'completed_at'):
            if data.get(key) and isinstance(data[key], str):
                data[key] = datetime.fromisoformat(data[key])

        # Convert status string to enum
        if isinstance(data.get('status'), str):
            data['status'] = TaskStatus(data['status'])

        return cls(**data)

    @property
    def is_overdue(self) -> bool:
        """Check if task is overdue."""
        if self.status == TaskStatus.COMPLETED or not self.deadline:
            return False
        return datetime.now(timezone.utc) > self.deadline

    @property
    def days_until_deadline(self) -> Optional[int]:
        """Days remaining until deadline."""
        if not self.deadline:
            return None
        delta = self.deadline - datetime.now(timezone.utc)
        return max(0, delta.days)

    def mark_completed(self) -> None:
        """Mark task as completed."""
        self.status = TaskStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


class TaskTracker:
    """Manages tasks with persistence and Drive sync.

    Handles:
    - Task CRUD operations
    - Status tracking and updates
    - Deadline reminder logic
    - Persistent storage in .assistant_state/tasks.json
    - Google Drive synchronization
    """

    def __init__(self, state_dir: str = ".assistant_state"):
        """Initialize TaskTracker.

        Args:
            state_dir: Directory for persistent state storage
        """
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(exist_ok=True)
        self.tasks_file = self.state_dir / "tasks.json"
        self.logger = logging.getLogger(__name__)

        self.tasks: Dict[str, Task] = {}
        self._load_from_disk()

    def add_task(self, task: Task) -> str:
        """Add a task to the tracker.

        Args:
            task: Task object to add

        Returns:
            Task ID
        """
        self.tasks[task.id] = task
        self._save_to_disk()
        self.logger.info(f"Added task '{task.title}' (ID: {task.id})")
        return task.id

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID.

        Args:
            task_id: Task ID

        Returns:
            Task object or None if not found
        """
        return self.tasks.get(task_id)

    def update_status(self, task_id: str, status: TaskStatus) -> bool:
        """Update task status.

        Args:
            task_id: Task ID
            status: New status

        Returns:
            True if updated, False if task not found
        """
        task = self.tasks.get(task_id)
        if not task:
            self.logger.error(f"Task {task_id} not found")
            return False

        old_status = task.status
        task.status = status
        task.updated_at = datetime.now(timezone.utc)

        if status == TaskStatus.COMPLETED:
            task.completed_at = datetime.now(timezone.utc)

        self._save_to_disk()
        self.logger.info(f"Updated task {task_id} status: {old_status} -> {status}")
        return True

    def get_overdue_tasks(self) -> List[Task]:
        """Get all overdue tasks.

        Returns:
            List of overdue tasks (not completed)
        """
        overdue = [
            task for task in self.tasks.values()
            if task.is_overdue
        ]
        return sorted(overdue, key=lambda t: t.deadline or datetime.now())

    def get_upcoming_tasks(self, days: int = 3) -> List[Task]:
        """Get tasks with deadline in next N days.

        Args:
            days: Number of days to look ahead

        Returns:
            List of upcoming tasks
        """
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days)

        upcoming = [
            task for task in self.tasks.values()
            if (task.status != TaskStatus.COMPLETED and
                task.deadline and
                now <= task.deadline <= cutoff)
        ]
        return sorted(upcoming, key=lambda t: t.deadline)

    def get_tasks_by_owner(self, owner: str) -> List[Task]:
        """Get tasks assigned to a specific owner.

        Args:
            owner: Owner name

        Returns:
            List of tasks for that owner
        """
        return [
            task for task in self.tasks.values()
            if task.owner.lower() == owner.lower() and
            task.status != TaskStatus.COMPLETED
        ]

    def get_tasks_by_status(self, status: TaskStatus) -> List[Task]:
        """Get tasks with specific status.

        Args:
            status: Task status

        Returns:
            List of tasks with that status
        """
        return [
            task for task in self.tasks.values()
            if task.status == status
        ]

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get summary statistics.

        Returns:
            Dictionary with task counts and stats
        """
        total = len(self.tasks)
        pending = len([t for t in self.tasks.values() if t.status == TaskStatus.PENDING])
        in_progress = len([t for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS])
        completed = len([t for t in self.tasks.values() if t.status == TaskStatus.COMPLETED])
        overdue = len(self.get_overdue_tasks())

        return {
            'total': total,
            'pending': pending,
            'in_progress': in_progress,
            'completed': completed,
            'overdue': overdue,
            'completion_rate': (completed / total * 100) if total > 0 else 0,
        }

    def sync_to_drive(self, folder_id: str) -> bool:
        """Sync tasks to Google Drive as a formatted table.

        Args:
            folder_id: Target folder ID in Drive

        Returns:
            True if successful, False otherwise
        """
        try:
            from .google_drive_manager import GoogleDriveManager

            manager = GoogleDriveManager()

            # Create CSV content
            csv_content = self._generate_csv()

            # Upload to Drive
            file_name = f"tasks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            file_id = manager.upload_file(
                file_path=None,  # We'll handle this differently for in-memory content
                folder_id=folder_id,
                file_name=file_name,
                mime_type='text/csv'
            )

            if file_id:
                self.logger.info(f"Synced tasks to Drive (file ID: {file_id})")
                return True
            else:
                self.logger.error("Failed to sync tasks to Drive")
                return False

        except Exception as e:
            self.logger.error(f"Failed to sync tasks to Drive: {e}")
            return False

    def load_from_drive(self, folder_id: str) -> bool:
        """Load tasks from Drive CSV file.

        Args:
            folder_id: Folder ID in Drive

        Returns:
            True if successful, False otherwise
        """
        try:
            from .google_drive_manager import GoogleDriveManager

            manager = GoogleDriveManager()

            # Find tasks CSV file
            files = manager.list_files(folder_id, mime_type='text/csv')
            task_files = [f for f in files if 'tasks_' in f['name']]

            if not task_files:
                self.logger.info("No task files found in Drive")
                return False

            # Get the most recent one
            latest = sorted(task_files, key=lambda x: x.get('modifiedTime', ''))[-1]
            file_id = latest['id']

            # Download and parse
            temp_file = "/tmp/tasks_sync.csv"
            if manager.download_file(file_id, temp_file):
                self._load_from_csv(temp_file)
                self.logger.info("Loaded tasks from Drive")
                return True

        except Exception as e:
            self.logger.error(f"Failed to load tasks from Drive: {e}")
            return False

    def _generate_csv(self) -> str:
        """Generate CSV representation of tasks."""
        lines = ["ID,Title,Owner,Deadline,Status,Priority,Meeting"]
        for task in self.tasks.values():
            deadline_str = task.deadline.isoformat() if task.deadline else ""
            meeting_str = task.meeting_id or ""
            lines.append(
                f'"{task.id}","{task.title}","{task.owner}","{deadline_str}","{task.status.value}","{task.priority}","{meeting_str}"'
            )
        return "\n".join(lines)

    def _load_from_csv(self, file_path: str) -> None:
        """Load tasks from CSV file.

        Args:
            file_path: Path to CSV file
        """
        try:
            import csv
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if not row['ID']:
                        continue
                    task = Task(
                        id=row['ID'],
                        title=row['Title'],
                        owner=row['Owner'],
                        status=TaskStatus(row['Status']),
                        priority=int(row['Priority']),
                        meeting_id=row.get('Meeting') or None,
                    )
                    if row['Deadline']:
                        task.deadline = datetime.fromisoformat(row['Deadline'])
                    self.tasks[task.id] = task
        except Exception as e:
            self.logger.error(f"Failed to load CSV: {e}")

    def _save_to_disk(self) -> None:
        """Save tasks to persistent storage."""
        try:
            data = {
                'tasks': {k: v.to_dict() for k, v in self.tasks.items()},
                'last_updated': datetime.now(timezone.utc).isoformat(),
            }
            with open(self.tasks_file, 'w') as f:
                json.dump(data, f, indent=2)
            self.logger.debug(f"Saved {len(self.tasks)} tasks to {self.tasks_file}")
        except Exception as e:
            self.logger.error(f"Failed to save tasks: {e}")

    def _load_from_disk(self) -> None:
        """Load tasks from persistent storage."""
        try:
            if not self.tasks_file.exists():
                self.logger.info("No existing tasks file found")
                return

            with open(self.tasks_file, 'r') as f:
                data = json.load(f)

            self.tasks = {
                task_id: Task.from_dict(task_data)
                for task_id, task_data in data.get('tasks', {}).items()
            }
            self.logger.info(f"Loaded {len(self.tasks)} tasks from {self.tasks_file}")
        except Exception as e:
            self.logger.error(f"Failed to load tasks: {e}")
