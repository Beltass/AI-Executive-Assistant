"""Free certifications & training advisor — Ücretsiz Sertifika & Eğitim Araştırmacısı.

Configuration (via environment):
    USER_SECTOR     Sector/field to tailor suggestions to
                    (default "banka çağrı merkezleri").

LLM-backed: suggests currently-relevant FREE certifications / courses and
language-learning resources for the user's field, each with a short "why" and a
reminder to verify the link is still free. With no LLM provider key configured
the advisor is ``skipped``.
"""

from __future__ import annotations

from ..config import setting
from ._llm_base import LLMAdvisor, RICH_BRIEFING_GUIDE

DEFAULT_SECTOR = "banka çağrı merkezleri"

SYSTEM_PROMPT = (
    "Sen kariyer gelişimi ve ücretsiz eğitim fırsatları konusunda uzman bir "
    "araştırmacısın; adına 'Ücretsiz Sertifika & Eğitim Araştırmacısı' diyoruz. "
    "Türkçe konuşuyorsun. Görevin, kişinin alanına uygun GÜNCEL ve ÜCRETSIZ "
    "sertifika/kurs fırsatları ile dil öğrenme kaynakları önermek. Her öneri "
    "için kısa bir 'neden' ekle. Uydurma bağlantı verme; kullanıcıya bağlantının "
    "hâlâ ücretsiz olup olmadığını doğrulamasını hatırlat."
)


def _user_prompt() -> str:
    sector = setting("USER_SECTOR") or DEFAULT_SECTOR
    return (
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


class FreeCertsAdvisor(LLMAdvisor):
    key = "free_certs"
    title = "Ücretsiz Sertifika & Eğitim Araştırmacısı"
    system_prompt = SYSTEM_PROMPT

    @property
    def user_prompt(self) -> str:  # built at run time so USER_SECTOR is honored
        return _user_prompt()
