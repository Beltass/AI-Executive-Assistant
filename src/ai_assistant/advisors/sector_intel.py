"""Sector & competitor intelligence advisor — Sektör & Rakip İstihbaratı.

Configuration (via environment):
    USER_SECTOR          Sector to analyze (default "banka çağrı merkezleri").
    SECTOR_NEWS_RSS_URL  RSS/Atom feed of sector news; recent headlines are
                         folded into the briefing when reachable. Defaults to a
                         Turkish Google News search feed so the briefing can
                         cite real, verifiable links out of the box.

LLM-backed: produces a Turkish briefing on sector technology & AI developments
and the competitor landscape. Live financial/graph data is not reliably
fetchable, so the analysis is LLM-based and ALWAYS carries an honest caveat that
figures are not real-time and should be verified. With no LLM provider key the
advisor is ``skipped``.

The RSS fetch happens locally (never inside the LLM call); only the
summarization joins the batched team request.
"""

from __future__ import annotations

from typing import List, Optional

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ._llm_base import RICH_BRIEFING_GUIDE
from ._rss import fetch_feed_items

DEFAULT_SECTOR = "banka çağrı merkezleri"

SYSTEM_PROMPT = (
    "Sen kıdemli bir sektör analisti ve rekabet istihbaratı uzmanısın. Türkçe "
    "konuşuyorsun. Görevin, belirli bir sektöre dair teknoloji ve yapay zeka "
    "gelişmeleri ile rakip ortamı üzerine somut, derinlikli ve stratejik bir "
    "brifing hazırlamak. Analitik, dengeli ve gerçekçi ol. Kesin sayısal "
    "iddialardan kaçın; verdiğin rakamların gerçek zamanlı olmadığını ve "
    "doğrulanması gerektiğini dürüstçe belirt."
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

        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")

        return self.ok(f"{body.strip()}\n\n{CAVEAT}")

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        if not llm.is_configured():
            return None
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._user_prompt(),
        )

    def briefing_from_batch(self, text: str) -> Briefing:
        return self.ok(f"{text.strip()}\n\n{CAVEAT}")

    # -- helpers ---------------------------------------------------------
    def _user_prompt(self) -> str:
        sector = setting("USER_SECTOR") or DEFAULT_SECTOR
        headlines = self._recent_headlines()

        user_prompt = (
            f"Sektör: {sector}\n\n"
            "Bu sektör için derinlikli bir istihbarat brifingi hazırla. "
            "Şunları kapsa: (1) sektördeki teknoloji ve yapay zeka "
            "gelişmeleri — hangi kullanım senaryosu, hangi olgunluk "
            "seviyesinde, hangi ölçülebilir faydayla; (2) rakip ortamı — öne "
            "çıkan oyuncular, tedarikçi/çözüm ortağı ilişkileri, büyüme ve "
            "başarı temaları; (3) operasyonel etki — bu gelişmelerin ekip "
            "yapısına, süreçlere ve KPI'lara (örn. AHT, FCR, NPS, kayıp çağrı "
            "oranı) olası yansımaları; (4) 'ne yapmalı' — bu hafta gündeme "
            "alınabilecek 2-3 stratejik hamle ve her birinin riski. Analitik, "
            "stratejik ve somut ol.\n\n"
            + RICH_BRIEFING_GUIDE
        )
        if headlines:
            joined = "\n".join(f"- {h}" for h in headlines)
            user_prompt += (
                "\n\nAşağıdaki güncel haber başlıklarını da dikkate al, ilgili "
                "olanları brifinge yedir ve '📚 Kaynaklar' bölümünde bu "
                f"başlıkların GERÇEK bağlantılarını tercih et:\n{joined}"
            )
        else:
            user_prompt += (
                "\n\nCanlı bir haber akışı sağlanmadı; '📚 Kaynaklar' bölümünde "
                "yalnızca bilinen ve kalıcı kök alan adlarını (örn. sektör "
                "otoriteleri, resmi kurum siteleri) kullan ve doğrulama notunu ekle."
            )
        return user_prompt

    def _recent_headlines(self) -> List[str]:
        url = setting("SECTOR_NEWS_RSS_URL")
        if not url:
            return []
        try:
            items = fetch_feed_items(url, limit=6)
        except Exception:
            # Optional enrichment only — never fail the briefing over the feed.
            return []
        return [
            item.title + (f" ({item.link})" if item.link else "") for item in items
        ]
