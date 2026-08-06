"""Tests for the Slack notifier.

Run offline with no Slack credentials: the notifier must report ``skipped``
and never attempt a network call or crash.
"""

from __future__ import annotations

import pytest

from ai_assistant.advisors import Briefing
from ai_assistant.daily_digest import Digest
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ai_assistant.notifiers import slack_notifier
from ai_assistant.operations_manager import Supervision

_ENV_VARS = [
    "SLACK_WEBHOOK_URL",
    "SLACK_BOT_TOKEN",
    "SLACK_CHANNEL",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "WEATHER_CITY",
    "WEATHER_LATITUDE",
    "WEATHER_LONGITUDE",
]


@pytest.fixture()
def no_slack(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield


def test_send_message_skipped_when_unconfigured(no_slack):
    result = slack_notifier.send_message("hello")
    assert result.status == STATUS_SKIPPED
    assert result.detail


def test_send_daily_digest_skipped_when_unconfigured(no_slack):
    result = slack_notifier.send_daily_digest()
    assert result.status == STATUS_SKIPPED


def test_bot_mode_requires_channel(no_slack, monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    # No SLACK_CHANNEL and no webhook -> still skipped (incomplete config).
    result = slack_notifier.send_message("hello")
    assert result.status == STATUS_SKIPPED


def test_main_exit_zero_when_unconfigured(no_slack, capsys):
    code = slack_notifier.main()
    assert code == 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out


def _digest(*briefings):
    return Digest(
        text="brifing gövdesi", supervision=Supervision(briefings=list(briefings))
    )


def test_run_report_lists_every_advisor_status(capsys):
    slack_notifier._print_run_report(
        _digest(
            Briefing(
                key="weather", title="Hava Durumu", status=STATUS_OK, text="x" * 120
            ),
            Briefing(
                key="coach",
                title="Koç",
                status=STATUS_FAILED,
                text="LLM isteği başarısız",
            ),
            Briefing(
                key="anka",
                title="Anka",
                status=STATUS_SKIPPED,
                text="missing env var(s)",
            ),
        )
    )
    out = capsys.readouterr().out

    assert "Hava Durumu" in out and "120 karakter" in out
    assert "LLM isteği başarısız" in out
    assert "missing env var(s)" in out
    assert "1 ok, 1 failed, 1 skipped" in out


def test_run_report_never_prints_the_briefing_body(capsys):
    """The workflow log is public; only statuses belong there, not content."""
    secret_ish = "Bugün çocuğunuzla şunu yapın: çok özel kişisel içerik"
    slack_notifier._print_run_report(
        _digest(Briefing(key="kids", title="Çocuk", status=STATUS_OK, text=secret_ish))
    )
    out = capsys.readouterr().out

    assert secret_ish not in out
    assert f"{len(secret_ish)} karakter" in out


def test_main_reports_statuses_before_sending(no_slack, capsys):
    code = slack_notifier.main()
    assert code == 0
    out = capsys.readouterr().out
    # The per-advisor table and the summary land in the log even when Slack
    # delivery itself is skipped.
    assert "Danışman Denetimi:" in out
    assert "Operasyon Yöneticisi:" in out


# --- the compact Block Kit index -------------------------------------------
#
# Slack no longer receives the briefing, it receives an INDEX: a header, a
# summary line, and ONE line per advisor with a link to that advisor's document
# on the dashboard. These tests pin that shape, its links and its limits.

import json
from datetime import datetime

from ai_assistant import reports
from ai_assistant.status_report import ISTANBUL

NOW = datetime(2026, 7, 31, 10, 4, tzinfo=ISTANBUL)

_SECTION = (
    "**Öne çıkan:** Ekibinin ritmini 20 dakikalık kontrolle sabitle.\n\n"
    "## Neden\n\nÇünkü sürprizler yarıya iner.\n"
)


def _ok(key, title, text=_SECTION, **kwargs):
    return Briefing(key=key, title=title, status=STATUS_OK, text=text, **kwargs)


def _publish(tmp_path, *briefings, mode="full"):
    supervision = Supervision(briefings=list(briefings), mode=mode)
    publication = reports.publish(supervision, root=str(tmp_path), now=NOW)
    return supervision, publication


def _block_types(blocks):
    return [block["type"] for block in blocks]


def _all_text(blocks):
    return json.dumps(blocks, ensure_ascii=False)


def test_index_is_a_header_summary_and_one_line_per_advisor(tmp_path):
    supervision, publication = _publish(
        tmp_path,
        _ok("leadership_coach", "Liderlik Koçu"),
        _ok("ai_news", "Yapay Zeka Haberleri"),
    )
    text, blocks = slack_notifier.build_index_message(
        supervision, publication, base_url="https://example.test/", now=NOW
    )

    assert blocks[0]["type"] == "header"
    assert "31.07.2026" in blocks[0]["text"]["text"]
    assert blocks[1]["type"] == "context"
    assert "2 ajan çalıştı" in blocks[1]["elements"][0]["text"]
    assert "2 rapor hazır" in blocks[1]["elements"][0]["text"]

    sections = [b for b in blocks if b["type"] == "section"]
    assert len(sections) == 2
    body = sections[0]["text"]["text"]
    assert "*Liderlik Koçu*" in body
    assert "Ekibinin ritmini" in body
    assert "📄 Tam rapor" in body
    assert "dk okuma" in body

    # The notification fallback stays short and mentions where to read.
    assert len(text) <= slack_notifier.MAX_FALLBACK_CHARS
    assert "https://example.test/" in text


def test_every_advisor_line_links_to_its_own_document(tmp_path):
    supervision, publication = _publish(
        tmp_path,
        _ok("leadership_coach", "Liderlik Koçu"),
        _ok("ai_news", "Yapay Zeka Haberleri"),
    )
    _, blocks = slack_notifier.build_index_message(
        supervision, publication, base_url="https://example.test/", now=NOW
    )
    blob = _all_text(blocks)
    assert "https://example.test/#/rapor/2026-07-31/leadership_coach" in blob
    assert "https://example.test/#/rapor/2026-07-31/ai_news" in blob


def test_the_full_section_body_never_reaches_slack(tmp_path):
    """The whole point of the redesign: Slack carries headlines, not reports."""
    long_body = (
        "**Öne çıkan:** Kısa özet.\n\n" + "Bu çok uzun bir bölüm gövdesi. " * 200
    )
    supervision, publication = _publish(
        tmp_path, _ok("leadership_coach", "Liderlik Koçu", text=long_body)
    )
    _, blocks = slack_notifier.build_index_message(
        supervision, publication, base_url="https://example.test/", now=NOW
    )
    blob = _all_text(blocks)
    assert "Kısa özet." in blob
    assert "Bu çok uzun bir bölüm gövdesi." not in blob
    assert len(blob) < 4000


def test_index_stays_within_slack_block_limits(tmp_path):
    briefings = [_ok(f"advisor_{index}", f"Danışman {index}") for index in range(40)]
    supervision, publication = _publish(tmp_path, *briefings)
    _, blocks = slack_notifier.build_index_message(
        supervision, publication, base_url="https://example.test/", now=NOW
    )

    assert len(blocks) <= slack_notifier.MAX_BLOCKS <= 50
    for block in blocks:
        if block["type"] == "section":
            assert len(block["text"]["text"]) <= 3000
        if block["type"] == "header":
            assert len(block["text"]["text"]) <= 150


def test_private_sections_are_sent_inline_and_flagged(tmp_path):
    personal = "**Öne çıkan:** 3 acil e-posta.\n\n- Ayşe Yılmaz — bütçe onayı"
    supervision, publication = _publish(
        tmp_path,
        _ok("leadership_coach", "Liderlik Koçu"),
        _ok(
            "daily_ops_briefing",
            "Gün Başı Operasyon Brifingi",
            text=personal,
            private=True,
        ),
    )
    _, blocks = slack_notifier.build_index_message(
        supervision, publication, base_url="https://example.test/", now=NOW
    )
    blob = _all_text(blocks)

    # Full content, in Slack only.
    assert "Ayşe Yılmaz" in blob
    assert "panoya yazılmaz" in blob.lower()
    # …and no public link was invented for it.
    assert "rapor/2026-07-31/daily_ops_briefing" not in blob


def test_index_says_so_when_nothing_was_published(tmp_path):
    supervision, publication = _publish(
        tmp_path,
        Briefing(key="a", title="A", status=STATUS_SKIPPED, text="missing env"),
    )
    _, blocks = slack_notifier.build_index_message(
        supervision, publication, base_url="https://example.test/", now=NOW
    )
    assert "hazırlanamadı" in _all_text(blocks)


def test_incremental_header_and_counts(tmp_path):
    supervision, publication = _publish(
        tmp_path,
        _ok("ai_news", "Yapay Zeka Haberleri", new_findings=3),
        mode="incremental",
    )
    _, blocks = slack_notifier.build_index_message(
        supervision, publication, base_url="https://example.test/", now=NOW
    )
    assert "Ara Brifing" in blocks[0]["text"]["text"]
    assert "3 yeni bulgu" in blocks[1]["elements"][0]["text"]


def test_footer_links_back_to_the_dashboard(tmp_path):
    supervision, publication = _publish(tmp_path, _ok("leadership_coach", "Koç"))
    _, blocks = slack_notifier.build_index_message(
        supervision, publication, base_url="https://example.test/", now=NOW
    )
    assert "Tüm raporlar" in blocks[-1]["elements"][0]["text"]
    assert "https://example.test/" in blocks[-1]["elements"][0]["text"]


# --- base URL ---------------------------------------------------------------


def test_dashboard_base_url_defaults_to_pages(monkeypatch):
    monkeypatch.delenv(slack_notifier.DASHBOARD_BASE_URL_ENV, raising=False)
    assert (
        slack_notifier.dashboard_base_url()
        == slack_notifier.DEFAULT_DASHBOARD_BASE_URL
        == "https://beltass.github.io/AI-Executive-Assistant/"
    )


def test_dashboard_base_url_is_configurable_and_normalised(monkeypatch):
    monkeypatch.setenv(slack_notifier.DASHBOARD_BASE_URL_ENV, "https://pano.test")
    assert slack_notifier.dashboard_base_url() == "https://pano.test/"
    monkeypatch.setenv(slack_notifier.DASHBOARD_BASE_URL_ENV, "https://pano.test/x/")
    assert slack_notifier.dashboard_base_url() == "https://pano.test/x/"


# --- mrkdwn translation ------------------------------------------------------


def test_markdown_is_translated_to_slack_mrkdwn():
    assert slack_notifier.to_mrkdwn("**kalın**") == "*kalın*"
    assert slack_notifier.to_mrkdwn("## Başlık") == "Başlık"
    assert (
        slack_notifier.to_mrkdwn("[Coursera](https://www.coursera.org)")
        == "<https://www.coursera.org|Coursera>"
    )


# --- payload wiring ----------------------------------------------------------


def test_blocks_are_posted_alongside_the_fallback_text(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        is_success = True
        text = "ok"

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp()

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setattr(slack_notifier, "http_post", fake_post)

    result = slack_notifier.send_message("kısa özet", blocks=[{"type": "divider"}])
    assert result.status == STATUS_OK
    assert captured["json"]["text"] == "kısa özet"
    assert captured["json"]["blocks"] == [{"type": "divider"}]


def test_bot_mode_sends_blocks_too(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"ok": True}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _Resp()

    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL", "#genel")
    monkeypatch.setattr(slack_notifier, "http_post", fake_post)

    slack_notifier.send_message("kısa özet", blocks=[{"type": "divider"}])
    assert captured["json"]["channel"] == "#genel"
    assert captured["json"]["blocks"] == [{"type": "divider"}]
