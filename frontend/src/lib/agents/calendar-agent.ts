import { getGeminiClient, ORCHESTRATOR_MODEL } from "@/lib/llm";
import { getCalendarProvider } from "@/lib/integrations/google-calendar";

/**
 * Calendar Agent — bkz. docs/AGENTS.md. Yaklaşan etkinlikleri okur,
 * özetler ve çakışma tespit eder. Bu ajan hiçbir etkinlik oluşturmaz/
 * düzenlemez/silmez — yalnızca okuma erişimi kullanır (asgari yetki,
 * bkz. docs/ARCHITECTURE.md §6). Etkinlik oluşturma, dış dünyaya giden
 * bir eylem olduğu için ayrı bir taslak/onay akışı gerektirir ve Faz
 * 1'in bu diliminde henüz eklenmedi (bkz. docs/ROADMAP.md).
 */
export async function summarizeUpcomingSchedule(
  hoursAhead = 24
): Promise<string> {
  const provider = getCalendarProvider();
  const events = await provider.listUpcomingEvents(hoursAhead);

  if (events.length === 0) {
    return `Önümüzdeki ${hoursAhead} saat içinde takviminizde etkinlik bulunamadı.`;
  }

  const genAI = getGeminiClient();
  const eventsAsText = events
    .map(
      (e, i) =>
        `${i + 1}. Başlık: ${e.title}\n   Başlangıç: ${e.start}\n   Bitiş: ${e.end}\n   Yer: ${e.location ?? "belirtilmemiş"}\n   Katılımcılar: ${(e.attendees ?? []).join(", ") || "belirtilmemiş"}`
    )
    .join("\n\n");

  const response = await genAI.models.generateContent({
    model: ORCHESTRATOR_MODEL,
    contents: `Şu takvim etkinliklerini özetle ve zaman çakışması varsa açıkça belirt:\n\n${eventsAsText}`,
    config: {
      systemInstruction:
        "Sen bir Calendar Agent'sın. Sana verilen etkinlik listesini " +
        "kronolojik sırayla kısa ve öz şekilde Türkçe özetle. İki veya " +
        "daha fazla etkinliğin zaman aralığı çakışıyorsa bunu net bir " +
        "uyarı olarak vurgula. Hiçbir etkinlik oluşturma/değiştirme " +
        "önerisinde bulunma, yalnızca mevcut durumu raporla.",
      maxOutputTokens: 1024,
      thinkingConfig: { thinkingBudget: 0 },
    },
  });

  return response.text ?? "Özet üretilemedi.";
}
