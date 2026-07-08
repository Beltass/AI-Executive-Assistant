import { Type, type Content, type FunctionDeclaration } from "@google/genai";
import { getGeminiClient, ORCHESTRATOR_MODEL } from "@/lib/llm";
import { summarizeInbox } from "@/lib/agents/email-agent";

/**
 * Master Orchestrator — bkz. docs/ARCHITECTURE.md §3 ve docs/AGENTS.md.
 * Kullanıcı isteğini sınıflandırır, ilgili uzman ajana yönlendirir.
 * Faz 1'in ilk dikey diliminde tek uzman ajan var: Email Agent.
 * Yeni bir ajan eklendiğinde yalnızca `functionDeclarations` listesine
 * ve `runTool` switch'ine bir dal eklenir — Orchestrator'ın geri kalanı
 * değişmez.
 */

const summarizeInboxDeclaration: FunctionDeclaration = {
  name: "summarize_inbox",
  description:
    "Kullanıcının Gmail gelen kutusundaki son e-postaları özetler ve " +
    "önceliklendirir. Kullanıcı e-postalarını, gelen kutusunu veya " +
    "önemli mesajlarını sorduğunda bu aracı kullan.",
  parameters: {
    type: Type.OBJECT,
    properties: {
      limit: {
        type: Type.NUMBER,
        description: "Kaç e-posta özetlenecek (varsayılan 5).",
      },
    },
  },
};

const tools = [{ functionDeclarations: [summarizeInboxDeclaration] }];

const ORCHESTRATOR_SYSTEM_PROMPT =
  "Sen kullanıcının kişisel AI Executive Assistant'ının Master " +
  "Orchestrator'ısın. Kullanıcının isteğini anla ve gerekirse elindeki " +
  "araçlardan (uzman ajanlardan) uygun olanı çağır. Araç gerekmeyen " +
  "genel sorularda doğrudan Türkçe yanıt ver. Kısa ve net konuş.";

async function runTool(name: string, args: Record<string, unknown>) {
  switch (name) {
    case "summarize_inbox":
      return summarizeInbox(typeof args.limit === "number" ? args.limit : 5);
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
  const genAI = getGeminiClient();

  const contents: Content[] = [{ role: "user", parts: [{ text: userMessage }] }];

  const first = await genAI.models.generateContent({
    model: ORCHESTRATOR_MODEL,
    contents,
    config: {
      systemInstruction: ORCHESTRATOR_SYSTEM_PROMPT,
      tools,
      thinkingConfig: { thinkingBudget: 0 },
    },
  });

  const calls = first.functionCalls;
  if (!calls || calls.length === 0) {
    return { reply: first.text ?? "Bir yanıt üretemedim.", usedAgent: null };
  }

  const call = calls[0];
  const toolResult = await runTool(call.name ?? "", call.args ?? {});

  const modelTurnParts = first.candidates?.[0]?.content?.parts ?? [
    { functionCall: { name: call.name, args: call.args } },
  ];
  contents.push({ role: "model", parts: modelTurnParts });
  contents.push({
    role: "user",
    parts: [
      {
        functionResponse: {
          name: call.name ?? "",
          response: { result: toolResult },
        },
      },
    ],
  });

  const second = await genAI.models.generateContent({
    model: ORCHESTRATOR_MODEL,
    contents,
    config: {
      systemInstruction:
        "Sen kullanıcının kişisel AI Executive Assistant'ının Master " +
        "Orchestrator'ısın. Bir uzman ajandan gelen sonucu kullanıcıya " +
        "Türkçe, kısa ve net şekilde ilet.",
      tools,
      maxOutputTokens: 1024,
      thinkingConfig: { thinkingBudget: 0 },
    },
  });

  return {
    reply: second.text ?? toolResult,
    usedAgent: call.name ?? null,
  };
}
