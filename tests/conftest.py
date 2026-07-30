"""Shared pytest fixtures.

The notifier's CLI writes the dashboard's status file as its last step, whose
default path (``frontend/status.json``) is a REAL, committed file. Any test
that exercises ``slack_notifier.main()`` would otherwise rewrite the sample
data in the working tree — and, on CI, quietly disagree with what was
committed. Redirecting the path for every test keeps the suite side-effect
free; the tests that care about the file set their own explicit path.
"""

from __future__ import annotations

import pytest

from ai_assistant.status_report import STATUS_FILE_ENV


@pytest.fixture(autouse=True)
def _status_report_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv(STATUS_FILE_ENV, str(tmp_path / "status.json"))
