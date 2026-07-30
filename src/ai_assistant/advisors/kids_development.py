"""Kids development advisor — çocuk gelişimi & eğitim danışmanı."""

from __future__ import annotations

from ._llm_base import LLMAdvisor

SYSTEM_PROMPT = (
    "Sen deneyimli bir çocuk gelişimi ve eğitim danışmanısın. Uzmanlığın; "
    "çocuklarda özgüven, sağlıklı duygusal gelişim ve başarılı eğitim. Türkçe "
    "konuşuyorsun. Danışanın, 10 ve 4 yaşında iki kızı olan bir ebeveyn. "
    "Yaş farkını gözeterek, bilimsel ama sıcak, yargılamayan ve pratik "
    "önerilerde bulun. Suçluluk hissettiren dil kullanma; ebeveyni destekle."
)

USER_PROMPT = (
    "Bugün için kısa bir günlük ebeveynlik briefingi hazırla. 10 ve 4 yaşındaki "
    "iki kız için özgüven, sağlıklı gelişim ve başarılı eğitim odağında: "
    "(1) bugüne dair pratik bir ipucu, (2) çocuklarla birlikte yapılabilecek "
    "somut bir aktivite. Mümkünse iki yaş için de küçük bir uyarlama ver. "
    "En fazla 150 kelime, sıcak ve anlaşılır Türkçe kullan."
)


class KidsDevelopmentAdvisor(LLMAdvisor):
    key = "kids_development"
    title = "Çocuk Gelişimi Danışmanı"
    system_prompt = SYSTEM_PROMPT
    user_prompt = USER_PROMPT
