"""Rapor üretim motoru — veri al, profille, analiz et, iki biçimde yayımla.

Bu paket "ham veriden profesyonel rapora" yolunu dört adıma böler:

1. :mod:`ai_assistant.analysis.dataset` — Excel / CSV / Google E-Tablo / yapıştırılmış
   metin okunur, her sütun profillenir (tip, boşluk oranı, dağılım) ve çağrı
   merkezi göstergeleri (AHT, SLA, terk oranı…) sütun adlarından tanınır.
2. :mod:`ai_assistant.analysis.analyzer` — kırılım (pivot) tabloları, zaman serisi,
   aykırı değer, korelasyon ve çağrı merkezine özel KPI'lar hesaplanır. Her bulgu
   Türkçe bir yorum cümlesi taşır.
3. :mod:`ai_assistant.analysis.excel_report` — gerçek bir ``.xlsx`` çalışma kitabı
   (yerel Excel grafikleri, koşullu biçimlendirme, donmuş başlıklar).
4. :mod:`ai_assistant.analysis.web_report` — mevcut okuma görünümünün yapısal rapor
   şemasına (``ai_assistant.reports``) uyan etkileşimli tarayıcı raporu.

:mod:`ai_assistant.analysis.live_sync` bir Drive e-tablosunu izler; satır
eklendiğinde analizi yeniden çalıştırır, iki çıktıyı da tazeler ve neyin
değiştiğini sürüm geçmişinde tutar.

MOTORUN TEK KURALI: hiçbir adım kullanıcıya traceback göstermez. Okunamayan
dosya, boş sayfa, tek sütunluk veri, eksik Google kimliği — hepsi
:class:`ai_assistant.analysis.dataset.DatasetError` üzerinden net bir Türkçe
cümleye dönüşür.

TİPİK AKIŞ — beş modülün de giriş noktası bu paketten doğrudan alınır::

    from ai_assistant.analysis import AnalysisRequest, analyze, build_workbook, load_any

    dataset = load_any("cagri_kayitlari.xlsx")
    result = analyze(dataset, AnalysisRequest(dimensions=["Takım"]))
    build_workbook(result, "rapor.xlsx")

Aşağıdaki ``__all__`` her modülün GERÇEK kamusal yüzeyidir, tamamı değil: ara
hesap yardımcıları (``pearson``, ``pivot_table_spec``, sayfa adı sabitleri…)
kasıtlı olarak dışarıda bırakıldı — onlara ihtiyaç duyan kod ilgili modülü tam
yoluyla içe aktarır.
"""

from __future__ import annotations

# 1. adım — veri alma ve profilleme.
from .dataset import (
    Dataset,
    DatasetError,
    ColumnProfile,
    load_any,
    load_csv,
    load_excel,
    load_google_sheet,
    load_text,
)

# 2. adım — analiz. `analyze` motorun kalbi; yanındaki tipler onun girdisi
# (istek/filtre) ve çıktısıdır (sonuç ve içindeki bulgu/ölçü/kırılım/seri
# kayıtları), yani raporu üreten kodun gerçekten elleyeceği şeyler.
from .analyzer import (
    AnalysisRequest,
    AnalysisResult,
    Filter,
    Finding,
    Measure,
    PivotTable,
    TimeSeries,
    analyze,
)

# 3. adım — Excel çıktısı. Modül openpyxl'i İÇE AKTARMA anında değil, yalnızca
# `build_workbook` çağrıldığında yükler; bu yüzden kütüphane eksik olsa bile bu
# paketi içe aktarmak güvenlidir ve hata kullanıcıya Türkçe DatasetError olarak
# ancak rapor istendiğinde ulaşır.
from .excel_report import build_workbook

# 4. adım — tarayıcı raporu.
from .web_report import build_and_publish, build_document, publish_document

# Canlı senkron — e-tabloyu izle, değiştiyse yeniden analiz et, geçmişi tut.
from .live_sync import (
    SyncResult,
    TrackedSource,
    Version,
    check_source,
    history,
    history_table_tr,
    sync_source,
)

__all__ = [
    # 1. dataset
    "ColumnProfile",
    "Dataset",
    "DatasetError",
    "load_any",
    "load_csv",
    "load_excel",
    "load_google_sheet",
    "load_text",
    # 2. analyzer
    "AnalysisRequest",
    "AnalysisResult",
    "Filter",
    "Finding",
    "Measure",
    "PivotTable",
    "TimeSeries",
    "analyze",
    # 3. excel_report
    "build_workbook",
    # 4. web_report
    "build_and_publish",
    "build_document",
    "publish_document",
    # live_sync
    "SyncResult",
    "TrackedSource",
    "Version",
    "check_source",
    "history",
    "history_table_tr",
    "sync_source",
]
