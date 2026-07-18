# N8N_SETUP.md — n8n ile paralel/alternatif kurulum

Bu doküman, `frontend/` altındaki Next.js + Gemini MVP'sinin **iş
mantığını** bir kod yazmadan, n8n workflow'ları olarak yeniden
kurmak isteyenler için bir kapsam/harita dokümanıdır. n8n sürümü,
Next.js sürümünün yerini almaz — aynı mimarinin görsel-workflow
alternatifidir (ör. tarayıcı/kod erişimi kısıtlı bir cihazdan
yönetmek isteyen kullanıcılar için). İki sürüm de aynı ilkelere
(`docs/PRD.md` §1) ve aynı MVP kapsamına (`docs/ROADMAP.md` Faz 1)
bağlıdır; biri güncellenirse diğeri de gözden geçirilmeli.

## 0. Önce okunacaklar

n8n workflow'larını kurmadan önce şu dokümanlardaki kararları
bilmek gerekir — burada tekrar etmiyoruz, referans veriyoruz:
- `docs/PRD.md` §1 — 7 tasarım ilkesi (proaktif, çok ajanlı, izin
  tabanlı, hafızalı, açıklanabilir, modüler, güvenli).
- `docs/ARCHITECTURE.md` §3 — taslak → onay akışı (n8n'de de
  birebir korunmalı).
- `docs/AGENTS.md` — her ajanın görev tanımı, hangi ajan MVP'de
  aktif.
- `docs/FEATURES.md` — MVP'de olan/olmayan özellikler.

## 1. Kapsam — yalnızca MVP (Faz 1)

`CLAUDE.md`'deki kapsam-genişlemesi uyarısı n8n kurulumu için de
geçerlidir: yalnızca şu altı bileşen kurulur, gerisi Faz 2/3'e
bırakılır.

1. Master Orchestrator
2. Chat Agent (n8n'de: Chat Trigger düğümü)
3. Email Agent (Gmail)
4. Calendar Agent (Google Calendar)
5. Memory Agent (Postgres/Supabase)
6. Job Search Agent + CV Optimizer (`Dashboard-Project/is-basvuru`
   mantığı)

Morning Briefing, Email + Calendar Agent'ı yeniden kullanan
"neredeyse bedava" bir bonus olduğu için (bkz. `ROADMAP.md` 5b) bu
listeye eklendi (7. madde, aşağıda).

**Şimdi kurulmayacaklar** (Faz 2/3, bkz. `AGENTS.md`/`ROADMAP.md`):
Meeting Agent, Note/Document Agent, Reminder Agent/Smart Automation,
Analytics Agent, Executive Dashboard, Voice Agent, Browser Agent,
Outlook/Teams/Zoom/Slack/Notion/LinkedIn derin entegrasyonları, AI
Learning geri bildirim döngüsü, RBAC/çoklu kullanıcı.

## 2. Gerekli n8n credential'ları

| Credential | Tip | Kullanan node'lar | Not |
|---|---|---|---|
| Gmail OAuth2 | Gmail node credential | Email Agent, Morning Briefing | Sadece `gmail.readonly` (+ taslak için `gmail.compose`); gönderme izni **verilmez** — onay akışı manuel gönderim üzerinden çalışır |
| Google Calendar OAuth2 | Google Calendar node credential | Calendar Agent, Morning Briefing | Etkinlik oluşturma da taslak/onay akışından geçer (bkz. §4) |
| Gemini API key | HTTP Request node header / Google Gemini node credential (varsa) | Master Orchestrator, tüm ajan alt-workflow'ları | `aistudio.google.com/apikey`, ücretsiz katman |
| Postgres/Supabase | Postgres node credential | Memory Agent, Job Search Agent takip kaydı | `frontend`'deki Supabase projesiyle aynısı yeniden kullanılabilir |

LinkedIn için **credential kurulmaz** — `is-basvuru`'nun ToS
kısıtı (otomatik giriş yok) n8n'de de geçerli; LinkedIn/kariyer.net
taraması yalnızca genel arama sonuçları (HTTP Request/arama node'u)
üzerinden, düşük hacimli ve insan gözetiminde yapılır.

## 3. Workflow haritası

n8n'de "Master Orchestrator" tek bir dev workflow değil; her ajan
ayrı bir **alt-workflow** (Execute Workflow node ile çağrılan) olarak
kurulup Orchestrator bunları yönlendirir. Bu, Next.js sürümündeki
`frontend/src/lib/agents/*.ts` dosya ayrımının n8n karşılığıdır.

### 3.1 Master Orchestrator workflow

- **Chat Trigger** node (n8n'in yerleşik chat arayüzü) — kullanıcı
  mesajını alır.
- **AI Agent** node (Gemini destekli, function-calling/tools açık) —
  `frontend/src/lib/agents/orchestrator.ts`'deki üç tool tanımının
  (`summarize_inbox`, `summarize_upcoming_schedule`,
  `get_morning_briefing`) n8n karşılığı: her biri bir **Tool**
  olarak bu node'a bağlanan bir **Execute Workflow (as Tool)**
  düğümü.
- Sistem promptu, Next.js'teki orchestrator prompt'uyla aynı
  ilkeleri taşımalı: hangi ajana yönlendirileceği, birden fazla
  ajan çıktısını birleştirme, ve **dış dünyaya giden hiçbir eylemi
  kendi başına kesinleştirmeme** kuralı (bkz. §4).

### 3.2 Email Agent alt-workflow

- **Execute Workflow Trigger** (girdi: `limit`, varsayılan 5).
- **Gmail** node → `Get Many` (son N mail, `me`/inbox).
- **AI Agent**/**Basic LLM Chain** node (Gemini, `thinkingConfig`
  eşdeğeri yoksa n8n'in Gemini node'unda "thinking" ayarını kapalı
  tutun — Next.js tarafında bu ayarın unutulması yanıtları
  bozmuştu, bkz. `docs/ARCHITECTURE.md` §8) → özet + öncelik
  sıralaması üretir.
- Çıktı, Orchestrator'a **salt metin özet** olarak döner; hiçbir
  mail bu workflow içinde yanıtlanmaz/gönderilmez.

### 3.3 Calendar Agent alt-workflow

- **Execute Workflow Trigger** (girdi: `hoursAhead`, varsayılan 24).
- **Google Calendar** node → `Get Many` (belirtilen pencere).
- **AI Agent** node → özet + çakışma tespiti (prompt'ta "çakışan
  etkinlikleri belirt" talimatı — `MockCalendarProvider`'daki
  bilerek-çakışan iki etkinlik testi burada da geçerli bir test
  senaryosu).
- Etkinlik oluşturma/düzenleme/iptal (yazma işlemleri) bu alt-
  workflow'a **eklenmez** — bunlar dış dünyaya giden eylemler,
  ayrı bir onay akışı gerektirir (§4), MVP'nin ilk sürümünde yok
  (bkz. `FEATURES.md`, henüz işaretlenmemiş).

### 3.4 Memory Agent alt-workflow

- **Execute Workflow Trigger** (girdi: `query` veya `factToStore`).
- **Postgres**/Supabase node → pgvector tablosuna okuma/yazma
  (basit RAG: embedding + benzerlik araması).
- Diğer tüm ajan alt-workflow'ları, kişiselleştirme gerektiren
  adımlarda bu alt-workflow'u bir **Tool** olarak çağırabilir
  (Next.js tarafında henüz kodlanmadı — bkz. `ROADMAP.md` madde 5,
  hâlâ MVP'de sırada).

### 3.5 Job Search Agent + CV Optimizer alt-workflow

`Dashboard-Project/is-basvuru/.claude/skills/{scrape,apply}`
mantığının n8n karşılığı; bu iki skill'in kuralları **birebir**
geçerli (bkz. bu reponun `CLAUDE.md`'si, "Job Search Agent / CV
Optimizer — mevcut mantığı yeniden kullan" bölümü):

- **scrape:** HTTP Request/arama node'ları ile kariyer.net + genel
  arama (LinkedIn'e otomatik giriş **yok**) → sonuçları
  `takip.csv`/Postgres tablosuna karşı dedupe eden bir Postgres
  sorgusu → kısa liste.
- **apply:** seçilen ilan için AI Agent node, `reviewer-kriterleri.md`
  rubriğini prompt'a gömerek 0-100 puan üretir. Akış dallanması
  (**IF/Switch** node):
  - ≥70 → devam: `profil.md` verisiyle CV/ön yazı taslağı üretimi.
  - 50-69 → kullanıcıya sor (Orchestrator'a "onay bekliyor" durumu
    döner, otomatik ilerlemez).
  - <50 → `durum=atlandi` ile Postgres/`takip.csv`'ye logla, taslak
    **üretme**.
- **Hiçbir node otomatik form göndermez veya "Kolay Başvuru"
  tıklamaz** — bu, n8n sürümünde de mutlak bir kural.

### 3.6 Morning Briefing workflow

- **Cron** (veya kullanıcı "günaydın" dediğinde Chat Trigger'dan
  tetiklenen) node.
- **Execute Workflow** ile Email Agent (limit 5) ve Calendar Agent
  (hoursAhead 16) **paralel** çağrılır (n8n'de iki dal, sonra
  **Merge** node — Next.js tarafındaki `Promise.all` eşdeğeri).
- Ekstra bir LLM çağrısı **gerekmez** — iki alt-workflow çıktısı
  sabit bir Türkçe şablonla birleştirilir (Next.js'teki
  `planner-agent.ts` mantığıyla birebir, bkz. `ROADMAP.md` 5b).

## 4. Zorunlu taslak → onay akışı

`ARCHITECTURE.md` §3'teki kural n8n'de şu şekilde uygulanır — bu
adım atlanmamalı:

1. Dış dünyaya giden bir eylem üretecek her alt-workflow (mail
   yanıtı, takvim daveti, iş başvurusu materyali) sonucu
   **göndermez**, yalnızca bir taslak/öneri metni döner.
2. Orchestrator bu taslağı kullanıcıya (chat arayüzünde) gösterir
   ve açıkça onay ister.
3. Kullanıcı onaylarsa, **ayrı, açık bir adım** (ör. Gmail node'unun
   `Create Draft` çıktısını kullanıcı kendi Gmail'inden gönderir,
   ya da n8n'de gönderim izni olan ayrı bir onaylı node yalnızca bu
   adımdan sonra tetiklenir).
4. Onay verilmeden hiçbir node "send"/"submit"/"Easy Apply"
   eylemine ulaşmamalı — workflow tasarımında bu node'ları ayrı,
   manuel tetiklemeli (n8n'in `Wait for approval` deseni veya ayrı
   bir "onaylandı" webhook'u) tutmak, yanlışlıkla otomatik
   zincirlenmeyi engeller.

## 5. Faz 1 çıkış kriteri (n8n sürümü için de aynı)

`PRD.md` §7'deki kriterler burada da geçerli:
- Kullanıcı Gmail'i manuel taramadan öncelikli mailleri görebiliyor.
- Takvim çakışmaları proaktif fark ediliyor.
- En az bir gerçek iş başvurusu uçtan uca (tarama → puanlama →
  taslak → kullanıcı onayı → takip kaydı) tamamlanabiliyor.
- Önceki oturumda paylaşılan bir tercih sonraki oturumda
  hatırlanıyor (Memory Agent).

## 6. Bu dokümanın sınırı

Bu doküman bir **kapsam haritasıdır**, adım adım n8n ekran
görüntülü bir kurulum kılavuzu değildir (n8n arayüzü sık
güncellendiği için ekran bazlı talimatlar hızla eskir). Kurulum
sırasında karşılaşılan spesifik hatalar/credential sorunları için
bu deponun `README.md`'sindeki "Çalıştırma" bölümündeki OAuth
kurulum notları (Google Cloud Console adımları) referans alınabilir
— aynı Google Cloud projesi/credential'lar hem Next.js hem n8n
sürümünde kullanılabilir.
