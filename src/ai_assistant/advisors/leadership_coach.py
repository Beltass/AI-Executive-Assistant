"""Leadership coach advisor — kıdemli yönetici / liderlik koçu."""

from __future__ import annotations

from ._llm_base import LLMAdvisor, RICH_BRIEFING_GUIDE

SYSTEM_PROMPT = (
    "Sen kıdemli bir yönetici ve deneyimli bir liderlik koçusun. Yıllarca üst "
    "düzey ekipleri yönetmiş, insanları geliştirmiş ve zorlu kararlar almış "
    "birisin. Türkçe konuşuyorsun. Görevin, yoğun çalışan bir yöneticiye her gün "
    "zengin, ilham verici ve gelişimsel bir liderlik briefingi vermek. "
    "Klişelerden kaçın, somut ve pratik ol, sıcak ama profesyonel bir ton kullan."
)

USER_PROMPT = (
    "Bugün için doyurucu bir günlük liderlik gelişimi briefingi hazırla; "
    "gerçek bir liderlik içgörüsüne, ilkeye veya çerçeveye odaklan.\n\n"
    + RICH_BRIEFING_GUIDE
)


class LeadershipCoachAdvisor(LLMAdvisor):
    key = "leadership_coach"
    title = "Liderlik Koçu"
    system_prompt = SYSTEM_PROMPT
    user_prompt = USER_PROMPT
