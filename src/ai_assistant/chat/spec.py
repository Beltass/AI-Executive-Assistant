"""``ReportSpec`` — sipariş edilen raporun tarafsız, diske yazılabilir tarifi.

Neden ayrı bir tip? Üç yerin AYNI şeyi anlatması gerekiyor:

* :mod:`ai_assistant.chat.session` — menüden adım adım doldurur,
* :mod:`ai_assistant.chat.intent` — tek cümleden çıkarır,
* :mod:`ai_assistant.chat.templates` — isimle kaydeder, sonra tekrar çalıştırır.

:class:`ai_assistant.analysis.analyzer.AnalysisRequest` bu iş için uygun değil:
``Measure``/``Filter`` nesneleri ve ``datetime`` alanları taşıyor, yani JSON'a
gidip geri dönmüyor. ``ReportSpec`` yalnızca ilkel değerler tutar ve tek yönlü
olarak :meth:`to_request` ile motorun istediği nesneye çevrilir.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..analysis.analyzer import AnalysisRequest

#: Veri kaynağının cinsi.
SOURCE_DRIVE = "drive"
SOURCE_PASTE = "paste"
SOURCE_PATH = "path"

#: Dönem seçenekleri — menüdeki 1..5 ile birebir aynı anahtarlar.
PERIOD_TODAY = "bugun"
PERIOD_WEEK = "bu_hafta"
PERIOD_MONTH = "bu_ay"
PERIOD_QUARTER = "son_3_ay"
PERIOD_CUSTOM = "ozel"

PERIOD_LABELS = {
    PERIOD_TODAY: "Bugün",
    PERIOD_WEEK: "Bu hafta",
    PERIOD_MONTH: "Bu ay",
    PERIOD_QUARTER: "Son 3 ay",
    PERIOD_CUSTOM: "Özel tarih aralığı",
}

#: Dönem seçiminin "son N gün" karşılığı ve zaman ekseni kovası.
PERIOD_WINDOW: Dict[str, int] = {
    PERIOD_TODAY: 1,
    PERIOD_WEEK: 7,
    PERIOD_MONTH: 30,
    PERIOD_QUARTER: 90,
}
PERIOD_BUCKET: Dict[str, str] = {
    PERIOD_TODAY: "saat",
    PERIOD_WEEK: "gün",
    PERIOD_MONTH: "gün",
    PERIOD_QUARTER: "hafta",
}

#: Görselleştirme seçenekleri.
CHART_LINE = "line"
CHART_BAR = "bar"
CHART_DONUT = "donut"
CHART_HEATMAP = "heatmap"
CHART_TABLE = "table"

CHART_LABELS = {
    CHART_LINE: "Trend çizgisi",
    CHART_BAR: "Karşılaştırma çubuğu",
    CHART_DONUT: "Dağılım halkası",
    CHART_HEATMAP: "Yoğunluk haritası",
    CHART_TABLE: "Sadece tablo (zaman serisi grafiği yok)",
}

#: Çıktı biçimleri.
FORMAT_WEB = "web"
FORMAT_XLSX = "xlsx"

FORMAT_LABELS = {
    FORMAT_WEB: "Tarayıcı raporu",
    FORMAT_XLSX: "Excel (.xlsx)",
}

#: "Sadece tablo" seçildiğinde üretilen analiz bölümleri — zaman serisi çıkar.
TABLE_ONLY_INCLUDE = ["kpi", "pivot", "outliers", "correlations"]


def days_label(days: int) -> str:
    """``90`` -> ``Son 3 ay``; ``14`` -> ``Son 2 hafta``; ``5`` -> ``Son 5 gün``."""
    if days <= 0:
        return "Tüm veri"
    if days % 30 == 0 and days >= 30:
        return f"Son {days // 30} ay"
    if days % 7 == 0 and days >= 7:
        return f"Son {days // 7} hafta"
    return f"Son {days} gün"


def _iso(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass
class ReportSpec:
    """Bir rapor siparişinin tamamı — JSON'a yazılabilir hâli."""

    #: ``drive`` / ``paste`` / ``path``
    source_kind: str = ""
    #: Drive dosya kimliği, e-tablo bağlantısı ya da yerel dosya yolu.
    source: str = ""
    #: Kullanıcıya gösterilecek kaynak adı ("Temmuz Çağrı Verisi").
    source_label: str = ""
    #: Yapıştırılan tablo metni (``source_kind == "paste"`` iken).
    pasted: str = ""
    #: E-tablo sayfası (boşsa ilk/ en dolu sayfa).
    sheet: str = ""

    period: str = ""
    date_from: str = ""
    date_to: str = ""
    #: Menüdeki beş seçeneğe uymayan serbest pencere ("son 45 gün"). Hızlı yol
    #: doldurur; menü ``period`` üzerinden aynı sonuca ulaşır.
    last_days: int = 0
    #: Zaman ekseni kovası — ``saat`` / ``gün`` / ``hafta`` / ``ay``.
    bucket: str = ""

    dimensions: List[str] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)
    chart: str = ""
    formats: List[str] = field(default_factory=list)

    title: str = ""
    #: İsteği doğuran ham cümle (hızlı yol) — rapora "ne sorulmuştu" diye yazılır.
    question: str = ""

    # --- kaynak -------------------------------------------------------------

    def has_source(self) -> bool:
        return bool(self.pasted if self.source_kind == SOURCE_PASTE else self.source)

    def source_display(self) -> str:
        """Kaynağın kullanıcıya gösterilecek adı."""
        if self.source_kind == SOURCE_PASTE:
            rows = len([line for line in self.pasted.splitlines() if line.strip()])
            return f"Yapıştırılan veri ({rows} satır)"
        return self.source_label or self.source or "—"

    # --- pencere ------------------------------------------------------------

    def window(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Dönem seçimini ``last_days`` / ``date_from`` / ``date_to``ya çevirir.

        ``bugun``/``bu hafta``/``bu ay`` takvim değil KAYAN penceredir: rapor
        çoğu zaman dünkü veriyle çalışır ve motor pencereyi verinin SON
        tarihinden geriye sayar, yani "bu ay" boş bir rapor üretmez.
        """
        if self.date_from or self.date_to:
            return {
                "last_days": None,
                "date_from": _iso(self.date_from),
                "date_to": _iso(self.date_to),
            }
        if self.last_days > 0:
            return {"last_days": self.last_days, "date_from": None, "date_to": None}
        days = PERIOD_WINDOW.get(self.period)
        return {"last_days": days, "date_from": None, "date_to": None}

    def has_period(self) -> bool:
        """Dönem gerçekten belirlenmiş mi? (Onay ekranı ve hızlı yol sorar.)"""
        return bool(self.period or self.date_from or self.date_to or self.last_days)

    def period_label(self) -> str:
        if self.date_from or self.date_to:
            start = _iso(self.date_from)
            end = _iso(self.date_to)
            if start and end:
                return f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"
            if start:
                return f"{start.strftime('%d.%m.%Y')} sonrası"
            if end:
                return f"{end.strftime('%d.%m.%Y')} öncesi"
            return "Özel tarih aralığı"
        if self.period in PERIOD_LABELS and self.period != PERIOD_CUSTOM:
            return PERIOD_LABELS[self.period]
        if self.last_days > 0:
            return days_label(self.last_days)
        if self.period == PERIOD_CUSTOM:
            return "Özel tarih aralığı"
        return "Tüm veri"

    def chart_label(self) -> str:
        return CHART_LABELS.get(self.chart, "Otomatik")

    def format_label(self) -> str:
        names = [FORMAT_LABELS[f] for f in self.formats if f in FORMAT_LABELS]
        return " + ".join(names) if names else "—"

    def wants(self, fmt: str) -> bool:
        return fmt in self.formats

    # --- motora çeviri ------------------------------------------------------

    def to_request(self, now: Optional[datetime] = None) -> AnalysisRequest:
        """Motorun anladığı :class:`AnalysisRequest`."""
        window = self.window(now)
        chart_type = "" if self.chart in ("", CHART_TABLE) else self.chart
        include = list(TABLE_ONLY_INCLUDE) if self.chart == CHART_TABLE else []
        return AnalysisRequest(
            dimensions=list(self.dimensions),
            metrics=list(self.metrics),
            period=self.bucket or PERIOD_BUCKET.get(self.period, ""),
            date_from=window["date_from"],
            date_to=window["date_to"],
            last_days=window["last_days"],
            chart_type=chart_type,
            formats=list(self.formats) or [FORMAT_XLSX, FORMAT_WEB],
            include=include,
            title=self.title,
            question=self.question,
        )

    # --- özet ---------------------------------------------------------------

    def summary_lines(self) -> List[str]:
        """Onay ekranının satırları — kullanıcı ne sipariş ettiğini görür."""
        return [
            f"• *Kaynak:* {self.source_display()}",
            f"• *Dönem:* {self.period_label()}",
            f"• *Kırılım:* {' × '.join(self.dimensions) if self.dimensions else 'otomatik'}",
            f"• *Metrikler:* {', '.join(self.metrics) if self.metrics else 'otomatik'}",
            f"• *Görselleştirme:* {self.chart_label()}",
            f"• *Format:* {self.format_label()}",
        ]

    def one_line(self) -> str:
        """Şablon listesinde görünen tek satırlık özet."""
        parts = [
            self.source_display(),
            self.period_label(),
            " × ".join(self.dimensions) or "otomatik kırılım",
            ", ".join(self.metrics) or "otomatik metrik",
            self.format_label(),
        ]
        return " · ".join(part for part in parts if part and part != "—")

    # --- serileştirme -------------------------------------------------------

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Any) -> "ReportSpec":
        """Diskten okunan sözlüğü nesneye çevirir; bozuk alanları yok sayar."""
        payload = data if isinstance(data, dict) else {}
        spec = cls()
        raw_days = payload.get("last_days")
        if isinstance(raw_days, int) and raw_days > 0:
            spec.last_days = raw_days
        for name in (
            "source_kind",
            "source",
            "source_label",
            "pasted",
            "sheet",
            "period",
            "date_from",
            "date_to",
            "bucket",
            "chart",
            "title",
            "question",
        ):
            value = payload.get(name)
            if isinstance(value, str):
                setattr(spec, name, value)
        for name in ("dimensions", "metrics", "formats"):
            value = payload.get(name)
            if isinstance(value, list):
                setattr(spec, name, [str(item) for item in value if str(item).strip()])
        return spec

    def copy(self) -> "ReportSpec":
        return ReportSpec.from_dict(self.as_dict())


def relative_window(period: str, now: Optional[datetime] = None) -> Optional[timedelta]:
    """Bir dönem anahtarının süre karşılığı; bilinmeyen anahtarda ``None``."""
    days = PERIOD_WINDOW.get(period)
    return timedelta(days=days) if days else None


__all__ = [
    "CHART_BAR",
    "CHART_DONUT",
    "CHART_HEATMAP",
    "CHART_LABELS",
    "CHART_LINE",
    "CHART_TABLE",
    "FORMAT_LABELS",
    "FORMAT_WEB",
    "FORMAT_XLSX",
    "PERIOD_BUCKET",
    "PERIOD_CUSTOM",
    "PERIOD_LABELS",
    "PERIOD_MONTH",
    "PERIOD_QUARTER",
    "PERIOD_TODAY",
    "PERIOD_WEEK",
    "PERIOD_WINDOW",
    "ReportSpec",
    "days_label",
    "SOURCE_DRIVE",
    "SOURCE_PASTE",
    "SOURCE_PATH",
    "TABLE_ONLY_INCLUDE",
    "relative_window",
]
