import { Type } from "@google/genai";
import { getGeminiClient, ORCHESTRATOR_MODEL } from "@/lib/llm";
import { PROFIL_MD } from "./job-search/profile-data";
import { REVIEWER_KRITERLERI_MD } from "./job-search/scoring-rubric";
import {
  CV_TEMPLATE_MD,
  BASE_SKILLS,
  DEFAULT_HEDEF_UNVAN,
} from "./job-search/cv-template";
import { fetchJobPostingText } from "@/lib/integrations/job-posting";
import {
  getApplicationTracker,
  isTrackingPersistent,
} from "@/lib/integrations/job-tracker";

/**
 * Job Search Agent + CV Optimizer — bkz. docs/AGENTS.md. Kaynak mantık:
 * Dashboard-Project/is-basvuru/.claude/skills/apply (kardeş repo, bkz.
 * bu reponun CLAUDE.md'si). Üç kural mutlak: (1) profil.md'deki olgusal
 * içerik asla değiştirilmez/uydurulmaz, (2) <50 puanlı ilana taslak
 * üretilmez, (3) hiçbir platforma otomatik başvuru gönderilmez — bu
 * ajan yalnızca taslak üretir, kullanıcı kendisi gönderir.
 *
 * Ortam farkı notu (bkz. docs/ARCHITECTURE.md §8): orijinal beceri
 * pdflatex ile iki sütunlu bir PDF üretiyordu; Vercel serverless'ta
 * LaTeX toolchain çalıştırmak mümkün olmadığı için çıktı tek sütunlu
 * Markdown'a uyarlandı (aynı zamanda ATS-güvenli format). Otomatik ilan
 * TARAMASI (LinkedIn/kariyer.net arama sonuçları) da bu sürümde YOK —
 * yalnızca kullanıcının verdiği tek bir ilan URL'si/metni değerlendirilir
 * (orijinal `scrape` becerisi de zaten kullanıcı onaylı bir URL istiyordu).
 */

interface FitScoreResult {
  score: number;
  company: string;
  title: string;
  strengths: string[];
  gaps: string[];
  recommendation: string;
}

async function scoreJobFit(jobPostingText: string): Promise<FitScoreResult> {
  const genAI = getGeminiClient();

  const response = await genAI.models.generateContent({
    model: ORCHESTRATOR_MODEL,
    contents:
      `Aday profili:\n\n${PROFIL_MD}\n\n---\n\n` +
      `Değerlendirilecek ilan metni:\n\n${jobPostingText}`,
    config: {
      systemInstruction:
        "Sen bir CV Optimizer / Job Search Agent'sın. Aday profiliyle " +
        "ilan metnini aşağıdaki rubriğe göre 0-100 arası puanla:\n\n" +
        REVIEWER_KRITERLERI_MD +
        "\n\nÖnyargısız değerlendir — yaş, cinsiyet, milliyet gibi ilanda " +
        "veya profilde geçen ama rubrikte yer almayan hiçbir ölçütü " +
        "değerlendirmeye katma. Yalnızca profildeki ve ilandaki somut " +
        "bilgilere dayan, spekülasyon yapma. İlan metninden şirket adını " +
        "ve unvanı da çıkar (bulamazsan 'Belirtilmemiş' yaz). strengths " +
        "(güçlü yönler) ve gaps (eksiklikler/riskler) alanlarını kısa, " +
        "somut maddeler halinde doldur.",
      responseMimeType: "application/json",
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          score: { type: Type.NUMBER },
          company: { type: Type.STRING },
          title: { type: Type.STRING },
          strengths: { type: Type.ARRAY, items: { type: Type.STRING } },
          gaps: { type: Type.ARRAY, items: { type: Type.STRING } },
          recommendation: { type: Type.STRING },
        },
        required: [
          "score",
          "company",
          "title",
          "strengths",
          "gaps",
          "recommendation",
        ],
      },
      maxOutputTokens: 2048,
      thinkingConfig: { thinkingBudget: 0 },
    },
  });

  const parsed = JSON.parse(response.text ?? "{}");
  return {
    score: Math.max(0, Math.min(100, Math.round(Number(parsed.score) || 0))),
    company: parsed.company || "Belirtilmemiş",
    title: parsed.title || "Belirtilmemiş",
    strengths: Array.isArray(parsed.strengths) ? parsed.strengths : [],
    gaps: Array.isArray(parsed.gaps) ? parsed.gaps : [],
    recommendation: parsed.recommendation || "",
  };
}

interface DraftResult {
  profilOzet: string;
  hedefUnvan: string;
  yetkinlikSirasi: string[];
  onYazi: string;
}

async function draftApplicationMaterials(
  jobPostingText: string,
  company: string,
  title: string
): Promise<DraftResult> {
  const genAI = getGeminiClient();

  const response = await genAI.models.generateContent({
    model: ORCHESTRATOR_MODEL,
    contents:
      `Aday profili:\n\n${PROFIL_MD}\n\n---\n\n` +
      `İlan (${company} — ${title}):\n\n${jobPostingText}`,
    config: {
      systemInstruction:
        "Sen bir CV Optimizer'sın. Aşağıdaki kurallara KESİNLİKLE uy:\n" +
        "1. profilOzet: Aday profilindeki 'Profesyonel Özet' bölümünü 2-4 " +
        "cümleye indir, ilanın öne çıkan anahtar kelimelerini vurgula. " +
        "Rakamları (17 yıl, 500.000+, 150+ vb.) ve olguları KESİNLİKLE " +
        "DEĞİŞTİRME — yalnızca hangi cümlelerin öne çıkacağını seç.\n" +
        "2. hedefUnvan: İlanın unvanına yakın ama adayın gerçek kariyer " +
        "geçmişiyle çelişmeyecek bir başlık öner.\n" +
        "3. yetkinlikSirasi: Aşağıdaki TAM kümeyi (tam olarak bu 17 öğe), " +
        "ilana en uygun olanlar başta olacak şekilde YENİDEN SIRALA. Madde " +
        "ekleme, çıkarma, metnini değiştirme — SADECE sırala:\n" +
        BASE_SKILLS.map((s) => `- ${s}`).join("\n") +
        "\n4. onYazi: 3-5 cümlelik, ilana özel, adayın somut " +
        "başarılarından 1-2 tanesini referans veren bir ön yazı/mesaj " +
        "taslağı yaz. Klişe/şişirilmiş dil kullanma, olgulara sadık kal, " +
        "hiçbir rakam/unvan uydurma.",
      responseMimeType: "application/json",
      responseSchema: {
        type: Type.OBJECT,
        properties: {
          profilOzet: { type: Type.STRING },
          hedefUnvan: { type: Type.STRING },
          yetkinlikSirasi: { type: Type.ARRAY, items: { type: Type.STRING } },
          onYazi: { type: Type.STRING },
        },
        required: ["profilOzet", "hedefUnvan", "yetkinlikSirasi", "onYazi"],
      },
      maxOutputTokens: 2048,
      thinkingConfig: { thinkingBudget: 0 },
    },
  });

  const parsed = JSON.parse(response.text ?? "{}");

  // Savunmacı kontrol: yetkinlikSirasi tam olarak BASE_SKILLS'in bir
  // permütasyonu olmalı. Model bir madde ekler/çıkarır/değiştirirse
  // (profil.md'ye sadakat kuralı gereği) orijinal sıraya geri dön.
  const candidateSkills: string[] = Array.isArray(parsed.yetkinlikSirasi)
    ? parsed.yetkinlikSirasi
    : [];
  const isValidPermutation =
    candidateSkills.length === BASE_SKILLS.length &&
    [...candidateSkills].sort().join("|") === [...BASE_SKILLS].sort().join("|");

  return {
    profilOzet: parsed.profilOzet || "",
    hedefUnvan: parsed.hedefUnvan || DEFAULT_HEDEF_UNVAN,
    yetkinlikSirasi: isValidPermutation ? candidateSkills : BASE_SKILLS,
    onYazi: parsed.onYazi || "",
  };
}

function buildCvMarkdown(draft: DraftResult): string {
  return CV_TEMPLATE_MD.replace("{{HEDEF_UNVAN}}", draft.hedefUnvan)
    .replace("{{PROFESYONEL_OZET}}", draft.profilOzet)
    .replace(
      "{{YETKINLIKLER}}",
      draft.yetkinlikSirasi.map((s) => `- ${s}`).join("\n")
    );
}

function sourceFromUrl(url: string | undefined): string {
  if (!url) return "yapıştırılan metin";
  try {
    return new URL(url).hostname;
  } catch {
    return "yapıştırılan metin";
  }
}

function persistenceNote(): string {
  return isTrackingPersistent()
    ? ""
    : "\n\n_Not: Supabase henüz bağlı olmadığı için bu takip kaydı kalıcı " +
        "değil, yalnızca bu sunucu oturumunda tutuluyor (bkz. .env.example)._";
}

export interface JobSearchAgentInput {
  jobPostingText?: string;
  jobPostingUrl?: string;
  /** Kullanıcı 50-69 puanlık bir ilan için önceki turda "devam et" dediyse
   * Orchestrator bunu konuşma geçmişinden çıkarıp true geçirmeli. */
  forceProceed?: boolean;
}

export async function evaluateJobApplication(
  input: JobSearchAgentInput
): Promise<string> {
  let postingText = input.jobPostingText?.trim() ?? "";

  if (!postingText && input.jobPostingUrl) {
    try {
      postingText = await fetchJobPostingText(input.jobPostingUrl);
    } catch (err) {
      return (
        "İlan sayfası otomatik olarak alınamadı " +
        `(${err instanceof Error ? err.message : "bilinmeyen hata"}). ` +
        "Bu genellikle LinkedIn gibi oturum duvarlı/JS ile render edilen " +
        "sitelerde olur. İlan metnini doğrudan yapıştırırsanız devam " +
        "edebilirim."
      );
    }
  }

  if (!postingText) {
    return (
      "Değerlendirebilmem için bir ilan metni yapıştırın ya da (kariyer.net " +
      "gibi) herkese açık bir ilan URL'si verin."
    );
  }

  const tracker = getApplicationTracker();
  if (input.jobPostingUrl) {
    const existing = await tracker.findByUrl(input.jobPostingUrl);
    if (existing) {
      return (
        `Bu ilan için zaten bir kayıt var: ${existing.sirket} — ` +
        `${existing.unvan}, durum: ${existing.durum} (${existing.tarih}). ` +
        "Yeniden taslak hazırlamamı ister misiniz?"
      );
    }
  }

  const fit = await scoreJobFit(postingText);
  const scoreSummary =
    `**${fit.company} — ${fit.title}**\n` +
    `Uygunluk puanı: ${fit.score}/100\n\n` +
    `**Güçlü Yönler:**\n${fit.strengths.map((s) => `- ${s}`).join("\n") || "- (belirtilmedi)"}\n\n` +
    `**Eksiklikler / Riskler:**\n${fit.gaps.map((s) => `- ${s}`).join("\n") || "- (belirtilmedi)"}\n\n` +
    `**Değerlendirme:** ${fit.recommendation}`;

  const kaynak = sourceFromUrl(input.jobPostingUrl);

  if (fit.score < 50 && !input.forceProceed) {
    await tracker.logApplication({
      tarih: new Date().toISOString(),
      sirket: fit.company,
      unvan: fit.title,
      ilanUrl: input.jobPostingUrl ?? "",
      kaynak,
      uygunlukPuani: fit.score,
      durum: "atlandi",
      not: fit.recommendation.slice(0, 200),
    });
    return (
      `${scoreSummary}\n\n50 puanın altında olduğu için başvuru taslağı ` +
      `hazırlamadım; takip kaydına "atlandı" olarak not düştüm.${persistenceNote()}`
    );
  }

  if (fit.score < 70 && !input.forceProceed) {
    return (
      `${scoreSummary}\n\nBu ilan orta düzeyde uygun. Yine de taslak ` +
      "hazırlamamı ister misiniz?"
    );
  }

  const draft = await draftApplicationMaterials(postingText, fit.company, fit.title);
  const cvMarkdown = buildCvMarkdown(draft);

  await tracker.logApplication({
    tarih: new Date().toISOString(),
    sirket: fit.company,
    unvan: fit.title,
    ilanUrl: input.jobPostingUrl ?? "",
    kaynak,
    uygunlukPuani: fit.score,
    durum: "taslak-hazir",
    not: "Taslak otomatik hazırlandı, kullanıcı onayı bekliyor.",
  });

  return (
    `${scoreSummary}\n\n---\n\n## Başvuru Taslağı (CV)\n\n${cvMarkdown}\n\n---\n\n` +
    `## Ön Yazı / Mesaj Taslağı\n\n${draft.onYazi}\n\n---\n\n` +
    "**Bu materyalleri ben göndermiyorum** — inceleyip uygun bulursanız " +
    "kendiniz başvurun. Başvuruyu fiilen gönderdiğinizde bana bildirin, " +
    `takip kaydını "başvuruldu" olarak güncelleyeyim.${persistenceNote()}`
  );
}

export async function markApplicationSubmitted(
  identifier: string
): Promise<string> {
  const tracker = getApplicationTracker();

  const looksLikeUrl = /^https?:\/\//i.test(identifier);
  if (looksLikeUrl) {
    const updated = await tracker.updateStatus(identifier, "basvuruldu");
    return updated
      ? "Takip kaydını güncelledim: durum artık \"başvuruldu\"."
      : "Bu ilan URL'sine ait bir takip kaydı bulamadım.";
  }

  const recent = await tracker.findRecent(20);
  const match = recent.find((r) =>
    r.sirket.toLowerCase().includes(identifier.toLowerCase())
  );
  if (!match) {
    return (
      `"${identifier}" ile eşleşen bir takip kaydı bulamadım. İlanın URL'sini ` +
      "verirseniz doğrudan onunla güncelleyebilirim."
    );
  }

  const updated = await tracker.updateStatus(match.ilanUrl, "basvuruldu");
  return updated
    ? `${match.sirket} — ${match.unvan} kaydını "başvuruldu" olarak güncelledim.`
    : "Kaydı bulundu ama güncellenemedi (ilan URL'si boş olabilir).";
}
