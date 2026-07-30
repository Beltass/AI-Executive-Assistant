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
    "Bugün için derinlikli bir günlük ebeveynlik briefingi hazırla. TEK bir "
    "tema seç (örneğin duygu düzenleme, özerklik desteği, ekran süresi, okuma "
    "alışkanlığı, kardeş çatışması) ve onu iki yaş için AYRI AYRI işle: "
    "10 yaş için ne yapılır, 4 yaş için ne yapılır. Her yaş uyarlamasında "
    "gelişimsel gerekçeyi kısaca açıkla (neden bu yaşta böyle davranıyor), "
    "ebeveynin kullanabileceği GERÇEK cümle kalıpları ver ('şunu şöyle "
    "söyleyin' formatında, 2-3 örnek), sık yapılan bir hatayı ve alternatifini "
    "göster, ve 10 dakikalık küçük bir birlikte-etkinlik öner. Suçluluk "
    "hissettirmeyen, destekleyici bir dil kullan. Kaynaklar arasında "
    "ebeveynlik/çocuk gelişimi kitapları veya güvenilir eğitim platformları "
    "önerebilirsin.\n\n"
    + RICH_BRIEFING_GUIDE
)


class KidsDevelopmentAdvisor(LLMAdvisor):
    key = "kids_development"
    title = "Çocuk Gelişimi Danışmanı"
    system_prompt = SYSTEM_PROMPT
    user_prompt = USER_PROMPT
