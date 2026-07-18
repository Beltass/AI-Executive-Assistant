# ROADMAP.md — Geliştirme Fazları

## Faz 0 — Dokümantasyon ve mimari (şu an)

- [x] `CLAUDE.md`, `README.md` — proje bağlamı
- [x] `docs/PRD.md` — ürün gereksinimleri
- [x] `docs/ARCHITECTURE.md` — mimari + teknoloji seçimi
- [x] `docs/AGENTS.md` — ajan tanımları
- [x] `docs/ROADMAP.md` — bu doküman
- [x] `docs/FEATURES.md` — özellik listesi
- [x] Klasör iskeleti (`agents/`, `backend/`, `frontend/`, `mobile/`,
      `api/`, `database/`, `integrations/`, `prompts/`, `automation/`,
      `tests/`, `deployment/`)
- [ ] Deployment kararının kesinleştirilmesi → `DEPLOYMENT.md`
- [ ] Faz 2 dokümanları: `DATABASE.md`, `API.md`, `SECURITY.md`,
      `INTEGRATIONS.md`, `UI_UX.md`, `TEST_PLAN.md`, `AI_MEMORY.md`,
      `AUTOMATION.md`, `PROMPTS.md`, `FUTURE.md`

**Çıkış kriteri:** Kullanıcı Faz 1 kapsamını (bu dokümanlardaki MVP
tanımı) onaylar.

## Faz 1 — MVP (Çekirdek 4 + Job Search/CV)

Hedef: tek kullanıcı için gerçekten kullanılabilir bir asistan.

1. [x] **Altyapı:** Next.js iskeleti kuruldu (`frontend/`), Vercel'e
   deploy edildi (`ai-executive-assistant-uerc.vercel.app`). Google
   Cloud OAuth kimlik bilgileri (Client ID/Secret/Refresh Token)
   oluşturuldu, Gmail API + Calendar API etkinleştirildi ve canlı
   ortamda doğrulandı. Supabase projesi henüz kurulmadı (Memory
   Agent'a geçmeden önce gerekecek).
2. [x] **Master Orchestrator + Chat Agent (ilk dikey dilim):** temel
   sohbet arayüzü + istek sınıflandırma/yönlendirme çalışıyor
   (`frontend/src/lib/agents/orchestrator.ts`); aynı oturum içindeki
   önceki mesajlar artık modele geçmiş (history) olarak gönderiliyor,
   böylece takip soruları ("bu mailde ne yazıyordu?") bağlamı
   koruyor. Bu, oturumlar arası kalıcı hafıza değil — o, ayrı
   maddedeki Memory Agent'a ait (bkz. madde 5).
3. [x] **Email Agent (ilk dikey dilim):** Gmail okuma/özetleme/
   önceliklendirme çalışıyor (`frontend/src/lib/agents/email-agent.ts`)
   — **gerçek Gmail verisiyle canlı ortamda doğrulandı**. Gmail'in
   kısa otomatik snippet'i yerine e-postanın gerçek gövdesi (`format:
   "full"`, `text/plain`/`text/html` ayrıştırma) kullanılıyor ve özet
   promptu somut ayrıntı (kim, ne zaman, ne kadar, ne istiyor)
   içerecek şekilde güncellendi — ilk sürümde özetler fazla yüzeysel
   kalıyordu. OAuth kimlik bilgisi yoksa `MockEmailProvider` ile demo
   veriyle de çalışmaya devam eder. Taslak yanıt üretimi henüz
   eklenmedi.
4. [x] **Calendar Agent (ilk dikey dilim):** Google Calendar okuma +
   LLM tabanlı özet/çakışma tespiti çalışıyor
   (`frontend/src/lib/agents/calendar-agent.ts`) — **gerçek Calendar
   verisiyle canlı ortamda doğrulandı** (kimlik bilgisi yoksa
   `MockCalendarProvider`, bilerek çakışan iki etkinlik içerir, ile
   demo veriyle de çalışmaya devam eder). Etkinlik oluşturma/
   düzenleme/iptal ve uygun saat önerisi (yazma işlemleri) henüz
   eklenmedi — bunlar dış dünyaya giden eylemler olduğu için taslak/
   onay akışı gerektiriyor (bkz. `ARCHITECTURE.md` §3), ayrı bir adım
   olarak ele alınacak.
5. **Memory Agent:** temel tercih/bağlam hafızası (pgvector ile basit
   RAG).
5b. [x] **Morning Briefing (bonus, neredeyse bedava):** Email + Calendar
   Agent'ı birleştiren `get_morning_briefing` aracı eklendi
   (`frontend/src/lib/agents/planner-agent.ts`) — ek Gemini çağrısı
   olmadan (sadece iki mevcut ajanı yeniden kullanarak) "günaydın"
   raporu üretiyor. Kritik görevler/teslim tarihleri henüz yok (görev
   sistemi gerektiriyor, Faz 2).
6. [x] **Job Search Agent + CV Optimizer:** `Dashboard-Project/is-basvuru`
   mantığının bu asistana taşınması (`frontend/src/lib/agents/job-search-agent.ts`).
   `profil.md` ve `reviewer-kriterleri.md` kardeş repodan birebir
   kopyalandı (`frontend/src/lib/agents/job-search/`); puanlama rubriği
   ve "olgusal içerik asla değiştirilmez" kuralı aynen korunuyor. İki
   ortam-kaynaklı uyarlama (bkz. `ARCHITECTURE.md` §8): (a) çıktı
   pdflatex/PDF yerine tek sütunlu Markdown CV — Vercel serverless'ta
   LaTeX toolchain yok; (b) otomatik LinkedIn/kariyer.net ARAMASI yok —
   yalnızca kullanıcının verdiği tek bir ilan metni/URL'si değerlendirilir
   (orijinal `scrape` becerisi de zaten kullanıcı onaylı URL istiyordu).
   Başvuru takip günlüğü Supabase'e yazılır; Supabase henüz kurulmadıysa
   oturum-bazlı (kalıcı olmayan) belleğe düşer — bkz. `.env.example`.
7. **Uçtan uca doğrulama:** PRD §7'deki başarı kriterlerinin gerçek
   kullanımla test edilmesi — Job Search Agent henüz canlıda gerçek bir
   ilanla denenmedi (yalnızca `npm run typecheck`/`build` doğrulandı).

**Sıradaki adımlar (kullanıcı girdisi gerekli):**
- ~~Ücretsiz Gemini API anahtarı~~ — tamamlandı, canlı ortamda çalışıyor.
- ~~Gerçek Gmail/Calendar verisiyle test için Google Cloud OAuth kimlik
  bilgileri~~ — tamamlandı, `ai-executive-assistant-uerc.vercel.app`
  üzerinde gerçek verilerle doğrulandı.
- Job Search Agent'ı canlıda gerçek bir ilanla test et (bir ilan
  yapıştır, "bu ilana uygun muyum?" de) — PRD §7'deki "en az bir gerçek
  başvuru uçtan uca tamamlanabiliyor" kriteri için gerekli.
- Supabase projesi (kurulursa hem Job Search Agent'ın takip günlüğü hem
  ileride Memory Agent kalıcı hale gelir) — kurulum adımları
  `.env.example`'da.
- Kalan Faz 1 parçası: **Memory Agent** (oturumlar arası hafıza).

**Çıkış kriteri:** PRD §7'deki tüm başarı kriterleri sağlanıyor.

## Faz 2 — Genişleme

- **Yeni ajanlar/yetenekler:** Meeting Agent (Meeting Intelligence),
  Note/Document Agent, Daily Planner (+ Morning Briefing / Evening
  Report), Reminder Agent, Analytics Agent (Decision Support,
  Relationship Manager, Workload Analysis).
- **Executive Dashboard:** sohbet ekranının yanına özet ekranı
  (okunmamış mail, bugünkü toplantılar, kritik görevler, bekleyen
  onaylar) — bkz. `AGENTS.md`.
- **AI Learning:** Memory Agent'a kullanıcı düzeltmelerinden öğrenme
  geri bildirim döngüsü.
- **Yeni entegrasyon:** Microsoft 365/Outlook (Email/Calendar
  Agent'ların sağlayıcıdan bağımsız hale getirilmesi ilk adım).
- **Yeni dokümanlar (bu fazda yazılır, çünkü artık somut mimari
  kararlara oturacaklar):** `DATABASE.md`, `API.md`, `SECURITY.md`
  (KVKK/GDPR + tek kullanıcı için token şifreleme/audit log — RBAC
  değil, bkz. `PRD.md` §1), `INTEGRATIONS.md`, `UI_UX.md`,
  `TEST_PLAN.md`, `DEPLOYMENT.md` (deployment kararının kesinleşmiş
  hâli), `AI_MEMORY.md`, `AUTOMATION.md` (Smart Automation kuralları
  dahil), `PROMPTS.md`.
- **Test altyapısı:** `tests/` klasörünün doldurulması, temel
  regresyon testleri.

## Faz 3 — İleri seviye

- **Yeni ajanlar:** Voice Agent, Browser Agent (Research Agent dahil).
- **Job Search Intelligence:** şirket/kültür analizi, maaş tahmini,
  başarı olasılığı — veri kaynağı kararı gerekiyor (bkz. `AGENTS.md`
  risk notu, Glassdoor'un ücretsiz API'si yok).
- **Yeni entegrasyonlar:** Teams, Zoom (transkript), Slack, Notion,
  LinkedIn derin entegrasyonu.
- **Mobil:** `mobile/` klasörünün doldurulması (muhtemelen React
  Native veya Expo — karar bu faza gelindiğinde verilecek); Voice
  Agent muhtemelen mobil ile birlikte gelir.
- `docs/FUTURE.md` bu fazın ayrıntılı planını taşıyacak.

## Faz 4 — Olgunlaşma (gerekirse)

- Çoklu kullanıcı/SaaS'a geçiş değerlendirmesi ve **rol tabanlı
  yetkilendirme (RBAC)** — bugün planlanmıyor, yalnızca olasılık
  olarak not düşülüyor (bkz. PRD §1). Faz 1-3 boyunca güvenlik "tek
  kullanıcı için sağlam" anlamına gelir (token şifreleme, audit log,
  asgari yetki), çoklu-kiracı izolasyon değil.
- Gelişmiş güvenlik/uyumluluk sertleştirmesi.
- Analitik/ölçeklenme optimizasyonları.

## Önceliklendirme ilkesi

Bir sonraki fazın ajanlarına/entegrasyonlarına geçmeden önce mevcut
fazın **çıkış kriteri** sağlanmalı. Paralel olarak 14 ajanın hepsini
"biraz biraz" geliştirmek yerine, MVP'nin gerçekten uçtan uca
çalıştığından emin olup öyle genişlemek tercih edilir.
