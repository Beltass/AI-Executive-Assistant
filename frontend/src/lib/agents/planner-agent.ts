import { summarizeInbox } from "@/lib/agents/email-agent";
import { summarizeUpcomingSchedule } from "@/lib/agents/calendar-agent";

/**
 * Daily Planner / Morning Briefing — bkz. docs/AGENTS.md. Ayrı bir
 * Gemini çağrısı yapmaz; Email Agent ve Calendar Agent'ın zaten
 * ürettiği özetleri birleştirir (bkz. docs/FEATURES.md "neredeyse
 * bedava" notu — iki mevcut ajanı yeniden kullanır, ek maliyet yok).
 * Kritik görevler/teslim tarihleri, henüz bir görev sistemi
 * (Reminder/Task) olmadığı için bu ilk sürümde yer almıyor — bkz.
 * docs/ROADMAP.md Faz 2.
 */
export async function getMorningBriefing(): Promise<string> {
  const [emailSummary, scheduleSummary] = await Promise.all([
    summarizeInbox(5),
    summarizeUpcomingSchedule(16),
  ]);

  return [
    "Günaydın Burak! İşte bugünkü durumun:",
    "",
    "📧 E-postalar",
    emailSummary,
    "",
    "📅 Bugünkü program",
    scheduleSummary,
  ].join("\n");
}
