"""Asana project and task management integration.

This module provides clients for creating projects, tasks, and subtasks in Asana,
as well as converting advisor reports into actionable Asana tasks. It handles
authentication via ASANA_TOKEN and includes resilience against rate-limiting.

Configuration (all via environment variables):
    * ``ASANA_TOKEN`` — Personal access token for Asana API.
    * ``ASANA_WORKSPACE_ID`` — Workspace ID where projects will be created.
    * ``ASANA_PROJECT_TEMPLATE`` — Template name for project IDs (e.g. "advisor_project").
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from ..config import REQUEST_TIMEOUT, get_integration
from . import CheckResult
from ._common import classify_response, failed, http_get, http_post, ok, skipped

logger = logging.getLogger(__name__)

SPEC = get_integration("asana")
BASE_URL = "https://api.asana.com/1.0"
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1  # seconds


def check_connection() -> CheckResult:
    """Verify Asana authentication by fetching user information."""
    missing = SPEC.missing_env()
    if missing:
        return skipped(SPEC.name, missing)

    token = os.getenv("ASANA_TOKEN", "")
    try:
        resp = http_get(
            f"{BASE_URL}/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception as exc:
        return failed(SPEC.name, f"request error: {exc}")
    return classify_response(SPEC.name, resp)


@dataclass
class TaskResult:
    """Result of a task operation."""

    success: bool
    task_id: Optional[str] = None
    task_name: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ProjectResult:
    """Result of a project operation."""

    success: bool
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ConversionResult:
    """Result of report-to-Asana conversion."""

    success: bool
    task_results: List[TaskResult] = field(default_factory=list)
    failed_count: int = 0
    errors: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, Any]:
        """Return a summary dict suitable for JSON serialization."""
        return {
            "success": self.success,
            "tasks_created": len([r for r in self.task_results if r.success]),
            "tasks_failed": self.failed_count,
            "errors": self.errors,
        }


class AsanaClient:
    """Client for interacting with the Asana API.

    Handles project creation, task management, and error resilience including
    rate-limit retry logic. All API calls are made with authentication headers
    and include retry-on-429 support.
    """

    def __init__(self, token: Optional[str] = None, workspace_id: Optional[str] = None):
        """Initialize the Asana client.

        Args:
            token: Asana API token. Defaults to ASANA_TOKEN environment variable.
            workspace_id: Default workspace ID. Defaults to ASANA_WORKSPACE_ID env var.
        """
        self.token = token or os.getenv("ASANA_TOKEN", "")
        self.workspace_id = workspace_id or os.getenv("ASANA_WORKSPACE_ID", "")

        if not self.token:
            logger.warning("ASANA_TOKEN not configured")

    def _headers(self) -> Dict[str, str]:
        """Return standard Asana API headers."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _retry_with_backoff(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute an HTTP request with retry logic for rate limits (429).

        Args:
            method: HTTP method (GET, POST, etc).
            url: Full URL to request.
            **kwargs: Additional arguments to pass to httpx.

        Returns:
            The HTTP response object.

        Raises:
            httpx.HTTPError: If the request fails after all retries.
        """
        for attempt in range(MAX_RETRIES):
            try:
                if method.upper() == "GET":
                    resp = httpx.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
                elif method.upper() == "POST":
                    resp = httpx.post(url, timeout=REQUEST_TIMEOUT, **kwargs)
                elif method.upper() == "PUT":
                    resp = httpx.put(url, timeout=REQUEST_TIMEOUT, **kwargs)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # Rate limit: respect 429 with exponential backoff.
                if resp.status_code == 429:
                    if attempt < MAX_RETRIES - 1:
                        retry_after = int(
                            resp.headers.get("Retry-After", RETRY_BASE_DELAY)
                        )
                        delay = retry_after * (2**attempt)
                        logger.info(
                            f"Rate limited; retrying after {delay}s (attempt {attempt + 1})"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        logger.error("Max retries exceeded for rate-limited request")

                return resp
            except httpx.RequestError as exc:
                if attempt == MAX_RETRIES - 1:
                    raise
                delay = RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    f"Request error on attempt {attempt + 1}, retrying in {delay}s: {exc}"
                )
                time.sleep(delay)

        raise httpx.HTTPError("Max retries exceeded")

    def create_project(
        self,
        name: str,
        description: str = "",
        workspace_id: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> ProjectResult:
        """Create a new Asana project.

        Args:
            name: Project name.
            description: Project description.
            workspace_id: Workspace ID. Defaults to self.workspace_id.
            team_id: Optional team ID for the project.

        Returns:
            ProjectResult with success status and project ID on success.
        """
        workspace = workspace_id or self.workspace_id
        if not workspace:
            return ProjectResult(
                success=False,
                error="workspace_id not provided and ASANA_WORKSPACE_ID not set",
            )

        payload = {
            "data": {
                "name": name,
                "workspace": workspace,
            }
        }
        if description:
            payload["data"]["notes"] = description
        if team_id:
            payload["data"]["team"] = team_id

        try:
            resp = self._retry_with_backoff(
                "POST",
                f"{BASE_URL}/projects",
                headers=self._headers(),
                json=payload,
            )

            if resp.status_code == 201:
                data = resp.json()
                project = data.get("data", {})
                project_id = project.get("gid")
                logger.info(f"Created project '{name}' (ID: {project_id})")
                return ProjectResult(
                    success=True,
                    project_id=project_id,
                    project_name=name,
                )

            error_msg = f"HTTP {resp.status_code}"
            try:
                error_data = resp.json()
                if "errors" in error_data:
                    error_msg = error_data["errors"][0].get("message", error_msg)
            except Exception:
                pass

            logger.error(f"Failed to create project '{name}': {error_msg}")
            return ProjectResult(success=False, error=error_msg)

        except Exception as exc:
            logger.error(f"Exception creating project '{name}': {exc}")
            return ProjectResult(success=False, error=str(exc))

    def get_or_create_project(
        self,
        project_name: str,
        workspace_id: Optional[str] = None,
    ) -> ProjectResult:
        """Find an existing project or create a new one.

        Searches for a project by exact name match in the workspace. If found,
        returns it; otherwise creates a new one.

        Args:
            project_name: Name of the project.
            workspace_id: Workspace ID. Defaults to self.workspace_id.

        Returns:
            ProjectResult with the existing or newly created project ID.
        """
        workspace = workspace_id or self.workspace_id
        if not workspace:
            return ProjectResult(
                success=False,
                error="workspace_id not provided and ASANA_WORKSPACE_ID not set",
            )

        # Search for existing project.
        try:
            resp = self._retry_with_backoff(
                "GET",
                f"{BASE_URL}/projects?workspace={workspace}&opt_fields=name,gid",
                headers=self._headers(),
            )

            if resp.status_code == 200:
                data = resp.json()
                for project in data.get("data", []):
                    if project.get("name") == project_name:
                        logger.info(f"Found existing project '{project_name}'")
                        return ProjectResult(
                            success=True,
                            project_id=project.get("gid"),
                            project_name=project_name,
                        )

        except Exception as exc:
            logger.warning(f"Error searching for project: {exc}")

        # Not found, create a new one.
        return self.create_project(project_name, workspace_id=workspace)

    def add_task(
        self,
        project_id: str,
        task_name: str,
        assignee_email: Optional[str] = None,
        due_date: Optional[str] = None,
        description: Optional[str] = None,
    ) -> TaskResult:
        """Create a new task in a project.

        Args:
            project_id: Target project ID.
            task_name: Name of the task (required).
            assignee_email: Email of the person to assign the task to.
            due_date: Due date in YYYY-MM-DD format.
            description: Task description/notes.

        Returns:
            TaskResult with success status and task ID on success.
        """
        if not project_id or not task_name:
            return TaskResult(
                success=False, error="project_id and task_name are required"
            )

        payload = {
            "data": {
                "name": task_name,
                "projects": [project_id],
            }
        }

        if assignee_email:
            payload["data"]["assignee"] = assignee_email
        if due_date:
            payload["data"]["due_on"] = due_date
        if description:
            payload["data"]["notes"] = description

        try:
            resp = self._retry_with_backoff(
                "POST",
                f"{BASE_URL}/tasks",
                headers=self._headers(),
                json=payload,
            )

            if resp.status_code == 201:
                data = resp.json()
                task = data.get("data", {})
                task_id = task.get("gid")
                logger.info(f"Created task '{task_name}' (ID: {task_id})")
                return TaskResult(
                    success=True,
                    task_id=task_id,
                    task_name=task_name,
                )

            error_msg = f"HTTP {resp.status_code}"
            try:
                error_data = resp.json()
                if "errors" in error_data:
                    error_msg = error_data["errors"][0].get("message", error_msg)
            except Exception:
                pass

            logger.error(f"Failed to create task '{task_name}': {error_msg}")
            return TaskResult(success=False, task_name=task_name, error=error_msg)

        except Exception as exc:
            logger.error(f"Exception creating task '{task_name}': {exc}")
            return TaskResult(success=False, task_name=task_name, error=str(exc))

    def create_subtask(
        self,
        task_id: str,
        subtask_name: str,
        description: Optional[str] = None,
    ) -> TaskResult:
        """Create a subtask for a parent task.

        Args:
            task_id: Parent task ID.
            subtask_name: Name of the subtask.
            description: Subtask description/notes.

        Returns:
            TaskResult with success status and subtask ID on success.
        """
        if not task_id or not subtask_name:
            return TaskResult(
                success=False, error="task_id and subtask_name are required"
            )

        payload = {
            "data": {
                "name": subtask_name,
            }
        }
        if description:
            payload["data"]["notes"] = description

        try:
            resp = self._retry_with_backoff(
                "POST",
                f"{BASE_URL}/tasks/{task_id}/subtasks",
                headers=self._headers(),
                json=payload,
            )

            if resp.status_code == 201:
                data = resp.json()
                subtask = data.get("data", {})
                subtask_id = subtask.get("gid")
                logger.info(f"Created subtask '{subtask_name}' (ID: {subtask_id})")
                return TaskResult(
                    success=True,
                    task_id=subtask_id,
                    task_name=subtask_name,
                )

            error_msg = f"HTTP {resp.status_code}"
            try:
                error_data = resp.json()
                if "errors" in error_data:
                    error_msg = error_data["errors"][0].get("message", error_msg)
            except Exception:
                pass

            logger.error(f"Failed to create subtask '{subtask_name}': {error_msg}")
            return TaskResult(success=False, task_name=subtask_name, error=error_msg)

        except Exception as exc:
            logger.error(f"Exception creating subtask '{subtask_name}': {exc}")
            return TaskResult(success=False, task_name=subtask_name, error=str(exc))

    def complete_task(
        self,
        task_id: str,
        completion_notes: Optional[str] = None,
    ) -> TaskResult:
        """Mark a task as complete.

        Optionally adds a note to document why the task is complete.

        Args:
            task_id: ID of the task to complete.
            completion_notes: Optional notes to add before completing.

        Returns:
            TaskResult with success status.
        """
        if not task_id:
            return TaskResult(success=False, error="task_id is required")

        payload = {
            "data": {
                "completed": True,
            }
        }
        if completion_notes:
            payload["data"]["notes"] = completion_notes

        try:
            resp = self._retry_with_backoff(
                "PUT",
                f"{BASE_URL}/tasks/{task_id}",
                headers=self._headers(),
                json=payload,
            )

            if resp.status_code == 200:
                logger.info(f"Marked task {task_id} as complete")
                return TaskResult(success=True, task_id=task_id)

            error_msg = f"HTTP {resp.status_code}"
            try:
                error_data = resp.json()
                if "errors" in error_data:
                    error_msg = error_data["errors"][0].get("message", error_msg)
            except Exception:
                pass

            logger.error(f"Failed to complete task {task_id}: {error_msg}")
            return TaskResult(success=False, task_id=task_id, error=error_msg)

        except Exception as exc:
            logger.error(f"Exception completing task {task_id}: {exc}")
            return TaskResult(success=False, task_id=task_id, error=str(exc))

    def add_attachment_url(
        self,
        task_id: str,
        url_title: str,
        url: str,
    ) -> TaskResult:
        """Add a link attachment (e.g. Google Drive document) to a task.

        Args:
            task_id: ID of the task.
            url_title: Display name for the link.
            url: URL to attach.

        Returns:
            TaskResult with success status.
        """
        if not task_id or not url:
            return TaskResult(success=False, error="task_id and url are required")

        payload = {
            "data": {
                "resource_subtype": "external_attachment",
                "resource": {
                    "name": url_title,
                    "resource_subtype": "external_link",
                    "url": url,
                },
            }
        }

        try:
            resp = self._retry_with_backoff(
                "POST",
                f"{BASE_URL}/tasks/{task_id}/attachments",
                headers=self._headers(),
                json=payload,
            )

            if resp.status_code == 201:
                logger.info(f"Added attachment '{url_title}' to task {task_id}")
                return TaskResult(success=True, task_id=task_id)

            error_msg = f"HTTP {resp.status_code}"
            try:
                error_data = resp.json()
                if "errors" in error_data:
                    error_msg = error_data["errors"][0].get("message", error_msg)
            except Exception:
                pass

            logger.error(f"Failed to add attachment to task {task_id}: {error_msg}")
            return TaskResult(success=False, task_id=task_id, error=error_msg)

        except Exception as exc:
            logger.error(f"Exception adding attachment to task {task_id}: {exc}")
            return TaskResult(success=False, task_id=task_id, error=str(exc))


class ReportToAsanaConverter:
    """Converts advisor JSON reports into Asana tasks.

    Takes structured JSON output from advisors and extracts actionable items,
    creating them as tasks in the specified Asana project with proper context
    and structure.
    """

    def __init__(self, asana_client: Optional[AsanaClient] = None):
        """Initialize the converter.

        Args:
            asana_client: AsanaClient instance. If not provided, creates a new one.
        """
        self.client = asana_client or AsanaClient()

    def _extract_tasks_from_report(
        self, report: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract actionable items from an advisor report.

        Looks for common task-like structures in the report including:
        - 'actionable_items' or 'actions' arrays
        - 'todos' or 'tasks' arrays
        - Items marked with task-like keywords

        Args:
            report: Parsed JSON report from an advisor.

        Returns:
            List of task dictionaries with extracted metadata.
        """
        tasks = []

        # Look for explicit actionable items.
        for key in ["actionable_items", "actions", "todos", "tasks"]:
            if key in report and isinstance(report[key], list):
                for item in report[key]:
                    if isinstance(item, dict):
                        tasks.append(
                            {
                                "name": item.get("name")
                                or item.get("title")
                                or item.get("text", ""),
                                "description": item.get("description")
                                or item.get("notes", ""),
                                "priority": item.get("priority", "normal"),
                                "due_date": item.get("due_date"),
                            }
                        )
                    elif isinstance(item, str):
                        tasks.append(
                            {
                                "name": item,
                                "description": "",
                                "priority": "normal",
                            }
                        )

        return tasks

    def convert(
        self,
        report: Dict[str, Any],
        project_name: str,
        advisor_name: str = "Advisor",
        assignee_email: Optional[str] = None,
    ) -> ConversionResult:
        """Convert an advisor report to Asana tasks.

        Creates or retrieves the project, extracts tasks from the report, and
        creates them in Asana with context about the advisor and report.

        Args:
            report: Parsed JSON report from an advisor.
            project_name: Name of the Asana project (or will create/find one).
            advisor_name: Name of the advisor (for context and Turkish labels).
            assignee_email: Email to assign tasks to (optional).

        Returns:
            ConversionResult with details about created/failed tasks.
        """
        result = ConversionResult(success=True)

        # Get or create the project.
        project_result = self.client.get_or_create_project(project_name)
        if not project_result.success:
            result.success = False
            result.errors.append(
                f"Failed to create/find project: {project_result.error}"
            )
            return result

        project_id = project_result.project_id

        # Extract tasks from the report.
        tasks = self._extract_tasks_from_report(report)
        if not tasks:
            logger.info(f"No actionable items found in report for {advisor_name}")
            return result

        # Create each task in Asana.
        for task_data in tasks:
            task_name = task_data.get("name", "").strip()
            if not task_name:
                result.errors.append("Skipped empty task name")
                continue

            # Build task description with advisor context.
            description = task_data.get("description", "").strip()
            if advisor_name and advisor_name != "Advisor":
                description = (
                    f"[{advisor_name}]\n{description}"
                    if description
                    else f"[{advisor_name}]"
                )

            task_result = self.client.add_task(
                project_id=project_id,
                task_name=task_name,
                assignee_email=assignee_email,
                due_date=task_data.get("due_date"),
                description=description,
            )

            result.task_results.append(task_result)
            if not task_result.success:
                result.failed_count += 1
                result.errors.append(f"Task '{task_name}': {task_result.error}")

        if result.failed_count > 0:
            result.success = False

        return result
