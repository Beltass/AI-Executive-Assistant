import { getGeminiClient, ORCHESTRATOR_MODEL } from "@/lib/llm";
import { getEmailProvider } from "@/lib/integrations/gmail";

/**
 * Email Agent — bkz. docs/AGENTS.md. Gelen kutusunu okur, özetler ve
 * önceliklendirir. Bu ajan hiçbir e-posta göndermez; yalnızca okuma
 * erişimi kullanır (asgari yetki, bkz. docs/ARCHITECTURE.md §6).
 */
export async function summarizeInbox(limit = 5): Promise<string> {
  const provider = getEmailProvider();
  const emails = await provider.listRecentEmails(limit);

  if (emails.length === 0) {
    return "Gelen kutunuzda özetlenecek yeni e-posta bulunamadı.";
  }

  const genAI = getGeminiClient();
  const emailsAsText = emails
    .map(
      (e, i) =>
        `${i + 1}. Kimden: ${e.from}\n   Konu: ${e.subject}\n   İçerik: ${e.body || e.snippet}\n   Tarih: ${e.receivedAt}`
    )
    .join("\n\n");

  const response = await genAI.models.generateContent({
    model: ORCHESTRATOR_MODEL,
    contents: `Şu e-postaları özetle ve önceliklendir:\n\n${emailsAsText}`,
    config: {
      systemInstruction:
        "Sen bir Email Agent'sın. Sana verilen e-posta listesini kullanıcı " +
        "için önem sırasına göre Türkçe özetle. Müşteri/iş ile ilgili " +
        "e-postaları bülten/otomatik bildirimlerden daha öncelikli say. Her " +
        "e-posta için: kimden geldiğini, ne istendiğini/ne bildirildiğini " +
        "(varsa tarih, tutar, isim, talep gibi somut ayrıntılarla) 2-3 " +
        "cümleyle açıkla ve kullanıcının bir aksiyon alması gerekip " +
        "gerekmediğini belirt. Genel geçer ifadelerle geçiştirme — e-postada " +
        "geçen somut bilgiyi (kim, ne zaman, ne kadar, ne istiyor) mutlaka " +
        "yaz, çünkü kullanıcı bu özete bakarak e-postayı açmadan karar " +
        "verecek. Hiçbir e-postaya yanıt taslağı üretme, yalnızca özetle.",
      maxOutputTokens: 2048,
      thinkingConfig: { thinkingBudget: 0 },
    },
  });

  return response.text ?? "Özet üretilemedi.";
}
