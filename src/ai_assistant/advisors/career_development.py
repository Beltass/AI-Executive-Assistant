"""Career development advisor — Kariyer Gelişimi (PHASE 1B consolidation).

Folds FOUR previously separate personas into ONE briefing produced by a SINGLE
LLM call:

* :mod:`~ai_assistant.advisors.career_hr` — kariyer planlama, yetkinlik açığı,
  CV geliştirme (the strategic "where am I going" layer).
* :mod:`~ai_assistant.advisors.job_scout` — hedef roller, başvuru malzemesi and
  the deterministic, ready-to-open search links.
* :mod:`~ai_assistant.advisors.language_coach` — iş İngilizcesi + yönetici
  iletişimi, with the ISO-week focus rotation kept intact.
* :mod:`~ai_assistant.advisors.free_certs` — ücretsiz sertifika/kurs fırsatları,
  fed by the same ``FREE_CERTS_RSS_URL`` announcement feed.

WHY ONE CALL. Four personas used to contribute four sections to the batched
team request, each repeating its own framing. They all answer the same
question — "how do I get further in my career this quarter?" — so they are now
one persona with four clearly-headed subsections. That is a 4 → 1 reduction in
batch sections and roughly a 60-70% cut in the prompt bytes this domain costs.

WHAT IS PRESERVED (deliberately, item by item):

* the free-certificate RSS feed and its :mod:`ai_assistant.memory` dedup, so the
  extra daily runs only mention announcements the user has not seen yet;
* the ISO-week rotation of the executive-communication focus, so the English
  coaching arc still changes week to week with no stored state;
* the job-scout COMPLIANCE contract — no login, no auto-submit, only prepared
  material plus plain search URLs the user opens themselves;
* the "verify the link is still free" reminder on every certificate suggestion.

Configuration (via environment):
    USER_SECTOR         Sector used to tailor every subsection
                        (default "banka çağrı merkezleri").
    JOB_KEYWORDS        Comma/space separated role keywords. Missing keywords
                        soften the job subsection to generic guidance instead of
                        skipping the whole advisor.
    JOB_LOCATION        Location hint (default "İstanbul").
    FREE_CERTS_RSS_URL  Feed of free-course / certificate announcements.

The feed fetch always happens locally, never inside the LLM call; only the
writing joins the batched team request. With no LLM provider key the advisor is
``skipped``.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional
from urllib.parse import quote_plus

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
    "## 💼 Kariyer & İK Gündemi",
    "## 🎯 Uygun İlanlar & Başvuru Hazırlığı",
    "## 🗣️ İngilizce Pratik Görevi",
    "## 🎓 Ücretsiz Sertifika Fırsatları",
)

# Rotating executive-communication focus, chosen by ISO week so each week has a
# different arc without any stored state (carried over from the language coach).
WEEKLY_FOCUS = [
    "veriyle hikâye anlatma (storytelling with data): sayıyı mesaja çevirmek, "
    "'so what' testi, bir grafiği tek cümleyle anlatmak",
    "yönetim kuruluna sunum (board-level communication): önce sonuç (BLUF), "
    "tek slaytlık özet, zor sorulara hazırlık",
    "ikna ve müzakere (persuasion & negotiation): çerçeveleme, taviz mimarisi, "
    "tedarikçi/vendor görüşmesinde dil",
    "toplantı yönetimi (running meetings): gündem kurma, sözü toparlama, "
    "araya girme ve kapanışta karar/aksiyon netleştirme",
]


def _weekly_focus(today: Optional[date] = None) -> str:
    """This week's executive-communication focus (ISO-week rotation)."""
    day = today or date.today()
    return WEEKLY_FOCUS[day.isocalendar()[1] % len(WEEKLY_FOCUS)]


SYSTEM_PROMPT = (
    "Sen kıdemli bir İnsan Kaynakları direktörü ve kariyer gelişimi "
    "mentorusun; aynı zamanda teknik işe alım uzmanı, ileri seviye iş "
    "İngilizcesi eğitmeni ve ücretsiz eğitim fırsatları araştırmacısısın. "
    "Yani bir profesyonelin kariyerinin DÖRT boyutuna birden bakan tek bir "
    "danışmansın: nereye gidiyor (kariyer planı), nereye başvuruyor (ilanlar "
    "ve başvuru malzemesi), nasıl anlatıyor (iş İngilizcesi ve yönetici "
    "iletişimi) ve nasıl belgeliyor (ücretsiz sertifikalar).\n\n"
    "Türkçe konuşuyorsun. Açıklamaların Türkçe; öğrettiğin İngilizce kalıplar "
    "İngilizce ve her birinin Türkçe karşılığını da verirsin. Somut, güncel ve "
    "uygulanabilir ol; genel geçer tavsiyelerden kaçın. Gerçekçi ve "
    "destekleyici bir ton kullan.\n\n"
    "ÖNEMLİ UYUM KURALI: Hiçbir platforma (LinkedIn, Kariyer.net vb.) "
    "kullanıcı adına giriş yapmaz, otomatik başvuru göndermezsin; bunlar "
    "kullanıcının bizzat gözden geçirip kendisinin yapması gereken adımlardır. "
    "Sen yalnızca öneri ve taslak üretirsin.\n"
    "DOĞRULUK KURALI: Uydurma kurs adı, uydurma sertifika, uydurma deyim veya "
    "var olmayan bağlantı verme. Emin olmadığında sağlayıcının ana adresini ve "
    "önerilen bir arama terimini yaz; ücretsizliğin doğrulanmasını hatırlat."
)

COMPLIANCE_NOTE = (
    "Not: Bu malzemeler ve bağlantılar sizin gözden geçirip kendinizin "
    "başvurması için hazırlanmıştır. Sizin adınıza otomatik giriş yapılmaz "
    "veya başvuru gönderilmez."
)

CAVEAT = (
    "ℹ️ Not: Eğitim ve sertifika koşulları (ücretsizlik, süre, dil) sağlayıcı "
    "tarafından değiştirilebilir; kaydolmadan önce sayfada teyit edin.\n"
    "🔎 Bağlantıları açılışta doğrulayın."
)


class CareerDevelopmentAdvisor(Advisor):
    key = "career_development"
    title = "Kariyer Gelişimi (İK · İlanlar · İngilizce · Sertifika)"

    # Its free-certificate announcement feed is a genuine source of NEW
    # findings between two runs on the same day.
    incremental_source = True

    def __init__(self) -> None:
        # Fetched once per run and reused by the batched path.
        self._items: List[FeedItem] = []
        self._fetched = False

    def _generate(self) -> Briefing:
        if not llm.is_configured():
            return self.skipped("missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY")
        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception as exc:
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
        """Append the deterministic search links and the standing notes."""
        return self.ok(self._compose(text))

    # -- deduplication ---------------------------------------------------
    def new_finding_count(self) -> int:
        return len(self._fetch_items())

    # -- helpers ---------------------------------------------------------
    def _fetch_items(self) -> List[FeedItem]:
        """Fetch the announcements feed once, keeping only NEW items."""
        if self._fetched:
            return self._items
        self._fetched = True
        url = setting("FREE_CERTS_RSS_URL")
        if not url:
            return self._items
        try:
            fetched = fetch_feed_items(url, limit=6)
        except Exception:
            # Optional enrichment only — never fail the briefing over a feed.
            return self._items
        self._items = filter_new_items(self.key, fetched)
        return self._items

    def _compose(self, body: str) -> str:
        """Body + ready-to-open search links + compliance note + caveat."""
        parts = [body.strip()]
        keywords = setting("JOB_KEYWORDS")
        if keywords:
            links = self._search_links(keywords, setting("JOB_LOCATION"))
            parts.append(
                "Hazır Arama Bağlantıları (kendiniz açıp inceleyin):\n" + links
            )
        parts.append(COMPLIANCE_NOTE)
        parts.append(CAVEAT)
        return "\n\n".join(parts)

    @staticmethod
    def _search_links(keywords: str, location: str) -> str:
        kw = quote_plus(keywords)
        linkedin = f"https://www.linkedin.com/jobs/search/?keywords={kw}"
        if location:
            linkedin += f"&location={quote_plus(location)}"
        kariyer = f"https://www.kariyer.net/is-ilanlari?q={kw}"
        if location:
            kariyer += f"&l={quote_plus(location)}"
        return f"- LinkedIn Jobs: {linkedin}\n- Kariyer.net: {kariyer}"

    def _user_prompt(self) -> str:
        sector = setting("USER_SECTOR") or DEFAULT_SECTOR
        keywords = setting("JOB_KEYWORDS")
        location = setting("JOB_LOCATION")

        prompt = (
            f"KULLANICININ ALANI: {sector} (üst düzey yönetici).\n"
            f"İŞ ARAMA ANAHTAR KELİMELERİ: {keywords or 'belirtilmedi'}\n"
            f"KONUM: {location or 'belirtilmedi'}\n"
            f"BU HAFTANIN YÖNETİCİ İLETİŞİMİ ODAĞI: {_weekly_focus()}\n\n"
            "Bugün için TEK bir kariyer gelişimi brifingi yaz. Brifing DÖRT alt "
            "bölümden oluşacak; alt başlıkları AYNEN aşağıdaki gibi, bu sırayla "
            "ve bu yazımla ver (rapor bu başlıklardan bölünüyor):\n"
            + "\n".join(SECTION_HEADINGS)
            + "\n\n"
            "Alt bölümlerin içeriği:\n\n"
            f"{SECTION_HEADINGS[0]}\n"
            "Stratejik kariyer planlama: bu alanda önümüzdeki dönem değer "
            "kazanacak 2-3 yetkinliği adlandır, kullanıcının muhtemel yetkinlik "
            "açığını ve nasıl kapatacağını yaz. Uygulanabilir bir rutin tarif et "
            "(süre, sıklık, hangi adım), CV için 'önce/sonra' biçiminde GERÇEK "
            "bir örnek ver (zayıf bir maddenin ölçülebilir, güçlü hâli), "
            "ilerlemenin nasıl ölçüleceğini söyle ve 4 haftalık kısa bir yol "
            "haritası çıkar. Genel geçer tavsiyelerden kaçın.\n\n"
            f"{SECTION_HEADINGS[1]}\n"
            "Uygun ilanlar ve başvuru hazırlığı:\n"
            "(a) Hedef Roller: anahtar kelimelere ve konuma uygun 3-5 pozisyon "
            "başlığı; her biri için hangi deneyimin öne çıkarılacağı ve bu rolün "
            "neden uygun olduğu.\n"
            "(b) CV / Ön Yazı Maddeleri: bu rollere uyarlanabilecek 4-6 vurucu, "
            "ÖLÇÜLEBİLİR madde — her birinde eylem fiili + somut sayı/oran + "
            "sonuç.\n"
            "(c) Mülakat Hazırlığı: çıkması çok olası 2-3 soru ve STAR "
            "yöntemiyle kısa yanıt iskeletleri.\n"
            "(d) İpuçları: ATS uyumu, anahtar kelime eşleştirme, takip mesajı "
            "zamanlaması.\n"
            "İlan listesi uydurma; şirket adı ve ilan bağlantısı ÜRETME — hazır "
            "arama bağlantıları brifingin sonuna sistem tarafından eklenecek.\n\n"
            f"{SECTION_HEADINGS[2]}\n"
            "İngilizce pratik görevi:\n"
            "(a) Bugünün 4-5 iş İngilizcesi kalıbı: yönetici seviyesinde, "
            "birbirinden farklı kalıplar. Her biri için: İngilizce kalıp — "
            "Türkçe karşılığı — kullanıcının alanından GERÇEKÇİ bir örnek cümle "
            "(SLA görüşmesi, vendor toplantısı, NPS sunumu, ekip geri bildirimi) "
            "— ve 'nerede kullanma' uyarısı ya da sık yapılan bir hata. "
            "Telaffuzu zor kelimelerde basit bir Türkçe okunuş ipucu ekle.\n"
            "(b) Haftanın odağı: yukarıdaki odak konusunu bir adım ilerlet; adı "
            "olan bir teknik/çerçeve ver, kısa bir örnek diyalog göster "
            "(İngilizce + Türkçe), yaygın hatayı düzelt.\n"
            "(c) Mini alıştırma: alana uygun 2 Türkçe cümle ver ve kullanıcıdan "
            "İngilizceye çevirmesini iste. Model cevabı BU BÖLÜMDE VERME; "
            "brifingin en sonuna bırakacaksın (aşağıya bak).\n\n"
            f"{SECTION_HEADINGS[3]}\n"
            "Ücretsiz sertifika ve eğitim fırsatları: bu alanda İŞE YARAYAN 3-4 "
            "ücretsiz sertifika/kurs — her biri için sağlayıcı, yaklaşık süre, "
            "zorluk seviyesi, hangi beceriyi kazandırdığı ve CV'de nasıl "
            "konumlandırılacağı. Ayrıca dil pratiği için somut bir haftalık "
            "rutin (hangi kaynak, günde kaç dakika, hangi çıktı) ve öğrenmeyi "
            "tamamlama oranını artıran 2-3 taktik. Tercihen Coursera "
            "(https://www.coursera.org), edX (https://www.edx.org), Khan Academy "
            "(https://www.khanacademy.org), freeCodeCamp "
            "(https://www.freecodecamp.org) gibi bilinen ücretsiz/açık "
            "platformların ANA adreslerini kullan; derin URL uydurma. Her öneriye "
            "kısa bir 'neden bu?' notu ve 'ücretsiz olduğunu doğrulayın' "
            "hatırlatması ekle.\n\n"
            "BRİFİNGİN EN SONUNDA, dört alt bölümden ve '📚 Kaynaklar' "
            "bölümünden SONRA, şu satırı aynen yaz:\n"
            "`— — — önce kendin dene, sonra bak — — —`\n"
            "ve altına '*Örnek cevap:*' başlığıyla mini alıştırmadaki "
            "cümlelerin model İngilizce çevirilerini, kısa bir 'neden böyle' "
            "notuyla ver. Bu bölüm en altta kalsın ki kullanıcı önce kendisi "
            "denesin.\n\n"
            "'✅ Bugünün görevi' bölümünde bugün 15-30 dakikada yapılabilecek "
            "TEK somut eylem yaz; dört alanın hangisine dokunduğunu belli et.\n\n"
            + RICH_BRIEFING_GUIDE
            + "\n\nUZUNLUK İSTİSNASI: Bu bölüm dört alt bölümden oluştuğu için "
            "ortak kurallardaki 300-500 kelime hedefi BÜTÜN için 700-900 "
            "kelimeye çıkar; her alt bölüm kendi başına doyurucu olsun ama "
            "hiçbiri atlanmasın."
        )

        items = self._fetch_items()
        if items:
            listing = "\n".join(
                f"- {item.title}" + (f" ({item.link})" if item.link else "")
                for item in items
            )
            prompt += (
                "\n\nAşağıdaki eğitim/sertifika duyuruları BUGÜN İLK KEZ "
                "geliyor; ilgili olanları 'Ücretsiz Sertifika Fırsatları' "
                "bölümüne yedir ve '📚 Kaynaklar' bölümünde bu GERÇEK "
                f"bağlantıları tercih et:\n{listing}"
            )
        else:
            prompt += (
                "\n\nBugün yeni bir eğitim duyurusu akışı yok; kaynak olarak "
                "yalnızca yukarıdaki kalıcı platformların ana adreslerini "
                "kullan ve derin URL uydurma."
            )
        return prompt


__all__ = ["CareerDevelopmentAdvisor", "SECTION_HEADINGS", "WEEKLY_FOCUS"]
