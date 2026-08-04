"""Tests for the Slack Block Kit presentation of an advisor report.

What is pinned here is the SHAPE of the delivered message — header, context,
lead, bullets, fields, link — plus the three ways Slack can reject a message
outright (3000 chars in a section, 50 blocks, ~40k in total). A rejected
message is a lost briefing, so the builders must clamp themselves; and when
they clamp, the link to the full report has to survive, or the user simply
loses the content.

No network anywhere: these functions only build dictionaries.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from ai_assistant import reports
from ai_assistant.advisors import Briefing
from ai_assistant.integrations import STATUS_OK, channel_config, slack_channels
from ai_assistant.notifiers import slack_blocks
from ai_assistant.operations_manager import Supervision
from ai_assistant.status_report import ISTANBUL

NOW = datetime(2026, 8, 4, 8, 30, tzinfo=ISTANBUL)

TYPICAL = """**Öne çıkan:** Yapay zekâ çağrı merkezinde verimliliği artırıyor.

Giriş paragrafı, raporun ne anlattığını özetler.

## 📊 Sektör Gündemi

Bankacılık sektöründe yapay zekâ kullanımı olgunlaşmaya devam ediyor. İkinci
cümle burada.

## 🤖 Riskler

Halüsinasyon ve uyum riskleri dikkatli bir yönetişim gerektiriyor.
"""


def _report(text: str = TYPICAL, key: str = "market_intelligence", tmp_path=None):
    """Publish one briefing and hand back the resulting document."""
    supervision = Supervision(
        briefings=[Briefing(key=key, title="Pazar İstihbaratı", status=STATUS_OK, text=text)]
    )
    publication = reports.publish(supervision, root=str(tmp_path / "reports"), now=NOW)
    assert publication.reports, "fixture must actually publish a document"
    return publication.reports[0]


def _types(blocks):
    return [block["type"] for block in blocks]


def _blob(blocks):
    return json.dumps(blocks, ensure_ascii=False)


# --- the shape of a typical report -----------------------------------------


def test_a_typical_report_is_a_scannable_block_kit_card(tmp_path):
    """Header, context, lead, bullets, link — in that order, on one screen."""
    text, blocks = slack_blocks.build_report_message(
        _report(tmp_path=tmp_path), base_url="https://pano/"
    )

    assert blocks[0]["type"] == "header"
    assert "Pazar İstihbaratı" in blocks[0]["text"]["text"]
    # A header block is plain_text: markup there renders as literal asterisks.
    assert blocks[0]["text"]["type"] == "plain_text"

    assert blocks[1]["type"] == "context"
    assert "dk okuma" in blocks[1]["elements"][0]["text"]

    # The lead is the headline only — quoted, so a phone draws a bar down it.
    lead = blocks[2]["text"]["text"]
    assert lead.startswith(">")
    assert "verimliliği artırıyor" in lead

    blob = _blob(blocks)
    assert "Öne çıkanlar" in blob
    assert "Sektör Gündemi" in blob
    assert "https://pano/#/rapor/2026-08-04/market_intelligence" in blob

    # There is a divider, but not one between every element.
    assert _types(blocks).count("divider") <= 2
    # And no buttons: this project has no HTTPS endpoint to receive the click.
    assert "actions" not in _types(blocks)


def test_numeric_data_is_rendered_as_two_up_fields(tmp_path):
    """`fields` is what Slack lays out in two columns — the phone-friendly form."""
    report = _report(tmp_path=tmp_path)
    report.key_metrics = [
        reports.KeyMetric(label="Çağrı Hacmi", value="1240", unit="adet", trend="up"),
        reports.KeyMetric(label="Ortalama Süre", value="4:12", trend="down"),
    ]
    _, blocks = slack_blocks.build_report_message(report, base_url="https://pano/")

    field_blocks = [b for b in blocks if b.get("fields")]
    assert len(field_blocks) == 1
    texts = [f["text"] for f in field_blocks[0]["fields"]]
    assert "*Çağrı Hacmi*\n1240 adet ↑" in texts
    assert "*Ortalama Süre*\n4:12 ↓" in texts


def test_actions_and_sources_are_summarised_not_dumped(tmp_path):
    report = _report(tmp_path=tmp_path)
    report.action_items = [reports.ActionItem(text=f"Aksiyon {i}") for i in range(9)]
    report.sources = [
        reports.Source(title=f"Kaynak {i}", url=f"https://kaynak{i}.test") for i in range(9)
    ]
    _, blocks = slack_blocks.build_report_message(report, base_url="https://pano/")
    blob = _blob(blocks)

    assert "Bugünün aksiyonları" in blob
    assert "Aksiyon 0" in blob
    assert "Aksiyon 8" not in blob, "nine actions in a phone message is a wall"
    assert slack_blocks.TRUNCATION_NOTE in blob
    assert "+6 kaynak" in blob


def test_freshness_badge_appears_only_when_there_is_something_new(tmp_path):
    report = _report(tmp_path=tmp_path)
    _, quiet = slack_blocks.build_report_message(report, base_url="https://pano/")
    _, fresh = slack_blocks.build_report_message(
        report, base_url="https://pano/", new_findings=3
    )
    assert "yeni bulgu" not in _blob(quiet)
    assert "🆕 3 yeni bulgu" in _blob(fresh)


# --- the plain-text fallback ------------------------------------------------


def test_a_plain_text_fallback_always_accompanies_the_blocks(tmp_path):
    """Slack requires `text` with `blocks`: it is the notification and the
    screen-reader version."""
    text, blocks = slack_blocks.build_report_message(
        _report(tmp_path=tmp_path), base_url="https://pano/"
    )
    assert text
    assert blocks
    assert len(text) <= slack_blocks.MAX_FALLBACK_CHARS
    assert "Pazar İstihbaratı" in text
    # Plain means plain: no mrkdwn markup leaks into the notification.
    assert "*" not in text and "<http" not in text


def test_the_fallback_is_clipped_not_dropped_for_a_long_headline(tmp_path):
    report = _report(tmp_path=tmp_path)
    report.headline = "Çok uzun bir öne çıkan cümle. " * 40
    text, _ = slack_blocks.build_report_message(report, base_url="https://pano/")
    assert len(text) <= slack_blocks.MAX_FALLBACK_CHARS
    assert text.endswith("…")


# --- Slack's hard limits ----------------------------------------------------


def test_a_section_never_exceeds_slacks_3000_character_limit():
    block = slack_blocks.section("x" * 9000)
    assert len(block["text"]["text"]) <= 3000
    assert block["text"]["text"].endswith(slack_blocks.TRUNCATION_NOTE)


def test_every_section_of_a_huge_report_fits_the_character_limit(tmp_path):
    report = _report(tmp_path=tmp_path)
    report.headline = "Uzun başlık. " * 500
    report.sections = [
        reports.Section(title="Başlık " * 40, body="Gövde cümlesi. " * 400)
        for _ in range(6)
    ]
    _, blocks = slack_blocks.build_report_message(report, base_url="https://pano/")

    for block in blocks:
        if block["type"] == "section" and "text" in block:
            assert len(block["text"]["text"]) <= 3000
        for field in block.get("fields", []):
            assert len(field["text"]) <= 2000
        if block["type"] == "header":
            assert len(block["text"]["text"]) <= 150


def test_the_block_count_never_exceeds_slacks_limit_and_keeps_the_tail():
    body = [slack_blocks.section(f"blok {index}") for index in range(200)]
    tail = [slack_blocks.divider(), slack_blocks.section("<https://pano/|📊 Pano>")]

    fitted = slack_blocks.fit_blocks(body, tail=tail)

    assert len(fitted) <= slack_blocks.MAX_BLOCKS <= 50
    assert fitted[-2:] == tail, "the way out to the full report is never trimmed"


def test_a_report_with_many_sections_stays_well_under_the_block_limit(tmp_path):
    report = _report(tmp_path=tmp_path)
    report.sections = [
        reports.Section(title=f"Bölüm {index}", body=f"Bölüm {index} gövdesi burada.")
        for index in range(60)
    ]
    _, blocks = slack_blocks.build_report_message(report, base_url="https://pano/")

    assert len(blocks) <= slack_blocks.MAX_BLOCKS
    # 60 sections must not become 60 bullets on a phone.
    assert _blob(blocks).count("•  ") <= slack_blocks.MAX_BULLETS
    assert slack_blocks.TRUNCATION_NOTE in _blob(blocks)


# --- the 20k report, which is the real case ---------------------------------


def _huge_markdown() -> str:
    parts = ["**Öne çıkan:** Yirmi bin karakterlik raporun tek cümlelik özeti."]
    for index in range(8):
        parts.append(f"## Bölüm {index}")
        parts.append(f"Bölüm {index} açılış cümlesi. " + ("Dolgu cümlesi. " * 160))
    return "\n\n".join(parts)


def test_a_twenty_thousand_character_report_is_truncated_with_the_link_kept(tmp_path):
    source = _huge_markdown()
    assert len(source) > 19000, "the fixture has to be the size we actually see"

    report = _report(text=source, tmp_path=tmp_path)
    text, blocks = slack_blocks.build_report_message(report, base_url="https://pano/")
    blob = _blob(blocks)

    # The message is a card, not the report.
    assert len(blob) < 6000
    assert blob.count("Dolgu cümlesi.") <= slack_blocks.MAX_BULLETS
    # Nothing is lost silently: the cut is marked and the way to the rest is
    # the last thing in the message.
    assert slack_blocks.TRUNCATION_NOTE in blob
    assert "Tam raporu aç" in blocks[-1]["text"]["text"]
    assert "https://pano/#/rapor/2026-08-04/market_intelligence" in blocks[-1]["text"]["text"]
    assert text and len(text) <= slack_blocks.MAX_FALLBACK_CHARS


def test_a_private_briefing_body_is_chunked_and_says_when_it_was_cut():
    briefing = Briefing(
        key="communications_calendar",
        title="İletişim & Takvim",
        status=STATUS_OK,
        text="\n\n".join(f"Paragraf {i}. " + ("dolgu " * 300) for i in range(12)),
        private=True,
    )
    text, blocks = slack_blocks.build_briefing_message(
        "İletişim & Takvim", briefing, emoji="📬"
    )

    assert text.startswith("📬")
    assert blocks[0]["type"] == "header"
    assert "panoya yazılmaz" in _blob(blocks)
    for block in blocks:
        if block["type"] == "section":
            assert len(block["text"]["text"]) <= 3000
    assert len(blocks) <= slack_blocks.MAX_BLOCKS
    assert "kısaltıldı" in _blob(blocks)


# --- degenerate content -----------------------------------------------------


def test_an_advisor_with_almost_no_content_still_produces_a_valid_message(tmp_path):
    report = _report(text="Tek satır.", tmp_path=tmp_path)
    text, blocks = slack_blocks.build_report_message(report, base_url="https://pano/")

    assert text
    assert blocks[0]["type"] == "header"
    assert all(block["type"] for block in blocks)
    # Every section carries non-empty text: Slack rejects an empty one.
    for block in blocks:
        if block["type"] == "section" and "text" in block:
            assert block["text"]["text"].strip()
    assert "Tam raporu aç" in blocks[-1]["text"]["text"]


def test_an_empty_report_object_does_not_crash_the_builder():
    """Defensive: a half-built report must cost formatting, never the run."""
    empty = reports.PublishedReport(
        id="bos",
        name="",
        emoji="",
        category="",
        date="2026-08-04",
        headline="",
        excerpt="",
        words=0,
        read_minutes=0,
    )
    text, blocks = slack_blocks.build_report_message(empty, base_url="https://pano/")

    assert text
    assert blocks[0]["text"]["text"], "a header block may not be empty"
    assert "özet çıkarılamadı" in _blob(blocks)
    assert "https://pano/" in _blob(blocks)


# --- mrkdwn translation -----------------------------------------------------


def test_markdown_lists_become_real_bullets():
    """Slack does not render Markdown lists; `- item` would show up verbatim."""
    out = slack_blocks.to_mrkdwn("- ilk\n- ikinci\n  * alt madde")
    assert out.splitlines() == ["• ilk", "• ikinci", "  • alt madde"]


def test_markdown_bold_headings_and_links_are_translated():
    assert slack_blocks.to_mrkdwn("**kalın**") == "*kalın*"
    assert slack_blocks.to_mrkdwn("## Başlık") == "Başlık"
    assert (
        slack_blocks.to_mrkdwn("[Coursera](https://www.coursera.org)")
        == "<https://www.coursera.org|Coursera>"
    )


def test_clip_cuts_on_a_word_boundary_and_marks_the_cut():
    out = slack_blocks.clip("bir iki üç dört beş altı yedi sekiz", 20)
    assert len(out) <= 20
    assert out.endswith("…")
    assert not out.startswith("bir iki üç dört beş altı")


# --- the delivered payload --------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_slack_env(monkeypatch):
    for var in ["SLACK_WEBHOOK_URL", "SLACK_BOT_TOKEN", "SLACK_CHANNEL", "SLACK_MAIN_CHANNEL"]:
        monkeypatch.delenv(var, raising=False)
    for key in channel_config.ADVISOR_KEYS:
        monkeypatch.delenv(channel_config.advisor_channel_env(key), raising=False)
    channel_config.reset_channel_config()
    yield
    channel_config.reset_channel_config()


def test_the_channel_fan_out_sends_the_new_card_with_its_fallback_text(
    monkeypatch, tmp_path
):
    """The per-advisor channel gets blocks AND text — Slack needs both."""
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_CHANNEL_MARKET_INTELLIGENCE", "CMARKET")
    channel_config.reset_channel_config()

    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json or {})

        class Resp:
            status_code = 200
            is_success = True
            text = "{}"

            @staticmethod
            def json():
                return {"ok": True, "ts": "1.2"}

        return Resp()

    monkeypatch.setattr(slack_channels, "http_post", fake_post)

    supervision = Supervision(
        briefings=[
            Briefing(
                key="market_intelligence",
                title="Pazar İstihbaratı",
                status=STATUS_OK,
                text=TYPICAL,
                new_findings=2,
            )
        ]
    )
    publication = reports.publish(supervision, root=str(tmp_path / "reports"), now=NOW)
    dist = slack_channels.distribute(supervision, publication, base_url="https://pano/")

    assert dist.delivered == 1
    payload = next(p for p in sent if p.get("channel") == "CMARKET")
    assert payload["text"], "the notification fallback must be sent"
    assert payload["blocks"][0]["type"] == "header"
    assert "🆕 2 yeni bulgu" in _blob(payload["blocks"])
    assert "https://pano/#/rapor/2026-08-04/market_intelligence" in _blob(payload["blocks"])


def test_the_webhook_fallback_still_carries_blocks_and_text(monkeypatch):
    """Incoming webhooks accept `blocks`; the summary must not degrade to text."""
    from ai_assistant.notifiers import slack_notifier

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/X/Y/Z")
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append((url, json or {}))

        class Resp:
            status_code = 200
            is_success = True
            text = "ok"

            @staticmethod
            def json():
                return {"ok": True}

        return Resp()

    monkeypatch.setattr(slack_notifier, "http_post", fake_post)

    result = slack_notifier.send_message("merhaba", blocks=[slack_blocks.section("gövde")])

    assert result.status == STATUS_OK
    url, payload = sent[0]
    assert url.startswith("https://hooks.slack.com/")
    assert payload["text"] == "merhaba"
    assert payload["blocks"][0]["type"] == "section"


def test_the_webhook_payload_omits_blocks_when_there_are_none(monkeypatch):
    """Degrade sensibly: a plain-text message stays a plain-text message."""
    from ai_assistant.notifiers import slack_notifier

    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/X/Y/Z")
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json or {})

        class Resp:
            status_code = 200
            is_success = True
            text = "ok"

        return Resp()

    monkeypatch.setattr(slack_notifier, "http_post", fake_post)
    slack_notifier.send_message("sadece metin")

    assert sent[0] == {"text": "sadece metin"}
