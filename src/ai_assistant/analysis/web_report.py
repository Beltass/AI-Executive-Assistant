"""Tarayıcıda okunan etkileşimli rapor — MEVCUT okuma görünümünün şemasıyla.

Burada yeni bir arayüz İCAT EDİLMEZ. Çıktı, :mod:`ai_assistant.reports` içindeki
yapısal belge şemasının (``schema_version = 2``) birebir kendisidir::

    { headline, key_metrics, sections[{title, body, table, chart}],
      action_items, sources, meta }

Bunun bedava getirdikleri: ``frontend/app.js``'in okuma görünümü, metrik şeridi,
sıralanabilir ``dataTable``, SVG grafik oluşturucuları, mobil düzen ve
``styles.css``'teki yazdırma/PDF stil sayfası. Rapor, danışman raporlarıyla aynı
sayfada, aynı tipografiyle açılır.

Grafik tanımları **var olan** :file:`frontend/charts.js` oluşturucularını
hedefler — ``line``, ``bar``, ``donut``, ``sparkline``, ``heatmap`` — çünkü
``app.js`` yalnızca bu beşini tanır (``mountSectionChart``).

MEVCUT ÖN YÜZÜN SINIRLARI (uydurmak yerine yazıyoruz):

* **Sıralama VAR.** ``dataTable`` her sütun başlığını sıralama düğmesi yapar ve
  ``table.sort = {key, dir}`` ilk sıralamayı belirler. Rapordaki her tablo
  anlamlı bir ön sıralamayla gelir; kullanıcı istediği sütuna tıklayıp kırılımı
  kendi sorusuna göre çevirebilir.
* **Süzgeç YOK.** Ön yüzde bölüm tablosuna bağlı bir filtre/arama kutusu ya da
  bir "drill-down" olayı bulunmuyor. Bu yüzden süzgeç, RAPOR ÜRETİM anında
  uygulanır (:class:`~ai_assistant.analysis.analyzer.AnalysisRequest`) ve hangi
  süzgecin uygulandığı belgenin başında yazar. İnteraktif süzgeç istenirse
  ``app.js`` + ``charts.js`` tarafına gerçek bir kontrol eklenmelidir; paralel
  bir oluşturucu yazmak yerine bu boşluk burada kayıtlıdır.
* ``type: "pct"`` hücreleri mini çubuk çizer, ``type: "trend"`` ok + renk
  gösterir — ikisi de kullanılıyor. ``column.format`` bir JS FONKSİYONU olduğu
  için JSON'dan geçemez; bu yüzden süre ölçütleri **dakikaya** çevrilip birim
  sütun başlığına yazılır (sıralanabilirlik korunur).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .. import reports
from ..status_report import ISTANBUL
from .analyzer import (
    AGG_LABELS,
    AnalysisResult,
    Finding,
    PivotTable,
    TimeSeries,
    TONE_BAD,
    TONE_GOOD,
    TONE_WARN,
    format_number,
    format_value,
)
from .dataset import Dataset

logger = logging.getLogger(__name__)

#: Belgenin varsayılan kimliği. Dosya adı ve ``#/rapor/<gün>/<id>`` rotası bu.
DEFAULT_REPORT_ID = "veri_analizi"
DEFAULT_REPORT_NAME = "Veri Analizi Raporu"
DEFAULT_EMOJI = "📊"
DEFAULT_CATEGORY = "Operasyon"

#: Bir bölüm tablosunda taşınan en fazla satır (JSON boyutu ve okunabilirlik).
MAX_TABLE_ROWS = 40

#: Grafiğe giren en fazla kategori.
MAX_CHART_CATEGORIES = 12

TONE_BADGE = {
    TONE_GOOD: {"tone": "ok", "icon": "✅", "label": "İyi"},
    TONE_WARN: {"tone": "warn", "icon": "⚠️", "label": "Dikkat"},
    TONE_BAD: {"tone": "bad", "icon": "⛔", "label": "Kritik"},
}


# --- yardımcılar -------------------------------------------------------------


def _series_color(index: int) -> str:
    return f"var(--series-{(index % 8) + 1})"


def _measure_column(measure: Any) -> Dict[str, Any]:
    """Bir ölçütü ``dataTable`` sütun tanımına çevirir.

    Süre (``sn``) ölçütleri DAKİKAYA çevrilir: ön yüzün sütun biçimleyicisi bir
    JS fonksiyonu olduğu için JSON'dan geçemiyor, ham saniye ise ("295") bir
    yöneticiye hiçbir şey anlatmıyor.
    """
    unit = measure.unit
    label = measure.title()
    if unit == "%":
        return {
            "key": measure.key,
            "label": label,
            "type": "pct",
            "digits": 1,
            "barMax": 100,
        }
    if unit == "sn":
        return {
            "key": measure.key,
            "label": f"{label} — dk",
            "type": "num",
            "digits": 1,
        }
    return {"key": measure.key, "label": label, "type": "num", "digits": 0}


def _measure_value(measure: Any, value: Any) -> Any:
    if value is None:
        return None
    if measure.unit == "sn":
        return round(float(value) / 60.0, 2)
    return round(float(value), 2) if isinstance(value, (int, float)) else value


def pivot_table_spec(pivot: PivotTable, limit: int = MAX_TABLE_ROWS) -> Dict[str, Any]:
    """Bir kırılımı, ön yüzün sıralanabilir tablo tanımına çevirir."""
    columns: List[Dict[str, Any]] = [
        {"key": dimension, "label": dimension, "type": "text"}
        for dimension in pivot.dimensions
    ]
    columns += [_measure_column(measure) for measure in pivot.measures]

    rows: List[Dict[str, Any]] = []
    for entry in pivot.rows[:limit]:
        row: Dict[str, Any] = {
            dimension: entry.get(dimension, "") for dimension in pivot.dimensions
        }
        for measure in pivot.measures:
            row[measure.key] = _measure_value(measure, entry.get(measure.key))
        rows.append(row)

    if pivot.totals and rows:
        total_row: Dict[str, Any] = {}
        for index, dimension in enumerate(pivot.dimensions):
            total_row[dimension] = "TOPLAM" if index == 0 else ""
        for measure in pivot.measures:
            total_row[measure.key] = _measure_value(
                measure, pivot.totals.get(measure.key)
            )
        rows.append(total_row)

    note = pivot.note or ""
    if pivot.truncated:
        note = (note + " ").strip()
    return {
        "title": pivot.title,
        "columns": columns,
        "rows": rows,
        "caption": pivot.title,
        "note": note or None,
        # Ön sıralama: en büyük ölçütten başla — "kim en çok / en yüksek" sorusu
        # rapora bakan kişinin ilk sorusudur. Başlığa tıklayınca değişir.
        "sort": (
            {"key": pivot.measures[0].key, "dir": "desc"} if pivot.measures else None
        ),
    }


def pivot_chart_spec(
    pivot: PivotTable, chart_type: str = ""
) -> Optional[Dict[str, Any]]:
    """Kırılımın grafiği: az dilim varsa halka, çoksa yatay çubuk."""
    if not pivot.rows or not pivot.measures:
        return None
    measure = pivot.measures[0]
    dimension = pivot.dimensions[0]
    rows = [
        row
        for row in pivot.rows[:MAX_CHART_CATEGORIES]
        if isinstance(row.get(measure.key), (int, float))
    ]
    if not rows:
        return None

    kind = (chart_type or "").lower()
    if kind not in ("bar", "donut", "line", "heatmap"):
        kind = "donut" if (measure.agg == "sum" and len(rows) <= 6) else "bar"

    if kind == "donut":
        return {
            "type": "donut",
            "title": f"{dimension} bazında {measure.title()}",
            "data": [
                {
                    "name": str(row.get(dimension, "—")),
                    "value": round(float(row[measure.key]), 2),
                    "color": _series_color(index),
                }
                for index, row in enumerate(rows)
            ],
            "options": {
                "centerLabel": measure.title(),
                "unit": measure.unit if measure.unit != "sn" else "sn",
                "legendLabel": f"{dimension} dağılımı",
            },
        }

    return {
        "type": "bar",
        "title": f"{dimension} bazında {measure.title()}",
        "data": [
            {
                "label": str(row.get(dimension, "—")),
                "value": round(float(row[measure.key]), 2),
                "color": _series_color(index),
            }
            for index, row in enumerate(rows)
        ],
        "options": {
            "unit": measure.unit,
            "aria": f"{dimension} bazında {measure.title()}",
        },
    }


def series_chart_spec(
    series: TimeSeries, chart_type: str = ""
) -> Optional[Dict[str, Any]]:
    """Zaman serisinin çizgi grafiği: değer + hareketli ortalama."""
    points = [p for p in series.points if p.value is not None]
    if len(points) < 2:
        return None
    if (chart_type or "").lower() == "bar":
        return {
            "type": "bar",
            "title": series.title,
            "data": [
                {"label": p.short or p.label, "value": round(float(p.value), 2)}
                for p in points
            ],
            "options": {"orientation": "vertical", "unit": series.unit},
        }

    data: List[Dict[str, Any]] = [
        {
            "name": series.title,
            "color": _series_color(0),
            "points": [
                {"value": round(float(p.value), 2), "label": p.label, "short": p.short}
                for p in points
            ],
        }
    ]
    moving = [p for p in points if p.moving is not None]
    if len(moving) >= 3:
        data.append(
            {
                "name": "Hareketli ortalama (3 dönem)",
                "color": "var(--neutral)",
                "points": [
                    {
                        "value": round(float(p.moving), 2),
                        "label": p.label,
                        "short": p.short,
                    }
                    for p in moving
                ],
            }
        )
    return {
        "type": "line",
        "title": series.title,
        "data": data,
        "options": {"unit": series.unit, "area": len(data) == 1, "aria": series.title},
        "caption": f"{series.period.capitalize()} bazında {len(points)} dönem.",
    }


def series_table_spec(
    series: TimeSeries, limit: int = MAX_TABLE_ROWS
) -> Dict[str, Any]:
    """Serinin sayısal karşılığı — grafiğin yanında her zaman tablo da olur."""
    unit_suffix = " — dk" if series.unit == "sn" else ""
    columns = [
        {"key": "period", "label": "Dönem", "type": "text"},
        {"key": "value", "label": f"Değer{unit_suffix}", "type": "num", "digits": 1},
        {
            "key": "delta",
            "label": "Fark",
            "type": "trend",
            "digits": 1,
            "betterWhen": series.better or "up",
        },
        {
            "key": "moving",
            "label": f"Hareketli ort.{unit_suffix}",
            "type": "num",
            "digits": 1,
        },
    ]

    def scale(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return round(value / 60.0, 2) if series.unit == "sn" else round(value, 2)

    rows = [
        {
            "period": point.label,
            "value": scale(point.value),
            "delta": scale(point.delta),
            "moving": scale(point.moving),
        }
        for point in series.points[-limit:]
    ]
    return {
        "title": f"{series.title} — dönemsel tablo",
        "columns": columns,
        "rows": rows,
        "caption": series.title,
        "note": series.note or None,
        "sort": {"key": "period", "dir": "asc"},
    }


def findings_table_spec(findings: Sequence[Finding]) -> Dict[str, Any]:
    """KPI listesi: değer, taban, fark ve durum rozeti."""
    columns = [
        {"key": "metric", "label": "Gösterge", "type": "text"},
        {"key": "value", "label": "Değer", "type": "text", "align": "right"},
        {"key": "baseline", "label": "Karşılaştırma", "type": "text"},
        {"key": "status", "label": "Durum", "type": "badge", "sortable": False},
    ]
    rows = []
    for finding in findings:
        rows.append(
            {
                "metric": finding.metric,
                "value": finding.display,
                "baseline": (
                    f"{finding.baseline_label} ({format_value(finding.baseline, finding.unit)})"
                    if finding.baseline is not None
                    else "—"
                ),
                "status": TONE_BADGE.get(
                    finding.tone, {"tone": "info", "icon": "•", "label": "Bilgi"}
                ),
            }
        )
    return {
        "title": "Gösterge tablosu",
        "columns": columns,
        "rows": rows,
        "caption": "Öne çıkan göstergeler",
    }


def profile_table_spec(dataset: Dataset) -> Dict[str, Any]:
    """Veri kalitesi tablosu — raporun dayandığı zeminin şeffaf hali."""
    columns = [
        {"key": "column", "label": "Sütun", "type": "text"},
        {"key": "kind", "label": "Tip", "type": "text"},
        {"key": "filled", "label": "Dolu kayıt", "type": "num", "digits": 0},
        {
            "key": "null_rate",
            "label": "Boşluk",
            "type": "pct",
            "digits": 1,
            "barMax": 100,
        },
        {"key": "distinct", "label": "Benzersiz", "type": "num", "digits": 0},
        {"key": "summary", "label": "Özet", "type": "text", "sortable": False},
    ]
    rows = []
    for profile in dataset.columns:
        if profile.is_numeric:
            summary = (
                f"ort. {format_value(profile.mean, profile.unit)} · "
                f"medyan {format_value(profile.median, profile.unit)} · "
                f"aralık {format_value(profile.minimum, profile.unit)}–"
                f"{format_value(profile.maximum, profile.unit)}"
            )
        elif profile.is_date:
            summary = (
                f"{profile.first.strftime('%d.%m.%Y') if profile.first else '—'} – "
                f"{profile.last.strftime('%d.%m.%Y') if profile.last else '—'} "
                f"({profile.granularity})"
            )
        elif profile.top_values:
            summary = "en sık: " + ", ".join(
                f"{v} ({c})" for v, c in profile.top_values[:3]
            )
        else:
            summary = "—"
        rows.append(
            {
                "column": profile.name
                + (f" · {profile.metric_label}" if profile.metric_label else ""),
                "kind": profile.kind_label,
                "filled": profile.count,
                "null_rate": round(profile.null_rate * 100, 1),
                "distinct": profile.distinct,
                "summary": summary,
            }
        )
    return {
        "title": "Veri profili",
        "columns": columns,
        "rows": rows,
        "caption": "Sütun bazında veri kalitesi",
        "note": "Boşluk oranı yüksek bir sütun, o sütuna dayanan her bulguyu zayıflatır.",
    }


# --- belge ------------------------------------------------------------------


def _key_metrics(result: AnalysisResult) -> List[reports.KeyMetric]:
    metrics: List[reports.KeyMetric] = []
    for finding in result.key_findings(reports.MAX_KEY_METRICS):
        note = ""
        if finding.baseline is not None and finding.delta is not None:
            note = f"{finding.baseline_label} {format_value(finding.delta, finding.unit)} fark"
        metrics.append(
            reports.KeyMetric(
                label=finding.metric,
                # Değer ZATEN biçimli (birim, yüzde, dakika:saniye) — ön yüz
                # bu dizeyi olduğu gibi basar, yeniden noktalamaz.
                value=finding.display,
                unit="",
                trend=(
                    finding.direction
                    if finding.direction in ("up", "down", "flat")
                    else ""
                ),
                note=note,
                spark=[float(v) for v in finding.spark[-12:]],
            )
        )
    return metrics


def _action_items(result: AnalysisResult) -> List[reports.ActionItem]:
    """Bulgulardan somut Türkçe aksiyonlar. Sorun yoksa aksiyon da yoktur."""
    actions: List[reports.ActionItem] = []
    recipes = {
        "sla": "Servis seviyesi hedefin altında: en düşük SLA'lı saat dilimleri için vardiya "
        "takviyesi planla ve kuyruk önceliklerini gözden geçir.",
        "abandon_rate": "Terk oranı eşiğin üzerinde: kuyrukta bekleme anonsunu, geri arama "
        "seçeneğini ve yoğun saat kadrosunu ele al.",
        "aht": "AHT uzuyor: en uzun görüşme konularını ayıkla, bilgi tabanını ve çağrı "
        "yönlendirme akışını bu konular için güncelle.",
        "occupancy": "Doluluk sağlıklı bandın dışında: mola/vardiya planını ve kadro "
        "büyüklüğünü yeniden hesapla.",
        "csat": "Memnuniyet geriliyor: düşük puan alan çağrıları dinleyip koçluk konularını çıkar.",
        "asa": "Bekleme süresi yükseliyor: yoğun saatlerde kuyruk devri ve ek kaynak seçeneğini değerlendir.",
        "fcr": "İlk temasta çözüm düşük: tekrar eden çağrı nedenlerini sınıflandırıp yetki "
        "sınırlarını genişlet.",
    }
    for finding in result.findings:
        if finding.tone not in (TONE_BAD, TONE_WARN):
            continue
        text = recipes.get(finding.key)
        if not text:
            text = (
                f"{finding.metric} istenmeyen yönde ({finding.display}). "
                f"Nedenini kırılım tablolarından ayıkla ve sorumlu ata."
            )
        actions.append(reports.ActionItem(text=text, owner="Operasyon"))

    for report in result.outliers:
        if report.count and report.examples:
            example = report.examples[0]
            where = f" ({example.context})" if example.context else ""
            actions.append(
                reports.ActionItem(
                    text=(
                        f"{report.column} için {report.count} aykırı ölçümü tek tek doğrula; "
                        f"en uç kayıt {format_value(example.value, report.unit)}{where}. "
                        f"Veri hatası mı, gerçek bir operasyon olayı mı ayır."
                    ),
                    owner="Raporlama",
                )
            )
            break
    return actions[: reports.MAX_ACTION_ITEMS]


def _summary_body(result: AnalysisResult) -> str:
    """Yönetici özeti: ne bakıldı, ne bulundu — madde madde."""
    dataset = result.dataset
    lines: List[str] = []
    request = result.request
    if request is not None and request.question:
        lines.append(f"**Sorulan soru:** {request.question}")
        lines.append("")
    lines.append(
        f"**Kapsam:** {dataset.summary_tr()} · **Kaynak:** {dataset.source or dataset.name}"
    )
    if request is not None:
        detail = request.summary_tr()
        if detail:
            lines.append("")
            lines.append(f"**Analiz tarifi:** {detail}")
    date_columns = dataset.date_columns()
    if date_columns and date_columns[0].first and date_columns[0].last:
        lines.append("")
        lines.append(
            f"**Dönem:** {date_columns[0].first.strftime('%d.%m.%Y')} – "
            f"{date_columns[0].last.strftime('%d.%m.%Y')} "
            f"({date_columns[0].granularity} bazında)"
        )
    if result.findings:
        lines.append("")
        for finding in result.findings:
            lines.append(f"- {finding.interpretation}")
    if result.notes:
        lines.append("")
        for note in result.notes[:6]:
            lines.append(f"> {note}")
    return "\n".join(lines)


def changes_section(change_notes: Sequence[str]) -> Optional[reports.Section]:
    """Canlı senkronun "SON SÜRÜMDEN BU YANA" bölümü.

    :func:`ai_assistant.analysis.live_sync.sync_source` her yeni sürümde neyin
    değiştiğini (kaç satır eklendi, hangi gösterge nereye gitti) hesaplar; rapor
    bunu KENDİ İÇİNDE, en başta söylemezse kullanıcı iki dosyayı yan yana
    koyup karşılaştırmak zorunda kalır.
    """
    lines = [str(note).strip() for note in (change_notes or []) if str(note).strip()]
    if not lines:
        return None
    return reports.Section(
        title="Son sürümden bu yana",
        body="\n".join(f"- {line}" for line in lines),
    )


def build_sections(
    result: AnalysisResult,
    change_notes: Optional[Sequence[str]] = None,
) -> List[reports.Section]:
    """Belgenin gövdesi: değişiklikler, özet, göstergeler, kırılımlar, trend, aykırılar, profil."""
    request = result.request
    chart_type = (request.chart_type if request else "") or ""
    sections: List[reports.Section] = []
    changes = changes_section(change_notes or [])
    if changes is not None:
        sections.append(changes)
    sections.append(reports.Section(title="Yönetici özeti", body=_summary_body(result)))

    if result.findings:
        sections.append(
            reports.Section(
                title="Öne çıkan göstergeler",
                body="Her satır bir gösterge: bulunan değer, karşılaştırıldığı taban ve durum.",
                table=findings_table_spec(result.findings),
            )
        )

    for index, pivot in enumerate(result.pivots):
        body_lines = []
        if pivot.rows and pivot.measures:
            measure = pivot.measures[0]
            best = pivot.rows[0]
            dimension = pivot.dimensions[0]
            body_lines.append(
                f"En yüksek {measure.title().lower()}: **{best.get(dimension)}** "
                f"({format_value(best.get(measure.key), measure.unit)})."
            )
            if len(pivot.rows) > 1:
                worst = pivot.rows[-1]
                body_lines.append(
                    f"En düşük: **{worst.get(dimension)}** "
                    f"({format_value(worst.get(measure.key), measure.unit)})."
                )
            body_lines.append(
                "Sütun başlığına dokunarak tabloyu istediğin ölçüte göre sıralayabilirsin."
            )
        sections.append(
            reports.Section(
                title=pivot.title,
                body=" ".join(body_lines),
                table=pivot_table_spec(pivot),
                # Halka yalnızca İLK kırılımda: arka arkaya üç halka aynı
                # soruyu üç kez sorar, çubuk ise karşılaştırmayı kolaylaştırır.
                chart=pivot_chart_spec(
                    pivot, chart_type or ("" if index == 0 else "bar")
                ),
            )
        )

    for series in result.series:
        spec = series_chart_spec(series, chart_type)
        trend_word = {"up": "yükseliş", "down": "düşüş", "flat": "yatay seyir"}.get(
            series.trend, ""
        )
        body = f"{series.period.capitalize()} bazında {len(series.points)} dönem"
        if series.change_pct is not None and trend_word:
            body += f"; dönemin ikinci yarısı ilk yarısına göre %{format_number(abs(series.change_pct), 1)} {trend_word} gösteriyor."
        else:
            body += "."
        sections.append(
            reports.Section(
                title=series.title,
                body=body,
                table=series_table_spec(series),
                chart=spec,
            )
        )

    if result.outliers:
        body = "\n\n".join(
            report.interpretation for report in result.outliers if report.interpretation
        )
        columns = [
            {"key": "column", "label": "Ölçüt", "type": "text"},
            {"key": "count", "label": "Aykırı adet", "type": "num", "digits": 0},
            {"key": "rate", "label": "Oran", "type": "pct", "digits": 1, "barMax": 100},
            {"key": "band", "label": "Normal bant", "type": "text", "sortable": False},
        ]
        rows = [
            {
                "column": report.column,
                "count": report.count,
                "rate": round(report.rate * 100, 1),
                "band": f"{format_value(report.lower, report.unit)} – {format_value(report.upper, report.unit)}",
            }
            for report in result.outliers
        ]
        sections.append(
            reports.Section(
                title="Aykırı değerler",
                body=body,
                table={
                    "title": "IQR bandı dışındaki ölçümler",
                    "columns": columns,
                    "rows": rows,
                    "caption": "Aykırı değer özeti",
                    "note": "Yöntem: Q1 − 1,5×IQR ile Q3 + 1,5×IQR bandının dışı.",
                    "sort": {"key": "count", "dir": "desc"},
                },
            )
        )

    if result.correlations:
        sections.append(
            reports.Section(
                title="Göstergeler arası ilişkiler",
                body="\n\n".join(item.interpretation for item in result.correlations),
                table={
                    "title": "Korelasyon tablosu",
                    "columns": [
                        {"key": "left", "label": "Gösterge 1", "type": "text"},
                        {"key": "right", "label": "Gösterge 2", "type": "text"},
                        {"key": "r", "label": "r", "type": "num", "digits": 2},
                        {"key": "strength", "label": "Güç", "type": "text"},
                    ],
                    "rows": [
                        {
                            "left": item.left,
                            "right": item.right,
                            "r": round(item.r, 2),
                            "strength": item.strength,
                        }
                        for item in result.correlations
                    ],
                    "caption": "Pearson korelasyon katsayıları",
                    "note": "İlişki nedensellik değildir; ilişki bir hipotezin başlangıcıdır.",
                    "sort": {"key": "r", "dir": "desc"},
                },
            )
        )

    sections.append(
        reports.Section(
            title="Veri profili",
            body="Rapor bu sütunlara dayanıyor. Boşluk oranı yüksek bir sütun, ona dayanan bulguyu da zayıflatır.",
            table=profile_table_spec(result.dataset),
        )
    )
    return sections


def build_document(
    result: AnalysisResult,
    report_id: str = DEFAULT_REPORT_ID,
    name: str = "",
    day: str = "",
    moment: Optional[datetime] = None,
    sources: Optional[Sequence[reports.Source]] = None,
    xlsx_path: str = "",
    change_notes: Optional[Sequence[str]] = None,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> reports.PublishedReport:
    """Analiz sonucunu yayımlanabilir bir :class:`reports.PublishedReport` yapar.

    ``change_notes`` verilirse (canlı senkron bunu verir) belge "Son sürümden bu
    yana" bölümüyle AÇILIR.
    """
    when = moment or datetime.now(ISTANBUL)
    when_local = when.astimezone(ISTANBUL) if when.tzinfo else when
    date = day or when_local.strftime("%Y-%m-%d")

    sections = build_sections(result, change_notes=change_notes)
    metrics = _key_metrics(result)
    actions = _action_items(result)

    dataset = result.dataset
    meta: Dict[str, Any] = {
        "advisor": report_id,
        "advisor_name": name or DEFAULT_REPORT_NAME,
        "category": DEFAULT_CATEGORY,
        "generated_at": when.isoformat(timespec="seconds"),
        "generated_at_istanbul": when_local.strftime("%d.%m.%Y %H:%M"),
        "source": dataset.source or dataset.name,
        "source_kind": dataset.source_kind,
        "source_id": dataset.source_id,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "is_call_center": result.is_call_center,
        "content_hash": dataset.content_hash(),
        "analysis_notes": list(result.notes),
        "tokens": 0,
        "tokens_estimated": True,
    }
    if change_notes:
        meta["change_notes"] = [str(note) for note in change_notes]
    if result.request is not None:
        meta["request"] = result.request.as_dict()
    if xlsx_path:
        meta["xlsx"] = os.path.basename(xlsx_path)
        meta["xlsx_path"] = xlsx_path
    if extra_meta:
        meta.update(extra_meta)

    report = reports.PublishedReport(
        id=report_id,
        name=name or result.title or DEFAULT_REPORT_NAME,
        emoji=DEFAULT_EMOJI,
        category=DEFAULT_CATEGORY,
        date=date,
        headline=result.headline[: reports.MAX_HEADLINE_CHARS],
        excerpt="",
        words=0,
        read_minutes=1,
        generated_at=when.isoformat(timespec="seconds"),
        generated_at_istanbul=when_local.strftime("%d.%m.%Y %H:%M"),
        key_metrics=metrics,
        sections=sections,
        action_items=actions,
        sources=list(sources or []),
        meta=meta,
    )

    # ``markdown`` v1 okuyucular ve Drive/Slack önizlemesi içindir: yapısal
    # belgenin birebir Markdown karşılığı yazılır, böylece eski bir okuyucu da
    # boş sayfa değil tam raporu görür.
    report.markdown = reports.render_markdown_document(report)
    report.words = reports.word_count(report.markdown)
    report.read_minutes = reports.read_minutes(report.words)
    report.excerpt = _excerpt(result)
    report.meta["words"] = report.words
    report.meta["read_minutes"] = report.read_minutes
    return report


def _excerpt(result: AnalysisResult) -> str:
    parts = [f.interpretation for f in result.findings[:2] if f.interpretation]
    text = " ".join(parts) or result.headline
    text = " ".join(text.split())
    if len(text) <= reports.MAX_EXCERPT_CHARS:
        return text
    return text[: reports.MAX_EXCERPT_CHARS].rsplit(" ", 1)[0] + "…"


def document_json(report: reports.PublishedReport) -> str:
    return json.dumps(report.document(), ensure_ascii=False, indent=2)


def publish_document(
    report: reports.PublishedReport,
    root: str = "",
    moment: Optional[datetime] = None,
) -> str:
    """Belgeyi ``<root>/<gün>/<id>.json`` olarak yazar ve günün dizinini tazeler.

    Danışman raporlarıyla AYNI klasöre yazar, aynı indeks birleştirme kuralını
    kullanır (sabahki rapor öğleden sonraki koşuyla silinmez) ve aynı arşiv
    indeksini günceller — yani mevcut panoda kendiliğinden görünür.

    Asla istisna fırlatmaz; yazamazsa boş dize döner ve nedenini loglar.
    """
    when = moment or datetime.now(ISTANBUL)
    target = root or reports.reports_dir()
    directory = os.path.join(target, report.date)
    path = os.path.join(directory, f"{report.id}.json")
    try:
        reports._write_json(path, report.document())
        index_path = os.path.join(directory, "index.json")
        existing = reports._read_json(index_path)
        cards = reports._merge_cards(existing.get("reports"), [report])
        reports._write_json(
            index_path,
            {
                "schema_version": 1,
                "date": report.date,
                "generated_at": when.isoformat(timespec="seconds"),
                "generated_at_istanbul": (
                    when.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M")
                    if when.tzinfo
                    else when.strftime("%d.%m.%Y %H:%M")
                ),
                "mode": str(existing.get("mode") or ""),
                "mode_label": str(existing.get("mode_label") or ""),
                "count": len(cards),
                "reports": cards,
            },
        )
        reports._write_archive_index(target, when)
    except Exception as exc:
        logger.warning("analiz raporu yazılamadı (%s): %s", path, exc)
        return ""
    return path


def build_and_publish(
    result: AnalysisResult,
    report_id: str = DEFAULT_REPORT_ID,
    name: str = "",
    root: str = "",
    moment: Optional[datetime] = None,
    xlsx_path: str = "",
) -> Dict[str, Any]:
    """Tek çağrıda belge + yayın. Panodaki bağlantıyı da döner."""
    report = build_document(
        result, report_id=report_id, name=name, moment=moment, xlsx_path=xlsx_path
    )
    path = publish_document(report, root=root, moment=moment)
    return {"report": report, "path": path, "route": report.route}


__all__ = [
    "DEFAULT_CATEGORY",
    "DEFAULT_EMOJI",
    "DEFAULT_REPORT_ID",
    "DEFAULT_REPORT_NAME",
    "build_and_publish",
    "build_document",
    "build_sections",
    "changes_section",
    "document_json",
    "findings_table_spec",
    "pivot_chart_spec",
    "pivot_table_spec",
    "profile_table_spec",
    "publish_document",
    "series_chart_spec",
    "series_table_spec",
]
