# Hedef Mimari

Tek cümle: **manifest tek kaynaktır, geri kalan her şey ondan türer; LLM'e
koşu başına tek çağrı gider ve her koşu ölçülür.**

## 1. Manifest tek kaynak

`src/ai_assistant/status_report.py` içindeki `ADVISOR_META` tek yazılan yerdir.

| Türeyen | Nereden | Nasıl |
|---|---|---|
| Canlı roster (`all_advisors()`) | `status`, `module`, `advisor_class` | `advisors/__init__.py` manifestten kurar |
| Slack kanalları | `slack_target` | Ajan başına fan-out |
| Pano sırası ve ajan listesi | `dashboard_order`, `title`, `emoji`, `category` | `frontend/advisors.json` (`python -m ai_assistant.frontend_manifest`) |
| README'deki ajan sayısı | roster uzunluğu | Elle yazılmaz, sayılır |
| Tetikleyici filtresi | `trigger` | `operations_manager` |
| Token bütçesi | `token_ceiling` | `metrics` katmanı "payını aştı" der |
| İçerik hash kapısı | `data_owner` | Aynı sahibi paylaşan ajanlar tek hash'le atlanır |

Kural: **manifestte olmayan ajan çalışmaz; manifestte olan ajan elle ikinci bir
listeye yazılmaz.**

## 2. Tetikleyici sınıfları

| Sınıf | Anlamı |
|---|---|
| `always` | Her koşuda çalışır. Brifingin onsuz anlamsız olduğu ajanlar. |
| `data_triggered` | Yalnızca `data_owner` kaynağı değiştiyse çalışır. |
| `weekly` | Haftada bir. Günlük değişmeyen ritim işleri. |
| `user_requested` | Yalnızca açıkça istenince (`DIGEST_FORCE_ADVISORS`). |

| Ajan | Tetikleyici | Token tavanı | Veri sahibi | Kategori |
|---|---|---|---|---|
| `morning_operations` | always | 1600 | gmail_calendar | operasyon |
| `communications_calendar` | always | 1400 | gmail_calendar | operasyon |
| `meeting_prep` | data_triggered | 1200 | calendar | operasyon |
| `career_development` | data_triggered | 1200 | career_feeds | kariyer |
| `market_intelligence` | data_triggered | 1400 | market_feeds | sektör |
| `complaint_radar` | data_triggered | 1200 | complaint_feeds | sektör |
| `linkedin_coach` | data_triggered | 1000 | linkedin | kişisel gelişim |
| `social_media_coach` | weekly | 900 | social | kişisel gelişim |
| `personal_assistant` | weekly | 1000 | calendar_tasks | operasyon |
| `data_analyst` | data_triggered | 1600 | analysis_dataset | operasyon |
| `ai_innovation` | weekly | 1000 | ai_feeds | kişisel gelişim |
| `kids_development` | user_requested | 800 | — | aile |
| `executive_coaching` | weekly | 900 | — | kişisel gelişim |
| `work_analyst` | always | 0 (LLM yok) | run_briefings | operasyon |
| `operations_director` | always | 1600 | run_briefings | operasyon |
| `sre_watchdog` | always | 0 (LLM yok) | system_health | operasyon |

Bu tablonun tamamı `ADVISOR_META`'dan doğrulandı (16 ajan, tetikleyici ve
tavan değerleri birebir tutuyor). Kapıların kaç ajanı elediği ölçüldü;
sayılar [`COORDINATION_BACKLOG.md`](COORDINATION_BACKLOG.md) §3'te. Özet:
Pazartesi dışı bir günde tetikleyici kapısı 16 ajandan 5'ini, veri kapısı da
devredeyken toplam 11'ini eliyor. Bunlar `token_ceiling` **tavanlarıdır**,
gerçekleşen tüketim değil — canlı koşu yapılmadı.

## 3. Veri akışı

```
1. GERÇEK VERİ  → RSS, KPI dosyaları, Gmail/Takvim, sistem sağlığı
2. HASH KAPISI  → data_owner başına içerik hash'i; değişmediyse ajan ATLANIR
3. TEK BATCH    → hayatta kalan ajanların istemleri TEK LLM çağrısında gider
4. SENTEZ       → iş analisti + operasyon direktörü diğerlerinin çıktısını okur
5. YAYIN        → rapor belgeleri, Slack, pano (status.json / metrics.json)
```

Sıra tersine çevrilemez: **önce veri, sonra model.** Modelden veri istemek
(uydurma) yasaktır; ajan okuduğu kaynağı raporunda gösterir.

## 4. Token kuralları

1. Batch başarısız olursa **varsayılan fallback yoktur**. Koşu, üretilemeyen
   bölümleri "atlandı" diye bildirir.
2. `DIGEST_BATCH_FALLBACK_MODE=per_advisor` yalnızca **elle kurtarma** içindir;
   varsayılan değeri asla bu olmaz.
3. Aynı veri iki ajana gönderilmez — ortak `data_owner` tek okuma, tek hash.
4. Her koşuda ölçülür ve `metrics.json`'a yazılır: **çağrı sayısı, token,
   süre, atlanan ajan sayısı**.
5. Yeni ajan eklemenin şartı dörttür: **tetikleyici + token tavanı + veri
   sahibi + başarı metriği**. Dördü yoksa manifeste giremez.

## 5. Action Center

Tek `ActionItem` modeli: `src/ai_assistant/action_center.py`.

| Alan | Anlamı |
|---|---|
| `id` | 8 karakterlik kimlik |
| `title` | Yapılacak iş (`text` / `description` eski adlar) |
| `priority` | `P0`-`P3`; 1-5 tamsayısıyla iki yönlü çevrilir |
| `owner` | Sorumlu |
| `due_date` | Son tarih (`deadline` eski adı) |
| `source_advisor` | Manifestteki ajan id'si |
| `evidence_links` | Kanıt bağlantıları |
| `impact` | Etki |
| `recommendation` | Öneri |
| `approval_status` | `not_required` / `pending` / `approved` / `rejected` |
| `status` | `pending` / … |

Kalıcılık: mevcut rapor JSON'ları. **Yeni veritabanı yok.** Aksiyonlar günün
`reports/<gün>/index.json` dosyasındaki `actions` alanında taşınır.

### Pano bölümleri (Aksiyon sekmesi)

| # | Bölüm | Kaynağı |
|---|---|---|
| 1 | Bugünün en fazla 3 önceliği | Gün index'i, P0/P1 |
| 2 | Karar/onay bekleyenler | `approval_status = pending` |
| 3 | Takvim ve operasyon riskleri | `status.json` (takvim, Gmail, başarısız ajanlar) |
| 4 | KPI sapmaları ve alarmlar | `status.json` `performance` (7 günlük seriye göre sapma) |
| 5 | Kariyer / öğrenme gelişimi | Manifest kategorisi `kariyer` + `kişisel gelişim` |
| 6 | Token, çağrı, maliyet, sistem sağlığı | `metrics.json` + son koşu |
