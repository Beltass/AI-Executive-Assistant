import { Type, type Content, type FunctionDeclaration } from "@google/genai";
import { getGeminiClient, ORCHESTRATOR_MODEL } from "@/lib/llm";
import { summarizeInbox } from "@/lib/agents/email-agent";
import { summarizeUpcomingSchedule } from "@/lib/agents/calendar-agent";
import { getMorningBriefing } from "@/lib/agents/planner-agent";

/**
 * Master Orchestrator — bkz. docs/ARCHITECTURE.md §3 ve docs/AGENTS.md.
 * Kullanıcı isteğini sınıflandırır, ilgili uzman ajana yönlendirir.
 * Faz 1'de üç uzman yetenek var: Email Agent, Calendar Agent ve bu
 * ikisini birleştiren Morning Briefing (Daily Planner'ın ilk çıktısı).
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

const summarizeScheduleDeclaration: FunctionDeclaration = {
  name: "summarize_upcoming_schedule",
  description:
    "Kullanıcının Google Calendar'ındaki yaklaşan etkinlikleri özetler " +
    "ve zaman çakışmalarını tespit eder. Kullanıcı takvimini, " +
    "programını, bugünkü/yarınki toplantılarını sorduğunda veya " +
    "çakışma olup olmadığını öğrenmek istediğinde bu aracı kullan.",
  parameters: {
    type: Type.OBJECT,
    properties: {
      hoursAhead: {
        type: Type.NUMBER,
        description:
          "Kaç saat ilerisine bakılacak (varsayılan 24, örn. 'yarın' için ~48).",
      },
    },
  },
};

const morningBriefingDeclaration: FunctionDeclaration = {
  name: "get_morning_briefing",
  description:
    "E-postaları ve bugünkü takvim programını tek bir günaydın " +
    "raporunda birleştirir. Kullanıcı 'günaydın', 'bugünkü briefingimi " +
    "ver', 'günlük özetimi göster' gibi genel bir durum raporu " +
    "istediğinde — yalnızca e-posta VEYA yalnızca takvim değil, ikisini " +
    "birden istediğinde — bu aracı kullan.",
  parameters: { type: Type.OBJECT, properties: {} },
};

const tools = [
  {
    functionDeclarations: [
      summarizeInboxDeclaration,
      summarizeScheduleDeclaration,
      morningBriefingDeclaration,
    ],
  },
];

const ORCHESTRATOR_SYSTEM_PROMPT =
  "Sen kullanıcının kişisel AI Executive Assistant'ının Master " +
  "Orchestrator'ısın. Kullanıcının isteğini anla ve gerekirse elindeki " +
  "araçlardan (uzman ajanlardan) uygun olanı çağır. Araç gerekmeyen " +
  "genel sorularda doğrudan Türkçe yanıt ver. Kısa ve net konuş.";

async function runTool(name: string, args: Record<string, unknown>) {
  switch (name) {
    case "summarize_inbox":
      return summarizeInbox(typeof args.limit === "number" ? args.limit : 5);
    case "summarize_upcoming_schedule":
      return summarizeUpcomingSchedule(
        typeof args.hoursAhead === "number" ? args.hoursAhead : 24
      );
    case "get_morning_briefing":
      return getMorningBriefing();
    default:
      throw new Error(`Bilinmeyen araç: ${name}`);
  }
}

export interface OrchestratorResult {
  reply: string;
  usedAgent: string | null;
}

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

/** Kaç önceki mesaj konuşma geçmişi olarak modele gönderilsin — sınırsız
 * büyümesin diye (token maliyeti). Uzun vadeli hafıza değil; bkz. Memory
 * Agent (Faz 1, ROADMAP.md madde 5) — bu yalnızca aynı oturum içi süreklilik. */
const MAX_HISTORY_TURNS = 20;

export async function handleUserMessage(
  userMessage: string,
  history: ChatTurn[] = []
): Promise<OrchestratorResult> {
  const genAI = getGeminiClient();

  const historyContents: Content[] = history
    .slice(-MAX_HISTORY_TURNS)
    .map((turn) => ({
      role: turn.role === "assistant" ? "model" : "user",
      parts: [{ text: turn.text }],
    }));

  const contents: Content[] = [
    ...historyContents,
    { role: "user", parts: [{ text: userMessage }] },
  ];

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
      maxOutputTokens: 2048,
      thinkingConfig: { thinkingBudget: 0 },
    },
  });

  return {
    reply: second.text ?? toolResult,
    usedAgent: call.name ?? null,
  };
}
