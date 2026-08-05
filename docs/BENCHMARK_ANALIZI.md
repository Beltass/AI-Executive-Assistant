# Benchmark ve Dürüst Değerlendirme

**Tarih:** 5 Ağustos 2026
**Kapsam:** Açık kaynak rakip/komşu proje araştırması + bu deponun ölçülmüş durumu + entegrasyon önerileri
**Yöntem:** Yıldız sayıları ve lisanslar 5 Ağustos 2026'da ilgili GitHub sayfalarından okundu. Yerel ölçümler bu depoda gerçekten çalıştırıldı. Doğrulayamadığım her şey açıkça "doğrulanamadı" olarak işaretlendi.

> **Uyarı — GitHub API erişimi kısıtlıydı.** Bu oturumda `api.github.com` yalnızca `Beltass/AI-Executive-Assistant` için açıktı. Diğer tüm depo verileri GitHub'ın **HTML sayfalarından** okundu. Bu yüzden yıldız sayıları GitHub'ın yuvarlanmış gösterimidir (ör. "36.2k"), tam sayı değildir. **Son commit tarihleri HTML'den güvenilir biçimde okunamadı — bu sütun bilinçli olarak "doğrulanamadı" bırakıldı.**

---

## BÖLÜM 1 — Araştırma: Gerçek ve Aktif Açık Kaynak Projeler

### A) AI Kişisel / Yönetici Asistanı

| Depo | URL | Yıldız (05.08.2026) | Lisans | Stack | Ne yapar | Self-host |
|---|---|---|---|---|---|---|
| `khoj-ai/khoj` | https://github.com/khoj-ai/khoj | 36.2k | **AGPL-3.0** | Python + Next.js | "İkinci beyin": kendi dokümanların ve web üzerinden yanıt, özel ajanlar, zamanlanmış otomasyonlar. Tarayıcı/Obsidian/Emacs/telefon/WhatsApp arayüzleri. | Evet (Docker, macOS, Linux, Windows) |
| `leon-ai/leon` | https://github.com/leon-ai/leon | 17.4k | MIT | Node.js ≥24 + TypeScript, Python beceriler | Kişisel sesli asistan; beceri (skill) tabanlı. 2.0 Developer Preview `develop` dalında sürüyor. | Evet |
| `All-Hands-AI/OpenHands` | https://github.com/All-Hands-AI/OpenHands | 83.2k | MIT | TypeScript + Python | Kodlama ajanları ve otomasyonlar için self-host kontrol merkezi. | Evet |
| `Significant-Gravitas/AutoGPT` | https://github.com/Significant-Gravitas/AutoGPT | ~185.8k | **Karma:** `autogpt_platform/` → Polyform Shield 1.0.0; `classic/` ve gerisi → MIT | Python | Otonom ajan platformu. **Platform kısmı Polyform Shield — rakip ürün üretimini yasaklar.** | Evet (kısıtlı lisans) |
| `crewAIInc/crewAI` | https://github.com/crewAIInc/crewAI | 56.6k | **MIT** | Python | Rol tabanlı çok-ajanlı iş akışı framework'ü. Yüksek seviye soyutlama + düşük seviye API. | Evet (kütüphane) |
| `microsoft/autogen` | https://github.com/microsoft/autogen | 60.2k | MIT (kod) + CC-BY-4.0 (dokümantasyon) | Python | Çok-ajanlı konuşma framework'ü. | Evet (kütüphane) |
| `langchain-ai/langgraph` | https://github.com/langchain-ai/langgraph | 38.9k | **MIT** | Python | Durum tutan (stateful) ajanlar için düşük seviye orkestrasyon; graf tabanlı, checkpoint/kalıcılık dahili. | Evet (kütüphane) |
| `langgenius/dify` | https://github.com/langgenius/dify | 151.4k | **Dify Open Source License** (Apache 2.0 + ek koşullar — çok-kiracılı SaaS olarak yeniden satış kısıtlı) | Python + TypeScript/Next.js | Görsel LLM uygulama geliştirme platformu: workflow, RAG, ajan, gözlemlenebilirlik. | Evet |
| `n8n-io/n8n` | https://github.com/n8n-io/n8n | 199.4k | **Sustainable Use License** (fair-code — açık kaynak DEĞİL; "hizmet olarak sunma" yasak) | TypeScript | 400+ entegrasyonlu görsel iş akışı otomasyonu, yerleşik AI düğümleri. | Evet (lisans kısıtlı) |
| `activepieces/activepieces` | https://github.com/activepieces/activepieces | 23.6k | MIT (Community Edition) + ticari (enterprise özellikler) | TypeScript | Zapier'in açık kaynak muadili; tip güvenli "pieces" framework'ü. | Evet |

### B) Slack Bot + LLM

| Depo | URL | Yıldız | Lisans | Stack | Ne yapar |
|---|---|---|---|---|---|
| `slackapi/bolt-python` | https://github.com/slackapi/bolt-python | 1.3k | MIT | Python | Slack'in **resmî** Python app framework'ü: event listener, async, Socket Mode. 1.016 commit. |
| `slackapi/bolt-js` | https://github.com/slackapi/bolt-js | 2.9k | MIT | TypeScript | Aynısının JS sürümü. |
| `seratch/ChatGPT-in-Slack` | https://github.com/seratch/ChatGPT-in-Slack | **513** | MIT | Python | Slack içinde ChatGPT: thread, DM, Home tab, çok turlu bağlam, DALL-E 3, çeviri/düzeltme. Bolt-Python yazarının referans uygulaması. |

> **Not:** Bu kategori beklenenden çok daha küçük. 513 yıldızlık bir referans uygulaması, bu alanın en bilinen açık kaynak örneği. Yani "Slack + LLM" olgun bir *ürün* değil, olgun bir *kütüphane* (Bolt) üstünde herkesin kendi yazdığı bir katman. Bu deponun Slack katmanının sıfırdan yazılmış olması bu yüzden mantıksız değil.

### C) İçerik Üretimi / Sosyal Medya Otomasyonu

| Depo | URL | Yıldız | Lisans | Stack | Ne yapar | Self-host |
|---|---|---|---|---|---|---|
| `gitroomhq/postiz-app` | https://github.com/gitroomhq/postiz-app | 34.3k | **AGPL-3.0** | Next.js + NestJS + Prisma/PostgreSQL + Temporal | Buffer/Hypefury alternatifi. **17 ağ:** Instagram, YouTube, LinkedIn, Reddit, TikTok, Facebook, Pinterest, Threads, X, Slack, Discord, Mastodon, Bluesky, Dribbble vd. | Evet |
| `inovector/mixpost` | https://github.com/inovector/mixpost | 3.5k | MIT | PHP (Laravel) | Self-host sosyal medya yönetimi; Lite sürüm açık, Pro ticari. 397 commit. | Evet |

### D) Toplantı Transkripsiyonu + Aksiyon Maddeleri

| Depo | URL | Yıldız | Lisans | Stack | Ne yapar | Self-host |
|---|---|---|---|---|---|---|
| `Zackriya-Solutions/meetily` | https://github.com/Zackriya-Solutions/meetily | 28.3k | MIT | **Rust** + Whisper/Parakeet | Bot'suz (sistem sesi) toplantı kaydı, canlı transkripsiyon, konuşmacı ayrımı, Ollama/Claude/Groq/OpenAI ile özet. macOS + Windows. **Sayfada "aksiyon maddesi çıkarma" özelliği ayrıca belirtilmiyor — özet üretiyor.** | Evet (%100 yerel) |
| `Vexa-ai/vexa` | https://github.com/Vexa-ai/vexa | 2.6k | **Apache-2.0** | TypeScript monorepo | Google Meet/Teams/Zoom/Jitsi'ye **bot olarak katılıp** konuşmacı etiketli transkripti gerçek zamanlı API ile akıtır. Ajan runtime + markdown workspace. Docker/K8s, air-gapped destekli. | Evet |
| `SYSTRAN/faster-whisper` | https://github.com/SYSTRAN/faster-whisper | 24.7k | **MIT** | Python (CTranslate2) | Whisper'ın 4x hızlı yeniden implementasyonu. Kelime seviyesi zaman damgası, VAD filtresi, batch, int8 kuantizasyon. CPU'da çalışır. | Evet (kütüphane) |

---

## BÖLÜM 2 — Bu Projenin Ölçülmüş Durumu

Aşağıdakilerin hepsi 5 Ağustos 2026'da bu depoda **gerçekten çalıştırıldı**.

### 2.1 Ham sayılar

| Ölçüm | Değer | Nasıl ölçüldü |
|---|---|---|
| Python dosyası | **406** | `find . -name "*.py"` (`.git`, `.venv`, `node_modules` hariç) |
| `src/` satır sayısı | **43.364** | `find src -name "*.py" \| xargs wc -l` |
| `tests/` satır sayısı | **15.905** | aynı |
| `backend/` satır sayısı | **4.467** | aynı |
| Toplam commit | **188** | `git log --oneline \| wc -l` |
| `src/` boyutu | 4.0 MB | `du -sh` |
| `frontend/` boyutu | 1.2 MB | `du -sh` |
| `backend/` boyutu | 204 KB | `du -sh` |
| `docs/` boyutu | 412 KB | `du -sh` |
| Depo (git/venv hariç) | 17 MB | `du -sh . --exclude=.git --exclude=.venv` |
| Danışman modülü | 39 dosya, **15 aktif roster** | `channel_config.ADVISOR_KEYS` |
| TODO/FIXME/NotImplementedError | **18** | `grep -rn ... src/ backend/` |

### 2.2 GERÇEK test sonucu

**İlk deneme başarısız oldu.** Test toplama (collection) aşamasında çöktü:

```
tests/test_notification_system.py:21: in <module>
    import pytz
E   ModuleNotFoundError: No module named 'pytz'
!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!
53 warnings, 1 error in 2.97s
```

Ayrıca 61 adet `@pytest.mark.asyncio` işaretli test `PytestUnknownMarkWarning` veriyordu — yani **çalışmıyorlardı**.

`pytz` + `pytest-asyncio` elle kurulduktan sonra:

```
1130 passed in 24.28s
```

**Bu gerçek bir paketleme hatası, test hatası değil.** Doğruladım:

- `pyproject.toml` içinde `pytz` **yok** (`grep -c "pytz\|slack" pyproject.toml` → `0`), ama `src/ai_assistant/integrations/notification_manager.py:21` onu **modül seviyesinde** import ediyor.
- `pyproject.toml`'un `[dev]` ekstrası yalnızca `pytest` içeriyor; `pytest-asyncio` yok.
- Temiz bir sanal ortamda **sadece** `pip install -e ".[dev]"` çalıştırıp testi denedim → **aynı `pytz` çökmesiyle tüm suite durdu.**
- CI (`.github/workflows/ci.yml:47-49`) bunu tesadüfen kurtarıyor:
  ```yaml
  pip install -e ".[dev]"
  pip install -r backend/requirements-dev.txt || true
  ```
  `backend/requirements-dev.txt` → `-r requirements.txt` (pytz burada) + `pytest-asyncio==0.21.1`.
  **Ama sondaki `|| true` yüzünden bu satır sessizce başarısız olabilir.** `backend/requirements.txt` içinde `spacy==3.7.2`, `chromadb==0.4.16`, `sentence-transformers==2.2.2`, `psycopg2-binary` gibi ağır ve kırılgan sabit sürümler var. O kurulum düşerse CI, `pytz` çökmesi ve 61 çalışmayan async testle **yeşil görünmeye devam eder mi, yoksa kırmızı mı olur** — `|| true` sadece pip'i yutuyor, `pytest -q` yine çökeceği için CI kırmızı olur. Yani sessiz yeşil riski yok; **kırılgan CI riski var.**

**Karar:** Test paketi gerçek ve geniş (1130 test, 15.905 satır). Ama **bağımlılık beyanı hatalı** ve suite'in çalışması `backend/` klasörünün ağır requirements dosyasına tesadüfi bir bağımlılıkla ayakta duruyor.

### 2.3 Dosya dosya: gerçek implementasyon mu, iskelet mi?

| Dosya | Satır | Karar | Kanıt |
|---|---|---|---|
| `src/ai_assistant/advisors/meeting_notes.py` | 518 | **İSKELET** | Aşağıya bakınız — en kritik bulgu |
| `src/ai_assistant/integrations/google_drive_manager.py` | 459 | **GERÇEK** | `googleapiclient.discovery.build` ile canlı Drive servisi (satır 49); `files().get`, `files().list`, parent taşıma (satır 305-310), Docs oluşturma (satır 366). Mock/TODO **sıfır**. |
| `src/ai_assistant/integrations/notification_manager.py` | 469 | **GERÇEK** | `slack_sdk.WebClient` (satır 102-104), `chat_postMessage` (satır 245) ve `build("gmail","v1",...)` (satır 116) ile canlı Gmail. Mock/TODO **sıfır**. Tek sorun: `pytz` beyan edilmemiş. |
| `src/ai_assistant/integrations/slack_advisor_bridge.py` | 769 | **GERÇEK** | 30 fonksiyon/sınıf. `AsyncWebClient.chat_postMessage` 5 ayrı çağrı noktasında (satır 148, 212, 238, 287, 333), thread yönetimi, Block Kit üretimi (satır 350-435), `.assistant_state/advisor_requests.json` ile kalıcı istek takibi. Mock/TODO **sıfır**. |
| `backend/app/services/gemini_service.py` | 255 | **KARMA — yarısı mock** | `self.model.generate_content()` çağrıları gerçek (satır 62, 102, 143). **Ama** `google-generativeai` kurulu değilse veya hata alınırsa `_mock_generate_variations`, `_mock_posting_time`, `_mock_fit_analysis` (satır 207-250) devreye giriyor. 255 satırın ~50 satırı mock veri üreticisi. Sessiz düşüş (silent fallback) — kullanıcı sahte veriyi gerçekten ayıramaz. |

#### `meeting_notes.py` — en kritik bulgu

Bu dosyada **518 satır var ama iki ana fonksiyonun ikisi de sabit metin döndürüyor.** Bu bir "test için mock" değil; **tek kod yolu bu.**

`transcribe_audio()` (satır 218-252) — ses dosyasını hiç açmıyor:
```python
# Mock implementation - in production, call Google Speech-to-Text API
mock_transcript = (
    "Selamlar herkese. Bugünün toplantısında üç ana konuyu ele aldık.\n"
    ...
)
return mock_transcript
```

`analyze_meeting()` (satır 254-332) — `transcript` parametresini alıyor ama **kullanmıyor**:
```python
# Mock implementation - in production would call LLM
meeting_notes.summary = "Toplantıda Q3 stratejisi, ürün lansmanı ve rakip analizi tartışıldı."
meeting_notes.findings = ["Pazarlama bütçesi %25 artırılmalı", ...]
meeting_notes.action_items = [
    ActionItem(description="Pazarlama bütçesi planını hazırla", owner="John", ...),
    ActionItem(description="Teknik specifikasyonları dokümante et", owner="Sarah", ...),
    ...
]
```

"John", "Sarah", "Mike", "%25", "XYZ şirketi" — hepsi kaynak kodda gömülü sabitler. `meeting-notes-poller.yml` her 30 dakikada bir çalışıyor ve bu sabit çıktıyı üretiyor.

Dosyada gerçek olan kısımlar: `MeetingNotes`/`ActionItem`/`CompetitiveAction` veri sınıfları, `TaskTracker` entegrasyonu, `GoogleDriveManager` ile rapor yükleme, Slack formatlama. **Yani boru hattı gerçek, içinden geçen su sahte.**

### 2.4 Diğer bulgular

- **`linkedin-coach/` (3.1 MB) — `src/` ağacının eski bir tam kopyası.** `.gitignore:55` ile git dışında tutulmuş, yani depoyu kirletmiyor; ama yerel diskte kafa karıştırıcı. `diff -rq` 39 fark satırı veriyor: `complaint_radar.py`, `meeting_notes.py`, `meeting_prep.py`, `personal_assistant.py`, `social_media_coach.py`, `chat/advisor_dialog.py`, `chat/ask.py`, `chat/direct_messaging.py`, `chat/task_commands.py` yalnızca `src/`'de var. Ayrıca `linkedin-coach/` içinde ikinci bir `metrics.py`, `seed_metrics.py`, `tests/` kopyası duruyor.
- **`backend/` (FastAPI + PostgreSQL + Celery) hiçbir üretim workflow'unda kullanılmıyor.** Yalnızca `ci.yml` ona dokunuyor. `requirements.txt` içinde `spacy`, `chromadb`, `sentence-transformers`, `tweepy`, `sendgrid`, `sentry-sdk`, `google-cloud-*` var — bunların hiçbiri `src/` tarafında kullanılmıyor. Kök dizindeki 5 durum raporu markdown'ı (`DEPLOYMENT_COMPLETE.md`, `DEPLOYMENT_STATUS.md`, `FINAL_DELIVERY_REPORT.md`, `PRODUCTION_CHECKLIST.md`, `GITHUB_SECRETS_SETUP.txt`) ~90 KB ve hepsi 1 Ağustos'ta donmuş.
- **`backend/app/services/linkedin_service.py` (190 satır) gerçek.** `https://api.linkedin.com/v2/ugcPosts` üzerine `requests.post` yapıyor (satır 84-85), analytics için `GET` (satır 118). Ama `async def` içinde senkron `requests` kullanıyor — event loop'u bloklar.
- **README 47.985 byte.** `src/` toplam kodunun ~%1'i kadar tek bir dosya.

---

## BÖLÜM 3 — Benchmark Tablosu

| Özellik | **Bu Proje** | Khoj | Dify | n8n | Postiz | CrewAI |
|---|---|---|---|---|---|---|
| **Yıldız (05.08.2026)** | **0** (yeni/kişisel) | 36.2k | 151.4k | 199.4k | 34.3k | 56.6k |
| **Slack entegrasyonu** | **Evet — çekirdek.** Kanal başına danışman, thread'li diyalog, Block Kit, `slack_advisor_bridge.py` (769 satır) | Kısmi (WhatsApp/Obsidian/tarayıcı öncelikli) | Evet (eklenti) | Evet (düğüm) | Evet (17 ağdan biri) | Hayır (kütüphane, arayüzü yok) |
| **Çoklu ajan** | **Evet — 15 danışman, TEK batched LLM çağrısı** (`_batch.py`, 372 satır) | Evet (özel ajanlar) | Evet (görsel ajan/workflow) | Evet (AI düğümleri) | Hayır | Evet (framework'ün tamamı bu) |
| **Türkçe desteği** | **Evet — birinci sınıf.** Prompt'lar, çıktılar, kod yorumları, workflow yorumları Türkçe | LLM'e bağlı (arayüz İngilizce) | Arayüz çevirili, içerik LLM'e bağlı | Arayüz çevirili | Arayüz İngilizce | LLM'e bağlı |
| **Self-host** | **Evet — sunucusuz.** GitHub Actions + repo commit'i = durum deposu | Evet (Docker) | Evet (Docker) | Evet (lisans kısıtlı) | Evet (Docker) | Evet (kütüphane) |
| **Kurulum zorluğu** | **Orta-Yüksek.** ~30+ GitHub secret, Google OAuth, Slack app; ama **veritabanı/sunucu yok** | Orta (Docker + LLM key) | Orta (Docker Compose, çok servis) | Düşük (tek Docker) | Yüksek (Postgres + Redis + Temporal) | Düşük (`pip install crewai`) |
| **Lisans** | **Belirtilmemiş** (depoda LICENSE yok — varsayılan olarak "tüm hakları saklı") | AGPL-3.0 | Dify OSS License (Apache+kısıt) | Sustainable Use (fair-code) | AGPL-3.0 | MIT |

**Lisans notu:** Bu depoda `LICENSE` dosyası yok. Kişisel kullanım için sorun değil; ama kimsenin katkı yapamayacağı/kullanamayacağı anlamına gelir. Tek satırlık bir düzeltme.

---

## BÖLÜM 4 — Ne Ödünç Alınır: Somut Entegrasyon Planı

> **Çerçeve:** Bu bölüm "şunu sil, onu kur" demiyor. Mevcut mimari (GitHub Actions + repo-as-database + batched LLM + Slack) **sunucusuz olması sayesinde bu ölçekte Dify/n8n/Postiz'den daha ucuz ve daha basit.** Aşağıdakiler o mimariyi bozmadan içine takılabilecek parçalar.

### 4.1 Doğrudan `pip install` edilebilir olanlar

| Kaynak Proje | Ne Ödünç Alınır | Nereye Entegre Edilir | Efor | Kazanç |
|---|---|---|---|---|
| **`SYSTRAN/faster-whisper`** (24.7k, MIT) | Yerel ses→metin, CPU'da int8 kuantizasyonla çalışır, kelime seviyesi zaman damgası + VAD | `advisors/meeting_notes.py` → `transcribe_audio()` (satır 218-252). Sabit metin yerine gerçek transkript. | **1 gün** | İskeletin yarısı kapanır. Google STT maliyeti ve OAuth kapsamı hiç gerekmez. `base`/`small` model GitHub Actions runner'ında çalışır. |
| **Bu projenin kendi `integrations/llm.py`** (671 satır, zaten var) | Batched Gemini çağrısı + fallback zinciri | `meeting_notes.py` → `analyze_meeting()` (satır 254-332). Sabit `ActionItem` listesi yerine gerçek LLM çıkarımı. | **0.5 gün** | İskeletin diğer yarısı kapanır. **Yeni bağımlılık yok** — altyapı zaten yazılmış, sadece çağrılmıyor. |
| **`slackapi/bolt-python`** (1.3k, MIT) | Socket Mode + event listener + `ack()` deseni | `chat-poller.yml`'ın 5 dakikalık yoklaması yerine. **Ama** bu, sürekli çalışan bir süreç gerektirir → sunucusuz mimariyi bozar. | 3-5 gün | **Şu an ÖNERİLMİYOR.** Yoklama gecikmesi (≤5 dk) kabul edilebilir olduğu sürece mevcut çözüm daha ucuz. Slack interaktif düğmeleri (Block Kit `actions`) gerekirse zorunlu hale gelir. |
| **`crewAIInc/crewAI`** (56.6k, MIT) | Rol/görev/süreç soyutlaması | `advisors/` katmanını sarmalamak | 1-2 hafta | **ÖNERİLMİYOR.** CrewAI ajan başına ayrı LLM çağrısı yapar. Bu proje 15 danışmanı **tek** çağrıda batch'liyor (ölçülen: çalışma başına 13.941 token). CrewAI'ye geçmek token maliyetini kabaca **5-10 katına çıkarır** ve mevcut avantajı yok eder. |

### 4.2 Kalıp olarak ödünç alınacaklar (kod değil, fikir)

| Kaynak Proje | Ne Ödünç Alınır | Nereye Entegre Edilir | Efor | Kazanç |
|---|---|---|---|---|
| **`langchain-ai/langgraph`** (38.9k, MIT) | **Checkpoint kalıbı:** her adım sonrası durumu serileştir, çökmede kaldığı yerden devam et | `chat/poller.py` + `.assistant_state/` imleç mantığı. Şu an imleç "hata olsa da ilerliyor" (chat-poller.yml yorumu) — yani **başarısız mesaj sessizce kayboluyor.** LangGraph'ın "başarısız düğümü yeniden dene, N denemeden sonra ölü mektup kuyruğuna at" kalıbı buna doğrudan uyar. | 1-2 gün | Kaybolan mesaj olmaz. Kütüphane kurmadan sadece kalıbı uygula. |
| **`Vexa-ai/vexa`** (2.6k, Apache-2.0) | **Markdown workspace kalıbı:** toplantı bilgisini dosya sistemine markdown olarak derle, sonra üstünde sorgula | `frontend/reports/` (808 KB) zaten böyle çalışıyor. Vexa'nın "derlenmiş bilgi üzerinde sohbet" katmanı `chat/ask.py`'a eklenebilir. | 2-3 gün | Danışman raporları "yazılıp unutulan" değil, sorgulanabilir bir hafıza olur. |
| **`Zackriya-Solutions/meetily`** (28.3k, MIT) | **Bot'suz kayıt kalıbı:** toplantıya bot sokmak yerine sistem sesini yakala | `meeting_notes_poller.py`. Vexa'nın bot yaklaşımı Google Workspace izinleri gerektirir; Meetily'nin yaklaşımı gerektirmez. | Kalıp bedava | Kurumsal onay süreci atlanır. |
| **`gitroomhq/postiz-app`** (34.3k, AGPL-3.0) | **Provider soyutlaması:** her sosyal ağ = tek bir arayüzü uygulayan bağımsız modül (17 ağ böyle yönetiliyor) | `backend/app/services/linkedin_service.py` şu an tek ağ için özel yazılmış. Aynı arayüz Instagram/X/Threads'e genişletilebilir. | 2 gün (refactor) | Yeni ağ eklemek 190 satır değil ~60 satır olur. **AGPL olduğu için kod kopyalanamaz — sadece tasarım ödünç alınır.** |
| **`seratch/ChatGPT-in-Slack`** (513, MIT) | **Home tab + hızlı prompt kalıbı** | `slack_advisor_bridge.py`. Şu an her şey kanal mesajı. Home tab, 15 danışmanın durumunu tek ekranda gösterir. | 1-2 gün | Frontend dashboard'a gitmeye gerek kalmaz. MIT — kod da doğrudan uyarlanabilir. |
| **`khoj-ai/khoj`** (36.2k, AGPL-3.0) | **Çoklu istemci kalıbı:** aynı çekirdek, farklı arayüzler (Obsidian/Emacs/WhatsApp) | İlham. **AGPL — kod alınamaz** (bu projeyi de AGPL yapardı). | — | Yalnızca yön: "Slack tek arayüz olmak zorunda değil." |

### 4.3 GERÇEK FARK — bu projenin benzersiz yanı ne?

Dürüst cevap: **üç şey gerçekten farklı, gerisi yeniden yazım.**

1. **Sunucusuz kalıcılık.** "Durumu repo'ya commit'le" kalıbı (`.assistant_state/*.json`, `frontend/status.json`). Khoj/Dify/Postiz'in hepsi PostgreSQL + Redis + kalıcı disk ister. Bu proje **sıfır sunucu, sıfır veritabanı, sıfır aylık altyapı ücretiyle** çalışıyor. Bu gerçekten alışılmadık ve kişisel ölçekte doğru karar.
2. **Tek batched çağrıyla çoklu ajan.** Ölçülen: 15 danışman, çalışma başına 13.941 token, 52.9 sn. CrewAI/AutoGen ajan başına çağrı yapar. Bu, listedeki hiçbir framework'ün varsayılan olarak yapmadığı bir maliyet optimizasyonu — ve `_batch.py` bunu token'ı ajan başına geri dağıtacak kadar da ölçüyor (`prompt_chars` per advisor).
3. **Türkçe birinci sınıf vatandaş.** Sadece çıktı değil; prompt'lar, persona tanımları, hata mesajları, kod yorumları, workflow yorumları Türkçe. Listedeki 12 projenin **hiçbirinde** bu yok. Kişiye özel 15 danışmanlık roster (kids_development, executive_coaching, complaint_radar…) de jenerik bir framework'ten çıkmaz.

**Benzersiz OLMAYAN:** Slack bot iskeleti (Bolt zaten var), sosyal medya zamanlama (Postiz 17 ağı çözmüş), toplantı transkripsiyonu (faster-whisper/Meetily çözmüş), FastAPI backend (kullanılmıyor bile).

### 4.4 EN AZ MALİYETLE EN ÇOK DEĞER — 1 haftalık plan

**Gün 1: `pyproject.toml`'u düzelt.** (2 saat)
`pytz` ve `slack-sdk` çalışma zamanı bağımlılıklarına, `pytest-asyncio` `[dev]`'e eklenecek. `ci.yml:49`'daki `|| true` kaldırılacak. Şu an temiz kurulumda `notification_manager` import edilemiyor — bu **üretimi etkileyen** bir hata, sadece test sorunu değil. Bir `LICENSE` dosyası da bu arada eklenir.

**Gün 2-3: `meeting_notes.py`'ı gerçekleştir.** (1.5 gün)
- `transcribe_audio()` → `faster-whisper` (`base` modeli, int8, CPU). ~15 satır.
- `analyze_meeting()` → mevcut `integrations/llm.py` üzerinden Gemini. Sabit `ActionItem` listesi yerine yapılandırılmış JSON çıkarımı. ~40 satır.
- Bu iki değişiklik 518 satırlık dosyayı iskeletten çalışan koda çevirir. Çevresindeki her şey (TaskTracker, Drive yükleme, Slack formatlama) **zaten hazır.**

**Gün 4: `gemini_service.py`'ın sessiz mock düşüşünü sesli hale getir.** (0.5 gün)
`_mock_*` fonksiyonları silinmesin — ama yalnızca `settings.USE_MOCK=true` açıkken devreye girsin. Aksi halde hata fırlatsın. Şu an kullanıcı sahte içerik önerisi ile gerçeğini ayırt edemiyor.

**Gün 5: Düşünme (thinking) token bütçesini kıs.** (0.5 gün) → *bkz. 4.6, ölçülmüş %44 israf*

**Kalan süre: Slack Home tab** (ChatGPT-in-Slack kalıbı, MIT).

### 4.5 SADELEŞTİRİLECEKLER (silinecekler değil)

| Ne | Bulgu | Öneri |
|---|---|---|
| `linkedin-coach/` (3.1 MB) | `src/` ağacının eski tam kopyası; `.gitignore:55` ile zaten git dışında | Yerel diskten sil. Git'i etkilemiyor, ama `diff -rq` 39 fark üretiyor ve arama sonuçlarını kirletiyor. **Riski sıfır.** |
| `backend/requirements.txt` | `spacy`, `chromadb`, `sentence-transformers`, `tweepy`, `sendgrid`, `sentry-sdk`, `google-cloud-storage`, `google-cloud-sql-connector`, `celery`, `redis` — hiçbiri `src/` tarafında kullanılmıyor. CI'da kurulmaya çalışılıyor. | Kullanılmayanları çıkar. CI kurulum süresi ve kırılganlığı ciddi düşer. |
| Kök dizindeki 5 rapor dosyası (~90 KB) | `DEPLOYMENT_COMPLETE.md`, `DEPLOYMENT_STATUS.md`, `FINAL_DELIVERY_REPORT.md`, `PRODUCTION_CHECKLIST.md`, `GITHUB_SECRETS_SETUP.txt` — hepsi 1 Ağustos'ta donmuş, içerikleri örtüşüyor | `docs/` altında **tek** `DEPLOYMENT.md`'de birleştir. |
| `README.md` (47.985 byte) | Tek dosyada kurulum + mimari + danışman listesi + secret listesi + sorun giderme | Üçe böl: `README.md` (kısa), `docs/KURULUM.md`, `docs/MIMARI.md`. |
| `meeting-notes-poller.yml` cron `*/30` | Ayda 1.440 çalışma; her biri **sabit metin** üretiyor (§2.3) | İskelet gerçekleşene kadar `workflow_dispatch`'e al. Gerçekleştikten sonra bile `*/30` fazla — toplantılar 30 dakikada bir bitmiyor. |
| `chat-poller.yml` cron `*/5` | Ayda 8.640 çalışma. **Tüm Actions tüketiminin ~%80'i** (§4.6) | `*/15`'e düşür → tüketim 1/3'e iner, kullanıcı gecikmesi 5→15 dk çıkar. Ya da mesai saatleri dışında hiç çalıştırma: `*/5 6-20 * * 1-5` → ~%75 tasarruf. |
| `backend/` (FastAPI + Postgres + Celery, 4.467 satır) | Hiçbir üretim workflow'unda kullanılmıyor; sadece `ci.yml` dokunuyor | **Silme** — `linkedin_service.py` ve `gemini_service.py` gerçek ve değerli. Ama CI'da ayrı bir opsiyonel job'a taşı ki ana test yolunu yavaşlatmasın. |
| `async def` + senkron `requests` | `backend/app/services/linkedin_service.py:38,84,118` | `httpx.AsyncClient`'a çevir (`httpx` zaten `pyproject.toml`'da var). |

### 4.6 RİSKLER — hesaplanmış

#### (a) GitHub Actions dakika tüketimi

Cron'lar (`.github/workflows/`'dan okundu):

| Workflow | Cron | Çalışma/ay | Tahmini süre | Tahmini dk/ay |
|---|---|---|---|---|
| `chat-poller.yml` | `*/5 * * * *` | **8.640** | ~2 dk (checkout + setup-python + `pip install -e .` + poll + commit) | **~17.280** |
| `meeting-notes-poller.yml` | `*/30 * * * *` | 1.440 | ~2 dk | ~2.880 |
| `daily-briefing.yml` | `0 7 * * *` + `0 11,15,19 * * *` | 120 | ~5 dk (ölçülen LLM gecikmesi 52,9 sn + kurulum + rapor + commit) | ~600 |
| `advisor-slack-bridge.yml` | `0 7 * * *` (2 job, timeout 15+10) | 30 × 2 | ~3 dk | ~180 |
| `drive-backup-scheduler.yml` | `0 23 * * *` + `30 23 28-31 * *` (3 job) | ~34 × 3 | ~2 dk | ~200 |
| `ci.yml` | push/PR, matrix `[3.11, 3.12]` + postgres servisi | değişken | ~4 dk × 2 | commit sıklığına bağlı |
| **TOPLAM (cron'lar)** | | **~10.300 çalışma** | | **~21.100 dk/ay** |

> Süreler **tahmindir** — gerçek çalışma logları bu ortamdan okunamadı. GitHub her job'u dakikaya yukarı yuvarladığı için 8.640 çalışma **en iyi ihtimalle** 8.640 dakikadır.

**Ücretsiz limit karşılaştırması:**
- **Özel (private) depo:** 2.000 dk/ay → **~10 kat aşım.** Aşan kısım Linux'ta $0,008/dk → **~$153/ay.**
- **Genel (public) depo:** GitHub Actions standart runner'larda **ücretsiz ve sınırsız.**

**Bu depo genel (public).** `https://github.com/Beltass/AI-Executive-Assistant` sayfası açılıyor ve 0 yıldız gösteriyor. Yani **şu an fatura riski yok.** Ama:
- **Depo özele çevrilirse anında ~$150/ay'lık maliyet doğar.** Bu, farkında olunması gereken tek yönlü bir kapı.
- GitHub, genel depolarda yüksek frekanslı zamanlanmış işleri **yoğunlukta erteler veya atlar.** `*/5` garanti değildir — GitHub cron dokümantasyonunun kendi uyarısı.
- Zamanlanmış workflow'lar, depoda **60 gün** aktivite olmazsa otomatik devre dışı bırakılır. Bu depo her çalışmada durum commit'lediği için bu risk şu an yok.

#### (b) Gemini token maliyeti — ÖLÇÜLMÜŞ VERİYLE

Tahmin değil: `frontend/metrics.json` (04.08.2026 tarihli, **25 gerçek çalışma**) okundu.

```
runs: 25 | total_tokens: 348.541
prompt_tokens: 149.084 | output_tokens: 102.031 | thoughts_tokens: 97.426
avg_tokens_per_run: 13.941 | avg_latency_seconds: 52,9 | fallback_runs: 2
```

Çalışma başına: **5.963 girdi + 4.081 çıktı + 3.897 düşünme** token.

15 danışman × günde 4 çalışma × 30 gün = **120 çalışma/ay**:
- Girdi: 5.963 × 120 = **~0,72 M token**
- Çıktı (düşünme dahil — Gemini düşünme token'ını çıktı olarak faturalar): 7.978 × 120 = **~0,96 M token**

`gemini-2.5-flash` fiyatı ($0,30/M girdi, $2,50/M çıktı):
- Girdi: 0,72 × $0,30 = **$0,21**
- Çıktı: 0,96 × $2,50 = **$2,39**
- **Toplam: ~$2,60/ay**

**Sonuç: Gemini maliyeti bir risk DEĞİL.** Ayda 2,6 dolar. Buradaki gerçek bulgular başka:

1. **Token'ın %44'ü görünmez düşünmeye gidiyor** (97.426 / 348.541). `metrics.json`'daki kendi öneri motoru da bunu işaretlemiş. Bu, aylık maliyetin **~$1,15'i** — yani yarısından fazlası brifingde hiç görünmeyen metne. `thinking_budget` parametresini kısmak veya `gemini-2.5-flash-lite`'a geçmek doğrudan tasarruf.
2. **25 çalışmanın 2'si fallback'e düştü** (`fallback_runs: 2`, %8). `gemini-2.5-flash` ücretsiz katmanda rutin olarak 429 veriyor — `llm.py:37`'deki fallback zinciri (`gemini-flash-latest`, `gemini-2.0-flash`) bu yüzden var ve **çalışıyor.** İyi mühendislik.
3. **`gemini-2.5-flash` 16 Ekim 2026'da kullanımdan kaldırılıyor.** (`llm.py:30`'daki varsayılan model bu.) Halefler: Gemini 3 Flash Preview ($0,50/$3,00) veya 3.1 Flash-Lite ($0,25/$1,50). 3 Flash'a geçişte aylık maliyet ~$3,23 olur — hâlâ önemsiz. **Ama model adı kodda sabit varsayılan olduğu için, o tarihte geçiş yapılmazsa sistem fallback zincirine düşer ve sonunda tamamen durur. Takvime alınmalı.**
4. Bu hesap **yalnızca `daily-briefing`'i** kapsar. `chat-poller` (8.640 çalışma/ay) ve `meeting-notes-poller` (1.440/ay) LLM çağırdığı ölçüde ekleyecek — ama chat-poller yalnızca yeni mesaj varsa çağırıyor, meeting-notes-poller ise şu an hiç çağırmıyor (sabit metin döndürüyor, §2.3).

#### (c) LinkedIn API

`backend/app/services/linkedin_service.py:85` `https://api.linkedin.com/v2/ugcPosts` kullanıyor. Doğrulanan kısıtlar:

- **Kendi profiline paylaşım** (`w_member_social`): Developer Portal'da uygulama kaydı + OAuth ile mümkün. **Bu proje için yeterli** — kişisel LinkedIn'e post atmak amaç.
- **Şirket sayfasına paylaşım / analytics** (Community Management API): **bireysel geliştiricilere kapalı.** Kayıtlı şirket + doğrulanmış LinkedIn Sayfası + iki aşamalı uygulama incelemesi + ekran kaydı (screencast) gerekiyor. Bireysel/tescilsiz başvuru **anında elenir.**
- **Token ömrü: access token 60 gün, refresh token 365 gün.** Kodda otomatik yenileme mantığı görmedim — **60 günde bir sessizce kırılacak.** Bu somut ve yakın bir risk.

#### (d) Instagram API

Kodda henüz Instagram entegrasyonu yok (`grep -rn "graph.instagram\|graph.facebook" src/ backend/` → sonuç yok). Eklenecekse doğrulanan engeller:

- Facebook Business hesabı + **bağlı Facebook Sayfası** (zorunlu) + Instagram Professional hesabı + Meta developer app + onaylı `instagram_business_content_publish` izni.
- Yayınlama iki adımlı: `POST /{ig-user-id}/media` → `POST /{ig-user-id}/media_publish`.
- **24 saatte 25 gönderi** sert limiti (Reels ve Story dahil aynı kova). Saatte 200 API çağrısı (BUC limiti).
- App Review başvuru başına **2-4 hafta**, her izin kapsamı için ayrı ekran kaydı; ret durumunda yeniden başvuru.

**Değerlendirme:** Instagram'ı sıfırdan yazmak ~4 hafta onay + implementasyon demek. Postiz bunu zaten çözmüş (17 ağ). Instagram gerçekten gerekiyorsa **Postiz'i yanına self-host edip Slack'ten tetiklemek**, Meta App Review sürecini kendi başına yönetmekten çok daha ucuz — ama Postiz AGPL-3.0 olduğu için kodu bu projeye kopyalanamaz, ayrı servis olarak çalıştırılmalı.

---

## Özet

**Bu proje bir "yeniden yazım" değil.** Sunucusuz mimari, batched çoklu-ajan çağrısı ve Türkçe birinci sınıf tasarım gerçekten farklı ve listedeki hiçbir projede birlikte yok. 1.130 test geçiyor, 43k satır `src/` kodu var, Google Drive / Slack / Gmail entegrasyonları **gerçek**.

**Ama iki somut kusur var:**
1. `meeting_notes.py` (518 satır) — transkripsiyon ve analiz **sabit metin döndürüyor**. `faster-whisper` + mevcut `llm.py` ile ~2 günde kapanır.
2. `pyproject.toml` `pytz`/`pytest-asyncio` beyan etmiyor — temiz kurulumda `notification_manager` import edilemiyor. 2 saatlik düzeltme.

**Maliyet tarafında sürpriz yok:** Gemini ~$2,60/ay (ölçülmüş), Actions ücretsiz (depo genel). En büyük iki maliyet kaldıracı: `chat-poller` frekansını `*/5` → `*/15` düşürmek ve düşünme token bütçesini kısmak (%44 israf).

**Takvime alınması gereken tek zorunlu iş:** `gemini-2.5-flash` 16 Ekim 2026'da kaldırılıyor.

---

## Kaynaklar

**GitHub depoları (05.08.2026'da sayfalardan okundu):**
[khoj-ai/khoj](https://github.com/khoj-ai/khoj) · [leon-ai/leon](https://github.com/leon-ai/leon) · [All-Hands-AI/OpenHands](https://github.com/All-Hands-AI/OpenHands) · [Significant-Gravitas/AutoGPT](https://github.com/Significant-Gravitas/AutoGPT) · [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) · [microsoft/autogen](https://github.com/microsoft/autogen) · [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) · [langgenius/dify](https://github.com/langgenius/dify) · [n8n-io/n8n](https://github.com/n8n-io/n8n) · [activepieces/activepieces](https://github.com/activepieces/activepieces) · [slackapi/bolt-python](https://github.com/slackapi/bolt-python) · [slackapi/bolt-js](https://github.com/slackapi/bolt-js) · [seratch/ChatGPT-in-Slack](https://github.com/seratch/ChatGPT-in-Slack) · [gitroomhq/postiz-app](https://github.com/gitroomhq/postiz-app) · [inovector/mixpost](https://github.com/inovector/mixpost) · [Zackriya-Solutions/meetily](https://github.com/Zackriya-Solutions/meetily) · [Vexa-ai/vexa](https://github.com/Vexa-ai/vexa) · [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper)

**Fiyatlandırma ve API kısıtları:**
[Gemini pricing 2026 — CloudZero](https://www.cloudzero.com/blog/gemini-pricing/) · [Gemini 2.5 Flash — pricepertoken](https://pricepertoken.com/pricing-page/model/google-gemini-2.5-flash) · [Gemini API Pricing — BenchLM](https://benchlm.ai/google/api-pricing) · [LinkedIn Community Management API](https://developer.linkedin.com/product-catalog/marketing/community-management-api) · [LinkedIn CM API onay süreci](https://singhamandeep.com/linkedin-community-management-api-access/) · [LinkedIn Posting API 2026](https://zernio.com/blog/linkedin-posting-api) · [Instagram Graph API 2026](https://www.netrows.com/blog/instagram-graph-api-guide-2026) · [Instagram'a API ile gönderi](https://postproxy.dev/blog/post-to-instagram-via-api/) · [Sosyal medya API limitleri](https://postproxy.dev/blog/social-media-platform-api-rules-rate-limits-media-specs/) · [Self-hosted toplantı transkripsiyon araçları 2026](https://meetily.ai/blog/best-self-hosted-meeting-transcription-tools-2026)
