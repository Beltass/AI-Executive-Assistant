# Ajan Kullanım Kılavuzu

Bu doküman, sistemdeki **21 canlı ajanın** ne yaptığını, ne zaman çalıştığını ve
onlarla nasıl konuşacağınızı anlatır. Tek doğruluk kaynağı koddur:
ajan listesi ve tetikleyiciler `src/ai_assistant/status_report.py` içindeki
`ADVISOR_META` manifestinden, Slack kanalları
`src/ai_assistant/integrations/slack_setup.py` dosyasından alınmıştır.

---

## Hızlı bakış

Tetikleyici sözlüğü: **Her gün** = `always` · **Veri değişince** = `data_triggered`
· **Haftada bir (Pazartesi)** = `weekly` · **Sadece istediğinizde** = `user_requested`

| # | Ajan | Ne işe yarar | Ne zaman çalışır | Slack kanalı |
|---|------|--------------|------------------|--------------|
| 1 | 📋 Sabah İşletme Brifingi | Dünün performansı + bugünün öncelikleri | Her gün | `#morning-operations` |
| 2 | 📬 İletişim & Takvim Danışmanı | E-posta yükü + takvim yoğunluğu tek bakışta | Her gün | `#communications-calendar` |
| 3 | 🤝 Toplantı Hazırlık & Takip | Yaklaşan toplantı öncesi hazırlık notu | Veri değişince | `#meeting-prep` |
| 4 | 🗂️ Drive Dosya Analisti | Drive'a düşen yeni dosyayı okur, özetler | Veri değişince | `#drive-insight` |
| 5 | 💼 Kariyer Gelişimi | İK, ilanlar, İngilizce, ücretsiz sertifika | Veri değişince | `#career-development` |
| 6 | 📊 Pazar İstihbaratı | Sektör, YZ, CX ve bankacılık haber akışı | Sadece istediğinizde | `#market-intelligence` |
| 7 | 📊 Kapsamlı Pazar & Sentiment Analizi | Müşteri şikâyeti, trend, rakip hamlesi | Veri değişince | `#complaint-radar` |
| 8 | 💼 LinkedIn İmaj Koçu | Profil, post taslağı, etkileşim takibi | Veri değişince | `#linkedin-coach` |
| 9 | 📱 Sosyal Medya İmaj Koçu | Instagram/Twitter içerik ve marka tutarlılığı | Haftada bir (Pazartesi) | `#social-media-coach` |
| 10 | 📅 Kişisel Asistan | Takvim, hedefler, ağ ve fırsat takibi | Haftada bir (Pazartesi) | `#personal-assistant` |
| 11 | 🔬 Raporlama & Veri Analisti | Operasyon verisini yoruma çevirir (Excel/rapor) | Veri değişince | `#data-analyst` |
| 12 | 🧠 Yapay Zeka & İnovasyon | Günün YZ dersi + somut proje fikri | Haftada bir (Pazartesi) | `#ai-innovation` |
| 13 | 👨‍👩‍👧 Çocuk Gelişimi Danışmanı | 10 ve 4 yaş için ebeveynlik brifingi | Sadece istediğinizde | `#kids-development` |
| 14 | 🧭 Yönetici Koçu | Liderlik gelişimi + taahhüt takibi | Haftada bir (Pazartesi) | `#executive-coaching` |
| 15 | ⏱️ Verimlilik Koçu | Odak blokları ve enerji mimarisi | Haftada bir (Pazartesi) | `#productivity-coach` |
| 16 | 📉 Risk Nöbetçisi | Trend hâlinde kötüleşen sinyaller, eşik aşımı | Veri değişince | `#risk-sentinel` |
| 17 | ⚖️ Karar Zekâsı | Verilmiş kararların sonucu ve karar kalitesi | Haftada bir (Pazartesi) | `#decision-intelligence` |
| 18 | 🛟 İtibar Muhafızı | Marka zararı ve kriz erken uyarısı | Veri değişince | `#social-guardian` |
| 19 | 📈 İş Analisti Danışmanı | Koşunun teknik sağlığı, anomali ve uyarılar | Her gün | `#work-analyst` |
| 20 | 🚦 Operasyon Direktörü | Günün bulgularını öncelikli karar listesine çevirir | Her gün | `#operations-director` |
| 21 | 🛡️ Teknik Gözetim (7/24 SRE) | Cron, kota, teslimat, besleme ayakta mı | Her gün | `#sre-watchdog` |

> **Ana kanal:** `SLACK_MAIN_CHANNEL` özet taşır — her ajan için tek satır başlık
> + panodaki tam rapora ve ajanın kendi kanalına bağlantı. Ajanın **tam** bölümü
> kendi alt kanalına düşer.

> **Gizlilik:** kişisel veri içerebilen ajanlar kodda `private = True` işaretlidir
> (ör. İletişim & Takvim, Toplantı Hazırlık). Bu bölümler **panoya yazılmaz**,
> yalnızca Slack'te kalır. Bunu kapatan bir ortam değişkeni bilinçli olarak yoktur.

---

## Ajanlar — ayrıntı

### Günlük operasyon

**📋 Sabah İşletme Brifingi** (`morning_operations`)
- **Ne yapar:** Dünün tamamlanma/başarı oranını ve trendini çıkarır, bugünün önceliklerini ve odak alanını yazar.
- **Girdisi:** Gmail + Takvim (`gmail_calendar`), bir önceki `status.json`, performans geçmişi.
- **Çıktısı:** Slack mesajı (`#morning-operations`) + pano rapor sayfası.
- **Nasıl tetiklenir:** Otomatik, her koşuda.

**📬 İletişim & Takvim Danışmanı** (`communications_calendar`)
- **Ne yapar:** E-posta aciliyeti ile takvim yoğunluğunu birleştirir; odak bloğu ve boş slot önerir.
- **Girdisi:** Gmail + Google Calendar (`gmail_calendar`, salt-okunur OAuth).
- **Çıktısı:** Slack mesajı (`#communications-calendar`). **Özel** — panoya yazılmaz.
- **Nasıl tetiklenir:** Otomatik, her koşuda.

**🤝 Toplantı Hazırlık & Takip** (`meeting_prep`)
- **Ne yapar:** Yaklaşan toplantı için "geçen sefer ne konuşuldu, kimin üstünde ne kaldı, bu sefer ne konuşulmalı" notunu yazar.
- **Girdisi:** Google Takvim (`calendar`) + Drive'daki toplantı notları.
- **Çıktısı:** Slack mesajı (`#meeting-prep`). **Özel** — panoya yazılmaz.
- **Nasıl tetiklenir:** Yaklaşan toplantı varsa otomatik. Slack'ten de sorulabilir: `yarınki toplantıya hazırla`.

**🗂️ Drive Dosya Analisti** (`drive_insight`)
- **Ne yapar:** Drive klasörüne düşen yeni dosyayı (teklif, vendor raporu, Excel, sunum) okur ve karara çevirir.
- **Girdisi:** Drive klasörü (`drive_files`) — `DRIVE_INSIGHT_FOLDER_ID`, yoksa `GOOGLE_DRIVE_FOLDER_ID`.
- **Çıktısı:** Slack mesajı (`#drive-insight`) + özet/sunum taslağı.
- **Nasıl tetiklenir:** Klasöre daha önce raporlanmamış yeni dosya düştüğünde. Yeni dosya yoksa model hiç çağrılmaz.

**📅 Kişisel Asistan** (`personal_assistant`)
- **Ne yapar:** Haftanın hedeflerini, son tarihlerini, ağ ve fırsat takibini toparlar.
- **Girdisi:** Takvim + görevler (`calendar_tasks`).
- **Çıktısı:** Slack mesajı (`#personal-assistant`).
- **Nasıl tetiklenir:** Haftalık otomatik; ayrıca Slack DM'den diyalog ajanı olarak çağrılabilir (bkz. aşağıdaki bölüm).

### Veri ve analiz

**🔬 Raporlama & Veri Analisti** (`data_analyst`)
- **Ne yapar:** `ai_assistant.analysis` motorunun ürettiği sayıyı yoruma çevirir; bulguları sütun sırasına göre değil **operasyonel etkiye** göre sıralar ve verinin desteklemediğini açıkça yazar.
- **Girdisi:** Analiz veri kümesi (`analysis_dataset`) — `DATA_ANALYST_SOURCE` / Drive tablosu.
- **Çıktısı:** Slack mesajı (`#data-analyst`), pano rapor sayfası, istenirse `.xlsx` dosyası ve kopyala-yapıştır sunum taslağı.
- **Nasıl tetiklenir:** Veri değişince otomatik. Slack'ten tek cümleyle sipariş verilebilir (bkz. "Slack'ten nasıl konuşulur").

**📊 Pazar İstihbaratı** (`market_intelligence`)
- **Ne yapar:** Sektör, YZ, CX ve bankacılık akışlarını tek havuzda birleştirir, tekilleştirir ve "bugün ne oynadı, ne yapmalıyım" der.
- **Girdisi:** RSS beslemeleri (`market_feeds`) — `SECTOR_NEWS_RSS_URL`, `AI_NEWS_RSS_URL`, `CX_RESEARCH_RSS_URL`, `BANKING_NEWS_RSS_URL`, `BANKING_SECURITY_RSS_URL`.
- **Çıktısı:** Slack mesajı (`#market-intelligence`) + pano raporu.
- **Nasıl tetiklenir:** Sadece istediğinizde — otomatik koşmaz, Slack'ten sipariş verin.

**📊 Kapsamlı Pazar & Sentiment Analizi** (`complaint_radar`)
- **Ne yapar:** Müşteri şikâyet gündemini sabit temalara toplar, rakip hamlesi ve tehdit/fırsat sinyalini KPI baskısına çevirir.
- **Girdisi:** Şikâyet/sektör akışları (`complaint_feeds`) — `COMPLAINT_RADAR_RSS_URL`, `COMPLAINT_RADAR_SECTOR_RSS_URL`, `COMPLAINT_RADAR_COMPETITORS`.
- **Çıktısı:** Slack mesajı (`#complaint-radar`) + pano raporu.
- **Nasıl tetiklenir:** Akış değişince otomatik.

**📉 Risk Nöbetçisi** (`risk_sentinel`)
- **Ne yapar:** Tek koşuya değil koşuların **dizisine** bakar; üç koşudur sessizce kötüleşen sayıyı henüz ucuzken söyler.
- **Girdisi:** Koşu geçmişi (`run_history`, `metrics.json`).
- **Çıktısı:** Slack mesajı (`#risk-sentinel`) + pano raporu.
- **Nasıl tetiklenir:** Yeni koşu kaydı geldiğinde otomatik; geçmiş değişmediyse model çağrılmaz.

**🛟 İtibar Muhafızı** (`social_guardian`)
- **Ne yapar:** Tek bir gönderi markayı yakabilir — hacme değil **zarara ve hıza** bakar, cevap penceresi önerir.
- **Girdisi:** İtibar izleme akışları (`reputation_feeds`).
- **Çıktısı:** Slack mesajı (`#social-guardian`).
- **Nasıl tetiklenir:** Akışta yeni başlık varsa otomatik; bir kez konuşulan başlık ikinci kez uyarı üretmez.

### Kariyer ve imaj

**💼 Kariyer Gelişimi** (`career_development`)
- **Ne yapar:** Kariyer planı, hedef roller ve başvuru malzemesi, iş İngilizcesi haftalık odağı, ücretsiz sertifika fırsatları — dört başlık tek çağrıda.
- **Girdisi:** Kariyer beslemeleri (`career_feeds`) — `FREE_CERTS_RSS_URL`, `JOB_KEYWORDS`, `JOB_LOCATION`.
- **Çıktısı:** Slack mesajı (`#career-development`) + hazır arama bağlantıları.
- **Nasıl tetiklenir:** Besleme değişince otomatik. **Uyumluluk kuralı:** oturum açmaz, otomatik başvuru göndermez — yalnızca malzeme ve link hazırlar.

**💼 LinkedIn İmaj Koçu** (`linkedin_coach`)
- **Ne yapar:** Profil iyileştirme önerisi, günlük post taslağı, onay iş akışı ve etkileşim takibi.
- **Girdisi:** LinkedIn (`linkedin`) — `LINKEDIN_PROFILE_URL`, token varsa API.
- **Çıktısı:** Slack mesajı (`#linkedin-coach`) + onay bekleyen post taslağı.
- **Nasıl tetiklenir:** Veri değişince otomatik. **Token yoksa mock modda çalışır: taslak üretir, paylaşmaz** (bkz. "Şu an çalışmayan özellikler").

**📱 Sosyal Medya İmaj Koçu** (`social_media_coach`)
- **Ne yapar:** Bio/profil optimizasyonu, içerik takvimi, etkileşim izleme, platformlar arası marka tutarlılığı.
- **Girdisi:** Sosyal hesap ayarları (`social`) — `SOCIAL_MEDIA_INSTAGRAM_HANDLE`, `SOCIAL_MEDIA_TWITTER_HANDLE`, `SOCIAL_MEDIA_CONTENT_STRATEGY`.
- **Çıktısı:** Slack mesajı (`#social-media-coach`); profil analizleri `.assistant_state/profile_analyses.json` içinde tutulur.
- **Nasıl tetiklenir:** Haftalık otomatik; Slack DM diyaloğundan da çağrılabilir.

### Kişisel gelişim

**🧠 Yapay Zeka & İnovasyon** (`ai_innovation`)
- **Ne yapar:** Günün YZ dersini verir (seviye `AI_MASTERY_LEVEL`) ve o beceriyi uygulayacak, eforu/etkisi 1-5 puanlanmış somut proje önerir.
- **Girdisi:** YZ beslemeleri (`ai_feeds`) — `AI_MASTERY_RSS_URL`; ayrıca son günlerin brifingleri.
- **Çıktısı:** Slack mesajı (`#ai-innovation`) + panodaki "Fikirler" sekmesi.
- **Nasıl tetiklenir:** Haftalık otomatik.

**🧭 Yönetici Koçu** (`executive_coaching`)
- **Ne yapar:** Liderlik gelişim odağı **ve** taahhüt takibi: "ne söz verdin, ne oldu, engel neydi".
- **Girdisi:** Görev tamamlama geçmişi, taahhüt kaydı (`ACCOUNTABILITY_STATE_FILE`).
- **Çıktısı:** Slack mesajı (`#executive-coaching`).
- **Nasıl tetiklenir:** Haftalık otomatik.

**⏱️ Verimlilik Koçu** (`productivity_coach`)
- **Ne yapar:** Haftanın odak blok mimarisini kurar; derin iş / sığ iş / toplantı kuşağı ve tamponu saat aralıklarıyla yerleştirir.
- **Girdisi:** Yok — takviminizi **okumaz** ve okumuş gibi de yapmaz.
- **Çıktısı:** Slack mesajı (`#productivity-coach`) + "bu hafta değiştireceğim tek şey".
- **Nasıl tetiklenir:** Haftalık otomatik. (Sınır: taahhüdün **içeriği** Yönetici Koçu'nun işi, **zamanı** buranın.)

**⚖️ Karar Zekâsı** (`decision_intelligence`)
- **Ne yapar:** Verilmiş kararların sonucunu beklenenle karşılaştırır; kararın **kalitesini** sonucundan ayırır (iyi karar kötü sonuçlanabilir).
- **Girdisi:** Sizin kaydettiğiniz karar günlüğü (`DECISION_INTELLIGENCE_DECISIONS`). Kayıt yoksa karar **uydurmaz**, bir karar günlüğü protokolü verir.
- **Çıktısı:** Slack mesajı (`#decision-intelligence`).
- **Nasıl tetiklenir:** Haftalık otomatik.

**👨‍👩‍👧 Çocuk Gelişimi Danışmanı** (`kids_development`)
- **Ne yapar:** Tek tema seçip 10 ve 4 yaş için ayrı ayrı işler: gelişimsel gerekçe, gerçek cümle kalıpları, sık hata + alternatifi, 10 dakikalık birlikte-etkinlik.
- **Girdisi:** Yok (dış veri kullanmaz).
- **Çıktısı:** Slack mesajı (`#kids-development`).
- **Nasıl tetiklenir:** **Sadece siz istediğinizde** — otomatik koşuda çalışmaz.
  Çalıştırmak için `DIGEST_FORCE_ADVISORS=kids_development` verin
  (`all` yazarsanız tüm kadro zorlanır).

### Teknik gözetim

**📈 İş Analisti Danışmanı** (`work_analyst`)
- **Ne yapar:** **Bu** koşuya bakar: hangi ajan çalıştı/hata verdi, başarı oranı, zaman aşımı, token verimliliği. 4 seviyeli uyarı (🔴🟠🟡🟢).
- **Girdisi:** Koşunun brifingleri (`run_briefings`).
- **Çıktısı:** Slack mesajı (`#work-analyst`) + pano "Sistem" sekmesi. **Model çağırmaz** (`token_ceiling = 0`).
- **Nasıl tetiklenir:** Otomatik, her koşuda, sondan bir önce.

**🚦 Operasyon Direktörü** (`operations_director`)
- **Ne yapar:** Kendi veri toplamaz; koşunun **tüm** brifinglerini okur ve öncelik sırasına dizilmiş karar listesi üretir. Her maddede **sahip + son tarih + aksiyon alınmazsa ne olur** zorunludur.
- **Girdisi:** Koşunun brifingleri (`run_briefings`), `OPERATIONS_DIRECTOR_BUSINESS`, `OPERATIONS_DIRECTOR_FORECAST`, `OPERATIONS_DIRECTOR_SLA_TARGET`.
- **Çıktısı:** Slack mesajı (`#operations-director`) + panonun **Aksiyon** sekmesi.
- **Nasıl tetiklenir:** Otomatik, en sondan bir önce. Sistem konularını (API hatası, token) bilinçli olarak yazmaz — o İş Analisti'nin işi.

**🛡️ Teknik Gözetim (7/24 SRE)** (`sre_watchdog`)
- **Ne yapar:** Koşuların **arasına** bakar: cron hâlâ tetikleniyor mu, kota tükendi mi, brifing Slack'e ulaştı mı, beslemeler ayakta mı, durum dosyası geri commit edildi mi.
- **Girdisi:** Sistem artefaktları (`system_health`) — `status.json`, `metrics.json`, rapor arşivi.
- **Çıktısı:** Slack mesajı (`#sre-watchdog`) + panodaki sağlık rozeti. **Model çağırmaz, ücretsiz kotadan hiçbir şey yemez.**
- **Nasıl tetiklenir:** Otomatik, en son. Ayrıca elle: `python -m ai_assistant.watchdog`.

---

## Slack'ten nasıl konuşulur

Slack tarafında **üç ayrı yol** vardır; hangisini kullandığınız ne istediğinize bağlı.

### 1) Rapor siparişi — analist kanalında serbest cümle
`src/ai_assistant/chat/poller.py` birkaç dakikada bir kanalı okur ve
`chat/session.py` durum makinesine verir. Tek Türkçe cümle yazarsanız
`chat/intent.py` yedi adımlık menüyü atlar, ne anladığını geri söyler ve
**yalnızca gerçekten eksik kalanı** sorar.

| Yazarsınız | Olur |
|---|---|
| `rapor` (veya `başla`, `menü`, `merhaba`) | Menü açılır, adım adım ilerlersiniz |
| `son 3 ay vardiya bazında SLA ve terk oranı, haftalık trend, Excel` | Hızlı yol: dönem/kırılım/grafik/format tek cümleden çözülür |
| `onayla` (veya `evet`, `tamam`) | Sipariş onaylanır, rapor üretilir |
| `geri` · `iptal` · `baştan` · `yardım` | Bir adım geri · siparişi iptal · sıfırdan başla · yardım |

Veride olmayan bir kırılım isterseniz sistem rastgele başka bir eksende rapor
üretmez — "veride vardiya diye bir sütun yok, şunlar var" diye sorar.

### 2) Toplantı notu özeti — tek cümle, kuyruğa girmez
`src/ai_assistant/chat/ask.py` şu kalıpları yakalar (noktalı/noktasız yazım kabul):

- `toplantı notlarını özetle`
- `geçen toplantıda ne konuştuk?`
- `yarınki toplantıya hazırla`
- `toplantı özeti çıkar`

Birden çok not aday olduğunda **tahmin yapmaz**, numaralı menüyle sorar; siz
numarayı yazarsınız. Uzun çağrıdan önce "bakıyorum" satırı düşer.

### 3) Ajanla doğrudan diyalog — `@advisor_key` mention / DM
`src/ai_assistant/integrations/slack_advisor_bridge.py` ve
`src/ai_assistant/chat/advisor_dialog.py` şu **dört** ajan için çok turlu,
thread tabanlı konuşma kurar (`SLACK_ADVISOR_REQUEST_ENABLED=true` iken):

| Mention | Ajan | Ne sorabilirsiniz |
|---|---|---|
| `@data_analyst` | 📊 Veri Analisti | CSV/JSON analizi, istatistik, grafik |
| `@linkedin_coach` | 💼 LinkedIn Koçu | Profil optimizasyonu, kişisel marka |
| `@social_media_coach` | 📱 Sosyal Medya Koçu | İçerik planı, platform stratejisi |
| `@personal_assistant` | 🤖 Kişisel Asistan | Günlük plan, görev, hedef, takvim |

Thread eşlemesi `.assistant_state/advisor_threads.json`, istek durumu
`.assistant_state/advisor_requests.json` içinde tutulur — yani süreç yeniden
başlasa da konuşma kaybolmaz.

### 4) Görev komutları (slash)
`src/ai_assistant/chat/task_commands.py`:

```
/task create "başlık" "@kişi" "son tarih" "öncelik"
/task list [mine|@kişi]
/task done <id>
/task reschedule <id> "tarih"
/task assign <id> "@kişi"
/task priority <id> "seviye"
/task notes <id> "metin"
```

---

## Dashboard nasıl okunur

Pano `frontend/index.html` + `frontend/app.js`; sekme listesi `app.js` içindeki
`TABS` dizisidir. Varsayılan açılış sekmesi **Aksiyon**'dur.

| Sekme | Ne bulursunuz |
|---|---|
| 🎯 **Aksiyon** (ilk sekme) | Günün karar listesi, öncelik rozetleriyle ve öncelik dağılımı halkasıyla. Panonun giriş kapısı burasıdır. |
| 🖥️ Sistem | Ajanların koşu durumu (✅ Çalıştı / ⚠️ Hata / ⏭️ Atlandı), Slack teslim durumu, nöbetçinin sağlık hükmü (🟢 Sağlıklı · 🟡 Dikkat · 🔴 Müdahale gerek). |
| 📄 İçerik | Günün ajan raporlarının okuma sayfaları (`frontend/reports/<tarih>/<ajan>.json`). |
| 📈 Performans | Koşu metrikleri, token tüketimi, süre ve trendler. |
| 🗂️ İşler | Görev/aksiyon takibi ve durumları. |
| 💡 Fikirler | Yapay Zeka & İnovasyon ajanının öneri ve proje fikirleri. |
| 🔌 Bağlantılar | Entegrasyon sağlığı: Slack, Asana, Drive — gönderim sayıları ve hatalar. |
| 📬 Gmail | E-posta analizi görünümü. |
| 🔬 Analiz | Veri Analisti çıktıları, grafikler ve tablolar. |
| 💼 LinkedIn | LinkedIn koçunun profil/post çıktıları ve onay bekleyenler. |

**Öncelik rozetleri** (Aksiyon sekmesi, `app.js` içinde tanımlı):

| Rozet | Anlamı | Ne yapmalısınız |
|---|---|---|
| **P0** | acil | Bugün, şimdi |
| **P1** | bugün | Gün bitmeden |
| **P2** | bu hafta | Haftalık planınıza koyun |
| **P3** | bilgi | Sadece haberdar olun |

Öncelik **sıralı bir ölçektir**, kategorik bir küme değil: rozet her zaman kodu
yazar (`P0 · acil`), yani anlam yalnızca renge bırakılmaz. Aksiyon sekmesinin
üst özeti P0/P1 seviyesindekileri ayrıca öne çıkarır; hiçbiri yoksa
"Bugünün raporlarında P0/P1 seviyesinde bir aksiyon yok." yazar.

---

## Bildirimler ve eskalasyon

`src/ai_assistant/integrations/notification_manager.py`.

**Zincir — sırayla ve neden bu sırayla:**

| Sıra | Kanal | Ne zaman | Not |
|---|---|---|---|
| 1 | **Slack DM** | Hemen | Telefona push düşer, ücretsizdir. Her uyarının birincil kanalı. |
| 2 | **E-posta** | DM `ESCALATION_DELAY_MINUTES` (varsayılan **30 dk**) yanıtsız kalırsa | Gmail servisi üzerinden. |
| 3 | **SMS** | E-posta da yanıtsız kalırsa | Twilio REST (httpx ile). **Ücretlidir ve varsayılan KAPALI.** |

**İki emniyet kilidi:**
1. **Öncelik eşiği:** yalnızca `ESCALATION_MIN_PRIORITY` (varsayılan **P1**) ve
   üstündeki uyarılar tırmanabilir. P2/P3 Slack DM'de kalır — bir P3 hatırlatma
   gece 03:00'te telefonu çaldırmaz.
2. **Kalıcı durum:** zincir `.assistant_state/escalations.json` dosyasında tutulur.
   Süreç yeniden başlasa bile gönderilmiş uyarı tekrar gönderilmez.

**Nasıl durdurulur:** `acknowledge(alert_id)` çağrıldığı anda kayıt
`acknowledged = True` olur, `closed_reason = "acknowledged"` yazılır ve zincir
o noktada durur — bir üst kanala **hiç** çıkmaz. Onaylanmış uyarı sessiz kalır.

Hedefi boş bırakılan kanal **sessizce atlanır**; sahte başarı dönmez.

**Ayarlanacak ortam değişkenleri:**

| Değişken | Ne işe yarar | Varsayılan |
|---|---|---|
| `ESCALATION_DELAY_MINUTES` | İki kanal arası bekleme (dakika) | `30` |
| `ESCALATION_MIN_PRIORITY` | Bu önceliğe kadar olanlar tırmanır | `P1` |
| `ESCALATION_SLACK_TARGET` | Slack DM hedefi | boş (atlanır) |
| `ESCALATION_EMAIL_TO` | E-posta hedefi | boş (atlanır) |
| `ESCALATION_SMS_TO` | SMS hedefi | boş (atlanır) |
| `TWILIO_ENABLED` | SMS ana anahtarı | `false` |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_PHONE_NUMBER` | Twilio üçlüsü; biri eksikse SMS gitmez | boş |
| `NOTIFICATION_ENABLED` | Bildirim sistemi ana anahtarı | `true` |
| `GMAIL_SENDER_EMAIL` | E-postanın gönderen adresi | `noreply@ai-assistant.com` |

---

## Token maliyeti ve tasarruf

Aşağıdakiler **ölçülmüş** değerlerdir, tahmin değil:

| Ölçüm | Taban | Yeni | Fark |
|---|---|---|---|
| Koşu başına token | 13.941 | **6.677** | **%52,1 tasarruf** |
| LLM çağrısı | — | **2** | — |
| Koşu süresi | 52,9 sn | **29,7 sn** | ~%44 daha hızlı |

**Tasarruf nereden geldi — üç kaynak:**

1. **Tetikleyici sınıflandırması.** Her ajan `always` değil; `weekly` ve
   `data_triggered` olanlar her gün çalışmaz. Günlük çalışan ajan sayısı düştü.
2. **İçerik-hash kapısı.** `data_triggered` ajanlarda istemin içerik özeti alınır
   (`OperationsManager._data_gate`); veri değişmediyse **model hiç çağrılmaz**.
3. **Batch fallback kapısı.** `DIGEST_BATCH_FALLBACK_MODE` varsayılan **off**.
   Eskiden toplu çağrı başarısız olduğunda 16 ayrı çağrıya patlıyordu; artık
   patlamıyor. Açmak istersen `per_advisor` değerini bilerek vermen gerekir.

**Yeni ajan eklerken kural:** tetikleyiciyi `always` yapmayın. Varsayılanınız
`weekly` ya da `data_triggered` olsun; `data_triggered` seçtiyseniz manifestte
`data_owner` alanını mutlaka doldurun — kapı onsuz çalışmaz.

Ajan başına `token_ceiling` manifestte yazılıdır (0 = model çağırmaz:
`work_analyst` ve `sre_watchdog`).

---

## Yapılandırma

`.env.example` dosyasından okunmuştur. "Zorunlu mu" sütunu, o özelliğin
çalışması için gerekliliği anlatır; boş bırakılan değişken sistemi çökertmez,
ilgili bölüm Türkçe bir açıklamayla `skipped` döner.

### Çekirdek (bunlar olmadan sistem iş görmez)

| Değişken | Ne işe yarar | Zorunlu mu |
|---|---|---|
| `GEMINI_API_KEY` | Model sağlayıcı (ikisi de doluysa tercih edilen) | **Evet** — biri şart |
| `OPENAI_API_KEY` | `GEMINI_API_KEY` boşsa kullanılır | **Evet** — biri şart |
| `SLACK_BOT_TOKEN` | `xoxb-…` bot jetonu. Ajan başına kanal dağıtımı **sadece** bununla mümkün | **Evet** (alt kanal istiyorsanız) |
| `SLACK_MAIN_CHANNEL` | Özetin düştüğü ana kanal | Evet |
| `SLACK_CHANNEL_<AJAN_KEY>` | Ajanın kendi kanalı (büyük harf + alt çizgi) | Alt kanal başına evet |
| `SLACK_WEBHOOK_URL` | Tek kanallı en basit kurulum. **Dikkat:** webhook tek kanala bağlıdır, ajan başına dağıtım atlanır | Hayır |
| `SLACK_CHANNEL` | Eski tek-kanal ayarı, son çare | Hayır |

> Slack kanallarını elle açmayın:
> `python -m ai_assistant.integrations.slack_setup --apply --write-env`
> ana kanalı + her ajan için birer kanal açar, Türkçe amaç/başlık yazar, botu davet
> eder ve id'leri `.env` biçiminde yazar. **Idempotenttir** — yeni ajan ekleyince
> tekrar çalıştırın, sadece eksiği yaratır.

### Google (Gmail, Takvim, Drive)

| Değişken | Ne işe yarar | Zorunlu mu |
|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Google Cloud Console OAuth uygulaması | Google ajanları için evet |
| `GOOGLE_OAUTH_REFRESH_TOKEN` | Kurulumda otomatik üretilir | Evet |
| `GOOGLE_OAUTH_CALLBACK_URL` | Yerel geliştirme geri dönüş adresi | Hayır |
| `GOOGLE_DRIVE_ROOT_FOLDER_ID` | Tüm ajan çıktılarının kök klasörü | Drive için evet |
| `MEETING_PREP_NOTES_FOLDER_ID` | Toplantı notlarının klasörü (yoksa `GOOGLE_DRIVE_FOLDER_ID`) | Toplantı ajanı için evet |
| `DRIVE_BACKUP_ENABLED`, `DRIVE_ARCHIVE_OLDER_THAN_DAYS`, `DRIVE_BACKUP_RETENTION_DAYS` | Yedekleme/arşiv politikası | Hayır |

### Besleme ve içerik kaynakları

| Değişken | Ne işe yarar | Zorunlu mu |
|---|---|---|
| `SECTOR_NEWS_RSS_URL`, `AI_NEWS_RSS_URL`, `CX_RESEARCH_RSS_URL`, `BANKING_NEWS_RSS_URL`, `BANKING_SECURITY_RSS_URL` | Pazar İstihbaratı beslemeleri | Hayır (boşsa bölüm atlanır) |
| `COMPLAINT_RADAR_RSS_URL`, `COMPLAINT_RADAR_SECTOR_RSS_URL`, `COMPLAINT_RADAR_BRANDS`, `COMPLAINT_RADAR_COMPETITORS` | Şikâyet/sentiment radarı | Hayır |
| `FREE_CERTS_RSS_URL`, `JOB_KEYWORDS`, `JOB_LOCATION`, `USER_SECTOR` | Kariyer Gelişimi girdileri | Hayır |
| `AI_MASTERY_LEVEL`, `AI_MASTERY_RSS_URL` | YZ dersinin seviyesi ve kaynağı | Hayır |
| `DATA_ANALYST_SOURCE`, `DATA_ANALYST_SHEET`, `DATA_ANALYST_DRIVE_FOLDER_ID`, `DATA_ANALYST_LAST_DAYS`, `DATA_ANALYST_SLA_TARGET` | Veri Analisti veri kümesi ve hedefleri | Analiz için evet |
| `OPERATIONS_DIRECTOR_BUSINESS`, `OPERATIONS_DIRECTOR_FORECAST`, `OPERATIONS_DIRECTOR_SLA_TARGET` | Direktörün iş bağlamı | Hayır |

### Pano ve raporlar

| Değişken | Ne işe yarar | Zorunlu mu |
|---|---|---|
| `STATUS_REPORT_FILE` | Koşu durum dosyası. Boşsa `frontend/status.json` — CI'da **boş bırakın** | Hayır |
| `REPORTS_DIR` | Rapor belgeleri. Boşsa `frontend/reports` — CI'da **boş bırakın** | Hayır |
| `REPORTS_RETENTION_DAYS` | Kaç gün rapor saklanır (varsayılan 30) | Hayır |
| `DASHBOARD_BASE_URL` | Slack'teki "📄 Tam rapor" bağlantılarının kökü | Hayır |

### Slack köprüsü ve sohbet

| Değişken | Ne işe yarar | Zorunlu mu |
|---|---|---|
| `SLACK_ADVISOR_BRIDGE_ENABLED` | İki yönlü köprü (varsayılan true, bot token varsa) | Hayır |
| `SLACK_ADVISOR_REQUEST_ENABLED` | `@advisor_key` mention'larını işler | Diyalog için evet |
| `SLACK_ADVISOR_INCLUDE` | Günlük güncelleme gönderecek ajanlar | Hayır |
| `SLACK_ADVISOR_UPDATE_HOUR` | Günlük güncelleme saati (UTC, varsayılan 7) | Hayır |
| `SLACK_ADVISOR_MAX_CONCURRENT` / `SLACK_ADVISOR_REQUEST_TIMEOUT` | Eşzamanlılık ve zaman aşımı (5 / 300 sn) | Hayır |
| `CHAT_POLL_MAX_MESSAGES` | Bir yoklama turunda işlenecek azami mesaj (20) | Hayır |

### Diğer

| Değişken | Ne işe yarar | Zorunlu mu |
|---|---|---|
| `DIGEST_BATCH_FALLBACK_MODE` | Toplu çağrı başarısızsa davranış. Varsayılan **off** — açık bırakın | Hayır |
| `DIGEST_FORCE_ADVISORS` | Tetikleyiciyi aşıp belirli ajanları çalıştırır (virgüllü liste ya da `all`) | Hayır |
| `DIGEST_WEEKLY_RUN` | "Bu koşu haftalık slot mu?" — açık yanıt, gün kontrolünü ezer | Hayır |
| `DIGEST_WEEKLY_DAY` | Haftalık slotun günü (0 = Pazartesi, varsayılan 0) | Hayır |
| `AI_ASSISTANT_HTTP_TIMEOUT` | Dış istek zaman aşımı (sn, varsayılan 10) | Hayır |
| `TASK_TIMEZONE`, `DEADLINE_CHECK_INTERVAL` | Görev zaman dilimi ve son tarih tarama aralığı | Hayır |
| `ASANA_TOKEN`, `ASANA_WORKSPACE_ID`, `NOTION_API_KEY`, `TODOIST_API_TOKEN` | İsteğe bağlı görev entegrasyonları | Hayır |

---

## Şu an ÇALIŞMAYAN özellikler

Bu bölüm bilinçli olarak dürüsttür. Aşağıdakiler kodda vardır ama **uçtan uca
çalışmaz**; beklentinizi buna göre kurun.

| Özellik | Durum | Ne gerekiyor |
|---|---|---|
| **LinkedIn otomatik paylaşım** | ❌ Paylaşmıyor | `LINKEDIN_ACCESS_TOKEN` gerekiyor: LinkedIn OAuth uygulaması + `w_member_social` izni. Token yokken ajan **taslak üretir ama paylaşmaz**. |
| **Instagram** | ❌ Yayınlamıyor | Graph API için **business/creator hesabı** ve **bağlı bir Facebook sayfası** şart. Şu an yalnızca içerik önerisi üretiliyor. |
| **SMS bildirimi** | ⚠️ Varsayılan kapalı | Twilio hesabı gerekiyor, **ücretlidir**. `TWILIO_ENABLED=false` varsayılan; açmak için bayrak **ve** Twilio üçlüsü birlikte dolmalı. |
| **Google Slides sunumu** | ❌ API entegrasyonu yok | Sunum dosyası **üretilmiyor**; yerine kopyala-yapıştır edilebilir slayt taslağı (metin) veriliyor. |
| **Uçtan uca toplantı akışı** | ⚠️ Doğrulanmadı | Gerçek bir ses dosyasıyla henüz koşulmadı. Ses → transkript → not → hazırlık zinciri kanıtlanmış değil. |

Ayrıca bilinmesi gerekenler:

- **Kariyer ajanı hiçbir ilana otomatik başvurmaz.** Oturum açmaz, form
  doldurmaz — sadece malzeme ve arama linki hazırlar. Bu bir eksik değil,
  bilinçli bir uyumluluk kararıdır.
- **Verimlilik Koçu takviminizi okumaz.** "Saat 14:00'te toplantın var"
  diyemez, çünkü o veri o bölüme hiç verilmiyor.
- **Karar Zekâsı karar uydurmaz.** Siz karar günlüğü tutmadıkça bir karar,
  tarih ya da sonuç icat etmez.
- **Drive içerik okuma** eski bir refresh token ile 403 dönebilir:
  `drive.readonly` kapsamı istenmektedir ama eski jeton yeni kapsamı
  kendiliğinden almaz. Yeniden onay verilene kadar notlar yalnızca **başlık ve
  tarih** düzeyinde kullanılır.
