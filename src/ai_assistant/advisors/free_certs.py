"""Free certifications & training advisor — Ücretsiz Sertifika & Eğitim Araştırmacısı.

Configuration (via environment):
    USER_SECTOR          Sector/field to tailor suggestions to
                         (default "banka çağrı merkezleri").
    FREE_CERTS_RSS_URL   Feed of free-course / certificate announcements.
                         Defaults to a Turkish Google News search so the
                         suggestions can cite REAL, current announcements and
                         not only evergreen platform home pages.

LLM-backed: suggests currently-relevant FREE certifications / courses and
language-learning resources for the user's field, each with a short "why" and a
reminder to verify the link is still free. With no LLM provider key configured
the advisor is ``skipped``.

The feed fetch happens locally (never inside the LLM call) and every fetched
item passes through the :mod:`ai_assistant.memory` ledger first, so the extra
runs during the day only mention announcements the user has not seen yet.
"""

from __future__ import annotations

from typing import List, Sequence

from ..config import setting
from ..memory import filter_new_items
from ._llm_base import LLMAdvisor, RICH_BRIEFING_GUIDE
from ._rss import FeedItem, fetch_feed_items

DEFAULT_SECTOR = "banka çağrı merkezleri"

SYSTEM_PROMPT = (
    "Sen kariyer gelişimi ve ücretsiz eğitim fırsatları konusunda uzman bir "
    "araştırmacısın; adına 'Ücretsiz Sertifika & Eğitim Araştırmacısı' diyoruz. "
    "Türkçe konuşuyorsun. Görevin, kişinin alanına uygun GÜNCEL ve ÜCRETSIZ "
    "sertifika/kurs fırsatları ile dil öğrenme kaynakları önermek. Her öneri "
    "için kısa bir 'neden' ekle. Uydurma bağlantı verme; kullanıcıya bağlantının "
    "hâlâ ücretsiz olup olmadığını doğrulamasını hatırlat."
)


def _user_prompt(items: Sequence[FeedItem] = ()) -> str:
    sector = setting("USER_SECTOR") or DEFAULT_SECTOR
    prompt = (
        f"Alan/sektör: {sector}\n\n"
        "Bu alana uygun ücretsiz sertifikalar/kurslar ve dil öğrenme "
        "kaynaklarını derinlemesine ele al. Şunları ayrı alt başlıklarda ver: "
        "(1) bu alanda İŞE YARAYAN 3-4 ücretsiz sertifika/kurs — her biri için "
        "sağlayıcı, yaklaşık süre, zorluk seviyesi, hangi beceriyi kazandırdığı "
        "ve CV'de nasıl konumlandırılacağı; (2) dil pratiği için somut bir "
        "haftalık rutin (hangi kaynak, günde kaç dakika, hangi çıktı); "
        "(3) öğrenmeyi tamamlama oranını artıran 2-3 taktik. '📚 Kaynaklar' "
        "bölümünde önerdiğin her kaynak için kısa bir 'neden' ve 'ücretsiz "
        "olduğunu doğrulayın' notu ekle; tercihen Coursera, edX, Khan Academy, "
        "freeCodeCamp gibi bilinen ücretsiz/açık platformların ana adreslerini "
        "kullan.\n\n"
        + RICH_BRIEFING_GUIDE
    )
    if items:
        listing = "\n".join(
            f"- {item.title}" + (f" ({item.link})" if item.link else "")
            for item in items
        )
        prompt += (
            "\n\nAşağıdaki eğitim/sertifika duyuruları BUGÜN İLK KEZ geliyor; "
            "ilgili olanları önerilerine yedir ve '📚 Kaynaklar' bölümünde bu "
            f"GERÇEK bağlantıları tercih et:\n{listing}"
        )
    return prompt


class FreeCertsAdvisor(LLMAdvisor):
    key = "free_certs"
    title = "Ücretsiz Sertifika & Eğitim Araştırmacısı"
    system_prompt = SYSTEM_PROMPT

    # Its announcement feed is a genuine source of NEW findings between runs.
    incremental_source = True

    def __init__(self) -> None:
        # Fetched once per run and reused by the batched path.
        self._items: List[FeedItem] = []
        self._fetched = False

    @property
    def user_prompt(self) -> str:  # built at run time so USER_SECTOR is honored
        return _user_prompt(self._fetch_items())

    # -- deduplication ---------------------------------------------------
    def new_finding_count(self) -> int:
        return len(self._fetch_items())

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
