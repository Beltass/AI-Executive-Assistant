"""Batched briefing mode — one LLM call for the whole advisor team.

WHY: the free Gemini tier allows only a couple of ``generateContent`` calls per
quota window. Asking every persona separately means nine calls per run, so most
sections come back 429 (rate limited) or 503 (model overloaded) no matter how
patiently we retry — retrying cannot beat a quota ceiling. Batching collapses
the whole team into ONE request, which fits the free quota and finishes in a
couple of minutes instead of twenty.

HOW: every LLM-backed advisor contributes a :class:`~ai_assistant.advisors.BatchSection`
(its persona + today's brief). Those are concatenated into a single prompt with
an explicit output contract — each section must start with a
``### SECTION: <advisor_key>`` marker — and the response is split back apart and
handed to each advisor, so per-advisor ``ok``/``failed``/``skipped`` statuses in
the digest and the Operations Manager summary are unchanged.

Non-LLM work stays OUT of the batch: the weather advisor still calls Open-Meteo
directly and the news advisors still fetch their RSS feeds themselves; only the
*summarization* participates.

Controlled by ``DIGEST_BATCH_MODE`` (default enabled). If the batched call
fails, the caller transparently falls back to the per-advisor path.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Sequence

from . import Advisor, BatchSection, is_quiet
from ..integrations import llm

logger = logging.getLogger(__name__)


@dataclass
class BatchOutcome:
    """What the batched call did in this process — pure observability.

    Recorded by :func:`run_batch` and read by
    :mod:`ai_assistant.status_report` so the monitoring dashboard can show
    whether the single shared Gemini call worked and how much of the team it
    covered. Contains counts and a public model name only, never a key.
    """

    enabled: bool = True
    attempted: bool = False
    sections_requested: int = 0
    sections_produced: int = 0

    @property
    def used(self) -> bool:
        """True when the batched call actually served at least one section."""
        return self.sections_produced > 0

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "attempted": self.attempted,
            "used": self.used,
            "sections_requested": self.sections_requested,
            "sections_produced": self.sections_produced,
        }


_last_outcome = BatchOutcome()


def last_outcome() -> BatchOutcome:
    """The outcome of the most recent :func:`run_batch` call in this process."""
    return _last_outcome

# Marker the model must emit before each section; also what we split on.
SECTION_MARKER = "### SECTION:"

# The bolded one-liner every section must open with. The compact Slack index
# lifts it straight out of the section (see
# :func:`ai_assistant.reports.extract_headline`), which is what turns the old
# wall of text into fifteen scannable lines.
HEADLINE_LABEL = "Öne çıkan"

# Tolerant matcher: accepts any heading depth, optional bold/brackets and
# trailing text, so a slightly creative model response still parses.
_SECTION_RE = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]*)?[*`_ \t]*SECTION[ \t]*:[ \t*`\[\"']*([A-Za-z0-9_]+)",
    re.MULTILINE,
)

# The batched answer carries the whole team's briefing, so it needs a much
# larger budget than a single section. Overridable via
# ``DIGEST_BATCH_MAX_OUTPUT_TOKENS``.
DEFAULT_BATCH_MAX_OUTPUT_TOKENS = 32768

_TRUTHY = {"1", "true", "yes", "on", "evet"}
_FALSY = {"0", "false", "no", "off", "hayir", "hayır"}

BATCH_SYSTEM_PROMPT = (
    "Sen, bir yöneticinin günlük brifingini birlikte hazırlayan uzman "
    "danışmanlardan oluşan bir ekibin baş editörüsün. Türkçe yazıyorsun. Her "
    "bölümde, o bölüm için tarif edilen uzmanın KİMLİĞİNE tam olarak bürünür "
    "ve o uzmanın sesiyle yazarsın. Bölümler birbirini tekrar etmez; her biri "
    "kendi başına doyurucu, somut ve uygulanabilirdir. Uydurma bilgi ve "
    "uydurma bağlantı vermezsin; emin olmadığın şeyleri kesinmiş gibi "
    "sunmazsın. Çıktı biçimi kurallarına harfiyen uyarsın."
)


def batch_mode_enabled() -> bool:
    """Whether batched mode is on (``DIGEST_BATCH_MODE``, default true)."""
    raw = (os.getenv("DIGEST_BATCH_MODE") or "").strip().lower()
    if raw in _FALSY:
        return False
    if raw in _TRUTHY:
        return True
    return True  # default ON


def _batch_max_output_tokens() -> int:
    try:
        tokens = int(
            os.getenv("DIGEST_BATCH_MAX_OUTPUT_TOKENS")
            or DEFAULT_BATCH_MAX_OUTPUT_TOKENS
        )
    except ValueError:
        tokens = DEFAULT_BATCH_MAX_OUTPUT_TOKENS
    return tokens if tokens > 0 else DEFAULT_BATCH_MAX_OUTPUT_TOKENS


def collect_sections(advisors: Sequence[Advisor]) -> List[BatchSection]:
    """Ask every advisor for its batchable section, skipping the opt-outs.

    An advisor that raises while preparing its section (e.g. a wobbly RSS
    fetch) is simply left out of the batch and later handled by its own
    per-advisor path.

    On an ``incremental`` run the advisors with nothing new to say are left out
    BEFORE the prompt is built (see :func:`~ai_assistant.advisors.is_quiet`), so
    their tokens are never spent. When nobody has anything new the section list
    is empty and :func:`run_batch` makes no model call at all.
    """
    sections: List[BatchSection] = []
    for advisor in advisors:
        try:
            if is_quiet(advisor):
                continue
            section = advisor.batch_section()
        except Exception as exc:  # never let one advisor break batching
            logger.warning(
                "'%s' danışmanı toplu isteğe hazırlanamadı: %s",
                getattr(advisor, "key", "unknown"),
                exc,
            )
            continue
        if section is not None:
            sections.append(section)
    return sections


def build_batch_prompt(sections: Sequence[BatchSection]) -> str:
    """Compose the single user prompt covering every advisor section."""
    keys = ", ".join(section.key for section in sections)
    parts: List[str] = [
        "Bugünün günlük brifingini TEK bir yanıtta hazırla. Aşağıda "
        f"{len(sections)} ayrı bölüm var; HER BİRİNİ eksiksiz yaz.\n\n"
        "ÇIKTI SÖZLEŞMESİ (kesinlikle uy):\n"
        f"- Her bölüme tam olarak şu satırla başla: `{SECTION_MARKER} <bölüm_kimliği>`\n"
        "- Bölüm kimliğini aynen kopyala, çevirme, değiştirme.\n"
        "- Marker satırından sonra o bölümün İLK satırı şu olmalı: "
        f"`**{HEADLINE_LABEL}:** <tek cümlelik ana bulgu>` — en fazla 200 "
        "karakter, kendi başına anlaşılır. Bu satır Slack'te o bölümün "
        "başlığı olarak kullanılıyor, o yüzden atlanamaz.\n"
        "- Bu satırdan sonra bölümün asıl içeriğini yaz.\n"
        f"- Bölümleri şu sırayla ve yalnızca şu kimliklerle ver: {keys}\n"
        "- Marker satırlarının dışında başka bir '### SECTION:' ifadesi kullanma.\n"
        "- Bölümler arasında özet, giriş veya kapanış metni ekleme.\n"
    ]

    for index, section in enumerate(sections, start=1):
        parts.append(
            f"\n{'=' * 60}\n"
            f"BÖLÜM {index}/{len(sections)} — kimlik: {section.key} — "
            f"başlık: {section.title}\n"
            f"{'=' * 60}\n"
            f"Bu bölümde şu uzman kimliğine bürün:\n{section.system_prompt}\n\n"
            f"Bu uzmanın bugünkü görevi:\n{section.user_prompt}\n"
        )

    parts.append(
        f"\n{'=' * 60}\n"
        f"Hatırlatma: yanıtın `{SECTION_MARKER} {sections[0].key}` satırıyla "
        "başlamalı ve her bölüm kendi marker satırıyla ayrılmalı."
    )
    return "".join(parts)


def parse_batch_response(text: str, valid_keys: Sequence[str]) -> Dict[str, str]:
    """Split a batched response into ``{advisor_key: section_text}``.

    Unknown markers and empty bodies are dropped; whatever is missing simply
    falls back to that advisor's own per-advisor path.
    """
    allowed = set(valid_keys)
    matches = list(_SECTION_RE.finditer(text or ""))
    result: Dict[str, str] = {}
    for index, match in enumerate(matches):
        key = match.group(1)
        if key not in allowed:
            continue
        # The body starts on the line AFTER the marker, so any decoration the
        # model appended to the marker line (``]``, ``**``…) is discarded.
        newline = text.find("\n", match.end())
        start = len(text) if newline == -1 else newline + 1
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            result[key] = body
    return result


def run_batch(advisors: Sequence[Advisor]) -> Dict[str, str]:
    """Run the whole team in ONE LLM call. Returns ``{key: text}``.

    Returns an empty dict whenever batching is off, not worth it (fewer than
    two participating advisors), or the call/parse failed — the caller then
    uses the normal per-advisor path. This function never raises.
    """
    global _last_outcome
    _last_outcome = BatchOutcome(enabled=batch_mode_enabled())

    if not _last_outcome.enabled:
        return {}

    sections = collect_sections(advisors)
    _last_outcome.sections_requested = len(sections)
    if len(sections) < 2:
        # One section is no cheaper batched, and zero means nothing to ask.
        return {}

    _last_outcome.attempted = True
    user_prompt = build_batch_prompt(sections)
    try:
        text = llm.generate_text(
            BATCH_SYSTEM_PROMPT,
            user_prompt,
            max_output_tokens=_batch_max_output_tokens(),
        )
    except Exception as exc:
        # Already key-redacted by the llm layer; per-advisor mode takes over.
        logger.warning("toplu brifing isteği başarısız, tekil moda dönülüyor: %s", exc)
        return {}

    parsed = parse_batch_response(text, [section.key for section in sections])
    _last_outcome.sections_produced = len(parsed)
    logger.info(
        "toplu brifing: %s bölümden %s tanesi tek çağrıda üretildi",
        len(sections),
        len(parsed),
    )
    return parsed
