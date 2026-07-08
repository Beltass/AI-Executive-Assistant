import Anthropic from "@anthropic-ai/sdk";
import { getAnthropicClient, ORCHESTRATOR_MODEL } from "@/lib/anthropic";
import { summarizeInbox } from "@/lib/agents/email-agent";

/**
 * Master Orchestrator — bkz. docs/ARCHITECTURE.md §3 ve docs/AGENTS.md.
 * Kullanıcı isteğini sınıflandırır, ilgili uzman ajana yönlendirir.
 * Faz 1'in ilk dikey diliminde tek uzman ajan var: Email Agent.
 * Yeni bir ajan eklendiğinde yalnızca `tools` listesine ve switch'e
 * bir dal eklenir — Orchestrator'ın geri kalanı değişmez.
 */

const tools: Anthropic.Tool[] = [
  {
    name: "summarize_inbox",
    description:
      "Kullanıcının Gmail gelen kutusundaki son e-postaları özetler ve " +
      "önceliklendirir. Kullanıcı e-postalarını, gelen kutusunu veya " +
      "önemli mesajlarını sorduğunda bu aracı kullan.",
    input_schema: {
      type: "object",
      properties: {
        limit: {
          type: "number",
          description: "Kaç e-posta özetlenecek (varsayılan 5).",
        },
      },
    },
  },
];

async function runTool(name: string, input: Record<string, unknown>) {
  switch (name) {
    case "summarize_inbox":
      return summarizeInbox(typeof input.limit === "number" ? input.limit : 5);
    default:
      throw new Error(`Bilinmeyen araç: ${name}`);
  }
}

export interface OrchestratorResult {
  reply: string;
  usedAgent: string | null;
}

export async function handleUserMessage(
  userMessage: string
): Promise<OrchestratorResult> {
  const anthropic = getAnthropicClient();

  const messages: Anthropic.MessageParam[] = [
    { role: "user", content: userMessage },
  ];

  const first = await anthropic.messages.create({
    model: ORCHESTRATOR_MODEL,
    max_tokens: 600,
    system:
      "Sen kullanıcının kişisel AI Executive Assistant'ının Master " +
      "Orchestrator'ısın. Kullanıcının isteğini anla ve gerekirse elindeki " +
      "araçlardan (uzman ajanlardan) uygun olanı çağır. Araç gerekmeyen " +
      "genel sorularda doğrudan Türkçe yanıt ver. Kısa ve net konuş.",
    tools,
    messages,
  });

  const toolUse = first.content.find((b) => b.type === "tool_use");

  if (!toolUse || toolUse.type !== "tool_use") {
    const textBlock = first.content.find((b) => b.type === "text");
    return {
      reply:
        textBlock && textBlock.type === "text"
          ? textBlock.text
          : "Bir yanıt üretemedim.",
      usedAgent: null,
    };
  }

  const toolResult = await runTool(
    toolUse.name,
    (toolUse.input as Record<string, unknown>) ?? {}
  );

  const second = await anthropic.messages.create({
    model: ORCHESTRATOR_MODEL,
    max_tokens: 600,
    system:
      "Sen kullanıcının kişisel AI Executive Assistant'ının Master " +
      "Orchestrator'ısın. Bir uzman ajandan gelen sonucu kullanıcıya " +
      "Türkçe, kısa ve net şekilde ilet.",
    tools,
    messages: [
      ...messages,
      { role: "assistant", content: first.content },
      {
        role: "user",
        content: [
          {
            type: "tool_result",
            tool_use_id: toolUse.id,
            content: toolResult,
          },
        ],
      },
    ],
  });

  const finalText = second.content.find((b) => b.type === "text");
  return {
    reply:
      finalText && finalText.type === "text"
        ? finalText.text
        : toolResult,
    usedAgent: toolUse.name,
  };
}
