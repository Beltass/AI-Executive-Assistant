"""Shared helpers for integration checks."""

from __future__ import annotations

from typing import List, Optional

import httpx

from ..config import REQUEST_TIMEOUT
from . import CheckResult, STATUS_FAILED, STATUS_OK, STATUS_SKIPPED


def skipped(name: str, missing: List[str]) -> CheckResult:
    """Build a ``skipped`` result naming the missing env vars."""
    joined = ", ".join(missing)
    return CheckResult(
        name=name,
        status=STATUS_SKIPPED,
        detail=f"missing env var(s): {joined}",
    )


def skipped_reason(name: str, detail: str) -> CheckResult:
    """Build a ``skipped`` result with a free-form reason string."""
    return CheckResult(name=name, status=STATUS_SKIPPED, detail=detail)


def ok(name: str, detail: str = "authenticated") -> CheckResult:
    return CheckResult(name=name, status=STATUS_OK, detail=detail)


def failed(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status=STATUS_FAILED, detail=detail)


def http_get(url: str, headers: Optional[dict] = None) -> httpx.Response:
    """Perform a GET with a shared timeout. Raises on transport errors."""
    return httpx.get(url, headers=headers, timeout=REQUEST_TIMEOUT)


def http_post(url: str, headers: Optional[dict] = None, json: Optional[dict] = None) -> httpx.Response:
    """Perform a POST with a shared timeout. Raises on transport errors."""
    return httpx.post(url, headers=headers, json=json, timeout=REQUEST_TIMEOUT)


def classify_response(name: str, resp: httpx.Response) -> CheckResult:
    """Turn an HTTP response into an ok/failed CheckResult.

    2xx -> ok. Anything else -> failed with status code and a short body
    snippet to aid debugging (e.g. 401 invalid credentials).
    """
    if resp.is_success:
        return ok(name, f"HTTP {resp.status_code}")
    snippet = resp.text.strip().replace("\n", " ")[:160]
    return failed(name, f"HTTP {resp.status_code}: {snippet}")
