"""AI news advisor — Yapay Zeka Haberleri.

Configuration (via environment):
    AI_NEWS_RSS_URL     Optional RSS/Atom feed of AI news. When set and
                        reachable, the latest items are summarized in Turkish.

Behavior:
    - Feed set & reachable -> summarize the latest headlines (with the LLM if a
      provider key is present, otherwise a plain Turkish headline list).
    - Feed unset (but LLM key present) -> an LLM-generated roundup with a caveat
      that it may not be the very latest and links should be verified.
    - Neither an LLM key nor a usable feed -> ``skipped``.
"""

from __future__ import annotations

import os

from . import Advisor, Briefing
from ..integrations import llm
from ._rss import fetch_feed_items

SYSTEM_PROMPT = (
    "Sen bir yapay zeka teknolojileri editörüsün. Türkçe konuşuyorsun. Görevin, "
    "yapay zeka dünyasındaki güncel gelişmeleri kısa, anlaşılır ve tarafsız bir "
    "şekilde özetlemek. Abartıdan kaçın, önemli olanı öne çıkar."
)

FEED_CAVEAT = (
    "Not: Başlıklar sağlanan haber akışından alınmıştır; ayrıntılar için "
    "bağlantıları kontrol edin."
)
LLM_CAVEAT = (
    "Uyarı: Bu özet, canlı bir haber akışı olmadan hazırlanmıştır; en güncel "
    "gelişmeleri yansıtmayabilir ve bağlantılar doğrulanmalıdır."
)


class AiNewsAdvisor(Advisor):
    key = "ai_news"
    title = "Yapay Zeka Haberleri"

    def _generate(self) -> Briefing:
        feed_url = (os.getenv("AI_NEWS_RSS_URL") or "").strip()

        if feed_url:
            return self._from_feed(feed_url)
        if llm.is_configured():
            return self._from_llm()
        return self.skipped(
            "missing env var(s): AI_NEWS_RSS_URL or GEMINI_API_KEY/OPENAI_API_KEY"
        )

    # -- feed path -------------------------------------------------------
    def _from_feed(self, url: str) -> Briefing:
        try:
            items = fetch_feed_items(url, limit=8)
        except Exception as exc:
            return self.failed(f"haber akışı alınamadı: {exc}")
        if not items:
            return self.failed("haber akışında öğe bulunamadı")

        listing = "\n".join(
            f"- {item.title}" + (f" ({item.link})" if item.link else "")
            for item in items
        )

        if llm.is_configured():
            user_prompt = (
                "Aşağıdaki güncel yapay zeka haber başlıklarını Türkçe olarak "
                "kısaca özetle; en önemli 3-5 gelişmeyi öne çıkar. En fazla 180 "
                f"kelime kullan.\n\n{listing}"
            )
            try:
                body = llm.generate_text(SYSTEM_PROMPT, user_prompt)
                return self.ok(f"{body.strip()}\n\n{FEED_CAVEAT}")
            except Exception:
                # Fall back to the plain headline list rather than failing.
                pass

        return self.ok(f"Güncel yapay zeka başlıkları:\n{listing}\n\n{FEED_CAVEAT}")

    # -- LLM-only path ---------------------------------------------------
    def _from_llm(self) -> Briefing:
        user_prompt = (
            "Yapay zeka dünyasındaki güncel ve önemli gelişmelere dair kısa bir "
            "derleme hazır. 3-5 madde halinde, tarafsız ve anlaşılır Türkçe "
            "kullan. En fazla 180 kelime."
        )
        try:
            body = llm.generate_text(SYSTEM_PROMPT, user_prompt)
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")
        return self.ok(f"{body.strip()}\n\n{LLM_CAVEAT}")
