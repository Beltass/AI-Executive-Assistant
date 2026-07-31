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
        "ai_innovation",            # reasons about the user's own backlog
        "executive_coaching",       # personal development + accountability
        "work_analyst",             # consolidates everyone else's private work
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
            "generated_at": self.generated_at,
            "generated_at_istanbul": self.generated_at_istanbul,
            "path": f"{self.id}.json",
        }

    def document(self) -> Dict[str, Any]:
        """The full document written to ``<date>/<id>.json``."""
        payload = self.card()
        payload.pop("path", None)
        payload.update(
            {
                "schema_version": 1,
                "date": self.date,
                "markdown": self.markdown,
            }
        )
        return payload


def build_report(briefing: Any, day: str, moment: datetime) -> PublishedReport:
    """Turn one successful, public briefing into a report document."""
    key = str(getattr(briefing, "key", "") or "unknown")
    meta = ADVISOR_META.get(key, DEFAULT_META)
    markdown = _scrub(str(getattr(briefing, "text", "") or "").strip())
    headline = extract_headline(markdown)
    words = word_count(markdown)
    return PublishedReport(
        id=key,
        name=str(getattr(briefing, "title", "") or key),
        emoji=meta["emoji"],
        category=meta["category"],
        date=day,
        headline=headline,
        excerpt=_excerpt(markdown, headline),
        words=words,
        read_minutes=read_minutes(words),
        generated_at=moment.isoformat(timespec="seconds"),
        generated_at_istanbul=moment.astimezone(ISTANBUL).strftime("%d.%m.%Y %H:%M"),
        markdown=markdown,
    )


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
        publication.reports = [
            build_report(b, day, moment) for b in briefings if is_publishable(b)
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
    "PublishedReport",
    "Publication",
    "build_report",
    "extract_headline",
    "is_private",
    "is_publishable",
    "prune",
    "publish",
    "read_minutes",
    "reports_dir",
    "retention_days",
    "word_count",
]
