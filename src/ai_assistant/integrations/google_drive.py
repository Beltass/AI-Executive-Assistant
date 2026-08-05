"""Google Drive document management integration.

Provides a high-level `DriveClient` for managing advisor reports and documents
in Google Drive. Handles OAuth authentication, document lifecycle (create, read,
update, archive), folder organization, and integration with other services.

Configuration (all via environment variables):

* ``GOOGLE_DRIVE_FOLDER_ID`` — root reports folder ID
* ``GOOGLE_DRIVE_ARCHIVE_FOLDER_ID`` — archive folder ID
* Other Google OAuth vars shared with Gmail/Calendar (see ``google_auth``)

Folder structure:
  Reports/
    2026-07-31/
      mail_analyst.md
      planner.md
      ...
    2026-07-30/
  Archive/
    2026-06/
    2026-05/

Example:
    from ai_assistant.integrations.google_drive import DriveClient

    client = DriveClient()
    # Upload a report
    file_id = client.upload_report(
        "analysis_2026-07-31.md",
        "# Analysis\\n...",
        folder_id="...",
        mime_type="text/markdown",
    )
    link = client.get_file_link(file_id)

    # Archive old documents
    archived = client.archive_old_documents(folder_id="...", days_old=30)
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from googleapiclient.discovery import Resource

from . import CheckResult
from . import google_auth
from ._common import failed, ok, skipped_reason

logger = logging.getLogger(__name__)

# Integration spec for health checks
from ..config import get_integration

SPEC = get_integration("google_drive")

_SKIP_DETAIL = (
    "no Google credentials/token configured "
    "(run: python -m ai_assistant.integrations.google_auth)"
)

# Rate limit handling constants
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 2.0  # exponential backoff multiplier
DEFAULT_INITIAL_WAIT = 1.0  # seconds

# Google Drive MIME types
MIME_TYPE_FOLDER = "application/vnd.google-apps.folder"
MIME_TYPE_DOCUMENT = "application/vnd.google-apps.document"
MIME_TYPE_MARKDOWN = "text/markdown"
MIME_TYPE_TEXT = "text/plain"


class DriveError(RuntimeError):
    """Raised when a Drive operation fails."""


class RateLimitError(DriveError):
    """Raised when we hit the Drive API rate limit."""


class DrivePermissionError(DriveError):
    """Raised when the credential may LIST a file but not read its CONTENT.

    This is the normal state of this project, not an exotic failure: the
    shared OAuth consent (:data:`ai_assistant.integrations.google_auth.SCOPES`)
    used to request only ``drive.metadata.readonly``, which authorises
    ``files.list`` but neither ``files.export`` nor ``files.get_media``. A
    refresh token minted under the old consent keeps the old scopes even after
    the scope list here grows, so callers must be able to tell "this document
    is empty" from "I am not allowed to open it" and say so to the user.
    """


#: Substrings that mark an API error as "not authorised to read the content"
#: rather than a transient failure. Drive reports the missing scope as a 403
#: with ``insufficientPermissions`` / ``ACCESS_TOKEN_SCOPE_INSUFFICIENT``.
_PERMISSION_MARKERS = (
    "insufficientpermissions",
    "insufficient permission",
    "insufficient authentication scopes",
    "access_token_scope_insufficient",
    "forbidden",
    "api error 403",
    "api error 401",
)


def _is_permission_error(exc: Exception) -> bool:
    """True when ``exc`` says "not allowed", not "try again"."""
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status in (401, 403):
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _PERMISSION_MARKERS)


def _read_with_retry(call):
    """Execute a read, retrying transient failures but NEVER a "not allowed".

    A missing scope does not heal by waiting, so the retry ladder (and its
    sleeps) is skipped entirely for it and the caller gets an actionable
    :class:`DrivePermissionError` at once. Reads are idempotent GETs, so
    handing the same callable to :func:`_retry_with_backoff` afterwards is
    safe.
    """
    try:
        return call()
    except Exception as exc:
        if _is_permission_error(exc):
            raise DrivePermissionError(str(exc)) from exc
    return _retry_with_backoff(call)


def _retry_with_backoff(
    func,
    *args,
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_wait: float = DEFAULT_INITIAL_WAIT,
    backoff: float = DEFAULT_RETRY_BACKOFF,
    **kwargs,
):
    """Execute a function with exponential backoff retry logic.

    Retries on rate limit (429) and server errors (5xx). Raises on
    other HTTP errors or max retries exceeded.
    """
    from googleapiclient.errors import HttpError

    wait_time = initial_wait
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except HttpError as exc:
            last_error = exc
            status = exc.resp.status if hasattr(exc, "resp") else None

            # Rate limit (429) or server error (5xx) — retry
            if status in (429, 500, 502, 503, 504):
                if attempt < max_retries:
                    logger.warning(
                        f"API error {status}, retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries + 1})"
                    )
                    time.sleep(wait_time)
                    wait_time *= backoff
                else:
                    if status == 429:
                        raise RateLimitError(
                            f"Rate limited after {max_retries} retries"
                        ) from exc
                    raise DriveError(f"Server error {status} after retries") from exc
            else:
                # Don't retry on client errors (401, 403, 404, etc.)
                raise DriveError(f"API error {status}: {exc}") from exc
        except Exception as exc:
            # Network errors, timeout, etc. — retry
            if attempt < max_retries:
                logger.warning(
                    f"Request failed ({exc}), retrying in {wait_time}s "
                    f"(attempt {attempt + 1}/{max_retries + 1})"
                )
                time.sleep(wait_time)
                wait_time *= backoff
            else:
                raise DriveError(f"Request failed after retries: {exc}") from exc

    raise DriveError(f"Unexpected error: {last_error}") from last_error


class DriveClient:
    """High-level client for Google Drive document management.

    Handles authentication, CRUD operations, folder management, and
    document lifecycle (archiving). Includes retry logic and rate limit
    handling.

    Attributes:
        service: The underlying Google Drive API v3 service object.
    """

    def __init__(self):
        """Initialize the Drive client with authenticated credentials.

        Raises:
            DriveError: If credentials cannot be obtained.
        """
        try:
            creds = google_auth.get_credentials()
        except google_auth.GoogleAuthError as exc:
            raise DriveError(f"Authentication failed: {exc}") from exc

        try:
            from googleapiclient.discovery import build

            self.service: Resource = build(
                "drive", "v3", credentials=creds, cache_discovery=False
            )
        except Exception as exc:
            raise DriveError(f"Failed to build Drive service: {exc}") from exc

    def list_documents_in_folder(
        self,
        folder_id: str,
        query_prefix: str = "",
        max_results: int = 100,
    ) -> list[dict]:
        """List documents in a folder, optionally filtered by name prefix.

        Args:
            folder_id: The folder to list documents from.
            query_prefix: Optional name prefix filter (e.g., "mail_analyst").
            max_results: Maximum number of results to return (default 100).

        Returns:
            List of file metadata dicts with id, name, modifiedTime, mimeType.

        Raises:
            DriveError: On API errors or permission issues.
        """
        try:
            # Build query: files in folder, not folders themselves
            query_parts = [f"'{folder_id}' in parents", "trashed = false"]

            if query_prefix:
                # Escape single quotes in the prefix for the query
                escaped = query_prefix.replace("'", "\\'")
                query_parts.append(f"name starts with '{escaped}'")

            query = " and ".join(f"({part})" for part in query_parts)

            def _execute():
                return (
                    self.service.files()
                    .list(
                        q=query,
                        spaces="drive",
                        fields="files(id, name, modifiedTime, mimeType, webViewLink)",
                        pageSize=min(max_results, 1000),
                        orderBy="modifiedTime desc",
                    )
                    .execute()
                )

            result = _retry_with_backoff(_execute)
            return result.get("files", [])

        except RateLimitError:
            raise
        except Exception as exc:
            raise DriveError(
                f"Failed to list documents in folder {folder_id}: {exc}"
            ) from exc

    def read_file_text(
        self,
        file_id: str,
        mime_type: Optional[str] = None,
        max_chars: int = 0,
    ) -> str:
        """Read a document's CONTENT as plain text.

        Google-native documents (Docs, Sheets, Slides — anything whose MIME
        type starts with ``application/vnd.google-apps.``) cannot be
        downloaded; they are exported as ``text/plain``. Everything else is
        fetched with ``files.get_media`` and decoded as UTF-8, replacing
        undecodable bytes rather than raising (a note is worth reading even
        with a mangled character in it).

        Args:
            file_id: The file to read.
            mime_type: The file's MIME type, when the caller already listed it.
                Saves a metadata round-trip; looked up when omitted.
            max_chars: Truncate the result to this many characters
                (``0`` = no limit).

        Returns:
            The document text, stripped. An EMPTY STRING means the document
            really is empty — a failure is always raised, never swallowed.

        Raises:
            DrivePermissionError: The credential may list the file but not open
                it — almost always the ``drive.metadata.readonly`` scope (see
                the class docstring); the fix is re-consenting, not a retry.
            RateLimitError: Drive rate limit hit after the retries.
            DriveError: Any other API or transport failure.
        """
        if not file_id:
            raise DriveError("read_file_text called without a file id")

        try:
            files = self.service.files()

            mime = str(mime_type or "").strip()
            if not mime:
                meta = _read_with_retry(
                    lambda: files.get(fileId=file_id, fields="mimeType").execute()
                )
                mime = str((meta or {}).get("mimeType") or "")

            if mime.startswith("application/vnd.google-apps."):
                raw = _read_with_retry(
                    lambda: files.export(
                        fileId=file_id, mimeType=MIME_TYPE_TEXT
                    ).execute()
                )
            else:
                raw = _read_with_retry(
                    lambda: files.get_media(fileId=file_id).execute()
                )
        except DrivePermissionError as exc:
            raise DrivePermissionError(
                f"Not permitted to read the content of {file_id}: {exc}"
            ) from exc
        except RateLimitError:
            raise
        except Exception as exc:
            if _is_permission_error(exc):
                raise DrivePermissionError(
                    f"Not permitted to read the content of {file_id}: {exc}"
                ) from exc
            raise DriveError(f"Failed to read file {file_id}: {exc}") from exc

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        text = str(raw or "").strip()
        return text[:max_chars] if max_chars > 0 else text

    def upload_report(
        self,
        file_name: str,
        file_content: str,
        folder_id: str,
        mime_type: str = MIME_TYPE_MARKDOWN,
    ) -> str:
        """Upload or update a report document.

        Creates a new document if it doesn't exist, or updates an existing
        one with the same name.

        Args:
            file_name: Name of the file (e.g., "mail_analyst.md").
            file_content: Text content of the document.
            folder_id: Destination folder ID.
            mime_type: MIME type (default: text/markdown).

        Returns:
            The file ID of the created/updated document.

        Raises:
            DriveError: On API errors or permission issues.
        """
        try:
            # Check if file already exists
            existing = self.list_documents_in_folder(folder_id, file_name)
            existing_file = next((f for f in existing if f["name"] == file_name), None)

            if existing_file:
                # Update existing file
                return self._update_file_content(
                    existing_file["id"], file_content, mime_type
                )
            else:
                # Create new file
                return self._create_file(file_name, file_content, folder_id, mime_type)

        except RateLimitError:
            raise
        except DriveError:
            raise
        except Exception as exc:
            raise DriveError(f"Failed to upload report {file_name}: {exc}") from exc

    def _create_file(
        self,
        file_name: str,
        content: str,
        folder_id: str,
        mime_type: str,
    ) -> str:
        """Create a new file in Drive.

        Args:
            file_name: Name of the new file.
            content: File content.
            folder_id: Parent folder ID.
            mime_type: MIME type.

        Returns:
            The file ID.

        Raises:
            DriveError: On API errors.
        """
        from googleapiclient.http import MediaInMemoryUpload

        try:
            media = MediaInMemoryUpload(
                content.encode("utf-8"),
                mimetype=mime_type,
                resumable=False,
            )

            file_metadata = {
                "name": file_name,
                "mimeType": mime_type,
                "parents": [folder_id],
            }

            def _execute():
                return (
                    self.service.files()
                    .create(
                        body=file_metadata,
                        media_body=media,
                        fields="id, webViewLink",
                    )
                    .execute()
                )

            result = _retry_with_backoff(_execute)
            logger.info(f"Created file: {file_name} ({result['id']})")
            return result["id"]

        except RateLimitError:
            raise
        except Exception as exc:
            raise DriveError(f"Failed to create file {file_name}: {exc}") from exc

    def _update_file_content(
        self,
        file_id: str,
        content: str,
        mime_type: str,
    ) -> str:
        """Update the content of an existing file.

        Args:
            file_id: The file ID to update.
            content: New file content.
            mime_type: MIME type.

        Returns:
            The file ID.

        Raises:
            DriveError: On API errors.
        """
        from googleapiclient.http import MediaInMemoryUpload

        try:
            media = MediaInMemoryUpload(
                content.encode("utf-8"),
                mimetype=mime_type,
                resumable=False,
            )

            def _execute():
                return (
                    self.service.files()
                    .update(
                        fileId=file_id,
                        media_body=media,
                        fields="id, webViewLink",
                    )
                    .execute()
                )

            result = _retry_with_backoff(_execute)
            logger.info(f"Updated file: {file_id}")
            return result["id"]

        except RateLimitError:
            raise
        except Exception as exc:
            raise DriveError(f"Failed to update file {file_id}: {exc}") from exc

    def update_document(self, doc_id: str, content: str) -> str:
        """Update the content of an existing document.

        This is an alias for _update_file_content that infers the MIME type
        as plain text.

        Args:
            doc_id: The document ID to update.
            content: New document content.

        Returns:
            The document ID.

        Raises:
            DriveError: On API errors.
        """
        return self._update_file_content(doc_id, content, MIME_TYPE_TEXT)

    def get_file_link(self, file_id: str) -> str:
        """Get a shareable link for a file.

        Makes the file world-readable and returns its public web link.

        Args:
            file_id: The file ID.

        Returns:
            A shareable web link (https://drive.google.com/file/d/{id}/view).

        Raises:
            DriveError: On API errors.
        """
        try:
            # Make the file accessible to anyone with the link
            def _share():
                return (
                    self.service.permissions()
                    .create(
                        fileId=file_id,
                        body={"role": "reader", "type": "anyone"},
                        fields="id",
                    )
                    .execute()
                )

            def _get_link():
                return (
                    self.service.files()
                    .get(
                        fileId=file_id,
                        fields="webViewLink",
                    )
                    .execute()
                )

            try:
                _retry_with_backoff(_share)
            except DriveError as exc:
                # Ignore if already shared (409 Conflict)
                if "409" not in str(exc):
                    logger.warning(f"Could not share file {file_id}: {exc}")

            result = _retry_with_backoff(_get_link)
            return result.get("webViewLink", "")

        except RateLimitError:
            raise
        except Exception as exc:
            raise DriveError(f"Failed to get link for file {file_id}: {exc}") from exc

    def get_folder_id_by_name(
        self,
        parent_folder_id: str,
        folder_name: str,
    ) -> Optional[str]:
        """Find a folder by name within a parent folder.

        Args:
            parent_folder_id: The parent folder ID.
            folder_name: Name of the folder to find.

        Returns:
            The folder ID if found, None otherwise.

        Raises:
            DriveError: On API errors.
        """
        try:
            query = (
                f"'{parent_folder_id}' in parents and "
                f"name = '{folder_name}' and "
                f"mimeType = '{MIME_TYPE_FOLDER}' and "
                f"trashed = false"
            )

            def _execute():
                return (
                    self.service.files()
                    .list(
                        q=query,
                        spaces="drive",
                        fields="files(id, name)",
                        pageSize=1,
                    )
                    .execute()
                )

            result = _retry_with_backoff(_execute)
            files = result.get("files", [])

            if files:
                return files[0]["id"]
            return None

        except RateLimitError:
            raise
        except Exception as exc:
            raise DriveError(
                f"Failed to find folder '{folder_name}' in {parent_folder_id}: {exc}"
            ) from exc

    def _create_folder(self, parent_folder_id: str, folder_name: str) -> str:
        """Create a new folder.

        Args:
            parent_folder_id: Parent folder ID.
            folder_name: Name of the new folder.

        Returns:
            The new folder ID.

        Raises:
            DriveError: On API errors.
        """
        try:
            file_metadata = {
                "name": folder_name,
                "mimeType": MIME_TYPE_FOLDER,
                "parents": [parent_folder_id],
            }

            def _execute():
                return (
                    self.service.files()
                    .create(
                        body=file_metadata,
                        fields="id",
                    )
                    .execute()
                )

            result = _retry_with_backoff(_execute)
            folder_id = result["id"]
            logger.info(f"Created folder: {folder_name} ({folder_id})")
            return folder_id

        except RateLimitError:
            raise
        except Exception as exc:
            raise DriveError(f"Failed to create folder {folder_name}: {exc}") from exc

    def archive_old_documents(
        self,
        folder_id: str,
        days_old: int = 30,
        archive_folder_id: Optional[str] = None,
    ) -> list[str]:
        """Move documents older than N days to an archive folder.

        Creates archive subfolders by month (YYYY-MM) if they don't exist.

        Args:
            folder_id: Source folder ID (usually the reports root).
            days_old: Archive documents older than this many days (default 30).
            archive_folder_id: Archive destination. If None, uses
                GOOGLE_DRIVE_ARCHIVE_FOLDER_ID env var.

        Returns:
            List of archived file IDs.

        Raises:
            DriveError: On API errors or if archive folder not configured.
        """
        if archive_folder_id is None:
            archive_folder_id = os.getenv("GOOGLE_DRIVE_ARCHIVE_FOLDER_ID")
            if not archive_folder_id:
                raise DriveError(
                    "archive_folder_id not provided and "
                    "GOOGLE_DRIVE_ARCHIVE_FOLDER_ID not set"
                )

        try:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_old)

            # List all files in the source folder
            query = f"'{folder_id}' in parents and trashed = false"

            def _list():
                return (
                    self.service.files()
                    .list(
                        q=query,
                        spaces="drive",
                        fields="files(id, name, modifiedTime, mimeType)",
                        pageSize=1000,
                    )
                    .execute()
                )

            result = _retry_with_backoff(_list)
            files = result.get("files", [])

            archived_ids = []
            for file_info in files:
                # Skip folders
                if file_info["mimeType"] == MIME_TYPE_FOLDER:
                    continue

                modified_str = file_info.get("modifiedTime", "")
                if not modified_str:
                    continue

                # Parse ISO 8601 datetime
                try:
                    modified_dt = datetime.fromisoformat(
                        modified_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    logger.warning(f"Could not parse date: {modified_str}")
                    continue

                # Archive if older than cutoff
                if modified_dt < cutoff_date:
                    archive_subdir = modified_dt.strftime("%Y-%m")
                    target_folder = self.get_folder_id_by_name(
                        archive_folder_id, archive_subdir
                    )

                    if not target_folder:
                        target_folder = self._create_folder(
                            archive_folder_id, archive_subdir
                        )

                    self._move_file(file_info["id"], target_folder)
                    archived_ids.append(file_info["id"])
                    logger.info(f"Archived {file_info['name']} to {archive_subdir}")

            return archived_ids

        except RateLimitError:
            raise
        except DriveError:
            raise
        except Exception as exc:
            raise DriveError(f"Failed to archive documents: {exc}") from exc

    def _move_file(self, file_id: str, new_parent_id: str) -> None:
        """Move a file to a new parent folder.

        Args:
            file_id: The file ID to move.
            new_parent_id: The new parent folder ID.

        Raises:
            DriveError: On API errors.
        """
        try:

            def _get_parents():
                return (
                    self.service.files()
                    .get(
                        fileId=file_id,
                        fields="parents",
                    )
                    .execute()
                )

            parents_result = _retry_with_backoff(_get_parents)
            old_parents = ",".join(parents_result.get("parents", []))

            def _move():
                return (
                    self.service.files()
                    .update(
                        fileId=file_id,
                        addParents=new_parent_id,
                        removeParents=old_parents,
                        fields="id, parents",
                    )
                    .execute()
                )

            _retry_with_backoff(_move)

        except RateLimitError:
            raise
        except Exception as exc:
            raise DriveError(f"Failed to move file {file_id}: {exc}") from exc


# Connection check for the health check system
def check_connection() -> CheckResult:
    """Query the Drive ``about`` endpoint to confirm authentication."""
    if not google_auth.google_configured():
        return skipped_reason(SPEC.name, _SKIP_DETAIL)

    try:
        creds = google_auth.get_credentials()
    except google_auth.GoogleAuthError as exc:
        return failed(SPEC.name, str(exc))

    try:
        from googleapiclient.discovery import build

        service = build("drive", "v3", credentials=creds, cache_discovery=False)
        about = service.about().get(fields="user").execute()
    except Exception as exc:
        return failed(SPEC.name, f"request error: {exc}")

    user = about.get("user", {}).get("emailAddress", "unknown")
    return ok(SPEC.name, f"user: {user}")
