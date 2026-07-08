/**
 * CalendarProvider soyutlaması — bkz. docs/ARCHITECTURE.md §8
 * ("sağlayıcıdan bağımsız arayüzler"), gmail.ts'teki EmailProvider ile
 * aynı desen. Faz 1'de tek implementasyon Google Calendar'dır.
 */

export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  location?: string;
  attendees?: string[];
}

export interface CalendarProvider {
  listUpcomingEvents(hoursAhead: number): Promise<CalendarEvent[]>;
}

/**
 * Gerçek kimlik bilgisi yoksa kullanılır — çakışma tespiti dahil dikey
 * dilimi demo etmek için bilerek iki çakışan etkinlik içerir.
 */
export class MockCalendarProvider implements CalendarProvider {
  async listUpcomingEvents(): Promise<CalendarEvent[]> {
    const now = Date.now();
    const at = (hoursFromNow: number) =>
      new Date(now + hoursFromNow * 3600_000).toISOString();

    return [
      {
        id: "mock-cal-1",
        title: "Haftalık ekip senkronizasyonu",
        start: at(2),
        end: at(2.5),
        location: "Google Meet",
        attendees: ["ekip@sirket.com"],
      },
      {
        id: "mock-cal-2",
        title: "Müşteri görüşmesi — sözleşme yenileme",
        start: at(2.25),
        end: at(3),
        location: "Google Meet",
        attendees: ["ayse@musteri-firma.com"],
      },
      {
        id: "mock-cal-3",
        title: "1:1 — yönetici görüşmesi",
        start: at(6),
        end: at(6.5),
      },
    ];
  }
}

/**
 * Google Calendar API üzerinden gerçek takvim erişimi. Gmail ile aynı
 * OAuth2 kimlik bilgilerini (GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN)
 * kullanır — yalnızca refresh token alınırken izin ekranında Calendar
 * kapsamının (calendar.readonly) da onaylanmış olması gerekir.
 */
export class GoogleCalendarProvider implements CalendarProvider {
  async listUpcomingEvents(hoursAhead: number): Promise<CalendarEvent[]> {
    const { google } = await import("googleapis");

    const oauth2Client = new google.auth.OAuth2(
      process.env.GOOGLE_CLIENT_ID,
      process.env.GOOGLE_CLIENT_SECRET,
      process.env.GOOGLE_REDIRECT_URI
    );
    oauth2Client.setCredentials({
      refresh_token: process.env.GOOGLE_REFRESH_TOKEN,
    });

    const calendar = google.calendar({ version: "v3", auth: oauth2Client });
    const now = new Date();
    const timeMax = new Date(now.getTime() + hoursAhead * 3600_000);

    const res = await calendar.events.list({
      calendarId: "primary",
      timeMin: now.toISOString(),
      timeMax: timeMax.toISOString(),
      singleEvents: true,
      orderBy: "startTime",
    });

    return (res.data.items ?? []).map((e) => ({
      id: e.id ?? "",
      title: e.summary ?? "(başlıksız)",
      start: e.start?.dateTime ?? e.start?.date ?? "",
      end: e.end?.dateTime ?? e.end?.date ?? "",
      location: e.location ?? undefined,
      attendees: e.attendees?.map((a) => a.email ?? "").filter(Boolean),
    }));
  }
}

function hasGoogleCredentials(): boolean {
  return Boolean(
    process.env.GOOGLE_CLIENT_ID &&
      process.env.GOOGLE_CLIENT_SECRET &&
      process.env.GOOGLE_REFRESH_TOKEN
  );
}

export function getCalendarProvider(): CalendarProvider {
  return hasGoogleCredentials()
    ? new GoogleCalendarProvider()
    : new MockCalendarProvider();
}
