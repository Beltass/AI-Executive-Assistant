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

1. [x] **Altyapı (kısmi):** Next.js iskeleti kuruldu (`frontend/`).
   Supabase projesi ve Google Cloud OAuth kimlik bilgileri henüz
   kullanıcı tarafından oluşturulmadı — bkz. §"Sıradaki adımlar".
2. [x] **Master Orchestrator + Chat Agent (ilk dikey dilim):** temel
   sohbet arayüzü + istek sınıflandırma/yönlendirme çalışıyor
   (`frontend/src/lib/agents/orchestrator.ts`).
3. [x] **Email Agent (ilk dikey dilim):** Gmail okuma/özetleme/
   önceliklendirme kodu yazıldı ve derleniyor
   (`frontend/src/lib/agents/email-agent.ts`); gerçek Gmail OAuth
   kimlik bilgileri girilene kadar demo veriyle (`MockEmailProvider`)
   çalışır. Taslak yanıt üretimi henüz eklenmedi.
4. **Calendar Agent:** Google Calendar okuma/yazma, çakışma tespiti.
5. **Memory Agent:** temel tercih/bağlam hafızası (pgvector ile basit
   RAG).
6. **Job Search Agent + CV Optimizer:** `Dashboard-Project/is-basvuru`
   mantığının bu asistana taşınması/entegrasyonu.
7. **Uçtan uca doğrulama:** PRD §7'deki başarı kriterlerinin gerçek
   kullanımla test edilmesi.

**Sıradaki adımlar (kullanıcı girdisi gerekli):**
- Ücretsiz Gemini API anahtarı (https://aistudio.google.com/apikey) →
  `frontend/.env.local` içine `GEMINI_API_KEY`
- Gerçek Gmail verisiyle test için Google Cloud OAuth kimlik bilgileri
  (`GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN`) — yoksa demo veriyle çalışmaya
  devam eder.
- Supabase projesi (Memory Agent'a geçmeden önce gerekecek).

**Çıkış kriteri:** PRD §7'deki tüm başarı kriterleri sağlanıyor.

## Faz 2 — Genişleme

- **Yeni ajanlar:** Meeting Agent, Note Agent, Daily Planner, Reminder
  Agent, Analytics Agent.
- **Yeni entegrasyon:** Microsoft 365/Outlook (Email/Calendar
  Agent'ların sağlayıcıdan bağımsız hale getirilmesi ilk adım).
- **Yeni dokümanlar (bu fazda yazılır, çünkü artık somut mimari
  kararlara oturacaklar):** `DATABASE.md`, `API.md`, `SECURITY.md`
  (KVKK/GDPR değerlendirmesi dahil), `INTEGRATIONS.md`, `UI_UX.md`,
  `TEST_PLAN.md`, `DEPLOYMENT.md` (deployment kararının kesinleşmiş
  hâli), `AI_MEMORY.md`, `AUTOMATION.md`, `PROMPTS.md`.
- **Test altyapısı:** `tests/` klasörünün doldurulması, temel
  regresyon testleri.

## Faz 3 — İleri seviye

- **Yeni ajanlar:** Voice Agent, Browser Agent.
- **Yeni entegrasyonlar:** Teams, Zoom (transkript), Slack, Notion,
  LinkedIn derin entegrasyonu.
- **Mobil:** `mobile/` klasörünün doldurulması (muhtemelen React
  Native veya Expo — karar bu faza gelindiğinde verilecek).
- `docs/FUTURE.md` bu fazın ayrıntılı planını taşıyacak.

## Faz 4 — Olgunlaşma (gerekirse)

- Çoklu kullanıcı/SaaS'a geçiş değerlendirmesi (bugün planlanmıyor,
  yalnızca olasılık olarak not düşülüyor — bkz. PRD §1).
- Gelişmiş güvenlik/uyumluluk sertleştirmesi.
- Analitik/ölçeklenme optimizasyonları.

## Önceliklendirme ilkesi

Bir sonraki fazın ajanlarına/entegrasyonlarına geçmeden önce mevcut
fazın **çıkış kriteri** sağlanmalı. Paralel olarak 14 ajanın hepsini
"biraz biraz" geliştirmek yerine, MVP'nin gerçekten uçtan uca
çalıştığından emin olup öyle genişlemek tercih edilir.
