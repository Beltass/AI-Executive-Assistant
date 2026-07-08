import { GoogleGenAI } from "@google/genai";

let client: GoogleGenAI | null = null;

/**
 * Google Gemini API — bkz. docs/ARCHITECTURE.md §1 (AI motoru). Gerçek
 * kullanım-bazlı ücretli olan Anthropic Claude API yerine, kişisel/düşük
 * hacimli kullanım için ücretsiz katmanı olan Gemini seçildi (Google AI
 * Studio: https://aistudio.google.com/apikey — kredi kartı gerektirmez,
 * rate-limit'li ücretsiz katman).
 */
export function getGeminiClient(): GoogleGenAI {
  if (!process.env.GEMINI_API_KEY) {
    throw new Error(
      "GEMINI_API_KEY tanımlı değil. https://aistudio.google.com/apikey " +
        "adresinden ücretsiz bir anahtar alıp frontend/.env.local içine " +
        "girin (frontend/.env.example'ı kopyalayarak başlayabilirsiniz)."
    );
  }
  if (!client) {
    client = new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY });
  }
  return client;
}

export const ORCHESTRATOR_MODEL =
  process.env.GEMINI_MODEL ?? "gemini-2.5-flash";
