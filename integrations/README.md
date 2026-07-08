# integrations/

Servis bazlı connector'lar için bkz. `../docs/INTEGRATIONS.md` (Faz 2).

**Uygulama notu (Faz 1):** Gmail connector'ının gerçek kodu şu an
burada değil, `../frontend/src/lib/integrations/gmail.ts` altında
yaşıyor — `EmailProvider` arayüzü + `GmailProvider` (gerçek API) +
`MockEmailProvider` (kimlik bilgisi yokken demo/geliştirme için).
Bu klasör, connector sayısı arttıkça (Outlook, Teams, Slack, Notion —
Faz 2/3) ayrı pakete çıkarılacağı yer olarak duruyor.
