"""Banking & contact-center project expert — Banka & Çağrı Merkezi Proje Uzmanı.

A DEEP DOMAIN specialist, deliberately distinct from the broader
:mod:`ai_assistant.advisors.sector_intel` advisor: where sector intel scans the
market and competitors, this persona is a senior consultant who has actually run
bank contact-center **outsourcing programs** and, just as importantly, has sat on
the other side of the table during **information-security and compliance audits**
of those programs. It speaks the language of RFPs, SLAs, transition plans,
right-to-audit clauses, KVKK data-processor contracts and PCI DSS scope
reduction.

The persona is grounded in the frameworks that actually govern this work in
Turkey and internationally:

* **BDDK** — *Bankaların Destek Hizmeti Almalarına İlişkin Yönetmelik* (support
  service procurement: risk management programme, written risk analysis before
  procurement, board/audit-committee reporting, provider qualification, the
  regulator's right to information and inspection) and *Bankaların Bilgi
  Sistemleri ve Elektronik Bankacılık Hizmetleri Hakkında Yönetmelik*
  (information-systems governance, IS risk management, information security
  management, continuity/availability, outsourcing of information systems,
  internal control & audit; subcontracting subject to bank approval; primary and
  secondary systems kept in-country; private/community cloud models).
* **KVKK / Kanun 6698** — controller vs. processor, data-processor contracts,
  aydınlatma & açık rıza, retention-and-destruction policy, VERBİS, breach
  notification to the Board, and the cross-border transfer regime rebuilt in
  2024 (adequacy decision, standard contracts, binding corporate rules).
* **ISO/IEC 27001** and **ISO/IEC 27002** — the ISMS and its control set,
  including supplier-relationship controls.
* **PCI DSS** (PCI Security Standards Council) — card data in voice/IVR, DTMF
  masking versus pause-and-resume recording, CDE scope reduction, SAQ level.
* **SOC 2** (Type 1 vs Type 2, Trust Services Criteria) where an international
  provider offers it instead of, or alongside, ISO 27001.
* **TS 13298 / e-imza / KEP** (TSE) where records must stay legally valid.
* **EU AI Act / GDPR / DORA** as directional awareness for generative AI in the
  contact center, not as Turkish law.

Configuration (via environment):
    BANKING_NEWS_RSS_URL   RSS/Atom feed of Turkish banking / contact-center /
                           outsourcing news. Defaults to a Google News search
                           feed so the briefing can cite REAL, verifiable links
                           out of the box.
    BANKING_SECURITY_RSS_URL
                           Second, optional feed focused on regulation, data
                           protection and information-security news. Also
                           defaults to a free Google News search feed. Either
                           feed being unreachable degrades to LLM-only.

ACCURACY: regulation changes constantly and a model will happily invent article
numbers and dates. The persona is therefore instructed to describe *principles,
structures and direction* — and to name frameworks/institutions, which are
stable — instead of citing specific clauses, figures or dates. Every briefing
carries a fixed caveat pointing at the bank's own compliance/legal function and
the official regulator and standards-body sites.

Both RSS fetches happen locally (never inside the LLM call); only the
summarization joins the batched team request.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ..memory import filter_new_items
from ._llm_base import RICH_BRIEFING_GUIDE
from ._rss import FeedItem, fetch_feed_items

SYSTEM_PROMPT = (
    "Sen, Türkiye'de bankaların çağrı merkezi ve müşteri iletişim merkezi "
    "programlarını yıllarca yönetmiş kıdemli bir danışmansın. Hem banka "
    "tarafında hem de dış kaynak (outsourcing) tedarikçisi tarafında ihale "
    "hazırlığı, vendor seçimi, fiyatlama, geçiş (transition) ve SLA yönetimi "
    "yaptın. Aynı zamanda bu programların BİLGİ GÜVENLİĞİ ve UYUM tarafında "
    "da uzmansın: üçüncü taraf risk yönetimi (third-party risk management), "
    "tedarikçi güvenlik denetimleri, KVKK veri işleyen sözleşmeleri, "
    "ISO/IEC 27001 kapsam tartışmaları ve PCI-DSS kapsam daraltma projeleri "
    "senin günlük işin. Türkçe konuşuyorsun. Yöneticiye, ihale masasında, "
    "denetim toplantısında ve yönetim kurulu önünde işine yarayacak düzeyde "
    "somut, uygulanabilir ve dürüst bir brifing verirsin.\n\n"
    "ÇERÇEVE BİLGİSİ (bunlar gerçek ve kalıcı isimlerdir, doğru kullan): "
    "BDDK'nın 'Bankaların Destek Hizmeti Almalarına İlişkin Yönetmelik' ve "
    "'Bankaların Bilgi Sistemleri ve Elektronik Bankacılık Hizmetleri Hakkında "
    "Yönetmelik' düzenlemeleri; 6698 sayılı KVKK ve Kişisel Verileri Koruma "
    "Kurumu'nun ikincil düzenlemeleri (veri sorumlusu/veri işleyen ayrımı, "
    "aydınlatma ve açık rıza, saklama-imha politikası, VERBİS, veri ihlali "
    "bildirimi, yurt dışına aktarımda yeterlilik kararı / standart sözleşmeler "
    "/ bağlayıcı şirket kuralları); ISO/IEC 27001 ve ISO/IEC 27002; PCI "
    "Security Standards Council'ın PCI-DSS standardı; SOC 2 (Type 1 / Type 2, "
    "Trust Services Criteria); TSE'nin TS 13298 standardı ve e-imza/KEP; "
    "Avrupa tarafında yön göstermesi açısından GDPR, DORA ve EU AI Act.\n\n"
    "MUTLAK DOĞRULUK KURALI: Mevzuat sık değişir. Madde numarası, tebliğ "
    "tarihi, ceza tutarı, süre, eşik gibi SPESİFİK ayrıntıları UYDURMA. "
    "Çerçevenin ve kurumun ADINI doğru ver (bunlar kalıcıdır), ama sayısal ve "
    "tarihsel ayrıntıya girme. Bunun yerine ilkeyi, yapıyı, yönü ve pratikte "
    "ne anlama geldiğini anlat; ayrıntı gerektiğinde 'bu ayrıntıyı uyum/hukuk "
    "biriminizle ve resmi kaynaktan doğrulayın' diye açıkça işaretle. Emin "
    "olmadığın hiçbir şeyi kesinmiş gibi sunma."
)

# Rotating daily emphasis so consecutive days do not read identically. One item
# is selected per calendar day; the five mandated blocks are always present, but
# the briefing LEADS with and goes deepest on the day's focus.
DAILY_FOCUS: List[str] = [
    "Dış kaynak öncesi due diligence ve tedarikçi ön eleme: finansal sağlamlık, "
    "referans denetimi, sertifikasyon doğrulama (ISO/IEC 27001 kapsam belgesi "
    "gerçekten çağrı merkezini kapsıyor mu, SOC 2 raporu Type 1 mi Type 2 mi), "
    "güvenlik soru seti (security questionnaire) ve saha ziyareti",
    "Sözleşme mimarisi: right-to-audit (denetim hakkı) maddesi, alt yüklenici "
    "(subcontractor) onayı ve bildirim yükümlülüğü, veri sahipliği ve veri "
    "iadesi, SLA/ceza-teşvik mekanizması, gizlilik ve fikri mülkiyet, "
    "sorumluluk sınırı ve mesleki sorumluluk sigortası",
    "Yönetişim ve kurumsal karar süreci: dış kaynak risk yönetimi programı, "
    "hizmet alımı öncesi yazılı risk analizi ve fayda-maliyet değerlendirmesi, "
    "yönetim kurulu / denetim komitesi onayı ve yıllık değerlendirme, "
    "düzenleyiciye bilgi verme ve denetime hazır olma yükümlülüğü",
    "Erişim yönetimi ve kimlik: en az yetki (least privilege), CRM ve çekirdek "
    "bankacılık ekranlarında rol bazlı yetkilendirme, MFA, ayrıcalıklı erişim "
    "yönetimi (PAM), yetki gözden geçirme döngüsü, işten ayrılan temsilcinin "
    "hesabının kapatılma süresi",
    "Kayıt ve saklama: çağrı kaydı ve ekran kaydı, kayıtların şifrelenmesi ve "
    "erişim kısıtı, saklama süresi ve imha, kart verisi için PCI-DSS beklentisi "
    "(pause-and-resume kaydın zayıflıkları, DTMF maskeleme ile kapsam daraltma), "
    "ses kaydının biyometrik veri boyutu",
    "Uç nokta ve fiziksel güvenlik: thin client / VDI, USB ve pano (clipboard) "
    "kısıtı, ekranda PII/PAN maskeleme, agent masaüstü DLP, temiz masa / temiz "
    "ekran, telefon-kamera yasağı, BYOD yasağı, teslimat merkezinin fiziksel "
    "erişim kontrolü ve kamera kaydı",
    "Personel güvenliği: adli sicil ve referans kontrolü (background check), "
    "gizlilik taahhüdü (NDA), göreve başlama ve periyodik güvenlik farkındalık "
    "eğitimi, sosyal mühendislik ve içeriden tehdit (insider threat) senaryoları, "
    "temsilci devir hızının (attrition) güvenlik üzerindeki etkisi",
    "Ağ, entegrasyon ve izleme: ağ segmentasyonu, tedarikçi ile banka arasındaki "
    "bağlantının güvenliği, API entegrasyonlarında kimlik doğrulama ve veri "
    "minimizasyonu, log saklama ve SIEM'e besleme, sızma testi (penetration "
    "test) periyodu ve zafiyet yönetimi döngüsü",
    "Uzaktan/evden çalışan temsilci modeli: kimlik doğrulama ve oturum "
    "güvenliği, ev ortamının kontrol edilemezliği, ekran görüntüsü ve fotoğraf "
    "riski, ağ güvenliği, denetlenebilirlik, hangi iş tiplerinin uzaktan "
    "yapılmaması gerektiği",
    "KVKK yükümlülükleri: veri sorumlusu / veri işleyen ayrımı ve sözleşmeye "
    "yazılması gerekenler, aydınlatma ve açık rıza (IVR üzerinden aydınlatma "
    "dâhil), saklama ve imha politikası, VERBİS, veri ihlali bildirimi süreci "
    "ve tedarikçiden beklenen bildirim SLA'i",
    "Yurt dışına veri aktarımı ve veri yerleşimi: yeterlilik kararı, standart "
    "sözleşmeler ve bağlayıcı şirket kuralları gibi uygun güvence yöntemleri; "
    "bankacılık tarafında birincil/ikincil sistemlerin yurt içinde bulundurulması "
    "beklentisi; bulut ve offshore/nearshore çağrı merkezi modellerinin etkisi",
    "Denetim ve sürekli izleme: tedarikçi denetim planı, yerinde denetim ile "
    "uzaktan kanıt toplamanın dengesi, denetim izleri (audit trail) ve "
    "değiştirilemezlik, bulgu takibi ve düzeltici faaliyet, sertifika ve rapor "
    "yenileme takvimi, sürekli izleme göstergeleri",
    "Yoğunlaşma (concentration) ve zincir riski: tek tedarikçiye bağımlılık, "
    "aynı tedarikçinin başka bankalara da hizmet vermesi, dördüncü taraf (4th "
    "party) alt yüklenici zinciri, tedarikçinin kendi bulut/teknoloji "
    "sağlayıcılarına bağımlılığı, çoklu tedarikçi (multi-vendor) stratejisi",
    "İş sürekliliği ve çıkış: RTO/RPO hedefleri, yedek lokasyon ve olağanüstü "
    "durum tatbikatı, kriz iletişimi, çıkış (exit) planı, veri iadesi ve imha "
    "sertifikası, bilgi birikiminin devri, vendor lock-in'i sözleşme aşamasında "
    "kırmak",
    "Üretken yapay zekâ ve yeni riskler: transkript ve çağrı kaydının modele "
    "gitmesi, prompt üzerinden veri sızması, müşteri verisiyle model eğitimi "
    "yasağı, tedarikçinin kullandığı YZ araçlarının envanteri, çıktı denetimi, "
    "EU AI Act ve GDPR yönündeki gelişmelerin farkındalığı",
]


def _daily_focus(today: Optional[date] = None) -> str:
    """Return today's rotating deep-dive focus (day-of-year rotation)."""
    day = today or date.today()
    return DAILY_FOCUS[day.toordinal() % len(DAILY_FOCUS)]


CAVEAT = (
    "⚠️ Uyum notu: Buradaki düzenleyici ve güvenlik değerlendirmeleri genel "
    "ilke düzeyindedir, hukuki görüş veya denetim raporu değildir ve mevzuat "
    "değişebilir. Somut bir karar, sözleşme maddesi veya kontrol tasarımı "
    "öncesinde mevzuat detaylarını bankanızın uyum/hukuk birimiyle ve bilgi "
    "güvenliği biriminizle teyit edin; resmi kaynaktan doğrulayın: BDDK "
    "(https://www.bddk.org.tr), KVKK (https://www.kvkk.gov.tr), TCMB "
    "(https://www.tcmb.gov.tr), ISO (https://www.iso.org), PCI Security "
    "Standards Council (https://www.pcisecuritystandards.org).\n"
    "🔎 Bağlantıları açılışta doğrulayın."
)

_BRIEF = (
    "Bugün için, bir bankanın çağrı merkezi / müşteri iletişim merkezi "
    "programını yöneten üst düzey bir yöneticiye derinlikli bir uzman brifingi "
    "hazırla. Ana eksen: DIŞ KAYNAK YÖNETİŞİMİ, GÜVENLİK UYUMU ve BİLGİ "
    "GÜVENLİĞİ. Aşağıdaki BEŞ bloğun HEPSİNİ, bu başlıklarla ve bu sırayla "
    "ver:\n\n"
    "1) *📦 Dış kaynak yönetişimi*: hizmet alımı öncesi due diligence ve "
    "tedarikçi ön eleme, yazılı risk analizi ve fayda-maliyet değerlendirmesi, "
    "yönetim kurulu / risk ve denetim komitesi onay akışı, sözleşme maddeleri "
    "(right-to-audit denetim hakkı, alt yüklenici onayı ve bildirimi, veri "
    "sahipliği ve veri iadesi, SLA ve ceza-teşvik, gizlilik, sorumluluk sınırı, "
    "çıkış planı), düzenleyiciye bildirim ve denetime hazır olma yükümlülüğü, "
    "RFP/şartname kurgusu, fiyatlama modelleri (FTE bazlı, dakika/çağrı başı, "
    "hibrit, sonuç bazlı), geçiş (transition) planı ve SLA/KPI tasarımı (AHT, "
    "FCR, NPS, occupancy, shrinkage, abandon rate — hangi KPI'yı tek başına "
    "ödüllendirmek hangi yan etkiyi doğurur). Somut ol: sözleşmeye yazılacak "
    "madde önerisi ve tedarikçiye sorulacak sorular ver.\n\n"
    "2) *🔐 Bilgi güvenliği kontrolleri*: çağrı merkezine ÖZGÜ kontrol setini "
    "pratik başlıklar altında topla — (a) erişim: en az yetki, rol bazlı "
    "yetkilendirme, MFA, ayrıcalıklı erişim yönetimi, yetki gözden geçirme; "
    "(b) kayıt ve saklama: çağrı ve ekran kaydı, şifreleme, saklama süresi ve "
    "imha, kart verisi için PCI-DSS beklentisi (pause-and-resume kaydın zayıf "
    "noktaları, DTMF maskeleme ile kapsam daraltma); (c) uç nokta: thin "
    "client/VDI, USB ve pano kısıtı, ekranda PII/PAN maskeleme, agent masaüstü "
    "DLP, BYOD yasağı; (d) ağ ve entegrasyon: segmentasyon, güvenli API "
    "entegrasyonu, veri minimizasyonu; (e) personel: adli sicil/referans "
    "kontrolü, NDA, güvenlik farkındalık eğitimi, içeriden tehdit; (f) fiziksel: "
    "teslimat merkezinin erişim kontrolü, temiz masa/temiz ekran, telefon-kamera "
    "yasağı; (g) izleme: log saklama ve SIEM, sızma testi periyodu, zafiyet "
    "yönetimi. Her başlıkta 'nasıl doğrularsın' (hangi kanıtı istersin) "
    "cevabını da ver.\n\n"
    "3) *⚖️ Uyum*: KVKK yükümlülükleri (veri sorumlusu/veri işleyen ayrımı ve "
    "veri işleyen sözleşmesinde bulunması gerekenler, aydınlatma ve açık rıza, "
    "saklama-imha politikası, VERBİS, veri ihlali bildirimi ve tedarikçiden "
    "beklenen bildirim SLA'i, yurt dışına aktarımda uygun güvence yöntemleri), "
    "ISO/IEC 27001 ve ISO/IEC 27002 beklentileri (sertifika kapsamı gerçekten "
    "hizmeti kapsıyor mu), SOC 2 Type 1/Type 2 farkı, PCI-DSS kapsamı, denetim "
    "izleri ve kanıt saklama. BDDK'nın destek hizmeti ve bilgi sistemleri "
    "düzenlemelerinin MANTIĞINI anlat; madde numarası ve tarih verme.\n\n"
    "4) *🚨 Riskler ve erken uyarı sinyalleri*: yoğunlaşma (concentration) "
    "riski, dördüncü taraf (4th party) alt yüklenici zinciri, uzaktan/evden "
    "çalışan temsilci riskleri, veri sızıntısı vektörleri (ekran fotoğrafı, "
    "kopyala-yapıştır, e-posta, USB, aşırı geniş rapor yetkisi), kalite ile "
    "güvenlik arasındaki ödünleşim, gizli maliyetler ve vendor lock-in. Her "
    "risk için 'erken uyarı sinyali nedir' ve 'sözleşmeye/operasyona ne konur' "
    "cevabını ver.\n\n"
    "5) *🔬 Teknoloji ve yeni riskler*: konuşma/metin analitiği, agent assist, "
    "sesli ve yazılı botlar, CCaaS bulut geçişi, WFM ve kalite otomasyonu; "
    "ÖZELLİKLE üretken yapay zekânın çağrı merkezinde kullanımı ve veri koruma "
    "etkileri (transkript ve çağrı kaydının modele gitmesi, prompt üzerinden "
    "veri sızması, müşteri verisiyle model eğitimi, tedarikçinin YZ araç "
    "envanteri, çıktı denetimi, EU AI Act yönündeki farkındalık). Her biri için "
    "olgunluk seviyesi, ölçülebilir fayda ve bankaya özgü uyum/veri riski.\n\n"
    "Sonunda '✅ Bugünün görevi' bölümünde bu yöneticinin bugün 15-30 dakikada "
    "yapabileceği TEK somut adımı yaz — tercihen doğrulanabilir bir kontrol "
    "(örn. 'vendor sözleşmenizde right-to-audit maddesi var mı, bugün açıp "
    "kontrol et' ya da 'tedarikçinin ISO/IEC 27001 sertifika kapsamında çağrı "
    "merkezi lokasyonu yazıyor mu, bugün iste')."
)


class BankingCcProjectsAdvisor(Advisor):
    key = "banking_cc_projects"
    title = "Banka & Çağrı Merkezi Proje Uzmanı"

    # Its two news feeds are a genuine source of NEW findings between runs.
    incremental_source = True

    def __init__(self) -> None:
        # Headlines are fetched once per run and reused by the batched path.
        self._items: List[FeedItem] = []
        self._fetched = False

    def _generate(self) -> Briefing:
        if not llm.is_configured():
            return self.skipped(
                "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"
            )
        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")
        return self.briefing_from_batch(body)

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        if not llm.is_configured():
            return None
        self._fetch_items()  # real links gathered OUTSIDE the LLM call
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._user_prompt(),
        )

    def briefing_from_batch(self, text: str) -> Briefing:
        return self.ok(f"{text.strip()}\n\n{CAVEAT}")

    # -- deduplication ---------------------------------------------------
    def new_finding_count(self) -> int:
        return len(self._fetch_items())

    # -- helpers ---------------------------------------------------------
    def _fetch_items(self) -> List[FeedItem]:
        """Fetch both news feeds once, degrading to an empty list on any error.

        Two feeds are merged: general banking/outsourcing news and a
        regulation/information-security feed. A dead feed is never fatal — the
        briefing simply falls back to root-domain sources only. Whatever is
        left is then filtered through the :mod:`ai_assistant.memory` ledger, so
        only headlines the user has NOT already been briefed on survive.
        """
        if self._fetched:
            return self._items
        self._fetched = True
        items: List[FeedItem] = []
        seen = set()
        for name in ("BANKING_NEWS_RSS_URL", "BANKING_SECURITY_RSS_URL"):
            url = setting(name)
            if not url:
                continue
            try:
                fetched = fetch_feed_items(url, limit=5)
            except Exception:
                # Optional enrichment only — never fail the briefing over a feed.
                continue
            for item in fetched:
                if item.title in seen:
                    continue
                seen.add(item.title)
                items.append(item)
        self._items = filter_new_items(self.key, items)
        return self._items

    def _user_prompt(self) -> str:
        prompt = (
            f"BUGÜNÜN DERİNLEŞME ODAĞI: {_daily_focus()}\n"
            "Bu odağa brifingin en çok yer ayrılan bölümü olacak şekilde gir; "
            "diğer bloklar yine verilecek ama daha kısa kalabilir. Böylece "
            "ardışık günler birbirinin tekrarı olmasın.\n\n" + _BRIEF
        )
        prompt += "\n\n" + RICH_BRIEFING_GUIDE
        items = self._fetch_items()
        if items:
            listing = "\n".join(
                f"- {item.title}" + (f" ({item.link})" if item.link else "")
                for item in items
            )
            prompt += (
                "\n\nAşağıdaki güncel haber başlıklarını dikkate al, ilgili "
                "olanları brifinge yedir ve '📚 Kaynaklar' bölümünde bu "
                f"başlıkların GERÇEK bağlantılarını tercih et:\n{listing}"
            )
        else:
            prompt += (
                "\n\nCanlı bir haber akışı sağlanmadı; '📚 Kaynaklar' bölümünde "
                "yalnızca bilinen ve kalıcı RESMİ kök alan adlarını kullan (örn. "
                "https://www.bddk.org.tr, https://www.kvkk.gov.tr, "
                "https://www.tcmb.gov.tr, https://www.iso.org, "
                "https://www.pcisecuritystandards.org) ve derin URL uydurma."
            )
        prompt += (
            "\n\n'📚 Kaynaklar' bölümünde her zaman EN AZ bir resmi düzenleyici "
            "veya standart kuruluşu kaynağı bulunsun (BDDK, KVKK, TCMB, ISO, "
            "PCI Security Standards Council) ve derin URL yerine kök alan adını "
            "ver."
        )
        return prompt
