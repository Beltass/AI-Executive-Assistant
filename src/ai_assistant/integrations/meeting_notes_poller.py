"""Meeting Notes Poller - Main entrypoint for the meeting-notes-poller workflow.

Runs every 30 minutes to:
1. Poll Gmail for new meeting notifications
2. Locate the recording (Gmail attachment, Drive, Dropbox, direct URL)
3. Transcribe audio
4. Analyze with LLM
5. Generate reports (PDF, Doc, Excel)
6. Create tasks in tracker
7. Send Slack deadline reminders
8. Sync to Drive

Usage:
    python -m ai_assistant.integrations.meeting_notes_poller
    python -m ai_assistant.integrations.meeting_notes_poller \
        --email-query="subject:Meeting" \
        --auto-transcribe=true \
        --generate-reports=true
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import binascii
import html
import json
import logging
import mimetypes
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import parse_qsl, unquote, urlparse, urlunparse, urlencode

from ..advisors.meeting_notes import MeetingNotesAgent, MeetingNotes
from ..integrations import gmail, google_auth
from ..integrations.google_drive_manager import GoogleDriveManager
from ..integrations.task_tracker import TaskTracker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audio source discovery
# ---------------------------------------------------------------------------

#: Anything past this is refused rather than pulled into memory. Deliberately
#: the same 100 MB as Gemini's inline-data ceiling
#: (:data:`ai_assistant.integrations.llm.MAX_INLINE_AUDIO_BYTES`): downloading
#: a recording we could never send on would only waste the run's time.
MAX_AUDIO_BYTES = 100 * 1024 * 1024  # 100 MB

#: How many Gmail hits one run looks at. The workflow runs every 30 minutes,
#: so a backlog drains over several runs rather than one very long one.
MAX_MESSAGES_PER_RUN = 10

#: MIME types Gmail uses for the audio recordings meeting tools send out.
AUDIO_MIME_TYPES = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/vnd.wave",
        "audio/ogg",
        "audio/webm",
        "audio/x-m4a",
        "audio/m4a",
        "audio/aac",
        "audio/flac",
    }
)

#: Extensions accepted for attachment filenames (Gmail sometimes reports
#: ``application/octet-stream`` for a perfectly ordinary .m4a).
AUDIO_FILE_EXTENSIONS = (".mp3", ".m4a", ".wav", ".ogg", ".webm", ".aac", ".flac")

#: Extensions accepted for a bare "direct link to an audio file" in the body.
DIRECT_URL_EXTENSIONS = (".mp3", ".m4a", ".wav", ".ogg")

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]}]+")
_URL_TRAILING_PUNCT = ".,;:!?)]}>\"'"

_DRIVE_HOSTS = ("drive.google.com", "docs.google.com")
_DROPBOX_HOSTS = ("dropbox.com", "www.dropbox.com", "dl.dropboxusercontent.com")

_DRIVE_ID_PATTERNS = (
    re.compile(r"/file/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"),
)


@dataclass
class AudioSource:
    """Where a meeting recording lives, before anything has been downloaded.

    Discovery and download are deliberately separate: ``kind``/``identifier``
    is everything :func:`fetch_audio_bytes` needs, and it can be asserted on in
    a test without a single network call.

    Attributes:
        kind: ``gmail_attachment`` | ``drive`` | ``dropbox`` | ``direct_url``
        identifier: attachment id, Drive file id, or a downloadable URL
        filename: best-known file name (may be derived from the URL)
        mime_type: reported or guessed MIME type ("" when unknown)
        size_bytes: reported size, when the source tells us up front
        message_id: Gmail message the source was found in (attachments need it)
    """

    kind: str
    identifier: str
    filename: str = ""
    mime_type: str = ""
    size_bytes: Optional[int] = None
    message_id: Optional[str] = None

    @property
    def locator(self) -> str:
        """A single string naming the source, for logging and transcription."""
        if self.kind == "gmail_attachment":
            return f"gmail://{self.message_id or 'unknown'}/{self.identifier}"
        if self.kind == "drive":
            return f"https://drive.google.com/file/d/{self.identifier}/view"
        return self.identifier


def _decode_base64url(data: str) -> bytes:
    """Decode Gmail's base64url payloads, padding included or not."""
    if not data:
        return b""
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except (binascii.Error, ValueError) as exc:
        logger.warning(f"Could not base64url-decode Gmail payload: {exc}")
        return b""


def _iter_parts(part: Any) -> Iterator[Dict[str, Any]]:
    """Yield ``part`` and every nested sub-part, depth first.

    A meeting notification is routinely ``multipart/mixed`` wrapping a
    ``multipart/alternative`` wrapping the text bodies, with the recording
    hanging off the outer level - a single-level scan misses plenty of them.
    """
    if not isinstance(part, dict):
        return
    yield part
    parts = part.get("parts")
    if isinstance(parts, list):
        for child in parts:
            yield from _iter_parts(child)


def _looks_like_audio(part: Dict[str, Any]) -> bool:
    """True when a MIME part is an audio recording."""
    mime_type = str(part.get("mimeType") or "").lower().split(";")[0].strip()
    if mime_type in AUDIO_MIME_TYPES or mime_type.startswith("audio/"):
        return True
    filename = str(part.get("filename") or "").lower()
    return filename.endswith(AUDIO_FILE_EXTENSIONS)


def _part_size(part: Dict[str, Any]) -> Optional[int]:
    body = part.get("body")
    if not isinstance(body, dict):
        return None
    size = body.get("size")
    try:
        return int(size) if size is not None else None
    except (TypeError, ValueError):
        return None


def find_gmail_attachment(message: Dict[str, Any]) -> Optional[AudioSource]:
    """Find the first audio attachment in a ``users.messages.get`` payload.

    Args:
        message: Gmail message dict (``format="full"``).

    Returns:
        AudioSource of kind ``gmail_attachment``, or None.
    """
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return None

    message_id = message.get("id")

    for part in _iter_parts(payload):
        if not _looks_like_audio(part):
            continue

        body = part.get("body") if isinstance(part.get("body"), dict) else {}
        attachment_id = body.get("attachmentId")
        filename = str(part.get("filename") or "")

        if not attachment_id:
            logger.debug(
                f"Audio part '{filename}' has no attachmentId; skipping it"
            )
            continue

        size = _part_size(part)
        if size is not None and size > MAX_AUDIO_BYTES:
            logger.warning(
                f"Skipping attachment '{filename}': {size} bytes exceeds the "
                f"{MAX_AUDIO_BYTES} byte limit"
            )
            continue

        mime_type = str(part.get("mimeType") or "")
        if not mime_type or mime_type == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(filename)
            mime_type = guessed or mime_type

        return AudioSource(
            kind="gmail_attachment",
            identifier=str(attachment_id),
            filename=filename,
            mime_type=mime_type,
            size_bytes=size,
            message_id=str(message_id) if message_id else None,
        )

    return None


def _collect_body_text(message: Dict[str, Any]) -> str:
    """Gather every scrap of text a message carries, decoded and unescaped."""
    chunks: List[str] = []

    for key in ("body", "snippet", "text", "html"):
        value = message.get(key)
        if isinstance(value, str):
            chunks.append(value)

    payload = message.get("payload")
    if isinstance(payload, dict):
        for part in _iter_parts(payload):
            mime_type = str(part.get("mimeType") or "").lower()
            if not mime_type.startswith("text/"):
                continue
            body = part.get("body")
            if not isinstance(body, dict):
                continue
            data = body.get("data")
            if isinstance(data, str) and data:
                chunks.append(_decode_base64url(data).decode("utf-8", "replace"))

    return html.unescape("\n".join(chunks))


def _iter_urls(text: str) -> Iterator[str]:
    """Yield URLs from free text, with trailing sentence punctuation removed."""
    for match in _URL_RE.finditer(text or ""):
        yield match.group(0).rstrip(_URL_TRAILING_PUNCT)


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _filename_from_url(url: str) -> str:
    try:
        path = urlparse(url).path
    except ValueError:
        return ""
    return unquote(path.rsplit("/", 1)[-1]) if path else ""


def extract_drive_file_id(url: str) -> Optional[str]:
    """Pull the file id out of any of Drive's URL shapes.

    Handles ``/file/d/<id>/view``, ``/open?id=<id>`` and ``?id=<id>``.
    """
    if not url:
        return None
    for pattern in _DRIVE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def find_drive_source(text: str) -> Optional[AudioSource]:
    """Find a Google Drive link in message text."""
    for url in _iter_urls(text):
        if _host_of(url) not in _DRIVE_HOSTS:
            continue
        file_id = extract_drive_file_id(url)
        if not file_id:
            logger.debug(f"Drive link without an extractable file id: {url}")
            continue
        filename = _filename_from_url(url)
        mime_type, _ = mimetypes.guess_type(filename)
        return AudioSource(
            kind="drive",
            identifier=file_id,
            filename=filename if filename.lower().endswith(AUDIO_FILE_EXTENSIONS) else "",
            mime_type=mime_type or "",
        )
    return None


def normalise_dropbox_url(url: str) -> str:
    """Turn a Dropbox share link into a direct download link (``dl=1``)."""
    parsed = urlparse(url)
    params = parse_qsl(parsed.query, keep_blank_values=True)
    params = [(key, value) for key, value in params if key != "dl"]
    params.append(("dl", "1"))
    return urlunparse(parsed._replace(query=urlencode(params)))


def find_dropbox_source(text: str) -> Optional[AudioSource]:
    """Find a Dropbox link, preferring one that names an audio file."""
    candidates = [url for url in _iter_urls(text) if _host_of(url) in _DROPBOX_HOSTS]
    if not candidates:
        return None

    chosen = next(
        (u for u in candidates if _filename_from_url(u).lower().endswith(AUDIO_FILE_EXTENSIONS)),
        candidates[0],
    )
    filename = _filename_from_url(chosen)
    mime_type, _ = mimetypes.guess_type(filename)
    return AudioSource(
        kind="dropbox",
        identifier=normalise_dropbox_url(chosen),
        filename=filename,
        mime_type=mime_type or "",
    )


def find_direct_url_source(text: str) -> Optional[AudioSource]:
    """Find a plain http(s) link whose path ends in an audio extension."""
    for url in _iter_urls(text):
        filename = _filename_from_url(url)
        if not filename.lower().endswith(DIRECT_URL_EXTENSIONS):
            continue
        mime_type, _ = mimetypes.guess_type(filename)
        return AudioSource(
            kind="direct_url",
            identifier=url,
            filename=filename,
            mime_type=mime_type or "",
        )
    return None


def extract_audio_source(message: Dict[str, Any]) -> Optional[AudioSource]:
    """Locate the recording a meeting email points at.

    Tried in order: Gmail attachment, Google Drive link, Dropbox link, direct
    audio URL. Nothing is downloaded here - see :func:`fetch_audio_bytes`.

    Args:
        message: Gmail message dict, either the raw ``users.messages.get``
            payload or a flattened dict carrying a ``body`` string.

    Returns:
        The first AudioSource found, or None when the message has none.
    """
    if not isinstance(message, dict):
        logger.info("No audio source: message is not a dict")
        return None

    message_id = message.get("id", "unknown")

    try:
        source = find_gmail_attachment(message)
        if source:
            logger.info(
                f"Audio source for {message_id}: Gmail attachment "
                f"'{source.filename}' ({source.mime_type or 'unknown type'})"
            )
            return source
    except Exception as exc:  # one malformed message must not stop the run
        logger.warning(f"Attachment scan failed for message {message_id}: {exc}")

    try:
        text = _collect_body_text(message)
    except Exception as exc:
        logger.warning(f"Body extraction failed for message {message_id}: {exc}")
        text = ""

    for finder in (find_drive_source, find_dropbox_source, find_direct_url_source):
        try:
            source = finder(text)
        except Exception as exc:
            logger.warning(
                f"{finder.__name__} failed for message {message_id}: {exc}"
            )
            continue
        if source:
            logger.info(
                f"Audio source for {message_id}: {source.kind} -> {source.locator}"
            )
            return source

    logger.info(
        f"No audio source in message {message_id}: searched attachments "
        f"(audio/* MIME parts, nested included), Google Drive links, Dropbox "
        f"links and direct {'/'.join(DIRECT_URL_EXTENSIONS)} URLs in the body"
    )
    return None


# ---------------------------------------------------------------------------
# Audio download
# ---------------------------------------------------------------------------


def _build_gmail_service():  # pragma: no cover - requires real credentials
    """Build a Gmail service from the shared Google OAuth credentials."""
    return gmail.build_service()


def _fetch_gmail_attachment(source: AudioSource, gmail_service: Any) -> bytes:
    if not source.message_id:
        raise ValueError("Gmail attachment source has no message_id")

    service = gmail_service or _build_gmail_service()
    response = (
        service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=source.message_id, id=source.identifier)
        .execute()
    )
    data = (response or {}).get("data")
    if not data:
        raise ValueError(
            f"Gmail returned no data for attachment {source.identifier}"
        )
    return _decode_base64url(data)


def _fetch_drive_file(source: AudioSource, drive_manager: Any) -> bytes:
    manager = drive_manager or GoogleDriveManager()
    suffix = Path(source.filename).suffix or ".audio"
    handle, temp_path = tempfile.mkstemp(suffix=suffix, prefix="meeting_audio_")
    os.close(handle)
    try:
        if not manager.download_file(source.identifier, temp_path):
            raise ValueError(f"Drive download failed for file {source.identifier}")
        return Path(temp_path).read_bytes()
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _fetch_http(url: str) -> bytes:
    import requests

    with requests.get(url, stream=True, timeout=60, allow_redirects=True) as response:
        response.raise_for_status()

        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > MAX_AUDIO_BYTES:
            raise ValueError(
                f"Refusing to download {url}: {declared} bytes exceeds the "
                f"{MAX_AUDIO_BYTES} byte limit"
            )

        chunks: List[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_AUDIO_BYTES:
                raise ValueError(
                    f"Refusing to download {url}: stream exceeded the "
                    f"{MAX_AUDIO_BYTES} byte limit"
                )
            chunks.append(chunk)

    return b"".join(chunks)


def fetch_audio_bytes(
    source: AudioSource,
    *,
    gmail_service: Any = None,
    drive_manager: Any = None,
) -> bytes:
    """Download the audio an :class:`AudioSource` points at.

    Args:
        source: What :func:`extract_audio_source` returned.
        gmail_service: Gmail API service; built from the shared credentials
            when omitted. Injectable so tests never touch the network.
        drive_manager: GoogleDriveManager; built when omitted.

    Returns:
        Raw audio bytes.

    Raises:
        ValueError: unknown source kind, empty response, or size over
            :data:`MAX_AUDIO_BYTES`.
    """
    if source is None:
        raise ValueError("No audio source given")

    if source.size_bytes is not None and source.size_bytes > MAX_AUDIO_BYTES:
        raise ValueError(
            f"Refusing to download '{source.filename or source.identifier}': "
            f"{source.size_bytes} bytes exceeds the {MAX_AUDIO_BYTES} byte limit"
        )

    if source.kind == "gmail_attachment":
        data = _fetch_gmail_attachment(source, gmail_service)
    elif source.kind == "drive":
        data = _fetch_drive_file(source, drive_manager)
    elif source.kind in ("dropbox", "direct_url"):
        data = _fetch_http(source.identifier)
    else:
        raise ValueError(f"Unknown audio source kind: {source.kind!r}")

    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError(
            f"Downloaded audio is {len(data)} bytes, over the "
            f"{MAX_AUDIO_BYTES} byte limit"
        )

    logger.info(f"Fetched {len(data)} bytes from {source.kind} {source.locator}")
    return data


class MeetingNotesPoller:
    """Main poller for meeting notes from Gmail."""

    def __init__(self):
        """Initialize the poller."""
        self.logger = logging.getLogger(__name__)
        self.agent = MeetingNotesAgent()
        self.drive_manager = GoogleDriveManager()
        self.task_tracker = TaskTracker()
        self.state_dir = Path(".assistant_state")
        self.state_dir.mkdir(exist_ok=True)
        self.processed_file = self.state_dir / "processed_meetings.json"
        # Built once per run and shared by the search and the attachment
        # downloads, so one run costs one OAuth refresh.
        self.gmail_service: Any = None

    async def run(
        self,
        email_query: str = 'from:notifications has:attachment filename:(mp3 OR wav OR m4a)',
        auto_transcribe: bool = True,
        generate_reports: bool = True,
    ) -> bool:
        """Run the poller.

        Args:
            email_query: Gmail query for finding meeting emails
            auto_transcribe: Whether to auto-transcribe audio
            generate_reports: Whether to generate reports

        Returns:
            True if successful
        """
        try:
            self.logger.info("Starting Meeting Notes Poller")

            if not google_auth.google_configured():
                self.logger.error(
                    "No Google credentials configured; run "
                    "`python -m ai_assistant.integrations.google_auth` (or set "
                    "GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_REFRESH_TOKEN)"
                )
                return False

            # Search for meeting emails. Full messages come back, so the audio
            # source can be found without a second round trip.
            self.logger.info(f"Searching Gmail: {email_query}")
            try:
                messages = gmail.search_messages(
                    email_query,
                    max_results=MAX_MESSAGES_PER_RUN,
                    service=self._get_gmail_service(),
                )
            except Exception as exc:
                self.logger.error(f"Gmail search failed: {exc}")
                return False

            if not messages:
                self.logger.info("No new meeting emails found")
                return True

            self.logger.info(f"Found {len(messages)} potential meeting emails")

            # Process each message
            processed_count = 0
            for message in messages:
                meeting_id = message.get('id')

                # Skip if already processed
                if self._is_processed(meeting_id):
                    self.logger.debug(f"Meeting {meeting_id} already processed")
                    continue

                try:
                    success = await self._process_meeting(
                        message,
                        auto_transcribe=auto_transcribe,
                        generate_reports=generate_reports,
                    )

                    if success:
                        self._mark_processed(meeting_id)
                        processed_count += 1

                except Exception as e:
                    self.logger.error(f"Failed to process meeting {meeting_id}: {e}")
                    continue

            self.logger.info(f"Processed {processed_count} new meetings")

            # Send reminders
            await self.agent.send_deadline_reminders()

            # Sync to Drive
            folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
            if folder_id:
                self.task_tracker.sync_to_drive(folder_id)

            return True

        except Exception as e:
            self.logger.error(f"Poller failed: {e}")
            return False

    async def _process_meeting(
        self,
        message: dict,
        auto_transcribe: bool = True,
        generate_reports: bool = True,
    ) -> bool:
        """Process a single meeting email.

        Args:
            message: Gmail message dict
            auto_transcribe: Whether to transcribe audio
            generate_reports: Whether to generate reports

        Returns:
            True if successful
        """
        try:
            message_id = message.get('id')
            subject = message.get('subject', 'Unknown Meeting')

            self.logger.info(f"Processing meeting: {subject}")

            # Locate the recording: attachment, Drive, Dropbox or direct link
            audio_source = self._extract_audio_source(message)

            if audio_source is None:
                self.logger.warning(f"No audio source found in message {message_id}")
                return False

            audio_url = audio_source.locator

            # Transcribe audio if enabled
            transcript = ""
            if auto_transcribe:
                self.logger.info(f"Transcribing audio from {audio_url}")
                transcript = await self.agent.transcribe_audio(audio_url)

                if not transcript:
                    self.logger.error("Transcription failed")
                    return False

            # Analyze meeting
            self.logger.info("Analyzing meeting...")
            attendees = message.get('attendees', [])
            meeting_notes = await self.agent.analyze_meeting(
                transcript,
                meeting_title=subject,
                attendees=attendees,
            )
            meeting_notes.audio_file_url = audio_url

            # Generate reports if enabled
            if generate_reports:
                self.logger.info("Generating reports...")
                reports = await self.agent.generate_report(meeting_notes)
                self.logger.info(f"Generated reports: {reports}")

            # Create tasks
            self.logger.info(f"Creating {len(meeting_notes.action_items)} action items...")
            task_ids = await self.agent.create_tasks_in_tracker(
                meeting_notes.action_items,
                meeting_notes.meeting_id,
            )
            self.logger.info(f"Created {len(task_ids)} tasks")

            # Save meeting notes to state
            self._save_meeting_notes(meeting_notes)

            return True

        except Exception as e:
            self.logger.error(f"Failed to process meeting: {e}")
            return False

    def _get_gmail_service(self) -> Any:
        """Return this run's Gmail service, building it on first use.

        ``getattr`` rather than plain attribute access because tests build a
        poller with ``object.__new__`` (``__init__`` wants live credentials).
        """
        service = getattr(self, "gmail_service", None)
        if service is None:
            service = gmail.build_service()
            self.gmail_service = service
        return service

    def _extract_audio_source(self, message: dict) -> Optional[AudioSource]:
        """Locate the recording a meeting email points at.

        Thin delegate to :func:`extract_audio_source` so discovery stays
        testable without constructing a poller (which needs live credentials).

        Args:
            message: Gmail message dict

        Returns:
            AudioSource or None
        """
        return extract_audio_source(message)

    def _save_meeting_notes(self, notes: MeetingNotes) -> None:
        """Save meeting notes to persistent storage."""
        try:
            meetings_file = self.state_dir / "meetings.json"
            data = {}

            if meetings_file.exists():
                with open(meetings_file, 'r') as f:
                    data = json.load(f)

            data[notes.meeting_id] = notes.to_dict()

            with open(meetings_file, 'w') as f:
                json.dump(data, f, indent=2)

            self.logger.info(f"Saved meeting notes: {notes.meeting_id}")

        except Exception as e:
            self.logger.error(f"Failed to save meeting notes: {e}")

    def _is_processed(self, message_id: str) -> bool:
        """Check if message already processed."""
        try:
            if not self.processed_file.exists():
                return False

            with open(self.processed_file, 'r') as f:
                data = json.load(f)

            return message_id in data.get('processed', [])

        except Exception:
            return False

    def _mark_processed(self, message_id: str) -> None:
        """Mark message as processed."""
        try:
            data = {}

            if self.processed_file.exists():
                with open(self.processed_file, 'r') as f:
                    data = json.load(f)

            if 'processed' not in data:
                data['processed'] = []

            data['processed'].append(message_id)
            data['last_run'] = datetime.now(timezone.utc).isoformat()

            with open(self.processed_file, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            self.logger.error(f"Failed to mark message as processed: {e}")


async def main():
    """Main entrypoint."""
    parser = argparse.ArgumentParser(
        description="Meeting Notes Poller - Process meeting emails and track action items"
    )
    parser.add_argument(
        "--email-query",
        default='from:notifications has:attachment filename:(mp3 OR wav OR m4a)',
        help="Gmail query for finding meeting emails",
    )
    parser.add_argument(
        "--auto-transcribe",
        type=lambda x: x.lower() == 'true',
        default=True,
        help="Auto-transcribe audio files",
    )
    parser.add_argument(
        "--generate-reports",
        type=lambda x: x.lower() == 'true',
        default=True,
        help="Generate meeting reports",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run poller
    poller = MeetingNotesPoller()
    success = await poller.run(
        email_query=args.email_query,
        auto_transcribe=args.auto_transcribe,
        generate_reports=args.generate_reports,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
