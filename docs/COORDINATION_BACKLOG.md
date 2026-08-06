# Koordinasyon İş Listesi

Sahiplik ayrımı (Claude / Codex) için bkz. [`IS_BOLUMU.md`](IS_BOLUMU.md).
Envanterin kaynağı [`SPRINT_0_AUDIT.md`](SPRINT_0_AUDIT.md), hedef
[`TARGET_ARCHITECTURE.md`](TARGET_ARCHITECTURE.md).

## 1. Tamamlananlar

| İş | Commit | Not |
|---|---|---|
| Manifest terfi: `ADVISOR_META` tek kaynak, tetikleyici metadata'sı | `ee44368` | `trigger`, `token_ceiling`, `data_owner`, `dashboard_order` |
| `meeting_prep` roster kaydı + Slack kanalı | `69a96c9` | Öksüz `# Position` yorumları temizlendi, roster 16 |
| Meeting notes zinciri (deşifre → aksiyon → görev) | `bbfffec` öncesi seri | Türkçe tarih çözümü dahil |
| JWT doğrulaması (placeholder değil, gerçek) | `bbfffec` | `backend/app/dependencies.py` |
| `/tmp` sabitlerinin temizliği | `bbfffec` | Üretim kodu + 4 test dosyası |
| CI pythonpath kırığı | `3d8d9c1` | `pytest -q` artık `ModuleNotFoundError` vermiyor |
| `ActionItem` birleştirmesi | `14c076d` | Tek model: `src/ai_assistant/action_center.py` |
| Pano: roster manifestten türüyor + Aksiyon Merkezi | `f379149` | `frontend/advisors.json`, 6 bölüm |
| Fallback kapısı | `978ef40` | Ajan-başına fallback artık OPT-IN: `DIGEST_BATCH_FALLBACK_MODE=per_advisor` demeden 1 çağrı 16 çağrıya patlamıyor |
| Tetikleyici koşumu | `d32d14a` | `trigger` koşuda gerçek filtre; ölçüm için aşağıdaki "Kapıların ölçülen etkisi" |
| Veri hash kapısı | `9e9feb3` | `data_owner` başına içerik hash'i; değişmeyen kaynak tüm sahiplerini atlar |
| Action Center veri hattı | `14c076d` + `reports.py` | Aksiyonlar ajan çıktısından ayrıştırılıyor (`_parse_action_line`, `_coerce_actions`) |
| Ölçüm: çağrı sayısı + atlama gerekçeleri | `8070433` | `metrics.json` artık NEDEN atlandığını da yazıyor |
| Düşünme bütçesi | `8b7b5e7` | Yapılandırılmış çıkarım çağrılarında düşünme tokenı ödenmiyor |
| CI: lint bastırması kaldırıldı | `35fe99e`, `99aa79c` | `continue-on-error` ve `--exit-zero` gitti; backend flake8 20 → 0 |
| Pano: bayat ölçüm verisi dürüstçe etiketlendi | `d873931` | Emekli ajan "(arşiv)", hiç ölçülmemiş danışmanlar için uyarı |

## 2. Devam edenler

| İş | Ne yapılacak | Sahip |
|---|---|---|
| Pano: Aksiyon sekmesi canlı doğrulama | Sekme canlı KOŞU verisiyle hâlâ doğrulanmadı. Bu depoda hiçbir LLM anahtarı tanımlı değil (`GEMINI_API_KEY` dahil hepsi boş), yani doğrulama ancak anahtarlı bir ortamda yapılabilir. Şema ve ayrıştırma tarafı test altında. | Claude |

## 3. Kapıların ölçülen etkisi

Canlı koşu YAPILMADI (anahtar yok). Aşağıdakiler kapı fonksiyonları
(`weekly_due`, `trigger_allows`) gerçek 16 kişilik ekip üzerinde doğrudan
çağrılarak SAYILDI; token değerleri manifestteki `token_ceiling` TAVANLARIDIR,
gerçekleşen tüketim değil.

| Senaryo | Koşan | Elenen | Elenen tavan |
|---|---|---|---|
| Pazartesi (haftalık slot açık) | 15 | 1 (`kids_development`) | 800 |
| Pazartesi dışı (ör. Çarşamba) | 11 | 5 | 4.600 |
| Pazartesi dışı + veri kapısı (hiçbir kaynak değişmemiş) | 5 | 11 | 12.200 |

Ekibin toplam tavanı 16.800. Pazartesi dışı bir günde tetikleyici kapısı
tavanın %27'sini, veri kapısı da devredeyken ikisi birlikte %73'ünü eliyor.
Veri kapısının davranışı `tests/test_run_gates.py` içinde ölçülüyor
(`test_unchanged_sources_cost_no_llm_call_at_all`: değişmemiş kaynakta LLM
çağrısı SIFIR).

## 4. Açık riskler

| Risk | Ölçüm | Etki |
|---|---|---|
| Repo geneli lint borcu | `src/` + `tests/` ~2.031 E501, 289 F401 | flake8 kapısı bilinçli olarak yalnızca `backend/`; kalan ağaç hiç black görmedi, kapıya alınırsa ya devasa bir reformat ya da yeniden bastırma gerekir |
| Backend testleri CWD'ye duyarlı | Depo kökünden `pytest backend/tests/` dolu bir `.env` ile patlıyor (`extra_forbidden`) | CI'da `.env` yok, orada geçiyor; geliştirici makinesinde yanıltıcı kırmızı. Kaynak: `backend/app/config.py` `env_file = ".env"` CWD'ye göre çözülüyor |
| Ölçülmemiş danışmanlar | 16 danışmanın 6'sının `metrics.json`'da hiç satırı yok | Token grafikleri onları göstermiyor; pano artık bunu yazıyor ama gerçek maliyetleri hâlâ bilinmiyor |
| Canlı token kazancı doğrulanmadı | Yalnızca tavan aritmetiği var | Gerçek tasarruf ancak anahtarlı bir koşuda ölçülebilir |

### Kapanan riskler

| Risk | Nasıl kapandı |
|---|---|
| `black` uyumsuzluğu (41 dosyanın 17'si) | `backend/` tamamen uyumlu; `black --check` artık bastırılmayan bir CI kapısı |
| `flake8` uyarıları (109) | `backend/` 0 bulgu (`35fe99e`); `--exit-zero` kaldırıldı |
| `httpx` pin çakışması | `bbfffec`'te hizalandı: her iki requirements dosyası da `httpx>=0.27.0,<0.28.0`. Üst sınır bilinçli — httpx 0.28 `Client(app=...)` kısayolunu kaldırıyor ve backend'in `TestClient`'ı kırılıyor. `pytest` de `>=8.0.0,<10` ile hizalı |
| `frontend/metrics.json` bayat | Grafikler son 7 koşuyu çiziyor, yani PHASE-1B öncesi isimler zaten ekranda değildi; kalan tek emekli ajan (`weather`) artık "(arşiv)" etiketli (`d873931`) |
| Batch fallback 16x maliyet | `978ef40` ile opt-in; varsayılan kapalı |
