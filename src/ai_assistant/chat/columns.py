"""Menü seçeneklerini GERÇEK VERİDEN türetir.

Kırılım ve metrik listeleri sabit değildir; olamaz da. Kullanıcının seçtiği
dosyada "Vardiya" sütunu yoksa menüde "Vardiya" yazmamalıdır — yoksa kullanıcı
var olmayan bir kırılımı seçer ve rapor sessizce başka bir şey üretir.

Bu modül profilleyicinin (:mod:`ai_assistant.analysis.dataset`) çıkardığı sütun
profillerini menü seçeneklerine çevirir ve serbest metinden gelen terimleri
(hızlı yol) gerçek sütunlara bağlar. Bağlanamayan terim UYDURULMAZ, çağırana
"bunu bulamadım" diye geri verilir.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from ..analysis.analyzer import resolve_columns
from ..analysis.dataset import Dataset
from .menu import Option, normalize

#: Menüde en çok bu kadar kırılım/metrik gösterilir.
MAX_OPTIONS = 12


def _dimension_hint(column: Any) -> str:
    parts = [column.kind_label]
    if column.distinct:
        parts.append(f"{column.distinct} farklı değer")
    return " · ".join(parts)


def _metric_hint(column: Any) -> str:
    parts = []
    if column.metric_label:
        parts.append("tanınan gösterge")
    if column.unit:
        parts.append(f"birim {column.unit}")
    if column.mean is not None:
        parts.append(f"ortalama {column.mean:,.1f}".replace(",", "."))
    return " · ".join(parts)


def dimension_options(dataset: Dataset, limit: int = MAX_OPTIONS) -> List[Option]:
    """Kırılım ekseni olabilecek SÜTUNLAR — ada göre değil profile göre.

    Tarih sütunları da eklenir: "tarih bazında" meşru bir kırılımdır, ama
    profilleyici onları ``is_groupable`` saymaz (sonsuz kardinalite).
    """
    seen: set = set()
    options: List[Option] = []
    for column in dataset.dimension_columns():
        if column.name in seen:
            continue
        seen.add(column.name)
        options.append(
            Option(value=column.name, label=column.name, hint=_dimension_hint(column))
        )
    for column in dataset.date_columns():
        if column.name in seen or len(options) >= limit:
            continue
        seen.add(column.name)
        options.append(
            Option(
                value=column.name,
                label=column.name,
                hint=f"tarih · {column.granularity or 'gün'} bazında",
            )
        )
    return options[:limit]


def metric_options(dataset: Dataset, limit: int = MAX_OPTIONS) -> List[Option]:
    """Ölçüt olabilecek SAYISAL sütunlar; tanınan göstergeler önce.

    Sıra kasıtlı: SLA, AHT, terk oranı gibi gerçekten saptanmış göstergeler
    listenin başında olur, geri kalan sayısal sütunlar arkalarından gelir.
    """
    options: List[Option] = []
    seen: set = set()
    for column in dataset.metric_columns():
        seen.add(column.name)
        label = column.metric_label or column.name
        options.append(
            Option(
                value=column.name,
                label=f"{column.name} — {label}" if label != column.name else column.name,
                hint=_metric_hint(column),
            )
        )
    for column in dataset.numeric_columns():
        if column.name in seen:
            continue
        seen.add(column.name)
        options.append(Option(value=column.name, label=column.name, hint=_metric_hint(column)))
    return options[:limit]


def options_as_dicts(options: Sequence[Option]) -> List[Dict[str, str]]:
    """Seçenekleri oturum dosyasına yazılabilir hâle getirir."""
    return [{"value": o.value, "label": o.label, "hint": o.hint} for o in options]


def options_from_dicts(payload: Any) -> List[Option]:
    """Oturum dosyasından okunan seçenekleri geri kurar."""
    out: List[Option] = []
    for item in payload or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "")
        if not value:
            continue
        out.append(
            Option(
                value=value,
                label=str(item.get("label") or value),
                hint=str(item.get("hint") or ""),
            )
        )
    return out


def match_terms(dataset: Dataset, terms: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Serbest metinden gelen terimleri gerçek sütun adlarına bağlar.

    ``(bulunanlar, bulunamayanlar)`` döner. Bulunamayan terim SESSİZCE
    ATILMAZ; çağıran onu kullanıcıya sorar.
    """
    found: List[str] = []
    missing: List[str] = []
    for term in terms:
        text = str(term or "").strip()
        if not text:
            continue
        resolved = resolve_columns(dataset, [text])
        if resolved:
            name = resolved[0].name
            if name not in found:
                found.append(name)
        elif text not in missing:
            missing.append(text)
    return found, missing


def mentioned_columns(dataset: Dataset, sentence: str, numeric: bool) -> List[str]:
    """Cümlede ADI GEÇEN sütunlar — sütun adı üzerinden birebir arama.

    ``numeric=True`` ölçüt adaylarını, ``False`` kırılım adaylarını verir.
    Cümlede geçmeyen hiçbir sütun dönmez; uydurma yok.
    """
    text = normalize(sentence)
    pool = dataset.numeric_columns() if numeric else dataset.dimension_columns()
    hits: List[str] = []
    for column in pool:
        name = normalize(column.name)
        if len(name) >= 3 and name in text and column.name not in hits:
            hits.append(column.name)
    return hits


__all__ = [
    "MAX_OPTIONS",
    "dimension_options",
    "match_terms",
    "mentioned_columns",
    "metric_options",
    "options_as_dicts",
    "options_from_dicts",
]
