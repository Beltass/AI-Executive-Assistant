"""Slack notifier — deliver a compact briefing INDEX to Slack.

Two delivery modes are supported, in priority order:

1. Incoming Webhook via ``SLACK_WEBHOOK_URL``.
2. Bot token via ``SLACK_BOT_TOKEN`` + ``SLACK_CHANNEL`` (``chat.postMessage``).

If neither is configured the notifier is ``skipped`` (never crashes).

WHAT GOES TO SLACK
------------------

Not the briefing. Fifteen advisors writing 300-500 words each used to arrive as
ONE message, which is unreadable on a phone. Slack now carries a short, scannable
**index** built with Block Kit:

* a date header and one context line with the run summary;
* ONE line per advisor — emoji, name, the advisor's own "öne çıkan bulgu"
  headline, and a ``📄 Tam rapor`` link to that advisor's document on the
  dashboard;
* the PRIVATE sections (Gmail/Calendar) inline, because those must never be
  published to the public dashboard and therefore have no link to point at.

The documents themselves are written by :mod:`ai_assistant.reports` into
``frontend/reports/<date>/<advisor>.json`` and rendered as mobile-first reading
pages by the static dashboard. ``DASHBOARD_BASE_URL`` says where that dashboard
is published (default: the GitHub Pages URL).

WHEN IT SENDS
-------------

The daily ``full`` briefing always goes out. An ``incremental`` run (see
``BRIEFING_MODE``) only posts when at least one advisor found something the user
has not been told yet — otherwise the channel stays quiet and only the dashboard
files are written (``SKIP_SLACK_WHEN_NOTHING_NEW``, default true). After a
successful delivery — and only then — the delivered findings are written to the
:mod:`ai_assistant.memory` ledger so the next run does not repeat them.

Run with::

    python -m ai_assistant.notifiers.slack_notifier
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Any, List, Optional, Tuple

from .. import memory, reports
from ..config import MODE_INCREMENTAL, skip_slack_when_nothing_new
from ..daily_digest import Digest, build_digest
from ..integrations import (
    CheckResult,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_SKIPPED,
)
from ..integrations._common import failed, http_post, ok, skipped_reason
from ..reports import Publication, PublishedReport
from ..status_report import ISTANBUL

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
CHANNEL_ENV = "SLACK_CHANNEL"
MAIN_CHANNEL_ENV = "SLACK_MAIN_CHANNEL"
POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"

#: Where the published dashboard lives, so the Slack index can link into it.
DASHBOARD_BASE_URL_ENV = "DASHBOARD_BASE_URL"
DEFAULT_DASHBOARD_BASE_URL = "https://beltass.github.io/AI-Executive-Assistant/"

NAME = "Slack Notifier"

# --- Block Kit limits -------------------------------------------------------
# Slack rejects the whole message if any of these is exceeded, and a rejected
# briefing is a lost briefing, so every builder below clamps itself.
MAX_BLOCKS = 45  # Slack's hard limit is 50; leave room for the footer.
MAX_SECTION_CHARS = 2900  # Slack's hard limit is 3000.
MAX_HEADER_CHARS = 145  # Slack's hard limit is 150.
MAX_FALLBACK_CHARS = 300  # The notification preview; short on purpose.
#: How many chunks one private section may occupy before it is cut short.
MAX_PRIVATE_CHUNKS = 3


def _post_webhook(url: str, text: str, blocks: Optional[list] = None) -> CheckResult:
    payload = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        resp = http_post(url, json=payload)
    except Exception as exc:
        return failed(NAME, f"request error (webhook): {exc}")
    if resp.is_success:
        return ok(NAME, f"webhook — HTTP {resp.status_code}")
    snippet = resp.text.strip().replace("\n", " ")[:160]
    return failed(NAME, f"webhook — HTTP {resp.status_code}: {snippet}")


def _post_bot(
    token: str, channel: str, text: str, blocks: Optional[list] = None
) -> CheckResult:
    payload = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        resp = http_post(
            POST_MESSAGE_URL,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
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


def main_channel() -> Optional[str]:
    """The channel the SUMMARY goes to: ``SLACK_MAIN_CHANNEL`` then ``SLACK_CHANNEL``.

    The per-advisor sub-channels are resolved separately, by
    :mod:`ai_assistant.integrations.channel_config`.
    """
    from ..integrations.channel_config import get_channel_config

    return get_channel_config().resolve_main_channel()


def send_message(text: str, blocks: Optional[list] = None) -> CheckResult:
    """Send a message to Slack using whichever mode is configured.

    ``text`` is always sent: Block Kit messages need it as the notification /
    accessibility fallback. ``blocks`` is what actually renders in the channel.
    """
    webhook = os.getenv(WEBHOOK_ENV)
    if webhook:
        return _post_webhook(webhook, text, blocks)

    token = os.getenv(BOT_TOKEN_ENV)
    channel = main_channel()
    if token and channel:
        return _post_bot(token, channel, text, blocks)

    return skipped_reason(
        NAME,
        f"missing env var(s): {WEBHOOK_ENV} or ({BOT_TOKEN_ENV} + "
        f"{MAIN_CHANNEL_ENV}/{CHANNEL_ENV})",
    )


# --- the compact index ------------------------------------------------------


def dashboard_base_url() -> str:
    """Public base URL of the dashboard, always with a trailing slash."""
    raw = (os.getenv(DASHBOARD_BASE_URL_ENV) or "").strip() or DEFAULT_DASHBOARD_BASE_URL
    return raw if raw.endswith("/") else raw + "/"


def report_url(report: PublishedReport, base: str = "") -> str:
    """Deep link to one advisor's document on the dashboard."""
    return (base or dashboard_base_url()) + report.route


_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def to_mrkdwn(text: str) -> str:
    """Translate the advisors' Markdown into Slack's ``mrkdwn`` dialect.

    Slack uses ``*bold*`` (not ``**bold**``), ``<url|label>`` links and has no
    headings at all. Everything else (bullets, ``_italic_``, ``code``) already
    matches closely enough.
    """
    out = _MD_LINK.sub(r"<\2|\1>", str(text or ""))
    out = _MD_BOLD.sub(r"*\1*", out)
    out = _MD_HEADING.sub("", out)
    return out.strip()


def _escape_header(text: str) -> str:
    """Header blocks are plain_text: no markup, and a hard length cap."""
    flat = " ".join(str(text or "").split())
    return flat[: MAX_HEADER_CHARS - 1] + "…" if len(flat) > MAX_HEADER_CHARS else flat


def _section(text: str) -> dict:
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text[:MAX_SECTION_CHARS]},
    }


def _context(text: str) -> dict:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": text[:MAX_SECTION_CHARS]}],
    }


def _chunks(text: str, size: int = MAX_SECTION_CHARS) -> List[str]:
    """Split a long body on paragraph boundaries so no block exceeds ``size``."""
    body = str(text or "").strip()
    if not body:
        return []
    parts: List[str] = []
    current = ""
    for paragraph in body.split("\n\n"):
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(paragraph) > size:
            parts.append(paragraph[:size])
            paragraph = paragraph[size:]
        current = paragraph
    if current:
        parts.append(current)
    return parts


def _links_line(parts: List[str]) -> str:
    return " · ".join(p for p in parts if p)


def _report_line(report: PublishedReport, base: str, channel_link: str = "") -> dict:
    """One advisor = one section block: emoji, name, headline, links.

    ``channel_link`` points into the advisor's OWN Slack channel — at the exact
    message when Slack gave us a permalink, at the channel otherwise. It is
    omitted when that advisor has no sub-channel of its own.
    """
    headline = to_mrkdwn(report.headline) or "_(özet çıkarılamadı)_"
    links = _links_line(
        [
            f"<{report_url(report, base)}|📄 Tam rapor>",
            f"<{channel_link}|💬 Kendi kanalı>" if channel_link else "",
            f"~{report.read_minutes} dk okuma",
        ]
    )
    return _section(f"{report.emoji} *{report.name}*\n{headline}\n{links}")


def _private_line(briefing: Any, channel_link: str) -> dict:
    """One line for a PRIVATE advisor that has its own channel.

    Its body lives in that channel and must not be repeated here; the summary
    carries only the headline and the way in.
    """
    key = str(getattr(briefing, "key", "") or "")
    meta = reports.ADVISOR_META.get(key, reports.DEFAULT_META)
    title = str(getattr(briefing, "title", "") or key)
    headline = to_mrkdwn(
        reports.extract_headline(str(getattr(briefing, "text", "") or ""))
    ) or "_(özet çıkarılamadı)_"
    tail = (
        f"<{channel_link}|💬 Kendi kanalında tam bölüm>"
        if channel_link
        else "_Tam bölüm kendi kanalında._"
    )
    return _section(f"{meta['emoji']} *{title}* 🔒\n{headline}\n{tail}")


def _private_blocks(briefing: Any) -> List[dict]:
    """A private advisor's FULL section, inline — it has no public link.

    This is the Gmail/Calendar briefing: personal data that must never reach the
    public dashboard, so Slack is the only place it can live.
    """
    body = to_mrkdwn(str(getattr(briefing, "text", "") or "").strip())
    if not body:
        return []
    title = str(getattr(briefing, "title", "") or "Özel bölüm")
    blocks: List[dict] = [
        _section(f"🔒 *{title}*\n_Kişisel veri — panoya yazılmaz, yalnızca burada._")
    ]
    parts = _chunks(body)
    for part in parts[:MAX_PRIVATE_CHUNKS]:
        blocks.append(_section(part))
    if len(parts) > MAX_PRIVATE_CHUNKS:
        blocks.append(_context("… bölümün kalanı uzunluk sınırı nedeniyle kısaltıldı."))
    return blocks


def build_index_message(
    supervision: Any,
    publication: Publication,
    base_url: str = "",
    now: Optional[datetime] = None,
    channel_links: Optional[dict] = None,
    own_channel_keys: Optional[set] = None,
) -> Tuple[str, List[dict]]:
    """Build the compact Slack index. Returns ``(fallback_text, blocks)``.

    This is what the MAIN channel receives: one line per advisor with its
    headline, a deep link to the full report, and — when the advisor has a
    sub-channel of its own — a link into that channel.

    Args:
        channel_links: ``advisor key -> link`` into that advisor's own channel,
            produced by :func:`ai_assistant.integrations.slack_channels.distribute`.
        own_channel_keys: advisors whose section was DELIVERED to a channel of
            their own. A private advisor in this set is summarised by its
            headline instead of being inlined in full, because its body already
            has a home; one that is not stays inlined, or it would be lost.

    Never raises and never grows past Slack's limits: the per-advisor lines are
    trimmed to fit :data:`MAX_BLOCKS` and every body is chunked to fit
    :data:`MAX_SECTION_CHARS`.
    """
    base = base_url or dashboard_base_url()
    links = dict(channel_links or {})
    delivered_elsewhere = set(own_channel_keys or ())
    moment = now or datetime.now(ISTANBUL)
    day_label = moment.astimezone(ISTANBUL).strftime("%d.%m.%Y")

    briefings = list(getattr(supervision, "briefings", []) or [])
    incremental = str(getattr(supervision, "mode", "")) == MODE_INCREMENTAL
    counts = dict(getattr(supervision, "counts", {}) or {})
    ran = int(counts.get(STATUS_OK, 0) or 0)
    broke = int(counts.get(STATUS_FAILED, 0) or 0)
    quiet = [b for b in briefings if getattr(b, "nothing_new", False)]
    published = list(publication.reports if publication else [])
    private = [
        b
        for b in briefings
        if reports.is_private(b) and str(getattr(b, "status", "")) == STATUS_OK
    ]

    heading = "🔄 Ara Brifing" if incremental else "🗓️ Günlük Brifing"
    summary_bits = [
        f"{ran} ajan çalıştı",
        f"{len(published)} rapor hazır",
    ]
    new_findings = int(getattr(supervision, "new_findings", 0) or 0)
    if new_findings:
        summary_bits.append(f"🆕 {new_findings} yeni bulgu")
    if broke:
        summary_bits.append(f"⚠️ {broke} bölüm hazırlanamadı")
    if quiet:
        summary_bits.append(f"🟰 {len(quiet)} ajanda yeni yok")

    blocks: List[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": _escape_header(f"{heading} — {day_label}"),
                "emoji": True,
            },
        },
        _context(" · ".join(summary_bits)),
        {"type": "divider"},
    ]

    for report in published:
        if len(blocks) >= MAX_BLOCKS - 4:
            blocks.append(
                _context(
                    f"… ve {len(published) - (len(blocks) - 3)} rapor daha — "
                    f"hepsi panoda."
                )
            )
            break
        blocks.append(_report_line(report, base, links.get(report.id, "")))

    # A private advisor that already has its own channel is summarised by one
    # line; one that does not is still inlined in full — that body has nowhere
    # else to go.
    summarised = [b for b in private if str(getattr(b, "key", "")) in delivered_elsewhere]
    inlined = [b for b in private if str(getattr(b, "key", "")) not in delivered_elsewhere]

    for briefing in summarised:
        if len(blocks) >= MAX_BLOCKS - 2:
            break
        blocks.append(_private_line(briefing, links.get(str(getattr(briefing, "key", "")), "")))

    for briefing in inlined:
        if len(blocks) >= MAX_BLOCKS - 2:
            break
        blocks.append({"type": "divider"})
        for block in _private_blocks(briefing):
            if len(blocks) >= MAX_BLOCKS - 1:
                break
            blocks.append(block)

    if not published and not private:
        blocks.append(
            _section(
                "_Bu çalıştırmada yayınlanacak yeni bir bölüm çıkmadı._"
                if incremental
                else "_Bu çalıştırmada hiçbir bölüm hazırlanamadı; panodaki "
                "durum sayfasında ayrıntılar var._"
            )
        )

    blocks.append({"type": "divider"})
    blocks.append(_context(f"<{base}|📊 Tüm raporlar ve pano> · rapor arşivi 30 gün"))

    fallback = f"{heading} — {day_label}: {len(published)} rapor hazır. {base}"
    return fallback[:MAX_FALLBACK_CHARS], blocks[:MAX_BLOCKS]


def send_briefing_index(
    supervision: Any,
    publication: Publication,
    base_url: str = "",
    distribution: Any = None,
) -> CheckResult:
    """Post the compact index for an already-published run to the MAIN channel.

    ``distribution`` is the result of the per-advisor fan-out (see
    :func:`ai_assistant.integrations.slack_channels.distribute`); when given,
    each line also links into that advisor's own channel.
    """
    text, blocks = build_index_message(
        supervision,
        publication,
        base_url=base_url,
        channel_links=getattr(distribution, "links", None),
        own_channel_keys=getattr(distribution, "delivered_keys", None),
    )
    return send_message(text, blocks=blocks)


def distribute_to_advisor_channels(supervision: Any, publication: Publication) -> Any:
    """Post every advisor's section to its OWN Slack channel.

    Best effort by construction: :func:`slack_channels.distribute` catches its
    own errors, and an import-time surprise here must not cost the summary.
    """
    try:
        from ..integrations import slack_channels

        return slack_channels.distribute(supervision, publication)
    except Exception as exc:  # pragma: no cover - defensive only
        logging.getLogger(__name__).error(f"Kanal dağıtımı başarısız: {exc}")
        return None


def send_daily_digest() -> CheckResult:
    """Run the team, publish the documents, fan out and post the Slack index."""
    digest = build_digest()
    publication = reports.publish(digest.supervision)
    distribution = distribute_to_advisor_channels(digest.supervision, publication)
    return send_briefing_index(
        digest.supervision, publication, distribution=distribution
    )


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


def _record_metrics(digest: Digest, started: float) -> None:
    """Record what this run COST for the performance tab.

    Best-effort, exactly like the status file: token accounting is worth
    strictly less than the briefing it accounts for, so every failure is a
    printed line and nothing more. Writes counts only — never a prompt, never a
    response, never a key.
    """
    try:
        from .. import metrics
        from ..advisors import _batch
        from ..integrations import llm

        path = metrics.record_run(
            digest.supervision,
            call_stats=llm.last_call_stats(),
            batch=_batch.last_outcome(),
            duration_seconds=time.monotonic() - started,
        )
        stats = llm.last_call_stats()
        if stats is not None:
            print(
                f"Token kullanımı: girdi {stats.prompt_tokens} · "
                f"çıktı {stats.output_tokens} · düşünme {stats.thoughts_tokens} · "
                f"toplam {stats.total_tokens}"
            )
        if path:
            print(f"Metrik dosyası: {path}")
    except Exception as exc:  # pragma: no cover - record_run already guards itself
        print(f"Metrikler yazılamadı: {exc}")


def _publish_reports(digest: Digest) -> Publication:
    """Write this run's per-advisor documents for the dashboard.

    Best-effort, exactly like the status file: a read-only checkout costs the
    dashboard a day, never the briefing. Prints only counts and paths — never a
    report body, because the workflow log is public.
    """
    try:
        publication = reports.publish(digest.supervision)
    except Exception as exc:  # pragma: no cover - publish already guards itself
        print(f"Rapor belgeleri yazılamadı: {exc}")
        return Publication()
    print(
        f"Yayınlanan rapor belgesi: {len(publication.reports)} "
        f"({publication.directory or '—'})"
    )
    if publication.private:
        print(
            f"Panoya yazılmayan özel bölüm: {len(publication.private)} "
            "(yalnızca Slack)"
        )
    if publication.pruned:
        print(f"Arşivden silinen eski gün: {', '.join(publication.pruned)}")
    return publication


def main() -> int:
    """CLI entrypoint. Builds + sends the digest. Returns the exit code."""
    _configure_logging()
    started = time.monotonic()
    digest = build_digest()
    _print_run_report(digest)

    # Documents first: the dashboard must be up to date even on a quiet run
    # where Slack deliberately stays silent.
    publication = _publish_reports(digest)

    if should_send(digest):
        # Sub-channels FIRST: the main channel's summary links into the
        # messages this fan-out creates, so it has to know where they landed.
        distribution = distribute_to_advisor_channels(digest.supervision, publication)
        if distribution is not None:
            print(f"Kanal dağıtımı: {distribution.summary_line()}")
        result = send_briefing_index(
            digest.supervision, publication, distribution=distribution
        )
    else:
        # Quiet incremental run: no message, but the dashboard still learns the
        # run happened (status.json is written below either way).
        result = skipped_reason(NAME, NOTHING_NEW_DETAIL)
    label = _STATUS_LABEL.get(result.status, result.status.upper())
    print(f"Slack Notifier: {label} — {result.detail}")

    # Only what actually reached the user is remembered as "already reported".
    _remember_delivered(result)

    _write_status_report(digest, result, started)
    _record_metrics(digest, started)
    return 1 if result.status == STATUS_FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
