"""Tests for ``scripts/upload_docs_to_drive.py``.

The point of these is the honesty contract: a run with no Google credentials
must SAY it skipped, and a failed upload must fail the process instead of
reporting a success that never happened.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "upload_docs_to_drive.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("upload_docs_to_drive", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script():
    return _load_script()


def test_guide_exists():
    """The document the script publishes is really in the repository."""
    module = _load_script()
    for rel_path, _ in module.DOCUMENTS:
        assert (REPO_ROOT / rel_path).is_file(), rel_path


def test_skips_without_credentials(script, monkeypatch, capsys):
    """No Google credentials: say so, exit 0, and never touch Drive."""
    from ai_assistant.integrations import google_auth

    monkeypatch.setattr(google_auth, "google_configured", lambda: False)
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "folder-123")

    def _boom():  # pragma: no cover - must never run
        raise AssertionError("DriveClient must not be constructed")

    monkeypatch.setattr(
        "ai_assistant.integrations.google_drive.DriveClient", lambda: _boom()
    )

    assert script.upload_documents() == 0
    assert "atlandı" in capsys.readouterr().out


def test_skips_without_folder_id(script, monkeypatch, capsys):
    """Credentials but no destination folder: skip, exit 0, no fake success."""
    from ai_assistant.integrations import google_auth

    monkeypatch.setattr(google_auth, "google_configured", lambda: True)
    monkeypatch.delenv("GOOGLE_DRIVE_FOLDER_ID", raising=False)

    assert script.upload_documents() == 0
    out = capsys.readouterr().out
    assert "GOOGLE_DRIVE_FOLDER_ID" in out
    assert "Yüklendi" not in out


def test_failed_upload_returns_error(script, monkeypatch, capsys):
    """A Drive error is reported and exits non-zero."""
    from ai_assistant.integrations import google_auth, google_drive

    monkeypatch.setattr(google_auth, "google_configured", lambda: True)
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "folder-123")

    class _Client:
        def upload_report(self, **kwargs):
            raise google_drive.DriveError("quota exceeded")

    monkeypatch.setattr(google_drive, "DriveClient", lambda: _Client())

    assert script.upload_documents() == 1
    assert "quota exceeded" in capsys.readouterr().out


def test_missing_file_id_is_not_success(script, monkeypatch, capsys):
    """An empty file id is a failure, not a silent success."""
    from ai_assistant.integrations import google_auth, google_drive

    monkeypatch.setattr(google_auth, "google_configured", lambda: True)
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "folder-123")

    class _Client:
        def upload_report(self, **kwargs):
            return ""

    monkeypatch.setattr(google_drive, "DriveClient", lambda: _Client())

    assert script.upload_documents() == 1
    assert "Yüklendi" not in capsys.readouterr().out


def test_successful_upload(script, monkeypatch, capsys):
    """A real file id from Drive is the only success path."""
    from ai_assistant.integrations import google_auth, google_drive

    monkeypatch.setattr(google_auth, "google_configured", lambda: True)
    monkeypatch.setenv("GOOGLE_DRIVE_FOLDER_ID", "folder-123")

    calls = []

    class _Client:
        def upload_report(self, **kwargs):
            calls.append(kwargs)
            return "file-abc"

    monkeypatch.setattr(google_drive, "DriveClient", lambda: _Client())

    assert script.upload_documents() == 0
    assert len(calls) == len(script.DOCUMENTS)
    assert calls[0]["folder_id"] == "folder-123"
    assert calls[0]["file_name"] == "AJAN_KULLANIM_KILAVUZU.md"
    assert calls[0]["mime_type"] == google_drive.MIME_TYPE_MARKDOWN
    assert calls[0]["file_content"].strip()
    assert "Yüklendi" in capsys.readouterr().out
