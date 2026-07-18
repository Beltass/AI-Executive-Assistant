/**
 * CV çıktı şablonu — Dashboard-Project/is-basvuru/.claude/skills/apply/
 * references/cv-sablonu.tex'in (iki sütunlu LaTeX/PDF) bu asistandaki
 * karşılığı. Vercel serverless ortamında pdflatex çalıştırmak mümkün
 * olmadığı için (bkz. docs/ARCHITECTURE.md §8) çıktı biçimi tek sütunlu
 * Markdown'a uyarlandı — bu aynı zamanda ATS-güvenli tek sütun format
 * gereksinimini (reviewer-kriterleri.md > ATS Format Uyumluluğu Notları)
 * varsayılan olarak karşılar.
 *
 * Yalnızca HEDEF_UNVAN, PROFESYONEL_OZET, YETKINLIKLER yer tutucuları CV
 * Optimizer tarafından doldurulur (cv-sablonu.tex'teki hedefUnvan/
 * profilOzet/YETKİNLİKLER sırası ile birebir aynı kapsam). Diğer tüm
 * bölümler profil.md'den DEĞİŞTİRİLMEDEN alınmıştır.
 */
export const CV_TEMPLATE_MD = "# Burak Eltaş\n{{HEDEF_UNVAN}}\n\n## İletişim\n- **Ad Soyad:** Burak Eltaş\n- **Konum:** İstanbul, Türkiye\n- **Telefon:** +90 532 555 32 80\n- **E-posta:** eltas.burak@gmail.com\n- **LinkedIn:** linkedin.com/in/burakeltas\n\n## Profesyonel Özet\n{{PROFESYONEL_OZET}}\n\n## Yetkinlikler\n{{YETKINLIKLER}}\n\n## Profesyonel Deneyim\n\n### Dış Kaynak Yöneticisi — Paribu Teknoloji A.Ş. (2025 – 2026)\n- 500.000'den fazla aktif fintech kullanıcısına hizmet veren outsource çağrı\n  merkezi ekosisteminin uçtan uca koordinasyonunu yönettim.\n- Çok tedarikçili yapıda ortak bir performans skorlama ve raporlama sistemi\n  kurarak tedarikçi değerlendirme süreçlerini standardize ettim.\n- AI destekli IVR ve dijital iletişim kanalı entegrasyon projelerini yöneterek\n  self-servis kullanımını artırmaya yönelik dönüşümü hayata geçirdim.\n- Tedarikçi maliyet yapısını ve sözleşme koşullarını yeniden yapılandırarak\n  bütçe disiplini ve maliyet optimizasyonu sağladım.\n\n### Müşteri Hizmetleri Yöneticisi — Paribu Teknoloji A.Ş. (2020 – 2025)\n- 5 outsource tedarikçi ve 150'den fazla operasyonel personelden oluşan\n  müşteri hizmetleri ekosistemini yönettim.\n- KPI setlerini sıfırdan tasarladım; aylık performans denetimlerini ve SLA\n  takip mekanizmalarını kurumsallaştırdım.\n- Outsource operasyon bütçesini ve aylık fatura mutabakat süreçlerini\n  yöneterek finansal kontrol düzenini kurdum.\n- Kapasite planlama modeli oluşturarak yoğun dönemlerde hizmet sürekliliğini\n  ve müşteri memnuniyetini güvence altına aldım.\n- Süreç iyileştirme ve kalite izleme projeleri yürüterek operasyonel\n  verimlilik ve hizmet kalitesinde sürdürülebilir gelişim sağladım.\n\n### Çağrı Merkezi Takım Lideri — Turkcell Global Bilgi (2017 – 2019)\n- Home-agent ve sahada görev yapan 40'tan fazla kişilik ekibin işe alım,\n  eğitim ve performans yönetimini yürüttüm.\n- Koçluk ve geri bildirim programları tasarlayarak çalışan bağlılığını ve\n  ekip devamlılığını güçlendirdim.\n- Müşteri deneyimi sapma analizleri yürüterek ilk aramada çözüm (FCR)\n  süreçlerinin iyileştirilmesine liderlik ettim.\n\n### Kalite Geliştirme Uzmanı — Turkcell Global Bilgi (2013 – 2017)\n- Finans projeleri kapsamında aylık 8.000'den fazla çağrının kalite analiz\n  sürecini yönettim.\n- Müşteri temsilcilerine yönelik eğitim içerikleri tasarladım ve uyguladım.\n- Gizli müşteri (mystery shopping) ve kalibrasyon programları kurarak segment\n  bazlı kalite ölçümünü standardize ettim.\n- Kök neden analizine dayalı şikâyet yönetimi yaklaşımıyla tekrarlayan\n  şikâyetlerin önlenmesine yönelik aksiyon planlarını yürüttüm.\n\n### Eğitim ve Kalite Sorumlusu — Koç Sistem / Callus Çağrı Merkezi (2010 – 2012)\n- Aygaz, Vodafone, Yapı Kredi, Ford, Opet ve Dell projelerinin 7/24 inbound\n  ve outbound operasyonlarında kalite standartlarını yönettim.\n- İşe alım mülakatlarını kalite kriterleri bazında yapılandırarak yeni\n  temsilcilerin adaptasyon süreçlerini hızlandırdım.\n- Düşük performanslı projelerde acil aksiyon planları devreye alarak\n  performans toparlanma süreçlerini yönettim.\n\n### Çağrı Merkezi Müşteri Temsilcisi — Koç Sistem / Callus Çağrı Merkezi (2010)\n- Vodafone inbound/outbound operasyonlarında görev aldım; gösterdiğim\n  performansla 9 ay içinde Eğitim ve Kalite Sorumlusu pozisyonuna terfi ettim.\n\n### Kurumsal Satış Sorumlusu — Avea Telekomünikasyon A.Ş. (2008 – 2010)\n- Kurumsal müşteri portföyü geliştirme ve bölge bazlı yeni müşteri kazanımı\n  çalışmalarını yürüttüm.\n- Türk Telekom ortak satış projelerinde görev aldım; bayi denetim ve eğitim\n  programlarıyla satış kanalı süreçlerini standardize ettim.\n\n## Anahtar Başarılar\n\n- 500.000+ aktif kullanıcıya hizmet veren outsource operasyon ekosisteminin\n  uçtan uca yönetimi\n- 5 tedarikçi ve 150+ kişilik çok-vendorlu kadronun liderliği\n- AI destekli IVR ve dijital kanal dönüşüm projelerinin hayata geçirilmesi\n- KPI/SLA yapısının sıfırdan kurulması ve kurumsallaştırılması\n- Süper İş Ödülü — Turkcell Global Bilgi (2013)\n\n## Diller\n\n- Türkçe — Ana Dil\n- İngilizce — Temel\n\n## Eğitim\n\n- **Lisans — İşletme**, Anadolu Üniversitesi (2013 – 2016)\n- **Ön Lisans — Bilgisayar Teknolojisi ve Programlama**, Çanakkale Onsekiz\n  Mart Üniversitesi (2006 – 2008)\n\n## Sertifikalar\n\n- Eğitimcinin Eğitimi — BNB Training\n- Temel Liderlik Becerileri — Turkcell Akademi\n- Temel Proje Yönetimi — Turkcell Akademi\n- Kök Neden Analizi — Turkcell Akademi\n- İş Süreçleri Yönetimi — İstanbul İşletme Enstitüsü\n- ISO 9001 Kalite Yönetim Sistemi\n- Müşteri İlişkileri Yönetimi\n\n## Ödüller\n\n- **Süper İş Ödülü** — Turkcell Global Bilgi (2013): Üstün başarı\n  performansı ile sertifikalı kurumsal ödül.\n\n## Gönüllü Faaliyet\n\n- **Genç TEMA Üyesi** — Genç TEMA Topluluğu (2014 – 2026): TEMA Vakfı\n  projelerinde aktif görev.\n";

/** profil.md > Yetkinlikler — CV Optimizer yalnızca bu kümeyi yeniden
 * sıralayabilir, madde ekleyip çıkaramaz (bkz. reviewer-kriterleri.md). */
export const BASE_SKILLS: string[] = [
  "Customer Experience Management",
  "Contact Center Operations",
  "Outsource Vendor Management",
  "CRM Strategy & Execution",
  "SLA & KPI Management",
  "Process Improvement",
  "Operational Excellence",
  "Quality Assurance & Audit",
  "Team Leadership (150+)",
  "Performance Analytics",
  "AI-Supported IVR / Digital Channels",
  "Capacity Planning",
  "Vendor Budget Management",
  "Eğitim Tasarımı (Train the Trainer)",
  "Kurumsal Müşteri Yönetimi",
  "İkna ve Müzakere Becerileri",
  "MS Office İleri Düzey (Excel, PPT, Word)"
];

/** profil.md > Unvan — ilana özel hedefUnvan üretilemezse varsayılan. */
export const DEFAULT_HEDEF_UNVAN = "Customer Experience & Contact Center Operations Manager";
