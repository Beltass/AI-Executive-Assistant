"""Contact-center & CX researcher — Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı.

A researcher who TEACHES with evidence. Deliberately distinct from the two
neighbouring personas: :mod:`ai_assistant.advisors.sector_intel` scans the
market, :mod:`ai_assistant.advisors.banking_cc_projects` governs outsourcing and
security — this one is about the discipline itself: what is actually known about
contact centers, customer relationships, satisfaction and retention, and how
that knowledge was established.

Coverage, with a rotating daily focus so consecutive days never read alike:
new trends; new applications and technologies; academic and industry research;
**success stories / case studies with concrete evidence** (what was done, which
metric moved, by how much, over what period); methodology (NPS/CSAT/CES
measurement, journey mapping, churn prediction, VoC programmes, first contact
resolution, effort reduction); retention and loyalty programmes; and the link
between employee experience and customer experience.

EVIDENCE DISCIPLINE — the reason this persona exists:

* A figure may only appear when it can be ATTRIBUTED, and the source
  organisation/report is always named next to it.
* Nothing is invented. No made-up statistics, no made-up case-study numbers, no
  made-up company results. "Bilinmiyor" is an acceptable answer.
* Anything the user might repeat in a meeting is explicitly flagged as
  "doğrulayın", and a standing caveat closes every section.
* Items from the live feed are PREFERRED over recalled ones, because they come
  with a real link.

Feed items are filtered through the :mod:`ai_assistant.memory` ledger first, so
the extra daily runs only discuss research the user has not been shown yet.

Configuration (via environment):
    CX_RESEARCH_RSS_URL  Feed of CX / contact-center news. Defaults to a Turkish
                         Google News search covering müşteri deneyimi, çağrı
                         merkezi and müşteri memnuniyeti.
    USER_SECTOR          The user's own field, used to make the exercise land.

With no LLM provider key the advisor is ``skipped``.
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

DEFAULT_SECTOR = "banka çağrı merkezleri"

# One focus per day (day-of-year rotation). Every section still carries the
# mandated blocks, but the day's focus is where the depth goes.
DAILY_FOCUS: List[str] = [
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

# Research bodies whose ROOT domains are stable enough to cite without a link.
STABLE_SOURCES = (
    "Gartner (https://www.gartner.com), Forrester (https://www.forrester.com), "
    "McKinsey (https://www.mckinsey.com), Harvard Business Review "
    "(https://hbr.org), CCW (https://www.customercontactweekdigital.com), "
    "ICMI (https://www.icmi.com), Qualtrics XM Institute "
    "(https://www.qualtrics.com/xm-institute)"
)

SYSTEM_PROMPT = (
    "Sen 'Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı'sın: müşteri "
    "deneyimi, müşteri ilişkileri, memnuniyet ve tutundurma alanında derin "
    "bilgi sahibi, kanıta dayalı çalışan bir araştırmacı ve eğitmensin. "
    "Türkçe konuşuyorsun. Öğretme biçimin akademik değil ama akademik "
    "titizlikte: bir iddiayı ortaya atarken nereden geldiğini söylersin.\n"
    "KANIT DİSİPLİNİ (mutlak kural): Sayı, oran veya vaka sonucu SADECE "
    "kaynağını söyleyebiliyorsan ver ve kaynağın adını (kuruluş/rapor) rakamın "
    "hemen yanında yaz. Emin değilsen rakam VERME; onun yerine yönü ve mekanizmayı "
    "anlat. Vaka çalışması sonucunu, şirket adını, tarihi veya yüzdeyi ASLA "
    "uydurma. Doğrulanması gereken her ifadeyi '(doğrulayın)' notuyla işaretle. "
    "Sana canlı bir haber akışı verildiyse GERÇEK maddeleri tercih et."
)

CAVEAT = (
    "📌 Kanıt notu: Buradaki rakamlar ve vaka sonuçları, yanında adı geçen "
    "kaynağa aittir; metodolojileri ve tarihleri farklılık gösterebilir. "
    "Bir toplantıda veya sunumda kullanmadan önce rakamı kaynağının kendi "
    "sayfasından teyit edin. Kaynağı belirtilmemiş hiçbir sayıyı kesin "
    "bilgi olarak aktarmayın.\n"
    "🔎 Bağlantıları açılışta doğrulayın."
)


def _daily_focus(today: Optional[date] = None) -> str:
    """Today's rotating research focus (day-of-year rotation)."""
    day = today or date.today()
    return DAILY_FOCUS[day.toordinal() % len(DAILY_FOCUS)]


class CxResearchAdvisor(Advisor):
    key = "cx_research"
    title = "Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı"

    # Its research feed is a genuine source of NEW findings between runs.
    incremental_source = True

    def __init__(self) -> None:
        # Fetched once per run and reused by the batched path.
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
        """Fetch the CX feed once, keeping only NOT-YET-REPORTED items."""
        if self._fetched:
            return self._items
        self._fetched = True
        url = setting("CX_RESEARCH_RSS_URL")
        if not url:
            return self._items
        try:
            fetched = fetch_feed_items(url, limit=8)
        except Exception:
            # Optional enrichment only — never fail the briefing over a feed.
            return self._items
        self._items = filter_new_items(self.key, fetched)
        return self._items

    def _user_prompt(self) -> str:
        sector = setting("USER_SECTOR") or DEFAULT_SECTOR
        prompt = (
            f"KULLANICININ ALANI: {sector}\n"
            f"BUGÜNÜN ARAŞTIRMA ODAĞI: {_daily_focus()}\n"
            "Bugünkü bölümün en derin kısmı bu odak olsun; diğer bloklar daha "
            "kısa kalabilir ama atlanmasın.\n\n"
            "Bölümü şu YAPIYLA ver:\n"
            "1) *🔍 Bugünün bulgusu*: odağa dair en önemli tespit; neyin "
            "bilindiğini, neyin tartışmalı olduğunu ve neyin bilinmediğini ayır.\n"
            "2) *📊 Kanıt*: bulguyu destekleyen araştırma veya sektör raporu — "
            "kuruluş/rapor adını yaz. Rakam veriyorsan kaynağını yanına ekle; "
            "kaynağını söyleyemiyorsan rakam verme, mekanizmayı anlat.\n"
            "3) *🏆 Başarı hikâyesi / vaka*: somut bir uygulama örneği — NE "
            "yapıldı, HANGİ metrik (NPS/CSAT/CES/FCR/churn/AHT) NE KADAR "
            "değişti, HANGİ sürede ve hangi koşulda. Bir vakanın rakamından "
            "emin değilsen sayı uydurma; bunun yerine uygulamayı ve "
            "mekanizmasını anlat, '(kaynağından doğrulayın)' notu ekle.\n"
            "4) *🧪 Metodoloji*: bu bulguyu kendi operasyonunda nasıl ÖLÇERSİN "
            "— ölçüm tanımı, örneklem, zamanlama, sık yapılan ölçüm hatası.\n"
            "5) *💛 Tutundurma bağlantısı*: bulgunun müşteri tutundurma "
            "(retention/sadakat) ve personel deneyimi ile ilişkisi.\n"
            "6) *✅ Bugünün görevi*: kullanıcının KENDİ operasyonunda bugün "
            "15-30 dakikada uygulayabileceği tek somut teknik — adımları ve "
            "başarı ölçütünü yaz.\n\n"
            "Kaynak verirken yalnızca bilinen ve KALICI kuruluşların kök alan "
            f"adlarını kullan: {STABLE_SOURCES}. Derin URL uydurma; emin "
            "olmadığında kök adres + önerilen arama terimi ver.\n\n"
            + RICH_BRIEFING_GUIDE
        )

        items = self._fetch_items()
        if items:
            listing = "\n".join(
                f"- {item.title}" + (f" ({item.link})" if item.link else "")
                for item in items
            )
            prompt += (
                "\n\nAşağıdaki başlıklar BUGÜN İLK KEZ geliyor. Bunları "
                "önceliklendir: ilgili olanları bulgu ve kanıt bölümlerine "
                "yedir ve '📚 Kaynaklar' bölümünde bu GERÇEK bağlantıları "
                f"tercih et. Bir başlığın içeriğinden emin değilsen yorumunu "
                f"'(başlığa göre, doğrulayın)' diye işaretle:\n{listing}"
            )
        else:
            prompt += (
                "\n\nBugün canlı bir haber akışı yok; yalnızca yukarıdaki "
                "kalıcı araştırma kuruluşlarının ana adreslerini kullan, derin "
                "URL uydurma ve kaynağını veremediğin rakamı hiç verme."
            )
        return prompt
