"""Published report documents — one readable page per advisor, per day.

Until now the whole briefing travelled as a single wall of text in one Slack
message. That is unreadable on a phone: fifteen advisors, each writing 300-500
words, collapse into a scroll nobody finishes.

This module splits the run apart. Every advisor that produced real content gets
its OWN document under::

    frontend/reports/<YYYY-MM-DD>/<advisor_id>.json

plus a per-day index and a top-level archive index. The static dashboard in
``frontend/`` renders those documents as typeset, mobile-first reading pages,
and Slack only carries a one-line headline per advisor with a link to the
document (see :mod:`ai_assistant.notifiers.slack_notifier`).

THREE HARD RULES, because the repository — and therefore the dashboard — is
PUBLIC:

1. **Private advisors are never published.** An advisor whose content can carry
   personal data (the Gmail/Calendar "Gün Başı Operasyon Brifingi") sets
   ``private = True``. Its section goes to Slack INLINE and never touches
   ``frontend/reports/``. :func:`is_private` is deliberately belt-and-braces: it
   trusts the flag AND a hard-coded key list, so a refactor that loses the flag
   still cannot leak the section.
2. **Only successful, non-quiet sections are published.** A ``failed`` or
   ``skipped`` briefing carries a diagnostic, not a report, and the dashboard's
   status view already shows those.
3. **No secrets, ever.** Published text is passed through
   :func:`ai_assistant.status_report.sanitize`-style scrubbing of the known key
   shapes before it is written.

And one operational rule, shared with the status file: publishing must NEVER
break the briefing. Every error is logged and swallowed.

An ``incremental`` run publishes only the advisors that had something new, so
the day's index is MERGED with what earlier runs already wrote rather than
replacing it — the 14:00 top-up must not delete the 10:00 briefing.

Old days are pruned (``REPORTS_RETENTION_DAYS``, default 30) so a daily commit
cannot grow the repository without bound.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .config import MODE_FULL, mode_label
from .integrations import STATUS_OK
from .status_report import ADVISOR_META, DEFAULT_META, ISTANBUL, sanitize

logger = logging.getLogger(__name__)

REPORTS_DIR_ENV = "REPORTS_DIR"
DEFAULT_REPORTS_DIR = "frontend/reports"

RETENTION_ENV = "REPORTS_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 30

#: Advisors whose content must never be published to the PUBLIC dashboard.
#: Duplicated deliberately: :attr:`ai_assistant.advisors.Advisor.private` is the
#: source of truth, this set is the safety net if that flag is ever lost.
#: Every advisor of the current roster that declares ``private = True`` MUST be
#: listed here (``tests/test_reports.py`` pins the two lists together).
_PRIVATE_ADVISOR_KEYS_CURRENT = frozenset(
    {
        "communications_calendar",  # real names, subjects and meetings
        "meeting_prep",             # calendar entries and meeting note content
        "data_analyst",             # the operation's own performance data
        "ai_innovation",            # reasons about the user's own backlog
        "executive_coaching",       # personal development + accountability
        "work_analyst",             # consolidates everyone else's private work
        "operations_director",      # synthesises every private section above
        "sre_watchdog",             # the system's own technical internals
    }
)

#: Keys of advisors that no longer run but were private while they did. Kept
#: forever: this list is a privacy net, and a stale card left in an archived
#: index by an older version must still be dropped on merge. Removing a name
#: here can only ever leak, never fix.
_PRIVATE_ADVISOR_KEYS_RETIRED = frozenset({"daily_ops_briefing"})

PRIVATE_ADVISOR_KEYS = _PRIVATE_ADVISOR_KEYS_CURRENT | _PRIVATE_ADVISOR_KEYS_RETIRED

#: The bolded one-liner every advisor is asked to open its section with.
HEADLINE_MARKER = "Öne çıkan"

#: Longest headline kept, so one runaway sentence cannot bloat a Slack block.
MAX_HEADLINE_CHARS = 240

#: Longest excerpt kept for a report card on the dashboard.
MAX_EXCERPT_CHARS = 200

#: Average Turkish reading speed used for the "3 dk okuma" estimate.
WORDS_PER_MINUTE = 200

#: Version of the document envelope written to ``<date>/<id>.json``.
#:
#: 1 — headline + excerpt + one blob of markdown.
#: 2 — the structured document: key metrics, sections, action items, sources
#:     and meta. EVERY v1 field is still written, so a v1 reader keeps working
#:     and a v2 reader degrades to ``markdown`` when a v1 file is opened from
#:     the archive.
SCHEMA_VERSION = 2

#: Most key metrics kept in the strip above the body — four is already the
#: point where a "strip" becomes a dashboard.
MAX_KEY_METRICS = 4

#: Most action items kept in the checklist block.
MAX_ACTION_ITEMS = 12

#: Longest single action kept. Generous on purpose: the roster's "Bugünün
#: görevi" is a whole paragraph (the longest in the archive is ~430 chars) and
#: an instruction cut in half is worse than a long checklist line. This is a
#: guard against a runaway, not a style rule.
MAX_ACTION_TEXT = 900

#: Most sources listed under the document.
MAX_SOURCES = 12

_DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --- configuration ----------------------------------------------------------


def reports_dir() -> str:
    """Where report documents are written (``REPORTS_DIR`` or the default)."""
    return (os.getenv(REPORTS_DIR_ENV) or "").strip() or DEFAULT_REPORTS_DIR


def retention_days() -> int:
    """How many days of reports are kept before pruning (default 30)."""
    raw = (os.getenv(RETENTION_ENV) or "").strip()
    try:
        days = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return days if days > 0 else DEFAULT_RETENTION_DAYS


# --- privacy ----------------------------------------------------------------


def is_private(briefing: Any) -> bool:
    """Whether this section must stay OUT of the published report files."""
    if bool(getattr(briefing, "private", False)):
        return True
    return str(getattr(briefing, "key", "") or "") in PRIVATE_ADVISOR_KEYS


def is_publishable(briefing: Any) -> bool:
    """Whether this section becomes a public document at all.

    Only a successful section with real content qualifies: private advisors,
    failures, "not configured" skips and the compact "yeni bulgu yok" lines all
    belong to Slack and the status view, not to a reading page.
    """
    if is_private(briefing):
        return False
    if getattr(briefing, "nothing_new", False):
        return False
    if str(getattr(briefing, "status", "")) != STATUS_OK:
        return False
    return bool(str(getattr(briefing, "text", "") or "").strip())


# --- headline extraction ----------------------------------------------------

# Markdown decoration stripped before a line is read as a headline.
_MD_LEAD = re.compile(r"^[\s>#*\-+_`•·]+")
_MD_TRAIL = re.compile(r"[\s*_`]+$")
_MD_INLINE = re.compile(r"(\*\*|__|\*|_|`)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")

# "Öne çıkan", "One cikan", "ÖNE ÇIKAN BULGU" … followed by ':' or '-'.
_HEADLINE_RE = re.compile(
    r"^\s*(?:o|ö)ne\s*(?:c|ç)(?:i|ı)kan(?:\s+bulgu)?\s*[:\-–—]\s*(.+)$",
    re.IGNORECASE,
)


def _plain(line: str) -> str:
    """Strip the markdown decoration off one line, keeping the words."""
    text = _MD_LINK.sub(r"\1", line)
    text = _MD_LEAD.sub("", text)
    text = _MD_TRAIL.sub("", text)
    text = _MD_INLINE.sub("", text)
    return text.strip()


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def extract_headline(markdown: str, limit: int = MAX_HEADLINE_CHARS) -> str:
    """Pull the one-line "öne çıkan bulgu" out of an advisor's section.

    The advisors are asked (in the batched prompt's output contract) to open
    every section with a bolded ``**Öne çıkan:** …`` line, which is exactly what
    the compact Slack index needs. Models forget instructions, so this falls
    back to the first real sentence of the section — never to nothing.

    Returns ``""`` only for an empty section.
    """
    lines = [line for line in str(markdown or "").splitlines()]

    # Pass 1: an explicit "Öne çıkan:" line anywhere near the top.
    for line in lines[:12]:
        plain = _plain(line)
        if not plain:
            continue
        match = _HEADLINE_RE.match(plain)
        if match and match.group(1).strip():
            return _clip(match.group(1), limit)

    # Pass 2: the first sentence of the first paragraph that is not a heading.
    for line in lines:
        raw = line.strip()
        if not raw or raw.startswith("#") or raw.startswith("---"):
            continue
        plain = _plain(line)
        if not plain:
            continue
        sentences = _SENTENCE_END.split(plain)
        first = sentences[0].strip() if sentences else plain
        return _clip(first or plain, limit)

    return ""


def _excerpt(markdown: str, headline: str) -> str:
    """A 1-2 sentence teaser for the report card, skipping the headline itself.

    Collects the first real PARAGRAPH, not the first line: the advisors hard-wrap
    their prose, so a line-based excerpt would stop mid-sentence.
    """
    paragraph: List[str] = []
    for line in str(markdown or "").splitlines():
        raw = line.strip()
        if not raw:
            if paragraph:
                break
            continue
        if raw.startswith("#") or raw.startswith("---"):
            if paragraph:
                break
            continue
        plain = _plain(line)
        if not plain:
            continue
        if not paragraph and _HEADLINE_RE.match(plain):
            continue
        if not paragraph and headline and plain.startswith(headline[:40]):
            continue
        paragraph.append(plain)
    if paragraph:
        return _clip(" ".join(paragraph), MAX_EXCERPT_CHARS)
    return _clip(headline, MAX_EXCERPT_CHARS)


# --- the structured document ------------------------------------------------
#
# THE COMPATIBILITY CONTRACT, because this is the part that is easy to break:
# advisors emit Markdown and NOTHING here asks them to stop. Every structured
# field below is either supplied by an advisor that happens to know about it
# (any attribute on the Briefing, see :func:`_structured`) or DERIVED from the
# Markdown. A report that carries only prose still produces a complete, clean
# document — it simply has no metric strip and no chart.


@dataclass
class KeyMetric:
    """One figure in the strip above the body: "Sıcaklık · 23 °C · ↑"."""

    label: str
    value: str
    unit: str = ""
    #: ``up`` / ``down`` / ``flat`` / ``""`` — a DIRECTION, never a judgement.
    #: Whether up is good is the advisor's business, not the renderer's.
    trend: str = ""
    note: str = ""
    #: Optional history, drawn as the sparkline inside the metric card.
    spark: List[float] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "label": self.label,
            "value": self.value,
            "unit": self.unit,
            "trend": self.trend,
        }
        if self.note:
            payload["note"] = self.note
        if self.spark:
            payload["spark"] = list(self.spark)
        return payload


@dataclass
class Section:
    """One part of the body: a heading, its prose, and optional exhibits.

    ``table`` is a :func:`AIACharts.dataTable` spec
    (``{columns, rows, caption, note}``) and ``chart`` is
    ``{type, data, options}`` where ``type`` names one of the chart builders.
    Both are passed through verbatim; the renderer validates them, because a
    malformed spec must cost an exhibit, never the document.
    """

    title: str = ""
    body: str = ""
    table: Optional[Dict[str, Any]] = None
    chart: Optional[Dict[str, Any]] = None

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"title": self.title, "body": self.body}
        if self.table:
            payload["table"] = self.table
        if self.chart:
            payload["chart"] = self.chart
        return payload


@dataclass
class ActionItem:
    """One line of the "Aksiyonlar" checklist."""

    text: str
    deadline: str = ""
    owner: str = ""

    def as_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"text": self.text}
        if self.deadline:
            payload["deadline"] = self.deadline
        if self.owner:
            payload["owner"] = self.owner
        return payload


@dataclass
class Source:
    """A link the report leans on, listed under the document."""

    title: str
    url: str
    #: What the advisor said ABOUT the source ("Bankacılık raporları sunar").
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        payload = {"title": self.title, "url": self.url}
        if self.note:
            payload["note"] = self.note
        return payload


# --- derivation from plain Markdown -----------------------------------------

_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*\S)\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+(.+)$")
_BARE_URL_RE = re.compile(r"https?://[^\s<>\)\]\"']+")
_TRAILING_PUNCT = ".,;:!?"

#: A heading that introduces things TO DO. Matched on the PLAIN text of the
#: line (emoji and markdown already stripped), so "#### ✅ Bugünün görevi" —
#: which every advisor in the current roster emits — lands here alongside
#: "### Aksiyonlar".
_ACTION_HEADING_RE = re.compile(
    r"^(?:bugünün|bugunun|haftanın|önerilen|onerilen|somut|kısa\s+vadeli)?\s*"
    r"(aksiyon(?:lar)?(?:\s+önerileri)?|yapılacaklar(?:\s+listesi)?|"
    r"görev(?:i|ler|leri)?|gorev(?:i|ler|leri)?|ödev|mikro\s+adım(?:lar)?|"
    r"eylem\s+(?:planı|maddeleri)|atılacak\s+adımlar|"
    r"action\s+items?|next\s+steps?|to\s?do)\s*[:：]?\s*$",
    re.IGNORECASE,
)

#: A heading that introduces the reference list.
_SOURCE_HEADING_RE = re.compile(
    r"^(kaynaklar|kaynakça|kaynakca|referanslar|okuma\s+listesi|sources?|"
    r"references?)\s*[:：]?\s*$",
    re.IGNORECASE,
)

#: "son tarih: 5 Ağustos", "termin — bugün", "deadline: 2026-08-05".
_DEADLINE_LABEL_RE = re.compile(
    r"[\(\[]?\s*(?:son\s+tarih|termin|deadline|hedef\s+tarih)\s*[:：\-–—]\s*"
    r"([^)\]\n]+?)\s*[\)\]]?\s*$",
    re.IGNORECASE,
)

#: A trailing "(bugün)" / "[bu hafta]" / "(2026-08-05)" hint. Only bracketed
#: forms, so an ordinary sentence about tomorrow is not read as a due date.
_DEADLINE_HINT_RE = re.compile(
    r"[\(\[]\s*((?:bugün|yarın|bu\s+hafta|bu\s+ay|gelecek\s+hafta|"
    r"pazartesi|salı|çarşamba|perşembe|cuma|cumartesi|pazar|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|"
    r"\d{1,2}\s+\w+(?:\s+\d{4})?)\s*)[\)\]]\s*$",
    re.IGNORECASE,
)

_OWNER_RE = re.compile(
    r"[\(\[]?\s*(?:sorumlu|owner|atanan)\s*[:：\-–—]\s*([^)\]\n]+?)\s*[\)\]]?\s*$",
    re.IGNORECASE,
)

#: "**Sıcaklık:** 23 °C ↑" — a labelled figure, which is the only shape safe to
#: lift out of prose as a metric. The value must START with a number.
_METRIC_LINE_RE = re.compile(
    r"^(?:[-*+•]\s+)?(?:\*\*|__)?\s*([^:*_\n]{2,42}?)\s*(?:\*\*|__)?\s*[:：]\s*"
    r"(?:\*\*|__)?\s*([+-]?\d[\d.,\s]*)\s*([^\s*_]{0,12})\s*(?:\*\*|__)?\s*"
    r"([↑↓→▲▼]|\+\d[\d.,]*%?|-\d[\d.,]*%?)?\s*$"
)

_TREND_GLYPHS = {"↑": "up", "▲": "up", "↓": "down", "▼": "down", "→": "flat"}


def _heading_key(title: str) -> str:
    """A heading reduced to its words: "#### ✅ Bugünün görevi" -> "Bugünün görevi".

    The advisors decorate every heading with an emoji, which no keyword list
    should have to enumerate.
    """
    return re.sub(r"^[\W_]+", "", _plain(title)).strip()


def _domain(url: str) -> str:
    body = re.sub(r"^https?://", "", str(url or "")).split("/", 1)[0]
    return body[4:] if body.startswith("www.") else body


def extract_sources(markdown: str, limit: int = MAX_SOURCES) -> List[Source]:
    """Every link the report cites, in the order it cites them.

    Inline ``[başlık](url)`` links keep their label; a bare URL is titled with
    its domain, which is what a reader actually scans for. De-duplicated by
    URL, because a source cited three times is still one source.
    """
    text = str(markdown or "")
    seen: Dict[str, Source] = {}
    order: List[str] = []

    for match in _MD_LINK.finditer(text):
        url = match.group(2).strip().split(" ", 1)[0]
        if not url.lower().startswith(("http://", "https://")):
            continue
        title = _plain(match.group(1)).strip() or _domain(url)
        if url not in seen:
            order.append(url)
            seen[url] = Source(title=_clip(title, 120), url=url)

    # Bare URLs, minus the ones already captured as the target of a [..](..).
    linked = {m.group(2).strip().split(" ", 1)[0] for m in _MD_LINK.finditer(text)}
    for match in _BARE_URL_RE.finditer(text):
        url = match.group(0).rstrip(_TRAILING_PUNCT)
        if url in linked or url in seen:
            continue
        order.append(url)
        seen[url] = Source(title=_domain(url) or url, url=url)

    return [seen[url] for url in order[:limit]]


def _parse_action_line(raw: str, limit: int = MAX_ACTION_TEXT) -> ActionItem:
    """One bullet -> text + (deadline) + (owner), with the labels stripped out.

    The badge only ever shows what the advisor WROTE; nothing here parses a
    date into a calendar object, because "bu hafta" is a perfectly good
    deadline and turning it into a timestamp would be an invention.
    """
    text = _plain(raw)
    deadline = ""
    owner = ""

    match = _OWNER_RE.search(text)
    if match:
        owner = _clip(match.group(1), 60)
        text = text[: match.start()].rstrip(" ,;·—–-")

    match = _DEADLINE_LABEL_RE.search(text)
    if match:
        deadline = _clip(match.group(1), 40)
        text = text[: match.start()].rstrip(" ,;·—–-")
    else:
        match = _DEADLINE_HINT_RE.search(text)
        if match:
            deadline = _clip(match.group(1), 40)
            text = text[: match.start()].rstrip(" ,;·—–-")

    return ActionItem(text=_clip(text, limit), deadline=deadline, owner=owner)


def _metric_from_line(raw: str) -> Optional[KeyMetric]:
    """A "**Etiket:** 23 °C ↑" line as a metric, or ``None`` for prose."""
    line = _MD_TRAIL.sub("", str(raw or "").strip())
    if not line or line.startswith("#"):
        return None
    match = _METRIC_LINE_RE.match(line)
    if not match:
        return None
    label = _plain(match.group(1)).strip(" :·-")
    value = " ".join(match.group(2).split())
    unit = (match.group(3) or "").strip(" .,;:")
    marker = (match.group(4) or "").strip()
    if not label or not value:
        return None
    trend = _TREND_GLYPHS.get(marker, "")
    if not trend and marker:
        trend = "up" if marker.startswith("+") else "down"
    return KeyMetric(label=_clip(label, 42), value=value, unit=unit, trend=trend)


def derive_key_metrics(markdown: str, limit: int = MAX_KEY_METRICS) -> List[KeyMetric]:
    """Lift the labelled figures out of a briefing — and nothing else.

    ONLY the explicit ``Etiket: 42 birim`` shape is read. Guessing numbers out
    of running prose would put invented figures at the top of a document that
    goes to a public dashboard, so a report without labelled figures correctly
    gets no metric strip at all.
    """
    out: List[KeyMetric] = []
    seen = set()
    for line in str(markdown or "").splitlines():
        metric = _metric_from_line(line)
        if not metric:
            continue
        key = metric.label.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(metric)
        if len(out) >= limit:
            break
    return out


def _drop_headline_line(body: str) -> str:
    """Remove a leading explicit ``**Öne çıkan:** …`` line from a section."""
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if _HEADLINE_RE.match(_plain(line)):
            return "\n".join(lines[index + 1 :]).strip("\n")
        break
    return body


def _source_from_line(raw: str) -> Optional[Source]:
    """One bullet of a "Kaynaklar" list as a source.

    The advisors write ``**Kuruluş:** *Gartner* — ne sunduğu [url](url)``, so
    the title is what stands before the first dash and the rest becomes the
    note. A line with no link is not a source.
    """
    urls = [
        m.group(2).strip().split(" ", 1)[0]
        for m in _MD_LINK.finditer(raw)
        if m.group(2).strip().lower().startswith(("http://", "https://"))
    ]
    if not urls:
        urls = [m.group(0).rstrip(_TRAILING_PUNCT) for m in _BARE_URL_RE.finditer(raw)]
    if not urls:
        return None
    # Strip the links out before the line is read as prose, or the URL text
    # would end up inside the title.
    prose = _MD_LINK.sub("", raw)
    prose = _BARE_URL_RE.sub("", prose)
    plain = _plain(prose).strip(" .,;:—–-")
    parts = re.split(r"\s+[—–-]\s+", plain, maxsplit=1)
    title = _clip(parts[0].strip(" .,;:"), 120) or _domain(urls[0])
    note = _clip(parts[1].strip(" .,;:"), 180) if len(parts) > 1 else ""
    return Source(title=title, url=urls[0], note=note)


def split_sections(markdown: str) -> tuple:
    """Split a briefing into ``(sections, action_items, sources)``.

    Headings start sections; anything before the first heading becomes the
    untitled opening section, so a report with NO headings at all is exactly
    one section and renders as it always did.

    Two headings are special, because every advisor of the current roster
    emits them and they are the two things a reader wants pulled out of the
    prose: a "Bugünün görevi" / "Aksiyonlar" section becomes the checklist,
    and a "Kaynaklar" section becomes the reference list. In both cases the
    lines are MOVED, never copied — the body never repeats them. A section
    that does not actually look like a list (or a link list) stays exactly
    where the advisor put it, which is the safe direction to fail.
    """
    sections: List[Section] = []
    actions: List[ActionItem] = []
    sources: List[Source] = []

    title = ""
    body: List[str] = []
    fenced = False

    def take_actions() -> bool:
        """Lift the LEADING block of an action section into the checklist.

        Only the leading block, because these sections routinely continue with
        material that is not a task at all ("Örnek cevap:", "Hazır arama
        bağlantıları", a closing note). Whatever follows is put back into the
        body under its own heading, so nothing the advisor wrote is lost —
        moving a line is fine, dropping one is not.
        """
        index = 0
        while index < len(body) and not body[index].strip():
            index += 1
        if index >= len(body):
            return False

        picked: List[ActionItem] = []
        if _BULLET_RE.match(body[index]):
            while index < len(body):
                line = body[index]
                match = _BULLET_RE.match(line)
                if match:
                    item = _parse_action_line(match.group(1))
                    if item.text:
                        picked.append(item)
                    index += 1
                    continue
                if line.startswith(("  ", "\t")) and line.strip() and picked:
                    # An indented continuation belongs to the bullet above it.
                    extra = _plain(line)
                    if extra:
                        picked[-1].text = _clip(
                            picked[-1].text + " " + extra, MAX_ACTION_TEXT
                        )
                    index += 1
                    continue
                if not line.strip():
                    # A blank line only continues the list if a bullet follows.
                    ahead = index + 1
                    while ahead < len(body) and not body[ahead].strip():
                        ahead += 1
                    if ahead < len(body) and _BULLET_RE.match(body[ahead]):
                        index = ahead
                        continue
                break
        else:
            paragraph: List[str] = []
            while index < len(body) and body[index].strip():
                paragraph.append(_plain(body[index]))
                index += 1
            text = _clip(" ".join(p for p in paragraph if p), MAX_ACTION_TEXT)
            if text:
                picked.append(_parse_action_line(text))

        if not picked:
            return False
        actions.extend(picked[: MAX_ACTION_ITEMS - len(actions)])

        # Whatever followed the task keeps its place in the document, but not
        # the "Bugünün görevi" heading — that meaning has moved to the
        # checklist and a second copy of it would only confuse the outline.
        rest = "\n".join(body[index:]).strip("\n")
        if rest.strip():
            sections.append(Section(title="", body=rest))
        return True

    def take_sources() -> bool:
        found = [s for s in (_source_from_line(line) for line in body) if s]
        leftovers = [
            line
            for line in body
            if line.strip() and not _source_from_line(line)
        ]
        # Convert only a list that really IS a list of links; two stray lines
        # (the "verify the links" nudge) are tolerated, a prose section is not.
        if not found or len(leftovers) > 2:
            return False
        known = {s.url for s in sources}
        for source in found:
            if source.url not in known and len(sources) < MAX_SOURCES:
                known.add(source.url)
                sources.append(source)
        return True

    def flush() -> None:
        text = "\n".join(body).strip("\n")
        if not title and not text.strip():
            return
        plain_title = _plain(title)
        keyword = _heading_key(title)
        if title and _ACTION_HEADING_RE.match(keyword) and take_actions():
            return
        if title and _SOURCE_HEADING_RE.match(keyword) and take_sources():
            return
        sections.append(Section(title=plain_title, body=text))

    for line in str(markdown or "").splitlines():
        if line.strip().startswith(("```", "~~~")):
            fenced = not fenced
        heading = None if fenced else _HEADING_RE.match(line)
        if heading:
            flush()
            title = heading.group(2)
            body = []
            continue
        body.append(line)
    flush()

    # The "Öne çıkan:" line opens the document as its lead, so leaving it in
    # the opening section too would print the same sentence twice, one line
    # apart. It is dropped from the SECTION only; ``markdown`` keeps it.
    if sections and not sections[0].title:
        sections[0].body = _drop_headline_line(sections[0].body)
        if not sections[0].body.strip():
            sections.pop(0)

    return sections, actions[:MAX_ACTION_ITEMS], sources


# --- structured input from an advisor (optional, never required) -------------


def _as_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "__dict__") and not isinstance(value, type):
        return {k: v for k, v in vars(value).items() if not k.startswith("_")}
    return {}


def _str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _coerce_metrics(raw: Any) -> List[KeyMetric]:
    out: List[KeyMetric] = []
    for item in list(raw or [])[:MAX_KEY_METRICS]:
        data = _as_mapping(item)
        label = _str(data.get("label") or data.get("name"))
        if not label:
            continue
        spark = [
            float(v)
            for v in list(data.get("spark") or [])
            if isinstance(v, (int, float))
        ]
        trend = _str(data.get("trend")).lower()
        out.append(
            KeyMetric(
                label=_clip(label, 42),
                value=_str(data.get("value")),
                unit=_str(data.get("unit")),
                trend=trend if trend in ("up", "down", "flat") else "",
                note=_clip(_str(data.get("note")), 80),
                spark=spark,
            )
        )
    return out


def _coerce_sections(raw: Any) -> List[Section]:
    out: List[Section] = []
    for item in list(raw or []):
        data = _as_mapping(item)
        title = _str(data.get("title"))
        body = _str(data.get("body") or data.get("markdown") or data.get("text"))
        table = data.get("table") if isinstance(data.get("table"), dict) else None
        chart = data.get("chart") if isinstance(data.get("chart"), dict) else None
        if not (title or body or table or chart):
            continue
        out.append(Section(title=title, body=body, table=table, chart=chart))
    return out


def _coerce_actions(raw: Any) -> List[ActionItem]:
    out: List[ActionItem] = []
    for item in list(raw or [])[:MAX_ACTION_ITEMS]:
        if isinstance(item, str):
            parsed = _parse_action_line(item)
            if parsed.text:
                out.append(parsed)
            continue
        data = _as_mapping(item)
        text = _clip(_str(data.get("text") or data.get("title")), 240)
        if not text:
            continue
        out.append(
            ActionItem(
                text=text,
                deadline=_clip(_str(data.get("deadline") or data.get("due")), 40),
                owner=_clip(_str(data.get("owner")), 60),
            )
        )
    return out


def _coerce_sources(raw: Any) -> List[Source]:
    out: List[Source] = []
    for item in list(raw or [])[:MAX_SOURCES]:
        if isinstance(item, str):
            url = item.strip()
            if url.lower().startswith(("http://", "https://")):
                out.append(Source(title=_domain(url) or url, url=url))
            continue
        data = _as_mapping(item)
        url = _str(data.get("url") or data.get("href"))
        if not url.lower().startswith(("http://", "https://")):
            continue
        out.append(
            Source(title=_clip(_str(data.get("title")) or _domain(url), 120), url=url)
        )
    return out


def _structured(briefing: Any) -> Dict[str, Any]:
    """Whatever structure an advisor CHOSE to attach, normalised.

    An advisor may set ``briefing.report`` to a mapping, or hang the individual
    fields (``key_metrics``, ``sections``, ``action_items``, ``sources``,
    ``headline``) straight off the briefing. None of it is required: today no
    advisor sets any of it, and every one of them still publishes a full
    document. Never raises — a malformed extra costs its own field only.
    """
    extra = _as_mapping(getattr(briefing, "report", None))
    out: Dict[str, Any] = {}
    for name, coerce in (
        ("key_metrics", _coerce_metrics),
        ("sections", _coerce_sections),
        ("action_items", _coerce_actions),
        ("sources", _coerce_sources),
    ):
        raw = extra.get(name, None)
        if raw is None:
            raw = getattr(briefing, name, None)
        if raw is None:
            continue
        try:
            value = coerce(raw)
        except Exception as exc:  # pragma: no cover - defensive only
            logger.warning("rapor alanı okunamadı (%s): %s", name, exc)
            continue
        if value:
            out[name] = value
    headline = _str(extra.get("headline") or getattr(briefing, "headline", ""))
    if headline:
        out["headline"] = _clip(headline, MAX_HEADLINE_CHARS)
    return out


def word_count(markdown: str) -> int:
    return len(str(markdown or "").split())


def read_minutes(words: int) -> int:
    """Reading-time estimate in whole minutes, never below 1."""
    return max(1, round(words / WORDS_PER_MINUTE)) if words else 1


# --- the published document -------------------------------------------------


@dataclass
class PublishedReport:
    """One advisor's report as it was written to disk.

    This is also what the Slack index is built from, so it carries everything
    the compact message needs: the emoji, the headline and where the document
    lives.
    """

    id: str
    name: str
    emoji: str
    category: str
    date: str
    headline: str
    excerpt: str
    words: int
    read_minutes: int
    generated_at: str = ""
    generated_at_istanbul: str = ""
    markdown: str = ""
    key_metrics: List[KeyMetric] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)
    action_items: List[ActionItem] = field(default_factory=list)
    sources: List[Source] = field(default_factory=list)
    #: Free-form document meta (advisor, timestamps, reading time, token cost).
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def route(self) -> str:
        """The dashboard's hash route for this document."""
        return f"#/rapor/{self.date}/{self.id}"

    def card(self) -> Dict[str, Any]:
        """The compact entry stored in the day's index (no body)."""
        return {
            "id": self.id,
            "name": self.name,
            "emoji": self.emoji,
            "category": self.category,
            "headline": self.headline,
            "excerpt": self.excerpt,
            "words": self.words,
            "read_minutes": self.read_minutes,
            "action_count": len(self.action_items),
            "generated_at": self.generated_at,
            "generated_at_istanbul": self.generated_at_istanbul,
            "path": f"{self.id}.json",
        }

    def document(self) -> Dict[str, Any]:
        """The full document written to ``<date>/<id>.json``.

        Every v1 key is still here. The structured fields are ADDITIVE, so an
        older reader ignores them and a newer one falls back to ``markdown``
        when it opens a day that was published before this schema existed.
        """
        payload = self.card()
        payload.pop("path", None)
        payload.update(
            {
                "schema_version": SCHEMA_VERSION,
                "date": self.date,
                "markdown": self.markdown,
                "key_metrics": [m.as_dict() for m in self.key_metrics],
                "sections": [s.as_dict() for s in self.sections],
                "action_items": [a.as_dict() for a in self.action_items],
                "sources": [s.as_dict() for s in self.sources],
                "meta": dict(self.meta),
            }
        )
        return payload

    def to_markdown(self) -> str:
        """The document as a standalone ``.md`` file (Drive, Slack previews).

        Mirrors the reading view: title block, metric table, sections, the
        action checklist and the sources — so the file a colleague opens in
        Drive is the same deliverable the dashboard shows, not a naked dump of
        the model's prose.
        """
        return render_markdown_document(self)


def _metrics_table(metrics: List[KeyMetric]) -> List[str]:
    """The key metrics as a real Markdown table (Drive renders these)."""
    if not metrics:
        return []
    arrow = {"up": "↑", "down": "↓", "flat": "→"}
    lines = ["| Gösterge | Değer | Eğilim |", "| --- | --- | --- |"]
    for metric in metrics:
        value = metric.value + (f" {metric.unit}" if metric.unit else "")
        lines.append(
            "| {label} | {value} | {trend} |".format(
                label=metric.label.replace("|", "\\|"),
                value=value.replace("|", "\\|") or "—",
                trend=arrow.get(metric.trend, "—"),
            )
        )
    return lines


def render_markdown_document(report: "PublishedReport") -> str:
    """Render a :class:`PublishedReport` as a structured Markdown file."""
    out: List[str] = [f"# {report.emoji} {report.name}".strip()]

    meta_bits = [
        f"**Tarih:** {report.date}",
        f"**Kategori:** {report.category}",
        f"**Okuma:** ~{report.read_minutes} dk ({report.words} kelime)",
    ]
    tokens = report.meta.get("tokens")
    if tokens:
        meta_bits.append(f"**Tahmini token:** {tokens}")
    out += ["", " · ".join(meta_bits)]

    if report.headline:
        out += ["", f"> **Öne çıkan:** {report.headline}"]

    if report.key_metrics:
        out += ["", "## Öne çıkan göstergeler", ""] + _metrics_table(report.key_metrics)

    sections = report.sections or [Section(title="", body=report.markdown)]
    for section in sections:
        body = (section.body or "").strip("\n")
        if not section.title and not body.strip():
            continue
        out.append("")
        if section.title:
            out.append(f"## {section.title}")
            out.append("")
        if body:
            out.append(body)
        if section.table:
            out += [""] + _spec_table_lines(section.table)

    if report.action_items:
        out += ["", "## Aksiyonlar", ""]
        for item in report.action_items:
            suffix = []
            if item.deadline:
                suffix.append(f"son tarih: {item.deadline}")
            if item.owner:
                suffix.append(f"sorumlu: {item.owner}")
            tail = f" _({' · '.join(suffix)})_" if suffix else ""
            out.append(f"- [ ] {item.text}{tail}")

    if report.sources:
        out += ["", "## Kaynaklar", ""]
        for index, source in enumerate(report.sources, start=1):
            note = f" — {source.note}" if source.note else ""
            out.append(f"{index}. [{source.title}]({source.url}){note}")

    stamp = report.generated_at_istanbul or report.generated_at
    if stamp:
        out += ["", "---", "", f"_Hazırlanma: {stamp} (İstanbul) · AI Executive Assistant_"]

    # Collapse the runs of blank lines the block assembly leaves behind.
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _spec_table_lines(spec: Dict[str, Any]) -> List[str]:
    """A ``dataTable`` spec as Markdown, so the export keeps its exhibits."""
    columns = [c for c in (spec.get("columns") or []) if isinstance(c, dict)]
    rows = spec.get("rows") or []
    if not columns or not rows:
        return []
    labels = [str(c.get("label") or c.get("key") or "") for c in columns]
    keys = [str(c.get("key") or "") for c in columns]
    lines = ["| " + " | ".join(labels) + " |", "| " + " | ".join("---" for _ in labels) + " |"]
    for row in rows[:50]:
        if isinstance(row, dict):
            cells = [str(row.get(key, "") if row.get(key) is not None else "") for key in keys]
        elif isinstance(row, (list, tuple)):
            cells = [str(cell) for cell in row][: len(labels)]
            cells += [""] * (len(labels) - len(cells))
        else:
            continue
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    return lines


def build_report(
    briefing: Any,
    day: str,
    moment: datetime,
    tokens: int = 0,
) -> PublishedReport:
    """Turn one successful, public briefing into a report document.

    Structure the advisor supplied wins; everything it did not supply is
    derived from the Markdown, so a prose-only briefing (which is all of them
    today) still gets a headline, sections and a source list.
    """
    key = str(getattr(briefing, "key", "") or "unknown")
    meta = ADVISOR_META.get(key, DEFAULT_META)
    markdown = _scrub(str(getattr(briefing, "text", "") or "").strip())
    given = _structured(briefing)
    headline = given.get("headline") or extract_headline(markdown)
    words = word_count(markdown)
    minutes = read_minutes(words)

    derived_sections, derived_actions, derived_sources = split_sections(markdown)
    # A reference list is the union of the "Kaynaklar" section and whatever the
    # prose links to inline, de-duplicated by URL and in citation order.
    known = {s.url for s in derived_sources}
    for source in extract_sources(markdown):
        if source.url not in known and len(derived_sources) < MAX_SOURCES:
            known.add(source.url)
            derived_sources.append(source)
    name = str(getattr(briefing, "title", "") or key)

    return PublishedReport(
        id=key,
        name=name,
        emoji=meta["emoji"],
        category=meta["category"],
        date=day,
        headline=headline,
        excerpt=_excerpt(markdown, headline),
        words=words,
        read_minutes=minutes,
        generated_at=moment.isoformat(timespec="seconds"),
        generated_at_istanbul=moment.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M"),
        markdown=markdown,
        key_metrics=given.get("key_metrics") or derive_key_metrics(markdown),
        sections=given.get("sections") or derived_sections,
        action_items=given.get("action_items") or derived_actions,
        sources=given.get("sources") or derived_sources,
        meta={
            "advisor": key,
            "advisor_name": name,
            "category": meta["category"],
            "generated_at": moment.isoformat(timespec="seconds"),
            "generated_at_istanbul": moment.astimezone(ISTANBUL).strftime(
                "%d.%m.%Y %H:%M"
            ),
            "words": words,
            "read_minutes": minutes,
            # An ESTIMATE: one batched call serves every advisor, so the cost is
            # attributed by share of produced text (the same rule metrics.py
            # uses). Zero means "not measured for this run".
            "tokens": int(tokens),
            "tokens_estimated": True,
        },
    )


def estimate_token_costs(briefings: Iterable[Any]) -> Dict[str, int]:
    """Attribute the last batched call's tokens across the sections it wrote.

    The advisors share ONE call, so a per-advisor cost can only ever be an
    estimate; it follows each section's share of the produced characters, which
    is the same attribution :mod:`ai_assistant.metrics` already publishes.
    Returns ``{}`` when there is nothing to attribute. Never raises.
    """
    try:
        from .integrations import llm

        stats = llm.last_call_stats()
        total = int(getattr(stats, "total_tokens", 0) or 0) if stats else 0
        if total <= 0:
            return {}
        chars = {
            str(getattr(b, "key", "") or "unknown"): len(
                str(getattr(b, "text", "") or "")
            )
            for b in briefings
            if str(getattr(b, "status", "")) == STATUS_OK
        }
        grand = sum(chars.values())
        if grand <= 0:
            return {}
        return {key: int(round(total * value / grand)) for key, value in chars.items()}
    except Exception as exc:  # pragma: no cover - defensive only
        logger.debug("token dağılımı hesaplanamadı: %s", exc)
        return {}


def _scrub(text: str) -> str:
    """Remove any credential shape from a body destined for a PUBLIC file.

    :func:`ai_assistant.status_report.sanitize` also collapses newlines and caps
    the length, which would destroy a report, so it is applied line by line and
    only for its redaction.
    """
    if not text:
        return ""
    out: List[str] = []
    for line in text.splitlines():
        if not line.strip():
            out.append("")
            continue
        # ``sanitize`` strips the line, but leading whitespace is meaningful in
        # markdown (nested lists, indented code), so it is put back.
        indent = line[: len(line) - len(line.lstrip())]
        out.append(indent + sanitize(line, limit=0))
    return "\n".join(out)


# --- writing ----------------------------------------------------------------


@dataclass
class Publication:
    """What one call to :func:`publish` produced."""

    date: str = ""
    directory: str = ""
    reports: List[PublishedReport] = field(default_factory=list)
    private: List[Any] = field(default_factory=list)
    pruned: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.reports)


def _write_json(path: str, payload: Any) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        logger.warning("rapor dosyası okunamadı (%s): %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _merge_cards(existing: Iterable[Any], fresh: List[PublishedReport]) -> List[dict]:
    """Keep earlier runs' cards, letting this run's fresher ones win.

    An incremental run publishes only what is new; without this merge the 14:00
    top-up would wipe the morning briefing off the day's page.
    """
    by_id: Dict[str, dict] = {}
    order: List[str] = []
    for entry in existing or []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("id") or "")
        if not key or key in PRIVATE_ADVISOR_KEYS:
            continue
        if key not in by_id:
            order.append(key)
        by_id[key] = entry
    for report in fresh:
        if report.id not in by_id:
            order.append(report.id)
        by_id[report.id] = report.card()
    return [by_id[key] for key in order]


def _day_directories(root: str) -> List[str]:
    try:
        names = os.listdir(root)
    except FileNotFoundError:
        return []
    except Exception as exc:  # pragma: no cover - defensive only
        logger.warning("rapor klasörü listelenemedi (%s): %s", root, exc)
        return []
    days = [
        name
        for name in names
        if _DATE_DIR_RE.match(name) and os.path.isdir(os.path.join(root, name))
    ]
    return sorted(days)


def prune(root: Optional[str] = None, keep: Optional[int] = None) -> List[str]:
    """Delete report days beyond the rolling window. Returns what was removed.

    The dashboard commits its data back to the repository on every run, so an
    unbounded archive would grow the clone forever. Never raises.
    """
    target = root or reports_dir()
    limit = keep if keep is not None else retention_days()
    days = _day_directories(target)
    if limit <= 0 or len(days) <= limit:
        return []
    removed: List[str] = []
    for day in days[: len(days) - limit]:
        try:
            shutil.rmtree(os.path.join(target, day))
            removed.append(day)
        except Exception as exc:  # pragma: no cover - defensive only
            logger.warning("eski rapor klasörü silinemedi (%s): %s", day, exc)
    return removed


def _write_archive_index(root: str, moment: datetime) -> None:
    """Rebuild the top-level archive index from what is actually on disk."""
    days: List[Dict[str, Any]] = []
    for day in reversed(_day_directories(root)):  # newest first
        index = _read_json(os.path.join(root, day, "index.json"))
        reports = index.get("reports")
        days.append(
            {
                "date": day,
                "count": len(reports) if isinstance(reports, list) else 0,
                "generated_at": str(index.get("generated_at") or ""),
                "generated_at_istanbul": str(index.get("generated_at_istanbul") or ""),
                "mode": str(index.get("mode") or ""),
            }
        )
    _write_json(
        os.path.join(root, "index.json"),
        {
            "schema_version": 1,
            "generated_at": moment.isoformat(timespec="seconds"),
            "retention_days": retention_days(),
            "days": days,
        },
    )


def publish(
    supervision: Any,
    root: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Publication:
    """Write every publishable advisor section as its own document.

    Returns a :class:`Publication` describing what was written, which the Slack
    notifier turns into a compact index. NEVER raises: a read-only checkout or a
    full disk costs the dashboard a day, never the briefing.
    """
    moment = now or datetime.now(ISTANBUL)
    day = moment.astimezone(ISTANBUL).strftime("%Y-%m-%d")
    target = root or reports_dir()
    directory = os.path.join(target, day)

    briefings = list(getattr(supervision, "briefings", []) or [])
    publication = Publication(date=day, directory=directory)
    publication.private = [b for b in briefings if is_private(b)]

    try:
        costs = estimate_token_costs(briefings)
        publication.reports = [
            build_report(b, day, moment, tokens=costs.get(str(getattr(b, "key", "")), 0))
            for b in briefings
            if is_publishable(b)
        ]

        existing_index = _read_json(os.path.join(directory, "index.json"))
        if not publication.reports and not existing_index:
            # An idle run (empty ``.env``, everything skipped) has nothing to
            # say, so it creates nothing: no empty directories, no churn in the
            # commit the workflow pushes back.
            return publication

        for report in publication.reports:
            _write_json(
                os.path.join(directory, f"{report.id}.json"), report.document()
            )

        cards = _merge_cards(existing_index.get("reports"), publication.reports)
        mode = str(getattr(supervision, "mode", MODE_FULL) or MODE_FULL)
        _write_json(
            os.path.join(directory, "index.json"),
            {
                "schema_version": 1,
                "date": day,
                "generated_at": moment.isoformat(timespec="seconds"),
                "generated_at_istanbul": moment.astimezone(ISTANBUL).strftime(
                    "%d.%m.%Y %H:%M"
                ),
                "mode": mode,
                "mode_label": mode_label(mode),
                "count": len(cards),
                "reports": cards,
            },
        )

        publication.pruned = prune(target)
        _write_archive_index(target, moment)
    except Exception as exc:
        logger.warning("rapor belgeleri yazılamadı (%s): %s", directory, exc)

    return publication


__all__ = [
    "DEFAULT_REPORTS_DIR",
    "HEADLINE_MARKER",
    "PRIVATE_ADVISOR_KEYS",
    "SCHEMA_VERSION",
    "ActionItem",
    "KeyMetric",
    "PublishedReport",
    "Publication",
    "Section",
    "Source",
    "build_report",
    "derive_key_metrics",
    "estimate_token_costs",
    "extract_headline",
    "extract_sources",
    "is_private",
    "is_publishable",
    "prune",
    "publish",
    "read_minutes",
    "render_markdown_document",
    "reports_dir",
    "retention_days",
    "split_sections",
    "word_count",
]
