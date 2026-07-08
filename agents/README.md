# agents/

Ajan görev tanımları için bkz. `../docs/AGENTS.md`. Faz 1 kapsamı için
bkz. `../docs/ROADMAP.md`.

**Uygulama notu (Faz 1):** Tek bir Next.js projesi olduğu için (bkz.
`../docs/ARCHITECTURE.md` §1 — "Frontend + API routes tek projede"),
ajanların gerçek kodu şu an burada değil,
`../frontend/src/lib/agents/` altında yaşıyor (`orchestrator.ts`,
`email-agent.ts`). Bu klasör, birden fazla tüketici (ör. Faz 2'deki
bir arka plan worker'ı) aynı ajan koduna ihtiyaç duyduğunda ayrı bir
pakete çıkarılacağı yer olarak duruyor — o zamana kadar gereksiz bir
soyutlama eklememek için kod tek projede tutuluyor.
