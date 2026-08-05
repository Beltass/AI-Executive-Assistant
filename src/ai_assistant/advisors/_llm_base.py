"""Shared base for LLM-backed advisor personas.

Each persona provides a strong Turkish SYSTEM prompt plus a daily USER
prompt and reuses ``integrations.llm`` for generation. If no LLM provider
key is configured the briefing is ``skipped``; any request/transport error
degrades to ``failed``.

Personas also expose :meth:`LLMAdvisor.batch_section` so the Operations
Manager can fold every persona into ONE batched Gemini call instead of one
call per advisor (see :mod:`ai_assistant.advisors._batch`).
"""

from __future__ import annotations

from typing import Optional

from . import Advisor, BatchSection, Briefing
from ..integrations import llm

# Shared structure appended to persona USER prompts so every daily briefing is
# deep, curiosity-provoking, source-linked and developmental — well-formatted
# for Slack (Markdown headings/bullets). Personas can inline it via
# ``RICH_BRIEFING_GUIDE``.
#
# The goal is a substantial read (~300-500 words per advisor), not a paragraph:
# multiple structured subsections with concrete specifics — named frameworks,
# numbers, worked examples, step-by-step reasoning — instead of generic advice.
RICH_BRIEFING_GUIDE = (
    "YAZIM VE DERİNLİK KURALLARI (hepsine uy):\n"
    "Brifingi Slack'te güzel görünecek şekilde Markdown ile biçimlendir "
    "(kısa başlıklar, madde işaretleri, gerektiğinde numaralı adımlar) ve "
    "yaklaşık 300-500 kelime yaz. Kısa, genel geçer bir paragrafla YETİNME; "
    "aşağıdaki bölümlerin HEPSİNİ sırayla ver:\n"
    "0. *İlk satır — ana bulgu*: brifingin İLK satırı tam olarak şu biçimde "
    "olsun: `**Öne çıkan:** <tek cümlelik ana bulgu>` (en fazla 200 karakter, "
    "kendi başına anlaşılır). Bu satır Slack özetinde başlık olarak "
    "kullanılıyor, o yüzden atlanamaz.\n"
    "1. *Merak uyandıran giriş* (2-3 cümle): çarpıcı bir soru, şaşırtıcı bir "
    "bulgu veya küçük bir vaka ile başla; okuyucuyu içeri çek.\n"
    "2. *Derinlemesine bölümler* (EN AZ 3 alt başlık): her alt başlıkta "
    "somut ve spesifik ol — adı olan bir çerçeve/model/yöntem (ve kimin "
    "geliştirdiği), sayılar veya oranlar, gerçek hayattan kısa bir örnek ya da "
    "diyalog, ve adım adım nasıl uygulanacağı. 'İletişim önemlidir' gibi "
    "klişelerden kaçın; 'şu durumda şunu şöyle söyle' düzeyinde netlik ver. "
    "Uygun olduğunda yaygın bir hatayı ve nasıl düzeltileceğini de göster.\n"
    "3. *Neden işe yarar*: kısa bir gerekçe — arkasındaki mantık, araştırma "
    "geleneği veya sektör pratiği; abartmadan ve emin olmadığın iddiaları "
    "'kesin' diye sunmadan.\n"
    "4. *📚 Kaynaklar*: 2-4 özenle seçilmiş kaynak öner (kitap: başlık + "
    "yazar; Coursera, edX, Khan Academy gibi saygın platformlar; resmi "
    "dokümanlar; bilinen YouTube kanalları; makaleler; araçlar) ve her birine "
    "BAĞLANTI ile birlikte tek cümlelik bir 'neden bu?' notu ekle. "
    "SADECE gerçek ve KALICI olduğundan emin olduğun bağlantıları ver; "
    "tercihen resmi ana sayfalar / bilinen kök alan adları (örn. "
    "https://www.coursera.org, https://www.edx.org, "
    "https://developers.google.com). Belirli bir derin URL'in var olduğundan "
    "emin değilsen tam yolu UYDURMA; bunun yerine platformun ana adresini ver "
    "ve önerilen bir arama terimi ekle. Bu bölümün sonuna "
    "'🔎 Bağlantıları açılışta doğrulayın.' notunu ekle.\n"
    "5. *✅ Bugünün görevi*: bugün 15-30 dakikada yapılabilecek TEK bir somut "
    "eylem; ne yapılacağını, nasıl yapılacağını ve başarının nasıl "
    "anlaşılacağını (küçük bir ölçüt) yaz.\n"
    "Tümü akıcı, sıcak ve anlaşılır Türkçe olsun; yapay kurumsal dilden kaçın."
)

# The SHORT version of the same contract, used on ``incremental`` runs.
#
# WHY: an incremental top-up reports only what is NEW since the morning. Two or
# three sections of a few hundred words each do not need the full 2.4 KB essay
# above — sending it anyway costs roughly 700 input tokens per section for
# instructions the model barely gets to apply. This keeps the parts that the
# rest of the pipeline actually DEPENDS on (the ``Öne çıkan:`` headline the
# Slack index lifts out, real links only, the daily task) and drops the depth
# coaching that only matters for the flagship briefing.
COMPACT_BRIEFING_GUIDE = (
    "YAZIM KURALLARI (kısa mod):\n"
    "- İLK satır tam olarak: `**Öne çıkan:** <tek cümlelik ana bulgu>` "
    "(en fazla 200 karakter).\n"
    "- Sonra 120-200 kelime: yalnızca YENİ olan gelişme, neden önemli olduğu "
    "ve somut çıkarım. Sabah anlatılanları tekrarlama.\n"
    "- Kaynak verirsen SADECE gerçek ve kalıcı bağlantı ver; emin değilsen "
    "platformun ana adresini ve bir arama terimi yaz.\n"
    "- Kapanışta `✅ Bugünün görevi`: 15-30 dakikalık tek somut eylem.\n"
    "- Akıcı, sade Türkçe; klişe ve dolgu cümle yok."
)

#: What replaces the guide inside each section once it has been lifted out and
#: stated ONCE for the whole batch (see
#: :func:`ai_assistant.advisors._batch.split_shared_guide`).
SHARED_GUIDE_POINTER = "(Yukarıdaki ORTAK YAZIM KURALLARI bu bölüm için de geçerli.)"


def briefing_guide(incremental: bool = False) -> str:
    """The writing contract for this run: full for ``full``, short otherwise."""
    return COMPACT_BRIEFING_GUIDE if incremental else RICH_BRIEFING_GUIDE


class LLMAdvisor(Advisor):
    """Base persona that turns a system/user prompt pair into a briefing."""

    # Subclasses override these.
    system_prompt: str = ""
    user_prompt: str = ""

    def _generate(self) -> Briefing:
        if not llm.is_configured():
            return self.skipped("missing env var(s): GEMINI_API_KEY or OPENAI_API_KEY")
        try:
            text = llm.generate_text(self.system_prompt, self.user_prompt)
        except Exception as exc:
            return self.failed(f"LLM isteği başarısız: {exc}")
        return self.ok(text)

    def batch_section(self) -> Optional[BatchSection]:
        """Join the batched call whenever a provider key is configured."""
        if not llm.is_configured():
            return None
        return BatchSection(
            key=self.key,
            title=self.title,
            system_prompt=self.system_prompt,
            user_prompt=self.user_prompt,
        )
