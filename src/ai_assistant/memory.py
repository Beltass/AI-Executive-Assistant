"""Findings memory — the ledger of what the team has ALREADY told the user.

The briefing now runs several times a day (see ``BRIEFING_MODE`` in
:mod:`ai_assistant.config`), and nothing annoys a reader faster than being told
the same thing at 10:00, 14:00, 18:00 and 22:00. This module keeps a small,
durable ledger of the findings that have already been DELIVERED, so every later
run can talk about genuinely new material only.

WHAT IS RECORDED
    Per advisor, a set of short *fingerprints* with the date they were first
    delivered:

    * RSS/news style findings -> the item URL, normalised (lowercased host,
      no ``www.``, no tracking parameters, no fragment) AND the normalised
      title, so the same story re-published under a different tracking link is
      still recognised.
    * LLM prose -> a hash of the meaningful text (whitespace/case normalised)
      plus the links it referenced, so a regenerated-but-identical section can
      be spotted.

    The briefing TEXT itself is never stored — only irreversible hashes — which
    keeps the ledger safe to commit back to a public repository, exactly like
    the accountability coach's streak file.

RETENTION
    Entries older than ``FINDINGS_MEMORY_DAYS`` (default 30) are dropped on
    load, so the file cannot grow forever and a genuinely recurring topic is
    allowed to resurface after the window.

WHEN IT IS WRITTEN
    Fingerprints are *staged* while the advisors work and only committed after
    Slack ACCEPTED the digest (:mod:`ai_assistant.notifiers.slack_notifier`).
    A finding that was never delivered is therefore still new next time —
    nothing is silently lost.

FAIL-SAFE
    A missing, corrupt, unreadable or unwritable ledger can NEVER break a run:
    every failure degrades to "everything is new" plus a log line. Repeating
    yourself is a much smaller sin than not briefing at all.

Configuration (via environment):
    FINDINGS_MEMORY_FILE  Ledger path (default ``.assistant_state/findings.json``).
    FINDINGS_MEMORY_DAYS  Retention window in days (default 30).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

MEMORY_FILE_ENV = "FINDINGS_MEMORY_FILE"
DEFAULT_MEMORY_FILE = ".assistant_state/findings.json"

RETENTION_ENV = "FINDINGS_MEMORY_DAYS"
DEFAULT_RETENTION_DAYS = 30

SCHEMA_VERSION = 1

# Query parameters that identify the CAMPAIGN, not the article. Stripping them
# means the same story shared through two channels collapses to one finding.
_TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_", "ga_")
_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "dclid",
    "gclsrc",
    "igshid",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "oc",
    "ocid",
    "ref",
    "ref_src",
    "referrer",
    "sourceid",
    "spm",
    "cmpid",
    "cid",
    "s_cid",
    "yclid",
    "_hsenc",
    "_hsmi",
    "at_medium",
    "at_campaign",
}

# Google News titles carry a " - Publisher" suffix; two aggregators can format
# the same headline differently, so trailing publisher noise is dropped.
_TITLE_TAIL = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,40}$")
_NON_WORD = re.compile(r"[^0-9a-zçğıöşü]+", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_URL_IN_TEXT = re.compile(r"https?://[^\s<>()\[\]\"'`]+")

# Fingerprint kinds, kept as one-letter prefixes so the ledger stays tiny.
KIND_URL = "u"
KIND_TITLE = "t"
KIND_CONTENT = "c"

_FINGERPRINT_CHARS = 16


# --- configuration ----------------------------------------------------------


def memory_file_path() -> str:
    """Where the ledger lives (``FINDINGS_MEMORY_FILE`` or the default)."""
    return (os.getenv(MEMORY_FILE_ENV) or "").strip() or DEFAULT_MEMORY_FILE


def retention_days() -> int:
    """Rolling retention window in days (``FINDINGS_MEMORY_DAYS``, default 30)."""
    raw = (os.getenv(RETENTION_ENV) or "").strip()
    if not raw:
        return DEFAULT_RETENTION_DAYS
    try:
        days = int(raw)
    except ValueError:
        return DEFAULT_RETENTION_DAYS
    return days if days > 0 else DEFAULT_RETENTION_DAYS


# --- normalisation ----------------------------------------------------------


def normalize_url(url: str) -> str:
    """Return a canonical form of ``url`` for comparison purposes.

    Lowercases the scheme and host, drops ``www.``, removes tracking query
    parameters and the fragment, and trims a trailing slash. Anything that does
    not parse is returned whitespace-trimmed and lowercased, which is still a
    stable key.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

        parts = urlsplit(raw)
        if not parts.netloc:
            return raw.lower()
        host = parts.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        query = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=False)
            if key.lower() not in _TRACKING_PARAMS
            and not key.lower().startswith(_TRACKING_PREFIXES)
        ]
        path = parts.path.rstrip("/")
        return urlunsplit(
            (parts.scheme.lower(), host, path, urlencode(query), "")
        )
    except Exception:  # pragma: no cover - defensive only
        return raw.lower()


def normalize_title(title: str) -> str:
    """Return a canonical form of a headline: no publisher tail, no noise."""
    raw = _WHITESPACE.sub(" ", (title or "")).strip()
    if not raw:
        return ""
    raw = _TITLE_TAIL.sub("", raw)
    return _NON_WORD.sub(" ", raw.lower()).strip()


def normalize_text(text: str) -> str:
    """Collapse whitespace and case so cosmetic edits do not look like news."""
    return _WHITESPACE.sub(" ", (text or "")).strip().lower()


def _digest(kind: str, value: str) -> str:
    return (
        f"{kind}:"
        + hashlib.sha256(value.encode("utf-8")).hexdigest()[:_FINGERPRINT_CHARS]
    )


def url_fingerprint(url: str) -> str:
    """Fingerprint of a link, or ``""`` when there is no usable URL."""
    normalized = normalize_url(url)
    return _digest(KIND_URL, normalized) if normalized else ""


def title_fingerprint(title: str) -> str:
    """Fingerprint of a headline, or ``""`` when there is no usable title."""
    normalized = normalize_title(title)
    return _digest(KIND_TITLE, normalized) if normalized else ""


def item_fingerprints(title: str = "", link: str = "") -> List[str]:
    """Every fingerprint identifying one feed item (URL first, then title).

    Both are returned on purpose: matching on EITHER catches both the same
    article behind two tracking links and the same headline syndicated under
    two URLs.
    """
    return [fp for fp in (url_fingerprint(link), title_fingerprint(title)) if fp]


def text_fingerprints(text: str) -> List[str]:
    """Fingerprints for LLM prose: the content hash plus the links it cited."""
    normalized = normalize_text(text)
    if not normalized:
        return []
    prints = [_digest(KIND_CONTENT, normalized)]
    seen = set(prints)
    for match in _URL_IN_TEXT.findall(text or ""):
        fingerprint = url_fingerprint(match.rstrip(".,;:)"))
        if fingerprint and fingerprint not in seen:
            seen.add(fingerprint)
            prints.append(fingerprint)
    return prints


# --- the ledger -------------------------------------------------------------


class FindingsMemory:
    """Persistent "already delivered" ledger, keyed by advisor.

    Instances are cheap; the process-wide one used by the advisors is
    :func:`shared`. Loading is lazy and every I/O path is guarded — see the
    module docstring for the fail-safe contract.
    """

    def __init__(
        self,
        path: Optional[str] = None,
        days: Optional[int] = None,
    ) -> None:
        self._path = path
        self._days = days
        self._loaded = False
        self._readable = True
        # {advisor_id: {fingerprint: "YYYY-MM-DD"}}
        self._seen: Dict[str, Dict[str, str]] = {}
        # Staged this run, committed only after a successful delivery.
        self._pending: Dict[str, Dict[str, str]] = {}
        # Per-advisor count of genuinely new findings observed this run.
        self._new_counts: Dict[str, int] = {}

    # -- configuration ---------------------------------------------------
    @property
    def path(self) -> str:
        return self._path or memory_file_path()

    @property
    def days(self) -> int:
        return self._days if self._days is not None else retention_days()

    # -- loading / saving ------------------------------------------------
    def _load(self) -> None:
        """Read the ledger once. Any problem degrades to an EMPTY ledger."""
        if self._loaded:
            return
        self._loaded = True
        path = self.path
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return  # day one: nothing has been delivered yet
        except Exception as exc:
            # Corrupt or unreadable: treat everything as new rather than
            # crashing the run, and say so in the log.
            logger.warning(
                "bulgu hafızası okunamadı (%s): %s — her şey yeni sayılacak",
                path,
                exc,
            )
            self._readable = False
            return
        self._seen = self._parse(data)

    def _parse(self, data: Any) -> Dict[str, Dict[str, str]]:
        """Validate the on-disk shape and drop entries past the window."""
        if not isinstance(data, dict):
            logger.warning("bulgu hafızası beklenen biçimde değil — sıfırlanıyor")
            return {}
        advisors = data.get("advisors")
        if not isinstance(advisors, dict):
            return {}

        cutoff = date.today() - timedelta(days=self.days)
        parsed: Dict[str, Dict[str, str]] = {}
        for advisor_id, entries in advisors.items():
            if not isinstance(entries, dict):
                continue
            kept: Dict[str, str] = {}
            for fingerprint, stamp in entries.items():
                seen_on = _parse_date(stamp)
                if seen_on is None or seen_on < cutoff:
                    continue  # outside the rolling window: may resurface
                kept[str(fingerprint)] = seen_on.isoformat()
            if kept:
                parsed[str(advisor_id)] = kept
        return parsed

    def save(self) -> bool:
        """Persist the ledger. Returns ``False`` (and logs) if it could not."""
        path = self.path
        document = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": datetime.now().date().isoformat(),
            "retention_days": self.days,
            "advisors": self._seen,
        }
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(document, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            return True
        except Exception as exc:
            # An unwritable path costs us dedup NEXT run, never this briefing.
            logger.warning("bulgu hafızası yazılamadı (%s): %s", path, exc)
            return False

    # -- queries ---------------------------------------------------------
    def is_new(self, advisor_id: str, fingerprint: str) -> bool:
        """True when this advisor has not delivered ``fingerprint`` before."""
        if not fingerprint:
            return True
        self._load()
        if fingerprint in self._seen.get(advisor_id, {}):
            return False
        return fingerprint not in self._pending.get(advisor_id, {})

    def are_new(self, advisor_id: str, fingerprints: Sequence[str]) -> bool:
        """True only when EVERY fingerprint is unknown (match any -> old)."""
        usable = [fp for fp in fingerprints if fp]
        if not usable:
            return True
        return all(self.is_new(advisor_id, fp) for fp in usable)

    # -- recording -------------------------------------------------------
    def stage(self, advisor_id: str, fingerprints: Iterable[str]) -> None:
        """Remember fingerprints as *delivered pending* for this run.

        Staged fingerprints already count as "not new" inside the same run (so
        two advisors sharing a feed do not both report the item twice), but
        they only reach the file once :meth:`commit` is called.
        """
        bucket = self._pending.setdefault(advisor_id, {})
        today = date.today().isoformat()
        for fingerprint in fingerprints:
            if fingerprint:
                bucket.setdefault(fingerprint, today)

    def mark_seen(self, advisor_id: str, fingerprints: Iterable[str]) -> None:
        """Record fingerprints as delivered and persist the ledger."""
        self._load()
        bucket = self._seen.setdefault(advisor_id, {})
        today = date.today().isoformat()
        for fingerprint in fingerprints:
            if fingerprint:
                bucket[fingerprint] = today
        self.save()

    def note_new(self, advisor_id: str, count: int) -> None:
        """Record how many genuinely new findings an advisor had this run."""
        self._new_counts[advisor_id] = self._new_counts.get(advisor_id, 0) + count

    def new_count(self, advisor_id: str) -> int:
        return self._new_counts.get(advisor_id, 0)

    @property
    def new_counts(self) -> Dict[str, int]:
        return dict(self._new_counts)

    @property
    def has_pending(self) -> bool:
        return any(self._pending.values())

    def commit(self) -> bool:
        """Move everything staged into the ledger and write it to disk.

        Called ONLY after a successful delivery. Returns ``True`` when the file
        was written (or there was nothing to write).
        """
        if not self.has_pending:
            return True
        self._load()
        for advisor_id, entries in self._pending.items():
            bucket = self._seen.setdefault(advisor_id, {})
            bucket.update(entries)
        self._pending = {}
        return self.save()

    def discard_pending(self) -> None:
        """Forget the staged fingerprints — the findings were never delivered."""
        self._pending = {}

    # -- the workhorse ---------------------------------------------------
    def filter_new_items(self, advisor_id: str, items: Sequence[Any]) -> List[Any]:
        """Return only the feed items this advisor has not reported yet.

        ``items`` are anything exposing ``title``/``link`` (in practice
        :class:`~ai_assistant.advisors._rss.FeedItem`). Survivors are staged, so
        a later run — or a second advisor in the same run — will not repeat
        them once the digest is delivered.
        """
        fresh: List[Any] = []
        for item in items:
            fingerprints = item_fingerprints(
                getattr(item, "title", "") or "",
                getattr(item, "link", "") or "",
            )
            if not fingerprints:
                continue
            if not self.are_new(advisor_id, fingerprints):
                continue
            self.stage(advisor_id, fingerprints)
            fresh.append(item)
        self.note_new(advisor_id, len(fresh))
        return fresh


def _parse_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10])
    except Exception:
        return None


# --- the process-wide ledger ------------------------------------------------
#
# One instance per run so the advisors, the notifier and the status report all
# talk about the same staged findings.

_shared: Optional[FindingsMemory] = None


def shared() -> FindingsMemory:
    """The ledger every advisor in this process shares."""
    global _shared
    if _shared is None:
        _shared = FindingsMemory()
    return _shared


def reset(path: Optional[str] = None, days: Optional[int] = None) -> FindingsMemory:
    """Replace the shared ledger — used by tests and by long-lived processes."""
    global _shared
    _shared = FindingsMemory(path=path, days=days)
    return _shared


def is_new(advisor_id: str, fingerprint: str) -> bool:
    """Module-level shortcut onto the shared ledger."""
    return shared().is_new(advisor_id, fingerprint)


def mark_seen(advisor_id: str, fingerprints: Iterable[str]) -> None:
    """Module-level shortcut onto the shared ledger."""
    shared().mark_seen(advisor_id, fingerprints)


def filter_new_items(advisor_id: str, items: Sequence[Any]) -> List[Any]:
    """Module-level shortcut onto the shared ledger."""
    return shared().filter_new_items(advisor_id, items)


def new_count(advisor_id: str) -> int:
    """How many new findings ``advisor_id`` reported in this process."""
    return shared().new_count(advisor_id)


def commit() -> bool:
    """Persist everything staged in this run (call after a successful send)."""
    return shared().commit()


__all__ = [
    "DEFAULT_MEMORY_FILE",
    "DEFAULT_RETENTION_DAYS",
    "FindingsMemory",
    "MEMORY_FILE_ENV",
    "RETENTION_ENV",
    "commit",
    "filter_new_items",
    "is_new",
    "item_fingerprints",
    "mark_seen",
    "memory_file_path",
    "new_count",
    "normalize_title",
    "normalize_url",
    "reset",
    "retention_days",
    "shared",
    "text_fingerprints",
    "title_fingerprint",
    "url_fingerprint",
]
