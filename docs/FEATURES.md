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

- [x] **MVP (uyarlanmış)** — İlan değerlendirme: otomatik LinkedIn/
      kariyer.net ARAMASI değil, kullanıcının verdiği tek bir ilan
      metni/URL'si (bkz. `AGENTS.md` — bulk scraping riski + serverless
      ortam kısıtı nedeniyle kasıtlı kapsam daraltması)
- [x] **MVP** — Takip kaydıyla tekrar eleme (Supabase `job_applications`,
      yoksa oturum-bazlı bellek)
- [ ] **F2** — Ek iş ilanı kaynakları (kullanıcı onayıyla)

## CV/Başvuru (CV Optimizer)

- [x] **MVP** — Uygunluk puanlama (0-100 rubrik, `reviewer-kriterleri.md`)
- [x] **MVP (uyarlanmış)** — Kişiselleştirilmiş CV üretimi: PDF değil,
      tek sütunlu Markdown (Vercel serverless'ta pdflatex yok)
- [x] **MVP** — Ön yazı/mesaj taslağı üretimi
- [x] **MVP** — Başvuru takip günlüğü + "başvuruldu" durum güncelleme
- [ ] **F2** — ATS-uyumlu düz metin CV varyantı otomasyonu (Markdown
      çıktı zaten tek sütun/ATS-güvenli; bu madde ek biçim ihracı içindir)

## Toplantı zekası — Meeting Intelligence (F2)

- [ ] **F2** — Toplantı gündemi hazırlama
- [ ] **F2** — Transkriptten yapılandırılmış çıktı: kim ne söyledi, kim
      hangi görevi aldı, deadline, riskler, kararlar, açık sorular
- [ ] **F2** — Notion'a not kaydetme

## Planlama & proaktif raporlama (F2)

- [ ] **F2** — Günlük öncelik planı
- [x] **MVP-bonus** — Morning Briefing (okunmamış mail + bugünkü
      program özeti — Email + Calendar Agent'ı ek maliyetsiz birleştirir)
- [ ] **F2** — Evening Report (tamamlanan/ertelenen işler özeti)
- [ ] **F2** — Koşullu hatırlatmalar (ör. "3 gün yanıt gelmezse")

## Analitik & karar desteği (F2)

- [ ] **F2** — Zaman kullanımı raporu (Workload Analysis)
- [ ] **F2** — Başvuru dönüşüm oranı raporu
- [ ] **F2** — E-posta/görev önem sıralaması (Decision Support)
- [ ] **F2** — İlişki analizi: kiminle sıklık, kim yanıt vermiyor
      (Relationship Manager)

## Executive Dashboard (F2)

- [ ] **F2** — Tek ekranda özet: okunmamış mail, bugünkü toplantılar,
      kritik görevler, haftalık hedefler, bekleyen onaylar, AI
      önerileri

## Kişiselleştirme (F2)

- [ ] **F2** — AI Learning: kullanıcı düzeltmelerinden (üslup, hitap)
      öğrenme geri bildirim döngüsü (Memory Agent)

## Otomasyon (F3)

- [ ] **F3** — Kural tabanlı Smart Automation (ör. "X başlıklı mail
      gelirse Y klasörüne taşı + takvime görev ekle") — kurulum
      kullanıcı onayı gerektirir

## Kariyer zekası (F3)

- [ ] **F3** — Şirket/kültür analizi, maaş tahmini, başarı olasılığı
      (veri kaynağı kararı bekliyor — bkz. `AGENTS.md`)

## Ses & tarayıcı otomasyonu (F3)

- [ ] **F3** — Sesli komut/yanıt
- [ ] **F3** — Onaylı tarayıcı otomasyonu + web araştırması (form
      doldurma, PDF indirme, rapor hazırlama)

## Entegrasyonlar

- [x] Gmail, Google Calendar — **MVP**
- [ ] Microsoft 365 / Outlook — **F2**
- [ ] Teams, Zoom (transkript) — **F3**
- [ ] Slack — **F3**
- [ ] Notion — **F3**
- [ ] LinkedIn (derin entegrasyon, resmi API sınırları dahilinde) — **F3**

## Güvenlik & uyumluluk (F2, detay `SECURITY.md`)

Faz 1-3 kapsamı **tek kullanıcı** için sağlamlaştırma; çoklu-kiracı
RBAC dahil değildir (bkz. `PRD.md` §1, Faz 4).

- [ ] **F2** — OAuth token şifreli saklama
- [ ] **F2** — KVKK/GDPR veri işleme değerlendirmesi
- [ ] **F2** — Denetim (audit) günlüğü
- [ ] **F4** — Rol tabanlı yetkilendirme (RBAC) / çoklu kullanıcı izolasyonu
