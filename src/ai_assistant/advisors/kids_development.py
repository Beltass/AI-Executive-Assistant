"""Kids development advisor — çocuk gelişimi & eğitim danışmanı."""

from __future__ import annotations

from ._llm_base import LLMAdvisor, RICH_BRIEFING_GUIDE

SYSTEM_PROMPT = (
    "Sen deneyimli bir çocuk gelişimi ve eğitim danışmanısın. Uzmanlığın; "
    "çocuklarda özgüven, sağlıklı duygusal gelişim ve başarılı eğitim. Türkçe "
    "konuşuyorsun. Danışanın, 10 ve 4 yaşında iki kızı olan bir ebeveyn. "
    "Yaş farkını gözeterek, bilimsel ama sıcak, yargılamayan ve pratik "
    "önerilerde bulun. Suçluluk hissettiren dil kullanma; ebeveyni destekle."
)

USER_PROMPT = (
    "Bugün için doyurucu bir günlük ebeveynlik briefingi hazırla. 10 ve 4 "
    "yaşındaki iki kız için özgüven, sağlıklı gelişim ve başarılı eğitim "
    "odağında yaz; mümkünse iki yaş için de küçük bir uyarlama ver. Kaynaklar "
    "arasında ebeveynlik/çocuk gelişimi kitapları veya güvenilir eğitim "
    "platformları önerebilirsin.\n\n"
    + RICH_BRIEFING_GUIDE
)


class KidsDevelopmentAdvisor(LLMAdvisor):
    key = "kids_development"
    title = "Çocuk Gelişimi Danışmanı"
    system_prompt = SYSTEM_PROMPT
    user_prompt = USER_PROMPT
