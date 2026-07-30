"""Shared base for LLM-backed advisor personas.

Each persona provides a strong Turkish SYSTEM prompt plus a daily USER
prompt and reuses ``integrations.llm`` for generation. If no LLM provider
key is configured the briefing is ``skipped``; any request/transport error
degrades to ``failed``.
"""

from __future__ import annotations

from . import Advisor, Briefing
from ..integrations import llm


# Shared structure appended to persona USER prompts so every daily briefing is
# rich, curiosity-provoking, source-linked and developmental — well-formatted
# for Slack (Markdown headings/bullets). Personas can inline it via
# ``RICH_BRIEFING_GUIDE``.
RICH_BRIEFING_GUIDE = (
    "Brifingi Slack'te güzel görünecek şekilde Markdown ile biçimlendir "
    "(kısa başlıklar ve madde işaretleri kullan) ve şu bölümleri MUTLAKA içer:\n"
    "1. *Merak uyandıran giriş*: ilgi çekici bir soru, çarpıcı bir bilgi veya "
    "içgörüyle başla; okuyucuyu okumaya devam etmeye teşvik et.\n"
    "2. *Derinlemesine rehberlik*: tek bir genel paragraf değil; kişiye ve "
    "konuya özel, somut, örnekli ve doyurucu açıklamalar ver.\n"
    "3. *📚 Kaynaklar*: 1-3 kaliteli kaynak öner (kitap: başlık + yazar; "
    "Coursera, edX, Khan Academy gibi saygın platformlar; resmi dokümanlar; "
    "bilinen YouTube kanalları; makaleler; araçlar) ve her birine BAĞLANTI ekle. "
    "SADECE gerçek ve KALICI olduğundan emin olduğun bağlantıları ver; tercihen "
    "resmi ana sayfalar / bilinen kök alan adları (örn. https://www.coursera.org, "
    "https://www.edx.org, https://developers.google.com). Belirli bir derin "
    "URL'in var olduğundan emin değilsen tam yolu UYDURMA; bunun yerine "
    "platformun ana adresini ver ve önerilen bir arama terimi ekle. Bu bölümün "
    "sonuna '🔎 Bağlantıları açılışta doğrulayın.' notunu ekle.\n"
    "4. *Bugünün görevi*: bugün yapılabilecek somut, gelişimsel bir eylem, "
    "alıştırma veya ödev ver.\n"
    "Tümü akıcı, sıcak ve anlaşılır Türkçe olsun."
)


class LLMAdvisor(Advisor):
    """Base persona that turns a system/user prompt pair into a briefing."""

    # Subclasses override these.
    system_prompt: str = ""
    user_prompt: str = ""

    def _generate(self) -> Briefing:
        if not llm.is_configured():
            return self.skipped(
                "missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY"
            )
        try:
            text = llm.generate_text(self.system_prompt, self.user_prompt)
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")
        return self.ok(text)
