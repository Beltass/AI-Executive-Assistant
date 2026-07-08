import Anthropic from "@anthropic-ai/sdk";

let client: Anthropic | null = null;

/** Tembel init — ANTHROPIC_API_KEY yoksa yalnızca gerçekten çağrıldığında hata verir. */
export function getAnthropicClient(): Anthropic {
  if (!process.env.ANTHROPIC_API_KEY) {
    throw new Error(
      "ANTHROPIC_API_KEY tanımlı değil. frontend/.env.example dosyasını " +
        "frontend/.env.local olarak kopyalayıp anahtarınızı girin."
    );
  }
  if (!client) {
    client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  }
  return client;
}

export const ORCHESTRATOR_MODEL = "claude-sonnet-5";
