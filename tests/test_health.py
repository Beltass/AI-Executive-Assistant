"""Tests for the connection-check aggregation.

These tests run with NO credentials configured, so every integration
should report ``skipped`` and the overall run must not fail or crash.
"""

from __future__ import annotations

import pytest

from ai_assistant.config import INTEGRATIONS
from ai_assistant.health import run_all_checks, summarize
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED

# Env vars used by any integration; cleared so checks skip deterministically.
_ALL_ENV_VARS = [
    "GOOGLE_OAUTH_ACCESS_TOKEN",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_CREDENTIALS_FILE",
    "SLACK_BOT_TOKEN",
    "TODOIST_API_TOKEN",
    "NOTION_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
]


@pytest.fixture()
def no_credentials(monkeypatch, tmp_path):
    for var in _ALL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    # Point the Google token file at a path that does not exist so the
    # Google checks deterministically report ``skipped`` regardless of the
    # developer's working directory.
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "no_such_token.json"))
    yield


def test_run_all_checks_returns_one_result_per_integration(no_credentials):
    results = run_all_checks()
    assert len(results) == len(INTEGRATIONS)


def test_all_checks_skipped_without_credentials(no_credentials):
    results = run_all_checks()
    for r in results:
        assert r.status == STATUS_SKIPPED, f"{r.name} was {r.status}: {r.detail}"
        assert r.detail  # a skip reason is always provided


def test_summary_counts_add_up(no_credentials):
    results = run_all_checks()
    counts = summarize(results)
    total = counts[STATUS_OK] + counts[STATUS_FAILED] + counts[STATUS_SKIPPED]
    assert total == len(results)
    assert counts[STATUS_FAILED] == 0
    assert counts[STATUS_SKIPPED] == len(results)


def test_results_are_structured(no_credentials):
    results = run_all_checks()
    for r in results:
        assert r.name
        assert r.status in {STATUS_OK, STATUS_FAILED, STATUS_SKIPPED}
