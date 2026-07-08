# FEATURES.md — Özellik Listesi

Durum etiketleri: **MVP** (Faz 1), **F2** (Faz 2), **F3** (Faz 3).
Detaylı ajan tanımları için `AGENTS.md`, faz sırası için `ROADMAP.md`.

## Sohbet / Orchestrator

- [ ] **MVP** — Doğal dil isteğini ilgili ajana yönlendirme
- [ ] **MVP** — Birden fazla ajanın çıktısını tek yanıtta birleştirme
- [ ] **MVP** — Dış dünyaya giden eylemler için taslak → onay akışı
- [ ] **F2** — Çok adımlı/uzun süren görevler için ilerleme bildirimi

## E-posta (Email Agent)

- [ ] **MVP** — Gelen kutusu özeti (son N e-posta)
- [ ] **MVP** — Önceliklendirme (kullanıcı tercihine göre)
- [ ] **MVP** — Taslak yanıt üretme (gönderim onaylı)
- [ ] **F2** — Outlook desteği
- [ ] **F2** — Otomatik etiketleme/klasörleme önerisi
- [ ] **F3** — Slack/Teams bildirimleriyle çapraz bağlam

## Takvim (Calendar Agent)

- [x] **MVP** — Yaklaşan etkinlikleri okuma/özetleme
- [x] **MVP** — Çakışma tespiti (LLM tabanlı özet içinde)
- [ ] **MVP** — Etkinlik oluşturma/düzenleme/iptal (taslak/onay akışı gerekiyor)
- [ ] **MVP** — Uygun saat önerisi
- [ ] **F2** — Outlook Calendar desteği
- [ ] **F2** — Toplantı öncesi otomatik hatırlatma (Reminder Agent ile)

## Hafıza (Memory Agent)

- [ ] **MVP** — Kullanıcı tercihlerini kaydetme/getirme (pgvector)
- [ ] **MVP** — Oturumlar arası bağlam sürekliliği
- [ ] **F2** — Uzun vadeli özet sıkıştırma (eski geçmişi özetleyip
      saklama)
- [ ] **F2** — Kullanıcıya "hafızamda şunlar var" görünürlüğü/düzenleme

## İş arama (Job Search Agent)

- [ ] **MVP** — LinkedIn + kariyer.net ilan tarama
      (`is-basvuru/scrape`'den taşınan mantık)
- [ ] **MVP** — Takip kaydıyla tekrar eleme
- [ ] **F2** — Ek iş ilanı kaynakları (kullanıcı onayıyla)

## CV/Başvuru (CV Optimizer)

- [ ] **MVP** — Uygunluk puanlama (0-100 rubrik)
- [ ] **MVP** — Kişiselleştirilmiş CV (PDF) üretimi
- [ ] **MVP** — Ön yazı/mesaj taslağı üretimi
- [ ] **MVP** — Başvuru takip günlüğü
- [ ] **F2** — ATS-uyumlu düz metin CV varyantı otomasyonu

## Toplantı & not (F2)

- [ ] **F2** — Toplantı gündemi hazırlama
- [ ] **F2** — Transkriptten aksiyon maddesi çıkarma (Zoom/Teams)
- [ ] **F2** — Notion'a not kaydetme

## Planlama & hatırlatma (F2)

- [ ] **F2** — Günlük öncelik planı
- [ ] **F2** — Koşullu hatırlatmalar (ör. "3 gün yanıt gelmezse")

## Analitik (F2)

- [ ] **F2** — Zaman kullanımı raporu
- [ ] **F2** — Başvuru dönüşüm oranı raporu

## Ses & tarayıcı otomasyonu (F3)

- [ ] **F3** — Sesli komut/yanıt
- [ ] **F3** — Onaylı tarayıcı otomasyonu (form doldurma vb.)

## Entegrasyonlar

- [x] Gmail, Google Calendar — **MVP**
- [ ] Microsoft 365 / Outlook — **F2**
- [ ] Teams, Zoom (transkript) — **F3**
- [ ] Slack — **F3**
- [ ] Notion — **F3**
- [ ] LinkedIn (derin entegrasyon, resmi API sınırları dahilinde) — **F3**

## Güvenlik & uyumluluk (F2, detay `SECURITY.md`)

- [ ] **F2** — OAuth token şifreli saklama
- [ ] **F2** — KVKK/GDPR veri işleme değerlendirmesi
- [ ] **F2** — Denetim (audit) günlüğü
