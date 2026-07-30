"""Career & HR advisor — kıdemli İK direktörü."""

from __future__ import annotations

from ._llm_base import LLMAdvisor

SYSTEM_PROMPT = (
    "Sen kıdemli bir İnsan Kaynakları direktörüsün ve aynı zamanda kariyer "
    "gelişimi mentorusun. Uzmanlığın; kariyer planlama, ücretsiz eğitim ve "
    "kurs fırsatları, yabancı dil pratiği ve etkili CV geliştirme. Türkçe "
    "konuşuyorsun. Somut, güncel ve uygulanabilir öneriler ver; genel geçer "
    "tavsiyelerden kaçın. Gerçekçi ve destekleyici bir ton kullan."
)

USER_PROMPT = (
    "Bugün için kısa bir günlük kariyer gelişimi briefingi hazırla. Şu "
    "alanlardan en uygun olan birine ya da birkaçına odaklan: ücretsiz "
    "eğitim/kurs fırsatları, yabancı dil pratiği, CV geliştirme. Bugün "
    "atılabilecek somut bir adım öner. En fazla 150 kelime, net ve "
    "uygulanabilir Türkçe kullan."
)


class CareerHrAdvisor(LLMAdvisor):
    key = "career_hr"
    title = "Kariyer & İK Danışmanı"
    system_prompt = SYSTEM_PROMPT
    user_prompt = USER_PROMPT
