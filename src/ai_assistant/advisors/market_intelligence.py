"""Market intelligence advisor — Pazar İstihbaratı (PHASE 1B consolidation).

Folds FOUR previously separate market-facing personas into ONE briefing
produced by a SINGLE LLM call:

* :mod:`~ai_assistant.advisors.sector_intel` — sektör teknoloji/YZ gelişmeleri
  ve rakip ortamı, fed by ``SECTOR_NEWS_RSS_URL``.
* :mod:`~ai_assistant.advisors.ai_news` — yapay zekâ dünyasındaki güncel
  gelişmeler, fed by ``AI_NEWS_RSS_URL``.
* :mod:`~ai_assistant.advisors.cx_research` — kanıta dayalı müşteri deneyimi
  araştırması, fed by ``CX_RESEARCH_RSS_URL``, with its day-of-year focus
  rotation kept intact.
* :mod:`~ai_assistant.advisors.banking_cc_projects` — banka çağrı merkezi
  ("CC" = *contact center*) dış kaynak yönetişimi, bilgi güvenliği ve uyum,
  fed by ``BANKING_NEWS_RSS_URL`` **and** ``BANKING_SECURITY_RSS_URL``, also
  with its own day-of-year focus rotation.

WHY ONE CALL. All four personas answer the same question — "what moved in my
market today and what should I do about it?" — from four angles. As four
batched sections they each re-stated their own framing and their own accuracy
rules. They are now one persona with four clearly headed subsections: a 4 → 1
reduction in batch sections, roughly a QUARTER off the input bytes this domain
costs (~13.5 KB of persona + brief down to ~10 KB, guide excluded) and — the
bigger win — ONE briefing's worth of output instead of four, since the
300-500-word writing contract now applies once rather than four times.

WHAT IS PRESERVED (deliberately, item by item):

* ALL FIVE RSS feeds. Nothing was dropped; the five feeds are fetched, merged
  and de-duplicated by title into one pool, then filtered through the
  :mod:`ai_assistant.memory` ledger so the extra daily runs only discuss items
  the user has NOT already been shown. Headlines are handed to the model
  GROUPED BY ORIGIN, so it still knows which subsection an item belongs to.
* The CX researcher's EVIDENCE DISCIPLINE — a figure only appears when its
  source organisation can be named next to it, "bilinmiyor" is an acceptable
  answer, and anything repeatable in a meeting is flagged "(doğrulayın)".
* The banking expert's ABSOLUTE ACCURACY RULE — name the framework/institution
  (those are stable), never invent article numbers, dates, thresholds or fines.
* Both DAILY FOCUS rotations (CX research and banking governance), so
  consecutive days never read alike and the whole ground is covered over time
  with no stored state.
* Every caveat: the sector "not real-time", the CX evidence note and the
  banking compliance note all still close the briefing.

Configuration (via environment):
    USER_SECTOR               Sector analysed by the first two subsections
                              (default "banka çağrı merkezleri").
    SECTOR_NEWS_RSS_URL       Sector & competitor news feed.
    AI_NEWS_RSS_URL           AI/ML news feed.
    CX_RESEARCH_RSS_URL       Customer-experience / contact-center research feed.
    BANKING_NEWS_RSS_URL      Banking / outsourcing news feed.
    BANKING_SECURITY_RSS_URL  Regulation / information-security news feed.

All five fetches happen locally, never inside the LLM call; only the writing
joins the batched team request. With no LLM provider key the advisor falls back
to a plain Turkish headline list when any feed produced items, and is
``skipped`` when it did not.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional, Sequence, Tuple

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ..memory import filter_new_items
from ._llm_base import RICH_BRIEFING_GUIDE
from ._rss import FeedItem, fetch_feed_items

DEFAULT_SECTOR = "banka çağrı merkezleri"

#: The subsection headings the model MUST emit, in this order. Exported so the
#: report renderer can split one consolidated briefing back into four blocks.
SECTION_HEADINGS = (
    "## 📊 Sektör İstihbaratı & Rakip Ortamı",
    "## 🤖 Yapay Zekâ Haberleri",
    "## 🎧 Müşteri Deneyimi Araştırması",
    "## 🏦 Bankacılık & Çağrı Merkezi Projeleri (Uyum & Güvenlik)",
)

#: ``(setting name, feed label, item limit)`` for every feed folded in here.
#: The label is what the model sees above that feed's headlines, which is how a
#: merged pool still routes to the right subsection.
FEEDS: Tuple[Tuple[str, str, int], ...] = (
    ("SECTOR_NEWS_RSS_URL", "Sektör & rakip haberleri", 6),
    ("AI_NEWS_RSS_URL", "Yapay zekâ haberleri", 8),
    ("CX_RESEARCH_RSS_URL", "Müşteri deneyimi / çağrı merkezi araştırması", 8),
    ("BANKING_NEWS_RSS_URL", "Bankacılık & dış kaynak haberleri", 5),
    ("BANKING_SECURITY_RSS_URL", "Düzenleme & bilgi güvenliği haberleri", 5),
)

# --- Rotating daily focus, carried over from cx_research -------------------
# One focus per day (day-of-year rotation). The CX subsection always carries
# its mandated blocks, but the day's focus is where the depth goes.
CX_DAILY_FOCUS: List[str] = [
    "Yeni trendler: müşteri beklentilerinin yönü, kanal tercihlerindeki "
    "kayma, self servis ile insan temsilci dengesi, proaktif hizmet",
    "Yeni uygulamalar ve teknolojiler: konuşma analitiği, agent assist, sesli "
    "ve yazılı botlar, CCaaS, WFM ve otomatik kalite yönetimi — hangi olgunluk "
    "seviyesinde, hangi ölçülebilir etkiyle",
    "Akademik araştırma: hizmet kalitesi ve memnuniyet literatürünün temel "
    "çizgileri (SERVQUAL, beklenti-onaylanmama modeli, hizmet telafisi "
    "paradoksu), bulguların sınırları ve tartışmalı yanları",
    "Sektörel araştırma ve raporlar: araştırma kuruluşlarının düzenli olarak "
    "ölçtüğü göstergeler, metodolojilerinin farkı ve rakamları okurken "
    "dikkat edilmesi gerekenler",
    "Başarı hikâyeleri ve vaka çalışmaları: ne yapıldı, hangi metrik ne kadar "
    "değişti, hangi sürede, hangi koşullarda tekrarlanabilir — kanıt zinciriyle",
    "Ölçüm metodolojisi: NPS, CSAT ve CES'in ne ölçtüğü, ne ölçmediği, örneklem "
    "ve zamanlama hataları, anket yorgunluğu, açık uçlu yanıtların kodlanması",
    "Müşteri yolculuğu haritalama: gerçek veriyle harita çıkarmak, acı "
    "noktalarını kanıtla tespit etmek, kanal geçişlerindeki kopmalar ve "
    "'sessiz başarısızlık' anları",
    "Churn (kayıp) tahmini: hangi sinyaller erken uyarı verir, model kurmadan "
    "önce hangi veri hijyeni gerekir, tahmini eyleme çevirmenin operasyonel "
    "tasarımı ve müdahale etiği",
    "VoC (müşterinin sesi) programları: geri bildirimin toplanması, "
    "önceliklendirilmesi, kapalı döngü (closed-loop) geri dönüş ve programın "
    "gerçekten değişiklik üretip üretmediğinin kanıtı",
    "İlk temasta çözüm (FCR) ve tekrar temas: doğru tanım, ölçüm tuzakları, "
    "kök neden analizi ve FCR'ı tek başına ödüllendirmenin yan etkileri",
    "Müşteri eforunu azaltmak: efor kaynaklarının haritası, kanal geçişini "
    "önlemek, temsilciye yetki devri, 'bir sonraki sorunu şimdiden çözmek'",
    "Tutundurma ve sadakat programları: hangi tasarımlar davranış değiştirir, "
    "indirim tuzağı, kayıp müşteriyi geri kazanma, sadakat ile memnuniyetin "
    "aynı şey olmaması",
    "Personel deneyimi ile müşteri deneyimi ilişkisi: hizmet-kâr zinciri "
    "mantığı, temsilci devir hızının müşteriye yansıması, koçluk ve geri "
    "bildirim kalitesi, tükenmişlik sinyalleri",
    "Şikâyet yönetimi ve hizmet telafisi: adalet algısının üç boyutu "
    "(sonuç, süreç, etkileşim), telafinin dozu, özrün dili ve telafi sonrası "
    "sadakatin ne kadar geri geldiğine dair kanıt",
]

# --- Rotating daily focus, carried over from banking_cc_projects -----------
# Same idea for the outsourcing-governance subsection: the mandated blocks are
# always present, but the briefing goes deepest on the day's focus.
BANKING_DAILY_FOCUS: List[str] = [
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

# Research bodies whose ROOT domains are stable enough to cite without a link
# (carried over from the CX researcher).
STABLE_RESEARCH_SOURCES = (
    "Gartner (https://www.gartner.com), Forrester (https://www.forrester.com), "
    "McKinsey (https://www.mckinsey.com), Harvard Business Review "
    "(https://hbr.org), CCW (https://www.customercontactweekdigital.com), "
    "ICMI (https://www.icmi.com), Qualtrics XM Institute "
    "(https://www.qualtrics.com/xm-institute)"
)

# Regulators and standards bodies whose ROOT domains are stable (carried over
# from the banking project expert).
OFFICIAL_SOURCES = (
    "BDDK (https://www.bddk.org.tr), KVKK (https://www.kvkk.gov.tr), "
    "TCMB (https://www.tcmb.gov.tr), ISO (https://www.iso.org), "
    "PCI Security Standards Council (https://www.pcisecuritystandards.org)"
)

# AI sources whose ROOT domains are stable (carried over from the AI news desk).
STABLE_AI_SOURCES = (
    "https://ai.googleblog.com, https://openai.com/blog, "
    "https://huggingface.co, https://arxiv.org"
)


def _cx_focus(today: Optional[date] = None) -> str:
    """Today's rotating CX research focus (day-of-year rotation)."""
    day = today or date.today()
    return CX_DAILY_FOCUS[day.toordinal() % len(CX_DAILY_FOCUS)]


def _banking_focus(today: Optional[date] = None) -> str:
    """Today's rotating outsourcing-governance focus (day-of-year rotation)."""
    day = today or date.today()
    return BANKING_DAILY_FOCUS[day.toordinal() % len(BANKING_DAILY_FOCUS)]


SYSTEM_PROMPT = (
    "Sen kıdemli bir pazar istihbaratı analistisin ve aynı anda DÖRT uzmanlığı "
    "birden taşıyorsun: (1) sektör ve rekabet istihbaratı analisti, (2) yapay "
    "zeka teknolojileri editörü, (3) kanıta dayalı çalışan müşteri deneyimi / "
    "çağrı merkezi araştırmacısı, (4) banka çağrı merkezi programlarını hem "
    "banka hem tedarikçi tarafında yönetmiş, bilgi güvenliği ve uyum "
    "denetimlerinden geçmiş kıdemli danışman. Türkçe konuşuyorsun. Her alt "
    "bölümde o uzmanın sesine geçersin; bölümler birbirini tekrar etmez.\n\n"
    "ÇERÇEVE ADLARI (kalıcıdır, doğru kullan): BDDK destek hizmeti ve bilgi "
    "sistemleri yönetmelikleri; 6698 sayılı KVKK ve KVKK Kurumu ikincil "
    "düzenlemeleri; ISO/IEC 27001-27002; PCI-DSS; SOC 2 (Type 1/2); TS 13298 "
    "ve e-imza/KEP; GDPR, DORA, EU AI Act.\n\n"
    "KANIT DİSİPLİNİ (mutlak): Rakam veya vaka sonucunu ancak kaynağının adını "
    "yanına yazabiliyorsan ver; yazamıyorsan rakam verme, mekanizmayı anlat. "
    "Şirket adı, tarih, yüzde ASLA uydurma. Doğrulanacak ifadeyi "
    "'(doğrulayın)' ile işaretle; 'bilinmiyor' geçerli bir cevaptır.\n\n"
    "MEVZUAT DOĞRULUĞU (mutlak): Madde numarası, tebliğ tarihi, ceza tutarı, "
    "süre ve eşik UYDURMA. Kurumun/çerçevenin adını doğru ver, ilkeyi ve "
    "pratik anlamını anlat, ayrıntı gerekince 'uyum/hukuk biriminizden "
    "doğrulayın' de.\n\n"
    "Sana canlı bir haber akışı verildiyse GERÇEK maddeleri tercih et; "
    "uydurma bağlantı verme. Analitik, dengeli ve somut ol; abartıdan ve "
    "moda sözcüklerden kaçın."
)

CAVEAT = (
    "📌 Kanıt notu: Buradaki rakamlar ve vaka sonuçları, yanında adı geçen "
    "kaynağa aittir; metodolojileri ve tarihleri farklılık gösterebilir. Bir "
    "toplantıda kullanmadan önce rakamı kaynağının kendi sayfasından teyit "
    "edin. Sayısal veriler gerçek zamanlı değildir.\n"
    "⚠️ Uyum notu: Düzenleyici ve güvenlik değerlendirmeleri genel ilke "
    "düzeyindedir; hukuki görüş veya denetim raporu değildir ve mevzuat "
    "değişebilir. Somut bir karar, sözleşme maddesi veya kontrol tasarımı "
    f"öncesinde bankanızın uyum/hukuk ve bilgi güvenliği birimleriyle ve resmi "
    f"kaynaktan doğrulayın: {OFFICIAL_SOURCES}.\n"
    "🔎 Bağlantıları açılışta doğrulayın."
)


class MarketIntelligenceAdvisor(Advisor):
    key = "market_intelligence"
    title = "Pazar İstihbaratı (Sektör · YZ · CX · Bankacılık)"

    # Five news/research feeds: a genuine source of NEW findings between two
    # runs on the same day.
    incremental_source = True

    def __init__(self) -> None:
        # Fetched once per run and reused by the batched path.
        self._groups: List[Tuple[str, List[FeedItem]]] = []
        self._items: List[FeedItem] = []
        self._fetched = False

    def _generate(self) -> Briefing:
        items = self._fetch_items()

        if not llm.is_configured():
            if items:
                # Real headlines beat an empty section.
                return self.ok(f"{self._headline_list()}\n\n{CAVEAT}")
            return self.skipped("missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY")

        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception as exc:
            if items:
                return self.ok(f"{self._headline_list()}\n\n{CAVEAT}")
            return self.failed(f"LLM isteği başarısız: {exc}")

        return self.briefing_from_batch(body)

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        """ONE section for what used to be four separate batched sections."""
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
        """Fetch all five feeds once, keeping only NOT-YET-REPORTED items.

        The feeds are merged into ONE pool so an article syndicated to two of
        them is discussed once, but the per-feed grouping is preserved for the
        prompt: the model needs to know whether a headline arrived from the
        sector desk or from the regulation desk. A dead feed is never fatal —
        this is optional enrichment and the briefing falls back to root-domain
        sources only.
        """
        if self._fetched:
            return self._items
        self._fetched = True

        collected: List[Tuple[str, List[FeedItem]]] = []
        pool: List[FeedItem] = []
        seen = set()
        for name, label, limit in FEEDS:
            url = setting(name)
            if not url:
                continue
            try:
                fetched = fetch_feed_items(url, limit=limit)
            except Exception:
                # Optional enrichment only — never fail the briefing over a feed.
                continue
            group: List[FeedItem] = []
            for item in fetched:
                if item.title in seen:
                    continue  # same story from two feeds: keep it once
                seen.add(item.title)
                group.append(item)
                pool.append(item)
            if group:
                collected.append((label, group))

        # ONE ledger entry for the consolidated advisor, so an item reported
        # this morning is not re-reported this afternoon.
        self._items = filter_new_items(self.key, pool)
        fresh = {id(item) for item in self._items}
        self._groups = [
            (label, [item for item in group if id(item) in fresh])
            for label, group in collected
        ]
        self._groups = [(label, group) for label, group in self._groups if group]
        return self._items

    @staticmethod
    def _format(items: Sequence[FeedItem]) -> str:
        return "\n".join(
            f"- {item.title}" + (f" ({item.link})" if item.link else "")
            for item in items
        )

    def _headline_list(self) -> str:
        """The no-LLM fallback: today's new headlines, grouped by source."""
        blocks = [f"*{label}*\n{self._format(group)}" for label, group in self._groups]
        return "Bugünün yeni başlıkları:\n\n" + "\n\n".join(blocks)

    def _feed_block(self) -> str:
        """The grouped headline listing handed to the model, or the fallback."""
        if not self._groups:
            return (
                "\n\nBugün canlı bir haber akışı yok. '📚 Kaynaklar' bölümünde "
                "yalnızca bilinen ve KALICI kök alan adlarını kullan "
                f"(araştırma: {STABLE_RESEARCH_SOURCES}; yapay zeka: "
                f"{STABLE_AI_SOURCES}; resmî: {OFFICIAL_SOURCES}), derin URL "
                "uydurma ve kaynağını veremediğin rakamı hiç verme."
            )
        blocks = "\n\n".join(
            f"[{label}]\n{self._format(group)}" for label, group in self._groups
        )
        return (
            "\n\nAşağıdaki başlıklar BUGÜN İLK KEZ geliyor ve KAYNAK AKIŞINA "
            "GÖRE gruplanmıştır. Her başlığı ilgili alt bölüme yedir, "
            "önceliklendir ve '📚 Kaynaklar' bölümünde bu GERÇEK bağlantıları "
            "tercih et. Bir başlığın içeriğinden emin değilsen yorumunu "
            f"'(başlığa göre, doğrulayın)' diye işaretle:\n\n{blocks}"
        )

    def _user_prompt(self) -> str:
        sector = setting("USER_SECTOR") or DEFAULT_SECTOR

        prompt = (
            f"KULLANICININ ALANI: {sector} (üst düzey yönetici).\n"
            f"BUGÜNÜN CX ARAŞTIRMA ODAĞI: {_cx_focus()}\n"
            f"BUGÜNÜN DIŞ KAYNAK/UYUM ODAĞI: {_banking_focus()}\n\n"
            "Bugün için TEK bir pazar istihbaratı brifingi yaz. Brifing DÖRT "
            "alt bölümden oluşacak; alt başlıkları AYNEN aşağıdaki gibi, bu "
            "sırayla ve bu yazımla ver (rapor bu başlıklardan bölünüyor):\n"
            + "\n".join(SECTION_HEADINGS)
            + "\n\n"
            "Alt bölümlerin içeriği:\n\n"
            f"{SECTION_HEADINGS[0]}\n"
            "Sektör ve rekabet istihbaratı: (a) teknoloji/YZ gelişmesi — "
            "kullanım senaryosu, olgunluk, ölçülebilir fayda; (b) rakip "
            "ortamı — öne çıkan oyuncular ve büyüme temaları; (c) operasyonel "
            "etki — süreçlere ve KPI'lara (AHT, FCR, NPS) yansıma; (d) 'ne "
            "yapmalı' — bu hafta gündeme alınabilecek 2 hamle ve riski.\n\n"
            f"{SECTION_HEADINGS[1]}\n"
            "Yapay zeka gündemi: en önemli 2-4 gelişmeyi seç ve her biri için "
            "'ne değişti, kimi etkiler, neden şimdi' sorularını yanıtla; "
            "pratikte ne anlama geldiğini ve mümkünse gelişmeler arasındaki "
            "ortak örüntüyü göster. Abartıdan kaçın, tarafsız ol.\n\n"
            f"{SECTION_HEADINGS[2]}\n"
            "Kanıta dayalı müşteri deneyimi araştırması; derinliği yukarıdaki "
            "CX ODAĞI'na ayır. Şu blokları ver:\n"
            "(a) *🔍 Bugünün bulgusu*: odağa dair en önemli tespit; bilineni, "
            "tartışmalıyı ve bilinmeyeni ayır.\n"
            "(b) *📊 Kanıt*: bulguyu destekleyen araştırma/rapor — kuruluş "
            "adını yaz. Kaynağını söyleyemiyorsan rakam verme.\n"
            "(c) *🏆 Vaka*: NE yapıldı, HANGİ metrik (NPS/CSAT/CES/FCR/AHT) NE "
            "KADAR, hangi sürede. Emin değilsen sayı verme; mekanizmayı anlat "
            "ve '(kaynağından doğrulayın)' ekle.\n"
            "(d) *🧪 Metodoloji*: bunu kendi operasyonunda nasıl ÖLÇERSİN — "
            "ölçüm tanımı, örneklem, sık yapılan hata.\n"
            "(e) *💛 Tutundurma bağlantısı*: bulgunun tutundurma ve personel "
            "deneyimiyle ilişkisi.\n"
            f"Kaynak verirken yalnızca şu kalıcı kuruluşların kök alan "
            f"adlarını kullan: {STABLE_RESEARCH_SOURCES}.\n\n"
            f"{SECTION_HEADINGS[3]}\n"
            "Banka çağrı merkezi programları: dış kaynak yönetişimi, bilgi "
            "güvenliği ve uyum. Derinliği yukarıdaki DIŞ KAYNAK/UYUM ODAĞI'na "
            "ayır; kalan bloklar kısa kalabilir ama atlanmasın:\n"
            "(a) *📦 Dış kaynak yönetişimi*: bugünün odağına düşen kısım — "
            "sözleşmeye yazılacak somut madde önerisi ve tedarikçiye "
            "sorulacak 2-3 soru ver.\n"
            "(b) *🔐 Bilgi güvenliği*: çağrı merkezine ÖZGÜ 3-4 kontrol seç "
            "(erişim, kayıt/saklama, uç nokta, personel, izleme alanlarından). "
            "Her biri için 'hangi kanıtı istersin' cevabını ver.\n"
            "(c) *⚖️ Uyum*: KVKK veri işleyen yükümlülükleri, sertifika "
            "kapsamının hizmeti gerçekten kapsayıp kapsamadığı ve denetim izi "
            "açısından bugünün odağına düşen kısım. BDDK düzenlemelerinin "
            "MANTIĞINI anlat; madde numarası ve tarih verme.\n"
            "(d) *🚨 Riskler*: 2-3 risk (yoğunlaşma, dördüncü taraf zinciri, "
            "uzaktan temsilci, veri sızıntısı vektörleri, vendor lock-in "
            "arasından). Her biri için erken uyarı sinyali ve alınacak önlem.\n"
            "(e) *🔬 Teknoloji*: konuşma analitiği, agent assist, CCaaS ve "
            "ÖZELLİKLE üretken YZ'nin çağrı merkezinde kullanımı — olgunluk, "
            "ölçülebilir fayda ve bankaya özgü veri/uyum riski.\n"
            f"'📚 Kaynaklar' bölümünde EN AZ bir resmî düzenleyici veya "
            f"standart kuruluşu kaynağı bulunsun ({OFFICIAL_SOURCES}); derin "
            "URL yerine kök alan adı ver.\n\n"
            "'✅ Bugünün görevi' bölümünde bugün 15-30 dakikada yapılabilecek "
            "TEK somut eylem yaz — tercihen doğrulanabilir bir kontrol (örn. "
            "'vendor sözleşmenizde right-to-audit maddesi var mı, bugün açıp "
            "kontrol et') ve dört alanın hangisine dokunduğunu belli et.\n\n"
            + RICH_BRIEFING_GUIDE
            + "\n\nUZUNLUK İSTİSNASI: Bu bölüm dört alt bölümden oluştuğu için "
            "ortak kurallardaki 300-500 kelime hedefi BÜTÜN için 550-700 "
            "kelimeye çıkar. Her alt bölüm kendi başına doyurucu olsun ama "
            "hiçbiri atlanmasın; dolgu cümlesi yerine tek somut örnek yaz."
        )
        return prompt + self._feed_block()


__all__ = [
    "MarketIntelligenceAdvisor",
    "SECTION_HEADINGS",
    "FEEDS",
    "CX_DAILY_FOCUS",
    "BANKING_DAILY_FOCUS",
]
