/**
 * EmailProvider soyutlaması — bkz. docs/ARCHITECTURE.md §8 ("sağlayıcıdan
 * bağımsız arayüzler"). Faz 1'de tek implementasyon Gmail'dir; Faz 2'de
 * Outlook eklendiğinde Email Agent kod değişikliği gerektirmeyecek.
 */

export interface EmailSummary {
  id: string;
  from: string;
  subject: string;
  snippet: string;
  body: string;
  receivedAt: string;
}

export interface EmailProvider {
  listRecentEmails(limit: number): Promise<EmailSummary[]>;
}

/**
 * Gerçek kimlik bilgisi (GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN) yoksa
 * bu sağlayıcı kullanılır — dikey dilimi uçtan uca demo etmek için.
 */
export class MockEmailProvider implements EmailProvider {
  async listRecentEmails(limit: number): Promise<EmailSummary[]> {
    const demo: EmailSummary[] = [
      {
        id: "mock-1",
        from: "ayse@musteri-firma.com",
        subject: "Sözleşme yenileme görüşmesi — bu hafta uygun musunuz?",
        snippet:
          "Merhaba, mevcut sözleşmemizin yenilenmesi için bu hafta 30 dakikalık bir görüşme ayarlayabilir miyiz?",
        body:
          "Merhaba,\n\nMevcut sözleşmemizin yenilenmesi için bu hafta 30 dakikalık " +
          "bir görüşme ayarlayabilir miyiz? Perşembe veya Cuma öğleden sonra " +
          "uygunum. Ayrıca yeni dönem için %10 hacim artışı talebimiz olacak, " +
          "bunu da görüşmede konuşmak isterim.\n\nİyi çalışmalar,\nAyşe",
        receivedAt: new Date(Date.now() - 2 * 3600_000).toISOString(),
      },
      {
        id: "mock-2",
        from: "no-reply@linkedin.com",
        subject: "5 yeni bağlantı isteğiniz var",
        snippet: "LinkedIn ağınızdaki gelişmeleri kaçırmayın.",
        body: "LinkedIn ağınızdaki gelişmeleri kaçırmayın. 5 yeni bağlantı isteğiniz var.",
        receivedAt: new Date(Date.now() - 5 * 3600_000).toISOString(),
      },
      {
        id: "mock-3",
        from: "finance@saas-tool.com",
        subject: "Faturanız hazır — Temmuz 2026",
        snippet: "Aylık aboneliğinize ait fatura ekte. Ödeme tarihi 15 Temmuz.",
        body:
          "Aylık aboneliğinize ait fatura ekte. Tutar: 49 USD. Ödeme tarihi: " +
          "15 Temmuz 2026. Otomatik ödeme kayıtlı kartınızdan tahsil edilecektir.",
        receivedAt: new Date(Date.now() - 20 * 3600_000).toISOString(),
      },
    ];
    return demo.slice(0, limit);
  }
}

/**
 * Gmail API üzerinden gerçek gelen kutusu erişimi. googleapis + OAuth2
 * (offline erişim, önceden alınmış refresh token) kullanır.
 */
/** Gmail body'leri gördüğü en detaylı `text/plain` parçası kadar uzun olabilir;
 * özet üretecek LLM çağrısının maliyetini kontrol altında tutmak için kırpılır. */
const MAX_BODY_CHARS = 2000;

function decodeGmailBase64Url(data: string): string {
  const normalized = data.replace(/-/g, "+").replace(/_/g, "/");
  return Buffer.from(normalized, "base64").toString("utf-8");
}

function stripHtml(html: string): string {
  return html
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** İç içe MIME parçalarında önce text/plain, bulunamazsa text/html arar. */
function extractBody(payload: unknown): string {
  type GmailPart = {
    mimeType?: string | null;
    body?: { data?: string | null } | null;
    parts?: GmailPart[] | null;
  };
  const root = payload as GmailPart | undefined;
  if (!root) return "";

  let plainFallback = "";
  let htmlFallback = "";

  function walk(part: GmailPart) {
    const data = part.body?.data;
    if (data && part.mimeType === "text/plain" && !plainFallback) {
      plainFallback = decodeGmailBase64Url(data);
    } else if (data && part.mimeType === "text/html" && !htmlFallback) {
      htmlFallback = decodeGmailBase64Url(data);
    }
    for (const child of part.parts ?? []) walk(child);
  }
  walk(root);

  const text = plainFallback || stripHtml(htmlFallback);
  return text.slice(0, MAX_BODY_CHARS);
}

export class GmailProvider implements EmailProvider {
  async listRecentEmails(limit: number): Promise<EmailSummary[]> {
    const { google } = await import("googleapis");

    const oauth2Client = new google.auth.OAuth2(
      process.env.GOOGLE_CLIENT_ID,
      process.env.GOOGLE_CLIENT_SECRET,
      process.env.GOOGLE_REDIRECT_URI
    );
    oauth2Client.setCredentials({
      refresh_token: process.env.GOOGLE_REFRESH_TOKEN,
    });

    const gmail = google.gmail({ version: "v1", auth: oauth2Client });
    const list = await gmail.users.messages.list({
      userId: "me",
      maxResults: limit,
    });

    const messages = list.data.messages ?? [];
    const details = await Promise.all(
      messages.map((m) =>
        gmail.users.messages.get({
          userId: "me",
          id: m.id!,
          format: "full",
        })
      )
    );

    return details.map((res) => {
      const headers = res.data.payload?.headers ?? [];
      const header = (name: string) =>
        headers.find((h) => h.name === name)?.value ?? "";
      return {
        id: res.data.id ?? "",
        from: header("From"),
        subject: header("Subject"),
        snippet: res.data.snippet ?? "",
        body: extractBody(res.data.payload),
        receivedAt: header("Date"),
      };
    });
  }
}

function hasGmailCredentials(): boolean {
  return Boolean(
    process.env.GOOGLE_CLIENT_ID &&
      process.env.GOOGLE_CLIENT_SECRET &&
      process.env.GOOGLE_REFRESH_TOKEN
  );
}

export function getEmailProvider(): EmailProvider {
  return hasGmailCredentials() ? new GmailProvider() : new MockEmailProvider();
}
