"""Todoist connection check."""

from __future__ import annotations

import os

from ..config import get_integration
from . import CheckResult
from ._common import classify_response, failed, http_get, skipped

SPEC = get_integration("todoist")
PROJECTS_URL = "https://api.todoist.com/rest/v2/projects"


def check_connection() -> CheckResult:
    """List projects to confirm the Todoist API token is valid."""
    missing = SPEC.missing_env()
    if missing:
        return skipped(SPEC.name, missing)

    token = os.getenv("TODOIST_API_TOKEN", "")
    try:
        resp = http_get(PROJECTS_URL, headers={"Authorization": f"Bearer {token}"})
    except Exception as exc:
        return failed(SPEC.name, f"request error: {exc}")
    return classify_response(SPEC.name, resp)
