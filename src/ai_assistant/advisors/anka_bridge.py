"""Anka bridge — Anka Köprüsü.

A configurable, generic HTTP connector to the user's external "Anka" assistant.
Because the exact Anka contract is user-provided, this is intentionally generic:
it fires a small JSON trigger at a user-configured endpoint and reports a short
status. All network I/O is guarded, so a broken endpoint degrades to ``failed``
and an unconfigured one to ``skipped``.

Configuration (via environment):
    ANKA_WEBHOOK_URL    Endpoint to call. ``ANKA_API_URL`` is accepted as an
                        alias. Without either, the advisor is ``skipped``.
    ANKA_API_KEY        Optional bearer token sent as ``Authorization: Bearer``.
    ANKA_HTTP_METHOD    Optional HTTP method (default ``POST``).

Trigger payload (POST): ``{"source": "ai_executive_assistant",
"action": "daily_trigger"}``.
"""

from __future__ import annotations

import os

import httpx

from . import Advisor, Briefing
from ..config import REQUEST_TIMEOUT

TRIGGER_PAYLOAD = {"source": "ai_executive_assistant", "action": "daily_trigger"}


class AnkaBridgeAdvisor(Advisor):
    key = "anka_bridge"
    title = "Anka Köprüsü"

    def _generate(self) -> Briefing:
        url = (os.getenv("ANKA_WEBHOOK_URL") or os.getenv("ANKA_API_URL") or "").strip()
        if not url:
            return self.skipped("Anka endpoint not configured (ANKA_WEBHOOK_URL/ANKA_API_URL)")

        method = (os.getenv("ANKA_HTTP_METHOD") or "POST").strip().upper()
        headers = {}
        api_key = (os.getenv("ANKA_API_KEY") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            if method == "GET":
                resp = httpx.get(url, headers=headers or None, timeout=REQUEST_TIMEOUT)
            else:
                resp = httpx.request(
                    method,
                    url,
                    headers=headers or None,
                    json=TRIGGER_PAYLOAD,
                    timeout=REQUEST_TIMEOUT,
                )
        except Exception as exc:
            return self.failed(f"Anka isteği başarısız: {exc}")

        if not resp.is_success:
            snippet = resp.text.strip().replace("\n", " ")[:120]
            return self.failed(f"Anka HTTP {resp.status_code}: {snippet}")

        preview = resp.text.strip().replace("\n", " ")[:200]
        detail = f" Yanıt: {preview}" if preview else ""
        return self.ok(
            f"Anka köprüsü tetiklendi ({method} {url}), HTTP {resp.status_code}.{detail}"
        )
