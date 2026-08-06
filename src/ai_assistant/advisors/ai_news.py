"""AI news advisor — Yapay Zeka Haberleri.

Configuration (via environment):
    AI_NEWS_RSS_URL     RSS/Atom feed of AI news. Defaults to a Turkish Google
                        News search feed so the roundup links to REAL articles
                        even when no secret is configured.

Behavior:
    - Feed reachable -> summarize the latest headlines (with the LLM if a
      provider key is present, otherwise a plain Turkish headline list).
    - Feed unreachable/empty (but LLM key present) -> degrade to an
      LLM-generated roundup with a caveat that it may not be the very latest
      and links should be verified.
    - Neither an LLM key nor a usable feed -> ``skipped``.

The feed fetch always happens locally; only the summarization joins the
batched team request (see :mod:`ai_assistant.advisors._batch`).
"""

from __future__ import annotations

from typing import List, Optional

from . import Advisor, BatchSection, Briefing
from ..config import setting
from ..integrations import llm
from ..memory import filter_new_items
from ._llm_base import RICH_BRIEFING_GUIDE
from ._rss import FeedItem, fetch_feed_items

SYSTEM_PROMPT = (
    "Sen bir yapay zeka teknolojileri editörüsün. Türkçe konuşuyorsun. Görevin, "
    "yapay zeka dünyasındaki güncel gelişmeleri merak uyandıran, anlaşılır ve "
    "tarafsız bir şekilde özetlemek. Abartıdan kaçın, önemli olanı öne çıkar; "
    "her gelişmenin 'ne değişti, kimi etkiler, neden şimdi' sorularına yanıt ver."
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

    # Its feed is a genuine source of NEW findings between runs.
    incremental_source = True

    def __init__(self) -> None:
        # Feed items are fetched once per run and reused by the batched path.
        self._items: List[FeedItem] = []
        self._fetched = False

    def _generate(self) -> Briefing:
        items = self._fetch_items()

        if not llm.is_configured():
            if items:
                return self.ok(f"{self._headline_list(items)}\n\n{FEED_CAVEAT}")
            return self.skipped(
                "missing env var(s): AI_NEWS_RSS_URL or GEMINI_API_KEY/OPENAI_API_KEY"
            )

        try:
            body = llm.generate_text(SYSTEM_PROMPT, self._user_prompt())
        except Exception as exc:
            if items:
                # Keep the real headlines rather than failing the section.
                return self.ok(f"{self._headline_list(items)}\n\n{FEED_CAVEAT}")
            return self.failed(f"LLM isteği başarısız: {exc}")

        return self.briefing_from_batch(body)

    # -- batching --------------------------------------------------------
    def batch_section(self) -> Optional[BatchSection]:
        if not llm.is_configured():
            return None
        self._fetch_items()  # real links gathered outside the LLM call
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=self._user_prompt(),
        )

    def briefing_from_batch(self, text: str) -> Briefing:
        caveat = FEED_CAVEAT if self._items else LLM_CAVEAT
        return self.ok(f"{text.strip()}\n\n{caveat}")

    # -- deduplication ---------------------------------------------------
    def new_finding_count(self) -> int:
        return len(self._fetch_items())

    # -- helpers ---------------------------------------------------------
    def _fetch_items(self) -> List[FeedItem]:
        """Fetch the feed once, keeping only NOT-YET-REPORTED headlines.

        Degrades to an empty list on any error. Everything that survives the
        :mod:`ai_assistant.memory` ledger is genuinely new to the user, so the
        extra runs during the day never repeat the morning's stories.
        """
        if self._fetched:
            return self._items
        self._fetched = True
        url = setting("AI_NEWS_RSS_URL")
        if not url:
            return self._items
        try:
            fetched = fetch_feed_items(url, limit=8)
        except Exception:
            # Guarded: an unreachable feed falls back to the LLM-only path.
            return self._items
        self._items = filter_new_items(self.key, fetched)
        return self._items

    @staticmethod
    def _headline_list(items: List[FeedItem]) -> str:
        listing = "\n".join(
            f"- {item.title}" + (f" ({item.link})" if item.link else "")
            for item in items
        )
        return f"Güncel yapay zeka başlıkları:\n{listing}"

    def _user_prompt(self) -> str:
        items = self._fetch_items()
        if items:
            listing = "\n".join(
                f"- {item.title}" + (f" ({item.link})" if item.link else "")
                for item in items
            )
            return (
                "Aşağıdaki güncel yapay zeka haber başlıklarını Türkçe olarak "
                "derinlemesine işle: en önemli 3-5 gelişmeyi seç, her biri için "
                "ne olduğunu, neden önemli olduğunu, kimi etkilediğini ve "
                "pratikte ne anlama geldiğini açıkla; mümkünse gelişmeler "
                "arasındaki ortak örüntüyü de göster. '📚 Kaynaklar' bölümünde "
                "aşağıdaki listeden GERÇEK bağlantıları tercih et.\n\n"
                + RICH_BRIEFING_GUIDE
                + f"\n\nHaber başlıkları:\n{listing}"
            )
        return (
            "Yapay zeka dünyasındaki güncel ve önemli gelişmelere dair "
            "derinlikli bir derleme hazırla; 3-5 önemli temayı tarafsız ve "
            "anlaşılır biçimde ele al, her tema için somut örnek ve pratik "
            "çıkarım ver. Canlı bir haber akışı yok; '📚 Kaynaklar' bölümünde "
            "yalnızca bilinen ve kalıcı kök alan adlarını kullan (örn. "
            "https://ai.googleblog.com, https://openai.com/blog) ve doğrulama "
            "notunu ekle.\n\n" + RICH_BRIEFING_GUIDE
        )
