"""Onaydan sonrası: analizi çalıştır, çıktıları üret, kanala teslim et.

Sıra:

1. veri okunur (:mod:`ai_assistant.analysis.dataset`),
2. analiz edilir (:func:`ai_assistant.analysis.analyzer.analyze`),
3. istenmişse ``.xlsx`` üretilir ve Slack'e YÜKLENİR (files.upload v2),
4. istenmişse tarayıcı raporu yayımlanır ve BAĞLANTISI gönderilir,
5. her hâlükârda kısa bir Türkçe BULGU ÖZETİ yazılır.

Beşinci madde isteğe bağlı değil. Bir dosya eki ya da bir bağlantı, "rapor
hazır" demekten başka bir şey söylemez; kullanıcı hiçbir şey açmadan da SLA'nın
düştüğünü görebilmeli. Özet o yüzden her teslimatın parçası.

Hiçbir adım istisna sızdırmaz: okunamayan veri, kurulu olmayan ``openpyxl``,
reddedilen Slack yüklemesi — hepsi "ne oldu, ne yapmalı" cümlesine dönüşür.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, List, Optional

from ..analysis import web_report
from ..analysis.analyzer import AnalysisResult, analyze
from ..analysis.dataset import Dataset, DatasetError
from ..analysis.excel_report import build_workbook
from .slack_api import SlackClient, SlackError
from .spec import FORMAT_WEB, FORMAT_XLSX, ReportSpec

logger = logging.getLogger(__name__)

#: Özette gösterilen bulgu sayısı — üçten fazlası Slack'te duvar olur.
MAX_FINDINGS = 3

#: Üretilen raporun pano üzerindeki kimliği.
REPORT_ID = "veri_analizi"

_SLUG_STRIP = re.compile(r"[^0-9a-zA-Z]+")
_TR_MAP = str.maketrans(
    {"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "İ": "i"}
)


@dataclass
class Delivery:
    """Bir teslimatın sonucu."""

    ok: bool = False
    messages: List[str] = field(default_factory=list)
    xlsx_path: str = ""
    report_route: str = ""
    error: str = ""
    result: Optional[AnalysisResult] = None


def slugify(text: str) -> str:
    """Dosya adı için güvenli bir gövde üretir."""
    folded = str(text or "").translate(_TR_MAP).casefold()
    slug = _SLUG_STRIP.sub("-", folded).strip("-")
    return slug[:48] or "rapor"


def dashboard_link(route: str) -> str:
    """Yayımlanan raporun tam adresi."""
    from ..notifiers.slack_notifier import dashboard_base_url

    return dashboard_base_url() + route


def summarize(result: AnalysisResult, limit: int = MAX_FINDINGS) -> str:
    """Raporun manşeti ve ilk bulguları — hiçbir şey açmadan okunacak özet."""
    lines: List[str] = []
    headline = str(result.headline or "").strip()
    if headline:
        lines.append(f"*{headline}*")

    for finding in result.key_findings(limit + 1):
        text = str(finding.interpretation or "").strip()
        if not text:
            label = finding.metric or finding.key
            text = f"{label}: {finding.display}"
        # Manşet zaten en önemli bulgudur; onu bir de madde olarak tekrarlamak
        # özeti kısaltmıyor, uzatıyor.
        if text == headline:
            continue
        lines.append(f"• {text}")
        if len(lines) > limit:
            break

    if not lines:
        lines.append("Veriden öne çıkan bir bulgu çıkmadı; tablolar rapordadır.")

    notes = [n for n in (result.notes or []) if n][:2]
    if notes:
        lines.append("_" + " ".join(notes) + "_")
    return "\n".join(lines)


def run(
    spec: ReportSpec,
    channel: str,
    client: Optional[SlackClient] = None,
    loader: Optional[Callable[[ReportSpec], Dataset]] = None,
    publisher: Optional[Callable[..., Any]] = None,
    reports_root: str = "",
    now: Optional[datetime] = None,
    workdir: str = "",
) -> Delivery:
    """Tarifi çalıştırır ve çıktıları kanala teslim eder.

    ``client`` yoksa yalnızca analiz yapılır ve özet metni döner (test ve kuru
    çalıştırma yolu). Asla istisna fırlatmaz.
    """
    from .session import default_loader

    read = loader or default_loader
    moment = now or datetime.now()
    delivery = Delivery()

    # 1 — veri
    try:
        dataset = read(spec)
    except DatasetError as exc:
        delivery.error = str(exc)
        delivery.messages.append(f"Veri okunamadı: {exc}")
        return delivery
    except Exception as exc:
        logger.warning("veri okunamadı: %s", exc)
        delivery.error = str(exc)
        delivery.messages.append(
            f"Veri okunamadı ({type(exc).__name__}): {exc}. "
            "Kaynağı kontrol edip `rapor` yazarak tekrar deneyin."
        )
        return delivery

    # 2 — analiz
    request = spec.to_request(moment)
    title = spec.title or f"{dataset.name} — {spec.period_label()}"
    try:
        result = analyze(dataset, request=request, title=title, now=moment)
    except Exception as exc:
        logger.exception("analiz çöktü: %s", exc)
        delivery.error = str(exc)
        delivery.messages.append(
            f"Analiz sırasında hata oldu ({type(exc).__name__}): {exc}. "
            "Farklı bir kırılım ya da dönem seçip tekrar deneyebilirsiniz."
        )
        return delivery
    delivery.result = result

    formats = spec.formats or [FORMAT_XLSX, FORMAT_WEB]
    stem = f"{slugify(dataset.name)}-{moment.strftime('%Y%m%d-%H%M')}"

    # 3 — Excel
    if FORMAT_XLSX in formats:
        path = os.path.join(workdir or tempfile.gettempdir(), f"{stem}.xlsx")
        try:
            build_workbook(result, path, moment=moment)
            delivery.xlsx_path = path
        except DatasetError as exc:
            delivery.messages.append(f"Excel dosyası üretilemedi: {exc}")
        except Exception as exc:
            logger.warning("Excel üretilemedi: %s", exc)
            delivery.messages.append(
                f"Excel dosyası üretilemedi ({type(exc).__name__}): {exc}"
            )

    # 4 — tarayıcı raporu
    if FORMAT_WEB in formats:
        publish = publisher or web_report.build_and_publish
        try:
            published = publish(
                result,
                report_id=REPORT_ID,
                name=title,
                root=reports_root,
                moment=moment,
                xlsx_path=delivery.xlsx_path,
            )
            route = str((published or {}).get("route") or "")
            if route:
                delivery.report_route = route
        except Exception as exc:
            logger.warning("tarayıcı raporu yayımlanamadı: %s", exc)
            delivery.messages.append(
                f"Tarayıcı raporu yayımlanamadı ({type(exc).__name__}): {exc}"
            )

    # 5 — özet
    summary = summarize(result)
    header = f"*{title}*\n{spec.one_line()}"
    delivery.messages.insert(0, f"{header}\n\n{summary}")
    if delivery.report_route:
        delivery.messages.append(f"<{dashboard_link(delivery.report_route)}|📄 Tam rapor>")

    # 6 — teslim
    if client is not None and client.configured:
        _ship(delivery, client, channel, title)

    delivery.ok = True
    return delivery


def _ship(delivery: Delivery, client: SlackClient, channel: str, title: str) -> None:
    """Üretilen dosyayı kanala yükler. Yükleme hatası teslimatı bitirmez."""
    if not delivery.xlsx_path:
        return
    try:
        client.upload_file(
            channel,
            delivery.xlsx_path,
            title=f"{title}.xlsx",
            comment="Excel raporu ektedir.",
        )
    except SlackError as exc:
        delivery.messages.append(
            f"Excel dosyası kanala yüklenemedi: {exc} "
            "Rapor yine de üretildi; tekrar denemek için siparişi yineleyin."
        )
    except Exception as exc:  # pragma: no cover - savunma
        logger.warning("dosya yüklenemedi: %s", exc)
        delivery.messages.append(f"Excel dosyası kanala yüklenemedi: {exc}")


__all__ = [
    "Delivery",
    "MAX_FINDINGS",
    "REPORT_ID",
    "dashboard_link",
    "run",
    "slugify",
    "summarize",
]
