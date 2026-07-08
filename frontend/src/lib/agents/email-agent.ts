import { getAnthropicClient, ORCHESTRATOR_MODEL } from "@/lib/anthropic";
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

  const anthropic = getAnthropicClient();
  const emailsAsText = emails
    .map(
      (e, i) =>
        `${i + 1}. Kimden: ${e.from}\n   Konu: ${e.subject}\n   Özet: ${e.snippet}\n   Tarih: ${e.receivedAt}`
    )
    .join("\n\n");

  const response = await anthropic.messages.create({
    model: ORCHESTRATOR_MODEL,
    max_tokens: 600,
    system:
      "Sen bir Email Agent'sın. Sana verilen e-posta listesini kullanıcı " +
      "için önem sırasına göre kısa ve öz şekilde Türkçe özetle. Müşteri/iş " +
      "ile ilgili e-postaları bülten/otomatik bildirimlerden daha öncelikli " +
      "say. Her e-posta için tek satırlık bir öncelik notu ver. Hiçbir " +
      "e-postaya yanıt taslağı üretme, yalnızca özetle.",
    messages: [
      {
        role: "user",
        content: `Şu e-postaları özetle ve önceliklendir:\n\n${emailsAsText}`,
      },
    ],
  });

  const textBlock = response.content.find((b) => b.type === "text");
  return textBlock && textBlock.type === "text"
    ? textBlock.text
    : "Özet üretilemedi.";
}
