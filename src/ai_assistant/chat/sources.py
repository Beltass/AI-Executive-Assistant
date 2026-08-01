"""Birinci adımın malzemesi: kullanıcının seçebileceği veri kaynakları.

Drive'daki tablo dosyaları (Google E-Tablo, ``.xlsx``, ``.csv``) EN YENİDEN
eskiye listelenir. Drive yapılandırılmamışsa ya da klasör boşsa liste boş döner
— hata değil: kullanıcı yine de veri yapıştırabilir, o yüzden akış durmaz.

Klasör ``CHAT_DATA_FOLDER_ID`` ile, o yoksa ``GOOGLE_DRIVE_FOLDER_ID`` ile
belirlenir. Listeleme :class:`ai_assistant.integrations.google_drive.DriveClient`
üzerinden yapılır; MIME süzgeci burada, istemcinin genel API'sini genişletmeden
uygulanır.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, List, Optional

logger = logging.getLogger(__name__)

FOLDER_ENV = "CHAT_DATA_FOLDER_ID"
FALLBACK_FOLDER_ENV = "GOOGLE_DRIVE_FOLDER_ID"

#: Menüde en çok bu kadar dosya gösterilir — daha uzun liste menü olmaktan çıkar.
MAX_SOURCES = 8

MIME_GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_CSV = "text/csv"

#: Tablo sayılan MIME tipleri. Rapor belgeleri (``text/markdown``) elenir.
TABLE_MIMES = {MIME_GOOGLE_SHEET, MIME_XLSX, MIME_CSV, "application/vnd.ms-excel"}

KIND_LABEL = {
    MIME_GOOGLE_SHEET: "Google E-Tablo",
    MIME_XLSX: "Excel",
    MIME_CSV: "CSV",
    "application/vnd.ms-excel": "Excel",
}


def folder_id() -> str:
    for env in (FOLDER_ENV, FALLBACK_FOLDER_ENV):
        value = (os.getenv(env) or "").strip()
        if value:
            return value
    return ""


@dataclass
class DriveSource:
    """Menüde bir satır: Drive'daki tek bir tablo dosyası."""

    id: str
    name: str
    mime_type: str = ""
    modified: str = ""

    @property
    def kind_label(self) -> str:
        return KIND_LABEL.get(self.mime_type, "Tablo")

    @property
    def modified_label(self) -> str:
        """``2026-07-30T08:15:00.000Z`` -> ``30.07.2026``."""
        raw = str(self.modified or "").strip()
        if not raw:
            return ""
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return ""
        return moment.strftime("%d.%m.%Y")

    def hint(self) -> str:
        parts = [self.kind_label]
        when = self.modified_label
        if when:
            parts.append(f"son değişiklik {when}")
        return " · ".join(parts)


def list_recent_sources(
    limit: int = MAX_SOURCES,
    client_factory: Optional[Callable[[], Any]] = None,
) -> List[DriveSource]:
    """Drive klasöründeki tablo dosyalarını en yeniden eskiye listeler.

    Asla istisna atmaz: kimlik yoksa, klasör tanımsızsa ya da Drive hata
    verirse BOŞ liste döner ve neden loglanır. Menü bu durumda yalnızca
    "veri yapıştır" seçeneğiyle çalışmaya devam eder.
    """
    root = folder_id()
    if not root:
        logger.info("Drive kaynak listesi atlandı: %s tanımlı değil", FOLDER_ENV)
        return []

    try:
        factory = client_factory or _default_client
        client = factory()
        files = client.list_documents_in_folder(root, max_results=max(limit * 4, 20))
    except Exception as exc:
        logger.warning("Drive kaynakları listelenemedi: %s", exc)
        return []

    sources: List[DriveSource] = []
    for item in files or []:
        if not isinstance(item, dict):
            continue
        mime = str(item.get("mimeType") or "")
        if mime not in TABLE_MIMES:
            continue
        sources.append(
            DriveSource(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or "adsız dosya"),
                mime_type=mime,
                modified=str(item.get("modifiedTime") or ""),
            )
        )
        if len(sources) >= limit:
            break
    return sources


def _default_client() -> Any:
    from ..integrations.google_drive import DriveClient

    return DriveClient()


__all__ = [
    "DriveSource",
    "FALLBACK_FOLDER_ENV",
    "FOLDER_ENV",
    "MAX_SOURCES",
    "MIME_CSV",
    "MIME_GOOGLE_SHEET",
    "MIME_XLSX",
    "TABLE_MIMES",
    "folder_id",
    "list_recent_sources",
]
