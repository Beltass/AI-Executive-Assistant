/**
 * Başvuru takip günlüğü — `is-basvuru/basvurular/takip.csv`'nin bu asistandaki
 * karşılığı (bkz. Dashboard-Project CLAUDE.md). Aynı sağlayıcı-soyutlama
 * deseni (bkz. gmail.ts/google-calendar.ts): Supabase kimlik bilgisi yoksa
 * oturum-bazlı (kalıcı olmayan) bir bellek-içi kayda düşer.
 */

export type ApplicationStatus =
  | "taslak-hazir"
  | "basvuruldu"
  | "elendi"
  | "atlandi";

export interface JobApplicationRecord {
  tarih: string;
  sirket: string;
  unvan: string;
  ilanUrl: string;
  kaynak: string;
  uygunlukPuani: number;
  durum: ApplicationStatus;
  not: string;
}

export interface ApplicationTracker {
  logApplication(record: JobApplicationRecord): Promise<void>;
  /** Aynı ilana daha önce kayıt girilip girilmediğini kontrol eder (dedupe). */
  findByUrl(ilanUrl: string): Promise<JobApplicationRecord | null>;
  /** En son kayıtları döner — "başvurdum" gibi serbest metin bildirimlerinde
   * ilanı şirket/unvan adıyla eşleştirmek için kullanılır. */
  findRecent(limit: number): Promise<JobApplicationRecord[]>;
  /** Kullanıcı başvuruyu fiilen gönderdiğini bildirdiğinde durumu günceller. */
  updateStatus(ilanUrl: string, durum: ApplicationStatus): Promise<boolean>;
}

/**
 * Supabase kimlik bilgisi girilmeden önce kullanılan varsayılan. Kayıtlar
 * yalnızca bu sunucu instance'ının belleğinde tutulur — deploy/soğuk
 * başlatma sonrası kaybolur. Gerçek kalıcılık için Supabase gerekir (bkz.
 * `.env.example`).
 */
export class InMemoryApplicationTracker implements ApplicationTracker {
  private static records: JobApplicationRecord[] = [];

  async logApplication(record: JobApplicationRecord): Promise<void> {
    InMemoryApplicationTracker.records.push(record);
  }

  async findByUrl(ilanUrl: string): Promise<JobApplicationRecord | null> {
    return (
      InMemoryApplicationTracker.records.find((r) => r.ilanUrl === ilanUrl) ??
      null
    );
  }

  async findRecent(limit: number): Promise<JobApplicationRecord[]> {
    return InMemoryApplicationTracker.records.slice(-limit).reverse();
  }

  async updateStatus(ilanUrl: string, durum: ApplicationStatus): Promise<boolean> {
    const record = InMemoryApplicationTracker.records.find(
      (r) => r.ilanUrl === ilanUrl
    );
    if (!record) return false;
    record.durum = durum;
    return true;
  }
}

/**
 * Supabase `job_applications` tablosu üzerinden kalıcı takip. Şema:
 * tarih (timestamptz), sirket (text), unvan (text), ilan_url (text, unique
 * önerilir), kaynak (text), uygunluk_puani (int), durum (text), not (text).
 */
export class SupabaseApplicationTracker implements ApplicationTracker {
  private async client() {
    const { createClient } = await import("@supabase/supabase-js");
    return createClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.SUPABASE_SERVICE_ROLE_KEY ??
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
    );
  }

  async logApplication(record: JobApplicationRecord): Promise<void> {
    const supabase = await this.client();
    const { error } = await supabase.from("job_applications").insert({
      tarih: record.tarih,
      sirket: record.sirket,
      unvan: record.unvan,
      ilan_url: record.ilanUrl,
      kaynak: record.kaynak,
      uygunluk_puani: record.uygunlukPuani,
      durum: record.durum,
      not: record.not,
    });
    if (error) throw new Error(`Supabase kayıt hatası: ${error.message}`);
  }

  async findByUrl(ilanUrl: string): Promise<JobApplicationRecord | null> {
    const supabase = await this.client();
    const { data, error } = await supabase
      .from("job_applications")
      .select("*")
      .eq("ilan_url", ilanUrl)
      .maybeSingle();
    if (error || !data) return null;
    return {
      tarih: data.tarih,
      sirket: data.sirket,
      unvan: data.unvan,
      ilanUrl: data.ilan_url,
      kaynak: data.kaynak,
      uygunlukPuani: data.uygunluk_puani,
      durum: data.durum,
      not: data.not,
    };
  }

  async findRecent(limit: number): Promise<JobApplicationRecord[]> {
    const supabase = await this.client();
    const { data, error } = await supabase
      .from("job_applications")
      .select("*")
      .order("tarih", { ascending: false })
      .limit(limit);
    if (error || !data) return [];
    return data.map((d) => ({
      tarih: d.tarih,
      sirket: d.sirket,
      unvan: d.unvan,
      ilanUrl: d.ilan_url,
      kaynak: d.kaynak,
      uygunlukPuani: d.uygunluk_puani,
      durum: d.durum,
      not: d.not,
    }));
  }

  async updateStatus(ilanUrl: string, durum: ApplicationStatus): Promise<boolean> {
    const supabase = await this.client();
    const { error, count } = await supabase
      .from("job_applications")
      .update({ durum }, { count: "exact" })
      .eq("ilan_url", ilanUrl);
    return !error && (count ?? 0) > 0;
  }
}

function hasSupabaseCredentials(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
      (process.env.SUPABASE_SERVICE_ROLE_KEY ||
        process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY)
  );
}

export function getApplicationTracker(): ApplicationTracker {
  return hasSupabaseCredentials()
    ? new SupabaseApplicationTracker()
    : new InMemoryApplicationTracker();
}

export function isTrackingPersistent(): boolean {
  return hasSupabaseCredentials();
}
