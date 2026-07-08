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

### 🎯 Master Orchestrator
Kullanıcının doğal dil isteğini sınıflandırır, uygun ajan(lar)a
yönlendirir, birden fazla ajanın çıktısını birleştirir, onay
akışını yönetir. Diğer tüm ajanların "giriş kapısı"dır.

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
ajanlar kişiselleştirme için Memory Agent'a danışır. Detaylar
`AI_MEMORY.md`'de (Faz 2).

### 💼 Job Search Agent
`Dashboard-Project/is-basvuru/.claude/skills/scrape` becerisindeki
mantığın bu asistana taşınmış hâli: LinkedIn ve kariyer.net'te
`profil.md`'deki hedef unvanlara uygun ilan tarar, tekrarları takip
kaydıyla eler, kısa liste sunar. Aynı ToS/kapsam kısıtları geçerlidir
(giriş duvarı aşma yok, CAPTCHA bypass yok, otomatik başvuru yok).

### 📄 CV Optimizer
`Dashboard-Project/is-basvuru/.claude/skills/apply` becerisindeki
mantığın taşınmış hâli: seçilen ilan için uygunluk puanlar (≥70 devam,
50-69 kullanıcıya sor, <50 üretme), `profil.md`'ye sadık kalarak CV/ön
yazı taslağı üretir, hiçbir platforma otomatik göndermez.

---

## Faz 2'de eklenecek

### 🤝 Meeting Agent
Takvimdeki toplantılar için gündem hazırlama, toplantı sonrası aksiyon
maddesi çıkarma (Zoom/Teams entegrasyonu ile, transkript üzerinden).

### 📝 Note Agent
Toplantı/e-posta/sohbetlerden yapılandırılmış not çıkarır, Notion'a
(veya Supabase'e) kaydeder.

### 📋 Daily Planner
Gün başında e-posta, takvim ve görev durumuna bakarak günlük öncelik
listesi/plan önerir. Email + Calendar + Memory Agent çıktısını
birleştirir.

### 🔔 Reminder Agent
Zaman/koşul bazlı hatırlatmalar (ör. "takip e-postası 3 gün sonra
gelmezse hatırlat") kurar ve tetikler.

### 📊 Analytics Agent
Kullanıcının zaman kullanımı, e-posta yanıt süreleri, başvuru
dönüşüm oranları gibi metrikleri raporlar.

---

## Faz 3'te eklenecek

### 🎙️ Voice Agent
Sesli komut/yanıt arayüzü (muhtemelen mobil uygulamayla birlikte).

### 🌐 Browser Agent
Otonom tarayıcı otomasyonu gerektiren görevler için (ör. bir portalda
form doldurma) — **yalnızca kullanıcının açıkça onayladığı, ToS'a
uygun senaryolarda**; `is-basvuru`'nun "otomatik gönderim yok" ilkesi
bu ajan için de geçerli olacak şekilde tasarlanacak.

---

## Entegrasyon genişlemesi (Faz 2-3, ajan değil ama ilgili)

Microsoft 365/Outlook, Teams, Zoom, Slack, Notion, LinkedIn (derin
entegrasyon) — mevcut ajanların (Email, Calendar, Meeting, Note)
sağlayıcıdan bağımsız arayüzler üzerinden bu servisleri de
desteklemesi şeklinde eklenir; yeni ajan tipleri değil, mevcut
ajanların genişletilmiş yetenekleridir. Detaylar `INTEGRATIONS.md`
(Faz 2).
