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

import os

from ._llm_base import LLMAdvisor

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
    sector = (os.getenv("USER_SECTOR") or "").strip() or DEFAULT_SECTOR
    return (
        f"Alan/sektör: {sector}\n\n"
        "Bu alana uygun 4-6 öneri hazırla: ücretsiz sertifikalar/kurslar ve "
        "dil öğrenme kaynakları. Her madde için: kaynak adı, kısa 'neden' ve "
        "'bağlantının hâlâ ücretsiz olduğunu doğrulayın' notu. En fazla 200 "
        "kelime, net ve uygulanabilir Türkçe kullan."
    )


class FreeCertsAdvisor(LLMAdvisor):
    key = "free_certs"
    title = "Ücretsiz Sertifika & Eğitim Araştırmacısı"
    system_prompt = SYSTEM_PROMPT

    @property
    def user_prompt(self) -> str:  # built at run time so USER_SECTOR is honored
        return _user_prompt()
