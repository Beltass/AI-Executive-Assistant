# Mimari Evrim Araştırması — Olay Güdümlü + Çok Kanallı Yapı

**Hazırlanma tarihi:** 5 Ağustos 2026
**Kapsam:** Yoklama (cron) tabanlı mimariden olay güdümlü mimariye geçiş için karar verilebilir veri
**Metodoloji:** Web araması + GitHub API. Doğrulanamayan her şey açıkça "doğrulanamadı" olarak işaretlendi.
**Uyarı:** Fiyatlar araştırma tarihindeki kamuya açık kaynaklara dayanır. Bazı sağlayıcı doküman siteleri
(developers.google.com, api.slack.com, twilio.com, cloud.google.com) bu ortamın ağ politikası tarafından
doğrudan erişime kapalıydı; bu durumlarda ikincil kaynaklar kullanıldı ve ayrıca belirtildi.

---

## 0. ÖNCE ŞU: MEVCUT MALİYET VARSAYIMI YANLIŞ OLABİLİR

Görev tanımında "aylık ~21.000 Actions dakikası" ve bunun bir maliyet problemi olduğu varsayılıyor.
İki düzeltme:

**Düzeltme 1 — Depo herkese açık (public).**
`Beltass/AI-Executive-Assistant` deposu GitHub API'ye göre `"private": false`.
GitHub'ın 2026 fiyat değişikliği duyurusuna göre *"Standard GitHub-hosted or self-hosted runner usage on
public repositories will remain free"*. Yani **bugünkü Actions dakika maliyeti 0 USD.**
Özel depoda olsaydı: Free planda 2.000 dk/ay ücretsiz, sonrası Linux 2-core için **0,006 USD/dk**
(1 Ocak 2026 indirimi; öncesi 0,008 USD/dk).
Kaynak: <https://github.com/resources/insights/2026-pricing-changes-for-github-actions> ,
<https://cicdcalculator.com/github-actions-free-tier> (erişim 05.08.2026)

**Düzeltme 2 — Mevcut cron yoğunluğu 21.000 dk'yı vermiyor.**
Depodaki güncel `.github/workflows/` içeriği:

| Workflow | Cron | Gün/çalışma |
|---|---|---|
| `chat-poller.yml` | `*/15 * * * *` | 96 |
| `meeting-notes-poller.yml` | `*/30 * * * *` | 48 |
| `daily-briefing.yml` | `0 7`, `0 11,15,19` | 4 |
| `advisor-slack-bridge.yml` | `0 7` | 1 |
| `drive-backup-scheduler.yml` | `0 23` + ay sonu | ~1 |
| **Toplam** | | **~150 çalışma/gün ≈ 4.500/ay** |

Çalışma başına 2 dk varsayımıyla ~9.000 dk/ay. `chat-poller` `*/5` iken (~288/gün) toplam ~21.000 dk'ya
yaklaşırdı — görevdeki rakam muhtemelen o dönemden. Şu an `*/15`.

**SONUÇ:** Olay güdümlü mimarinin gerekçesi **maliyet değil**. Gerçek gerekçeler:
1. **Gecikme** — Slack'e gelen bir mesaja 15 dakikaya kadar geç yanıt. Olay güdümlüde ~1-3 sn.
2. **Boşa çalışma** — 4.500 çalışmanın büyük kısmı "yeni bir şey yok" diyip kapanıyor.
3. **API kota israfı** — her yoklama Gmail/Drive kotasından yiyor.
4. **Etkileşim imkânsızlığı** — Slack slash komutu, buton, modal gibi *senkron* etkileşimler cron ile
   mümkün değil; 3 saniyelik yanıt penceresi gerekiyor (bkz. Bölüm 1c).

**ÖNERİ:** Projeyi "Actions faturasını düşürmek" için değil, **"gecikmeyi 15 dk'dan saniyelere indirmek ve
etkileşimli kanalları açmak"** için evriltin. Bu, hangi tetikleyicinin öncelikli olduğunu da değiştirir:
Slack (etkileşim gerekiyor) > Gmail (gecikme önemli) > Calendar > Drive (gecikme önemsiz, cron kalabilir).

---

## BÖLÜM 1 — OLAY GÜDÜMLÜ TETİKLEME

### 1a) Gmail push bildirimleri (`users.watch` + Cloud Pub/Sub)

**Nasıl çalışır (zincir):**
```
Gmail kutusu değişir
  → Gmail, sizin GCP Pub/Sub topic'inize mesaj yayınlar (payload: {emailAddress, historyId})
  → Pub/Sub push subscription, HTTPS endpoint'inize POST eder (OIDC token ile imzalı)
  → Endpoint historyId'yi alır, users.history.list ile delta'yı çeker
```
Bildirim **e-postanın içeriğini taşımaz**, sadece `historyId` taşır. Son işlenen `historyId`'yi kalıcı
saklamanız şart (yoksa delta hesaplayamazsınız).

**Gerçek gereksinimler:**

| Soru | Cevap |
|---|---|
| GCP projesi şart mı? | **Evet.** Pub/Sub topic'i bir GCP projesinde yaşamak zorunda. |
| Pub/Sub ücretli mi? | Ücretsiz katman var: **her takvim ayı ilk 10 GiB throughput ücretsiz**, sonrası **40 USD/TiB**. Depolama 0,10–0,21 USD/GiB-ay. Kaynak: <https://cloud.google.com/pubsub/pricing> , özet: <https://airbyte.com/data-engineering-resources/google-pub-sub-pricing> (05.08.2026) |
| Bu proje 10 GiB'i aşar mı? | **Hayır, yakınına bile gelmez.** Bildirim payload'ı ~100 byte. Günde 500 e-posta = ~50 KB/gün = ~1,5 MB/ay. 10 GiB'in ~0,015%'i. **Pratikte 0 USD.** |
| Topic'e izin | Gmail'in yayın yapabilmesi için topic üzerinde `gmail-api-push@system.gserviceaccount.com` hesabına `roles/pubsub.publisher` verilmeli. |
| Watch süresi | **7 gün.** Süresi dolduğunda **sessizce** durur — hata yok, uyarı yok. |
| Yenileme | Otomatik yenileme YOK. Google **en az günde bir** `users.watch` çağrılmasını öneriyor. Pratikte 24 saatlik cron ideal. |

Kaynaklar: <https://developers.google.com/workspace/gmail/api/guides/push> (doğrudan erişilemedi, ikincil
kaynaklardan doğrulandı), <https://cli.nylas.com/guides/gmail-push-notifications> ,
<https://www.unipile.com/gmail-api-push-notifications/> , <https://kb.torq.io/en/articles/9138324-receive-gmail-push-notifications-using-google-cloud-pub-sub>

> **Kritik risk:** 7 günlük sessiz sona erme. Yenileme cron'u bir kez kaçarsa sistem sessizce kör olur.
> **Karşı önlem:** (a) günlük yenileme cron'u, (b) "son 6 saatte hiç bildirim gelmedi" alarmı,
> (c) düşük frekanslı (örn. 6 saatte bir) yedek yoklama — kemer + askı.

**Push hedefi neden GitHub Actions olamaz:** Pub/Sub push subscription, sürekli erişilebilir bir HTTPS
endpoint'e POST eder. GitHub Actions'ın böyle bir dinleyicisi yoktur.
**Ancak bir ara yol var:** `repository_dispatch` / `workflow_dispatch` GitHub REST API uç noktaları HTTPS'tir.
Çok ince bir "shim" (Cloud Run/Worker) Pub/Sub push'unu alıp GitHub'a `repository_dispatch` atabilir; ağır iş
Actions'ta kalır. Bu, mevcut kodu taşımadan olay güdümlülüğe geçmenin en ucuz yolu (bkz. Bölüm 2 önerisi).

### 1b) Google Calendar push (`events.watch`)

- **Nasıl:** `events.watch` ile bir *notification channel* açılır (`type: "web_hook"`, `address: <HTTPS URL>`).
  Değişiklikte Google, endpoint'inize POST atar. Body genelde boştur; bilgi HTTP header'larındadır
  (`X-Goog-Channel-ID`, `X-Goog-Resource-State`, `X-Goog-Message-Number`, `X-Goog-Channel-Expiration`).
  Delta'yı `syncToken` ile `events.list` çağırarak alırsınız.
- **Süre:** **7 gün** (kanal başına). Otomatik yenileme yok; `watch`'ı tekrar çağırıp yeni kanal açmanız gerek.
  İstekte daha kısa bir `expiration` talep edebilirsiniz; Google'ın iç limiti daha kısıtlayıcıysa o geçerli olur.
- **Gmail ile altyapı paylaşımı:** **Kısmen.** Aynı GCP projesini, aynı OAuth istemcisini ve **aynı HTTPS
  endpoint host'unu** paylaşabilir. Ama **Pub/Sub'ı paylaşamaz** — Calendar/Drive Pub/Sub kullanmaz, doğrudan
  webhook (web_hook) modelidir. Yani iki farklı ingest yolu yazacaksınız:
  `/webhook/gmail` (Pub/Sub POST + OIDC doğrulama) ve `/webhook/calendar` (Google webhook + token doğrulama).
- **Domain doğrulaması:** Google, webhook adresinin sahibi olduğunuzu doğrulamanızı ister (Search Console
  domain verification). `*.run.app` gibi Google'a ait alan adlarında bu adım genelde sorun çıkarmaz;
  kendi alan adınızda doğrulama gerekir.

Kaynak: <https://developers.google.com/workspace/calendar/api/guides/push> ,
<https://cli.nylas.com/guides/google-calendar-push-notifications>

### 1c) Slack Events API — Socket Mode vs HTTP

| | **HTTP Events endpoint** | **Socket Mode** |
|---|---|---|
| Nasıl | Slack sizin HTTPS URL'inize POST eder | Uygulamanız Slack'e WebSocket açar, olaylar oradan akar |
| Public URL gerekir mi | **Evet** | **Hayır** |
| Sürekli açık bağlantı | Hayır (stateless) | **Evet** — bu yüzden serverless'a uymaz |
| 3 saniye kuralı | **Evet** | **Evet — Socket Mode'da da geçerli** |
| Slack'in tavsiyesi | Üretim için önerilen | Ölçekte üretim için önerilmiyor |

**"Socket Mode sürekli açık bağlantı gerektiriyor, serverless'a uymuyor" — DOĞRU.**
Socket Mode kalıcı bir WebSocket süreci ister; Cloud Run/Workers/Lambda gibi istek-başına-ölçeklenen
platformlarda bu süreci ayakta tutmak ya imkânsız ya da pahalıdır (min-instance=1 + CPU always-on).

**"3 saniyelik yanıt süresi kısıtı var mı" — EVET, ve önemli bir yanılgıyı düzeltelim:**
3 saniye kuralı **Socket Mode'da da geçerlidir**. Socket Mode "3 saniyeden kurtarır" diye yaygın bir
yanlış inanç var; Slack POST etmek yerine WebSocket üzerinden payload gönderir ama ack yine 3 sn içinde
beklenir. Timeout aşılırsa Slack yeniden dener → **tekrarlı işleme (duplicate) riski**. "Delayed Events"
açıksa ilk 3 denemeden sonra 24 saate kadar saatlik denemeler yapılır.

Kaynaklar: <https://api.slack.com/apis/event-delivery> , <https://docs.slack.dev/apis/events-api/> ,
<https://hookdeck.com/webhooks/platforms/guide-to-slack-webhooks-features-and-best-practices> ,
<https://www.questionbase.com/resources/blog/slack-events-api-acknowledgement-requirements-what-every-developer-needs-to-know>

**Python için doğrudan çözüm var:** `slack_bolt`'un **Lazy Listeners** özelliği (yalnızca Bolt for Python'da
mevcut) tam olarak bu problem için tasarlandı: `process_before_response=True` ile önce `ack()` gönder,
uzun işi ayrı bir çağrıda yap. Depoda `slack-bolt==1.18.0` zaten kurulu.
Kaynak: <https://docs.slack.dev/tools/bolt-python/concepts/lazy-listeners/> ,
repo: `slackapi/bolt-python` — **1.319 ★, MIT**, son push 04.08.2026

> **Kritik risk:** Cloud Run'da Python cold start 500 ms – 3 sn (bkz. Bölüm 2). Bu, 3 saniyelik Slack
> bütçesinin tamamını yiyebilir. **Karşı önlem:** Slack endpoint'i için `min-instances=1` (aylık ~5-10 USD)
> **veya** Slack ingest'i Cloudflare Workers'ta (cold start ~0) tutup ağır işi kuyruğa atmak.

### 1d) Google Drive `changes.watch`

- **Var mı:** Evet. `POST https://www.googleapis.com/drive/v3/changes/watch`, gövdede
  `{id, type:"web_hook", address, token, expiration}`.
- **Nasıl:** Calendar ile aynı webhook modeli (Pub/Sub değil). Bildirim geldiğinde `changes.list` +
  `pageToken` ile delta alınır. `changes.getStartPageToken` ile başlangıç token'ı alınır.
- **Süre:** **En fazla 7 gün.** Otomatik yenileme yok. `channels.stop` ile erken kapatılabilir
  (`id` + `resourceId` gerekir).

Kaynak: <https://developers.google.com/workspace/drive/api/guides/push> ,
<https://googleapis.github.io/google-api-python-client/docs/dyn/drive_v3.channels.html>

### KARAR TABLOSU — Olay kaynakları

| Kaynak | Push destekliyor mu | Mekanizma | Barındırma gereksinimi | Aylık ücretsiz katman | Yenileme periyodu | Bu proje için öncelik |
|---|---|---|---|---|---|---|
| **Gmail** | Evet | `users.watch` → Pub/Sub → push | HTTPS endpoint + GCP projesi + Pub/Sub topic | Pub/Sub 10 GiB/ay (bu proje ~1,5 MB → **0 USD**) | **7 gün** (günlük yenileme önerilir) | **Yüksek** |
| **Google Calendar** | Evet | `events.watch` → doğrudan webhook | HTTPS endpoint (Pub/Sub gerekmez) | Ücretsiz (API kotası dahilinde) | **7 gün** | Orta |
| **Google Drive** | Evet | `changes.watch` → doğrudan webhook | HTTPS endpoint | Ücretsiz | **7 gün (maks.)** | **Düşük** — cron kalsın |
| **Slack (HTTP Events)** | Evet | Events API → HTTPS POST | HTTPS endpoint, **3 sn içinde 2xx** | Ücretsiz (Slack planına bağlı) | Yenileme yok (kalıcı) | **En yüksek** |
| **Slack (Socket Mode)** | Evet | WebSocket | **Kalıcı süreç** — serverless'a uymaz | Ücretsiz | Yenileme yok | Alternatif değil |
| **GitHub Actions cron** (mevcut) | Hayır | Zamanlanmış | Yok | Public repo → **0 USD** | — | Yedek katman olarak kalsın |

**ÖNERİ:** Sıralama şu olsun — **(1) Slack HTTP Events** (etkileşimi açar, en yüksek getiri),
**(2) Gmail push** (gecikmeyi 15 dk → saniyeler yapar), **(3) Calendar watch**, **(4) Drive'ı cron'da bırakın**
(dosya değişikliği için 15 dk gecikme kimseyi öldürmez, 7 günlük kanal yenilemesi ek karmaşıklık getirir).
Her push kaynağının yanında **düşük frekanslı yedek cron** (6 saatte bir) bırakın — 7 günlük sessiz sona
erme riskine karşı tek gerçekçi sigorta budur.

---

## BÖLÜM 2 — BARINDIRMA SEÇENEĞİ

### Karşılaştırma tablosu (Ağustos 2026)

| Platform | Ücretsiz katman | Cold start | Python? | GCP entegrasyonu | Ticari kullanım |
|---|---|---|---|---|---|
| **Cloud Run** | 2M istek/ay, 360.000 GB-sn bellek, 180.000 vCPU-sn — kalıcı ("always free") | **500 ms – 3 sn** (Python, FastAPI+pydantic ölçümünde ort. 3.069 ms) | **Evet, tam** (herhangi bir container) | **Yerli** — Pub/Sub push, Secret Manager, IAM/OIDC hazır | Serbest |
| **Cloud Functions 2nd gen** | Cloud Run üzerine kurulu — aynı serverless kotası + fonksiyon çağrı kotası | Cloud Run ile benzer | Evet | Yerli | Serbest |
| **Cloudflare Workers** | **100.000 istek/gün** (~3M/ay), istek başına 10 ms CPU (Free) | **~0** (V8 isolate) | Evet ama **Pyodide/WASM** — FastAPI, Pydantic, Langchain destekli; keyfi C uzantılı paketler değil | Zayıf — Google IAM/OIDC'yi elle doğrulamanız gerekir | Serbest |
| **Deno Deploy** | 1M istek/ay, 100 GB egress, istek başına 50 ms CPU, 1 GiB KV | ~0 | **Hayır** (TS/JS) | Zayıf | Serbest |
| **Vercel Functions (Hobby)** | 1M fonksiyon çağrısı, 1M edge isteği, 100 GB transfer, 4 CPU-saat, **10 sn timeout** | Python'da +300–800 ms init; Hobby'de daha agresif | Evet (Python runtime) | Zayıf | **Hobby yalnızca kişisel/ticari olmayan** |
| **Fly.io** | **Yok** — 7 Ekim 2024'ten sonraki hesaplar için ücretsiz katman kaldırıldı. Yeni hesap: 5 USD deneme kredisi | Makine uyanması ~ saniyeler | Evet | Zayıf | Serbest |

Kaynaklar:
Cloud Run: <https://cloud.google.com/run/pricing> , <https://www.freetiers.com/directory/google-cloud-run> ,
cold start ölçümü: <https://blog.devops.dev/the-truth-about-cold-starts-in-google-cloud-run-functions-efb1c5bccfda> ,
<https://oneuptime.com/blog/post/2026-02-17-how-to-configure-minimum-instances-on-cloud-run-to-eliminate-cold-starts-for-production-services/view>
Cloudflare: <https://developers.cloudflare.com/workers/platform/pricing/> ,
<https://developers.cloudflare.com/workers/languages/python/> ,
<https://blog.cloudflare.com/python-workers-advancements/>
Deno: <https://docs.deno.com/deploy/pricing_and_limits/> , <https://deno.com/deploy/pricing>
Vercel: <https://www.fencode.dev/en/blog/vercel-free-vs-pro-2026-official-limits-pricing> ,
<https://kuberns.com/blogs/vercel-python/>
Fly.io: <https://fly.io/docs/about/pricing/> , <https://www.saaspricepulse.com/blog/flyio-free-tier-2026>
(hepsi erişim 05.08.2026)

### Eleme gerekçeleri

- **Fly.io — ELE.** Yeni hesaplarda ücretsiz katman yok. Minimum ~2-5 USD/ay. Karşılığında Cloud Run'a
  göre ek bir şey vermiyor.
- **Vercel — ELE.** Hobby planı lisans olarak "kişisel, ticari olmayan" ile sınırlı. Burak'ın kurumsal
  iş akışı için kullanılması gri alan. Ayrıca GCP entegrasyonu (Pub/Sub OIDC doğrulaması) elle yazılmalı.
- **Deno Deploy — ELE.** Python yok. Mevcut kod tabanı Python; ikinci bir dil eklemek kabul edilemez maliyet.
- **Cloud Functions 2nd gen — Cloud Run'a tercih edilecek bir sebep yok.** Zaten Cloud Run üzerinde çalışıyor;
  FastAPI uygulamasını olduğu gibi taşımak Cloud Run'da daha doğrudan.
- **Cloudflare Workers — güçlü ama kısıtlı.** Cold start ~0 (Slack'in 3 sn kuralı için ideal) ve
  100k istek/gün cömert. Ama: (a) Free planda istek başına **10 ms CPU** — LLM çağrısı beklerken geçen süre
  CPU sayılmaz ama JSON işleme + kripto doğrulama dar bir bütçe, (b) Python Workers Pyodide/WASM üzerinde —
  `google-api-python-client`, `spacy`, `chromadb` gibi mevcut bağımlılıklar çalışmaz, (c) GCP OIDC
  doğrulamasını elle yazmanız gerekir.

### ÖNERİ

**Birincil: Google Cloud Run.** Gerekçeler:

1. **Mevcut kod olduğu gibi taşınır.** `backend/app/main.py` bir FastAPI uygulaması; `requirements.txt`'te
   `uvicorn[standard]`, `google-auth`, `google-cloud-secret-manager`, `google-cloud-storage` zaten var.
   Bir `Dockerfile` + `gcloud run deploy` yeter. Diğer platformların hiçbiri bunu vaat edemiyor.
2. **Gmail push zaten GCP gerektiriyor.** Pub/Sub topic'i bir GCP projesinde olacak. Push hedefi de aynı
   projede Cloud Run olursa OIDC doğrulaması tek satır IAM ayarı (`--no-allow-unauthenticated` +
   `roles/run.invoker` push service account'a). Cloudflare'de aynı şeyi elle JWT doğrulayarak yazacaksınız.
3. **Ücretsiz katman fazlasıyla yeterli.** 2M istek/ay; bu proje günde birkaç yüz olay üretecek (~10k/ay).
4. **Secret Manager entegrasyonu yerli** — Google OAuth refresh token'larını, Slack signing secret'ı vs.
   ortam değişkeni olarak mount edebilirsiniz.

**Tek gerçek zayıflığı cold start (500 ms – 3 sn), ve bu yalnızca Slack için sorun.** İki çözüm:
- (a) Slack endpoint'i için ayrı bir Cloud Run servisi + `min-instances=1`. Maliyet: idle CPU faturalanır,
  kabaca **5-10 USD/ay** (kesin rakam iş yüküne bağlı — **doğrulanamadı**, GCP fiyat hesaplayıcısıyla
  ölçülmeli). Ücretsiz katmanın 180.000 vCPU-sn'si min-instance=1'in bir ayını (2,6M vCPU-sn) karşılamaz.
- (b) **Daha ucuz melez:** Slack ingest'i **Cloudflare Workers**'ta tut — tek işi imza doğrulaması +
  `ack()` + olayı Pub/Sub'a/Cloud Tasks'a atmak. Ağır iş Cloud Run'da (cold start artık önemsiz).
  Maliyet 0 USD. Bedeli: iki dilde iki küçük servis.

**Geçiş stratejisi (kademeli, geri dönülebilir):**
```
Aşama 0 (bugün):    cron → Actions → Python
Aşama 1:            Cloud Run "shim" ekle → Pub/Sub/webhook alır → repository_dispatch atar
                    → Actions çalışır (mevcut kod hiç değişmez, sadece tetikleyici değişir)
Aşama 2:            Ağır işi Cloud Run'a taşı, Actions'ı yedek/CI'ya indir
Aşama 3:            Slack için min-instances=1 veya CF Workers ingest
```
Aşama 1 tek başına **gecikmeyi 15 dk'dan ~30 sn'ye** indirir (Actions kuyruk süresi dahil) ve mevcut kodun
tek satırını değiştirmez. En yüksek getiri/risk oranı burada.

---

## BÖLÜM 3 — İLETİŞİM KANALLARI

### 3a) WhatsApp

**WhatsApp Business Cloud API — gerçek gereksinimler:**

| Adım | Gereken | Süre (kamuya açık kullanıcı raporları) |
|---|---|---|
| Meta Business hesabı (WABA) | Facebook Business Manager hesabı | Dakikalar |
| **İş doğrulaması** (Business Verification) | Ticaret sicil / vergi levhası benzeri resmi belge, doğrulanabilir adres + telefon, web sitesi | **2–5 iş günü**, belgeler eksikse **14 güne** kadar |
| Telefon numarası kaydı | Halihazırda normal WhatsApp'ta kayıtlı **olmayan** bir numara | Dakikalar–saatler |
| Görünen ad (Display Name) onayı | Markayla uyumlu ad | Dakikalar–saatler |
| **Mesaj şablonu onayı** | Her giden şablon Meta incelemesinden geçer | Dakikalar–saatler (utility şablonlar hızlı) |
| **Uçtan uca toplam** | | **3–10 iş günü** tipik |

Kaynaklar: <https://www.interakt.shop/whatsapp-business-api/account-approval/> ,
<https://chatimize.com/get-approved-whatsapp/> , <https://www.celitix.com/tutorial/whatsapp-approval-time>
(erişim 05.08.2026)

**Fiyatlandırma — mesaj başına (1 Temmuz 2025'ten beri konuşma başına DEĞİL):**

| Kategori | Türkiye fiyatı (USD/teslim edilen şablon mesajı) |
|---|---|
| Marketing | ~**0,0109 – 0,013** (1 Nisan 2026 tarifesi) |
| Utility | ~**0,0014** (1 Nisan 2026); 1 Temmuz 2026'da Türkiye utility oranında %84 indirim raporlanıyor |
| Authentication | ~**0,0014** |
| **Service** (kullanıcı size yazdıktan sonraki 24 saat içindeki serbest yanıtlar) | **ÜCRETSİZ, aylık tavan yok** |

Kaynaklar: <https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing> (resmî),
<https://whautomate.com/whatsapp-business-api-pricing> , <https://formbeep.com/whatsapp-api-pricing/> ,
<https://blueticks.co/blog/whatsapp-business-api-pricing-2026>

> **Bu proje için kritik gözlem:** Burak kendi asistanıyla konuşacak. Burak asistana bir mesaj yazdığında
> **24 saatlik service window** açılır ve o pencerede tüm yanıtlar **ücretsizdir**. Yani gerçek mesaj
> maliyeti neredeyse **sıfır**. Maliyet, asistanın *ilk temas kurduğu* (proaktif bildirim) durumlarda
> utility şablon başına ~0,0014 USD. Günde 20 proaktif bildirim = **aylık ~0,85 USD**.
> **Yani WhatsApp'ın engeli fiyat değil, onboarding sürtünmesi (3-10 iş günü + belge).**

**Kişisel WhatsApp otomasyonu (whatsapp-web.js vb.) — ToS ihlali mi, ban riski gerçek mi?**

**Evet, ikisi de.** Kütüphanenin kendi belgeleri "resmi olmayan" olduğunu ve engellenmeyeceğinizin garanti
edilmediğini söylüyor. Kamuya açık raporlar:
- Tespit **sezgisel/ML tabanlı**, tek bir sabit kural değil → **öngörülemez**. Bir hesap aylarca temiz
  çalışır, bir başkası aynı işi yaparken bir haftada banlanır.
- WhatsApp Web'i tersine mühendislikle kullanan araçların tipik olarak **2–8 hafta** içinde tespit edildiği
  raporlanıyor. Tespit otomatiktir, şikâyete bağlı değildir.

Kaynaklar: <https://www.bot.space/blog/whatsapp-api-vs-unofficial-tools-a-complete-risk-reward-analysis-for-2025> ,
<https://sporesec.com/en/blog/whatsapp-unofficial-api-ban-risk> , <https://achiya-automation.com/en/blog/whatsapp-spam-detection-2026/>

> **Değerlendirme:** Burak'ın kişisel numarası bir Operations Director'ün birincil iş iletişim kanalı.
> Ban riski = iş iletişiminin kesilmesi. **Bu, tasarruf edilen efora değmez. Kesin hayır.**

**Alternatif: Telegram Bot API**

| Boyut | Durum |
|---|---|
| Ücret | **Tamamen ücretsiz.** Bot oluşturma, mesaj, dosya — hepsi ücretsiz. |
| Kurulum | @BotFather'dan token al → 5 dakika. Doğrulama, belge, şablon onayı **yok**. |
| Mesaj limiti | Bot genel: ~30 mesaj/sn. Aynı sohbete: ~1 mesaj/sn. Aynı gruba: 20 mesaj/dk. Bu proje için fazlasıyla yeterli. |
| **Dosya indirme limiti** | **20 MB** (public Bot API sunucusu). Gönderme 50 MB. Kendi Bot API sunucunuzu barındırırsanız 2 GB. |
| Webhook | Yerli destek — `setWebhook` ile HTTPS endpoint'e push. Cloud Run ile birebir uyumlu. |
| Türkiye'de yaygınlık | **Doğrulanamadı.** Türkiye'de bireysel Telegram kullanımı hakkında güvenilir, tarihli bir penetrasyon rakamı bulunamadı. Ancak bu proje için **önemsiz**: tek kullanıcı Burak'ın kendisi. |

Kaynaklar: <https://core.telegram.org/bots/faq> , <https://core.telegram.org/bots/api> ,
<https://pipsync.io/en/blog/telegram-rate-limits>

**ÖNERİ (3a):** **Telegram ile başlayın, WhatsApp'ı erteleyin.**
Telegram: 5 dakikada kurulur, 0 USD, webhook yerli, sesli mesaj desteği mükemmel (bkz. 3b-B).
WhatsApp Cloud API teknik olarak uygun ve **ucuz** (aylık ~1 USD), ama 3-10 iş günü onboarding gerektiriyor —
bunu bir "faz 2" işi yapın; Telegram'da mimariyi kanıtlayıp aynı soyutlamayı WhatsApp'a bağlarsınız.
Kişisel WhatsApp otomasyonu: **kesinlikle hayır.**

---

### 3b) TELEFON / SES — dört ayrı senaryo

#### A) Gerçek zamanlı telefon konuşması (arayıp konuşmak)

**Zincir:** Twilio Voice (PSTN) → Media Streams (WebSocket) → streaming STT → LLM → streaming TTS → geri ses.

**Gecikme bütçesi — "~800 ms" iddiası DOĞRULANDI, nüansıyla:**

| Eşik | Algı |
|---|---|
| < 500 ms | Konuşma gibi hissettirir, kullanıcı boşluğu fark etmez |
| 500–800 ms | Küçük ama fark edilir duraklama; akışı bozmaz |
| **> 800 ms** | **Belirgin gecikme hissi** |
| > 1.500 ms | Kullanıcılar "konuşma bozuk" diyor |

Kök referans: insan konuşmasında sıra devri boşluğu ~200 ms (konuşma analizi literatürü), tek kelimelik bir
yanıtı üretmek bile ~600 ms sürerken. Yani insanlar yanıtı *önceden* planlıyor.

Tipik boru hattı bütçesi: STT 100–300 ms + LLM 350–1.000 ms + TTS 90–200 ms + ağ 50–200 ms.
→ **Toplam kolayca 600–1.700 ms.** 800 ms'in altında kalmak ciddi mühendislik gerektirir.

Kaynaklar: <https://prodinit.com/blog/production-voice-ai-agents-latency-architecture> ,
<https://hamming.ai/resources/voice-ai-latency-whats-fast-whats-slow-how-to-fix-it> ,
<https://thepromptbench.com/voice-and-realtime/latency-budgets-for-realtime-voice/>

**Bu zinciri çözmüş açık kaynak projeler (05.08.2026 itibarıyla GitHub API'den doğrulanmış):**

| Proje | ★ | Lisans | Dil | Durum |
|---|---|---|---|---|
| [pipecat-ai/pipecat](https://github.com/pipecat-ai/pipecat) | **13.935** | **BSD-2-Clause** | Python | Aktif (son push 04.08.2026). Daily tarafından sürdürülüyor. |
| [livekit/agents](https://github.com/livekit/agents) | **12.599** | **Apache-2.0** | Python | Çok aktif (son push 05.08.2026). WebRTC tabanlı. |
| [vocodedev/vocode-core](https://github.com/vocodedev/vocode-core) | **3.781** | **MIT** | Python | **Bakımsız** — son push 15.11.2024. Kullanmayın. |
| [dograh-hq/dograh](https://github.com/dograh-hq/dograh) | 5.130 | (doğrulanmadı) | Python | Self-hosted Vapi/Retell alternatifi, Pipecat üstüne kurulu |

**Türkiye numara/dakika ücreti — DOĞRULANAMADI.**
Twilio'nun Türkiye numara ve Programmable Voice dakika fiyat sayfaları
(`twilio.com/en-us/voice/pricing/tr`, numara fiyat CSV'si) bu ortamın ağ politikası tarafından engellendi
(403). Referans olarak ABD yerel numara ~1,15 USD/ay ve gelen çağrı ~0,0085 USD/dk; Türkiye rakamları
bundan **belirgin biçimde farklı** olacaktır ve tahmin edilmemelidir. Ayrıca Twilio, Türkiye numaraları için
**Regulatory Bundle** (kimlik + adres belgesi) istiyor — yani WhatsApp'a benzer bir belge süreci var.
**Yapılacak:** Twilio Console'da Türkiye için gerçek fiyat ve belge listesi kontrol edilmeli.
Kaynak (belge zorunluluğu): <https://www.twilio.com/docs/phone-numbers/regulatory/faq> ,
<https://www.twilio.com/en-us/guidelines/regulatory>

**A için efor/maliyet özeti:**

| Boyut | Değerlendirme |
|---|---|
| Efor | **Çok yüksek.** Yeni framework (Pipecat/LiveKit), kalıcı WebSocket süreci → Cloud Run'ın istek-tabanlı modelinden çıkış, streaming STT+TTS sağlayıcı seçimi, barge-in/kesme mantığı, telefon numarası regülasyonu. Tahmini **3-6 hafta**. |
| Altyapı | Serverless'a **uymuyor**. Kalıcı süreç gerekir (Fly.io makinesi / Cloud Run + CPU always-on + min-instances). Aylık sabit maliyet kaçınılmaz. |
| Değişken maliyet | Twilio dakika + STT dakika + LLM token + TTS karakter. Kabaca **0,05–0,15 USD/dakika** aralığı (bileşen bazlı; kesin rakam sağlayıcı seçimine bağlı, **doğrulanamadı**). |
| Türkçe riski | Streaming STT'de Türkçe kalitesi İngilizceden düşük. Doğrulanabilir Türkçe streaming WER verisi **bulunamadı**. |

---

#### B) Sesli not → aksiyon (ÖNCELİKLİ)

**B1. Slack sesli mesaj (audio clip) API'den nasıl indirilir?**

**Evet, mümkün — ama "clip" ile "huddle"ı ayırmak şart.**

| Slack ses türü | API'den erişilebilir mi |
|---|---|
| **Audio clip** (kanalda/DM'de kaydedilen ses klibi) | **EVET.** Bir `file` nesnesidir. `file_shared` / `message` olayı gelir → `files.info` → `url_private_download` → `Authorization: Bearer <token>` header'ıyla indirilir. Gereken scope: **`files:read`**. |
| **Huddle** (sesli görüşme) | **HAYIR.** Slack huddle kaydını/transkriptini hiçbir API uç noktasından vermiyor. Sadece `user_huddle_changed` ile katılımcı metadata'sı alınır. Üçüncü taraf (Recall.ai vb.) gerekir. |

Ayrıca: Slack, klip için transkript üretirse `transcript` alanı file nesnesinde bulunabilir —
**bu alanın Türkçe için doldurulup doldurulmadığı doğrulanamadı.** Kendi transkripsiyonunuzu yapmak
daha güvenli.

Kaynaklar: <https://docs.slack.dev/reference/objects/file-object/> ,
<https://medium.com/slack-developer-blog/important-changes-to-files-in-the-web-api-eb38f2a9c1e7> ,
<https://www.recall.ai/blog/get-recordings-and-transcripts-from-slack-huddles-api>

**B2. Telegram sesli mesaj — ne kadar kolay?**

**En kolay kanal, farkla.**
```
update.message.voice.file_id
  → getFile(file_id)  →  {file_path}
  → GET https://api.telegram.org/file/bot<TOKEN>/<file_path>
```
Format: **OGG/Opus** (.oga). Boyut limiti: **20 MB indirme** (public Bot API). Bir sesli not 20 MB'a ancak
~saatlerce konuşmayla ulaşır → pratikte limit yok.

Kaynaklar: <https://core.telegram.org/bots/api> , <https://dev.to/techresolve/solved-convert-voice-memos-from-telegram-to-text-using-openai-whisper-api-41al>

**B3. WhatsApp sesli mesaj — Business API destekliyor mu?**

**Evet.** Gelen `audio` tipi mesajda `media id` gelir → `GET /<MEDIA_ID>` ile geçici indirme URL'i alınır →
access token ile indirilir. Desteklenen formatlar: AAC, MP3, OGG (Opus codec). **Sesli mesaj (voice note)
özellikle OGG/Opus olmalı.** Boyut limiti: **16 MB** (ses/video).

Kaynaklar: <https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/audio-messages> ,
<https://www.chatarchitect.com/news/using-multimedia-in-whatsapp-bots-sending-and-handling-video-audio-and-documents>

**B4. `generate_from_audio()` yeniden kullanılabilir mi? Marjinal efor gerçekten düşük mü?**

Kısa cevap: **Evet, büyük ölçüde. Ama üç gizli zorluk var ve biri varsayımı düzeltiyor.**

**Düzeltme — 20 MB inline sınırı artık 100 MB.**
Gemini API'de inline veri limiti **Ocak 2026'da 20 MB'dan 100 MB'a çıkarıldı**. Yani "20 MB inline sınırı"
varsayımı güncelliğini yitirmiş olabilir. Yine de Google'ın kendi tavsiyesi: toplam istek boyutu büyükse
Files API kullanın. Tek prompt'ta toplam ses uzunluğu üst sınırı: **9,5 saat**.
Kaynaklar: <https://blog.google/innovation-and-ai/technology/developers-tools/gemini-api-new-file-limits/> ,
<https://ai.google.dev/gemini-api/docs/audio> , <https://ai.google.dev/gemini-api/docs/file-input-methods>

**Zorluk 1 — Ön işleme aslında GEREKMEYEBİLİR.**
Gemini ses dosyalarını **kendisi 16 kbps çözünürlüğe indirir ve çok kanallıysa tek kanala birleştirir.**
Yani "16 kHz mono ön işleme" adımının Gemini için ne kadar gerekli olduğu sorgulanmalı — muhtemelen
gereksiz iş. **Not:** Kaynak "16 Kbps" diyor (bit hızı), yaygın olarak alıntılanan "16 kHz" (örnekleme hızı)
ile karıştırılıyor; bu belirsizlik **doğrulanamadı**, Gemini dokümanından teyit edilmeli.
→ Eğer ön işleme gereksizse **`ffmpeg` bağımlılığı tamamen düşer** ve marjinal efor daha da azalır.

**Zorluk 2 — Format çeşitliliği (gerçek zorluk).**
Telegram → OGG/Opus. WhatsApp → OGG/Opus veya AAC/MP3. Slack clip → (format doğrulanmadı, muhtemelen
MP4/AAC veya WebM). Gemini'nin desteklediği MIME tiplerinin bu üçünü de kapsayıp kapsamadığı
**doğrulanmalı**. Kapsamıyorsa `ffmpeg` transcode gerekir → Cloud Run container'ına ffmpeg binary'si
eklemek gerekir (imaj boyutu ↑ → cold start ↑). **Bu, gerçek marjinal eforun kaynağı.**

**Zorluk 3 — Asıl iş transkripsiyon değil, "aksiyona çevirme".**
`generate_from_audio()` size metin verir. Ama "sesli not → aksiyon" için gereken:
sesli notu **yapılandırılmış çıktıya** (görev / takvim daveti / not / e-posta taslağı) dönüştürmek,
belirsiz ifadeleri ("Ahmet'le şu işi konuş") mevcut bağlamla eşleştirmek, ve **onay döngüsü** kurmak
(yanlış anlaşılan sesli not sessizce yanlış aksiyon üretmemeli). Bu, transkripsiyon kodundan **daha büyük**
bir iş.

**Marjinal efor tablosu:**

| Bileşen | Efor | Not |
|---|---|---|
| Ses dosyasını indirmek (Telegram) | ~1 saat | `getFile` + HTTP GET |
| Ses dosyasını indirmek (Slack) | ~2 saat | `files.info` + Bearer header + `files:read` scope |
| Ses dosyasını indirmek (WhatsApp) | ~3 saat | Media ID → URL → token'lı indirme |
| `generate_from_audio()` çağrısı | **~0** | Yeniden kullanılır |
| Format normalizasyonu (gerekirse) | ~4 saat + imaj boyutu maliyeti | ffmpeg |
| **Yapılandırılmış aksiyon çıkarımı + onay döngüsü** | **~2-3 gün** | Asıl iş burada |

**B5. Gemini'nin Türkçe konuşma tanıma kalitesi — doğrulanabilir veri var mı?**

**Türkçe için doğrudan, güvenilir, tarihli bir Gemini WER rakamı BULUNAMADI.** Elde edilenler dolaylı:

- Gemini teknik raporunda (arXiv 2312.11805) Gemini Pro'nun FLEURS ASR'da Whisper ve USM'yi geçtiği
  belirtiliyor; ancak **Gemini FLEURS eğitim setiyle eğitildiği için bu karşılaştırma taraflı**. Rapor,
  FLEURS olmadan eğitilen modelin **WER 15,8** verdiğini ve bunun yine de Whisper'ı geçtiğini söylüyor.
  Bu **çok dilli ortalama**, Türkçeye özel değil.
  <https://arxiv.org/pdf/2312.11805>
- Türkçe için bağımsız bir referans noktası: Whisper mimarisi Türkçe veri kümelerinde **%4,3 – %14,2 WER**
  aralığında ölçülmüş (MDPI, hakemli).
  <https://www.mdpi.com/2079-9292/13/21/4227>

**Dürüst sonuç:** Gemini'nin Türkçe ASR kalitesi hakkında karar verilebilir bir sayı yok.
**Yapılması gereken:** Burak'ın kendi sesiyle 10-20 gerçek sesli not kaydedip Gemini'ye vermek ve
elle değerlendirmek. Bu, herhangi bir benchmark'tan daha bilgilendirici olur (aksan, jargon, kod-değiştirme
"meeting'i reschedule edelim" gibi Türkçe-İngilizce karışımı — benchmark'lar bunu ölçmez).

**B için özet:** Efor **düşük-orta** (transkripsiyon ~0, aksiyon çıkarımı 2-3 gün), maliyet **~0**
(Gemini ses token'ları, mevcut kotada), değer **yüksek** (araba/yürüyüş sırasında kullanılabilir).

---

#### C) Sesli günlük özet (TTS) (ÖNCELİKLİ)

**C1. Google Cloud TTS Türkçe ses seçenekleri ve fiyat**

| Katman | Fiyat (1M karakter) | Ücretsiz/ay | Türkçe (tr-TR) |
|---|---|---|---|
| Standard | **4 USD** | 4M karakter | Var |
| WaveNet | **4 USD** (2026 başında 16'dan düştü) | 4M karakter (Standard ile ortak) | Var |
| Neural2 | **16 USD** | 1M karakter | Var (tam liste doğrulanmadı) |
| **Chirp 3: HD** | **30 USD** | 1M karakter | **Var — tr-TR için 8 konuşmacı** |

Kaynaklar: <https://texttolab.com/blog/google-cloud-tts-pricing> ,
<https://costbench.com/software/ai-voice-tools/google-cloud-text-to-speech/free-plan/> ,
<https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd> ,
<https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types> (erişim 05.08.2026)

**Bu proje için gerçek maliyet hesabı:**
Günlük sesli özet ~3.000 karakter (≈ 3-4 dakikalık konuşma) × 30 gün = **90.000 karakter/ay**.

| Katman | Aylık maliyet |
|---|---|
| Standard/WaveNet | **0 USD** (4M ücretsiz sınırın %2,25'i) |
| Neural2 | **0 USD** (1M ücretsiz sınırın %9'u) |
| **Chirp 3: HD** | **0 USD** (1M ücretsiz sınırın %9'u) |

> **Sonuç: En kaliteli sesi (Chirp 3: HD) kullansanız bile ücretsiz katmanda kalıyorsunuz.**
> Kalite için taviz vermeye gerek yok.

**C2. Gemini'nin kendi TTS'i var mı?**

Evet — `gemini-2.5-flash-preview-tts`. Fiyat kaynakları çelişiyor:
- 0,50 USD/1M giriş token + **10,00 USD/1M çıkış token** (getmaxim.ai, cloudprice.net)
- 0,30 USD/1M giriş + 2,50 USD/1M çıkış (başka bir kaynak)

**Doğrulanamadı — token↔karakter dönüşümü de belirsiz olduğu için Cloud TTS ile doğrudan
karşılaştırılamıyor.** Resmî kaynak: <https://ai.google.dev/gemini-api/docs/pricing>

**Karar:** Cloud TTS bu iş yükünde **kanıtlanabilir biçimde 0 USD** ve Türkçe Chirp3-HD sesleri mevcut.
Gemini TTS'in fiyatı belirsiz ve avantajı net değil. **Cloud TTS kullanın.**

**C3. Üretilen sesi Slack'e nasıl bırakırız?**

- **`files.upload` / `files.uploadV2`** ile MP3/OGG dosyası kanala/DM'e yüklenir. Slack oynatıcı gösterir.
  Gereken scope: `files:write`.
- **Slack "audio clip" olarak yükleyemezsiniz** — clip formatı Slack istemcisinin kendi kayıt akışına özgü.
  API'den yüklenen ses normal bir dosya eki olarak görünür (oynatılabilir ama "klip" UI'ı olmaz).
  Bu bir sorun değil.
- **Daha iyi alternatif:** Telegram `sendVoice` — dosyayı **gerçek sesli mesaj** olarak gönderir
  (dalga formu + oynat butonu + hız kontrolü). OGG/Opus şart. Telefonda dinleme deneyimi Slack'ten
  belirgin biçimde iyi.
  <https://telegram-bot-sdk.readme.io/reference/sendvoice>

**C4. Podcast RSS feed mantıklı mı?**

**Evet, ve efor şaşırtıcı derecede düşük.** Araba/spor senaryosu için doğru çözüm bu, çünkü:
- Podcast uygulamaları **arka planda otomatik indirir** (araçta veri/kapsama sorunu yok)
- **Araç ekranı (CarPlay/Android Auto) entegrasyonu bedava gelir** — Slack/Telegram'da yok
- Oynatma hızı, geri sarma, kaldığı yerden devam — hepsi hazır

**Nasıl:** `python-feedgen` (podcast extension'ı var) ile RSS üret, MP3'leri Google Cloud Storage'a
(ücretsiz katman) veya Cloud Run'dan statik servis et, RSS URL'ini tahmin edilemez bir token'la gizle
(private podcast). Apple Podcasts / Pocket Casts / Overcast hepsi "URL ile abone ol" destekler.
- `lkiesow/python-feedgen` — RSS/Atom/Podcast üretici
- `vpetersson/podcast-rss-generator` — self-hosted ses için RSS üretici (referans implementasyon)

Kaynaklar: <https://feedgen.kiesow.be/> , <https://github.com/lkiesow/python-feedgen> ,
<https://github.com/vpetersson/podcast-rss-generator> , <https://podnews.net/article/self-hosting-podcast-tips>

**Efor: ~1 gün** (feed üretimi + GCS yükleme + token'lı URL).

**C5. Türkçe telaffuz kalitesi — doğrulanabilir bilgi**

**Doğrulanabilir bir Türkçe TTS kalite karşılaştırması (MOS skoru vb.) BULUNAMADI.**
Doğrulanabilen tek şey: Chirp 3: HD modelinin **tr-TR için 8 konuşmacıyla desteklendiği**
(Google Cloud TTS sürüm notları). Kalite hakkında iddiada bulunmuyorum.

**Yapılması gereken:** Aynı Türkçe paragrafı `tr-TR-Standard-*`, `tr-TR-Wavenet-*`, `tr-TR-Chirp3-HD-*`
ile sentezleyip Burak'a dinletin. Özellikle test edilmesi gerekenler: **kısaltmalar (KPI, OEE, ERP),
İngilizce teknik terimler Türkçe cümle içinde, sayı/tarih okuma, özel isimler.** Bunlar Türkçe TTS'in
tipik zayıf noktalarıdır ve otomatik metrikler yakalamaz.

**C için özet:** Efor **düşük** (~1-2 gün), maliyet **0 USD**, değer **yüksek** (yeni bir zaman dilimini —
araba, spor, yürüyüş — sisteme açar).

---

#### D) Arama transkripsiyonu

**Teknik boyut (kısa):**
Twilio Voice fiyatları (2026):

| Kalem | Fiyat |
|---|---|
| Çağrı kaydı | 0,0025 USD/dk |
| Kayıt depolama | 0,0005 USD/dk-ay |
| Batch transkripsiyon | **0,024 USD/dk** |
| Streaming (gerçek zamanlı) transkripsiyon | **0,027 USD/dk** |
| Language Operators (analiz) | 0,0035–0,0040 USD/dk |

Kaynak: <https://quiq.com/blog/twilio-voice-pricing/> , <https://www.twilio.com/en-us/pricing> (05.08.2026)
**Not:** Alternatif olarak kaydı indirip Gemini'ye vermek (bkz. 3b-B) muhtemelen daha ucuz ve zaten yazılmış
koddan yararlanır. Twilio'nun kendi transkripsiyonuna gerek yok.

---

**ASIL KONU: Türkiye'de telefon görüşmesi kaydının hukuki durumu**

> **Bu hukuki tavsiye DEĞİLDİR.** Aşağıdakiler kamuya açık kaynaklardan derlenmiş özetlerdir.
> Uygulamaya geçmeden önce KVKK uyum danışmanı / avukat görüşü alınmalıdır.

**Ceza hukuku boyutu (TCK):**
- **TCK 132** — Haberleşmenin gizliliğini ihlal. **Telefon görüşmeleri bu madde kapsamındadır.**
- **TCK 133** — Kişiler arasındaki konuşmaların dinlenmesi/kayda alınması. Yüz yüze, aleni olmayan
  konuşmalar (aynı odada, araçta, iş yerinde) bu madde kapsamındadır.
- İhlal **içeriğin kaydedilmesi suretiyle** gerçekleşirse **ceza bir kat artırılır.**
- Kaynaklar: <https://barandogan.av.tr/blog/ceza-hukuku/haberlesmenin-gizliligini-ihla-sucu-cezasi.html> ,
  <https://www.fiilhukuk.com/haberlesmenin-gizliligini-ihlal-sucu-ve-gizli-ses-kaydi-tck-132-tck-133/> ,
  <https://www.tahanci.av.tr/haberlesmenin-gizliligini-ihlal-sucu/>

**Veri koruma boyutu (KVKK):**
- Ses kaydı kişisel veridir. İşlemek için KVKK m.5'te sayılan bir hukuki sebep gerekir.
- Kurumsal çağrı merkezi pratiğinde yaygın görüş: kalite/hizmet amaçlı kayıt için **açık rıza şart değil**;
  **meşru menfaat (m.5/2-f)** veya **sözleşmenin ifası (m.5/2-c)** dayanak olabilir.
- **ANCAK: ses biyometrisi / kimlik doğrulama amacıyla kullanılırsa açık rıza ZORUNLUDUR** (özel nitelikli
  kişisel veri).
- **Aydınlatma yükümlülüğü her hâlükârda vardır** — hukuki sebep ne olursa olsun. KVKK Tebliği, aydınlatmanın
  ses kaydı / çağrı merkezi gibi ortamlarda da yerine getirilebileceğini düzenler ("Bu görüşme kayıt
  altına alınmaktadır" anonsu bu yüzden vardır).
- KVK Kurulu, bir bankanın çağrı merkezinin **aydınlatma yapmadan ve açık rıza almadan** arama yaparak
  kişisel veri işlemesini ihlal saymıştır (Karar 2022/863).
- KVK Kurulu, **açık rıza alınmadan ses kaydı alınması, paylaşılması ve mahkeme dosyasına sunulmasını**
  ayrı bir kararda incelemiştir (Karar 2023/1548).
- Kaynaklar: <https://www.kvkk.gov.tr/Icerik/7582/2022-863> , <https://www.kvkk.gov.tr/Icerik/7777/2023-1548> ,
  <https://kvkk.gov.tr/Icerik/5443/AYDINLATMA-YUKUMLULUGUNUN-YERINE-GETIRILMESINDE-UYULACAK-USUL-VE-ESASLAR-HAKKINDA-TEBLIG>

**Pratik sonuç — bu proje için:**

| Senaryo | Durum |
|---|---|
| Burak'ın **kendi sesli notunu** kaydetmesi (3b-B) | **Sorun yok.** Tek taraf, kendisi. |
| Burak'ın **kendi telefon görüşmesini** kaydetmesi | **Riskli.** Karşı tarafın bilgisi yoksa TCK 132/133 riski var. Kurumsal bağlamda ayrıca aydınlatma yükümlülüğü doğar. |
| Sistemin **otomatik** olarak görüşmeleri kaydetmesi | **Yapmayın.** Aydınlatma anonsu, saklama süresi politikası, KVKK envanteri, veri sorumlusu sıfatı… bunların hepsi kurumsal bir uyum projesidir, bir yan özellik değil. |
| **Toplantı notu** (halihazırda projede var) | Katılımcılar bilgilendirilmiş ve kayıt toplantı platformunun kendi özelliğiyse durum farklı — yine de aydınlatma gerekir. |

**ÖNERİ (D):** **Otomatik arama transkripsiyonunu kapsam dışı bırakın.** Teknik efor düşük ama
hukuki/uyum eforu (aydınlatma metni, saklama politikası, KVKK envanteri, muhtemelen hukuk danışmanlığı)
teknik eforun kat kat üzerinde ve Burak'ı kişisel olarak riske sokabilir. Değeri de B'nin (sesli not)
üzerine çok az şey katıyor.

---

### 3b ÖNERİ — B ve C önce, A ertelenmeli mi?

**EVET, kesinlikle. Gerekçe:**

| | **B (Sesli not → aksiyon)** | **C (Sesli özet / TTS)** | **A (Gerçek zamanlı konuşma)** |
|---|---|---|---|
| Efor | 2-4 gün | 1-2 gün | **3-6 hafta** |
| Aylık maliyet | ~0 USD | **0 USD** (ücretsiz katmanda) | Sabit altyapı + 0,05-0,15 USD/dk |
| Mimari değişiklik | Yok (mevcut Cloud Run) | Yok | **Var** — kalıcı WebSocket süreci, serverless'tan çıkış |
| Yeni bağımlılık | (belki ffmpeg) | `google-cloud-texttospeech`, `feedgen` | Pipecat/LiveKit + streaming STT + telefon regülasyonu |
| Türkçe riski | Orta (ölçülmeli) | Orta (dinlenmeli) | **Yüksek** (streaming STT Türkçe verisi yok) |
| Türkiye regülasyonu | Yok | Yok | Twilio Regulatory Bundle + belge |
| Başarısızlık maliyeti | Düşük (metni düzeltirsiniz) | Düşük (okursunuz) | **Yüksek** (konuşma ortasında kopan bot) |

**A'nın B+C üzerine kattığı marjinal değer nedir?**

B + C birlikte şu döngüyü zaten kapatıyor:
```
Burak konuşur (sesli not)  →  sistem anlar ve aksiyon alır      [B]
Sistem konuşur (günlük özet podcast/sesli mesaj)  →  Burak dinler [C]
```
Bu **asenkron ama tam** bir sesli arayüzdür. A'nın eklediği tek şey **eşzamanlılık** — yani "cevabı hemen,
konuşma sırasında almak" ve "çok turlu diyalog".

Marjinal değer gerçekten var mı? Üç senaryoda var:
1. **Ellerin dolu + acil**: araba kullanırken bir kararı hemen netleştirmek. Ama B ile sesli not bırakıp
   30 saniye sonra sesli yanıt almak (C) bunun **%80'ini** karşılıyor.
2. **Belirsizliğin çözülmesi**: "hangi Ahmet?" sorusunun anında sorulması. B'de bu bir onay mesajıyla çözülür.
3. **Üçüncü taraflarla konuşma** (asistanın Burak adına birini araması) — bu tamamen farklı ve çok daha
   riskli bir ürün; ayrıca Türkiye'de otomatik arama regülasyonu ayrı bir konu.

**Sonuç:** A'nın marjinal değeri **eforunun 10-15 katı altında.** Ayrıca B+C çalıştıktan sonra A'yı
yapmak *daha kolay* olur — çünkü ses formatı işleme, Türkçe kalite kalibrasyonu, TTS ses seçimi ve
"sesli komut → aksiyon" mantığı zaten yazılmış olur. A'ya yatırım yapmadan önce şu soruyu ölçün:
**B ve C canlıya alındıktan 1 ay sonra Burak hâlâ "keşke konuşabilseydim" diyor mu?** Demiyorsa A gereksizdir.

**Sıralama: C (1-2 gün, 0 USD, en hızlı görünür değer) → B (2-4 gün, en yüksek değer) → D (yapmayın) → A (ertelenir).**

---

### 3c) Takvim / Notlar / Sunum

| API | Mümkün mü | Kısıtlar | Efor |
|---|---|---|---|
| **Google Slides API** | **Evet** | Sayfa boyutu API'den **değiştirilemez** → her slayt zorunlu **16:9**. `presentations.create` şablon/master kabul etmez, boş slayt üretir → **çözüm: Drive API ile şablon dosyasını kopyala, sonra `batchUpdate`**. Özel şekil/ikon ekleme yok (sadece standart şekiller). GET ve `batchUpdate` şemaları 1:1 değil → elle çeviri gerekir. | Orta-Yüksek |
| **Google Docs API** | **Evet, en olgun yol** | Şablon dokümanı Drive API ile kopyala → `documents.batchUpdate` + `replaceAllText` ile `{{placeholder}}` doldur. Regex desteklenmiyor (issuetracker 265842859). Tablo/grafik eklemek metin değiştirmekten belirgin biçimde zor. | **Düşük** |
| **Google Keep API** | **Pratikte hayır** | API **yalnızca Google Workspace** (Business/Enterprise/Education) hesapları için; **kişisel @gmail.com hesaplarında yok**. Workspace admin'in domain-wide delegation ile etkinleştirmesi gerekir; kullanıcı kendi başına açamaz. Amaç da "yönetici not yönetimi", kişisel not alma değil. Gayriresmî `gkeepapi` var ama desteklenmiyor. | — |

Kaynaklar: <https://developers.google.com/workspace/slides/api/guides/overview> ,
<https://www.flashdocs.com/post/google-slides-api-comprehensive-guide-for-developers> ,
<https://www.bentumbleson.com/experiments-with-the-google-slides-api-to-recreate-slides/> ,
<https://developers.google.com/workspace/docs/api/how-tos/merge> ,
<https://developers.google.com/workspace/keep/api/guides> , <https://issuetracker.google.com/issues/263769283>

**ÖNERİ (3c):** **Docs API ile başlayın** — şablon kopyala + `replaceAllText` kalıbı en düşük efor/en yüksek
güvenilirlik. Slides'ı ancak Burak'ın gerçekten yönetime sunum götürmesi gerekiyorsa yapın; o zaman da
"sıfırdan üret" değil **"elle tasarlanmış şablonu Drive'dan kopyala + doldur"** kalıbını kullanın.
Keep'i **kapsam dışı bırakın** — kişisel hesapta API yok. Not tutma için Docs veya mevcut Drive yapısı yeterli.

---

## BÖLÜM 4 — DASHBOARD DIŞI RAPORLAMA / ALARM MEKANİZMALARI

| # | Mekanizma | Efor | Aylık maliyet | Burak'ın iş akışına uygunluk | Karar |
|---|---|---|---|---|---|
| 1 | **E-posta digest (HTML)** | Düşük (1-2 gün) | **0 USD** (Gmail API) veya 0 USD (Resend free 3.000/ay) | **Yüksek** — Ops Director günü e-postayla açar; arşivlenebilir, aranabilir, iletilebilir | **YAP (1. sırada)** |
| 2 | **PDF rapor** | Orta (2-3 gün) | 0 USD | Orta — aylık/çeyreklik yönetim raporu için; günlük için abartı | Yap (2. faz) |
| 3 | **Google Sheets canlı pano** | Düşük-Orta (2 gün) | 0 USD | **Yüksek** — Ops ekipleri zaten Sheets'te yaşar; Burak veriyi kendisi kesip biçebilir | **YAP (2. sırada)** |
| 4 | **Takvim bloklama (derin çalışma)** | Düşük (1 gün) | 0 USD | Yüksek ama **davranışsal risk** | Yap, ama **öneri modunda** |
| 5 | **Slack Canvas** | Orta | Slack **ücretli plan gerekir** | Orta | **Erteleyin** |
| 6 | **Sesli özet (TTS + podcast)** | Düşük (1-2 gün) | **0 USD** | Yüksek — yeni zaman dilimi açar (araba/spor) | **YAP** (bkz. 3b-C) |

### Detaylar

**1. E-posta digest.**
- **Gönderim:** Gmail API ile Burak'ın kendi hesabından kendine göndermek en basit ve ücretsiz.
  **DİKKAT — mevcut `requirements.txt`'te `sendgrid==6.10.0` var.** Twilio, SendGrid'in kalıcı ücretsiz
  planını **27 Mayıs 2025'te sonlandırdı**; 26 Temmuz 2025 itibarıyla ücretsiz katman tamamen kapandı.
  Yeni hesaplar 60 günlük deneme (100 e-posta/gün) sonrası **19,95 USD/ay**'dan başlıyor.
  **Bu bağımlılık ya kaldırılmalı ya da Resend (3.000 e-posta/ay ücretsiz, kalıcı) ile değiştirilmeli.**
  Kaynaklar: <https://www.twilio.com/en-us/changelog/sendgrid-free-plan> , <https://resend.com/blog/new-free-tier>
- **Şablon kalıbı:** Jinja2 + **inline CSS** (Gmail `<style>` bloklarını kısmen atar) + tablo tabanlı layout.
  MJML kullanılacaksa Node bağımlılığı gelir — bu Python projesinde gereksiz. **Jinja2 + elle inline CSS yeterli.**
- **İçerik kalıbı:** "Dün ne oldu / bugün ne var / dikkat gerektirenler / bekleyen kararlar" —
  4 blok, her biri max 5 madde.

**2. PDF rapor — WeasyPrint mi ReportLab mı?**

| | **WeasyPrint** | **ReportLab** |
|---|---|---|
| Model | HTML+CSS → PDF | Programatik çizim API'si |
| **Türkçe karakter** | HTML'de `<meta charset="utf-8">` doğru ise sorunsuz; font yapılandırması gerekmez | **Font'u elle yüklemek zorunlu** (`pdfmetrics.registerFont` + TTF). Varsayılan Type-1 fontlar Latin-1 varsayar → ş/ğ/ı/İ bozulur |
| **Tablo desteği** | CSS tabloları — sayfa kırılması, tekrar eden başlık (`thead`), hücre birleştirme hepsi CSS'ten gelir | `Table` flowable'ı güçlü ama **her stil elle kodlanır** |
| Şablon yeniden kullanımı | **E-posta digest'iyle aynı Jinja2 şablonunu paylaşabilir** | Ayrı kod tabanı |
| Bağımlılık | Sistem kütüphaneleri (Pango, Cairo, GDK-PixBuf) → **Docker imajına apt paketleri eklenmeli** | Saf Python (+ Pillow) → hafif |

**Karar: WeasyPrint.** Belirleyici sebep **kod paylaşımı** — aynı Jinja2 şablonu hem HTML e-posta digest'i
hem PDF üretir. Türkçe karakter avantajı da net. Bedeli: Docker imajına sistem kütüphaneleri eklemek
(imaj boyutu ↑ → Cloud Run cold start ↑). **Çözüm: PDF üretimini Slack/webhook servisinden ayrı bir
Cloud Run job'ında çalıştırın** — böylece sıcak yoldaki servis hafif kalır.
Kaynaklar: <https://kaijuconverter.com/guides/convert-markdown-to-pdf-python-guide> ,
<https://behainguyen.wordpress.com/2022/05/30/python-reportlab-how-utf-8-gets-displayed-by-browsers-and-pdf-creation-tools/> ,
<https://pypi.org/project/weasyprint/>

**3. Google Sheets canlı pano — API ile formül ve grafik kurulabilir mi?**

**Evet, tamamen.** `spreadsheets.batchUpdate` ile:
- **Grafik:** `AddChartRequest` → `EmbeddedChart` döner. `chartId` verilmezse otomatik üretilir.
- **Koşullu biçimlendirme:** `AddConditionalFormatRuleRequest` (0-tabanlı index ile eklenir; sonraki
  kuralların index'i kayar).
- **Formül:** `values.update` ile `valueInputOption=USER_ENTERED` gönderirsen `=SUM(...)` formül olarak yazılır
  (`RAW` gönderirsen düz metin olur — sık yapılan hata).

Kaynaklar: <https://developers.google.com/workspace/sheets/api/samples/conditional-formatting> ,
<https://googleapis.dev/java/google-api-services-sheets/latest/index-all.html>

**Kalıp önerisi:** Ham veriyi bir "veri" sekmesine yazın (append-only), grafikleri ve formülleri
**bir kez** kurun. Her gün grafiği yeniden yaratmayın — veri satırı ekleyin, grafik kendi güncellenir.
Bu hem API çağrısını azaltır hem Burak'ın kendi eklediği formülleri ezmez.

**4. Takvim bloklama — sistem otomatik "derin çalışma" bloğu açabilir mi?**

**Evet.** `events.insert` ile:
- `eventType: "focusTime"` + `focusTimeProperties` alanı
- `transparency: "opaque"`
- Zamanlı etkinlik olmalı (tüm gün etkinliği olamaz)

**Kritik kısıt: Focus Time bir Google Workspace özelliğidir, kişisel Google hesaplarında yoktur.**
Burak Workspace kullanmıyorsa normal bir `event` (busy) oluşturun — işlev aynı, sadece Focus Time'ın
otomatik bildirim-susturma özelliği olmaz.

Kaynaklar: <https://developers.google.com/workspace/calendar/api/guides/calendar-status> ,
<https://workspaceupdates.googleblog.com/2023/11/calendar-api-read-write-out-of-office-and-focus-time-events.html>

> **Davranışsal uyarı:** Takvimine izinsiz blok koyan bir sistem, ilk yanlış kararında güveni yakar
> (bir toplantı çakışması yeter). **Önerilen kalıp:** Sistem Slack'e "yarın 09:00-11:00 boş, derin çalışma
> bloğu açayım mı? [Evet] [Hayır] [Başka saat]" butonlu mesaj atsın. Onay alınca ekle. Bu aynı zamanda
> Slack etkileşimli endpoint'ini (Bölüm 1c) ilk gerçek kullanım senaryosuyla test eder.

**5. Slack Canvas.**
- API: `canvases.create`, `canvases.edit`, `canvases.access.set`. Scope: **`canvases:write`**.
- **Plan kısıtı:** Kanal ve DM canvas'ları tüm planlarda; **bağımsız (standalone) canvas'lar yalnızca
  ücretli planlarda.** Ücretsiz workspace'te `canvases.create` çağrısında **`channel_id` zorunlu alan**.
- Kaynaklar: <https://docs.slack.dev/reference/methods/canvases.create/> ,
  <https://slack.com/help/articles/27204752526611-Feature-limitations-on-the-free-version-of-Slack>

**ÖNERİ (Bölüm 4):** Şu sırayla yapın:
**(1) E-posta digest** (Jinja2 + Gmail API, SendGrid'i sökün) →
**(2) Google Sheets canlı pano** (append + tek seferlik grafik kurulumu) →
**(3) Sesli özet/podcast** (Bölüm 3b-C ile birleştirin, aynı içerik üreticisini paylaşırlar) →
**(4) Takvim bloklama, onay butonlu** →
**(5) PDF** (aylık ritim oturunca, e-posta şablonunu yeniden kullanarak) →
**(6) Slack Canvas'ı ertelein** (plan kısıtı + diğerlerinin üstüne az şey katıyor).

**Ortak tasarım ilkesi:** Hepsi **tek bir "günlük özet nesnesi"nden** (yapılandırılmış dict/pydantic modeli)
beslensin. Sonra render katmanları: `→ HTML e-posta`, `→ Sheets satırı`, `→ TTS metni`, `→ PDF`, `→ Slack mesajı`.
Beş ayrı rapor üreticisi yazarsanız beşi de birbirinden sapar.

---

## BÖLÜM 5 — BENZER PROJELER (olay güdümlü)

GitHub API'den 05.08.2026 tarihinde doğrulanmış veriler:

| Proje | ★ | Lisans | Dil | Son push | İlgili olduğu yer |
|---|---|---|---|---|---|
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | **385.200** | **NOASSERTION** (özel lisans — ticari kullanım için okunmalı) | TypeScript | 05.08.2026 | Mesajlaşma platformlarını (Slack/Discord/iMessage/WhatsApp) birincil arayüz yapan kişisel ajan. Cron + **webhook tetikleyicileri** var. |
| [elie222/inbox-zero](https://github.com/elie222/inbox-zero) | **11.865** | **NOASSERTION** | TypeScript | 05.08.2026 | **Gmail odaklı, üretimde çalışan bir ürün.** Slack/Telegram'dan kontrol. Gmail watch/push kalıbının en olgun açık kaynak örneği. |
| [theexperiencecompany/gaia](https://github.com/theexperiencecompany/gaia) | **256** | **NOASSERTION** (Polyform Strict — **ticari kullanım yasak**) | **Python** | 05.08.2026 | **Açıkça "event-driven"**: Gmail, Calendar ve Linear/Slack/GitHub/Todoist/Sheets/Docs webhook'larına tepki verir. Python + FastAPI. **Mimari olarak en yakın eşleşme.** |
| [kaymen99/personal-ai-assistant](https://github.com/kaymen99/personal-ai-assistant) | 179 | (lisans dosyası yok) | Python | 16.01.2025 (**bakımsız**) | WhatsApp/Slack/Telegram + e-posta/takvim. LangGraph. Referans olarak bakılabilir, bağımlılık kurulmamalı. |
| [slackapi/bolt-python](https://github.com/slackapi/bolt-python) | 1.319 | **MIT** | Python | 04.08.2026 | **Doğrudan kullanılacak.** Lazy Listeners = Slack 3 sn probleminin resmî çözümü. |
| [byeokim/gmailpush](https://github.com/byeokim/gmailpush) | 56 | **MIT** | JavaScript | 02.10.2023 (bakımsız) | Gmail push handler. Kod olarak değil, **historyId yönetimi ve watch yenileme mantığı için okunacak referans.** |

**Voice framework'leri** (Bölüm 3b-A'da detaylı):
`pipecat-ai/pipecat` 13.935★ BSD-2-Clause · `livekit/agents` 12.599★ Apache-2.0 · `vocodedev/vocode-core`
3.781★ MIT (**bakımsız, 15.11.2024'ten beri push yok**).

### "Bu mimariyi zaten çözmüş bir proje var mı, ondan ne ödünç alınır?"

**Tam eşleşen bir proje yok**, ama üç yerden somut şey alınır:

1. **GAIA (`theexperiencecompany/gaia`) — mimari şablon.**
   Python + FastAPI + olay güdümlü + Gmail/Calendar/Slack webhook'ları. Bu projenin yığınıyla neredeyse
   birebir. **Ödünç alınacak:** webhook ingest → normalize edilmiş olay → ajan dispatch katmanlaması;
   çoklu entegrasyonda kimlik/token yönetimi.
   **⚠️ LİSANS ENGELİ: Polyform Strict — ticari kullanıma izin vermiyor.** Burak'ın kurumsal kullanımı
   için **kod kopyalanamaz.** Sadece **mimariye bakılır, kod alınmaz.** Bu ayrımı ciddiye alın.

2. **inbox-zero — Gmail push'un üretim kalitesinde referansı.**
   **Ödünç alınacak:** `historyId` kalıcılığı, watch yenileme zamanlaması, tekrarlı bildirim (duplicate)
   idempotency stratejisi, Gmail kotası yönetimi. Lisans NOASSERTION → **kod kopyalamadan önce
   LICENSE dosyası okunmalı.** TypeScript olduğu için zaten doğrudan kopyalanamaz; kalıp öğrenilir.

3. **bolt-python Lazy Listeners — doğrudan kullanılacak tek şey.**
   MIT, aktif, resmî. Bu projeye **bağımlılık olarak zaten var** (`slack-bolt==1.18.0`).
   `process_before_response=True` + lazy listener kalıbı, Bölüm 1c'deki 3 saniye probleminin
   hazır çözümü. **Sürüm güncellenmeli** (1.18.0 Eylül 2023 civarı; 2026'da daha yeni sürümler var).

**Dikkat çeken şey:** Yüksek yıldızlı projelerin **hepsi NOASSERTION veya kısıtlayıcı lisans**.
Bu alanda ticarileşme baskısı yüksek. **Serbestçe ödünç alınabilecek (MIT/Apache/BSD) tek şeyler:
`bolt-python`, `pipecat`, `livekit/agents`, `google-api-python-client`.**

**ÖNERİ (Bölüm 5):** GAIA'nın **mimarisini** okuyun (kodunu değil — lisans engeli), inbox-zero'dan
**Gmail historyId + watch yenileme kalıbını** öğrenin, `bolt-python` Lazy Listeners'ı **doğrudan kullanın**.
Hiçbirini fork'lamayın — hepsi bu projenin ihtiyacından farklı bir ürün için optimize edilmiş.
Ödünç alınacak şey kod değil, **çözülmüş problemlerin listesi**.

---

## GENEL ÖNERİ — ÖNCELİKLENDİRİLMİŞ YOL HARİTASI

| Sıra | İş | Efor | Aylık maliyet | Neden bu sırada |
|---|---|---|---|---|
| 1 | **Cloud Run'a FastAPI deploy + Slack HTTP Events endpoint** (bolt-python lazy listeners) | 3-5 gün | 0 USD (min-instances kapalıyken) | Tüm diğer işlerin önkoşulu. Etkileşimi açar. |
| 2 | **E-posta digest** (Jinja2 + Gmail API) + **SendGrid bağımlılığını sök** | 1-2 gün | 0 USD | En hızlı görünür değer, mevcut veriden besleniyor |
| 3 | **Sesli günlük özet** (Cloud TTS Chirp3-HD tr-TR + Telegram sendVoice / private podcast RSS) | 1-2 gün | **0 USD** | Ücretsiz katmanda kalıyor, yeni zaman dilimi açıyor |
| 4 | **Gmail push** (`users.watch` + Pub/Sub → Cloud Run) + günlük yenileme cron + yedek yoklama | 3-4 gün | ~0 USD | Gecikmeyi 15 dk → saniyeler |
| 5 | **Sesli not → aksiyon** (Telegram + Slack clip → `generate_from_audio()` → yapılandırılmış aksiyon + onay) | 2-4 gün | ~0 USD | 3'teki TTS altyapısını tamamlar; çift yönlü ses |
| 6 | **Google Sheets canlı pano** | 2 gün | 0 USD | Ops kültürüne en uygun format |
| 7 | **Calendar watch** + onay butonlu derin çalışma bloğu | 2-3 gün | 0 USD | 1'deki Slack etkileşimini kullanır |
| 8 | **PDF rapor** (WeasyPrint, ayrı Cloud Run job) | 2-3 gün | 0 USD | Aylık ritim oturunca |
| 9 | WhatsApp Cloud API | 2 gün kod + **3-10 iş günü onay** | ~1 USD | Onay süreci paralel yürütülebilir |
| — | **YAPILMAYACAKLAR** | | | |
| ✗ | Gerçek zamanlı telefon asistanı (3b-A) | 3-6 hafta | Yüksek | Marjinal değer eforu haklı çıkarmıyor; B+C %80'ini veriyor |
| ✗ | Otomatik arama transkripsiyonu (3b-D) | Düşük teknik | **Hukuki risk** | KVKK/TCK uyum eforu teknik eforun katı |
| ✗ | Kişisel WhatsApp otomasyonu | Düşük | **Ban riski** | İş iletişiminin kesilmesi riski |
| ✗ | Google Keep | — | — | Kişisel hesapta API yok |
| ✗ | Slack Canvas | Orta | Ücretli plan | Getirisi düşük |
| ✗ | Drive `changes.watch` | Orta | 0 USD | 7 günlük kanal yenilemesi, gecikme önemsiz — cron kalsın |

**Toplam öngörülen aylık işletme maliyeti (1-8 arası): ~0-10 USD.**
(0 USD, Slack için `min-instances=1` kullanılmazsa; ~5-10 USD kullanılırsa — bu rakam **doğrulanamadı**,
GCP fiyat hesaplayıcısıyla ölçülmeli.)

---

## DOĞRULANAMAYANLAR LİSTESİ

Bu belgede aşağıdakiler **doğrulanamadı** ve tahmin edilmedi:

1. **Twilio Türkiye numara kiralama aylık ücreti** ve **Programmable Voice Türkiye dakika ücreti** —
   Twilio fiyat sayfaları bu ortamdan erişilemedi (HTTP 403). Twilio Console'dan kontrol edilmeli.
2. **Twilio Türkiye SMS gönderim ücreti** — aynı sebep.
3. **Netgsm / İleti Merkezi güncel birim SMS fiyatı** — Netgsm paket sayfası "1.000 SMS 899 TL"den
   bahsediyor ama tarih ve paket detayı doğrulanamadı.
4. **Gemini TTS fiyatı** — kaynaklar çelişiyor (10 USD/1M çıkış token vs 2,50 USD/1M). Token↔karakter
   dönüşümü de bilinmiyor.
5. **Gemini'nin Türkçe ASR WER değeri** — hiçbir güvenilir kaynakta Türkçeye özel Gemini rakamı yok.
6. **Google TTS Türkçe telaffuz kalitesi** (MOS vb.) — karşılaştırmalı veri yok.
7. **Gemini ses ön işleme**: kaynak "16 Kbps"e indirdiğini söylüyor; yaygın olarak "16 kHz" diye
   aktarılıyor. Hangisi doğru — Gemini resmî dokümanından teyit edilmeli.
8. **Slack audio clip dosya formatı** (MIME tipi) — Gemini'nin desteklediği formatlarla uyumlu mu,
   test edilmeli.
9. **Slack file nesnesindeki `transcript` alanının Türkçe için dolup dolmadığı.**
10. **Cloud Run `min-instances=1` için gerçek aylık maliyet** — iş yüküne bağlı, hesaplayıcıyla ölçülmeli.
11. **Türkiye'de Telegram kullanım yaygınlığı** — güvenilir, tarihli penetrasyon verisi bulunamadı.
    (Bu proje için önemsiz: tek kullanıcı var.)
12. **Türkiye WhatsApp utility fiyatının 1 Temmuz 2026 sonrası kesin değeri** — %84 indirim raporlanıyor
    ama indirim sonrası kesin rakam ikincil kaynaklarda tutarsız.

**Erişim engeli notu:** `developers.google.com`, `cloud.google.com`, `docs.cloud.google.com`,
`api.slack.com`, `docs.slack.dev`, `twilio.com`, `developers.cloudflare.com`, `blog.google` alan adlarına
bu araştırma ortamından doğrudan sayfa çekilemedi (proxy 403). Bu kaynaklardaki bilgiler arama sonuçları
ve ikincil kaynaklar üzerinden derlendi. **Uygulamaya geçmeden önce resmî dokümanlardan teyit edilmeli.**
