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
        receivedAt: new Date(Date.now() - 2 * 3600_000).toISOString(),
      },
      {
        id: "mock-2",
        from: "no-reply@linkedin.com",
        subject: "5 yeni bağlantı isteğiniz var",
        snippet: "LinkedIn ağınızdaki gelişmeleri kaçırmayın.",
        receivedAt: new Date(Date.now() - 5 * 3600_000).toISOString(),
      },
      {
        id: "mock-3",
        from: "finance@saas-tool.com",
        subject: "Faturanız hazır — Temmuz 2026",
        snippet: "Aylık aboneliğinize ait fatura ekte. Ödeme tarihi 15 Temmuz.",
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
          format: "metadata",
          metadataHeaders: ["From", "Subject", "Date"],
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
