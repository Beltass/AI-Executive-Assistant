"""Upload the agent usage guide (``docs/AJAN_KULLANIM_KILAVUZU.md``) to Drive.

WHY THIS EXISTS. The guide is the document a human actually reads before
operating the assistant, and it lived only in the repository. This puts it in
the same Drive folder (``GOOGLE_DRIVE_FOLDER_ID``) the advisor reports are
archived to, using the SAME client — :class:`ai_assistant.integrations.
google_drive.DriveClient` — so there is no second Drive code path to keep in
sync.

WHAT IT IS HONEST ABOUT. There is no fake success here:

* no Google credentials  -> prints "Drive kimlik bilgisi yok, atlandı", exit 0
* no ``GOOGLE_DRIVE_FOLDER_ID`` -> prints why it was skipped, exit 0
* upload attempted and failed -> prints the error, exit 1

Only a real file id coming back from Drive is reported as success.

Run with::

    python scripts/upload_docs_to_drive.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The documents to publish: repository path -> name in Drive.
DOCUMENTS: list[tuple[str, str]] = [
    ("docs/AJAN_KULLANIM_KILAVUZU.md", "AJAN_KULLANIM_KILAVUZU.md"),
]


def upload_documents() -> int:
    """Upload :data:`DOCUMENTS` to Drive and return a process exit code."""
    from ai_assistant.integrations import google_auth

    if not google_auth.google_configured():
        print("Drive kimlik bilgisi yok, atlandı.")
        return 0

    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        print("GOOGLE_DRIVE_FOLDER_ID tanımlı değil, atlandı.")
        return 0

    from ai_assistant.integrations.google_drive import (
        MIME_TYPE_MARKDOWN,
        DriveClient,
    )

    try:
        client = DriveClient()
    except Exception as exc:
        print(f"HATA: Drive istemcisi kurulamadı: {exc}")
        return 1

    failed = False
    for rel_path, drive_name in DOCUMENTS:
        source = REPO_ROOT / rel_path
        if not source.is_file():
            print(f"HATA: dosya yok: {rel_path}")
            failed = True
            continue

        content = source.read_text(encoding="utf-8")
        try:
            file_id = client.upload_report(
                file_name=drive_name,
                file_content=content,
                folder_id=folder_id,
                mime_type=MIME_TYPE_MARKDOWN,
            )
        except Exception as exc:
            print(f"HATA: {rel_path} yüklenemedi: {exc}")
            failed = True
            continue

        if not file_id:
            print(f"HATA: {rel_path} için Drive dosya kimliği dönmedi.")
            failed = True
            continue

        print(f"Yüklendi: {rel_path} -> {drive_name} (id: {file_id})")

    return 1 if failed else 0


def main() -> int:
    return upload_documents()


if __name__ == "__main__":
    sys.exit(main())
