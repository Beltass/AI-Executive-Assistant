# Sprint 0 — Envanter Denetimi

Bu doküman, 5 Ağustos 2026'da repodan **ölçülerek** çıkarılan gerçek durumdur.
Plan değil, sayım. Her satırın kaynağı repodaki dosya veya commit'tir.

## 1. Ajan sayısı: hangi rakam nerede yazıyor?

| Kaynak | Sayı | Not |
|---|---|---|
| `src/ai_assistant/advisors/` altındaki public modüller | 35 | Emekliye ayrılanlar dahil, diskte duruyor |
| `advisors.all_advisors()` (canlı roster) | 16 | `meeting_prep` eklendikten sonra |
| `status_report.ADVISOR_META` (manifest) | 16 | Tek kaynak |
| `frontend/app.js` (`EXPERTISE_AREAS`) | 16 | Artık manifestten türetiliyor |
| `frontend/metrics.json` (son koşu) | 12 | **Bayat** — PHASE-1B öncesi isimler |

**"13" sayısı repoda ajan sayısı olarak geçmiyor.** Kaynağı
`docs/BENCHMARK_ANALIZI.md`'deki **13.941 token/koşu** ifadesinin yanlış
okunmasıdır.

## 2. `frontend/metrics.json` bayatlığı

| Ölçüm | Değer |
|---|---|
| Kayıtlı koşu | 25 |
| Dosyada geçen farklı ajan id'si | 22 (emekli `weather` dahil) |
| Son koşuda görünen ajan | 12, **hepsi PHASE-1B öncesi isim** |

Son koşudaki isimler: `banking_cc_projects`, `cx_research`, `ai_mastery`,
`sector_intel`, `job_scout`, `ai_news`, `career_hr`, `leadership_coach`,
`free_certs`, `language_coach`, `accountability_coach`, `kids_development`.

Canlı roster'da olup metrics.json'da **hiç olmayan** 5 ajan:
`communications_calendar`, `linkedin_coach`, `social_media_coach`,
`personal_assistant`, `data_analyst`.

Sonuç: pano ajan listesini metrics.json'dan **almamalı**. Manifestten türeyen
`frontend/advisors.json` bu yüzden var.

## 3. Bulunan kırıklar ve durumları

| # | Bulgu | Yer | Durum |
|---|---|---|---|
| 1 | `meeting_prep` öksüzdü: `__init__.py:263` docstring'i "eklendi" diyordu ama import/instantiate edilmiyordu; öksüz `# Position 3` yorumu ve **iki** `# Position 9` vardı | `advisors/__init__.py` | Düzeltildi — `69a96c9` |
| 2 | `run_batch()` sessizce `{}` döndürüyor, çağıran koşulsuz ajan-başına fallback yapıyor → **1 çağrı 16 çağrıya patlıyor** | `advisors/_batch.py:316`, `operations_manager.py:153` | **Açık** |
| 3 | JWT doğrulaması placeholder'dı | `backend/app/dependencies.py` | Düzeltildi — `bbfffec` |
| 4 | `/tmp` sabitleri: üretim kodunda 1, testlerde 4 dosya | `integrations/task_tracker.py:332` | Düzeltildi — `bbfffec` |
| 5 | CI: `\|\| true`'lar zaten temizlenmişti; gerçek kırık `pytest -q`'nun `ModuleNotFoundError` vermesiydi | `.github/workflows/ci.yml` | Düzeltildi — `3d8d9c1` (pythonpath) |
| 6 | `httpx` pin çakışması | `backend/requirements.txt:16` ve kök `requirements.txt:39` → `0.25.2`; `pyproject.toml:14` → `>=0.27.0` | **Açık** |
| 7 | İki ayrı `ActionItem` tanımı | `advisors/meeting_notes.py:222`, `reports.py:341` | Birleştirildi — `14c076d` |
| 8 | `app.js` yorumu "ADVISOR_META source of truth" derken 16 kayıt elle tutuluyordu | `frontend/app.js:148` | Düzeltildi — `f379149` |

## 4. Ölçülen taban

| Ölçüm | Değer |
|---|---|
| Token / koşu (ortalama) | 13.941 |
| Koşu süresi (ortalama) | 52,9 sn |
| Test durumu (denetim anı) | 1381 geçiyor, 0 hata |

## 5. Kod kalitesi (açık)

| Araç | Durum |
|---|---|
| `black` | backend'de 41 dosyanın 17'si uyumsuz |
| `flake8` | 109 uyarı |
