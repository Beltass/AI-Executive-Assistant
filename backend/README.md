# backend/

**Uygulama notu (Faz 1):** Ayrı bir backend süreci yok — "backend",
`../frontend/src/app/api/` altındaki Next.js API route handler'larıdır
(ör. `POST /api/chat`, Master Orchestrator'ı çağırır). Bu, tasarım
gereği: `../docs/ARCHITECTURE.md` §1 "Frontend + API routes tek
projede" kararının doğal sonucu — ayrı bir sunucu süreci kurmak bu
aşamada gereksiz karmaşıklık olurdu.

Bu klasör, Faz 2'de gerçek bir arka plan worker'ı (ör. e-posta/takvim
polling, `../docs/AUTOMATION.md`) gerektiğinde o sürecin kodu için
kullanılacak.
