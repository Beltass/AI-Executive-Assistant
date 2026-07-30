"""Shared base for LLM-backed advisor personas.

Each persona provides a strong Turkish SYSTEM prompt plus a daily USER
prompt and reuses ``integrations.llm`` for generation. If no LLM provider
key is configured the briefing is ``skipped``; any request/transport error
degrades to ``failed``.
"""

from __future__ import annotations

from . import Advisor, Briefing
from ..integrations import llm


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
