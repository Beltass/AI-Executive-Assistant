/**
 * İlan metni edinme — `is-basvuru/scrape` becerisinin bu asistandaki en
 * sınırlı (ve en ToS-güvenli) karşılığı. Otomatik arama/tarama YAPMAZ:
 * yalnızca kullanıcının verdiği TEK bir ilan URL'sini getirir (tek istek,
 * insan tarafından seçilmiş sayfa) — bkz. Dashboard-Project CLAUDE.md
 * "No bulk/automated scraping — low-volume, human-supervised browsing
 * only." LinkedIn gibi JS ile render edilen/oturum duvarlı siteler bu
 * basit fetch ile çoğunlukla boş/eksik içerik döner; bu durumda kullanıcıdan
 * ilan metnini elle yapıştırması istenmelidir (Job Search Agent bunu zaten
 * yapar, bkz. job-search-agent.ts).
 */

const MAX_POSTING_CHARS = 6000;

function stripHtml(html: string): string {
  return html
    .replace(/<style[\s\S]*?<\/style>/gi, "")
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export async function fetchJobPostingText(url: string): Promise<string> {
  const res = await fetch(url, {
    headers: {
      "User-Agent":
        "Mozilla/5.0 (compatible; AI-Executive-Assistant/1.0; tek-kullanıcı iş başvuru asistanı)",
    },
  });
  if (!res.ok) {
    throw new Error(`İlan sayfası alınamadı (HTTP ${res.status}): ${url}`);
  }
  const html = await res.text();
  return stripHtml(html).slice(0, MAX_POSTING_CHARS);
}
