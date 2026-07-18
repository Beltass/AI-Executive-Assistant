import { NextRequest, NextResponse } from "next/server";
import { handleUserMessage, type ChatTurn } from "@/lib/agents/orchestrator";

function parseHistory(value: unknown): ChatTurn[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (t): t is ChatTurn =>
      t &&
      (t.role === "user" || t.role === "assistant") &&
      typeof t.text === "string"
  );
}

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const message = typeof body?.message === "string" ? body.message.trim() : "";
  const history = parseHistory(body?.history);

  if (!message) {
    return NextResponse.json(
      { error: "'message' alanı zorunludur." },
      { status: 400 }
    );
  }

  try {
    const result = await handleUserMessage(message, history);
    return NextResponse.json(result);
  } catch (err) {
    const detail = err instanceof Error ? err.message : "Bilinmeyen hata";
    return NextResponse.json({ error: detail }, { status: 500 });
  }
}
