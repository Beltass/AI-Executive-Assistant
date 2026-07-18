"use client";

import { useState } from "react";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  usedAgent?: string | null;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function sendMessage() {
    const text = input.trim();
    if (!text || loading) return;

    const history = messages.map((m) => ({ role: m.role, text: m.text }));
    setMessages((prev) => [...prev, { role: "user", text }]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history }),
      });
      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error ?? "İstek başarısız oldu.");
      }

      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: data.reply, usedAgent: data.usedAgent },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bilinmeyen hata");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        maxWidth: 640,
        margin: "0 auto",
        padding: 24,
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        boxSizing: "border-box",
      }}
    >
      <h1 style={{ fontSize: 20 }}>AI Executive Assistant</h1>
      <p style={{ color: "#666", fontSize: 14 }}>
        Faz 1 — dikey dilim demosu. Deneyin: &quot;günaydın&quot;,
        &quot;bugünkü e-postalarımı özetle&quot; veya &quot;yarınki
        programımda çakışma var mı?&quot;
      </p>

      <div
        style={{
          flex: 1,
          overflowY: "auto",
          border: "1px solid #ddd",
          borderRadius: 8,
          padding: 16,
          margin: "16px 0",
        }}
      >
        {messages.length === 0 && (
          <p style={{ color: "#999" }}>Henüz mesaj yok.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} style={{ marginBottom: 12 }}>
            <strong>{m.role === "user" ? "Sen" : "Asistan"}:</strong>{" "}
            <span style={{ whiteSpace: "pre-wrap" }}>{m.text}</span>
            {m.usedAgent && (
              <div style={{ fontSize: 12, color: "#888" }}>
                → {m.usedAgent} çağrıldı
              </div>
            )}
          </div>
        ))}
        {loading && <p style={{ color: "#999" }}>Yazıyor…</p>}
        {error && <p style={{ color: "crimson" }}>Hata: {error}</p>}
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder="Bir mesaj yazın…"
          style={{ flex: 1, padding: 10, fontSize: 14 }}
        />
        <button onClick={sendMessage} disabled={loading} style={{ padding: "10px 16px" }}>
          Gönder
        </button>
      </div>
    </main>
  );
}
