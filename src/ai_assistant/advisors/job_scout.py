"""Job scout advisor — İş Avcısı & Başvuru Hazırlayıcı.

Configuration (via environment):
    JOB_KEYWORDS    Comma/space separated role keywords (e.g. "veri analisti").
                    Falls back to the default in
                    :data:`~ai_assistant.config.DEFAULT_SETTINGS`, so the
                    advisor is active out of the box.
    JOB_LOCATION    Location hint (default "İstanbul").

COMPLIANCE: This advisor NEVER logs in to or auto-submits applications on
LinkedIn / Kariyer.net (that would violate their Terms of Service and is an
irreversible action). Instead it PREPARES material for the user to review and
submit themselves: suggested target roles, tailored CV / cover-letter bullet
points, and plain, ready-to-use SEARCH URLs the user can open manually.

LLM-backed: with no LLM provider key configured the advisor is ``skipped``.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote_plus

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ._llm_base import RICH_BRIEFING_GUIDE

SYSTEM_PROMPT = (
    "Sen deneyimli bir kariyer koçu ve teknik işe alım uzmanısın; adına 'İş "
    "Avcısı & Başvuru Hazırlayıcı' diyoruz. Türkçe konuşuyorsun. Görevin, bir "
    "profesyonelin iş arama sürecini hızlandıracak MALZEMEYİ hazırlamak. ÖNEMLİ "
    "UYUM KURALI: Hiçbir platforma (LinkedIn, Kariyer.net vb.) senin adına giriş "
    "yapmaz, otomatik başvuru göndermezsin; bunlar kullanıcının bizzat gözden "
    "geçirip kendisinin yapması gereken adımlardır. Sen yalnızca öneri ve taslak "
    "üretirsin. Somut, gerçekçi ve uygulanabilir ol; klişelerden kaçın."
)


class JobScoutAdvisor(Advisor):
    key = "job_scout"
    title = "İş Avcısı & Başvuru Hazırlayıcı"

    def _generate(self) -> Briefing:
        keywords = setting("JOB_KEYWORDS")
        if not keywords:
            return self.skipped("missing env var(s): JOB_KEYWORDS")
        if not llm.is_configured():
            return self.skipped("missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY")

        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")

        return self.ok(self._compose(body))

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        """Join the batched call when keywords and a provider key are present."""
        if not setting("JOB_KEYWORDS") or not llm.is_configured():
            return None
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._user_prompt(),
        )

    def briefing_from_batch(self, text: str) -> Briefing:
        """Append the deterministic search links to the batched section."""
        return self.ok(self._compose(text))

    # -- helpers ---------------------------------------------------------
    def _user_prompt(self) -> str:
        keywords = setting("JOB_KEYWORDS")
        location = setting("JOB_LOCATION")
        return (
            "Aşağıdaki iş arama girdilerine göre bir başvuru hazırlık brifingi "
            "oluştur.\n"
            f"Anahtar kelimeler: {keywords}\n"
            f"Konum: {location or 'belirtilmedi'}\n\n"
            "Şu bölümleri ver:\n"
            "(1) Hedef Roller: kişiye uygun 3-5 pozisyon başlığı önerisi; her "
            "biri için hangi deneyimin öne çıkarılacağını ve bu rolün neden "
            "uygun olduğunu yaz.\n"
            "(2) CV / Ön Yazı Maddeleri: bu rollere göre uyarlanabilecek 4-6 "
            "vurucu, ÖLÇÜLEBİLİR madde (bullet) — her birinde eylem fiili + "
            "somut sayı/oran + sonuç olsun; ayrıca zayıf bir maddeyi güçlü "
            "hâline dönüştüren 'önce/sonra' örneği ver.\n"
            "(3) Mülakat Hazırlığı: bu roller için çıkması çok olası 2-3 soru "
            "ve STAR yöntemiyle nasıl yanıtlanacağına dair kısa iskeletler.\n"
            "(4) İpuçları: başvuruyu güçlendirecek somut öneriler (ATS uyumu, "
            "anahtar kelime eşleştirme, takip mesajı zamanlaması).\n"
            "'📚 Kaynaklar' bölümünde CV/mülakat gelişimi için kaliteli, "
            "kalıcı kaynaklar (kitap, saygın platform, resmi rehber) öner.\n\n"
            + RICH_BRIEFING_GUIDE
        )

    def _compose(self, body: str) -> str:
        """Body + ready-to-open search links + the compliance note."""
        links = self._search_links(setting("JOB_KEYWORDS"), setting("JOB_LOCATION"))
        return "\n\n".join(
            [
                body.strip(),
                "Hazır Arama Bağlantıları (kendiniz açıp inceleyin):\n" + links,
                (
                    "Not: Bu malzemeler ve bağlantılar sizin gözden geçirip "
                    "kendinizin başvurması için hazırlanmıştır. Sizin adınıza "
                    "otomatik giriş yapılmaz veya başvuru gönderilmez."
                ),
            ]
        )

    def _search_links(self, keywords: str, location: str) -> str:
        kw = quote_plus(keywords)
        linkedin = f"https://www.linkedin.com/jobs/search/?keywords={kw}"
        if location:
            linkedin += f"&location={quote_plus(location)}"
        kariyer = f"https://www.kariyer.net/is-ilanlari?q={kw}"
        if location:
            kariyer += f"&l={quote_plus(location)}"
        return f"- LinkedIn Jobs: {linkedin}\n- Kariyer.net: {kariyer}"
