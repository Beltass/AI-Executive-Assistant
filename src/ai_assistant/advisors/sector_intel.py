"""Sector & competitor intelligence advisor — Sektör & Rakip İstihbaratı.

Configuration (via environment):
    USER_SECTOR          Sector to analyze (default "banka çağrı merkezleri").
    SECTOR_NEWS_RSS_URL  Optional RSS/Atom feed of sector news; recent headlines
                         are folded into the briefing when reachable.

LLM-backed: produces a Turkish briefing on sector technology & AI developments
and the competitor landscape. Live financial/graph data is not reliably
fetchable, so the analysis is LLM-based and ALWAYS carries an honest caveat that
figures are not real-time and should be verified. With no LLM provider key the
advisor is ``skipped``.
"""

from __future__ import annotations

import os

from . import Advisor, Briefing
from ..integrations import llm
from ._rss import fetch_feed_items

DEFAULT_SECTOR = "banka çağrı merkezleri"

SYSTEM_PROMPT = (
    "Sen kıdemli bir sektör analisti ve rekabet istihbaratı uzmanısın. Türkçe "
    "konuşuyorsun. Görevin, belirli bir sektöre dair teknoloji ve yapay zeka "
    "gelişmeleri ile rakip ortamı üzerine kısa, somut ve stratejik bir brifing "
    "hazırlamak. Analitik, dengeli ve gerçekçi ol. Kesin sayısal iddialardan "
    "kaçın; verdiğin rakamların gerçek zamanlı olmadığını ve doğrulanması "
    "gerektiğini dürüstçe belirt."
)

CAVEAT = (
    "Uyarı: Buradaki değerlendirmeler yapay zeka analizine dayanır; sayısal "
    "veriler gerçek zamanlı değildir ve güncel kaynaklardan doğrulanmalıdır."
)


class SectorIntelAdvisor(Advisor):
    key = "sector_intel"
    title = "Sektör & Rakip İstihbaratı"

    def _generate(self) -> Briefing:
        if not llm.is_configured():
            return self.skipped(
                "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"
            )

        sector = (os.getenv("USER_SECTOR") or "").strip() or DEFAULT_SECTOR
        headlines = self._recent_headlines()

        user_prompt = (
            f"Sektör: {sector}\n\n"
            "Bu sektör için kısa bir istihbarat brifingi hazırla. Şunları kapsa: "
            "(1) sektördeki teknoloji ve yapay zeka gelişmeleri, "
            "(2) rakip ortamı (öne çıkan oyuncular, tedarikçi/çözüm ortağı "
            "ilişkileri, büyüme ve başarı temaları). En fazla 220 kelime, net ve "
            "stratejik Türkçe kullan."
        )
        if headlines:
            joined = "\n".join(f"- {h}" for h in headlines)
            user_prompt += (
                "\n\nAşağıdaki güncel haber başlıklarını da dikkate al ve "
                f"ilgili olanları brifinge yedir:\n{joined}"
            )

        try:
            body = llm.generate_text(SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")

        return self.ok(f"{body.strip()}\n\n{CAVEAT}")

    # -- helpers ---------------------------------------------------------
    def _recent_headlines(self) -> list[str]:
        url = (os.getenv("SECTOR_NEWS_RSS_URL") or "").strip()
        if not url:
            return []
        try:
            items = fetch_feed_items(url, limit=6)
        except Exception:
            # Optional enrichment only — never fail the briefing over the feed.
            return []
        return [item.title for item in items]
