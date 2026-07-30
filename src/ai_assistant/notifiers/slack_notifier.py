"""Slack notifier — deliver the daily digest to Slack.

Two delivery modes are supported, in priority order:

1. Incoming Webhook via ``SLACK_WEBHOOK_URL``.
2. Bot token via ``SLACK_BOT_TOKEN`` + ``SLACK_CHANNEL`` (``chat.postMessage``).

If neither is configured the notifier is ``skipped`` (never crashes).

The daily ``full`` briefing always goes out. An ``incremental`` run (see
``BRIEFING_MODE``) only posts when at least one advisor found something the user
has not been told yet — otherwise the channel stays quiet and only the dashboard
status file is written (``SKIP_SLACK_WHEN_NOTHING_NEW``, default true). After a
successful delivery — and only then — the delivered findings are written to the
:mod:`ai_assistant.memory` ledger so the next run does not repeat them.

Run with::

    python -m ai_assistant.notifiers.slack_notifier
"""

from __future__ import annotations

import logging
import os
import sys
import time

from .. import memory
from ..config import MODE_INCREMENTAL, skip_slack_when_nothing_new
from ..daily_digest import Digest, build_digest
from ..integrations import (
    CheckResult,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED,
)
from ..integrations._common import failed, http_post, ok, skipped_reason

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
CHANNEL_ENV = "SLACK_CHANNEL"
POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

NAME = "Slack Notifier"


def _post_webhook(url: str, text: str) -> CheckResult:
    try:
        resp = http_post(url, json={"text": text})
    except Exception as exc:
        return failed(NAME, f"request error (webhook): {exc}")
    if resp.is_success:
        return ok(NAME, f"webhook — HTTP {resp.status_code}")
    snippet = resp.text.strip().replace("\n", " ")[:160]
    return failed(NAME, f"webhook — HTTP {resp.status_code}: {snippet}")


def _post_bot(token: str, channel: str, text: str) -> CheckResult:
    try:
        resp = http_post(
            POST_MESSAGE_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": channel, "text": text},
        )
    except Exception as exc:
        return failed(NAME, f"request error (chat.postMessage): {exc}")
    try:
        data = resp.json()
    except Exception:
        return failed(NAME, f"HTTP {resp.status_code}: non-JSON response")
    if data.get("ok"):
        return ok(NAME, f"chat.postMessage — channel: {channel}")
    return failed(NAME, f"chat.postMessage error: {data.get('error', 'unknown')}")


def send_message(text: str) -> CheckResult:
    """Send a plain-text message to Slack using whichever mode is configured."""
    webhook = os.getenv(WEBHOOK_ENV)
    if webhook:
        return _post_webhook(webhook, text)

    token = os.getenv(BOT_TOKEN_ENV)
    channel = os.getenv(CHANNEL_ENV)
    if token and channel:
        return _post_bot(token, channel, text)

    return skipped_reason(
        NAME,
        f"missing env var(s): {WEBHOOK_ENV} or ({BOT_TOKEN_ENV} + {CHANNEL_ENV})",
    )


def send_daily_digest() -> CheckResult:
    """Build the daily digest and post it to Slack."""
    digest = build_digest()
    return send_message(digest.text)


NOTHING_NEW_DETAIL = "artımlı çalıştırma — yeni bulgu yok, mesaj gönderilmedi"


def should_send(digest: Digest) -> bool:
    """Whether this digest is worth putting in the channel.

    The flagship ``full`` briefing ALWAYS goes out. An ``incremental`` run only
    interrupts the user when at least one advisor found something new — that is
    the whole point of running four times a day without becoming noise. Set
    ``SKIP_SLACK_WHEN_NOTHING_NEW=false`` to receive every run regardless.
    """
    supervision = digest.supervision
    if getattr(supervision, "mode", "") != MODE_INCREMENTAL:
        return True
    if supervision.has_new_findings:
        return True
    return not skip_slack_when_nothing_new()


def _remember_delivered(result: CheckResult) -> None:
    """Mark this run's findings as seen — ONLY after a successful delivery.

    If Slack refused (or was never configured) the findings never reached the
    user, so they must stay "new" for the next run. Persisting the ledger can
    never break the job: :meth:`ai_assistant.memory.FindingsMemory.commit`
    swallows its own I/O errors.
    """
    ledger = memory.shared()
    if result.status == STATUS_OK:
        ledger.commit()
    else:
        ledger.discard_pending()


_STATUS_LABEL = {
    STATUS_OK: "OK",
    STATUS_FAILED: "FAILED",
    STATUS_SKIPPED: "SKIPPED",
}


def _configure_logging() -> None:
    """Surface the advisors' INFO logs when run as a job.

    The interesting diagnostics — which Gemini model actually served the answer,
    how many sections the batched call covered — are logged at INFO, which is
    invisible with Python's default configuration. Turning them on makes a
    scheduled run auditable after the fact. Only configured for the CLI, so
    importing the module as a library still leaves logging untouched.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _print_run_report(digest: Digest) -> None:
    """Print a per-advisor status table for the job log.

    Deliberately prints STATUSES ONLY, never the briefing bodies: the digest is
    the user's personal daily report and the workflow log is public. For a
    ``failed``/``skipped`` advisor the short reason IS printed — that is the
    diagnostic we actually need, and the LLM layer has already redacted any API
    key from it.
    """
    supervision = digest.supervision
    print(f"Çalıştırma modu: {supervision.mode} ({supervision.mode_label})")
    print("Danışman Denetimi:")
    for briefing in supervision.briefings:
        label = _STATUS_LABEL.get(briefing.status, briefing.status.upper())
        if briefing.nothing_new:
            label = "YENİ YOK"
            detail = briefing.text.strip()
        elif briefing.status == STATUS_OK:
            # Length is a cheap, non-revealing proxy for "did we get real content".
            detail = f"{len(briefing.text)} karakter"
            if briefing.new_findings:
                detail += f" · {briefing.new_findings} yeni bulgu"
        else:
            detail = briefing.text.strip().replace("\n", " ")[:200]
        print(f"  - {briefing.title:<32} {label:<8} {detail}")
    print(
        f"Operasyon Yöneticisi: {supervision.summary_line()} · "
        f"{supervision.new_findings} yeni bulgu"
    )


def _write_status_report(digest: Digest, result: CheckResult, started: float) -> None:
    """Record the finished run for the monitoring dashboard.

    Called AFTER Slack delivery so the file reflects the true final state,
    including whether the digest actually reached the user. Purely a
    monitoring artefact: it is written best-effort and can never affect the
    exit code (``write_status_report`` already swallows its own errors; the
    extra guard here covers even an import-time surprise).
    """
    try:
        from ..status_report import write_status_report

        path = write_status_report(
            digest.supervision,
            slack_result=result,
            duration_seconds=time.monotonic() - started,
        )
        if path:
            print(f"Durum raporu: {path}")
    except Exception as exc:  # pragma: no cover - defensive only
        print(f"Durum raporu yazılamadı: {exc}")


def main() -> int:
    """CLI entrypoint. Builds + sends the digest. Returns the exit code."""
    _configure_logging()
    started = time.monotonic()
    digest = build_digest()
    _print_run_report(digest)

    if should_send(digest):
        result = send_message(digest.text)
    else:
        # Quiet incremental run: no message, but the dashboard still learns the
        # run happened (status.json is written below either way).
        result = skipped_reason(NAME, NOTHING_NEW_DETAIL)
    label = _STATUS_LABEL.get(result.status, result.status.upper())
    print(f"Slack Notifier: {label} — {result.detail}")

    # Only what actually reached the user is remembered as "already reported".
    _remember_delivered(result)

    _write_status_report(digest, result, started)
    return 1 if result.status == STATUS_FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
