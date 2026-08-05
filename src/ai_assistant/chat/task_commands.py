"""Slack slash commands for task management.

Implements commands:
- /task create "title" "@person" "deadline" "priority"
- /task list [mine|@person]
- /task done <id>
- /task reschedule <id> "date"
- /task assign <id> "@person"
- /task priority <id> "level"
- /task notes <id> "text"

Commands sync with Google Drive and update task tracking system.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of a command execution."""

    success: bool
    message: str
    task_id: Optional[str] = None
    blocks: Optional[List[Dict[str, Any]]] = None  # Slack block kit format


class TaskCommandParser:
    """Parses Slack slash commands for task management."""

    def __init__(self, task_tracker=None, notification_manager=None):
        """Initialize TaskCommandParser.

        Args:
            task_tracker: TaskTracker instance
            notification_manager: NotificationManager instance
        """
        self.task_tracker = task_tracker
        self.notification_manager = notification_manager

    def parse_command(self, command_text: str, user_id: str) -> CommandResult:
        """Parse and execute a slash command.

        Args:
            command_text: Raw slash command text (without leading /)
            user_id: Slack user ID of command issuer

        Returns:
            CommandResult with execution status
        """
        parts = command_text.strip().split(None, 1)
        if not parts:
            return CommandResult(
                success=False, message="Usage: /task <subcommand> [args]"
            )

        subcommand = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Route to appropriate handler
        handlers = {
            "create": self._handle_create,
            "list": self._handle_list,
            "done": self._handle_done,
            "reschedule": self._handle_reschedule,
            "assign": self._handle_assign,
            "priority": self._handle_priority,
            "notes": self._handle_notes,
        }

        if subcommand in handlers:
            return handlers[subcommand](args, user_id)
        else:
            return CommandResult(
                success=False,
                message=f"Unknown subcommand: {subcommand}. Available: "
                f"create, list, done, reschedule, assign, priority, notes",
            )

    def _handle_create(self, args: str, user_id: str) -> CommandResult:
        """Handle /task create command.

        Format: /task create "Title" "@person" "2026-08-10" "HIGH"
        """
        if not self.task_tracker:
            return CommandResult(
                success=False, message="Task tracker not available"
            )

        # Parse quoted arguments
        parts = self._parse_quoted_args(args, 4)
        if len(parts) < 3:
            return CommandResult(
                success=False,
                message="Usage: /task create \"Title\" \"@person\" \"YYYY-MM-DD\" "
                "[priority: 1-5]",
            )

        title = parts[0]
        owner = parts[1].lstrip("@")
        deadline_str = parts[2]
        priority = self._parse_priority(parts[3] if len(parts) > 3 else "3")

        # Parse deadline
        try:
            deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d")
            deadline = deadline_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return CommandResult(
                success=False,
                message=f"Invalid date format: {deadline_str}. Use YYYY-MM-DD",
            )

        # Create task
        import uuid

        task_id = str(uuid.uuid4())[:8]
        from ..integrations.task_tracker import Task, TaskStatus

        task = Task(
            id=task_id,
            title=title,
            description=f"Created by {user_id}",
            owner=owner,
            deadline=deadline,
            priority=priority,
            status=TaskStatus.PENDING,
        )

        self.task_tracker.add_task(task)

        return CommandResult(
            success=True,
            message=f"✅ Task created: {title}\n"
            f"Owner: @{owner}\n"
            f"Deadline: {deadline_str}\n"
            f"Priority: {priority}/5",
            task_id=task_id,
            blocks=self._format_task_blocks(task),
        )

    def _handle_list(self, args: str, user_id: str) -> CommandResult:
        """Handle /task list command.

        Formats:
        - /task list (all active)
        - /task list mine (user's tasks)
        - /task list @person (person's tasks)
        """
        if not self.task_tracker:
            return CommandResult(
                success=False, message="Task tracker not available"
            )

        filter_type = args.strip().lower() if args else "all"
        tasks = []

        if filter_type == "all":
            tasks = [
                t
                for t in self.task_tracker.tasks.values()
                if t.status != "completed"
            ]
        elif filter_type == "mine":
            tasks = self.task_tracker.get_tasks_by_owner(user_id)
        elif filter_type.startswith("@"):
            owner = filter_type.lstrip("@")
            tasks = self.task_tracker.get_tasks_by_owner(owner)
        else:
            return CommandResult(
                success=False,
                message="Usage: /task list [all|mine|@person]",
            )

        if not tasks:
            return CommandResult(
                success=True,
                message="No tasks found.",
            )

        # Sort by deadline
        tasks.sort(key=lambda t: t.deadline or datetime.max.replace(tzinfo=timezone.utc))

        # Build block format
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"📋 Tasks ({len(tasks)} active)",
                },
            }
        ]

        for task in tasks[:20]:  # Limit to 20 to avoid message size limits
            deadline_str = (
                task.deadline.strftime("%Y-%m-%d")
                if task.deadline
                else "No deadline"
            )
            days_left = task.days_until_deadline if task.deadline else None
            urgency = ""
            if days_left is not None:
                if days_left < 0:
                    urgency = " ⚠️ OVERDUE"
                elif days_left == 0:
                    urgency = " 🔴 TODAY"
                elif days_left <= 1:
                    urgency = " 🟠 1 DAY"

            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{task.title}* {urgency}\n"
                        f"Owner: @{task.owner} | Deadline: {deadline_str} | Priority: {task.priority}/5",
                    },
                }
            )

        return CommandResult(
            success=True,
            message=f"Found {len(tasks)} tasks",
            blocks=blocks,
        )

    def _handle_done(self, args: str, user_id: str) -> CommandResult:
        """Handle /task done command.

        Format: /task done <task_id>
        """
        if not self.task_tracker:
            return CommandResult(
                success=False, message="Task tracker not available"
            )

        task_id = args.strip()
        if not task_id:
            return CommandResult(
                success=False,
                message="Usage: /task done <task_id>",
            )

        task = self.task_tracker.get_task(task_id)
        if not task:
            return CommandResult(
                success=False,
                message=f"Task {task_id} not found",
            )

        from ..integrations.task_tracker import TaskStatus

        self.task_tracker.update_status(task_id, TaskStatus.COMPLETED)

        return CommandResult(
            success=True,
            message=f"✅ Marked done: {task.title}",
        )

    def _handle_reschedule(self, args: str, user_id: str) -> CommandResult:
        """Handle /task reschedule command.

        Format: /task reschedule <task_id> "2026-08-15"
        """
        if not self.task_tracker:
            return CommandResult(
                success=False, message="Task tracker not available"
            )

        parts = args.split(None, 1)
        if len(parts) < 2:
            return CommandResult(
                success=False,
                message="Usage: /task reschedule <task_id> \"YYYY-MM-DD\"",
            )

        task_id = parts[0]
        deadline_str = parts[1].strip('"')

        task = self.task_tracker.get_task(task_id)
        if not task:
            return CommandResult(
                success=False,
                message=f"Task {task_id} not found",
            )

        try:
            deadline_dt = datetime.strptime(deadline_str, "%Y-%m-%d")
            task.deadline = deadline_dt.replace(tzinfo=timezone.utc)
            task.updated_at = datetime.now(timezone.utc)
            self.task_tracker._save_to_disk()

            return CommandResult(
                success=True,
                message=f"🔄 Rescheduled: {task.title}\nNew deadline: {deadline_str}",
            )
        except ValueError:
            return CommandResult(
                success=False,
                message=f"Invalid date format: {deadline_str}. Use YYYY-MM-DD",
            )

    def _handle_assign(self, args: str, user_id: str) -> CommandResult:
        """Handle /task assign command.

        Format: /task assign <task_id> "@person"
        """
        if not self.task_tracker:
            return CommandResult(
                success=False, message="Task tracker not available"
            )

        parts = args.split(None, 1)
        if len(parts) < 2:
            return CommandResult(
                success=False,
                message="Usage: /task assign <task_id> \"@person\"",
            )

        task_id = parts[0]
        new_owner = parts[1].strip('"@')

        task = self.task_tracker.get_task(task_id)
        if not task:
            return CommandResult(
                success=False,
                message=f"Task {task_id} not found",
            )

        old_owner = task.owner
        task.owner = new_owner
        task.updated_at = datetime.now(timezone.utc)
        self.task_tracker._save_to_disk()

        return CommandResult(
            success=True,
            message=f"👤 Reassigned: {task.title}\nOld: @{old_owner} → New: @{new_owner}",
        )

    def _handle_priority(self, args: str, user_id: str) -> CommandResult:
        """Handle /task priority command.

        Format: /task priority <task_id> <1-5>
        """
        if not self.task_tracker:
            return CommandResult(
                success=False, message="Task tracker not available"
            )

        parts = args.split()
        if len(parts) < 2:
            return CommandResult(
                success=False,
                message="Usage: /task priority <task_id> <1-5>",
            )

        task_id = parts[0]
        priority_str = parts[1]

        task = self.task_tracker.get_task(task_id)
        if not task:
            return CommandResult(
                success=False,
                message=f"Task {task_id} not found",
            )

        try:
            priority = int(priority_str)
            if priority < 1 or priority > 5:
                raise ValueError("Priority must be 1-5")

            task.priority = priority
            task.updated_at = datetime.now(timezone.utc)
            self.task_tracker._save_to_disk()

            return CommandResult(
                success=True,
                message=f"Priority updated: {task.title}\nNew priority: {priority}/5",
            )
        except ValueError as e:
            return CommandResult(
                success=False,
                message=f"Invalid priority: {priority_str}. {str(e)}",
            )

    def _handle_notes(self, args: str, user_id: str) -> CommandResult:
        """Handle /task notes command.

        Format: /task notes <task_id> "text"
        """
        if not self.task_tracker:
            return CommandResult(
                success=False, message="Task tracker not available"
            )

        parts = args.split(None, 1)
        if len(parts) < 2:
            return CommandResult(
                success=False,
                message="Usage: /task notes <task_id> \"note text\"",
            )

        task_id = parts[0]
        note_text = parts[1].strip('"')

        task = self.task_tracker.get_task(task_id)
        if not task:
            return CommandResult(
                success=False,
                message=f"Task {task_id} not found",
            )

        # Append note to description
        if task.description:
            task.description += f"\n\n[Note] {note_text}"
        else:
            task.description = f"[Note] {note_text}"

        task.updated_at = datetime.now(timezone.utc)
        self.task_tracker._save_to_disk()

        return CommandResult(
            success=True,
            message=f"📝 Note added: {task.title}",
        )

    # Helper methods

    @staticmethod
    def _parse_quoted_args(text: str, expected: int) -> List[str]:
        """Parse quoted arguments from command text.

        Example:
            '"Title" "@person" "2026-08-10" "HIGH"'
            -> ["Title", "@person", "2026-08-10", "HIGH"]
        """
        pattern = r'"([^"]*)"'
        matches = re.findall(pattern, text)
        return matches[:expected]

    @staticmethod
    def _parse_priority(priority_str: str) -> int:
        """Parse priority from string (1-5 or LOW/HIGH).

        Args:
            priority_str: Priority value

        Returns:
            Priority as integer 1-5
        """
        try:
            priority = int(priority_str)
            return max(1, min(5, priority))  # Clamp to 1-5
        except ValueError:
            pass

        # Try named levels
        named_levels = {
            "critical": 5,
            "high": 4,
            "medium": 3,
            "low": 2,
            "minimal": 1,
        }

        return named_levels.get(priority_str.lower(), 3)

    @staticmethod
    def _format_task_blocks(task) -> List[Dict[str, Any]]:
        """Format task as Slack blocks.

        Args:
            task: Task object

        Returns:
            List of Slack block dicts
        """
        deadline_str = (
            task.deadline.strftime("%Y-%m-%d") if task.deadline else "No deadline"
        )

        return [
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Task:*\n{task.title}"},
                    {"type": "mrkdwn", "text": f"*Owner:*\n@{task.owner}"},
                    {"type": "mrkdwn", "text": f"*Deadline:*\n{deadline_str}"},
                    {"type": "mrkdwn", "text": f"*Priority:*\n{task.priority}/5"},
                ],
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"Task ID: `{task.id}` | Status: {task.status.value}",
                    }
                ],
            },
        ]
