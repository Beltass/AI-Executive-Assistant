# CLAUDE.md

Claude Code (ve diğer AI asistanları) için bu depoda geliştirme
yaparken uyulması gereken kurallar ve proje bağlamı.

## Proje nedir

Bu bir chatbot değil — kullanıcının **AI Chief of Staff'ı**. Gmail,
Google Calendar ve zamanla Microsoft 365, Teams, Zoom, Slack, Notion,
LinkedIn gibi servislerle entegre çalışan, kullanıcı adına proaktif
işlem yapabilen kişisel bir yapay zekâ yönetici asistanı. Tek kullanıcı
için tasarlanıyor (proje sahibi: Burak Eltaş) — çoklu kiracı/SaaS/RBAC
değil (bkz. `docs/PRD.md` §1). Tasarım ilkeleri (proaktif, çok ajanlı,
izin tabanlı, hafızalı, açıklanabilir, modüler, tek-kullanıcı-güvenli)
için `docs/PRD.md` §1'e bakın — yeni bir özellik/ajan önerirken bu
ilkelere göre değerlendirin.

**Önce şunları oku:** `docs/PRD.md` (ne inşa ediyoruz ve neden),
`docs/ARCHITECTURE.md` (nasıl inşa ediyoruz), `docs/AGENTS.md` (hangi
ajan ne yapar), `docs/ROADMAP.md` (hangi sırayla). Bu dosyalar
sözleşme niteliğindedir — kod, buradaki kararlarla çelişiyorsa ya kodu
ya da dokümanı düzelt, ikisini tutarsız bırakma.

## Mevcut durum

**Faz 0 — dokümantasyon tamamlandı, kod henüz yazılmadı.** Klasör
iskeleti (`agents/`, `backend/`, `frontend/`, `mobile/`, `api/`,
`database/`, `integrations/`, `prompts/`, `automation/`, `tests/`,
`deployment/`) her klasörde ne bekleneceğini açıklayan bir `README.md`
stub'ıyla oluşturuldu; içleri Faz 1'de doldurulmaya başlanacak.

## Teknoloji yığını (Faz 1)

TypeScript uçtan uca · Next.js (App Router) · Supabase (Postgres +
Auth + pgvector) · Google Gemini API (`@google/genai`) — Anthropic
Claude API'nin ücretsiz bir katmanı olmadığı kullanıcı testinde ortaya
çıktığı için Gemini'ye geçildi (bkz. `docs/ARCHITECTURE.md` §1 ve §8).
LLM erişimi tek dosyada izole (`frontend/src/lib/llm.ts`) — ileride
sağlayıcı değişirse Orchestrator/ajan kodunun geri kalanı etkilenmemeli.
Deployment hedefi (Vercel + Supabase önerisi) henüz kullanıcı
tarafından kesinleştirilmedi — `DEPLOYMENT.md` (Faz 2) yazılana kadar
bunu varsayım olarak kullan, geri dönüşü kolay tut (ör. hosting'e sıkı
bağımlı kod yazma).

## MVP kapsamı — kapsam genişlemesine karşı en önemli kural

MVP (Faz 1) **yalnızca** şunları içerir: Master Orchestrator, Chat
Agent, Email Agent (Gmail), Calendar Agent (Google Calendar), Memory
Agent, Job Search Agent, CV Optimizer. Toplam 14 ajan planlanıyor
olsa da (`docs/AGENTS.md`), geri kalanı Faz 2/3'e ait. Bir görev
sırasında "madem buradayız, X ajanını da ekleyelim" dürtüsüne
**karşı çık** — `docs/ROADMAP.md`'deki faz sırasını takip et. Kullanıcı
açıkça bir sonraki faza geçmeyi istemedikçe kapsamı genişletme.

## Job Search Agent / CV Optimizer — mevcut mantığı yeniden kullan

Bu iki ajanın iş mantığı sıfırdan tasarlanmayacak: kaynak,
`Dashboard-Project` reposundaki `is-basvuru/.claude/skills/{scrape,apply}`
becerileridir (aynı hesabın kardeş reposu). O becerilerdeki kurallar
bu ajanlar için de geçerlidir:
- Hiçbir siteye otomatik giriş/CAPTCHA bypass yok.
- Hiçbir form otomatik gönderilmez, hiçbir "Kolay Başvuru" tıklanmaz —
  kullanıcı her zaman taslağı inceleyip kendisi gönderir.
- `profil.md`'deki olgusal veriler (deneyim, tarih, rakam) asla
  abartılmaz/uydurulmaz.
- Uygunluk puanı <50 olan ilanlar için taslak üretilmez.

Bu "önce taslak, sonra kullanıcı onayı, asla otomatik gönderim"
ilkesi yalnızca bu iki ajana değil, **tüm asistana** geneldir (bkz.
`docs/ARCHITECTURE.md` §3, `docs/PRD.md` §6).

## Klasör yapısı

```
CLAUDE.md, README.md          # kök: bu dosyalar
docs/                          # ürün/mimari dokümantasyonu (bkz. yukarısı)
agents/                        # ajan implementasyonları (1 ajan = 1 alt klasör: prompt + araçlar + testler)
backend/                       # Next.js API routes, Orchestrator, iş mantığı
frontend/                      # Next.js dashboard UI (chat arayüzü)
database/                      # Supabase şema/migration
integrations/                  # servis bazlı connector (gmail/, google-calendar/, ...)
mobile/, api/, prompts/,
automation/, tests/, deployment/  # Faz 2/3'te doldurulacak — bkz. ROADMAP
```

Detaylı gerekçe ve veri akışı için `docs/ARCHITECTURE.md`.

## Geliştirme kuralları

- **Dil:** Kullanıcıya dönük metinler (UI, ajan yanıtları, commit
  mesajları açıklaması) Türkçe öncelikli olabilir; kod (değişken/fonksiyon
  adları, yorumlar) İngilizce — mevcut `is-basvuru` deposundaki Türkçe
  içerik/İngilizce kod ayrımıyla tutarlı.
- **Asgari yetki:** Her ajan yalnızca görevi için gerekli araca/veriye
  erişsin; Orchestrator'a veya birbirine gereğinden fazla yetki verme.
- **Sağlayıcıdan bağımsız arayüzler:** Email/Calendar Agent'ları
  doğrudan Gmail/Google Calendar'a sıkı bağlı yazma — Faz 2'de Outlook
  eklenecek, bu yüzden `EmailProvider`/`CalendarProvider` gibi bir
  soyutlama düşün (ama Faz 1'de tek implementasyon: Google).
- **Şema tasarımı:** `user_id` alanlarını şimdiden ekle (ileride çoklu
  kullanıcıya geçiş şema göçü gerektirmesin) ama yetkilendirme/izolasyon
  mantığını Faz 1'de kurma — bu bilinçli bir "ileriye hazır ama
  bugün gereksiz karmaşıklık yok" dengesi (bkz. `docs/PRD.md` §1).
- Henüz test altyapısı (`tests/`) kurulmadı — kod yazmaya
  başlandığında en azından ajan sözleşmelerini (girdi/çıktı formatı)
  doğrulayan testler ekle.

## Git workflow

- Ana dal: `main`.
- Repo GitHub'da `Beltass/AI-Executive-Assistant` olarak barındırılıyor.
