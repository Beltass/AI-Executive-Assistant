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

Controlled by ``DIGEST_BATCH_MODE`` (default enabled).

WHAT HAPPENS WHEN THE BATCH FAILS — read this before changing it
----------------------------------------------------------------
Falling back to "one call per advisor" turns ONE failed request into fifteen,
which on a free tier is the most expensive thing this codebase can do: the
batch usually fails because the quota is gone, and the fallback then spends
fifteen more calls discovering that fifteen more times. So the fallback is now
OPT-IN via ``DIGEST_BATCH_FALLBACK_MODE``:

* ``off`` (default) — an advisor that was IN the batch and got no section back
  is reported as ``skipped`` with the reason "batch failed". No extra call.
* ``per_advisor`` — the old behaviour, for debugging a parsing problem where
  the quota is known to be healthy.

Advisors that never joined the batch (non-LLM ones, or those the model was
never asked about) are unaffected either way: they always run their own path.

:func:`run_batch` keeps returning ``{key: text}``, but it no longer fails
silently — :attr:`BatchOutcome.failure_reason` on :func:`last_outcome` says
WHY the dict is empty, so the caller can tell "batching is off" from "the model
refused".
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field, replace
from typing import Dict, List, Sequence, Tuple

from . import Advisor, BatchSection, is_quiet
from ..config import is_incremental
from ..integrations import llm

logger = logging.getLogger(__name__)


@dataclass
class BatchOutcome:
    """What the batched call did in this process — pure observability.

    Recorded by :func:`run_batch` and read by
    :mod:`ai_assistant.status_report` so the monitoring dashboard can show
    whether the single shared Gemini call worked and how much of the team it
    covered. Contains counts and a public model name only, never a key.

    ``prompt_chars`` additionally records how LONG each advisor's slice of the
    prompt was. That is what lets :mod:`ai_assistant.metrics` split ONE batched
    call's input tokens back out per advisor and answer "which agent is
    expensive?" — see that module for why the split is an estimate.
    """

    enabled: bool = True
    attempted: bool = False
    sections_requested: int = 0
    sections_produced: int = 0
    #: ``{advisor_key: characters}`` — the size of each section's own prompt,
    #: shared boilerplate excluded.
    prompt_chars: Dict[str, int] = field(default_factory=dict)
    #: Size of the whole prompt actually sent, boilerplate included.
    prompt_chars_total: int = 0
    #: Characters saved by stating the shared writing guide ONCE instead of
    #: once per section (see :func:`split_shared_guide`).
    guide_saved_chars: int = 0
    #: WHY the batch produced nothing, ``""`` when it produced sections. One of
    #: the ``REASON_*`` constants below. This is what stops :func:`run_batch`
    #: from returning an empty dict with no explanation.
    failure_reason: str = ""
    #: Short, already key-redacted detail for the log/dashboard. Never content.
    failure_detail: str = ""

    @property
    def used(self) -> bool:
        """True when the batched call actually served at least one section."""
        return self.sections_produced > 0

    @property
    def failed(self) -> bool:
        """True when the batch RAN and came back with nothing usable.

        Deliberately not the same as "empty result": batching being switched
        off, or fewer than two participating advisors, are normal states in
        which the per-advisor path is simply the right one.
        """
        return self.attempted and not self.used

    @property
    def participants(self) -> Tuple[str, ...]:
        """Keys of the advisors whose sections were actually sent to the model.

        Empty when nothing was attempted. An advisor NOT in here never took
        part in the batch, so a batch failure says nothing about it and it must
        still run its own path.
        """
        return tuple(self.prompt_chars)

    def missing(self, key: str) -> bool:
        """True when ``key`` was sent in the batch but got no section back."""
        return self.attempted and key in self.prompt_chars

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "attempted": self.attempted,
            "used": self.used,
            "sections_requested": self.sections_requested,
            "sections_produced": self.sections_produced,
            "prompt_chars_total": self.prompt_chars_total,
            "guide_saved_chars": self.guide_saved_chars,
            "failure_reason": self.failure_reason,
            "failure_detail": self.failure_detail,
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

# --- why a batch produced nothing -------------------------------------------
#: Batching is switched off (``DIGEST_BATCH_MODE``) — not a failure.
REASON_DISABLED = "disabled"
#: Nobody offered a section (empty ``.env``, or a quiet incremental run).
REASON_NO_SECTIONS = "no_sections"
#: Exactly one section: batching one advisor is no cheaper than calling it.
REASON_SINGLE_SECTION = "single_section"
#: The model call itself raised (quota, timeout, transport).
REASON_LLM_ERROR = "llm_error"
#: The model answered but not one section marker could be parsed out.
REASON_UNPARSABLE = "unparsable_response"

# --- what to do when it DID fail --------------------------------------------
FALLBACK_MODE_ENV = "DIGEST_BATCH_FALLBACK_MODE"
#: Default: skip the advisors the batch could not serve. One failed call stays
#: one failed call instead of becoming one per advisor.
FALLBACK_OFF = "off"
#: Opt-in: retry each unserved advisor on its own, the pre-gate behaviour.
FALLBACK_PER_ADVISOR = "per_advisor"

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


def fallback_mode() -> str:
    """What to do with advisors the batch could not serve.

    ``DIGEST_BATCH_FALLBACK_MODE``; anything other than ``per_advisor`` (case
    and dash insensitive) means :data:`FALLBACK_OFF`, which is the default.
    """
    raw = (os.getenv(FALLBACK_MODE_ENV) or "").strip().lower().replace("-", "_")
    return FALLBACK_PER_ADVISOR if raw == FALLBACK_PER_ADVISOR else FALLBACK_OFF


def per_advisor_fallback_enabled() -> bool:
    """Whether a failed batch may re-ask every advisor on its own."""
    return fallback_mode() == FALLBACK_PER_ADVISOR


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


def split_shared_guide(
    sections: Sequence[BatchSection], incremental: bool = False
) -> Tuple[List[BatchSection], str, int]:
    """Lift the writing guide out of every section and state it ONCE.

    THE PROBLEM IT SOLVES. Twelve of the personas append the very same ~2.4 KB
    ``RICH_BRIEFING_GUIDE`` to their user prompt. That was harmless when each
    advisor made its own call, but the whole team now rides on ONE batched
    request — so the identical essay was being transmitted a dozen times in a
    single prompt, costing roughly 8-9 thousand input tokens per run to repeat
    instructions the model had already read.

    This hoists the guide into the shared header and leaves a one-line pointer
    behind in each section. The instructions the model receives are unchanged;
    only the repetition is gone.

    On an ``incremental`` run the SHORT variant is hoisted instead: a top-up
    reporting two or three genuinely new items does not need the depth coaching
    written for the flagship briefing.

    Returns ``(trimmed_sections, shared_guide_text, characters_saved)``.
    ``shared_guide_text`` is empty when fewer than two sections carried the
    guide, in which case nothing is changed at all.
    """
    from ._llm_base import RICH_BRIEFING_GUIDE, SHARED_GUIDE_POINTER, briefing_guide

    carriers = [s for s in sections if RICH_BRIEFING_GUIDE in (s.user_prompt or "")]
    if len(carriers) < 2:
        return list(sections), "", 0

    shared = briefing_guide(incremental)
    trimmed: List[BatchSection] = []
    removed = 0
    for section in sections:
        prompt = section.user_prompt or ""
        if RICH_BRIEFING_GUIDE in prompt:
            removed += len(RICH_BRIEFING_GUIDE) * prompt.count(RICH_BRIEFING_GUIDE)
            prompt = prompt.replace(RICH_BRIEFING_GUIDE, SHARED_GUIDE_POINTER)
            trimmed.append(replace(section, user_prompt=prompt.strip()))
        else:
            trimmed.append(section)

    pointer_cost = len(SHARED_GUIDE_POINTER) * len(carriers)
    saved = removed - pointer_cost - len(shared)
    return trimmed, shared, max(0, saved)


def _output_contract(sections: Sequence[BatchSection], incremental: bool) -> str:
    """The response-format rules, kept identical in substance for both modes.

    The incremental wording is deliberately terser: the same five rules, fewer
    words, because they are re-sent on every one of the day's three top-up runs.
    """
    keys = ", ".join(section.key for section in sections)
    header = (
        f"Bu, günün ARA çalıştırması: yalnızca YENİ gelişmeler var. {len(sections)} "
        "bölümü TEK yanıtta, kısa ve öz yaz.\n\n"
        if incremental
        else "Bugünün günlük brifingini TEK bir yanıtta hazırla. Aşağıda "
        f"{len(sections)} ayrı bölüm var; HER BİRİNİ eksiksiz yaz.\n\n"
    )
    return (
        header + "ÇIKTI SÖZLEŞMESİ (kesinlikle uy):\n"
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
    )


def build_batch_prompt(
    sections: Sequence[BatchSection], incremental: bool = False
) -> str:
    """Compose the single user prompt covering every advisor section.

    The shared writing guide is stated once for the whole batch rather than
    repeated inside every section (:func:`split_shared_guide`), which is the
    single biggest input-token saving available here.
    """
    trimmed, shared_guide, _saved = split_shared_guide(sections, incremental)
    parts: List[str] = [_output_contract(trimmed, incremental)]

    if shared_guide:
        parts.append(
            f"\n{'=' * 60}\n"
            "ORTAK YAZIM KURALLARI — aşağıdaki TÜM bölümler için geçerlidir, "
            "bir kez yazıldı:\n"
            f"{'=' * 60}\n{shared_guide}\n"
        )

    for index, section in enumerate(trimmed, start=1):
        parts.append(
            f"\n{'=' * 60}\n"
            f"BÖLÜM {index}/{len(trimmed)} — kimlik: {section.key} — "
            f"başlık: {section.title}\n"
            f"{'=' * 60}\n"
            f"Bu bölümde şu uzman kimliğine bürün:\n{section.system_prompt}\n\n"
            f"Bu uzmanın bugünkü görevi:\n{section.user_prompt}\n"
        )

    parts.append(
        f"\n{'=' * 60}\n"
        f"Hatırlatma: yanıtın `{SECTION_MARKER} {trimmed[0].key}` satırıyla "
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
    two participating advisors), or the call/parse failed. The dict alone
    cannot tell those cases apart, so the REASON is always recorded on
    :func:`last_outcome` (``failure_reason``/``failure_detail``) and logged —
    the caller reads it to decide between "run the per-advisor path, that is
    normal" and "the model is down, do not make fifteen more calls".

    This function never raises.
    """
    global _last_outcome
    _last_outcome = BatchOutcome(enabled=batch_mode_enabled())

    if not _last_outcome.enabled:
        _last_outcome.failure_reason = REASON_DISABLED
        _last_outcome.failure_detail = "DIGEST_BATCH_MODE kapalı"
        logger.info("toplu brifing kapalı (DIGEST_BATCH_MODE): tekil mod kullanılacak")
        return {}

    sections = collect_sections(advisors)
    _last_outcome.sections_requested = len(sections)
    if len(sections) < 2:
        # One section is no cheaper batched, and zero means nothing to ask.
        _last_outcome.failure_reason = (
            REASON_SINGLE_SECTION if sections else REASON_NO_SECTIONS
        )
        _last_outcome.failure_detail = (
            f"toplu istek için yeterli bölüm yok ({len(sections)})"
        )
        logger.info(
            "toplu brifing atlandı: %s bölüm var, en az 2 gerekiyor", len(sections)
        )
        return {}

    _last_outcome.attempted = True
    incremental = is_incremental()

    # Build once, and record the SIZES on the way through so the metrics layer
    # can attribute one batched call's input tokens back to the advisors.
    trimmed, _shared_guide, saved = split_shared_guide(sections, incremental)
    _last_outcome.guide_saved_chars = saved
    _last_outcome.prompt_chars = {
        section.key: len(section.system_prompt or "") + len(section.user_prompt or "")
        for section in trimmed
    }

    user_prompt = build_batch_prompt(sections, incremental)
    _last_outcome.prompt_chars_total = len(user_prompt)
    if saved:
        logger.info(
            "ortak yazım kuralları tek sefer gönderildi: ~%s karakter tasarruf",
            saved,
        )
    try:
        text = llm.generate_text(
            BATCH_SYSTEM_PROMPT,
            user_prompt,
            max_output_tokens=_batch_max_output_tokens(),
        )
    except Exception as exc:
        # Already key-redacted by the llm layer. The caller decides what to do
        # with the advisors this call was carrying — see ``fallback_mode``.
        _last_outcome.failure_reason = REASON_LLM_ERROR
        _last_outcome.failure_detail = str(exc)[:200]
        logger.error(
            "toplu brifing isteği başarısız (%s bölüm taşınıyordu): %s",
            len(sections),
            exc,
        )
        return {}

    parsed = parse_batch_response(text, [section.key for section in sections])
    _last_outcome.sections_produced = len(parsed)
    if not parsed:
        _last_outcome.failure_reason = REASON_UNPARSABLE
        _last_outcome.failure_detail = (
            "model yanıtında hiçbir bölüm işaretçisi ayrıştırılamadı"
        )
        logger.error(
            "toplu brifing yanıtı ayrıştırılamadı: %s bölüm istendi, 0 bölüm okundu",
            len(sections),
        )
        return parsed

    logger.info(
        "toplu brifing: %s bölümden %s tanesi tek çağrıda üretildi",
        len(sections),
        len(parsed),
    )
    if len(parsed) < len(sections):
        missing = [s.key for s in sections if s.key not in parsed]
        logger.warning(
            "toplu brifingde eksik kalan bölümler: %s", ", ".join(missing)
        )
    return parsed
