#!/usr/bin/env node
/**
 * Tek seferlik yerel yardımcı: Google OAuth "izin ver" akışını tamamlayıp
 * GOOGLE_REFRESH_TOKEN üretir. Ön koşul: Google Cloud Console'da bir OAuth
 * Client ID oluşturup GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET'i
 * frontend/.env.local içine yazmış olman gerekir — bkz. README talimatı.
 *
 * Kullanım: npm run get-google-token
 */
import { google } from "googleapis";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadEnvLocal() {
  const envPath = path.resolve(__dirname, "..", ".env.local");
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, "utf-8").split("\n")) {
    const match = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (match && !process.env[match[1]]) {
      process.env[match[1]] = match[2].trim();
    }
  }
}

loadEnvLocal();

const CLIENT_ID = process.env.GOOGLE_CLIENT_ID;
const CLIENT_SECRET = process.env.GOOGLE_CLIENT_SECRET;
const REDIRECT_URI =
  process.env.GOOGLE_REDIRECT_URI ?? "http://localhost:3000/api/auth/google/callback";

if (!CLIENT_ID || !CLIENT_SECRET) {
  console.error(
    "\nHata: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET frontend/.env.local içinde bulunamadı.\n" +
      "Önce Google Cloud Console'da bir OAuth Client ID oluşturup bu iki değeri girin.\n"
  );
  process.exit(1);
}

const redirectUrl = new URL(REDIRECT_URI);
const port = Number(redirectUrl.port || 3000);

const oauth2Client = new google.auth.OAuth2(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI);

const SCOPES = [
  "https://www.googleapis.com/auth/gmail.readonly",
  "https://www.googleapis.com/auth/calendar.readonly",
];

const authUrl = oauth2Client.generateAuthUrl({
  access_type: "offline",
  prompt: "consent",
  scope: SCOPES,
});

console.log("\n1) Şu adresi tarayıcıda aç ve kendi Google hesabınla giriş yap:\n");
console.log(authUrl);
console.log(
  `\n2) İzin verdikten sonra tarayıcı otomatik olarak localhost:${port} adresine yönlenecek ` +
    "ve bu terminale sonucu yazdıracağım. Bu pencereyi kapatma.\n"
);

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${port}`);
  if (url.pathname !== redirectUrl.pathname) {
    res.writeHead(404);
    res.end();
    return;
  }

  const code = url.searchParams.get("code");
  const error = url.searchParams.get("error");

  if (error) {
    res.writeHead(400, { "Content-Type": "text/html; charset=utf-8" });
    res.end(`<h1>Hata: ${error}</h1><p>Terminale dönüp scripti tekrar çalıştırın.</p>`);
    console.error("\nOAuth hatası:", error, "\n");
    server.close();
    process.exit(1);
  }

  try {
    const { tokens } = await oauth2Client.getToken(code);
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
    res.end("<h1>Başarılı — bu sekmeyi kapatabilirsiniz.</h1><p>Terminale dönün.</p>");

    if (!tokens.refresh_token) {
      console.warn(
        "\nUyarı: refresh_token dönmedi. Muhtemelen bu uygulamaya daha önce izin " +
          "vermiştiniz. https://myaccount.google.com/connections adresinden bu " +
          "uygulamanın erişimini iptal edip scripti tekrar çalıştırın.\n"
      );
    } else {
      console.log("\n✅ Başarılı! Şu satırı frontend/.env.local dosyasına ekleyin:\n");
      console.log(`GOOGLE_REFRESH_TOKEN=${tokens.refresh_token}\n`);
    }
  } catch (err) {
    res.writeHead(500, { "Content-Type": "text/html; charset=utf-8" });
    res.end("<h1>Token alınamadı.</h1>");
    console.error("\nToken değişimi başarısız:", err instanceof Error ? err.message : err, "\n");
  } finally {
    server.close();
    process.exit(0);
  }
});

server.listen(port, () => {});
