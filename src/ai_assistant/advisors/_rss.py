"""Shared RSS/Atom feed fetching + parsing helper for advisors.

Uses ``httpx`` (via the shared :func:`http_get`) for the request and the
stdlib :mod:`xml.etree.ElementTree` for parsing, so no heavy feed-parsing
dependency is added. This helper RAISES on transport/parse errors; callers are
expected to guard with ``try/except`` and degrade to ``failed``/``skipped``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List

from ..integrations._common import http_get


@dataclass
class FeedItem:
    """One headline from an RSS/Atom feed."""

    title: str
    link: str = ""


def _localname(tag: str) -> str:
    """Strip any XML namespace, returning the lowercase local tag name."""
    return tag.split("}")[-1].lower()


def fetch_feed_items(url: str, limit: int = 8) -> List[FeedItem]:
    """Fetch and parse an RSS or Atom feed, returning up to ``limit`` items.

    Handles both RSS (``<item>`` with a text ``<link>``) and Atom
    (``<entry>`` with a ``<link href=...>``). Namespaces are ignored.
    """
    resp = http_get(url)
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    items: List[FeedItem] = []
    for elem in root.iter():
        if _localname(elem.tag) not in ("item", "entry"):
            continue
        title = ""
        link = ""
        for child in elem:
            ctag = _localname(child.tag)
            if ctag == "title" and child.text and not title:
                title = child.text.strip()
            elif ctag == "link" and not link:
                href = child.attrib.get("href")
                if href:
                    link = href.strip()
                elif child.text:
                    link = child.text.strip()
        if title:
            items.append(FeedItem(title=title, link=link))
        if len(items) >= limit:
            break
    return items
