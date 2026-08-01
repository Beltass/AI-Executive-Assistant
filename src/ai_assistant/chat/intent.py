"""Hızlı yol: tek Türkçe cümleden rapor tarifi çıkarır.

    "son 3 ay vardiya bazında SLA ve terk oranı, haftalık trend, Excel"

yedi adımlık menünün tamamını atlar. Bu modül o cümleyi bir
:class:`ai_assistant.chat.spec.ReportSpec` parçasına çevirir, NE ANLADIĞINI
Türkçe olarak geri söyler ve SADECE gerçekten eksik kalanı sorar.

İKİ AŞAMALI, VE BU ÖNEMLİ
-------------------------

1. :func:`parse` — veri olmadan çözülebilenler: dönem, zaman kovası, grafik
   tipi, çıktı biçimi ve METİNDE GEÇEN gösterge/kırılım ADAYLARI.
2. :func:`ground` — kullanıcı kaynağı seçtikten sonra, adaylar GERÇEK
   SÜTUNLARA bağlanır.

Bağlanamayan aday sessizce atılmaz ve asla uydurulmaz: "vardiya" diye bir sütun
yoksa rapor rastgele başka bir eksende üretilmez, kullanıcıya "veride vardiya
diye bir sütun yok, şunlar var" diye sorulur. Yanlış bir rapor, bir soru
sormaktan pahalıdır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..analysis.dataset import METRIC_PATTERNS, Dataset
from . import spec as spec_mod
from .columns import match_terms, mentioned_columns
from .menu import normalize
from .spec import (
    CHART_BAR,
    CHART_DONUT,
    CHART_HEATMAP,
    CHART_LINE,
    CHART_TABLE,
    FORMAT_WEB,
    FORMAT_XLSX,
    PERIOD_MONTH,
    PERIOD_QUARTER,
    PERIOD_TODAY,
    PERIOD_WEEK,
    ReportSpec,
)

#: Dönem ifadeleri — sıra önemli, daha ÖZEL kalıp önce gelir ("son 3 ay" ile
#: "bu ay" aynı cümlede geçtiğinde uzun olan kazanmalı.)
_PERIOD_RULES: Tuple[Tuple[str, Dict[str, Any]], ...] = (
    (r"son\s+(\d{1,3})\s*(gün|gun)", {"unit": 1}),
    (r"son\s+(\d{1,2})\s*(hafta)", {"unit": 7}),
    (r"son\s+(\d{1,2})\s*(ay)\b", {"unit": 30}),
    (r"son\s+(\d{1,2})\s*(yıl|yil)", {"unit": 365}),
    (r"son\s+çeyrek|son\s+ceyrek|bu\s+çeyrek|bu\s+ceyrek", {"period": PERIOD_QUARTER}),
    (r"geçen\s+ay|gecen\s+ay|bu\s+ay\b|aylık\s+bazda|bu\s+ayın|bu\s+ayin", {"period": PERIOD_MONTH}),
    (r"geçen\s+hafta|gecen\s+hafta|bu\s+hafta", {"period": PERIOD_WEEK}),
    (r"\bbugün\b|\bbugun\b|\bdün\b|\bdun\b|son\s+24\s*saat", {"period": PERIOD_TODAY}),
)

#: Zaman ekseni kovası.
_BUCKET_RULES: Tuple[Tuple[str, str], ...] = (
    (r"saatlik|saat\s+bazında|saat\s+bazinda|saat\s+kırılımı", "saat"),
    (r"günlük|gunluk|gün\s+bazında|gun\s+bazinda", "gün"),
    (r"haftalık|haftalik|hafta\s+bazında|hafta\s+bazinda", "hafta"),
    (r"aylık|aylik|ay\s+bazında|ay\s+bazinda", "ay"),
)

#: Görselleştirme.
_CHART_RULES: Tuple[Tuple[str, str], ...] = (
    (r"yoğunluk|yogunluk|ısı\s*harita|isi\s*harita|heatmap", CHART_HEATMAP),
    (r"halka|donut|pasta|pie|dağılım\s*(grafi|halka)|dagilim\s*(grafi|halka)", CHART_DONUT),
    (r"çubuk|cubuk|karşılaştırma|karsilastirma|bar\s*grafi", CHART_BAR),
    (r"trend|çizgi|cizgi|line|seyri|seyir", CHART_LINE),
    (r"sadece\s+tablo|grafiksiz|tablo\s+olarak|yalnızca\s+tablo", CHART_TABLE),
)

#: Çıktı biçimi.
_XLSX_RE = re.compile(r"excel|xlsx|çalışma\s*kitab|calisma\s*kitab|tablo\s*dosya")
_WEB_RE = re.compile(r"tarayıcı|tarayici|web|link|bağlantı|baglanti|pano|sayfa\s*olarak|online")
_BOTH_RE = re.compile(r"ikisi(ni)?\s*(de|birden)?|her\s*ikisi|hem\s*excel|hem\s*de")

#: "X bazında", "X kırılımında", "X başına", "X'e göre" — kırılım adayları.
_DIMENSION_RES = (
    re.compile(r"([\wçğıöşüÇĞİÖŞÜ .]{2,40}?)\s*(?:bazında|bazinda|bazlı|bazli)"),
    re.compile(r"([\wçğıöşüÇĞİÖŞÜ .]{2,40}?)\s*kırılım(?:ında|ı|)"),
    re.compile(r"([\wçğıöşüÇĞİÖŞÜ .]{2,40}?)\s*(?:başına|basina)"),
    re.compile(r"([\wçğıöşüÇĞİÖŞÜ .]{2,40}?)['’]?\s*(?:e|a|ye|ya)\s+göre"),
)

#: Kırılım adayından atılan dolgu kelimeleri.
_DIMENSION_STOP = {
    "ve",
    "ile",
    "için",
    "icin",
    "raporu",
    "rapor",
    "analiz",
    "analizi",
    "olarak",
    "lütfen",
    "lutfen",
    "bana",
    "bir",
    "de",
    "da",
    "the",
}


@dataclass
class Intent:
    """Bir cümleden çıkarılanlar ve çıkarılamayanlar."""

    raw: str = ""
    spec: ReportSpec = field(default_factory=ReportSpec)
    #: Türkçe "şunu anladım" satırları.
    understood: List[str] = field(default_factory=list)
    #: Cümlede geçen ama veride KARŞILIĞI OLMAYAN terimler.
    unknown: List[str] = field(default_factory=list)
    #: Ham kırılım/metrik adayları — veri gelince bağlanır.
    dimension_terms: List[str] = field(default_factory=list)
    metric_terms: List[str] = field(default_factory=list)
    #: Veriye bağlanma yapıldı mı?
    grounded: bool = False

    @property
    def signals(self) -> int:
        """Cümlede kaç ayrı bilgi bulundu? Hızlı yolun eşiği budur."""
        return sum(
            1
            for present in (
                self.spec.has_period(),
                bool(self.spec.bucket),
                bool(self.dimension_terms or self.spec.dimensions),
                bool(self.metric_terms or self.spec.metrics),
                bool(self.spec.chart),
                bool(self.spec.formats),
            )
            if present
        )

    def understood_text(self) -> str:
        """Onay öncesi "şunu anladım" bloğu."""
        if not self.understood:
            return ""
        return "*Anladığım:*\n" + "\n".join(f"• {line}" for line in self.understood)


def looks_like_request(text: str) -> bool:
    """Bu cümle bir rapor siparişi mi, yoksa "merhaba" mı?

    Eşik iki sinyal: tek başına "excel" yazmak menüyü açar, "son 3 ay Excel"
    hızlı yola girer. Böylece tek kelimelik mesajlar yanlışlıkla yarım bir
    rapor tarifine dönüşmez.
    """
    intent = parse(text)
    return intent.signals >= 2


# --- birinci aşama: veri olmadan ---------------------------------------------


def parse(text: str) -> Intent:
    """Cümleyi veri olmadan çözebildiği kadar çözer."""
    raw = str(text or "").strip()
    intent = Intent(raw=raw, spec=ReportSpec(question=raw))
    if not raw:
        return intent

    residual = normalize(raw)

    residual = _read_period(residual, intent)
    residual = _read_bucket(residual, intent)
    _read_chart(residual, intent)
    _read_formats(residual, intent)
    intent.dimension_terms = _dimension_candidates(residual)
    intent.metric_terms = _metric_candidates(residual)

    if intent.dimension_terms:
        intent.understood.append("Kırılım: " + " × ".join(intent.dimension_terms))
    if intent.metric_terms:
        intent.understood.append("Metrikler: " + ", ".join(intent.metric_terms))
    return intent


def _read_period(text: str, intent: Intent) -> str:
    for pattern, rule in _PERIOD_RULES:
        match = re.search(pattern, text)
        if not match:
            continue
        if "unit" in rule:
            try:
                count = int(match.group(1))
            except (IndexError, ValueError):
                continue
            intent.spec.last_days = max(1, count) * int(rule["unit"])
        else:
            intent.spec.period = str(rule["period"])
        intent.understood.append(f"Dönem: {intent.spec.period_label()}")
        return _cut(text, match)
    return text


def _read_bucket(text: str, intent: Intent) -> str:
    for pattern, bucket in _BUCKET_RULES:
        match = re.search(pattern, text)
        if match:
            intent.spec.bucket = bucket
            intent.understood.append(f"Zaman ekseni: {bucket} bazında")
            return _cut(text, match)
    return text


def _read_chart(text: str, intent: Intent) -> None:
    for pattern, chart in _CHART_RULES:
        if re.search(pattern, text):
            intent.spec.chart = chart
            intent.understood.append(f"Görselleştirme: {intent.spec.chart_label()}")
            return


def _read_formats(text: str, intent: Intent) -> None:
    wants_xlsx = bool(_XLSX_RE.search(text))
    wants_web = bool(_WEB_RE.search(text))
    if _BOTH_RE.search(text):
        wants_xlsx = wants_web = True
    formats = [f for f, wanted in ((FORMAT_XLSX, wants_xlsx), (FORMAT_WEB, wants_web)) if wanted]
    if formats:
        intent.spec.formats = formats
        intent.understood.append(f"Format: {intent.spec.format_label()}")


def _cut(text: str, match: "re.Match[str]") -> str:
    """Eşleşen ifadeyi metinden çıkarır.

    Gerekli, çünkü "son 3 ay" içindeki "ay" kelimesi kırılım tarayıcısına
    kalırsa "Ay" diye bir eksen uydurulur. Dönem okunduktan sonra o parça
    cümleden düşer.
    """
    return (text[: match.start()] + " " + text[match.end() :]).strip()


def _dimension_candidates(text: str) -> List[str]:
    found: List[str] = []
    for pattern in _DIMENSION_RES:
        for match in pattern.finditer(text):
            term = _clean_term(match.group(1))
            if term and term not in found:
                found.append(term)
    return found


def _clean_term(raw: str) -> str:
    """Yakalanan kırılım adayını temizler: dolgu kelimeleri ve bağlaçlar gider."""
    words = [w for w in re.split(r"[\s,]+", str(raw or "").strip()) if w]
    while words and words[0] in _DIMENSION_STOP:
        words.pop(0)
    # Yalnızca SON isim öbeği alınır: "raporu vardiya bazında" -> "vardiya".
    while len(words) > 2:
        words.pop(0)
    while words and words[-1] in _DIMENSION_STOP:
        words.pop()
    return " ".join(words).strip(" .,:;")


def _metric_candidates(text: str) -> List[str]:
    """Cümlede geçen gösterge ANAHTARLARI, geçtikleri sıraya göre.

    Profilleyicinin kendi kalıplarını kullanır — yani sohbet katmanı ikinci bir
    gösterge sözlüğü tutmaz; veri okuyucusu neyi SLA sayıyorsa burada da o SLA'dır.
    """
    hits: List[Tuple[int, str]] = []
    for pattern, hint in METRIC_PATTERNS:
        if hint.dimension:
            continue
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            hits.append((match.start(), hint.key))
    ordered: List[str] = []
    for _, key in sorted(hits):
        if key not in ordered:
            ordered.append(key)
    return ordered


# --- ikinci aşama: veriye bağlama --------------------------------------------


def ground(intent: Intent, dataset: Dataset) -> Intent:
    """Adayları GERÇEK sütunlara bağlar; bağlanamayanları not eder.

    Bu, "veride olmayan bir kırılımı uydurma" kuralının uygulandığı yerdir.
    """
    dimensions, missing_dims = match_terms(dataset, intent.dimension_terms)
    metrics, missing_metrics = match_terms(dataset, intent.metric_terms)

    # Cümlede sütun ADI birebir geçiyorsa o da alınır ("Terk Edilen Çağrı").
    for name in mentioned_columns(dataset, intent.raw, numeric=False):
        if name not in dimensions:
            dimensions.append(name)
    for name in mentioned_columns(dataset, intent.raw, numeric=True):
        if name not in metrics:
            metrics.append(name)

    intent.spec.dimensions = dimensions
    intent.spec.metrics = metrics
    intent.unknown = [*missing_dims, *missing_metrics]
    intent.grounded = True

    intent.understood = [
        line
        for line in intent.understood
        if not line.startswith("Kırılım:") and not line.startswith("Metrikler:")
    ]
    if dimensions:
        intent.understood.append("Kırılım: " + " × ".join(dimensions))
    if metrics:
        intent.understood.append("Metrikler: " + ", ".join(metrics))
    return intent


def unknown_note(intent: Intent, dataset: Optional[Dataset] = None) -> str:
    """Bağlanamayan terimler için Türkçe uyarı — ve veride NE OLDUĞU."""
    if not intent.unknown:
        return ""
    terms = ", ".join(f"“{t}”" for t in intent.unknown)
    note = f"Veride {terms} diye bir sütun bulamadım, bu yüzden onu yok saydım."
    if dataset is not None:
        available = [c.name for c in dataset.columns][:10]
        if available:
            note += " Veride şunlar var: " + ", ".join(available) + "."
    return note


def missing_steps(spec_obj: ReportSpec) -> List[str]:
    """Hızlı yolun ardından hâlâ SORULMASI gereken adımlar."""
    missing: List[str] = []
    if not spec_obj.has_source():
        missing.append("kaynak")
    if not spec_obj.has_period():
        missing.append("donem")
    if not spec_obj.formats:
        missing.append("format")
    return missing


__all__ = [
    "Intent",
    "ground",
    "looks_like_request",
    "missing_steps",
    "parse",
    "unknown_note",
]
