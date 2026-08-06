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
| `frontend/metrics.json` (son koşu) | 2 | Güncel isimler; aşağıdaki düzeltmeye bakın |

**"13" sayısı repoda ajan sayısı olarak geçmiyor.** Kaynağı
`docs/BENCHMARK_ANALIZI.md`'deki **13.941 token/koşu** ifadesinin yanlış
okunmasıdır.

## 2. `frontend/metrics.json` bayatlığı

> **Düzeltme (aynı gün, yeniden sayıldı).** Bu bölümün ilk hâli "son koşuda 12
> ajan var, hepsi PHASE-1B öncesi isim" diyordu. Bu yanlıştı: o 12 ajanlık koşu
> dosyanın **ilk** koşusu (29.07.2026), **son** koşusu değil. Sıralama tersten
> okunmuş. Aşağıdaki tablo yeniden sayımdır.

| Ölçüm | Değer |
|---|---|
| Kayıtlı koşu | 25 (29.07.2026 – 04.08.2026) |
| Dosyada geçen farklı ajan id'si | 22 |
| Bunların güncel roster'da olmayanı | 12 (emekli `weather` dahil) |
| İlk koşu (29.07) | 12 ajan, ağırlıklı olarak PHASE-1B öncesi isimler |
| Son koşu (04.08 23:26) | 2 ajan, **güncel** isimler |

PHASE-1B öncesi isimler (`banking_cc_projects`, `cx_research`, `ai_mastery`,
`sector_intel`, `job_scout`, `ai_news`, `career_hr`, `leadership_coach`,
`free_certs`, `language_coach`, `accountability_coach`) yalnızca 29–31.07
koşularında geçiyor. Pano grafikleri **son 7 koşuyu** çizdiği için bu isimler
zaten ekranda değil; o pencerede kalan tek emekli ajan `weather`.

Canlı roster'da olup metrics.json'da **hiç olmayan** 6 ajan:
`communications_calendar`, `data_analyst`, `linkedin_coach`, `meeting_prep`,
`personal_assistant`, `social_media_coach`. (İlk sayımda 5 yazıyordu;
`meeting_prep` atlanmış.)

Sonuç: pano ajan listesini metrics.json'dan **almıyor**, manifestten türeyen
`frontend/advisors.json`'dan alıyor. Ölçüm grafikleri ise kaçınılmaz olarak
ölçüm dosyasını çizer; emekli ajanlar `d873931` ile "(arşiv)" etiketlendi ve
hiç ölçülmemiş danışmanlar için grafiklerin üstüne uyarı satırı eklendi.

## 3. Bulunan kırıklar ve durumları

| # | Bulgu | Yer | Durum |
|---|---|---|---|
| 1 | `meeting_prep` öksüzdü: `__init__.py:263` docstring'i "eklendi" diyordu ama import/instantiate edilmiyordu; öksüz `# Position 3` yorumu ve **iki** `# Position 9` vardı | `advisors/__init__.py` | Düzeltildi — `69a96c9` |
| 2 | `run_batch()` sessizce `{}` döndürüyor, çağıran koşulsuz ajan-başına fallback yapıyor → **1 çağrı 16 çağrıya patlıyor** | `advisors/_batch.py:316`, `operations_manager.py:153` | Düzeltildi — `978ef40` (fallback artık `DIGEST_BATCH_FALLBACK_MODE` ile opt-in) |
| 3 | JWT doğrulaması placeholder'dı | `backend/app/dependencies.py` | Düzeltildi — `bbfffec` |
| 4 | `/tmp` sabitleri: üretim kodunda 1, testlerde 4 dosya | `integrations/task_tracker.py:332` | Düzeltildi — `bbfffec` |
| 5 | CI: `\|\| true`'lar zaten temizlenmişti; gerçek kırık `pytest -q`'nun `ModuleNotFoundError` vermesiydi | `.github/workflows/ci.yml` | Düzeltildi — `3d8d9c1` (pythonpath) |
| 6 | `httpx` pin çakışması | `backend/requirements.txt:16` ve kök `requirements.txt:39` → `0.25.2`; `pyproject.toml:14` → `>=0.27.0` | Düzeltildi — `bbfffec`; her iki dosya da `httpx>=0.27.0,<0.28.0`. Üst sınır bilinçli: httpx 0.28 `Client(app=...)` kısayolunu kaldırıyor ve backend `TestClient`'ı kırılıyor |
| 7 | İki ayrı `ActionItem` tanımı | `advisors/meeting_notes.py:222`, `reports.py:341` | Birleştirildi — `14c076d` |
| 8 | `app.js` yorumu "ADVISOR_META source of truth" derken 16 kayıt elle tutuluyordu | `frontend/app.js:148` | Düzeltildi — `f379149` |

## 4. Ölçülen taban

| Ölçüm | Değer |
|---|---|
| Token / koşu (ortalama) | 13.941 |
| Koşu süresi (ortalama) | 52,9 sn |
| Test durumu (denetim anı) | 1381 geçiyor, 0 hata |
| Test durumu (sprint 1 sonu) | kök 1458 geçiyor, backend 122 geçiyor |

Token ve süre rakamları `metrics.json`'daki 25 koşunun ortalamasıdır, yani
kapılar devreye girmeden ÖNCEKİ tabandır. Kapıların ölçülen etkisi için
[`COORDINATION_BACKLOG.md`](COORDINATION_BACKLOG.md) §3.

## 5. Kod kalitesi

| Araç | Denetim anı | Şimdi |
|---|---|---|
| `black` | backend'de 41 dosyanın 17'si uyumsuz | 43 dosyanın hepsi uyumlu; CI kapısı bastırılmıyor |
| `flake8` (`backend/`) | 109 uyarı | 0 bulgu; `--exit-zero` kaldırıldı (`35fe99e`, `99aa79c`) |
| `flake8` (repo geneli) | ölçülmemişti | ~2.031 E501 + 289 F401 — `src/` ve `tests/` hiç black görmedi, kapı bilinçli olarak yalnızca `backend/` |
