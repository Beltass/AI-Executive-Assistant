import { NextRequest, NextResponse } from "next/server";
import { handleUserMessage } from "@/lib/agents/orchestrator";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const message = typeof body?.message === "string" ? body.message.trim() : "";

  if (!message) {
    return NextResponse.json(
      { error: "'message' alanı zorunludur." },
      { status: 400 }
    );
  }

  try {
    const result = await handleUserMessage(message);
    return NextResponse.json(result);
  } catch (err) {
    const detail = err instanceof Error ? err.message : "Bilinmeyen hata";
    return NextResponse.json({ error: detail }, { status: 500 });
  }
}
