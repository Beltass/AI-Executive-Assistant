# AI-Executive-Assistant

A production-ready **AI Executive Assistant** — your personal digital chief of
staff. This repository currently contains the project skeleton and a runnable
**connection check** that verifies whether each integration the assistant
relies on is configured and reachable.

## Integrations covered

| Integration      | Purpose                    | Required env var(s)                          |
| ---------------- | -------------------------- | -------------------------------------------- |
| Gmail            | Email                      | Google OAuth (see below)                     |
| Google Calendar  | Scheduling                 | Google OAuth (see below)                     |
| Google Drive     | Documents / files          | Google OAuth (see below)                     |
| Slack            | Messaging                  | `SLACK_BOT_TOKEN`                            |
| Todoist          | Tasks                      | `TODOIST_API_TOKEN`                          |
| Notion           | Notes / knowledge base     | `NOTION_API_KEY`                             |
| LLM (Gemini/OpenAI) | Reasoning engine        | `GEMINI_API_KEY` or `OPENAI_API_KEY`         |

Gmail, Calendar and Drive share a single Google account and one OAuth consent
via a **permanent** login: you authorize once, a refresh token is stored, and
every subsequent run refreshes the short-lived access token automatically. See
[Google OAuth login](#google-oauth-login) below.

Each check **skips** gracefully when its credentials are missing, so the tool
runs cleanly out of the box before you have configured anything.

## Daily advisor team

On top of the connection checks the assistant ships a **supervised team of
daily advisor agents** that produce a single Turkish morning briefing.

The live roster is **thirteen** advisors, in report order (the Turkish titles
are the ones the dashboard and Slack show; the key is the stable identifier used
by `SLACK_CHANNEL_<KEY>` and by `frontend/reports/`):

| # | Advisor (`key`) | Persona | Needs |
| - | --------------- | ------- | ----- |
| 1 | 📋 Sabah İşletme Brifingi (`morning_operations`) | Chief-of-staff start-of-day briefing: yesterday's numbers, today's priorities | Google OAuth for the mail/calendar facts (+ an LLM key to deepen it) |
| 2 | 📬 İletişim & Takvim Danışmanı (`communications_calendar`) | Mail load, action items, meeting density and free focus blocks | Google OAuth + an LLM key |
| 3 | 🗓️ Toplantı Hazırlık & Takip (`meeting_prep`) | Executive-assistant prep note for the next meeting: what was said last time, what is still open, this time's agenda | Google OAuth (Calendar + Drive); `MEETING_PREP_NOTES_FOLDER_ID` or `GOOGLE_DRIVE_FOLDER_ID` for the past notes |
| 4 | 💼 Kariyer Gelişimi (İK · İlanlar · İngilizce · Sertifika) (`career_development`) | HR mentor + job scout + business-English coach + free-certificate hunter, in one call | An LLM key (`JOB_KEYWORDS` / `JOB_LOCATION` / `USER_SECTOR` have defaults) |
| 5 | 📊 Pazar İstihbaratı (Sektör · YZ · CX · Bankacılık) (`market_intelligence`) | Sector & competitor intel, AI news, CX research and bank contact-center governance, in one call | An LLM key (every RSS feed has a default) |
| 6 | 📣 Müşteri Şikayet & İtibar Radarı (`complaint_radar`) | Reads the sector's complaint agenda from RSS, groups it into fixed themes and INTERPRETS it (volume, competitor comparison, which KPI it presses) | Nothing — both feeds have defaults; an LLM key turns the headlines into commentary |
| 7 | 🔬 Veri Analisti (Çağrı Merkezi Operasyonu) (`data_analyst`) | Reads the operation's own numbers (`ai_assistant.analysis`) and says what they mean | A data source (`DATA_ANALYST_SOURCE`) + an LLM key |
| 8 | 🧠 Yapay Zeka & İnovasyon (Ustalaşma · Fikirler) (`ai_innovation`) | AI enablement lesson of the day + concrete project proposals scored for effort/impact | An LLM key (`AI_MASTERY_LEVEL` / `AI_MASTERY_RSS_URL` have defaults) |
| 9 | 👨‍👩‍👧 Çocuk Gelişimi Danışmanı (`kids_development`) | Child development & education advisor | An LLM key |
| 10 | 🧭 Yönetici Koçu (Gelişim + Hesap Verebilirlik) (`executive_coaching`) | Leadership coaching plus the accountability streak over yesterday's tasks | An LLM key (the accountability half needs none) |
| 11 | 📈 İş Analisti Danışmanı (`work_analyst`) | Watches the run itself: anomalies, bottlenecks, repeated failures | An LLM key |
| 12 | 🚦 Operasyon Direktörü (Günün Kararları) (`operations_director`) | Turns the whole run into ONE prioritised decision list (owner · deadline · cost of inaction) | An LLM key |
| 13 | 🛡️ Teknik Gözetim (7/24 SRE) (`sre_watchdog`) | The machine's own watchdog: run freshness, quota, artefacts | Nothing — **no LLM call at all** |

Many of these are *consolidations*: the specialist personas described in the
phase sections below (job scout, sector intel, AI news, accountability coach, …)
still live in `src/ai_assistant/advisors/`, but they now contribute to one of
the thirteen briefings above instead of writing their own.

Each advisor exposes one interface — `generate_briefing()` — returning a
structured `Briefing` (title, status `ok`/`failed`/`skipped`, text). All
network/LLM calls are guarded, so a missing key means `skipped` and a broken
call means `failed`; neither crashes the run.

### Phase 2 advisors

Four additional supervised agents extend the team. They follow the exact same
`Advisor` interface, so the Operations Manager auto-discovers them, and they
degrade to `skipped` when their config/LLM key is absent.

| Advisor                          | Persona                                              | Needs                                              |
| -------------------------------- | ---------------------------------------------------- | -------------------------------------------------- |
| İş Avcısı & Başvuru Hazırlayıcı  | Prepares target roles, CV/cover-letter bullets & search links | An LLM key (`JOB_KEYWORDS`/`JOB_LOCATION` have defaults) |
| Sektör & Rakip İstihbaratı       | Sector technology/AI & competitor briefing           | An LLM key (`USER_SECTOR`, `SECTOR_NEWS_RSS_URL` have defaults) |
| Yapay Zeka Haberleri             | AI news roundup from a feed or LLM                    | Nothing — `AI_NEWS_RSS_URL` has a default feed; an LLM key deepens it |
| Ücretsiz Sertifika & Eğitim      | Free certs/courses & language resources for your field | LLM key (opt. `USER_SECTOR`)                     |

**İş Avcısı compliance note.** The job scout deliberately does **not** log in to
or auto-submit applications on LinkedIn / Kariyer.net (that would breach their
Terms of Service and is irreversible). Instead it **prepares** material for you
to review and submit yourself: suggested target roles, tailored CV/cover-letter
bullet points, and plain, ready-to-use SEARCH URLs for LinkedIn Jobs and
Kariyer.net built from your keywords/location.

**Sektör & Yapay Zeka Haberleri caveats.** Because live financial/graph data and
the very latest headlines aren't reliably fetchable, these briefings are
LLM-based and carry an honest caveat that figures/links are not real-time and
should be verified. `SECTOR_NEWS_RSS_URL` / `AI_NEWS_RSS_URL` default to Turkish
Google News search feeds, so recent headlines (with their real links) are folded
in out of the box — fetched with `httpx` + stdlib `xml.etree` and guarded, so an
unreachable feed degrades to the LLM-only roundup instead of failing.

### Phase 3 advisors

Four more supervised agents, discovered the same way and degrading to
``skipped`` exactly like the rest.

| Advisor                              | Persona                                                            | Needs                                                     |
| ------------------------------------ | ------------------------------------------------------------------ | --------------------------------------------------------- |
| Banka & Çağrı Merkezi Proje Uzmanı   | Outsourcing **governance, security compliance & information security** for bank contact centers | An LLM key (both RSS feeds have defaults)   |
| Hesap Sorucu Koç                     | Behaviour-science accountability coach over the other advisors' tasks | Nothing — **no LLM call at all** (`ACCOUNTABILITY_STATE_FILE` has a default) |
| Gün Başı Operasyon Brifingi          | Chief-of-staff morning briefing from Gmail + Calendar               | The one-time **Google OAuth login** (+ an LLM key to deepen it) |
| İngilizce & Yönetici İletişimi Koçu  | Business-English + executive-presence coach                          | An LLM key (opt. `USER_SECTOR`)                            |

**Banka & Çağrı Merkezi Proje Uzmanı** is a deep *domain* expert, deliberately
distinct from the broader `sector_intel` agent: it writes like a senior
consultant who has both **run** bank contact-center outsourcing programs and
**been audited** on them. Its centre of gravity is the question the regulator and
your CISO will actually ask — *what rules must a bank observe when it outsources
a contact center, and what do you watch for on security and information
security?* Every briefing delivers five blocks:

1. **📦 Dış kaynak yönetişimi** — pre-procurement due diligence and vendor
   screening, the written risk analysis and cost/benefit assessment, board /
   risk & audit committee approval, contract architecture (**right-to-audit**,
   subcontractor approval & notification, data ownership and return, SLA with
   penalty–bonus, liability and professional indemnity, exit plan), regulator
   notification and inspection-readiness — plus the classic commercial layer
   (RFP prep, pricing models FTE / per-minute / hybrid / outcome-based,
   transition risk, SLA & KPI design around AHT, FCR, NPS, occupancy,
   shrinkage, abandon rate).
2. **🔐 Bilgi güvenliği kontrolleri** — the contact-center-specific control set,
   grouped so it is usable: *access* (least privilege, role-based CRM/core
   banking rights, MFA, privileged access management, entitlement reviews),
   *recording & retention* (call and screen recording, encryption, retention and
   destruction, card data — the weaknesses of pause-and-resume recording versus
   **DTMF masking** for scope reduction, and the biometric dimension of voice),
   *endpoint* (thin client / VDI, USB and clipboard restrictions, PII/PAN
   masking on the agent screen, desktop DLP, no BYOD), *network & integration*
   (segmentation, secure API integration, data minimisation), *people*
   (background checks, NDAs, awareness training, insider threat), *physical*
   (delivery-center access control, clean desk / clear screen, no phones or
   cameras) and *monitoring* (log retention & SIEM, penetration-test cadence,
   vulnerability management) — each with "what evidence do you ask for".
3. **⚖️ Uyum** — KVKK duties (controller vs. processor and what belongs in the
   processor contract, aydınlatma & açık rıza, retention-and-destruction policy,
   VERBİS, breach notification and the notification SLA you demand from the
   vendor, cross-border transfer safeguards), ISO/IEC 27001 & 27002 expectations
   (does the certificate's **scope** actually cover the service?), SOC 2 Type 1
   vs Type 2, PCI-DSS scope, and audit trails / evidence retention.
4. **🚨 Riskler ve erken uyarı sinyalleri** — concentration risk, the fourth-party
   subcontractor chain, remote/home-working agent exposure, data-leakage vectors
   (screen photos, copy-paste, e-mail, USB, over-broad reporting rights), the
   quality-versus-security trade-off, hidden costs and vendor lock-in — each with
   its early-warning signal and the contract/operational counter-measure.
5. **🔬 Teknoloji ve yeni riskler** — speech/text analytics, agent assist, voice
   and chat bots, CCaaS, WFM, QM automation, and especially **generative AI in
   the contact center**: transcripts and recordings reaching a model, prompt-level
   data leakage, training on customer data, the vendor's AI tool inventory,
   output review, and EU AI Act awareness.

A **rotating daily focus** (`DAILY_FOCUS`, selected from the day number) decides
which of these the briefing goes deepest on, so consecutive days never read the
same. Each briefing ends with a ✅ *Bugünün görevi* that is a verifiable check —
e.g. *"does your vendor contract carry a right-to-audit clause? open it today"*.

*Accuracy first:* the persona is grounded in the **real framework and institution
names** — BDDK's *Bankaların Destek Hizmeti Almalarına İlişkin Yönetmelik* and
*Bankaların Bilgi Sistemleri ve Elektronik Bankacılık Hizmetleri Hakkında
Yönetmelik*, KVKK / Law 6698 and its secondary regulation, ISO/IEC 27001 &
27002, the PCI Security Standards Council's PCI-DSS, SOC 2, TSE's TS 13298 and
e-imza/KEP, plus GDPR / DORA / EU AI Act as directional awareness — because those
names are stable. It is simultaneously instructed to describe **principles,
structure and direction, never specific article numbers, dates, thresholds or
fines**, to flag whatever must be verified, and every briefing ends with a fixed
caveat telling you to confirm the regulatory detail with your bank's own
compliance/legal and information-security functions, pointing at official root
domains only (BDDK, KVKK, TCMB, ISO, PCI SSC) plus the shared
*"🔎 Bağlantıları açılışta doğrulayın."* note.

It is grounded in **two** RSS feeds, both fetched locally (outside the LLM call)
and merged with de-duplication: `BANKING_NEWS_RSS_URL` (banking / contact-center
/ outsourcing) and `BANKING_SECURITY_RSS_URL` (KVKK, data breaches, information
security). Both default to free Turkish Google News search feeds so the briefing
can cite REAL links; either feed being unreachable silently degrades towards the
LLM-only briefing with official root domains.

**Hesap Sorucu Koç** reads the other advisors' `✅ Bugünün görevi` items from the
**current run**, restates them as one checkable list, and asks yesterday's
uncomfortable question — *yaptın mı?* — alongside your streak, an implementation
intention prompt and a "shrink the task" fallback. It is registered **last** so
the supervisor can hand it the briefings produced before it (via the
`Advisor.observe()` hook), and it makes **no LLM call**, so it costs nothing
against the free-tier quota and cannot invent a task you were never given. If the
other sections failed or were skipped, it degrades to a generic restart nudge.

> 💾 **How the memory survives (durable streaks).** The coach stores a small JSON
> file (`ACCOUNTABILITY_STATE_FILE`, default
> `.assistant_state/accountability.json`) with each day's tasks and the streak
> counter. The **GitHub Actions runner filesystem is ephemeral**, so the *Daily
> Briefing* workflow makes it durable by **committing that file back to `main`**:
> the job runs with `permissions: contents: write`, and a final
> *"Persist accountability state"* step commits and pushes the file as
> `github-actions[bot]` whenever it changed. The next scheduled run checks it out
> and the streak continues. `.gitignore` carries an explicit exception for this
> one file (`.assistant_state/*` is ignored, `!.assistant_state/accountability.json`
> is not).
>
> The step is deliberately **non-fatal**: it runs `if: always()` with
> `continue-on-error: true`, retries with `git pull --rebase` to survive a race
> with another push, and exits `0` even when it cannot push. Losing a streak must
> never cost you the briefing. "No prior state" therefore remains a legitimate
> fresh start — day-1 streak, no crash — on a brand-new repo, after a failed
> push, or when you run locally.
>
> Keep the `ACCOUNTABILITY_STATE_FILE` secret **unset** in CI so the default
> (committed) path is used; pointing it elsewhere silently disables persistence.

**Gün Başı Operasyon Brifingi** uses the **existing** shared Google OAuth
(read-only Gmail/Calendar scopes — no new auth is invented). Until you complete
the one-time login it reports `skipped` with that exact instruction, which is the
expected state on a fresh checkout:

```bash
python -m ai_assistant.integrations.google_auth
```

> ☁️ **Running it in GitHub Actions.** A runner has no token file, which is why
> this section used to be permanently `skipped` in the cloud. Credentials can now
> also be supplied **entirely through environment variables**. The one-time login
> above is still required — it is what produces the refresh token — but it only
> ever has to be done **once, locally**.
>
> Precedence in `google_auth.get_credentials()`:
> **token file (if present) → `GOOGLE_REFRESH_TOKEN` → `skipped` with a clear reason.**
>
> After the login the CLI prints exactly which secrets to set. It prints the
> **names only** — never the values — so nothing sensitive lands in a terminal
> scrollback or a CI log:
>
> | GitHub secret          | Where to read the value from                                |
> | ---------------------- | ----------------------------------------------------------- |
> | `GOOGLE_CLIENT_ID`     | the `client_id` field in `.google_token.json` (or the Google Cloud console) |
> | `GOOGLE_CLIENT_SECRET` | the `client_secret` field in `.google_token.json` (or the console) |
> | `GOOGLE_REFRESH_TOKEN` | the `refresh_token` field in `.google_token.json`            |
>
> Add them under **Settings → Secrets and variables → Actions**; the workflow
> already passes all three through. `.google_token.json` stays git-ignored —
> never commit it or paste its contents anywhere. With the three secrets set, the
> ops briefing runs in the cloud exactly as it does locally; without them it
> still degrades to `skipped` rather than failing the run.

Once logged in it fetches a **bounded** slice of recent unread/important mail
(`OPS_BRIEFING_EMAIL_WINDOW`, default `1d`; `OPS_BRIEFING_MAX_EMAILS`, default 12)
plus today's calendar events, then produces: e-postalarda aksiyon gerektirenler /
bekleyen cevaplar, bugünkü toplantılar + her biri için kısa hazırlık notu,
çakışmalar ve derin çalışma için boş bloklar, and günün 3 kritik önceliği.
**Privacy:** only metadata (sender, subject, time) and Gmail's own short snippet
are read — never a full message body — and the snippet is truncated before it
reaches the model. Every network call is guarded; if the model is unavailable you
still get the gathered facts.

**İngilizce & Yönetici İletişimi Koçu** teaches 5 business-English patterns a day
with banking/contact-center usage examples, a "Bu cümleyi İngilizce kur" mini
exercise whose model answer is printed at the very bottom behind an explicit
*"önce kendin dene"* divider (the advisor keeps no state, so the answer travels
with the exercise), and a weekly executive-communication focus that rotates off
the ISO week number: veriyle hikâye anlatma → yönetim kuruluna sunum → ikna &
müzakere → toplantı yönetimi.

### Phase 4 advisors

Two more supervised agents, discovered the same way and degrading to `skipped`
without an LLM key.

| Advisor                                        | Persona                                                         | Needs                                     |
| ---------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------- |
| Yapay Zeka Ustalığı Koçu                       | AI enablement coach: teaches AI tools from zero to advanced      | An LLM key (`AI_MASTERY_LEVEL` / `AI_MASTERY_RSS_URL` have defaults) |
| Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı | Evidence-driven CX / contact-center researcher                   | An LLM key (`CX_RESEARCH_RSS_URL` has a default) |

**Yapay Zeka Ustalığı Koçu** works through a rotating syllabus (prompt
engineering, system prompts and context, chain-of-thought and structured output,
RAG, agents and tool use, automation with n8n/Zapier/Make, API usage, evaluating
outputs, avoiding hallucinations, data privacy, cost control, choosing the right
model) at the level set by `AI_MASTERY_LEVEL` (`temel` → `orta` → `ileri`).
Every section carries a **hap bilgi**, **eğitim videoları**, **ücretsiz
sertifikalı eğitimler** and a hands-on `✅ Bugünün görevi` to run in a real AI
tool. Course links come from its feed or from stable providers by ROOT domain
(Google Cloud Skills Boost, Microsoft Learn, DeepLearning.AI, Coursera, edX,
Hugging Face, Kaggle Learn, freeCodeCamp, Anthropic/OpenAI docs) — never an
invented deep URL.

**Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı** teaches with evidence: new
trends, new technologies, academic and industry research, success stories with
concrete before/after metrics, measurement methodology (NPS/CSAT/CES, journey
mapping, churn prediction, VoC, FCR, effort reduction), retention programmes and
the employee-experience ↔ customer-experience link. Its hard rule is that a
figure may only appear when it can be ATTRIBUTED — the source organisation is
named next to it, unverifiable numbers are simply not given, and a standing
caveat tells the user to confirm anything at the source.

### Phase 1C advisors (the current roster's two newest)

The consolidation that produced today's thirteen advisors also **retired** two
(*Hava Durumu* — a phone already gives you the forecast — and *Anka Köprüsü*,
whose bridge is no longer fed; both modules stay on disk so a rollback is a
comment change) and **added** two:

| Advisor                         | Persona                                                        | Needs                                                       |
| ------------------------------- | -------------------------------------------------------------- | ----------------------------------------------------------- |
| Toplantı Hazırlık & Takip       | Executive assistant writing the note you read before walking in | Google OAuth (Calendar + Drive); notes folder optional        |
| Müşteri Şikayet & İtibar Radarı | Complaint-management / VoC consultant reading the sector's complaint agenda | Nothing — both feeds have defaults; an LLM key interprets them |

**Toplantı Hazırlık & Takip** reads the upcoming meetings from Google Calendar
(the **same** shared OAuth as the ops briefing — no second auth path), drops what
nobody prepares for (all-day entries, attendee-less focus blocks), and matches
each meeting to past notes in Drive by TITLE tokens and ATTENDEE names, with
Turkish letters folded so *Şikayet* and *sikayet* are the same word. The notes
folder is `MEETING_PREP_NOTES_FOLDER_ID`, falling back to
`GOOGLE_DRIVE_FOLDER_ID`; `MEETING_PREP_LOOKAHEAD_DAYS` (default 3) and
`MEETING_PREP_MAX_NOTES` (default 3) bound the work. Reading a note *body*
needs the `drive.readonly` scope; with an older refresh token (see
[Re-consent after a scope change](#re-consent-after-a-scope-change)) the shared
credential still only sees file *metadata*, so an unreadable note body is
normal: the section is then written at title level and the model is told to say
so. Its output separates
**your** open items from **the team's**, proposes an agenda with the carried-over
items first, and ends with one 15-30 minute preparation task. It is `private`:
calendar entries and note content never reach the public dashboard. Missing
Google credentials, an auth failure, an unreachable calendar or an empty diary
each degrade to `skipped` with a Turkish explanation.

**Müşteri Şikayet & İtibar Radarı** merges two complaint/reputation feeds
(`COMPLAINT_RADAR_RSS_URL`, `COMPLAINT_RADAR_SECTOR_RSS_URL`, both defaulting to
Turkish Google News searches for banking complaints) into ONE pool, de-duplicates
by headline, and passes what is left through the findings ledger — so the day's
second run never re-tells the morning's complaint. Headlines are grouped under
the **fixed** themes in `COMPLAINT_THEMES` (waiting time, unresolved cases,
repeat contacts, fees, digital channels, tone, product decisions, data &
security), so the same complaint carries the same label from day to day. Its job
is interpretation, not a list: what mechanism broke, which reply closes a
complaint and which enlarges it, what it presses on FCR / repeat contact / CES /
NPS. Optionally `COMPLAINT_RADAR_BRANDS` and `COMPLAINT_RADAR_COMPETITORS`
(comma-separated) name the institutions to watch; those have **no** default,
because inventing a brand name would put a fabricated institution in the
briefing, and without them the model is told to compare only the institutions the
feed actually names. Without an LLM key the section still delivers today's REAL
headlines, grouped by source.

### Deduplication + incremental runs

Running four times a day is only useful if the later runs do not repeat the
morning. `ai_assistant.memory` keeps a small ledger of everything already
**delivered**, per advisor:

- feed items are fingerprinted by normalised URL (lowercased host, no tracking
  parameters, no fragment) *and* normalised title, so the same story behind two
  links is recognised once;
- LLM prose is fingerprinted by a content hash plus the links it cited;
- only irreversible hashes are stored — never the briefing text — so the file is
  safe in a public repository;
- entries expire after `FINDINGS_MEMORY_DAYS` (default 30), letting a genuinely
  recurring topic resurface later;
- fingerprints are written **only after Slack accepted the digest**, so a
  finding that never reached the user stays new;
- a corrupt, unreadable or unwritable ledger degrades to "everything is new" and
  logs — it can never break a run.

With `BRIEFING_MODE=incremental` the advisors with nothing new collapse to a
one-line "yeni bulgu yok", they are kept out of the batched prompt (so a quiet
run costs **no** model tokens), and when nobody has anything new the notifier
skips Slack entirely while still writing `status.json`
(`SKIP_SLACK_WHEN_NOTHING_NEW`, default `true`). The `full` daily briefing always
sends.

### Defaults: the whole team is active out of the box

`config.DEFAULT_SETTINGS` pre-fills the **non-secret** configuration so every
agent produces content without any setup. A non-empty environment variable or
GitHub secret always wins; an unset secret (which Actions expands to an empty
string) falls back to the default.

| Setting               | Default                                                        |
| --------------------- | -------------------------------------------------------------- |
| `USER_SECTOR`         | `banka çağrı merkezleri`                                        |
| `JOB_KEYWORDS`        | `çağrı merkezi müdürü, müşteri deneyimi yöneticisi, operasyon müdürü` |
| `JOB_LOCATION`        | `İstanbul`                                                      |
| `AI_NEWS_RSS_URL`     | Google News RSS search for *yapay zeka* (Turkish)               |
| `SECTOR_NEWS_RSS_URL` | Google News RSS search for *çağrı merkezi banka* (Turkish)      |
| `BANKING_NEWS_RSS_URL` | Google News RSS search for banking / contact-center / outsourcing news (Turkish) |
| `BANKING_SECURITY_RSS_URL` | Google News RSS search for KVKK / bilgi güvenliği / veri ihlali in banking (Turkish) |
| `COMPLAINT_RADAR_RSS_URL` | Google News RSS search for *banka şikayet* / *bankacılık müşteri şikayeti* (Turkish) |
| `COMPLAINT_RADAR_SECTOR_RSS_URL` | Google News RSS search for sector complaints — *bankacılık şikayet*, *tüketici hakem heyeti*, BDDK (Turkish) |
| `ACCOUNTABILITY_STATE_FILE` | `.assistant_state/accountability.json` (committed back to `main` by the workflow) |

Two deliberate exceptions: **no API key is ever defaulted** (without
`GEMINI_API_KEY`/`OPENAI_API_KEY` the LLM advisors still report `skipped` and the
run exits `0`), and **nothing user-specific is invented** — the complaint radar's
`COMPLAINT_RADAR_BRANDS` / `COMPLAINT_RADAR_COMPETITORS` name real institutions
and the meeting-prep notes folder is your own Drive folder, so those stay unset
until you provide them (and the advisors simply do less, never crash).

### One batched LLM call per run

The free Gemini tier only allows a couple of `generateContent` calls per quota
window, so asking each persona separately (nine calls) meant most sections came
back `429`/`503` no matter how patiently the client retried — retrying cannot
beat a quota ceiling. By default (`DIGEST_BATCH_MODE=true`) every LLM-backed
advisor contributes a `BatchSection` (its persona + today's brief), they are sent
as **one** request with an explicit output contract, and the response is split
back apart on `### SECTION: <advisor_key>` markers — so per-advisor
`ok`/`failed`/`skipped` statuses are unchanged.

All three LLM-backed Phase 3 advisors join that single call too: the banking
expert and the ops briefing gather their real data first (RSS feed / Gmail +
Calendar) and then contribute those facts inside their batched section, exactly
like the existing RSS advisors. The accountability coach uses no LLM at all, so
the run stays at ~1 Gemini request.

Non-LLM work stays outside the batch: the news advisors and the complaint radar
still fetch their RSS feeds themselves, meeting prep still reads Calendar and
Drive itself, and the SRE watchdog reads files only; only the *summarization* is
batched. If the batched call fails, or the model omits a
section, those advisors transparently fall back to their own per-advisor call.
Set `DIGEST_BATCH_MODE=false` to disable batching entirely.

### Gemini resilience

Transient failures are retried with backoff — `429` (rate limit) **and**
`500/502/503/504` (the "model is overloaded" / "service unavailable" family) —
honouring `Retry-After` when present. If a model keeps failing, the client walks
a **fallback chain** (`GEMINI_MODEL` → `gemini-flash-latest` → `gemini-2.0-flash`,
overridable via `GEMINI_FALLBACK_MODELS`) and logs which model actually served
the answer. Every request carries a timeout (`GEMINI_TIMEOUT_SECONDS`, default
120s) so a hung call can't stall the job, and every surfaced error is passed
through key redaction — **the API key can never appear in a log, an error or a
Slack message**.

### Operations Manager (the supervising agent)

`ai_assistant.operations_manager.OperationsManager` is the single orchestration
entry point. It auto-discovers every advisor, runs each one, isolates per-advisor
failures so one broken advisor never breaks the others, and returns a
supervision summary (who ran, each status, failure reasons, counts like
`3 ok, 0 failed, 1 skipped`).

```bash
python -m ai_assistant.operations_manager
```

Exits `0` even when advisors are skipped; non-zero only if a *configured*
advisor actually failed (mirroring `health.py`).

### Daily digest

`ai_assistant.daily_digest.build_digest()` runs the Operations Manager and
assembles one dated Turkish report — a header, one section per advisor, and a
short supervision line (`Operasyon Yöneticisi: 3 ok, 1 skipped`).

```bash
python -m ai_assistant.daily_digest
```

### Report documents (one reading page per advisor)

Thirteen advisors writing 300-500 words each used to arrive as ONE Slack message.
That is unreadable on a phone, so the run is now split apart.
`ai_assistant.reports` writes every successful section as its own document:

```
frontend/reports/index.json                       # archive, newest day first
frontend/reports/2026-07-31/index.json            # that day's cards
frontend/reports/2026-07-31/leadership_coach.json # one advisor's full report
```

The dashboard renders those as typeset, mobile-first reading pages behind a
hash router (`#/rapor/2026-07-31/leadership_coach`). An `incremental` run merges
into the day rather than replacing it, and days older than
`REPORTS_RETENTION_DAYS` (default 30) are pruned so the repository cannot grow
without bound.

**Privacy.** The dashboard is PUBLIC. An advisor whose section can contain
personal data sets `private = True` (today: `communications_calendar`,
`meeting_prep`, `data_analyst`, `ai_innovation`, `executive_coaching`,
`work_analyst`, `operations_director` and `sre_watchdog`). Its content is never written to
`frontend/reports/` — it is delivered inline in Slack instead. The rule is
enforced twice, by the flag and by a hard-coded key list, and it has its own
test.

### Slack notifier (a compact index, not the briefing)

`ai_assistant.notifiers.slack_notifier` publishes the report documents and then
posts a short **Block Kit** index to Slack: a date header, one context line with
the run summary, and ONE line per advisor — emoji, name, the advisor's own
`**Öne çıkan:**` headline and a `📄 Tam rapor` link to its document. Private
sections travel inline, because they have no public link to point at. Delivery
is via an Incoming Webhook (`SLACK_WEBHOOK_URL`) or a bot token
(`SLACK_BOT_TOKEN` + `SLACK_CHANNEL`, `chat.postMessage`); with neither set it
reports `skipped` and exits `0`.

`DASHBOARD_BASE_URL` says where those links point (default:
<https://beltass.github.io/AI-Executive-Assistant/>).

```bash
python -m ai_assistant.notifiers.slack_notifier
```

### Scheduled daily delivery

`.github/workflows/daily-briefing.yml` runs **four times a day** (GitHub Actions
cron is always UTC) and on manual `workflow_dispatch` (which takes a `mode`
input, `full` or `incremental`, defaulting to `full`):

| Cron (UTC)       | İstanbul | Mode          | What it does                          |
| ---------------- | -------- | ------------- | ------------------------------------- |
| `0 7 * * *`      | 10:00    | `full`        | The complete daily briefing            |
| `0 11,15,19 * * *` | 14:00 / 18:00 / 22:00 | `incremental` | Only findings that are NEW since the last run |

A step derives the mode from `github.event.schedule`, the job declares a
`concurrency` group so runs queue instead of racing each other's commits, and it
installs the package, runs the Slack notifier, and then commits the
accountability state, the findings ledger and `frontend/status.json` back to
`main` — which is why the job declares `permissions: contents: write`.

To turn on **live daily delivery**, add these GitHub repository **Secrets**
(Settings → Secrets and variables → Actions):

- `GEMINI_API_KEY` **or** `OPENAI_API_KEY` — activates the LLM personas.
- `SLACK_WEBHOOK_URL` **or** (`SLACK_BOT_TOKEN` + `SLACK_CHANNEL`) — activates Slack delivery.

Everything else is **optional** and now has a sensible default (see
[Defaults](#defaults-the-whole-team-is-active-out-of-the-box)); set a secret only
when you want to override one:

- `JOB_KEYWORDS` / `JOB_LOCATION` — override the default job-scout search.
- `USER_SECTOR` — tailors the sector intel & free-cert advisors (default
  "banka çağrı merkezleri").
- `SECTOR_NEWS_RSS_URL` / `AI_NEWS_RSS_URL` / `BANKING_NEWS_RSS_URL` /
  `BANKING_SECURITY_RSS_URL` / `COMPLAINT_RADAR_RSS_URL` /
  `COMPLAINT_RADAR_SECTOR_RSS_URL` — override the default Google News feeds.
- `COMPLAINT_RADAR_BRANDS` / `COMPLAINT_RADAR_COMPETITORS` — comma-separated
  institutions the complaint radar watches and compares. **No default** (a made-up
  brand must never reach the briefing); unset simply drops that part of the prompt.
- `ACCOUNTABILITY_STATE_FILE` — where the accountability coach writes its streak
  state. **Leave this unset in CI**: the workflow only commits the default path
  back to the repo, so overriding it disables the durable streak.
- `OPS_BRIEFING_MAX_EMAILS` / `OPS_BRIEFING_EMAIL_WINDOW` — how much recent mail
  the ops briefing looks at (defaults: 12 messages, `1d`).
- `GOOGLE_DRIVE_FOLDER_ID` — the Drive root used for report archiving, and the
  fallback folder meeting prep looks for past meeting notes in.
- `MEETING_PREP_NOTES_FOLDER_ID` / `MEETING_PREP_LOOKAHEAD_DAYS` /
  `MEETING_PREP_MAX_NOTES` — the notes folder and the bounds of the meeting-prep
  search (defaults: `GOOGLE_DRIVE_FOLDER_ID`, 3 days, 3 notes).
- `SLACK_CHANNEL_<ADVISOR_KEY>` — one optional sub-channel per advisor, e.g.
  `SLACK_CHANNEL_MEETING_PREP` or `SLACK_CHANNEL_COMPLAINT_RADAR`; an unset one
  falls back to `SLACK_MAIN_CHANNEL`. Create them all with
  `python -m ai_assistant.integrations.slack_setup --apply`.

To activate the **Gün Başı Operasyon Brifingi** in the cloud, do the one-time
local Google login once and add the three secrets it names:

```bash
python -m ai_assistant.integrations.google_auth
```

- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` — read the
  values out of your local `.google_token.json` (`client_id`, `client_secret`,
  `refresh_token`). The CLI prints the **names** and where to find them, never
  the values themselves.

Until those exist the section reports `skipped` on every scheduled run, which is
expected and never fails the job.

Any secret you omit falls back to its default (or leaves that advisor/notifier
`skipped` when there is none); the workflow still succeeds.

## Project layout

```
.
├── pyproject.toml                 # deps + packaging + pytest config
├── .env.example                   # every expected env var, documented
├── .github/workflows/ci.yml       # GitHub Actions: install + pytest
├── .github/workflows/daily-briefing.yml  # scheduled Slack daily digest
├── .github/workflows/pages.yml    # publishes the dashboard to GitHub Pages
├── frontend/                      # dashboard + report reading pages (static)
│   ├── index.html                 # Turkish UI, no framework, no build step
│   ├── styles.css                 # dark-first, mobile-first, reading type
│   ├── markdown.js                # small, SAFE markdown → HTML renderer
│   ├── app.js                     # data + hash router, refreshes every 60 s
│   ├── status.json                # run status, written by every briefing run
│   └── reports/                   # per-advisor documents, last 30 days
├── src/ai_assistant/
│   ├── __init__.py
│   ├── config.py                  # loads .env, defines integration specs
│   ├── health.py                  # run_all_checks() + CLI entrypoint
│   ├── operations_manager.py      # supervising agent over the advisors
│   ├── daily_digest.py            # build_digest() + CLI entrypoint
│   ├── status_report.py           # writes frontend/status.json for the dashboard
│   ├── reports.py                 # writes frontend/reports/ (public sections only)
│   ├── advisors/
│   │   ├── __init__.py            # Advisor/Briefing base + discovery
│   │   ├── _llm_base.py           # shared LLM persona base + rich guide
│   │   ├── _batch.py              # one batched LLM call for the whole team
│   │   ├── _rss.py                # shared RSS/Atom fetch + parse helper
│   │   ├── meeting_prep.py        # Calendar + Drive meeting prep note (private)
│   │   ├── complaint_radar.py     # sector complaint & reputation radar
│   │   ├── weather.py             # RETIRED (kept on disk for rollback)
│   │   ├── leadership_coach.py
│   │   ├── kids_development.py
│   │   ├── career_hr.py
│   │   ├── job_scout.py           # prepares applications + search links
│   │   ├── sector_intel.py        # sector & competitor intelligence
│   │   ├── ai_news.py             # AI news (feed or LLM roundup)
│   │   ├── free_certs.py          # free certifications & training
│   │   ├── banking_cc_projects.py # bank contact-center outsourcing expert
│   │   ├── ai_mastery.py          # AI enablement coach (temel→ileri)
│   │   ├── cx_research.py         # CX / contact-center researcher
│   │   ├── accountability_coach.py# consolidates + chases the daily tasks
│   │   ├── daily_ops_briefing.py  # Gmail + Calendar morning briefing
│   │   ├── language_coach.py      # business English & executive presence
│   │   └── anka_bridge.py         # RETIRED (kept on disk for rollback)
│   ├── memory.py                  # findings ledger (dedup across runs)
│   ├── notifiers/
│   │   ├── __init__.py
│   │   └── slack_notifier.py      # compact Block Kit index → Slack
│   └── integrations/
│       ├── __init__.py            # CheckResult + status constants
│       ├── _common.py             # shared HTTP helpers
│       ├── google_auth.py         # shared Google OAuth 2.0 flow + CLI
│       ├── gmail.py
│       ├── google_calendar.py
│       ├── google_drive.py
│       ├── slack.py
│       ├── todoist.py
│       ├── notion.py
│       └── llm.py                 # check + generate_text() for advisors
└── tests/
    ├── test_health.py
    ├── test_google_auth.py
    ├── test_advisors.py
    ├── test_new_advisors.py
    ├── test_meeting_prep.py        # calendar/Drive stubs, every skip path
    ├── test_complaint_radar.py     # feed merge, dedup, non-LLM fallback
    ├── test_batch.py
    ├── test_operations_manager.py
    ├── test_status_report.py
    ├── test_reports.py             # report documents + PRIVACY assertions
    ├── test_frontend_markdown.py   # the dashboard renderer, under node
    └── test_slack_notifier.py
```

`scripts/seed_dashboard.py` writes a sample set of report documents offline (no
network, no model) so a freshly published dashboard has something true to
render.

## Live dashboard

Every briefing run ends by writing `frontend/status.json` — per-advisor
statuses, run counts, Slack delivery, the accountability streak and a rolling
window of the last 30 runs — which the `Daily Briefing` workflow commits back to
`main`. The static site in `frontend/` renders it: a Turkish, mobile-friendly
monitor that answers "did the team run this morning, and what broke?" without
opening GitHub Actions.

It contains **no briefing content** — only statuses, reasons and character
counts — because the repository is public. Reasons are sanitised for API keys
on top of the redaction the LLM layer already does.

Alongside it, `frontend/reports/` carries the readable per-advisor documents
(see above) — that is the part with actual briefing text in it, minus every
`private` advisor.

Two hosts, no build step in either:

- **Vercel** — the connected project's root directory is `frontend`, so the
  files are served as-is on every push.
- **GitHub Pages** — `.github/workflows/pages.yml` publishes the same directory
  and asks GitHub to enable Pages on its first run. If that is not permitted,
  do it by hand once: **Settings → Pages → Source: GitHub Actions**. Either way
  the dashboard then lives at <https://beltass.github.io/AI-Executive-Assistant/>.

#### Why the live dashboard used to go stale

The briefing commits its data back to `main`, and that commit reached the
repository and stopped there: the published site kept serving an older build,
so the dashboard showed an old run while the file in git was already fresh. Two
independent causes, both real:

1. the commit message carried `[skip ci]`, which skips **every** workflow for
   that push — including the Pages deploy. It is gone.
2. more fundamentally, a push made with the default `GITHUB_TOKEN` never
   triggers another workflow run. No commit message can change that.

So `pages.yml` now also listens for the `Daily Briefing` **workflow** finishing
(`workflow_run`), which is not subject to that rule and fires after the new
files are already on `main`. No loop is possible: `pages.yml` only reads and
publishes, and `daily-briefing.yml` is triggered solely by `schedule` and
`workflow_dispatch`.

The page defends itself too: `status.json` is fetched with a cache-buster, the
run timestamp is shown at the top, and data older than ~12 hours raises a
"veri eski görünüyor" banner instead of quietly looking current.

See [`frontend/README.md`](frontend/README.md) for details and local preview.

## Setup

Requires Python 3.9+.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install the package (plus dev tools for tests)
pip install -e ".[dev]"

# 3. Configure credentials
cp .env.example .env
# then edit .env and fill in the tokens you have
```

## Google OAuth login

Gmail, Google Calendar and Google Drive authenticate through a single shared
Google OAuth 2.0 flow (read-only scopes: `gmail.readonly`, `calendar.readonly`,
`drive.metadata.readonly` and `drive.readonly`). You log in **once**:

1. In the [Google Cloud console](https://console.cloud.google.com/), create an
   OAuth client of type **Desktop app** and enable the Gmail, Calendar and
   Drive APIs. Either copy the client id/secret into `.env`
   (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) or download the
   `client_secret*.json` and point `GOOGLE_CREDENTIALS_FILE` at it.
2. Run the one-time login flow:

   ```bash
   python -m ai_assistant.integrations.google_auth
   ```

   A browser opens for consent; on success a token (including the refresh
   token) is written to `GOOGLE_TOKEN_FILE` (default `.google_token.json`,
   which is git-ignored). From then on the connection checks refresh the
   access token automatically — no further interaction required. The command
   then prints which GitHub Secrets to set if you also want this to work in the
   cloud (names only — the values stay in the token file).

3. *(Optional, for CI)* Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and
   `GOOGLE_REFRESH_TOKEN` as environment variables / repository secrets. That
   is a complete, **file-free** credential: `get_credentials()` prefers a token
   file when one exists and otherwise exchanges the refresh token directly.

If no Google client credentials, no `GOOGLE_REFRESH_TOKEN` and no token file are
present, the three Google checks simply report **SKIPPED**.

### Re-consent after a scope change

**A refresh token keeps the scopes it was issued with.** `drive.readonly` was
added to the list above so that meeting-note *content* can be read
(`files.export` / `files.get_media`); `drive.metadata.readonly` on its own only
permits *listing*. A token minted before that change therefore keeps failing
every content read with a 403 — nothing you can retry your way out of. To pick
the new scope up:

1. delete `GOOGLE_TOKEN_FILE` (default `.google_token.json`),
2. run `python -m ai_assistant.integrations.google_auth` again and consent,
3. copy the **new** refresh token into `GOOGLE_REFRESH_TOKEN` (and into the
   GitHub secret of the same name).

Until then nothing breaks: listing keeps working, the meeting-prep section falls
back to title level, and the Slack summary answers with a Turkish message that
names this exact problem instead of an empty answer.

## Run the connection check

```bash
python -m ai_assistant.health
# or, equivalently:
python scripts/check_connections.py
```

You'll get a table of every integration with a status of **OK**, **FAILED**, or
**SKIPPED**, followed by a summary line. The process exits:

- **0** — no configured integration failed (skipped ones are fine)
- **1** — at least one configured integration failed its health check

With an empty `.env`, every integration reports `SKIPPED` and the command
exits `0`.

## Run the tests

```bash
pytest
```

The test suite runs without any credentials and verifies that missing-credential
integrations report `skipped` and that the aggregation never crashes.
