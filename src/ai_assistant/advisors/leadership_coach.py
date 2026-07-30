"""Leadership coach advisor — kıdemli yönetici / liderlik koçu."""

from __future__ import annotations

from ._llm_base import LLMAdvisor

SYSTEM_PROMPT = (
    "Sen kıdemli bir yönetici ve deneyimli bir liderlik koçusun. Yıllarca üst "
    "düzey ekipleri yönetmiş, insanları geliştirmiş ve zorlu kararlar almış "
    "birisin. Türkçe konuşuyorsun. Görevin, yoğun çalışan bir yöneticiye her gün "
    "kısa, uygulanabilir ve ilham verici bir liderlik briefingi vermek. "
    "Klişelerden kaçın, somut ve pratik ol, sıcak ama profesyonel bir ton kullan."
)

USER_PROMPT = (
    "Bugün için kısa bir günlük liderlik briefingi hazırla. İçinde şunlar olsun: "
    "(1) bir liderlik içgörüsü ya da güncel bir hatırlatma, (2) bugün hemen "
    "uygulanabilecek somut bir alıştırma veya davranış. En fazla 150 kelime, "
    "sade ve motive edici Türkçe kullan."
)


class LeadershipCoachAdvisor(LLMAdvisor):
    key = "leadership_coach"
    title = "Liderlik Koçu"
    system_prompt = SYSTEM_PROMPT
    user_prompt = USER_PROMPT
