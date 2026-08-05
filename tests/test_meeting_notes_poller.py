"""Tests for meeting-notes audio source discovery and download.

These test BEHAVIOUR, not a mock's echo: every assertion is about what the
code decides when handed a realistically shaped Gmail message - which part of
a nested MIME tree wins, which of four URL shapes yields the same Drive id,
what a share link is rewritten to, and what happens when there is nothing to
find or the message is malformed.

Discovery (:func:`extract_audio_source`) and download
(:func:`fetch_audio_bytes`) are exercised separately, because they fail for
different reasons and only the second one needs credentials.
"""

from __future__ import annotations

import base64
import logging
from unittest.mock import Mock

import pytest

from ai_assistant.integrations.meeting_notes_poller import (
    MAX_AUDIO_BYTES,
    AudioSource,
    MeetingNotesPoller,
    extract_audio_source,
    extract_drive_file_id,
    fetch_audio_bytes,
    find_gmail_attachment,
    normalise_dropbox_url,
)


def b64url(text: str) -> str:
    """Encode text the way Gmail encodes part bodies (base64url, unpadded)."""
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def text_part(body: str, mime_type: str = "text/plain") -> dict:
    return {"mimeType": mime_type, "body": {"data": b64url(body), "size": len(body)}}


def audio_part(
    filename: str = "meeting.mp3",
    mime_type: str = "audio/mpeg",
    attachment_id: str = "ATTACH_1",
    size: int = 2_048_000,
) -> dict:
    return {
        "mimeType": mime_type,
        "filename": filename,
        "body": {"attachmentId": attachment_id, "size": size},
    }


def message(payload: dict | None = None, **extra) -> dict:
    msg = {"id": "msg_1", "threadId": "thread_1"}
    if payload is not None:
        msg["payload"] = payload
    msg.update(extra)
    return msg


class TestGmailAttachmentDiscovery:
    """Attachments beat links, and nesting must not hide them."""

    def test_flat_attachment_is_found(self):
        msg = message(
            {
                "mimeType": "multipart/mixed",
                "parts": [text_part("Recording attached."), audio_part()],
            }
        )

        source = extract_audio_source(msg)

        assert source is not None
        assert source.kind == "gmail_attachment"
        assert source.identifier == "ATTACH_1"
        assert source.filename == "meeting.mp3"
        assert source.mime_type == "audio/mpeg"
        assert source.size_bytes == 2_048_000
        # fetching an attachment is impossible without the owning message
        assert source.message_id == "msg_1"

    def test_attachment_nested_two_levels_deep_is_found(self):
        """multipart/mixed > multipart/alternative > ... > the recording."""
        msg = message(
            {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            text_part("plain body"),
                            {
                                "mimeType": "multipart/related",
                                "parts": [
                                    text_part("<p>html body</p>", "text/html"),
                                    audio_part("deep.m4a", "audio/x-m4a", "DEEP_ID"),
                                ],
                            },
                        ],
                    }
                ],
            }
        )

        source = extract_audio_source(msg)

        assert source is not None
        assert source.identifier == "DEEP_ID"
        assert source.filename == "deep.m4a"

    @pytest.mark.parametrize(
        "mime_type",
        ["audio/mpeg", "audio/mp4", "audio/wav", "audio/ogg", "audio/webm", "audio/x-m4a"],
    )
    def test_every_expected_audio_mime_type_is_recognised(self, mime_type):
        msg = message(
            {"mimeType": "multipart/mixed", "parts": [audio_part(mime_type=mime_type)]}
        )

        source = extract_audio_source(msg)

        assert source is not None, f"{mime_type} should count as audio"
        assert source.kind == "gmail_attachment"

    def test_attachment_wins_over_a_drive_link_in_the_same_message(self):
        """Both present: the attachment is the cheaper, more reliable source."""
        msg = message(
            {
                "mimeType": "multipart/mixed",
                "parts": [
                    text_part("Backup copy: https://drive.google.com/file/d/DRIVE_ID/view"),
                    audio_part(attachment_id="WINNER"),
                ],
            }
        )

        source = extract_audio_source(msg)

        assert source.kind == "gmail_attachment"
        assert source.identifier == "WINNER"

    def test_non_audio_attachment_is_ignored(self):
        msg = message(
            {
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "application/pdf",
                        "filename": "agenda.pdf",
                        "body": {"attachmentId": "PDF_1", "size": 900},
                    }
                ],
            }
        )

        assert extract_audio_source(msg) is None

    def test_oversized_attachment_is_skipped_and_the_next_source_used(self):
        """A 200 MB recording must not be picked up; the link still can be."""
        msg = message(
            {
                "mimeType": "multipart/mixed",
                "parts": [
                    text_part("Mirror: https://drive.google.com/file/d/FALLBACK/view"),
                    audio_part(size=MAX_AUDIO_BYTES + 1),
                ],
            }
        )

        source = extract_audio_source(msg)

        assert source is not None
        assert source.kind == "drive", "oversized attachment should have been skipped"
        assert source.identifier == "FALLBACK"

    def test_attachment_just_under_the_limit_is_accepted(self):
        msg = message(
            {"mimeType": "multipart/mixed", "parts": [audio_part(size=MAX_AUDIO_BYTES - 1)]}
        )

        source = extract_audio_source(msg)

        assert source is not None
        assert source.kind == "gmail_attachment"

    def test_audio_part_without_attachment_id_is_not_returned(self):
        """Nothing to fetch by: an id-less part must not become a source."""
        part = audio_part()
        part["body"] = {"size": 1000}
        msg = message({"mimeType": "multipart/mixed", "parts": [part]})

        assert find_gmail_attachment(msg) is None


class TestDriveDiscovery:
    """One file id, several URL spellings."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://drive.google.com/file/d/1AbCdEf_GhIj-KlM/view?usp=sharing",
            "https://drive.google.com/open?id=1AbCdEf_GhIj-KlM",
            "https://drive.google.com/uc?export=download&id=1AbCdEf_GhIj-KlM",
        ],
    )
    def test_all_drive_url_shapes_yield_the_same_file_id(self, url):
        source = extract_audio_source(message(body=f"Kayıt burada: {url}"))

        assert source is not None
        assert source.kind == "drive"
        assert source.identifier == "1AbCdEf_GhIj-KlM"

    def test_drive_link_only_in_the_html_part_is_still_found(self):
        """Some senders put the link in text/html and leave text/plain bare."""
        msg = message(
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    text_part("See the attached recording."),
                    text_part(
                        '<a href="https://drive.google.com/file/d/HTML_ONLY/view'
                        '?usp=sharing&amp;ts=1">recording</a>',
                        "text/html",
                    ),
                ],
            }
        )

        source = extract_audio_source(msg)

        assert source is not None
        assert source.kind == "drive"
        assert source.identifier == "HTML_ONLY"

    def test_trailing_sentence_punctuation_is_not_part_of_the_id(self):
        source = extract_audio_source(
            message(body="Link: https://drive.google.com/file/d/PUNCT_ID/view.")
        )

        assert source.identifier == "PUNCT_ID"

    def test_drive_host_without_a_usable_id_is_not_a_source(self):
        assert extract_drive_file_id("https://drive.google.com/drive/my-drive") is None
        assert extract_audio_source(
            message(body="https://drive.google.com/drive/my-drive")
        ) is None


class TestDropboxDiscovery:
    """Share links have to become download links."""

    def test_dl_zero_becomes_dl_one(self):
        source = extract_audio_source(
            message(body="https://www.dropbox.com/s/abc123/standup.m4a?dl=0")
        )

        assert source is not None
        assert source.kind == "dropbox"
        assert source.identifier == "https://www.dropbox.com/s/abc123/standup.m4a?dl=1"
        assert source.filename == "standup.m4a"

    def test_link_without_dl_param_gains_one(self):
        source = extract_audio_source(
            message(body="https://dl.dropboxusercontent.com/s/xyz/call.mp3")
        )

        assert source.identifier.endswith("?dl=1")
        assert source.identifier.startswith(
            "https://dl.dropboxusercontent.com/s/xyz/call.mp3"
        )

    def test_other_query_params_survive_the_rewrite(self):
        rewritten = normalise_dropbox_url(
            "https://www.dropbox.com/s/abc/rec.wav?rlkey=k9&dl=0"
        )

        assert "rlkey=k9" in rewritten
        assert "dl=1" in rewritten
        assert "dl=0" not in rewritten

    def test_audio_link_preferred_over_an_unrelated_dropbox_link(self):
        body = (
            "Slides: https://www.dropbox.com/s/deck/slides.pdf?dl=0\n"
            "Audio: https://www.dropbox.com/s/rec/meeting.mp3?dl=0"
        )

        source = extract_audio_source(message(body=body))

        assert source.filename == "meeting.mp3"


class TestDirectUrlDiscovery:
    @pytest.mark.parametrize("extension", ["mp3", "m4a", "wav", "ogg"])
    def test_direct_audio_urls_are_recognised(self, extension):
        url = f"https://cdn.example.com/recordings/2026-08-05.{extension}"

        source = extract_audio_source(message(body=f"Download: {url}"))

        assert source is not None
        assert source.kind == "direct_url"
        assert source.identifier == url

    def test_query_string_is_kept_but_ignored_for_the_extension_check(self):
        url = "https://cdn.example.com/rec.mp3?token=abc123"

        source = extract_audio_source(message(body=url))

        assert source.identifier == url
        assert source.filename == "rec.mp3"

    def test_non_audio_url_is_not_a_source(self):
        assert extract_audio_source(
            message(body="Notes at https://example.com/notes.pdf")
        ) is None


class TestNoSourceAndMalformedInput:
    """Silence is the bug this replaced; absence must be logged loudly."""

    def test_returns_none_and_logs_what_was_searched(self, caplog):
        with caplog.at_level(logging.INFO):
            result = extract_audio_source(
                message({"mimeType": "text/plain", "body": {"data": b64url("hi")}})
            )

        assert result is None
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert "msg_1" in logged
        assert "No audio source" in logged
        # the log has to say WHERE it looked, or it is no better than silence
        assert "attachment" in logged.lower()
        assert "drive" in logged.lower()
        assert "dropbox" in logged.lower()

    def test_missing_payload_does_not_raise(self):
        assert extract_audio_source({"id": "no_payload"}) is None

    def test_payload_of_the_wrong_type_does_not_raise(self):
        assert extract_audio_source({"id": "x", "payload": "not-a-dict"}) is None
        assert extract_audio_source({"id": "y", "payload": None}) is None

    def test_parts_of_the_wrong_type_do_not_raise(self):
        msg = message({"mimeType": "multipart/mixed", "parts": "broken"})

        assert extract_audio_source(msg) is None

    def test_null_entries_inside_parts_do_not_raise(self):
        msg = message(
            {"mimeType": "multipart/mixed", "parts": [None, 42, audio_part()]}
        )

        source = extract_audio_source(msg)

        assert source is not None
        assert source.identifier == "ATTACH_1"

    def test_undecodable_body_data_does_not_raise(self):
        msg = message(
            {"mimeType": "multipart/mixed", "parts": [{"mimeType": "text/plain", "body": {"data": "!!!not-base64!!!"}}]}
        )

        assert extract_audio_source(msg) is None

    def test_non_dict_message_returns_none(self):
        assert extract_audio_source(None) is None
        assert extract_audio_source("just a string") is None


class TestPollerDelegates:
    def test_poller_method_finds_the_same_source(self):
        """The method must not reintroduce its own weaker parsing."""
        poller = object.__new__(MeetingNotesPoller)  # __init__ needs live creds
        poller.logger = logging.getLogger("test")
        msg = message({"mimeType": "multipart/mixed", "parts": [audio_part()]})

        source = poller._extract_audio_source(msg)

        assert source == extract_audio_source(msg)
        assert source.kind == "gmail_attachment"


class TestLocator:
    def test_locator_shapes_per_kind(self):
        attachment = AudioSource(
            kind="gmail_attachment", identifier="A1", message_id="M1"
        )
        assert attachment.locator == "gmail://M1/A1"

        drive = AudioSource(kind="drive", identifier="F1")
        assert drive.locator == "https://drive.google.com/file/d/F1/view"

        direct = AudioSource(kind="direct_url", identifier="https://x/y.mp3")
        assert direct.locator == "https://x/y.mp3"


class TestFetchAudioBytes:
    """Downloading is a separate job from finding, and tested as one."""

    def test_gmail_attachment_is_base64url_decoded(self):
        payload = b"\xff\xfb\x90\x00fake mp3 bytes ~ with padding needs"
        service = Mock()
        service.users.return_value.messages.return_value.attachments.return_value.get.return_value.execute.return_value = {
            "size": len(payload),
            "data": base64.urlsafe_b64encode(payload).decode().rstrip("="),
        }
        source = AudioSource(
            kind="gmail_attachment",
            identifier="ATT",
            filename="a.mp3",
            message_id="MSG",
        )

        data = fetch_audio_bytes(source, gmail_service=service)

        assert data == payload
        service.users.return_value.messages.return_value.attachments.return_value.get.assert_called_once_with(
            userId="me", messageId="MSG", id="ATT"
        )

    def test_gmail_attachment_without_message_id_raises(self):
        source = AudioSource(kind="gmail_attachment", identifier="ATT")

        with pytest.raises(ValueError, match="message_id"):
            fetch_audio_bytes(source, gmail_service=Mock())

    def test_drive_download_uses_the_existing_drive_manager(self, tmp_path):
        written = b"drive audio payload"

        def fake_download(file_id, output_path):
            assert file_id == "FILE_ID"
            with open(output_path, "wb") as handle:
                handle.write(written)
            return True

        manager = Mock()
        manager.download_file.side_effect = fake_download
        source = AudioSource(kind="drive", identifier="FILE_ID", filename="rec.mp3")

        assert fetch_audio_bytes(source, drive_manager=manager) == written

    def test_failed_drive_download_raises(self):
        manager = Mock()
        manager.download_file.return_value = False
        source = AudioSource(kind="drive", identifier="NOPE")

        with pytest.raises(ValueError, match="Drive download failed"):
            fetch_audio_bytes(source, drive_manager=manager)

    def test_oversized_source_is_refused_before_any_download(self):
        manager = Mock()
        source = AudioSource(
            kind="drive",
            identifier="BIG",
            filename="huge.wav",
            size_bytes=MAX_AUDIO_BYTES + 1,
        )

        with pytest.raises(ValueError, match="exceeds"):
            fetch_audio_bytes(source, drive_manager=manager)

        manager.download_file.assert_not_called()

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown audio source kind"):
            fetch_audio_bytes(AudioSource(kind="carrier_pigeon", identifier="x"))
