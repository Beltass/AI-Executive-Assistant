"""Shared pytest fixtures.

Two run artefacts have REAL, committed default paths, and a test that exercises
the CLI would otherwise rewrite them in the working tree — and, on CI, quietly
disagree with what was committed:

* the dashboard's status file (``frontend/status.json``);
* the findings ledger (``.assistant_state/findings.json``), which additionally
  has to start EMPTY in every test, or dedup results would leak from one test
  into the next.

Both are redirected into ``tmp_path`` for every test and the process-wide
ledger is reset, which keeps the suite side-effect free and each test
independent. Tests that care about either file set their own explicit path.
"""

from __future__ import annotations

import pytest

from ai_assistant import memory
from ai_assistant.status_report import STATUS_FILE_ENV


@pytest.fixture(autouse=True)
def _status_report_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv(STATUS_FILE_ENV, str(tmp_path / "status.json"))


@pytest.fixture(autouse=True)
def _findings_memory_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setenv(memory.MEMORY_FILE_ENV, str(tmp_path / "findings.json"))
    memory.reset()
    yield
    memory.reset()
