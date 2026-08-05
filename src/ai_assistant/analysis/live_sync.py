"""Canlı rapor — kaynak e-tabloya satır eklendiğinde rapor kendini tazeler.

Kullanıcının "canlı" derken kastettiği şey basit: Drive'daki tabloya yeni gün
işlendiğinde raporun da yeni günü göstermesi. Bunun iki tuzağı var ve ikisi de
burada kapatılıyor:

1. **Gereksiz yeniden üretim.** Her koşuda tüm veriyi indirip analiz etmek hem
   yavaş hem de Drive kotasını yakar. Bu yüzden önce UCUZ kapı kontrol edilir:
   Drive'ın ``modifiedTime`` damgası (yerel dosyada dosya zaman damgası). Damga
   değişmemişse hiçbir şey indirilmez. Damga değişmişse veri okunur ve
   İÇERİK ÖZETİ karşılaştırılır — Drive dosyayı "değişti" diye işaretleyip
   içerik aynı kalabilir (bir hücreye tıklayıp çıkmak yeter).

2. **Sessiz üzerine yazma.** "Canlı" bir raporun dünkü halinin yok olması
   demek değildir. Her yayımlanan sürüm küçük bir geçmiş kaydına yazılır
   (satır sayısı, içerik özeti, o günkü KPI değerleri) ve yeni rapor
   "SON SÜRÜMDEN BU YANA" bölümüyle açılır: kaç satır eklendi, hangi gösterge
   nereden nereye gitti.

Durum dosyası varsayılan olarak ``.assistant_state/analysis_sources.json``
(``ANALYSIS_STATE_FILE`` ile değiştirilebilir) ve depoya girmez.

Google kimliği yoksa, dosya silinmişse ya da sayfa boşsa hiçbir şey patlamaz:
:class:`SyncResult` ``ok=False`` ve TÜRKÇE bir ``message`` ile döner.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..status_report import ISTANBUL
from .analyzer import AnalysisRequest, AnalysisResult, analyze, format_value
from .dataset import Dataset, DatasetError, load_any, sheet_id_from_url

logger = logging.getLogger(__name__)

STATE_FILE_ENV = "ANALYSIS_STATE_FILE"
DEFAULT_STATE_FILE = ".assistant_state/analysis_sources.json"

HISTORY_ENV = "ANALYSIS_VERSION_HISTORY"
DEFAULT_HISTORY = 10

STATE_VERSION = 1


def state_file_path() -> str:
    return (os.getenv(STATE_FILE_ENV) or "").strip() or DEFAULT_STATE_FILE


def history_limit() -> int:
    raw = (os.getenv(HISTORY_ENV) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_HISTORY
    return value if value > 0 else DEFAULT_HISTORY


# --- sürüm kaydı -------------------------------------------------------------


@dataclass
class Version:
    """Yayımlanmış tek bir rapor sürümü."""

    number: int = 1
    published_at: str = ""
    published_at_istanbul: str = ""
    modified_time: str = ""
    row_count: int = 0
    column_count: int = 0
    content_hash: str = ""
    headline: str = ""
    #: ``{"sla": {"value": 84.2, "display": "%84,2", "label": "SLA tutturma"}}``
    metrics: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    xlsx_path: str = ""
    web_path: str = ""
    changes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "number": self.number,
            "published_at": self.published_at,
            "published_at_istanbul": self.published_at_istanbul,
            "modified_time": self.modified_time,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "content_hash": self.content_hash,
            "headline": self.headline,
            "metrics": dict(self.metrics),
            "xlsx_path": self.xlsx_path,
            "web_path": self.web_path,
            "changes": list(self.changes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Version":
        return cls(
            number=int(data.get("number") or 1),
            published_at=str(data.get("published_at") or ""),
            published_at_istanbul=str(data.get("published_at_istanbul") or ""),
            modified_time=str(data.get("modified_time") or ""),
            row_count=int(data.get("row_count") or 0),
            column_count=int(data.get("column_count") or 0),
            content_hash=str(data.get("content_hash") or ""),
            headline=str(data.get("headline") or ""),
            metrics=dict(data.get("metrics") or {}),
            xlsx_path=str(data.get("xlsx_path") or ""),
            web_path=str(data.get("web_path") or ""),
            changes=[str(c) for c in (data.get("changes") or [])],
        )


@dataclass
class TrackedSource:
    """İzlenen bir kaynak ve yayımlanmış sürümlerinin geçmişi."""

    key: str
    source: str = ""
    kind: str = ""
    name: str = ""
    report_id: str = ""
    sheet: str = ""
    created_at: str = ""
    versions: List[Version] = field(default_factory=list)

    @property
    def latest(self) -> Optional[Version]:
        return self.versions[-1] if self.versions else None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "source": self.source,
            "kind": self.kind,
            "name": self.name,
            "report_id": self.report_id,
            "sheet": self.sheet,
            "created_at": self.created_at,
            "versions": [v.as_dict() for v in self.versions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrackedSource":
        return cls(
            key=str(data.get("key") or ""),
            source=str(data.get("source") or ""),
            kind=str(data.get("kind") or ""),
            name=str(data.get("name") or ""),
            report_id=str(data.get("report_id") or ""),
            sheet=str(data.get("sheet") or ""),
            created_at=str(data.get("created_at") or ""),
            versions=[
                Version.from_dict(v)
                for v in (data.get("versions") or [])
                if isinstance(v, dict)
            ],
        )


class SourceStore:
    """``analysis_sources.json`` üzerindeki ince katman. Asla istisna atmaz."""

    def __init__(self, path: str = ""):
        self.path = path or state_file_path()
        self.sources: Dict[str, TrackedSource] = {}
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.warning("analiz durum dosyası okunamadı (%s): %s", self.path, exc)
            return
        if not isinstance(data, dict):
            return
        for key, payload in (data.get("sources") or {}).items():
            if isinstance(payload, dict):
                tracked = TrackedSource.from_dict(payload)
                tracked.key = tracked.key or str(key)
                self.sources[str(key)] = tracked

    def save(self) -> bool:
        payload = {
            "state_version": STATE_VERSION,
            "updated_at": datetime.now(ISTANBUL).isoformat(timespec="seconds"),
            "sources": {key: source.as_dict() for key, source in self.sources.items()},
        }
        try:
            directory = os.path.dirname(os.path.abspath(self.path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            return True
        except Exception as exc:
            logger.warning("analiz durum dosyası yazılamadı (%s): %s", self.path, exc)
            return False

    def get(self, key: str) -> Optional[TrackedSource]:
        return self.sources.get(key)

    def track(self, key: str, **fields: Any) -> TrackedSource:
        tracked = self.sources.get(key)
        if tracked is None:
            tracked = TrackedSource(
                key=key, created_at=datetime.now(ISTANBUL).isoformat(timespec="seconds")
            )
            self.sources[key] = tracked
        for name, value in fields.items():
            if value:
                setattr(tracked, name, value)
        return tracked

    def forget(self, key: str) -> bool:
        return self.sources.pop(key, None) is not None


# --- uzak durum --------------------------------------------------------------


@dataclass
class RemoteState:
    """Kaynağın ucuz kontrol edilebilen dış durumu."""

    modified_time: str = ""
    name: str = ""
    available: bool = True
    reason: str = ""


def source_key(source: str) -> str:
    """Bir kaynağın kararlı kimliği: Drive dosya kimliği ya da mutlak yol."""
    text = str(source or "").strip()
    if not text:
        return ""
    file_id = sheet_id_from_url(text)
    if file_id and not os.path.exists(text):
        return f"drive:{file_id}"
    if os.path.exists(text):
        return f"file:{os.path.abspath(text)}"
    # Yerleşik ``hash()`` her SÜREÇTE farklı sonuç verir (PYTHONHASHSEED
    # rastgeledir), yani yapıştırılmış bir veri kaynağının anahtarı her koşuda
    # değişir ve sürüm geçmişi her seferinde sıfırdan başlardı. Kararlı kimlik
    # kararlı bir özet ister.
    return "raw:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def remote_state(source: str, service: Any = None) -> RemoteState:
    """Kaynağın ``modifiedTime`` damgası — veriyi İNDİRMEDEN.

    Google Drive için Drive API'sinin dosya üst verisi, yerel dosya için dosya
    sisteminin değişiklik zamanı. Kimlik yoksa ``available=False`` döner ve
    çağıran taraf "ucuz kapıyı atla, doğrudan içeriğe bak" der.
    """
    text = str(source or "").strip()
    if os.path.exists(text):
        try:
            stamp = datetime.fromtimestamp(os.path.getmtime(text)).isoformat(
                timespec="seconds"
            )
        except OSError as exc:
            return RemoteState(
                available=False, reason=f"Dosya zaman damgası okunamadı: {exc}"
            )
        return RemoteState(modified_time=stamp, name=os.path.basename(text))

    file_id = sheet_id_from_url(text)
    if not file_id:
        return RemoteState(
            available=False, reason="Kaynak ne dosya ne de Google E-Tablo bağlantısı."
        )

    if service is None:
        try:
            from ..integrations import google_auth

            if not google_auth.google_configured():
                return RemoteState(
                    available=False,
                    reason="Google hesabı bağlı değil; değişiklik kontrolü yapılamadı.",
                )
            from googleapiclient.discovery import build

            service = build(
                "drive",
                "v3",
                credentials=google_auth.get_credentials(),
                cache_discovery=False,
            )
        except Exception as exc:
            return RemoteState(
                available=False, reason=f"Drive bağlantısı kurulamadı: {exc}"
            )

    try:
        meta = (
            service.files()
            .get(fileId=file_id, fields="id, name, modifiedTime")
            .execute()
        )
    except Exception as exc:
        return RemoteState(
            available=False, reason=f"Drive dosya bilgisi alınamadı: {exc}"
        )
    return RemoteState(
        modified_time=str(meta.get("modifiedTime") or ""),
        name=str(meta.get("name") or ""),
    )


# --- değişiklik özeti --------------------------------------------------------


def metric_snapshot(result: AnalysisResult) -> Dict[str, Dict[str, Any]]:
    """Sürüm karşılaştırması için KPI fotoğrafı."""
    snapshot: Dict[str, Dict[str, Any]] = {}
    for finding in result.findings:
        if not finding.key:
            continue
        snapshot[finding.key] = {
            "label": finding.metric,
            "value": finding.value,
            "display": finding.display,
            "unit": finding.unit,
        }
    return snapshot


def describe_changes(
    previous: Optional[Version], dataset: Dataset, result: AnalysisResult
) -> List[str]:
    """ "Son sürümden bu yana" satırları — yeni satırlar ve kayan göstergeler."""
    if previous is None:
        return [f"İlk sürüm: {dataset.row_count} satır analiz edildi."]

    lines: List[str] = []
    delta_rows = dataset.row_count - previous.row_count
    if delta_rows > 0:
        lines.append(
            f"Kaynak tabloya {delta_rows} yeni satır eklendi (toplam {dataset.row_count})."
        )
    elif delta_rows < 0:
        lines.append(
            f"Kaynak tablodan {abs(delta_rows)} satır çıkarıldı (toplam {dataset.row_count})."
        )
    else:
        lines.append(
            f"Satır sayısı değişmedi ({dataset.row_count}); değerler güncellenmiş."
        )

    current = metric_snapshot(result)
    for key, now in current.items():
        before = previous.metrics.get(key)
        if not isinstance(before, dict):
            continue
        old_value = before.get("value")
        new_value = now.get("value")
        if not isinstance(old_value, (int, float)) or not isinstance(
            new_value, (int, float)
        ):
            continue
        difference = new_value - old_value
        if not old_value and not difference:
            continue
        if abs(difference) < abs(old_value or 1) * 0.005:
            continue
        unit = str(now.get("unit") or "")
        arrow = "↑" if difference > 0 else "↓"
        lines.append(
            f"{now.get('label') or key}: {before.get('display') or format_value(old_value, unit)} → "
            f"{now.get('display') or format_value(new_value, unit)} "
            f"({arrow} {format_value(abs(difference), unit)})"
        )

    for key, now in current.items():
        if key not in previous.metrics:
            lines.append(
                f"Yeni gösterge raporlanmaya başladı: {now.get('label') or key}."
            )
    return lines


# --- senkronizasyon ----------------------------------------------------------


@dataclass
class SyncResult:
    """Bir senkronizasyon denemesinin sonucu — her alanı Türkçe anlatılabilir."""

    ok: bool = False
    changed: bool = False
    message: str = ""
    key: str = ""
    version: int = 0
    row_count: int = 0
    new_rows: int = 0
    changes: List[str] = field(default_factory=list)
    xlsx_path: str = ""
    web_path: str = ""
    route: str = ""
    result: Optional[AnalysisResult] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "changed": self.changed,
            "message": self.message,
            "key": self.key,
            "version": self.version,
            "row_count": self.row_count,
            "new_rows": self.new_rows,
            "changes": list(self.changes),
            "xlsx_path": self.xlsx_path,
            "web_path": self.web_path,
            "route": self.route,
        }


def check_source(
    source: str, store: Optional[SourceStore] = None, service: Any = None
) -> Dict[str, Any]:
    """Veriyi indirmeden "değişmiş olabilir mi?" sorusunu yanıtlar."""
    keeper = store or SourceStore()
    key = source_key(source)
    tracked = keeper.get(key)
    state = remote_state(source, service=service)
    if not tracked or not tracked.latest:
        return {
            "key": key,
            "known": False,
            "changed": True,
            "reason": "Bu kaynak ilk kez raporlanacak.",
            "modified_time": state.modified_time,
        }
    latest = tracked.latest
    if not state.available:
        return {
            "key": key,
            "known": True,
            "changed": True,
            "reason": state.reason + " Bu yüzden içerik doğrudan kontrol edilecek.",
            "modified_time": "",
        }
    changed = bool(state.modified_time) and state.modified_time != latest.modified_time
    return {
        "key": key,
        "known": True,
        "changed": changed,
        "reason": (
            "Kaynak son yayından bu yana güncellenmiş."
            if changed
            else f"Kaynak {latest.published_at_istanbul} tarihli sürümden beri değişmemiş."
        ),
        "modified_time": state.modified_time,
    }


def sync_source(
    source: str,
    request: Optional[AnalysisRequest] = None,
    report_id: str = "",
    name: str = "",
    sheet: str = "",
    xlsx_dir: str = "",
    reports_root: str = "",
    force: bool = False,
    store: Optional[SourceStore] = None,
    service: Any = None,
    loader: Optional[Callable[[], Dataset]] = None,
    now: Optional[datetime] = None,
) -> SyncResult:
    """Kaynağı kontrol eder, değiştiyse analizi ve İKİ çıktıyı yeniden üretir.

    ``loader`` verilirse veri onunla yüklenir (testler ve önceden yüklenmiş veri
    için); yoksa :func:`ai_assistant.analysis.dataset.load_any` kullanılır.

    Asla istisna fırlatmaz: her başarısızlık ``ok=False`` ve Türkçe bir
    ``message`` olarak döner.
    """
    from . import excel_report, web_report  # döngüsel içe aktarmayı geciktir

    moment = now or datetime.now(ISTANBUL)
    keeper = store or SourceStore()
    key = source_key(source)
    result = SyncResult(key=key)

    if not key:
        result.message = "Bir veri kaynağı verilmedi."
        return result

    tracked = keeper.get(key)
    latest = tracked.latest if tracked else None
    state = remote_state(source, service=service)

    if not force and latest is not None and state.available and state.modified_time:
        if state.modified_time == latest.modified_time:
            result.ok = True
            result.changed = False
            result.version = latest.number
            result.row_count = latest.row_count
            result.xlsx_path = latest.xlsx_path
            result.web_path = latest.web_path
            result.message = (
                f"Kaynak {latest.published_at_istanbul} tarihli v{latest.number} sürümünden beri "
                f"değişmedi; rapor yeniden üretilmedi."
            )
            return result

    try:
        dataset = loader() if loader else load_any(source, sheet=sheet)
    except DatasetError as exc:
        result.message = str(exc)
        return result
    except Exception as exc:  # beklenmeyen her şey de Türkçe döner
        logger.warning("veri yüklenemedi (%s): %s", key, exc)
        result.message = f"Veri okunamadı: {exc}"
        return result

    content_hash = dataset.content_hash()
    if not force and latest is not None and content_hash == latest.content_hash:
        # Drive damgası değişmiş ama içerik aynı: bir hücreye tıklayıp çıkmak
        # bile damgayı ilerletir. Rapor yeniden yayımlanmaz.
        tracked = keeper.track(key)
        latest.modified_time = state.modified_time or latest.modified_time
        keeper.save()
        result.ok = True
        result.changed = False
        result.version = latest.number
        result.row_count = latest.row_count
        result.xlsx_path = latest.xlsx_path
        result.web_path = latest.web_path
        result.message = f"Kaynak dosya güncellenmiş ama veri içeriği aynı; v{latest.number} sürümü geçerli."
        return result

    try:
        analysis = analyze(dataset, request, now=moment.replace(tzinfo=None))
    except Exception as exc:
        logger.warning("analiz başarısız (%s): %s", key, exc)
        result.message = f"Analiz tamamlanamadı: {exc}"
        return result

    changes = describe_changes(latest, analysis.dataset, analysis)
    number = (latest.number + 1) if latest else 1

    # Rapor, neyin değiştiğini KENDİ İÇİNDE söylesin.
    if latest is not None:
        analysis.notes.insert(0, "Son sürümden bu yana: " + " ".join(changes))

    document_id = (
        report_id
        or (tracked.report_id if tracked else "")
        or web_report.DEFAULT_REPORT_ID
    )
    document_name = (
        name or (tracked.name if tracked else "") or f"{dataset.name} — Veri Analizi"
    )

    xlsx_path = ""
    wants_xlsx = request is None or "xlsx" in (request.formats or ["xlsx", "web"])
    if wants_xlsx:
        directory = xlsx_dir or os.path.join(
            "frontend", "reports", moment.strftime("%Y-%m-%d")
        )
        filename = f"{document_id}_v{number}.xlsx"
        try:
            xlsx_path = excel_report.build_workbook(
                analysis,
                os.path.join(directory, filename),
                moment=moment.replace(tzinfo=None),
            )
        except DatasetError as exc:
            analysis.notes.append(f"Excel çıktısı üretilemedi: {exc}")
        except Exception as exc:
            logger.warning("Excel çıktısı üretilemedi (%s): %s", key, exc)
            analysis.notes.append(f"Excel çıktısı üretilemedi: {exc}")

    web_path = ""
    route = ""
    wants_web = request is None or "web" in (request.formats or ["xlsx", "web"])
    if wants_web:
        document = web_report.build_document(
            analysis,
            report_id=document_id,
            name=document_name,
            moment=moment,
            xlsx_path=xlsx_path,
            change_notes=changes if latest is not None else [],
            extra_meta={
                "version": number,
                "source_key": key,
                "modified_time": state.modified_time,
                "previous_version": latest.number if latest else 0,
            },
        )
        web_path = web_report.publish_document(
            document, root=reports_root, moment=moment
        )
        route = document.route

    version = Version(
        number=number,
        published_at=moment.isoformat(timespec="seconds"),
        published_at_istanbul=(
            moment.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M")
            if moment.tzinfo
            else moment.strftime("%d.%m.%Y %H:%M")
        ),
        modified_time=state.modified_time,
        row_count=analysis.dataset.row_count,
        column_count=analysis.dataset.column_count,
        content_hash=content_hash,
        headline=analysis.headline,
        metrics=metric_snapshot(analysis),
        xlsx_path=xlsx_path,
        web_path=web_path,
        changes=changes,
    )
    tracked = keeper.track(
        key,
        source=source,
        kind=dataset.source_kind,
        name=document_name,
        report_id=document_id,
        sheet=sheet,
    )
    tracked.versions.append(version)
    limit = history_limit()
    if len(tracked.versions) > limit:
        # Geçmiş kırpılır ama SIFIRLANMAZ: "canlı", "sessizce silindi" demek değil.
        tracked.versions = tracked.versions[-limit:]
    keeper.save()

    result.ok = True
    result.changed = True
    result.version = number
    result.row_count = analysis.dataset.row_count
    result.new_rows = max(
        0, analysis.dataset.row_count - (latest.row_count if latest else 0)
    )
    result.changes = changes
    result.xlsx_path = xlsx_path
    result.web_path = web_path
    result.route = route
    result.result = analysis
    result.message = (
        f"v{number} yayımlandı · {analysis.dataset.row_count} satır"
        + (f" (+{result.new_rows} yeni)" if latest and result.new_rows else "")
        + ". "
        + (changes[0] if changes else "")
    )
    return result


def history(source: str, store: Optional[SourceStore] = None) -> List[Version]:
    """Bir kaynağın sürüm geçmişi, eskiden yeniye."""
    keeper = store or SourceStore()
    tracked = keeper.get(source_key(source))
    return list(tracked.versions) if tracked else []


def history_table_tr(source: str, store: Optional[SourceStore] = None) -> str:
    """Sürüm geçmişini Slack/Markdown'da gösterilebilir bir tabloya çevirir."""
    versions = history(source, store=store)
    if not versions:
        return "Bu kaynak için henüz yayımlanmış rapor sürümü yok."
    lines = ["| Sürüm | Tarih | Satır | Öne çıkan |", "| --- | --- | --- | --- |"]
    for version in reversed(versions):
        headline = version.headline.replace("|", "/")
        if len(headline) > 90:
            headline = headline[:89] + "…"
        lines.append(
            f"| v{version.number} | {version.published_at_istanbul} | {version.row_count} | {headline} |"
        )
    return "\n".join(lines)


__all__ = [
    "DEFAULT_HISTORY",
    "DEFAULT_STATE_FILE",
    "RemoteState",
    "SourceStore",
    "SyncResult",
    "TrackedSource",
    "Version",
    "check_source",
    "describe_changes",
    "history",
    "history_table_tr",
    "metric_snapshot",
    "remote_state",
    "source_key",
    "state_file_path",
    "sync_source",
]
