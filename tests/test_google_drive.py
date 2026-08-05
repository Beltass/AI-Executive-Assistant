"""Tests for ``DriveClient.read_file_text`` — reading a document's CONTENT.

Listing a file and OPENING it are two different permissions. The shared OAuth
consent used to ask only for ``drive.metadata.readonly``, which allows
``files.list`` but neither ``files.export`` nor ``files.get_media``, and a
refresh token minted under that consent keeps those scopes even now that
``drive.readonly`` is requested. So this method must:

* export Google-native documents as text and download everything else;
* raise ``DrivePermissionError`` — not return "" — when the credential may not
  open the file, so the caller can tell the user to re-consent;
* keep an EMPTY string meaning "the document is empty", nothing else.

No network: the Drive service is a stub.
"""

from __future__ import annotations

import pytest

from ai_assistant.integrations import google_drive
from ai_assistant.integrations.google_drive import (
    DriveClient,
    DriveError,
    DrivePermissionError,
)

DOC_MIME = "application/vnd.google-apps.document"


class FakeResponse:
    """An HTTP response shaped enough for the permission classifier."""

    def __init__(self, status):
        self.status = status


class FakeHttpError(Exception):
    def __init__(self, status, message=""):
        super().__init__(message or f"<HttpError {status}>")
        self.resp = FakeResponse(status)


class FakeRequest:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def execute(self):
        if self.error is not None:
            raise self.error
        return self.result


class FakeFiles:
    """Records how the content was asked for."""

    def __init__(self, meta=None, exported=None, media=None, error=None):
        self.meta = meta or {}
        self.exported = exported
        self.media = media
        self.error = error
        self.calls = []

    def get(self, fileId, fields=""):
        self.calls.append(("get", fileId, fields))
        return FakeRequest(result=self.meta, error=self.error)

    def export(self, fileId, mimeType=""):
        self.calls.append(("export", fileId, mimeType))
        return FakeRequest(result=self.exported, error=self.error)

    def get_media(self, fileId):
        self.calls.append(("get_media", fileId, ""))
        return FakeRequest(result=self.media, error=self.error)


def _client(files):
    """A DriveClient whose service is the stub — no auth, no network."""
    client = DriveClient.__new__(DriveClient)
    client.service = type("Service", (), {"files": lambda self: files})()
    return client


@pytest.fixture(autouse=True)
def _no_sleeping(monkeypatch):
    """The retry ladder must never make the suite wait."""
    monkeypatch.setattr(google_drive.time, "sleep", lambda seconds: None)


# --- the two content paths ---------------------------------------------------


def test_a_google_document_is_exported_as_plain_text():
    files = FakeFiles(meta={"mimeType": DOC_MIME}, exported="Toplantı notu")
    assert _client(files).read_file_text("note-1") == "Toplantı notu"
    assert ("export", "note-1", "text/plain") in files.calls


def test_a_binary_file_is_downloaded_and_decoded():
    files = FakeFiles(meta={"mimeType": "text/plain"}, media=b"Karar: \xc3\xb6deme")
    assert _client(files).read_file_text("note-2") == "Karar: ödeme"
    assert ("get_media", "note-2", "") in files.calls


def test_undecodable_bytes_do_not_lose_the_document():
    files = FakeFiles(meta={"mimeType": "text/plain"}, media=b"karar \xff son")
    text = _client(files).read_file_text("note-2")
    assert text.startswith("karar")
    assert text.endswith("son")


def test_a_known_mime_type_saves_the_metadata_round_trip():
    files = FakeFiles(exported="Metin")
    assert _client(files).read_file_text("note-1", mime_type=DOC_MIME) == "Metin"
    assert [call[0] for call in files.calls] == ["export"]


def test_the_text_can_be_truncated():
    files = FakeFiles(meta={"mimeType": DOC_MIME}, exported="0123456789")
    assert _client(files).read_file_text("note-1", max_chars=4) == "0123"


def test_an_empty_document_reads_as_an_empty_string():
    files = FakeFiles(meta={"mimeType": DOC_MIME}, exported="   ")
    assert _client(files).read_file_text("note-1") == ""


# --- the permission path -----------------------------------------------------


def test_a_403_is_a_permission_error_not_an_empty_string():
    files = FakeFiles(meta={"mimeType": DOC_MIME}, error=FakeHttpError(403))
    with pytest.raises(DrivePermissionError):
        _client(files).read_file_text("note-1")


def test_a_401_is_a_permission_error():
    files = FakeFiles(error=FakeHttpError(401))
    with pytest.raises(DrivePermissionError):
        _client(files).read_file_text("note-1")


def test_an_insufficient_scope_message_is_recognised_without_a_status():
    files = FakeFiles(
        meta={"mimeType": DOC_MIME},
        error=RuntimeError("Request had insufficient authentication scopes."),
    )
    with pytest.raises(DrivePermissionError) as excinfo:
        _client(files).read_file_text("note-1")
    assert "note-1" in str(excinfo.value)


def test_a_permission_error_is_still_a_drive_error():
    """Callers that only catch DriveError keep working."""
    assert issubclass(DrivePermissionError, DriveError)


def test_a_permission_failure_is_not_retried(monkeypatch):
    """A missing scope does not heal by waiting — no sleeping, no second try."""
    files = FakeFiles(meta={"mimeType": DOC_MIME}, error=FakeHttpError(403))
    monkeypatch.setattr(
        google_drive.time, "sleep", lambda s: pytest.fail("retried a 403")
    )
    with pytest.raises(DrivePermissionError):
        _client(files).read_file_text("note-1")
    assert len(files.calls) == 1


# --- other failures ----------------------------------------------------------


def test_a_missing_file_id_is_rejected_loudly():
    with pytest.raises(DriveError):
        _client(FakeFiles()).read_file_text("")


def test_a_transport_failure_becomes_a_drive_error():
    files = FakeFiles(
        meta={"mimeType": DOC_MIME}, error=RuntimeError("connection reset")
    )
    with pytest.raises(DriveError) as excinfo:
        _client(files).read_file_text("note-1")
    assert not isinstance(excinfo.value, DrivePermissionError)
    assert "note-1" in str(excinfo.value)


# --- the advisor's reader on top of it ---------------------------------------


def test_read_note_turns_a_permission_error_into_a_reportable_state():
    from ai_assistant.advisors.meeting_prep import (
        NOTE_READ_FORBIDDEN,
        Note,
        read_note,
    )

    class Denied:
        def read_file_text(self, file_id, mime_type=None, max_chars=0):
            raise DrivePermissionError("403 insufficientPermissions")

    result = read_note(Denied(), Note(id="note-1", name="Nisan notu"))
    assert result.problem == NOTE_READ_FORBIDDEN
    assert result.text == ""
    assert result.ok is False


def test_read_note_returns_the_text_when_the_scope_is_wide_enough():
    from ai_assistant.advisors.meeting_prep import Note, read_note

    class Allowed:
        def read_file_text(self, file_id, mime_type=None, max_chars=0):
            return "  Karar: ödeme planı.  "

    result = read_note(Allowed(), Note(id="note-1", name="Nisan notu"))
    assert result.text == "Karar: ödeme planı."
    assert result.ok is True
