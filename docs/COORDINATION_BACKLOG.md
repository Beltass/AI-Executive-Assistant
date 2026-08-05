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

## 2. Devam edenler

| İş | Ne yapılacak | Sahip |
|---|---|---|
| Fallback kapısı | `_batch.py:316` sessiz `{}` + `operations_manager.py:153` koşulsuz ajan-başına fallback → kapatılacak, yalnızca elle kurtarma | Codex |
| Tetikleyici koşumu | `trigger` alanının koşuda gerçekten filtre olması (`always` / `data_triggered` / `weekly` / `user_requested`) | Codex |
| Veri hash kapısı | `data_owner` başına içerik hash'i; değişmeyen kaynak tüm sahiplerini atlar | Codex |
| Action Center veri hattı | Aksiyonların ajan çıktısından uçtan uca dolması (şema hazır, üretim tarafı bekliyor) | Claude |
| Pano | Aksiyon sekmesinin canlı koşu verisiyle doğrulanması | Claude |

## 3. Açık riskler

| Risk | Ölçüm | Etki |
|---|---|---|
| `black` uyumsuzluğu | backend'de 41 dosyanın 17'si | Biçim commit'leri gerçek diff'i gömüyor |
| `flake8` uyarıları | 109 | Gerçek hata uyarı gürültüsünde kayboluyor |
| `httpx` pin çakışması | `requirements.txt` → `0.25.2`, `pyproject.toml` → `>=0.27.0` | Ortamlar arasında farklı sürüm |
| `frontend/metrics.json` bayat | Son koşuda 12 ajan, hepsi PHASE-1B öncesi isim | Pano ajan listesini buradan almamalı (alınmıyor) |
| Batch fallback | 1 çağrı 16 çağrıya patlayabiliyor | Token maliyeti 16x |
