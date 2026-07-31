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
"""

from __future__ import annotations

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

__all__ = [
    "ColumnProfile",
    "Dataset",
    "DatasetError",
    "load_any",
    "load_csv",
    "load_excel",
    "load_google_sheet",
    "load_text",
]
