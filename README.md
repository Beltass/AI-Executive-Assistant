# AI Executive Assistant

Gmail, Google Calendar, Microsoft 365, Teams, Zoom, Slack, Notion ve
LinkedIn gibi servislerle entegre çalışan; e-postaları, takvimi,
toplantıları, hatırlatmaları ve iş başvurularını benim adıma yöneten
kişisel yapay zekâ yönetici asistanı ("dijital chief of staff").

> **Durum:** Faz 1 — ilk dikey dilim uçtan uca doğrulandı: Master
> Orchestrator + Email Agent + Calendar Agent + Morning Briefing,
> Vercel'de canlı (`ai-executive-assistant-uerc.vercel.app`) ve
> gerçek Gmail/Google Calendar verisiyle test edildi (`frontend/`).
> Sırada Memory Agent / Job Search Agent var — bkz. `docs/ROADMAP.md`.

## Bu proje ne yapar (hedef)

Sadece bir iş başvuru botu değil — e-posta triyajından takvim
yönetimine, toplantı notlarından günlük planlamaya kadar birden fazla
uzman **AI ajanının** bir **Master Orchestrator** altında koordine
olduğu, kullanıcı adına gerçek işlemler yapabilen bir asistan.

## Dokümantasyon

| Doküman | Amaç |
|---|---|
| [`CLAUDE.md`](./CLAUDE.md) | Claude Code için geliştirme kuralları ve proje bağlamı |
| [`docs/PRD.md`](./docs/PRD.md) | Ürün gereksinimleri, hedef kullanıcı, kapsam |
| [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) | Sistem mimarisi, teknoloji yığını, veri akışı |
| [`docs/AGENTS.md`](./docs/AGENTS.md) | Tüm AI ajanlarının görev tanımları |
| [`docs/ROADMAP.md`](./docs/ROADMAP.md) | Geliştirme fazları ve önceliklendirme |
| [`docs/FEATURES.md`](./docs/FEATURES.md) | Özellik listesi (MVP / gelecek) |
| [`docs/N8N_SETUP.md`](./docs/N8N_SETUP.md) | Aynı MVP'yi n8n workflow'ları olarak kurmak isteyenler için kapsam haritası |

Faz 2'de eklenecek: `DATABASE.md`, `API.md`, `SECURITY.md`,
`INTEGRATIONS.md`, `UI_UX.md`, `TEST_PLAN.md`, `DEPLOYMENT.md`,
`AI_MEMORY.md`, `AUTOMATION.md`, `PROMPTS.md`, `FUTURE.md` — mimari
kararlar netleştikçe (bkz. `docs/ROADMAP.md`).

## MVP kapsamı (Faz 1)

- 🎯 Master Orchestrator — kullanıcı isteğini ilgili ajana yönlendirir
- 💬 Chat Agent — konuşma arayüzü (dashboard üzerinden)
- 📧 Email Agent — Gmail triyaj/özet/taslak
- 📅 Calendar Agent — Google Calendar yönetimi
- 🧠 Memory Agent — kullanıcı tercihleri ve bağlam hafızası
- 💼 Job Search Agent + 📄 CV Optimizer — `Dashboard-Project/is-basvuru`
  becerilerinin bu asistana entegrasyonu

Kapsam dışı bırakılan ajanlar (Meeting, Note, Daily Planner, Reminder,
Analytics, Voice, Browser) ve entegrasyonlar (Outlook, Teams, Slack,
Notion, LinkedIn derin entegrasyonu) `docs/ROADMAP.md` ve ileride
`FUTURE.md`'de ele alınacak.

## Teknoloji yığını (Faz 1)

TypeScript uçtan uca (Next.js), Supabase (Postgres + Auth + pgvector),
Google Gemini API (`@google/genai`) — ücretsiz, kredi kartı gerektirmeyen
katman. Gerekçe için [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md)
içindeki "Teknoloji Seçimi ve Gerekçe" bölümüne bakın.

## Çalıştırma (ilk dikey dilim)

```
cd frontend
cp .env.example .env.local   # GEMINI_API_KEY girin (aistudio.google.com/apikey)
npm install
npm run dev
```
`http://localhost:3000` adresini açın. Gmail/Calendar bağlanmadıysa
Email/Calendar Agent demo veriyle çalışır.

**Gerçek Gmail/Calendar verisiyle çalıştırmak için:** `.env.example`
içindeki Google Cloud kurulum adımlarını takip edip Client ID/Secret'i
girin, ardından:
```
npm run get-google-token
```
Tarayıcıda açılan bağlantıda izin verin; script `GOOGLE_REFRESH_TOKEN`
değerini otomatik üretip ekrana basar, onu da `.env.local`'e ekleyin.

## Katkı / geliştirme

Bu depoda çalışan bir Claude Code oturumu için önce
[`CLAUDE.md`](./CLAUDE.md) dosyasını okuyun.
