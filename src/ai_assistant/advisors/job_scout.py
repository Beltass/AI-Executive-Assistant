"""Job scout advisor — İş Avcısı & Başvuru Hazırlayıcı.

Configuration (via environment):
    JOB_KEYWORDS    Comma/space separated role keywords (e.g. "veri analisti").
                    REQUIRED — without it the advisor is ``skipped``.
    JOB_LOCATION    Optional location hint (e.g. "İstanbul").

COMPLIANCE: This advisor NEVER logs in to or auto-submits applications on
LinkedIn / Kariyer.net (that would violate their Terms of Service and is an
irreversible action). Instead it PREPARES material for the user to review and
submit themselves: suggested target roles, tailored CV / cover-letter bullet
points, and plain, ready-to-use SEARCH URLs the user can open manually.

LLM-backed: with no LLM provider key configured the advisor is ``skipped``.
"""

from __future__ import annotations

import os
from urllib.parse import quote_plus

from . import Advisor, Briefing
from ..integrations import llm

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
        keywords = (os.getenv("JOB_KEYWORDS") or "").strip()
        if not keywords:
            return self.skipped("missing env var(s): JOB_KEYWORDS")
        if not llm.is_configured():
            return self.skipped(
                "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"
            )

        location = (os.getenv("JOB_LOCATION") or "").strip()

        user_prompt = (
            "Aşağıdaki iş arama girdilerine göre bir başvuru hazırlık brifingi "
            "oluştur.\n"
            f"Anahtar kelimeler: {keywords}\n"
            f"Konum: {location or 'belirtilmedi'}\n\n"
            "Şu üç bölümü ver:\n"
            "(1) Hedef Roller: kişiye uygun 3-5 pozisyon başlığı önerisi.\n"
            "(2) CV / Ön Yazı Maddeleri: bu rollere göre uyarlanabilecek 4-6 "
            "vurucu, ölçülebilir madde (bullet).\n"
            "(3) İpuçları: başvuruyu güçlendirecek kısa öneriler.\n"
            "En fazla 200 kelime, net ve uygulanabilir Türkçe kullan."
        )

        try:
            body = llm.generate_text(SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")

        links = self._search_links(keywords, location)
        text = "\n\n".join(
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
        return self.ok(text)

    # -- helpers ---------------------------------------------------------
    def _search_links(self, keywords: str, location: str) -> str:
        kw = quote_plus(keywords)
        linkedin = f"https://www.linkedin.com/jobs/search/?keywords={kw}"
        if location:
            linkedin += f"&location={quote_plus(location)}"
        kariyer = f"https://www.kariyer.net/is-ilanlari?q={kw}"
        if location:
            kariyer += f"&l={quote_plus(location)}"
        return f"- LinkedIn Jobs: {linkedin}\n- Kariyer.net: {kariyer}"
