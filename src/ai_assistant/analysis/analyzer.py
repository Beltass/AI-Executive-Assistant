"""Analiz — profillenmiş veriden gerçek bulgulara.

:mod:`ai_assistant.analysis.dataset` veriyi tanır; bu modül veriye SORU sorar:

* **Kırılım (pivot)**: bir ya da iki boyutta toplam / ortalama / adet / en düşük
  / en yüksek. "Temsilci bazında toplam çağrı ve ortalama AHT" tek çağrıdır.
* **Zaman serisi**: dönemsel toplamlar, bir önceki döneme göre fark, hareketli
  ortalama ve eğilim yönü.
* **Aykırı değer**: IQR (çeyrekler açıklığı) yöntemiyle, hangi satırın neden
  sıra dışı olduğu ile birlikte.
* **Korelasyon**: sayısal sütunlar arasında Pearson katsayısı ve ne anlama
  geldiğinin Türkçe karşılığı.
* **Çağrı merkezi KPI'ları**: veri gerçekten çağrı merkezi verisiyse SLA
  tutturma yüzdesi, terk oranı, AHT eğilimi, doluluk, CSAT eğilimi, temsilci ve
  saat dilimi kırılımları kendiliğinden hesaplanır.

HER BULGU (:class:`Finding`) beş şeyi birden taşır: gösterge, değer,
karşılaştırma tabanı, yön ve DÜZ TÜRKÇE bir yorum cümlesi. Rapor katmanları bu
cümleyi olduğu gibi basar; yorumu grafik çizen kod üretmez.

Hiçbir fonksiyon veri yüzünden patlamaz: tek sütunluk veri, tamamen metin veri,
üç satırlık veri — hepsi boş ama geçerli bir sonuç üretir ve nedenini
``notes`` içinde Türkçe söyler.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .dataset import (
    KIND_BOOLEAN,
    KIND_CATEGORICAL,
    KIND_DATE,
    KIND_NUMERIC,
    ColumnProfile,
    Dataset,
)

logger = logging.getLogger(__name__)

#: Varsayılan SLA hedefi (%). Çağrı merkezlerinin klasik "%80/20" kuralı.
DEFAULT_SLA_TARGET = 80.0

#: Bir kırılım tablosunda gösterilen en fazla satır.
MAX_PIVOT_ROWS = 25

#: Zaman serisinde çizilen en fazla nokta.
MAX_SERIES_POINTS = 60

#: Hareketli ortalama penceresi.
MOVING_WINDOW = 3

#: Aykırı değer listesinde saklanan örnek sayısı.
MAX_OUTLIER_EXAMPLES = 8

#: Korelasyonun "anlamlı" sayıldığı eşik.
CORRELATION_THRESHOLD = 0.5

AGG_LABELS = {
    "sum": "toplam",
    "mean": "ortalama",
    "count": "adet",
    "min": "en düşük",
    "max": "en yüksek",
    "median": "medyan",
}

TONE_GOOD = "good"
TONE_WARN = "warn"
TONE_BAD = "bad"
TONE_INFO = "info"


# --- biçimlendirme -----------------------------------------------------------


def format_number(value: Optional[float], digits: int = 1) -> str:
    """Türkçe sayı biçimi: binlik ayırıcı nokta, ondalık virgül."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    if digits <= 0:
        text = f"{round(float(value)):,}"
        return text.replace(",", ".")
    text = f"{float(value):,.{digits}f}"
    whole, _, frac = text.partition(".")
    return whole.replace(",", ".") + "," + frac


def format_duration(seconds: Optional[float]) -> str:
    """Saniyeyi çağrı merkezinin okuduğu biçime çevirir: ``4 dk 35 sn``."""
    if seconds is None or not math.isfinite(seconds):
        return "—"
    total = int(round(abs(seconds)))
    sign = "-" if seconds < 0 else ""
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{sign}{hours} sa {minutes} dk"
    if minutes:
        return f"{sign}{minutes} dk {secs} sn"
    return f"{sign}{secs} sn"


def format_value(
    value: Optional[float], unit: str = "", digits: Optional[int] = None
) -> str:
    """Bir değeri birimiyle birlikte, insanın okuduğu gibi yazar."""
    if (
        value is None
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        return "—"
    if unit == "sn":
        return format_duration(value)
    if unit == "%":
        return "%" + format_number(value, 1 if digits is None else digits)
    if digits is None:
        digits = 0 if abs(value - round(value)) < 1e-9 and abs(value) >= 1 else 1
    text = format_number(value, digits)
    return f"{text} {unit}".strip() if unit else text


def _auto_digits(values: Sequence[float]) -> int:
    if not values:
        return 0
    if all(abs(v - round(v)) < 1e-9 for v in values):
        return 0
    return 1 if max(abs(v) for v in values) >= 10 else 2


# --- ölçütler ----------------------------------------------------------------


@dataclass
class Measure:
    """Bir kırılım tablosunun sayısal sütunu: hangi alan, hangi toplama."""

    column: str
    agg: str = "sum"
    label: str = ""
    unit: str = ""
    digits: Optional[int] = None
    #: Ağırlıklı ortalama için ağırlık sütunu (ör. çağrı adediyle ağırlıklı AHT).
    weight: str = ""

    @property
    def key(self) -> str:
        raw = re.sub(r"\W+", "_", f"{self.column}_{self.agg}".casefold())
        return re.sub(r"_+", "_", raw).strip("_") or "deger"

    def title(self) -> str:
        return self.label or f"{self.column} ({AGG_LABELS.get(self.agg, self.agg)})"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "column": self.column,
            "agg": self.agg,
            "label": self.title(),
            "unit": self.unit,
        }


def default_agg(profile: ColumnProfile) -> str:
    """Bir sütun için doğru toplama işlevi.

    SLA'nın toplamı, AHT'nin toplamı anlamsızdır; çağrı adedinin ortalaması ise
    çoğu zaman istenmeyendir. Bu eşleme, kullanıcının hiçbir şey seçmeden doğru
    tabloyu görmesini sağlar.
    """
    if profile.unit == "%":
        return "mean"
    if profile.metric in (
        "sla",
        "occupancy",
        "adherence",
        "fcr",
        "csat",
        "nps",
        "aht",
        "asa",
        "acw",
        "hold",
    ):
        return "mean"
    if profile.metric in ("calls", "answered", "abandon", "transfer"):
        return "sum"
    if profile.unit == "sn":
        return "mean"
    return "sum"


def measure_for(profile: ColumnProfile, weight: str = "") -> Measure:
    agg = default_agg(profile)
    label_base = profile.metric_label or profile.name
    label = f"{label_base} ({AGG_LABELS.get(agg, agg)})"
    return Measure(
        column=profile.name,
        agg=agg,
        label=label,
        unit=profile.unit,
        weight=weight if agg == "mean" else "",
    )


# --- analiz isteği (dışarıdan programatik tarif) -----------------------------


@dataclass
class Filter:
    """Tek bir satır süzgeci: ``("Vardiya", "=", "Akşam")``.

    Karşılaştırma değeri metinse Türkçe büyük/küçük harf farkı yok sayılır;
    sayısal ve tarihsel karşılaştırmalar sütunun TİPİNE göre yapılır.
    """

    column: str
    op: str = "="
    value: Any = None

    def matches(self, cell: Any) -> bool:
        op = (self.op or "=").lower()
        target = self.value
        if op in ("in", "içinde"):
            values = target if isinstance(target, (list, tuple, set)) else [target]
            return any(_same(cell, item) for item in values)
        if op in ("contains", "içerir"):
            return (
                str(target or "").casefold()
                in str(cell if cell is not None else "").casefold()
            )
        if op in ("between", "arası"):
            try:
                low, high = target  # type: ignore[misc]
            except (TypeError, ValueError):
                return True
            return _compare(cell, low) >= 0 and _compare(cell, high) <= 0
        if op in ("!=", "<>", "değil"):
            return not _same(cell, target)
        if op == "=":
            return _same(cell, target)
        result = _compare(cell, target)
        if result is None:
            return False
        return {
            ">": result > 0,
            ">=": result >= 0,
            "<": result < 0,
            "<=": result <= 0,
        }.get(op, True)

    def label(self) -> str:
        words = {
            "=": "=",
            "!=": "≠",
            "<>": "≠",
            ">": ">",
            ">=": "≥",
            "<": "<",
            "<=": "≤",
            "in": "içinde",
            "contains": "içerir",
            "between": "arası",
        }
        if (
            self.op in ("between", "arası")
            and isinstance(self.value, (list, tuple))
            and len(self.value) == 2
        ):
            return f"{self.column}: {_pretty(self.value[0])} – {_pretty(self.value[1])}"
        if isinstance(self.value, (list, tuple, set)):
            return f"{self.column} {words.get(self.op, self.op)} " + ", ".join(
                _pretty(v) for v in self.value
            )
        return f"{self.column} {words.get(self.op, self.op)} {_pretty(self.value)}"


def _pretty(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _same(cell: Any, target: Any) -> bool:
    if isinstance(cell, str) or isinstance(target, str):
        return (
            str(cell if cell is not None else "").strip().casefold()
            == str(target if target is not None else "").strip().casefold()
        )
    return cell == target


def _compare(cell: Any, target: Any) -> Optional[int]:
    """``cell`` ile ``target`` arasında -1/0/1; kıyaslanamıyorsa ``None``."""
    if cell is None or target is None:
        return None
    try:
        if isinstance(cell, datetime) or isinstance(target, datetime):
            left = cell if isinstance(cell, datetime) else None
            right = target if isinstance(target, datetime) else None
            if left is None or right is None:
                return None
        elif isinstance(cell, (int, float)) and isinstance(target, (int, float)):
            left, right = float(cell), float(target)
        else:
            left, right = str(cell).casefold(), str(target).casefold()
        return (left > right) - (left < right)
    except TypeError:  # pragma: no cover - savunma
        return None


@dataclass
class AnalysisRequest:
    """Çağıran tarafın "şunu istiyorum" dediği analiz tarifi.

    HİÇBİR ALANI ZORUNLU DEĞİL. Boş bir istek, motorun kendi seçimini yaptığı
    otomatik analizle birebir aynı sonucu verir; doldurulan her alan otomatik
    seçimin yerine geçer. Slack üzerinden gelen "son 3 ayın vardiya bazında SLA
    ve terk oranı, haftalık trend grafiğiyle Excel olarak" cümlesi bu nesneye
    çevrilir::

        AnalysisRequest(
            dimensions=["Vardiya"],
            metrics=["sla", "abandon"],
            last_days=90,
            period="hafta",
            chart_type="line",
            formats=["xlsx"],
        )

    Böylece istek ayrıştırma katmanı analiz mantığından tamamen ayrı kalır.
    """

    #: Kırılım eksenleri (sütun adları). Boşsa profil seçer.
    dimensions: List[str] = field(default_factory=list)
    #: Doğrudan ölçüt tanımları. Boşsa ``metrics``/otomatik seçim kullanılır.
    measures: List[Measure] = field(default_factory=list)
    #: Gösterge anahtarları ("sla", "aht", "abandon"…) ya da sütun adları.
    metrics: List[str] = field(default_factory=list)
    #: Toplama işlevi dayatması ("sum"/"mean"/"count"/"min"/"max"/"median").
    agg: str = ""
    #: Zaman ekseni sütunu. Boşsa ilk tarih sütunu.
    date_column: str = ""
    #: Dönem kovası: ``saat`` / ``gün`` / ``hafta`` / ``ay``.
    period: str = ""
    #: Satır süzgeçleri.
    filters: List[Filter] = field(default_factory=list)
    #: Tarih aralığı (dahil).
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    #: "Son N gün" kısayolu; ``date_from`` verilmemişse verinin SON tarihinden
    #: geriye doğru sayılır (rapor dünkü veriyle çalışsa bile doğru pencere).
    last_days: Optional[int] = None
    #: Kırılım tablolarında gösterilecek satır sayısı.
    top_n: int = MAX_PIVOT_ROWS
    #: Sıralama ölçütü (``Measure.key``); boşsa ilk ölçüt.
    sort_by: str = ""
    descending: bool = True
    #: Web raporundaki ana grafik tipi: ``line`` / ``bar`` / ``donut`` / ``heatmap``.
    chart_type: str = ""
    #: İstenen çıktılar: ``xlsx`` ve/veya ``web``.
    formats: List[str] = field(default_factory=lambda: ["xlsx", "web"])
    #: Hangi analiz bölümleri üretilsin: ``kpi``, ``pivot``, ``series``,
    #: ``outliers``, ``correlations``. Boşsa hepsi.
    include: List[str] = field(default_factory=list)
    title: str = ""
    sla_target: float = DEFAULT_SLA_TARGET
    #: İsteği doğuran ham cümle — rapora "ne sorulmuştu" diye yazılır.
    question: str = ""

    def wants(self, part: str) -> bool:
        return not self.include or part in self.include

    def as_dict(self) -> Dict[str, Any]:
        return {
            "dimensions": list(self.dimensions),
            "metrics": list(self.metrics),
            "measures": [m.as_dict() for m in self.measures],
            "agg": self.agg,
            "date_column": self.date_column,
            "period": self.period,
            "filters": [f.label() for f in self.filters],
            "date_from": self.date_from.isoformat() if self.date_from else "",
            "date_to": self.date_to.isoformat() if self.date_to else "",
            "last_days": self.last_days,
            "top_n": self.top_n,
            "chart_type": self.chart_type,
            "formats": list(self.formats),
            "include": list(self.include),
            "title": self.title,
            "sla_target": self.sla_target,
            "question": self.question,
        }

    def summary_tr(self) -> str:
        """İsteğin Türkçe özeti — raporun "Ne sorduk" satırı."""
        parts: List[str] = []
        if self.metrics or self.measures:
            names = [m.column for m in self.measures] + [m for m in self.metrics]
            parts.append("Göstergeler: " + ", ".join(names))
        if self.dimensions:
            parts.append("Kırılım: " + " × ".join(self.dimensions))
        if self.period:
            parts.append(f"Dönem: {self.period} bazında")
        window = self.window_label()
        if window:
            parts.append(window)
        if self.filters:
            parts.append("Süzgeç: " + "; ".join(f.label() for f in self.filters))
        return " · ".join(parts)

    def window_label(self) -> str:
        if self.date_from and self.date_to:
            return f"Aralık: {self.date_from.strftime('%d.%m.%Y')} – {self.date_to.strftime('%d.%m.%Y')}"
        if self.last_days:
            if self.last_days % 30 == 0 and self.last_days >= 30:
                return f"Son {self.last_days // 30} ay"
            if self.last_days % 7 == 0 and self.last_days >= 7:
                return f"Son {self.last_days // 7} hafta"
            return f"Son {self.last_days} gün"
        if self.date_from:
            return f"{self.date_from.strftime('%d.%m.%Y')} sonrası"
        if self.date_to:
            return f"{self.date_to.strftime('%d.%m.%Y')} öncesi"
        return ""


def resolve_columns(dataset: Dataset, names: Sequence[str]) -> List[ColumnProfile]:
    """Sütun adı VEYA gösterge anahtarı listesini gerçek sütunlara çevirir.

    ``["sla", "Terk Edilen"]`` gibi karışık bir liste çalışır: önce birebir ad
    eşleşmesi, sonra gösterge anahtarı, sonra ada göre parça eşleşmesi denenir.
    Bulunamayan ad sessizce atlanır — çağıran taraf ne bulunduğunu
    :attr:`AnalysisResult.notes` içinde görür.
    """
    out: List[ColumnProfile] = []
    seen = set()
    for raw in names:
        text = str(raw or "").strip()
        if not text:
            continue
        found = dataset.column(text)
        if found is None:
            found = next(
                (c for c in dataset.columns if c.metric == text.casefold()), None
            )
        if found is None:
            needle = text.casefold()
            found = next(
                (c for c in dataset.columns if needle in c.name.casefold()), None
            )
        if found is not None and found.index not in seen:
            seen.add(found.index)
            out.append(found)
    return out


def apply_request_filters(
    dataset: Dataset, request: "AnalysisRequest"
) -> Tuple[Dataset, List[str]]:
    """İsteğin süzgeçlerini ve tarih penceresini uygular.

    Süzgeç hiçbir satır bırakmazsa ORİJİNAL veri döner ve not düşülür: boş bir
    rapor, yanlış yazılmış bir vardiya adından daha kötüdür.
    """
    notes: List[str] = []
    rows = dataset.rows
    unknown = [f.column for f in request.filters if dataset.index_of(f.column) < 0]
    if unknown:
        notes.append(
            "Süzgeçte tanınmayan sütun(lar) yok sayıldı: " + ", ".join(unknown) + "."
        )

    active = [f for f in request.filters if dataset.index_of(f.column) >= 0]
    if active:
        indexes = [(dataset.index_of(f.column), f) for f in active]
        rows = [
            row
            for row in rows
            if all(
                item.matches(row[index] if index < len(row) else None)
                for index, item in indexes
            )
        ]

    date_column = None
    if request.date_column:
        date_column = dataset.column(request.date_column)
    if date_column is None or date_column.kind != KIND_DATE:
        date_column = dataset.date_columns()[0] if dataset.date_columns() else None

    start = request.date_from
    end = request.date_to
    if (
        start is None
        and request.last_days
        and date_column is not None
        and date_column.last
    ):
        start = date_column.last - timedelta(days=int(request.last_days))
    if (start or end) and date_column is not None:
        index = date_column.index
        rows = [
            row
            for row in rows
            if not isinstance(row[index] if index < len(row) else None, datetime)
            or (
                (start is None or row[index] >= start)
                and (end is None or row[index] <= end)
            )
        ]
    elif (start or end) and date_column is None:
        notes.append(
            "Tarih aralığı istendi ama veride tarih sütunu yok; aralık uygulanmadı."
        )

    if not rows:
        notes.append(
            "Süzgeçler hiçbir satır bırakmadı, bu yüzden rapor süzgeçsiz veriyle üretildi: "
            + "; ".join(f.label() for f in active)
            + (f" · {request.window_label()}" if request.window_label() else "")
        )
        return dataset, notes

    if len(rows) != dataset.row_count:
        label = "; ".join(f.label() for f in active)
        window = request.window_label()
        detail = " · ".join(part for part in (window, label) if part)
        notes.append(
            f"Süzgeç uygulandı ({detail}): {dataset.row_count} satırdan {len(rows)} satır kaldı."
        )
        return dataset.subset(rows), notes
    return dataset, notes


# --- bulgu -------------------------------------------------------------------


@dataclass
class Finding:
    """Tek bir bulgu: gösterge, değer, taban, yön ve Türkçe yorum."""

    metric: str
    value: Optional[float]
    unit: str = ""
    baseline_label: str = ""
    baseline: Optional[float] = None
    #: ``up`` / ``down`` / ``flat`` — sadece YÖN; iyi mi kötü mü ``tone`` söyler.
    direction: str = "flat"
    delta: Optional[float] = None
    delta_pct: Optional[float] = None
    interpretation: str = ""
    tone: str = TONE_INFO
    key: str = ""
    spark: List[float] = field(default_factory=list)

    @property
    def display(self) -> str:
        return format_value(self.value, self.unit)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "metric": self.metric,
            "value": self.value,
            "display": self.display,
            "unit": self.unit,
            "baseline_label": self.baseline_label,
            "baseline": self.baseline,
            "direction": self.direction,
            "delta": self.delta,
            "delta_pct": self.delta_pct,
            "interpretation": self.interpretation,
            "tone": self.tone,
            "spark": list(self.spark),
        }


def _direction(delta: Optional[float], tolerance: float = 1e-9) -> str:
    if delta is None or abs(delta) <= tolerance:
        return "flat"
    return "up" if delta > 0 else "down"


def _tone(direction: str, better: str) -> str:
    """Yön + "hangi yön iyidir" → renk tonu. Bilinmiyorsa yorumsuz."""
    if not better or direction == "flat":
        return TONE_INFO
    if direction == better:
        return TONE_GOOD
    return TONE_WARN


def make_finding(
    metric: str,
    value: Optional[float],
    unit: str = "",
    baseline: Optional[float] = None,
    baseline_label: str = "",
    better: str = "",
    key: str = "",
    interpretation: str = "",
    spark: Optional[Sequence[float]] = None,
) -> Finding:
    """Bir bulguyu farkı, yönünü ve Türkçe yorumuyla birlikte kurar."""
    delta = None
    delta_pct = None
    if value is not None and baseline is not None:
        delta = value - baseline
        if baseline:
            delta_pct = (delta / abs(baseline)) * 100.0
    direction = _direction(delta) if delta is not None else "flat"
    tone = _tone(direction, better)
    if not interpretation:
        interpretation = _auto_interpretation(
            metric,
            value,
            unit,
            baseline,
            baseline_label,
            delta,
            delta_pct,
            direction,
            better,
        )
    return Finding(
        metric=metric,
        value=value,
        unit=unit,
        baseline=baseline,
        baseline_label=baseline_label,
        direction=direction,
        delta=delta,
        delta_pct=delta_pct,
        interpretation=interpretation,
        tone=tone,
        key=key or re.sub(r"\W+", "_", metric.casefold()).strip("_"),
        spark=[float(v) for v in (spark or []) if isinstance(v, (int, float))],
    )


_DIRECTION_WORDS = {"up": "yükseldi", "down": "geriledi", "flat": "yatay seyretti"}


def _auto_interpretation(
    metric: str,
    value: Optional[float],
    unit: str,
    baseline: Optional[float],
    baseline_label: str,
    delta: Optional[float],
    delta_pct: Optional[float],
    direction: str,
    better: str,
) -> str:
    shown = format_value(value, unit)
    if baseline is None or delta is None:
        return f"{metric} {shown} seviyesinde."
    taban = baseline_label or "önceki dönem"
    change = format_value(abs(delta), unit)
    pct = f" (%{format_number(abs(delta_pct), 1)})" if delta_pct is not None else ""
    word = _DIRECTION_WORDS.get(direction, "değişti")
    sentence = f"{metric} {shown}; {taban} göre {change}{pct} {word}."
    if better and direction != "flat":
        sentence += " Bu iyi yönde." if direction == better else " Bu istenmeyen yönde."
    return sentence


# --- kırılım (pivot) ---------------------------------------------------------


@dataclass
class PivotTable:
    """Bir kırılım tablosu: boyut(lar) × ölçüt(ler) + toplam satırı."""

    title: str
    dimensions: List[str]
    measures: List[Measure]
    rows: List[Dict[str, Any]] = field(default_factory=list)
    totals: Dict[str, Any] = field(default_factory=dict)
    note: str = ""
    truncated: int = 0

    @property
    def column_keys(self) -> List[str]:
        return list(self.dimensions) + [m.key for m in self.measures]

    def column_specs(self) -> List[Dict[str, Any]]:
        """Ön yüzün ``dataTable`` sütun tanımları (sıralanabilir)."""
        specs: List[Dict[str, Any]] = [
            {"key": dim, "label": dim, "type": "text"} for dim in self.dimensions
        ]
        for measure in self.measures:
            specs.append(
                {
                    "key": measure.key,
                    "label": measure.title(),
                    "type": "num",
                    "digits": 0 if measure.unit not in ("%",) else 1,
                }
            )
        return specs

    def display_rows(self) -> List[Dict[str, Any]]:
        """Satırlar, sayılar Türkçe biçimlenmiş halde (Excel/markdown için)."""
        out: List[Dict[str, Any]] = []
        for row in self.rows:
            item: Dict[str, Any] = {dim: row.get(dim, "") for dim in self.dimensions}
            for measure in self.measures:
                item[measure.key] = format_value(
                    row.get(measure.key), measure.unit, measure.digits
                )
            out.append(item)
        return out

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "dimensions": list(self.dimensions),
            "measures": [m.as_dict() for m in self.measures],
            "rows": list(self.rows),
            "totals": dict(self.totals),
            "note": self.note,
        }


_AGGREGATORS: Dict[str, Callable[[Sequence[float]], Optional[float]]] = {
    "sum": lambda v: math.fsum(v) if v else None,
    "mean": lambda v: statistics.fmean(v) if v else None,
    "median": lambda v: statistics.median(v) if v else None,
    "min": lambda v: min(v) if v else None,
    "max": lambda v: max(v) if v else None,
}


def _aggregate(
    agg: str, values: Sequence[float], weights: Optional[Sequence[float]] = None
) -> Optional[float]:
    if agg == "count":
        return float(len(values))
    if agg == "mean" and weights:
        pairs = [(v, w) for v, w in zip(values, weights) if w and w > 0]
        if pairs:
            total_weight = math.fsum(w for _, w in pairs)
            if total_weight > 0:
                return math.fsum(v * w for v, w in pairs) / total_weight
    func = _AGGREGATORS.get(agg)
    if func is None:
        return None
    try:
        return func([float(v) for v in values])
    except (TypeError, ValueError):  # pragma: no cover - savunma
        return None


def _label_of(value: Any) -> str:
    if value is None:
        return "(boş)"
    if isinstance(value, bool):
        return "Evet" if value else "Hayır"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def group_by(
    dataset: Dataset,
    dimensions: Sequence[str],
    measures: Sequence[Measure],
    limit: int = MAX_PIVOT_ROWS,
    sort_key: str = "",
    descending: bool = True,
    title: str = "",
) -> PivotTable:
    """Çok boyutlu kırılım tablosu üretir.

    Boyut bulunamazsa ya da ölçüt yoksa BOŞ ama geçerli bir tablo döner; hata
    fırlatmaz, çünkü bu çağrı çoğu zaman otomatik seçimle yapılır.
    """
    dims = [d for d in dimensions if dataset.index_of(d) >= 0]
    used_measures = [
        m for m in measures if dataset.index_of(m.column) >= 0 or m.agg == "count"
    ]
    heading = title or ((" × ".join(dims) + " kırılımı") if dims else "Genel toplam")
    table = PivotTable(title=heading, dimensions=dims, measures=list(used_measures))
    if not dims or not used_measures or not dataset.rows:
        table.note = "Kırılım için uygun boyut ya da ölçüt bulunamadı."
        return table

    dim_indexes = [dataset.index_of(d) for d in dims]
    measure_indexes = [dataset.index_of(m.column) for m in used_measures]
    weight_indexes = [
        dataset.index_of(m.weight) if m.weight else -1 for m in used_measures
    ]

    buckets: Dict[Tuple[str, ...], List[List[float]]] = {}
    weights: Dict[Tuple[str, ...], List[List[float]]] = {}
    order: List[Tuple[str, ...]] = []

    for row in dataset.rows:
        key = tuple(_label_of(row[i]) if i < len(row) else "(boş)" for i in dim_indexes)
        if key not in buckets:
            buckets[key] = [[] for _ in used_measures]
            weights[key] = [[] for _ in used_measures]
            order.append(key)
        for position, index in enumerate(measure_indexes):
            if index < 0:
                buckets[key][position].append(1.0)
                weights[key][position].append(1.0)
                continue
            value = row[index] if index < len(row) else None
            if isinstance(value, bool):
                value = 1.0 if value else 0.0
            if isinstance(value, (int, float)):
                buckets[key][position].append(float(value))
                weight_index = weight_indexes[position]
                weight_value = (
                    row[weight_index] if 0 <= weight_index < len(row) else None
                )
                weights[key][position].append(
                    float(weight_value)
                    if isinstance(weight_value, (int, float))
                    else 0.0
                )

    rows: List[Dict[str, Any]] = []
    for key in order:
        entry: Dict[str, Any] = {dim: key[i] for i, dim in enumerate(dims)}
        for position, measure in enumerate(used_measures):
            entry[measure.key] = _aggregate(
                measure.agg,
                buckets[key][position],
                weights[key][position] if measure.weight else None,
            )
        rows.append(entry)

    sort_field = sort_key or used_measures[0].key
    if any(sort_field == m.key for m in used_measures):
        rows.sort(
            key=lambda r: (r.get(sort_field) is None, r.get(sort_field) or 0),
            reverse=descending,
        )
    else:
        rows.sort(key=lambda r: str(r.get(dims[0], "")))

    if limit and len(rows) > limit:
        table.truncated = len(rows) - limit
        table.note = f"{len(rows)} kırılımdan ilk {limit} tanesi gösteriliyor."
        rows = rows[:limit]
    table.rows = rows

    totals: Dict[str, Any] = {dims[0]: "TOPLAM"}
    for position, measure in enumerate(used_measures):
        index = measure_indexes[position]
        values: List[float] = []
        weight_values: List[float] = []
        for row in dataset.rows:
            value = row[index] if 0 <= index < len(row) else None
            if isinstance(value, bool):
                value = 1.0 if value else 0.0
            if isinstance(value, (int, float)):
                values.append(float(value))
                weight_index = weight_indexes[position]
                weight_value = (
                    row[weight_index] if 0 <= weight_index < len(row) else None
                )
                weight_values.append(
                    float(weight_value)
                    if isinstance(weight_value, (int, float))
                    else 0.0
                )
        totals[measure.key] = _aggregate(
            measure.agg, values, weight_values if measure.weight else None
        )
    table.totals = totals
    return table


# --- zaman serisi ------------------------------------------------------------


@dataclass
class SeriesPoint:
    label: str
    short: str
    value: Optional[float]
    delta: Optional[float] = None
    delta_pct: Optional[float] = None
    moving: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "short": self.short,
            "value": self.value,
            "delta": self.delta,
            "delta_pct": self.delta_pct,
            "moving": self.moving,
        }


@dataclass
class TimeSeries:
    """Bir ölçütün zaman içindeki seyri, dönem farklarıyla birlikte."""

    title: str
    column: str
    agg: str
    period: str
    unit: str = ""
    points: List[SeriesPoint] = field(default_factory=list)
    trend: str = "flat"
    change_pct: Optional[float] = None
    note: str = ""
    better: str = ""

    @property
    def values(self) -> List[float]:
        return [p.value for p in self.points if p.value is not None]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "column": self.column,
            "agg": self.agg,
            "period": self.period,
            "unit": self.unit,
            "trend": self.trend,
            "change_pct": self.change_pct,
            "note": self.note,
            "points": [p.as_dict() for p in self.points],
        }


_PERIOD_KEYS = {
    "saat": ("%Y-%m-%d %H:00", "%d.%m %H:00", "%H:00"),
    "gün": ("%Y-%m-%d", "%d.%m.%Y", "%d.%m"),
    "hafta": ("", "", ""),
    "ay": ("%Y-%m", "%m.%Y", "%m.%y"),
}


def _period_for(profile: ColumnProfile) -> str:
    granularity = (profile.granularity or "").lower()
    if "dakika" in granularity or granularity == "saat":
        return "saat"
    if granularity in ("hafta",):
        return "hafta"
    if granularity in ("ay", "uzun dönem"):
        return "ay"
    return "gün"


def _bucket(moment: datetime, period: str) -> Tuple[str, str, str]:
    """(sıralama anahtarı, tam etiket, kısa etiket)."""
    if period == "hafta":
        monday = moment.date().fromordinal(moment.date().toordinal() - moment.weekday())
        return (
            monday.isoformat(),
            f"{monday.strftime('%d.%m.%Y')} haftası",
            monday.strftime("%d.%m"),
        )
    key_fmt, long_fmt, short_fmt = _PERIOD_KEYS.get(period, _PERIOD_KEYS["gün"])
    return (
        moment.strftime(key_fmt),
        moment.strftime(long_fmt),
        moment.strftime(short_fmt),
    )


def time_series(
    dataset: Dataset,
    date_column: str,
    value_column: str,
    agg: str = "",
    period: str = "",
    limit: int = MAX_SERIES_POINTS,
    title: str = "",
) -> TimeSeries:
    """Dönemsel seri + dönemler arası fark + hareketli ortalama + eğilim."""
    date_profile = dataset.column(date_column)
    value_profile = dataset.column(value_column)
    if not date_profile or date_profile.kind != KIND_DATE:
        return TimeSeries(
            title=title or value_column,
            column=value_column,
            agg=agg or "sum",
            period=period or "gün",
            note="Zaman serisi için tarih sütunu bulunamadı.",
        )
    if not value_profile or value_profile.kind != KIND_NUMERIC:
        return TimeSeries(
            title=title or value_column,
            column=value_column,
            agg=agg or "sum",
            period=period or "gün",
            note="Zaman serisi için sayısal bir ölçüt bulunamadı.",
        )

    use_agg = agg or default_agg(value_profile)
    use_period = period or _period_for(date_profile)
    date_index = date_profile.index
    value_index = value_profile.index

    buckets: Dict[str, List[float]] = {}
    labels: Dict[str, Tuple[str, str]] = {}
    for row in dataset.rows:
        moment = row[date_index] if date_index < len(row) else None
        value = row[value_index] if value_index < len(row) else None
        if not isinstance(moment, datetime) or not isinstance(value, (int, float)):
            continue
        key, long_label, short_label = _bucket(moment, use_period)
        buckets.setdefault(key, []).append(float(value))
        labels[key] = (long_label, short_label)

    series = TimeSeries(
        title=title
        or f"{value_profile.metric_label or value_profile.name} ({AGG_LABELS.get(use_agg, use_agg)})",
        column=value_profile.name,
        agg=use_agg,
        period=use_period,
        unit=value_profile.unit,
        better=value_profile.better,
    )
    if not buckets:
        series.note = "Tarih ve ölçüt birlikte dolu olan satır yok."
        return series

    keys = sorted(buckets)
    if len(keys) > limit:
        series.note = f"{len(keys)} dönemden son {limit} tanesi gösteriliyor."
        keys = keys[-limit:]

    points: List[SeriesPoint] = []
    previous: Optional[float] = None
    for key in keys:
        value = _aggregate(use_agg, buckets[key])
        long_label, short_label = labels[key]
        point = SeriesPoint(label=long_label, short=short_label, value=value)
        if previous is not None and value is not None:
            point.delta = value - previous
            if previous:
                point.delta_pct = (point.delta / abs(previous)) * 100.0
        points.append(point)
        previous = value if value is not None else previous

    window: List[float] = []
    for point in points:
        if point.value is not None:
            window.append(point.value)
            if len(window) > MOVING_WINDOW:
                window.pop(0)
            point.moving = statistics.fmean(window)
    series.points = points

    values = series.values
    if len(values) >= 2:
        head = values[: max(1, len(values) // 2)]
        tail = values[-max(1, len(values) // 2) :]
        change = statistics.fmean(tail) - statistics.fmean(head)
        base = abs(statistics.fmean(head))
        series.change_pct = (change / base * 100.0) if base else None
        threshold = 0.02 * base if base else 0.0
        series.trend = _direction(change, threshold)
    return series


# --- aykırı değerler ---------------------------------------------------------


@dataclass
class Outlier:
    value: float
    row_index: int
    context: str = ""
    side: str = "üst"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "row_index": self.row_index,
            "context": self.context,
            "side": self.side,
        }


@dataclass
class OutlierReport:
    column: str
    unit: str = ""
    q1: Optional[float] = None
    q3: Optional[float] = None
    iqr: Optional[float] = None
    lower: Optional[float] = None
    upper: Optional[float] = None
    count: int = 0
    total: int = 0
    examples: List[Outlier] = field(default_factory=list)
    interpretation: str = ""

    @property
    def rate(self) -> float:
        return (self.count / self.total) if self.total else 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "column": self.column,
            "unit": self.unit,
            "q1": self.q1,
            "q3": self.q3,
            "iqr": self.iqr,
            "lower": self.lower,
            "upper": self.upper,
            "count": self.count,
            "total": self.total,
            "rate": round(self.rate, 4),
            "interpretation": self.interpretation,
            "examples": [o.as_dict() for o in self.examples],
        }


def find_outliers(
    dataset: Dataset,
    column: str,
    context_column: str = "",
    factor: float = 1.5,
) -> OutlierReport:
    """IQR yöntemiyle aykırı değerleri bulur ve Türkçe yorumlar."""
    profile = dataset.column(column)
    report = OutlierReport(column=column)
    if not profile or profile.kind != KIND_NUMERIC:
        report.interpretation = (
            f"'{column}' sayısal bir sütun olmadığı için aykırı değer aranmadı."
        )
        return report
    report.unit = profile.unit

    index = profile.index
    pairs = [
        (float(row[index]), position)
        for position, row in enumerate(dataset.rows)
        if index < len(row)
        and isinstance(row[index], (int, float))
        and not isinstance(row[index], bool)
    ]
    if len(pairs) < 8:
        report.total = len(pairs)
        report.interpretation = f"'{column}' için aykırı değer analizi en az 8 ölçüm ister; elde {len(pairs)} ölçüm var."
        return report

    values = [v for v, _ in pairs]
    ordered = sorted(values)
    q1 = _quantile(ordered, 0.25)
    q3 = _quantile(ordered, 0.75)
    iqr = q3 - q1
    report.q1, report.q3, report.iqr = q1, q3, iqr
    report.lower = q1 - factor * iqr
    report.upper = q3 + factor * iqr
    report.total = len(values)

    context_index = dataset.index_of(context_column) if context_column else -1
    hits: List[Outlier] = []
    for value, position in pairs:
        if iqr <= 0:
            break
        if value > report.upper or value < report.lower:
            row = dataset.rows[position]
            context = ""
            if 0 <= context_index < len(row):
                context = _label_of(row[context_index])
            hits.append(
                Outlier(
                    value=value,
                    row_index=position,
                    context=context,
                    side="üst" if value > report.upper else "alt",
                )
            )
    report.count = len(hits)
    hits.sort(
        key=lambda o: abs(
            o.value - (report.upper if o.side == "üst" else report.lower)
        ),
        reverse=True,
    )
    report.examples = hits[:MAX_OUTLIER_EXAMPLES]

    label = profile.metric_label or column
    if not hits:
        report.interpretation = (
            f"{label} dağılımı dengeli: {format_value(report.lower, profile.unit)} – "
            f"{format_value(report.upper, profile.unit)} bandının dışında ölçüm yok."
        )
    else:
        top = report.examples[0]
        where = f" (örn. {top.context})" if top.context else ""
        report.interpretation = (
            f"{label} için {report.count} aykırı ölçüm var (%{format_number(report.rate * 100, 1)}); "
            f"en uç değer {format_value(top.value, profile.unit)}{where}. "
            f"Normal bant {format_value(report.lower, profile.unit)} – {format_value(report.upper, profile.unit)}."
        )
    return report


def _quantile(ordered: Sequence[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return float(ordered[0])
    position = fraction * (len(ordered) - 1)
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return float(ordered[low])
    weight = position - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


# --- korelasyon --------------------------------------------------------------


@dataclass
class Correlation:
    left: str
    right: str
    r: float
    pairs: int
    interpretation: str = ""

    @property
    def strength(self) -> str:
        magnitude = abs(self.r)
        if magnitude >= 0.85:
            return "çok güçlü"
        if magnitude >= 0.7:
            return "güçlü"
        if magnitude >= 0.5:
            return "orta"
        if magnitude >= 0.3:
            return "zayıf"
        return "ihmal edilebilir"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "left": self.left,
            "right": self.right,
            "r": round(self.r, 4),
            "pairs": self.pairs,
            "strength": self.strength,
            "interpretation": self.interpretation,
        }


def pearson(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    pairs = [
        (a, b)
        for a, b in zip(left, right)
        if isinstance(a, (int, float)) and isinstance(b, (int, float))
    ]
    if len(pairs) < 3:
        return None
    xs = [float(a) for a, _ in pairs]
    ys = [float(b) for _, b in pairs]
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    cov = math.fsum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = math.fsum((x - mean_x) ** 2 for x in xs)
    var_y = math.fsum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def correlations(
    dataset: Dataset, threshold: float = CORRELATION_THRESHOLD
) -> List[Correlation]:
    """Sayısal sütunlar arasındaki anlamlı ilişkiler, güçlüden zayıfa."""
    numeric = dataset.numeric_columns()
    out: List[Correlation] = []
    for i, left in enumerate(numeric):
        for right in numeric[i + 1 :]:
            xs = [
                row[left.index] if left.index < len(row) else None
                for row in dataset.rows
            ]
            ys = [
                row[right.index] if right.index < len(row) else None
                for row in dataset.rows
            ]
            usable = [
                (x, y)
                for x, y in zip(xs, ys)
                if isinstance(x, (int, float))
                and not isinstance(x, bool)
                and isinstance(y, (int, float))
                and not isinstance(y, bool)
            ]
            value = pearson([x for x, _ in usable], [y for _, y in usable])
            if value is None or abs(value) < threshold:
                continue
            item = Correlation(
                left=left.name, right=right.name, r=value, pairs=len(usable)
            )
            way = "birlikte artıyor" if value > 0 else "ters yönde hareket ediyor"
            item.interpretation = (
                f"{left.metric_label or left.name} ile {right.metric_label or right.name} arasında "
                f"{item.strength} bir ilişki var (r = {format_number(value, 2)}): iki gösterge {way}."
            )
            out.append(item)
    out.sort(key=lambda c: abs(c.r), reverse=True)
    return out[:8]


# --- çağrı merkezi KPI'ları --------------------------------------------------


def _weighted_mean(
    dataset: Dataset, column: ColumnProfile, weight: Optional[ColumnProfile]
) -> Optional[float]:
    values: List[float] = []
    weights: List[float] = []
    for row in dataset.rows:
        value = row[column.index] if column.index < len(row) else None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        values.append(float(value))
        if weight is not None:
            weight_value = row[weight.index] if weight.index < len(row) else None
            weights.append(
                float(weight_value) if isinstance(weight_value, (int, float)) else 0.0
            )
    if not values:
        return None
    if weights and math.fsum(weights) > 0:
        return _aggregate("mean", values, weights)
    return statistics.fmean(values)


def _half_split(values: Sequence[float]) -> Tuple[Optional[float], Optional[float]]:
    usable = [v for v in values if isinstance(v, (int, float))]
    if len(usable) < 2:
        return (None, None)
    half = max(1, len(usable) // 2)
    return statistics.fmean(usable[:half]), statistics.fmean(usable[-half:])


def call_center_kpis(
    dataset: Dataset,
    sla_target: float = DEFAULT_SLA_TARGET,
    series_by: Optional[Dict[str, TimeSeries]] = None,
) -> List[Finding]:
    """Veri çağrı merkezi verisiyse türetilen göstergeler.

    Yalnızca GEREKLİ SÜTUNLAR VARSA hesaplanır; olmayan gösterge uydurulmaz.
    """
    findings: List[Finding] = []
    by_metric: Dict[str, ColumnProfile] = {}
    for column in dataset.columns:
        if column.metric and column.is_numeric and column.metric not in by_metric:
            by_metric[column.metric] = column

    calls = by_metric.get("calls")
    series_by = series_by or {}

    def spark_of(metric_key: str) -> List[float]:
        series = series_by.get(metric_key)
        return series.values[-12:] if series else []

    # 1. SLA tutturma
    sla = by_metric.get("sla")
    if sla is not None:
        value = _weighted_mean(dataset, sla, calls)
        if value is not None:
            finding = make_finding(
                metric="SLA tutturma",
                value=value,
                unit="%",
                baseline=sla_target,
                baseline_label=f"%{format_number(sla_target, 0)} hedefine",
                better="up",
                key="sla",
                spark=spark_of("sla"),
            )
            gap = value - sla_target
            if gap >= 0:
                finding.interpretation = (
                    f"Servis seviyesi %{format_number(value, 1)} ile %{format_number(sla_target, 0)} "
                    f"hedefinin {format_number(abs(gap), 1)} puan üzerinde. Hedef tutturuluyor."
                )
                finding.tone = TONE_GOOD
            else:
                finding.interpretation = (
                    f"Servis seviyesi %{format_number(value, 1)}; hedefin {format_number(abs(gap), 1)} "
                    f"puan altında. Kuyruğa ek kaynak ya da vardiya düzenlemesi gerekiyor."
                )
                finding.tone = TONE_BAD if gap < -5 else TONE_WARN
            findings.append(finding)

    # 2. Terk oranı
    abandon = by_metric.get("abandon")
    if abandon is not None:
        if abandon.unit == "%":
            rate = _weighted_mean(dataset, abandon, calls)
        elif calls is not None and calls.total:
            rate = (abandon.total or 0.0) / calls.total * 100.0
        else:
            rate = None
        if rate is not None:
            finding = make_finding(
                metric="Terk oranı",
                value=rate,
                unit="%",
                baseline=5.0,
                baseline_label="%5 sektör eşiğine",
                better="down",
                key="abandon_rate",
                spark=spark_of("abandon"),
            )
            if rate <= 5:
                finding.interpretation = (
                    f"Terk oranı %{format_number(rate, 1)} ile %5'lik kabul eşiğinin altında; "
                    f"müşteri kuyrukta kaybolmuyor."
                )
                finding.tone = TONE_GOOD
            else:
                lost = abandon.total or 0.0
                extra = (
                    f" Dönem içinde {format_number(lost, 0)} çağrı terk edilmiş."
                    if lost
                    else ""
                )
                finding.interpretation = (
                    f"Terk oranı %{format_number(rate, 1)}; %5 eşiğinin üzerinde.{extra} "
                    f"Bekleme süresini kısaltmadan bu oran düşmez."
                )
                finding.tone = TONE_BAD if rate > 10 else TONE_WARN
            findings.append(finding)

    # 3. AHT ve eğilimi
    aht = by_metric.get("aht")
    if aht is not None and aht.mean is not None:
        series = series_by.get("aht")
        first, last = _half_split(series.values) if series else (None, None)
        finding = make_finding(
            metric="Ortalama görüşme süresi (AHT)",
            value=_weighted_mean(dataset, aht, calls),
            unit=aht.unit or "sn",
            baseline=first,
            baseline_label="dönemin ilk yarısına",
            better="down",
            key="aht",
            spark=spark_of("aht"),
        )
        if first is not None and last is not None:
            delta = last - first
            direction = "uzadı" if delta > 0 else "kısaldı"
            finding.interpretation = (
                f"AHT {format_value(finding.value, finding.unit)}; dönemin ilk yarısına göre "
                f"{format_duration(abs(delta))} {direction}. "
                + (
                    "Görüşme süresi uzuyor, bilgi tabanı ve yönlendirme gözden geçirilmeli."
                    if delta > 0
                    else "Kısalan süre kapasiteyi rahatlatıyor."
                )
            )
        else:
            finding.interpretation = (
                f"Ortalama görüşme süresi {format_value(finding.value, finding.unit)}."
            )
        findings.append(finding)

    # 4. Doluluk
    occupancy = by_metric.get("occupancy")
    if occupancy is not None and occupancy.mean is not None:
        value = _weighted_mean(dataset, occupancy, calls)
        finding = make_finding(
            metric="Doluluk",
            value=value,
            unit=occupancy.unit or "%",
            baseline=85.0,
            baseline_label="%85 üst sınırına",
            better="",
            key="occupancy",
            spark=spark_of("occupancy"),
        )
        if value is not None and value > 90:
            finding.interpretation = (
                f"Doluluk %{format_number(value, 1)}. %90 üzeri doluluk tükenmişlik ve devir "
                f"maliyeti üretir; mola planı ve kadro gözden geçirilmeli."
            )
            finding.tone = TONE_BAD
        elif value is not None and value < 65:
            finding.interpretation = (
                f"Doluluk %{format_number(value, 1)}. Kapasite talebin üzerinde; vardiya "
                f"dağılımı sıkılaştırılabilir."
            )
            finding.tone = TONE_WARN
        elif value is not None:
            finding.interpretation = f"Doluluk %{format_number(value, 1)} ile sağlıklı bant (%65–%90) içinde."
            finding.tone = TONE_GOOD
        findings.append(finding)

    # 5. CSAT eğilimi
    csat = by_metric.get("csat")
    if csat is not None and csat.mean is not None:
        series = series_by.get("csat")
        first, last = _half_split(series.values) if series else (None, None)
        finding = make_finding(
            metric="Müşteri memnuniyeti (CSAT)",
            value=_weighted_mean(dataset, csat, calls),
            unit=csat.unit,
            baseline=first,
            baseline_label="dönemin ilk yarısına",
            better="up",
            key="csat",
            spark=spark_of("csat"),
        )
        findings.append(finding)

    # 6. Bekleme süresi (ASA)
    asa = by_metric.get("asa")
    if asa is not None and asa.mean is not None:
        value = _weighted_mean(dataset, asa, calls)
        finding = make_finding(
            metric="Ortalama cevaplama süresi (ASA)",
            value=value,
            unit=asa.unit or "sn",
            baseline=asa.median,
            baseline_label="medyana",
            better="down",
            key="asa",
            spark=spark_of("asa"),
        )
        if value is not None and asa.p90 is not None:
            finding.interpretation = (
                f"Çağrılar ortalama {format_value(value, asa.unit or 'sn')} bekliyor; "
                f"her on çağrıdan biri {format_value(asa.p90, asa.unit or 'sn')} ve üzeri bekliyor."
            )
        findings.append(finding)

    # 7. FCR
    fcr = by_metric.get("fcr")
    if fcr is not None and fcr.mean is not None:
        value = _weighted_mean(dataset, fcr, calls)
        finding = make_finding(
            metric="İlk temasta çözüm (FCR)",
            value=value,
            unit=fcr.unit or "%",
            baseline=75.0,
            baseline_label="%75 referansına",
            better="up",
            key="fcr",
            spark=spark_of("fcr"),
        )
        findings.append(finding)

    # 8. Toplam hacim
    if calls is not None and calls.total is not None:
        findings.insert(
            0,
            make_finding(
                metric="Toplam çağrı",
                value=calls.total,
                unit="",
                key="calls_total",
                interpretation=(
                    f"Dönem içinde toplam {format_number(calls.total, 0)} çağrı işlendi; "
                    f"günlük/dönemsel ortalama {format_number(calls.mean, 1)}."
                ),
                spark=spark_of("calls"),
            ),
        )

    return findings


# --- bütün analiz ------------------------------------------------------------


@dataclass
class AnalysisResult:
    """Bir veri kümesi hakkında üretilen her şey."""

    dataset: Dataset
    #: Bu sonucu doğuran istek (varsayılan: boş, yani otomatik analiz).
    request: Optional["AnalysisRequest"] = None
    title: str = ""
    headline: str = ""
    findings: List[Finding] = field(default_factory=list)
    pivots: List[PivotTable] = field(default_factory=list)
    series: List[TimeSeries] = field(default_factory=list)
    outliers: List[OutlierReport] = field(default_factory=list)
    correlations: List[Correlation] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    generated_at: str = ""
    is_call_center: bool = False

    def key_findings(self, limit: int = 4) -> List[Finding]:
        """Metrik şeridine çıkacak bulgular: önce uyarı verenler."""
        order = {TONE_BAD: 0, TONE_WARN: 1, TONE_GOOD: 2, TONE_INFO: 3}
        ranked = sorted(self.findings, key=lambda f: (order.get(f.tone, 4),))
        return ranked[:limit]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "headline": self.headline,
            "generated_at": self.generated_at,
            "is_call_center": self.is_call_center,
            "request": self.request.as_dict() if self.request else {},
            "profile": self.dataset.profile(),
            "findings": [f.as_dict() for f in self.findings],
            "pivots": [p.as_dict() for p in self.pivots],
            "series": [s.as_dict() for s in self.series],
            "outliers": [o.as_dict() for o in self.outliers],
            "correlations": [c.as_dict() for c in self.correlations],
            "notes": list(self.notes),
        }


#: Kırılım ekseni olarak tercih sırası — çağrı merkezinde bu sıra rapora bakan
#: yöneticinin sorduğu soru sırasıdır.
_DIMENSION_PRIORITY = (
    "agent",
    "queue",
    "interval",
    "team",
    "shift",
    "channel",
    "reason",
)


def _pick_dimensions(dataset: Dataset, limit: int = 3) -> List[ColumnProfile]:
    candidates = dataset.dimension_columns()
    ranked = sorted(
        candidates,
        key=lambda c: (
            (
                _DIMENSION_PRIORITY.index(c.metric)
                if c.metric in _DIMENSION_PRIORITY
                else 99
            ),
            c.distinct,
        ),
    )
    return ranked[:limit]


def _pick_measures(dataset: Dataset, weight: str = "", limit: int = 4) -> List[Measure]:
    metrics = dataset.metric_columns()
    if not metrics:
        metrics = [c for c in dataset.numeric_columns() if c.distinct > 1]
    ordered = sorted(
        metrics,
        key=lambda c: (0 if c.metric in ("calls", "answered") else 1, c.index),
    )
    return [measure_for(column, weight=weight) for column in ordered[:limit]]


#: Zaman serisi çizilirken hangi göstergenin önce geleceği. Yöneticinin
#: baktığı sıra: önce hacim, sonra süre, sonra servis seviyesi.
_SERIES_PRIORITY = ("calls", "aht", "sla", "abandon", "asa", "csat", "occupancy", "fcr")


def _series_measures(
    dataset: Dataset, measures: Sequence[Measure], limit: int = 4
) -> List[Measure]:
    """Zaman serisi çizilecek ölçütler — aynı sorunun iki kopyası değil.

    Varsayılan ölçüt listesi "çağrı, cevaplanan, terk" gibi birbirinin türevi
    üç sütunla başlayabiliyor; grafik olarak bu üç kez aynı eğridir. Burada
    farklı göstergeler öne alınır.
    """
    by_key: Dict[str, Measure] = {}
    for measure in measures:
        profile = dataset.column(measure.column)
        key = profile.metric if profile and profile.metric else measure.column
        by_key.setdefault(key, measure)
    ordered: List[Measure] = []
    for key in _SERIES_PRIORITY:
        if key in by_key:
            ordered.append(by_key.pop(key))
    ordered.extend(by_key.values())
    return ordered[:limit]


def analyze(
    dataset: Dataset,
    request: Optional[AnalysisRequest] = None,
    sla_target: Optional[float] = None,
    title: str = "",
    now: Optional[datetime] = None,
) -> AnalysisResult:
    """Veriye bakıp istenen (ya da uygun olan HER) analizi çalıştırır.

    ``request`` verilmezse motor kendi seçimini yapar: hangi sütunun ölçüt,
    hangisinin eksen olduğuna profil karar verir. ``request`` verilirse — Slack
    üzerinden gelen bir cümleden çevrilmiş olabilir — kırılım, ölçüt, dönem,
    süzgeç ve satır sayısı ORADAN gelir; tarif edilmeyen her şey yine otomatik
    seçilir.

    Hiçbir analiz uygulanamıyorsa sonuç boş döner ve nedeni ``notes`` içinde
    Türkçe yazar — istisna fırlatmaz.
    """
    spec = request or AnalysisRequest()
    if sla_target is not None:
        spec.sla_target = sla_target
    moment = now or datetime.now()

    source, filter_notes = apply_request_filters(dataset, spec)

    result = AnalysisResult(
        dataset=source,
        request=spec,
        title=title or spec.title or f"{source.name} — Veri Analizi",
        generated_at=moment.isoformat(timespec="seconds"),
    )
    result.notes.extend(source.notes)
    result.notes.extend(filter_notes)
    result.is_call_center = source.call_center_score() >= 0.34 and bool(
        source.metric_columns()
    )

    numeric = source.numeric_columns()
    if not numeric:
        result.notes.append(
            "Veride sayısal sütun yok; yalnızca dağılım tabloları üretilebildi."
        )

    calls = next((c for c in source.metric_columns() if c.metric == "calls"), None)
    weight = calls.name if calls else ""

    # --- ölçütler: istek → gösterge adları → otomatik seçim
    measures: List[Measure] = list(spec.measures)
    if not measures and spec.metrics:
        wanted = resolve_columns(source, spec.metrics)
        missing = [m for m in spec.metrics if not resolve_columns(source, [m])]
        if missing:
            result.notes.append(
                "İstenen ama veride bulunamayan gösterge(ler): "
                + ", ".join(missing)
                + "."
            )
        measures = [
            Measure(
                column=column.name,
                agg=spec.agg or default_agg(column),
                label=f"{column.metric_label or column.name} "
                f"({AGG_LABELS.get(spec.agg or default_agg(column), spec.agg)})",
                unit=column.unit,
                weight=weight if (spec.agg or default_agg(column)) == "mean" else "",
            )
            for column in wanted
            if column.is_numeric
        ]
    if not measures:
        measures = _pick_measures(source, weight=weight)
        if spec.agg:
            for measure in measures:
                measure.agg = spec.agg
                measure.label = (
                    f"{measure.column} ({AGG_LABELS.get(spec.agg, spec.agg)})"
                )

    # --- kırılımlar: istek → otomatik seçim
    if spec.dimensions:
        dimensions = resolve_columns(source, spec.dimensions)
        unknown = [d for d in spec.dimensions if not resolve_columns(source, [d])]
        if unknown:
            result.notes.append(
                "İstenen ama veride bulunamayan kırılım(lar): "
                + ", ".join(unknown)
                + "."
            )
        if not dimensions:
            dimensions = _pick_dimensions(source)
    else:
        dimensions = _pick_dimensions(source)

    limit = spec.top_n or MAX_PIVOT_ROWS

    # 1. Kırılımlar
    if spec.wants("pivot"):
        if len(spec.dimensions) > 1 and len(dimensions) > 1:
            # Çok boyut AÇIKÇA istendiyse tek bir çapraz tablo üretilir.
            cross = group_by(
                source,
                [d.name for d in dimensions],
                measures,
                limit=limit,
                sort_key=spec.sort_by,
                descending=spec.descending,
                title=" × ".join(d.name for d in dimensions) + " kırılımı",
            )
            if cross.rows:
                result.pivots.append(cross)
        else:
            for dimension in dimensions:
                if not measures:
                    break
                pivot = group_by(
                    source,
                    [dimension.name],
                    measures,
                    limit=limit,
                    sort_key=spec.sort_by,
                    descending=spec.descending,
                    title=f"{dimension.metric_label or dimension.name} kırılımı",
                )
                if pivot.rows:
                    result.pivots.append(pivot)

            # İki boyutlu çapraz tablo, iki uygun eksen varsa (küçük tutulur).
            if not spec.dimensions and len(dimensions) >= 2 and measures:
                small = [d for d in dimensions if d.distinct <= 12]
                if len(small) >= 2:
                    cross = group_by(
                        source,
                        [small[0].name, small[1].name],
                        measures[:2],
                        limit=limit,
                        title=f"{small[0].name} × {small[1].name} çapraz kırılımı",
                    )
                    if cross.rows:
                        result.pivots.append(cross)

    # 2. Zaman serileri
    date_columns = source.date_columns()
    requested_date = source.column(spec.date_column) if spec.date_column else None
    if requested_date is not None and requested_date.kind != KIND_DATE:
        result.notes.append(
            f"'{spec.date_column}' bir tarih sütunu değil; zaman ekseni otomatik seçildi."
        )
        requested_date = None
    date_column = requested_date or (date_columns[0] if date_columns else None)

    series_by_metric: Dict[str, TimeSeries] = {}
    if spec.wants("series") and date_column is not None and measures:
        pool = (
            measures
            if (spec.measures or spec.metrics)
            else _pick_measures(source, weight=weight, limit=12)
        )
        for measure in _series_measures(source, pool):
            series = time_series(
                source,
                date_column.name,
                measure.column,
                agg=measure.agg,
                period=spec.period,
            )
            if len(series.values) >= 2:
                result.series.append(series)
                profile = source.column(measure.column)
                if profile and profile.metric:
                    series_by_metric[profile.metric] = series
    elif spec.wants("series") and date_column is None:
        result.notes.append("Tarih sütunu bulunmadığı için zaman serisi üretilemedi.")

    # 3. Aykırı değerler
    if spec.wants("outliers"):
        context = dimensions[0].name if dimensions else ""
        targets = (
            [source.column(m.column) for m in measures]
            if (spec.measures or spec.metrics)
            else numeric[:4]
        )
        for column in [c for c in targets if c is not None][:4]:
            report = find_outliers(source, column.name, context_column=context)
            if report.count or report.total >= 8:
                result.outliers.append(report)

    # 4. Korelasyonlar
    if spec.wants("correlations"):
        result.correlations = correlations(source)

    # 5. Bulgular
    if spec.wants("kpi"):
        if result.is_call_center:
            result.findings.extend(
                call_center_kpis(
                    source, sla_target=spec.sla_target, series_by=series_by_metric
                )
            )
        if not result.findings:
            result.findings.extend(_generic_findings(source, result.series))

    result.headline = _headline(result)
    return result


def _generic_findings(dataset: Dataset, series: Sequence[TimeSeries]) -> List[Finding]:
    """Çağrı merkezi olmayan veride de dolu bir metrik şeridi üretir."""
    out: List[Finding] = []
    series_by_column = {s.column: s for s in series}
    for column in dataset.numeric_columns()[:4]:
        agg = default_agg(column)
        value = column.total if agg == "sum" else column.mean
        related = series_by_column.get(column.name)
        first, last = _half_split(related.values) if related else (None, None)
        out.append(
            make_finding(
                metric=f"{column.name} ({AGG_LABELS.get(agg, agg)})",
                value=value,
                unit=column.unit,
                baseline=first,
                baseline_label="dönemin ilk yarısına",
                key=column.name,
                spark=related.values[-12:] if related else [],
            )
        )
    if not out:
        for column in dataset.columns:
            if column.top_values:
                label, count = column.top_values[0]
                out.append(
                    make_finding(
                        metric=f"En sık {column.name}",
                        value=float(count),
                        interpretation=(
                            f"'{column.name}' sütununda en sık görülen değer '{label}' "
                            f"({count} kayıt, toplamın %{format_number(count / max(1, column.count) * 100, 1)}'i)."
                        ),
                        key=column.name,
                    )
                )
                break
    return out[:4]


def _headline(result: AnalysisResult) -> str:
    """Raporun tek cümlelik "öne çıkan" satırı."""
    dataset = result.dataset
    problems = [f for f in result.findings if f.tone in (TONE_BAD, TONE_WARN)]
    if problems:
        return problems[0].interpretation
    if result.series:
        series = result.series[0]
        if series.trend != "flat" and series.change_pct is not None:
            word = "yükseliş" if series.trend == "up" else "düşüş"
            return (
                f"{series.title} dönem boyunca %{format_number(abs(series.change_pct), 1)} "
                f"{word} gösterdi ({series.period} bazında {len(series.points)} dönem)."
            )
    if result.findings:
        return result.findings[0].interpretation
    return f"{dataset.summary_tr()} veri incelendi; öne çıkan bir sapma bulunmadı."


__all__ = [
    "AGG_LABELS",
    "AnalysisRequest",
    "AnalysisResult",
    "Correlation",
    "Filter",
    "apply_request_filters",
    "resolve_columns",
    "DEFAULT_SLA_TARGET",
    "Finding",
    "Measure",
    "Outlier",
    "OutlierReport",
    "PivotTable",
    "SeriesPoint",
    "TimeSeries",
    "analyze",
    "call_center_kpis",
    "correlations",
    "default_agg",
    "find_outliers",
    "format_duration",
    "format_number",
    "format_value",
    "group_by",
    "make_finding",
    "measure_for",
    "pearson",
    "time_series",
]
