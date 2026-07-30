"""Banking & contact-center project expert — Banka & Çağrı Merkezi Proje Uzmanı.

A DEEP DOMAIN specialist, deliberately distinct from the broader
:mod:`ai_assistant.advisors.sector_intel` advisor: where sector intel scans the
market and competitors, this persona is a senior consultant who has actually run
bank contact-center **outsourcing programs** and speaks in the language of RFPs,
SLAs, transition plans and regulatory obligations.

Configuration (via environment):
    BANKING_NEWS_RSS_URL  RSS/Atom feed of Turkish banking / contact-center /
                          regulation news. Defaults to a Google News search feed
                          so the briefing can cite REAL, verifiable links out of
                          the box. An unreachable feed degrades to LLM-only.

ACCURACY: regulation changes constantly and a model will happily invent article
numbers and dates. The persona is therefore instructed to describe *principles
and direction* instead of citing specific clauses, to flag anything that must be
verified, and every briefing carries a fixed caveat pointing at the bank's own
compliance/legal function and the official regulator sites.

The RSS fetch happens locally (never inside the LLM call); only the
summarization joins the batched team request.
"""

from __future__ import annotations

from typing import List, Optional

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ._llm_base import RICH_BRIEFING_GUIDE
from ._rss import FeedItem, fetch_feed_items

SYSTEM_PROMPT = (
    "Sen, Türkiye'de bankaların çağrı merkezi ve müşteri iletişim merkezi "
    "programlarını yıllarca yönetmiş kıdemli bir danışmansın. Hem banka "
    "tarafında hem de dış kaynak (outsourcing) tedarikçisi tarafında ihale "
    "hazırlığı, vendor seçimi, fiyatlama, geçiş (transition) ve SLA yönetimi "
    "yapmış birisin. Türkçe konuşuyorsun. Yöneticiye, ihale masasında ve "
    "yönetim kurulu önünde işine yarayacak düzeyde somut, uygulanabilir ve "
    "dürüst bir brifing verirsin.\n\n"
    "MUTLAK DOĞRULUK KURALI: Mevzuat sık değişir. Madde numarası, tebliğ "
    "tarihi, ceza tutarı, süre gibi SPESİFİK ayrıntıları UYDURMA. Bunun yerine "
    "ilkeyi, yönü ve pratikte ne anlama geldiğini anlat; ayrıntı gerektiğinde "
    "'bu ayrıntıyı uyum/hukuk biriminizle ve resmi kaynaktan doğrulayın' diye "
    "açıkça işaretle. Emin olmadığın hiçbir şeyi kesinmiş gibi sunma."
)

# Rotating emphasis so consecutive days do not read identically. The model picks
# one to lead with; the four mandated blocks are always present.
ROTATION_HINT = (
    "Her gün farklı bir açıdan başla (ihale/RFP hazırlığı, fiyatlama modelleri, "
    "geçiş planı, SLA/KPI tasarımı, denetim ve uyum, kalite yönetimi, teknoloji "
    "dönüşümü gibi) ki brifingler birbirinin tekrarı olmasın."
)

CAVEAT = (
    "⚠️ Uyum notu: Buradaki düzenleyici değerlendirmeler genel ilke "
    "düzeyindedir, hukuki görüş değildir ve mevzuat değişebilir. Somut bir "
    "karar öncesinde bankanızın uyum/hukuk birimiyle ve resmi kaynaklardan "
    "doğrulayın: BDDK (https://www.bddk.org.tr), KVKK "
    "(https://www.kvkk.gov.tr), TCMB (https://www.tcmb.gov.tr).\n"
    "🔎 Bağlantıları açılışta doğrulayın."
)

_BRIEF = (
    "Bugün için, bir bankanın çağrı merkezi / müşteri iletişim merkezi "
    "programını yöneten üst düzey bir yöneticiye derinlikli bir uzman brifingi "
    "hazırla. Aşağıdaki DÖRT bloğun HEPSİNİ, bu başlıklarla ve bu sırayla ver:\n\n"
    "1) *📦 Dış kaynak (outsourcing) projeleri*: RFP/ihale hazırlığı ve "
    "şartname kurgusu, vendor seçim kriterleri ve ağırlıklandırma, fiyatlama "
    "modelleri (FTE bazlı, dakika/çağrı başı, hibrit, sonuç/performans bazlı) "
    "ve hangisinin hangi durumda avantajlı olduğu, geçiş (transition) planı ve "
    "geçiş riskleri, SLA ve KPI tasarımı (AHT, FCR, NPS, occupancy, shrinkage, "
    "abandon rate — hangi eşik neden makul, hangi KPI'yı tek başına ödüllendirmek "
    "hangi yan etkiyi doğurur) ve ceza/teşvik (penalty–bonus) mekanizmaları.\n\n"
    "2) *⚠️ Bankanın dikkat etmesi gereken kurallar*: bilgi sistemleri ve dış "
    "hizmet alımı düzenlemelerinin mantığı (BDDK yaklaşımı), KVKK açısından "
    "veri sorumlusu / veri işleyen ayrımı ve sözleşmeye ne yazılması gerektiği, "
    "aydınlatma ve saklama süreleri, veri yerleşimi ile yurt dışına aktarım, "
    "PCI-DSS ve kart verisi, çağrı kaydı ve kayıtların saklanması, denetim "
    "izleri (audit trail) ve yetki yönetimi, iş sürekliliği ve felaket kurtarma "
    "beklentileri. Madde numarası ve tarih verme; ilkeyi ve pratik karşılığını anlat.\n\n"
    "3) *🚨 Uyarılar / tipik tuzaklar*: veri sızıntısı ve aşırı geniş erişim "
    "yetkileri, SLA boşlukları ve ölçüm tanımı anlaşmazlıkları, gizli maliyetler "
    "(değişiklik talepleri, eğitim, teknoloji lisansı, devir maliyeti), kalite "
    "düşüşünün erken sinyalleri, vendor lock-in ve çıkış (exit) planı eksikliği, "
    "alt yüklenici (subcontractor) zinciri riski. Her tuzak için 'nasıl fark "
    "edilir' ve 'sözleşmeye/operasyona ne konur' cevabını ver.\n\n"
    "4) *🔬 Son teknolojik gelişmeler*: konuşma ve metin analitiği, agent assist, "
    "sesli ve yazılı botlar, CCaaS bulut geçişi, WFM, omnichannel, üretken yapay "
    "zekânın çağrı merkezine entegrasyonu, kalite yönetimi otomasyonu — her biri "
    "için olgunluk seviyesi, ölçülebilir fayda ve bankaya özgü uyum/veri riski.\n\n"
    "Sonunda '✅ Bugünün görevi' bölümünde bu yöneticinin bugün 15-30 dakikada "
    "yapabileceği TEK somut adımı yaz.\n\n" + ROTATION_HINT
)


class BankingCcProjectsAdvisor(Advisor):
    key = "banking_cc_projects"
    title = "Banka & Çağrı Merkezi Proje Uzmanı"

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

    # -- helpers ---------------------------------------------------------
    def _fetch_items(self) -> List[FeedItem]:
        """Fetch the news feed once, degrading to an empty list on any error."""
        if self._fetched:
            return self._items
        self._fetched = True
        url = setting("BANKING_NEWS_RSS_URL")
        if not url:
            return self._items
        try:
            self._items = fetch_feed_items(url, limit=6)
        except Exception:
            # Optional enrichment only — never fail the briefing over the feed.
            self._items = []
        return self._items

    def _user_prompt(self) -> str:
        prompt = _BRIEF + "\n\n" + RICH_BRIEFING_GUIDE
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
                "yalnızca bilinen ve kalıcı kök alan adlarını kullan (örn. "
                "https://www.bddk.org.tr, https://www.kvkk.gov.tr, "
                "https://www.tcmb.gov.tr) ve derin URL uydurma."
            )
        return prompt
