# AGENTS.md — AI Ajanları

Bu doküman, Master Orchestrator altında çalışacak (veya ileride
çalışacak) tüm uzman ajanların görev tanımlarını içerir. Her ajanın
**durumu** (MVP'de aktif / Faz 2 / Faz 3) açıkça belirtilir — hepsini
aynı anda geliştirmiyoruz (bkz. `ROADMAP.md`).

Ortak kurallar (tüm ajanlar için geçerli):
- Asgari yetki: yalnızca görevi için gerekli API/veriye erişir.
- Dış dünyaya giden hiçbir eylemi (gönderme, silme, başvuru) kendi
  başına *kesinleştirmez* — taslak üretir, onay Orchestrator/kullanıcı
  katmanında verilir (bkz. `ARCHITECTURE.md` §3).
- Girdi/çıktı formatı yapılandırılmıştır; serbest metin değil.
- Kendi sistem promptu `prompts/<agent-adı>.md` altında tutulur
  (Faz 2'de doldurulacak, bkz. `PROMPTS.md`).

---

## MVP'de aktif (Faz 1)

### 🎯 Master Orchestrator ("CEO Agent")
Kullanıcının doğal dil isteğini sınıflandırır, uygun ajan(lar)a
yönlendirir, birden fazla ajanın çıktısını birleştirir, onay
akışını yönetir. Diğer tüm ajanların "giriş kapısı"dır. (Vizyon
tartışmalarında "CEO Agent" olarak da anılır — aynı bileşen, tek
isim kullanılıyor: Master Orchestrator.)

### 💬 Chat Agent
Dashboard'daki sohbet arayüzünün konuşma katmanı. Kullanıcıyla doğal
dilde etkileşir, Orchestrator'a yapılandırılmış istek olarak iletir,
yanıtları kullanıcı dostu formatta sunar. Bağımsız bir "ajan"dan çok,
Orchestrator'ın kullanıcıya bakan yüzüdür.

### 📧 Email Agent
Gmail gelen kutusunu okur, özetler, önceliklendirir, taslak yanıt
üretir. Gönderim her zaman kullanıcı onayı gerektirir. İleride
sağlayıcıdan bağımsız bir arayüz (`EmailProvider`) üzerinden
Outlook'u da destekleyecek şekilde genişletilir (Faz 2).

### 📅 Calendar Agent
Google Calendar üzerinde etkinlik oluşturma/düzenleme/iptal, çakışma
tespiti, uygun saat önerisi. Davet gönderimi onay gerektirir.

### 🧠 Memory Agent
Kullanıcı tercihlerini, tekrarlayan bağlamı ve geçmiş etkileşim
özetlerini Supabase + pgvector üzerinde saklar/getirir. Diğer tüm
ajanlar kişiselleştirme için Memory Agent'a danışır. Hatırlaması
gereken kategori örnekleri: yazışma stili/hitap tercihi, imza bilgisi,
şirket/görev bilgisi, ekip/müşteri isimleri, sık yapılan işlemler,
geçmiş toplantı özetleri — "Burak bunu bana geçen ay kim söylemişti?"
gibi sorulara cevap verebilecek düzeyde. Detaylar `AI_MEMORY.md`'de
(Faz 2).

**Faz 2 eklentisi — AI Learning:** Kullanıcı asistanın bir çıktısını
düzelttiğinde (ör. "merhaba" yerine "selam" kullanıyorum), bu düzeltme
Memory Agent'a kaydedilir ve sonraki üretimlerde uygulanır. Ayrı bir
ajan değil, Memory Agent'ın geri bildirim döngüsüdür.

### 💼 Job Search Agent
`Dashboard-Project/is-basvuru/.claude/skills/scrape` becerisindeki
mantığın bu asistana taşınmış hâli: LinkedIn ve kariyer.net'te
`profil.md`'deki hedef unvanlara uygun ilan tarar, tekrarları takip
kaydıyla eler, kısa liste sunar. Aynı ToS/kapsam kısıtları geçerlidir
(giriş duvarı aşma yok, CAPTCHA bypass yok, otomatik başvuru yok).

**Faz 3 eklentisi — Job Search Intelligence:** şirket analizi
(kültür/itibar), maaş tahmini, CV-ilan eşleşme skoru, başarı
olasılığı. **Risk notu:** Glassdoor'un ücretsiz/genel amaçlı bir
public API'si yok; bu veriler ya ücretli bir veri sağlayıcısı ya da
ToS'a uygun düşük hacimli manuel/yarı-otomatik tarama gerektirir —
"kolay ve ücretsiz" ilkesiyle gerilimli olduğu için Faz 3'te, somut
bir veri kaynağı kararıyla birlikte netleştirilecek.

### 📄 CV Optimizer
`Dashboard-Project/is-basvuru/.claude/skills/apply` becerisindeki
mantığın taşınmış hâli: seçilen ilan için uygunluk puanlar (≥70 devam,
50-69 kullanıcıya sor, <50 üretme), `profil.md`'ye sadık kalarak CV/ön
yazı taslağı üretir, hiçbir platforma otomatik göndermez.

---

## Faz 2'de eklenecek

### 🤝 Meeting Agent (Meeting Intelligence)
Takvimdeki toplantılar için gündem hazırlama; toplantı sonrası
(Zoom/Teams transkripti üzerinden) yapılandırılmış çıktı üretir: kim
ne söyledi, kim hangi görevi aldı, deadline'lar, riskler, alınan
kararlar, açık sorular, eksik kalan konular. Ham transkript özeti
değil, aksiyon-odaklı bir rapor hedeflenir.

### 📝 Note Agent / Document Agent
Toplantı/e-posta/sohbetlerden yapılandırılmış not çıkarır, Notion'a
(veya Supabase'e) kaydeder. Faz 3'te belge oluşturma/düzenleme
(rapor taslağı, özet doküman) yeteneği eklenerek "Document Agent"a
genişler — ayrı bir ajan değil, Note Agent'ın genişletilmiş kapsamı.

### 📋 Daily Planner (Planner Agent)
Gün başında e-posta, takvim ve görev durumuna bakarak günlük öncelik
listesi/plan önerir. Email + Calendar + Memory Agent çıktısını
birleştirir. **Morning Briefing** (günaydın mesajı: okunmamış mail
sayısı, bugünkü toplantılar, kritik görevler, teslim tarihleri) ve
**Evening Report** (tamamlanan/ertelenen işler, cevaplanan mailler,
yarına kalanlar) bu ajanın iki somut çıktı formatıdır — hava
durumu/trafik/haberler gibi asistanın kendi veri kaynağı olmayan
bilgiler yalnızca kullanıcı açıkça bir servis bağlarsa eklenir.

### 🔔 Reminder Agent / Smart Automation
Zaman/koşul bazlı hatırlatmalar (ör. "takip e-postası 3 gün sonra
gelmezse hatırlat") kurar ve tetikler. Faz 3'te kural tabanlı bir
otomasyon motoruna genişler (ör. "'Fatura' başlıklı mail gelirse
Muhasebe klasörüne taşı + takvime görev ekle") — bkz.
`AUTOMATION.md`. Otomasyon kuralları da diğer her eylem gibi ilk
kurulumda kullanıcı onayından geçer; sessizce genişletilmez.

### 📊 Analytics Agent (Decision Support / Relationship Manager / Workload Analysis)
Üç ilişkili yeteneği kapsar:
- **Decision Support:** "Bugün 37 mail geldi, hangilerini önce
  cevaplamalıyım?" gibi sorularda önem sırası üretir (Email/Calendar
  Agent çıktısını temel alır, yeni bir veri kaynağı gerektirmez).
- **Relationship Manager:** kiminle ne sıklıkta görüşüldüğü, kimin
  yanıt vermediği, hangi müşterinin beklediği gibi basit bir CRM
  analizi — mevcut e-posta/takvim verisinden türetilir, ayrı bir CRM
  entegrasyonu gerekmez.
- **Workload Analysis:** haftalık rapor (toplantılarda geçen süre,
  mail süreleri, odak zamanı) — zaman kullanımı ve başvuru dönüşüm
  oranları dahil.

### 📊 Executive Dashboard (ajan değil, arayüz)
Sohbet ekranının yanında bir özet ekranı: okunmamış mailler, bugünkü
toplantılar, kritik görevler, haftalık hedefler, iş başvuruları,
bekleyen onaylar, AI önerileri. Yeni bir ajan değil — mevcut
ajanların (Email, Calendar, Job Search, Analytics) çıktılarını tek
ekranda birleştiren bir frontend özelliğidir; detay `UI_UX.md`'de
(Faz 2).

---

## Faz 3'te eklenecek

### 🎙️ Voice Agent
Sesli komut/yanıt arayüzü (muhtemelen mobil uygulamayla birlikte).

### 🌐 Browser Agent (Research Agent dahil)
Otonom tarayıcı otomasyonu gerektiren görevler için (ör. bir portalda
form doldurma, web araştırması yapma, PDF indirme, rapor hazırlama)
— **yalnızca kullanıcının açıkça onayladığı, ToS'a uygun
senaryolarda**; `is-basvuru`'nun "otomatik gönderim yok" ilkesi bu
ajan için de geçerli olacak şekilde tasarlanacak. Ayrı bir "Research
Agent" tanımlanmıyor — web araştırması bu ajanın salt-okunur bir
modu.

---

## Entegrasyon genişlemesi (Faz 2-3, ajan değil ama ilgili)

Microsoft 365/Outlook, Teams, Zoom, Slack, Notion, LinkedIn (derin
entegrasyon) — mevcut ajanların (Email, Calendar, Meeting, Note)
sağlayıcıdan bağımsız arayüzler üzerinden bu servisleri de
desteklemesi şeklinde eklenir; yeni ajan tipleri değil, mevcut
ajanların genişletilmiş yetenekleridir. Detaylar `INTEGRATIONS.md`
(Faz 2).
