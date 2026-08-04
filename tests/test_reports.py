"""Tests for the published report documents.

The dashboard is PUBLIC, so the most important assertions here are the negative
ones: a private advisor's content must never appear anywhere under
``frontend/reports/``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from ai_assistant import reports
from ai_assistant.advisors import Advisor, Briefing
from ai_assistant.advisors.daily_ops_briefing import DailyOpsBriefingAdvisor
from ai_assistant.integrations import STATUS_FAILED, STATUS_OK, STATUS_SKIPPED
from ai_assistant.operations_manager import Supervision
from ai_assistant.status_report import ISTANBUL

NOW = datetime(2026, 7, 31, 10, 4, tzinfo=ISTANBUL)

SECTION = """**Öne çıkan:** Ekibinin haftalık ritmini 20 dakikalık bir kontrol
toplantısıyla sabitle.

## Neden önemli

Sabit ritim, sürpriz eskalasyonları yarıya indirir.

- Birinci madde
- İkinci madde

[Coursera](https://www.coursera.org)
"""


def _briefing(key="leadership_coach", title="Liderlik Koçu", text=SECTION, **kwargs):
    return Briefing(key=key, title=title, status=STATUS_OK, text=text, **kwargs)


def _supervision(*briefings, mode="full"):
    return Supervision(briefings=list(briefings), mode=mode)


# --- shape ------------------------------------------------------------------


def test_publish_writes_one_document_per_advisor(tmp_path):
    publication = reports.publish(
        _supervision(
            _briefing(),
            _briefing(key="ai_news", title="Yapay Zeka Haberleri"),
        ),
        root=str(tmp_path),
        now=NOW,
    )

    assert publication.date == "2026-07-31"
    assert [r.id for r in publication.reports] == ["leadership_coach", "ai_news"]

    day = tmp_path / "2026-07-31"
    assert (day / "leadership_coach.json").exists()
    assert (day / "ai_news.json").exists()

    document = json.loads((day / "leadership_coach.json").read_text(encoding="utf-8"))
    assert document["id"] == "leadership_coach"
    assert document["name"] == "Liderlik Koçu"
    assert document["date"] == "2026-07-31"
    assert document["emoji"]
    assert document["category"]
    assert document["read_minutes"] >= 1
    assert document["words"] > 0
    assert "Öne çıkan" in document["markdown"] or document["headline"]
    assert document["markdown"].strip()


def test_publish_writes_a_day_index_and_an_archive_index(tmp_path):
    reports.publish(_supervision(_briefing()), root=str(tmp_path), now=NOW)

    day_index = json.loads(
        (tmp_path / "2026-07-31" / "index.json").read_text(encoding="utf-8")
    )
    assert day_index["date"] == "2026-07-31"
    assert day_index["count"] == 1
    assert day_index["mode"] == "full"
    assert day_index["reports"][0]["path"] == "leadership_coach.json"
    # The index is an INDEX: no bodies in it, or the phone downloads the whole
    # briefing just to draw the cards.
    assert "markdown" not in day_index["reports"][0]

    archive = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert archive["days"][0]["date"] == "2026-07-31"
    assert archive["days"][0]["count"] == 1


def test_report_route_matches_the_dashboard_router(tmp_path):
    publication = reports.publish(_supervision(_briefing()), root=str(tmp_path), now=NOW)
    assert publication.reports[0].route == "#/rapor/2026-07-31/leadership_coach"


def test_incremental_run_adds_to_the_day_instead_of_replacing_it(tmp_path):
    reports.publish(_supervision(_briefing()), root=str(tmp_path), now=NOW)
    later = NOW + timedelta(hours=4)
    reports.publish(
        _supervision(
            _briefing(key="ai_news", title="Yapay Zeka Haberleri"), mode="incremental"
        ),
        root=str(tmp_path),
        now=later,
    )

    day_index = json.loads(
        (tmp_path / "2026-07-31" / "index.json").read_text(encoding="utf-8")
    )
    ids = [entry["id"] for entry in day_index["reports"]]
    assert ids == ["leadership_coach", "ai_news"]
    # The morning's document is still on disk, untouched.
    assert (tmp_path / "2026-07-31" / "leadership_coach.json").exists()


def test_a_later_run_refreshes_an_advisors_own_card(tmp_path):
    reports.publish(_supervision(_briefing()), root=str(tmp_path), now=NOW)
    reports.publish(
        _supervision(_briefing(text="**Öne çıkan:** Yeni sürüm.")),
        root=str(tmp_path),
        now=NOW + timedelta(hours=4),
    )
    day_index = json.loads(
        (tmp_path / "2026-07-31" / "index.json").read_text(encoding="utf-8")
    )
    assert len(day_index["reports"]) == 1
    assert day_index["reports"][0]["headline"] == "Yeni sürüm."


# --- what is NOT published --------------------------------------------------


def test_failed_and_skipped_and_quiet_sections_are_not_published(tmp_path):
    publication = reports.publish(
        _supervision(
            Briefing(key="a", title="A", status=STATUS_FAILED, text="LLM patladı"),
            Briefing(key="b", title="B", status=STATUS_SKIPPED, text="missing env"),
            Briefing(
                key="c", title="C", status=STATUS_SKIPPED, text="yeni bulgu yok",
                nothing_new=True,
            ),
            Briefing(key="d", title="D", status=STATUS_OK, text="   "),
        ),
        root=str(tmp_path),
        now=NOW,
    )
    assert publication.reports == []
    # An idle run leaves no empty directories behind.
    assert not (tmp_path / "2026-07-31").exists()


# --- PRIVACY ----------------------------------------------------------------

PERSONAL = (
    "**Öne çıkan:** Bugün 3 acil e-posta var.\n\n"
    "- Ayşe Yılmaz'dan gelen 'Q3 bütçe onayı' konulu e-posta yanıt bekliyor.\n"
    "- 14:00 — Genel Müdür ile birebir görüşme.\n"
)


def test_private_advisor_content_never_lands_in_a_published_file(tmp_path):
    """The single most important test in this repository.

    The dashboard is a PUBLIC site built from a PUBLIC repository. The
    Gmail/Calendar briefing carries real names, real subjects and real meetings,
    so not one byte of it may reach ``frontend/reports/``.
    """
    publication = reports.publish(
        _supervision(
            _briefing(),
            Briefing(
                key="daily_ops_briefing",
                title="Gün Başı Operasyon Brifingi",
                status=STATUS_OK,
                text=PERSONAL,
                private=True,
            ),
        ),
        root=str(tmp_path),
        now=NOW,
    )

    assert [r.id for r in publication.reports] == ["leadership_coach"]
    assert len(publication.private) == 1

    written = list(tmp_path.rglob("*.json"))
    assert written, "the public advisor should still have been published"
    for path in written:
        blob = path.read_text(encoding="utf-8")
        assert "daily_ops_briefing" not in blob
        assert "Ayşe Yılmaz" not in blob
        assert "Q3 bütçe onayı" not in blob
        assert "Genel Müdür" not in blob


def test_private_is_detected_from_the_key_even_without_the_flag(tmp_path):
    """Belt and braces: losing the flag in a refactor must not leak the section."""
    publication = reports.publish(
        _supervision(
            Briefing(
                key="daily_ops_briefing",
                title="Gün Başı Operasyon Brifingi",
                status=STATUS_OK,
                text=PERSONAL,  # private=False — the flag was "lost"
            )
        ),
        root=str(tmp_path),
        now=NOW,
    )
    assert publication.reports == []
    assert not any(
        "Ayşe Yılmaz" in path.read_text(encoding="utf-8")
        for path in tmp_path.rglob("*.json")
    )


def test_the_ops_briefing_advisor_declares_itself_private():
    assert DailyOpsBriefingAdvisor.private is True


def test_private_key_list_matches_the_rosters_private_flags():
    """The safety net only helps if it names every private advisor we run."""
    from ai_assistant.advisors import all_advisors

    roster = all_advisors()
    private = {a.key for a in roster if a.private}
    public = {a.key for a in roster if not a.private}

    assert private == {
        "communications_calendar",
        "meeting_prep",
        "data_analyst",
        "ai_innovation",
        "executive_coaching",
        "work_analyst",
        "operations_director",
        "sre_watchdog",
    }
    # Every private advisor is covered…
    assert private <= reports.PRIVATE_ADVISOR_KEYS
    # …and no public one was swept in by mistake.
    assert not (public & reports.PRIVATE_ADVISOR_KEYS)


def test_advisors_are_public_by_default():
    assert Advisor.private is False


def test_the_private_flag_travels_on_the_briefing():
    class Personal(Advisor):
        key = "personal"
        title = "Kişisel"
        private = True

    advisor = Personal()
    assert advisor.ok("x").private is True
    assert advisor.skipped("x").private is True
    assert advisor.failed("x").private is True
    assert advisor.nothing_new().private is True


def test_a_private_card_in_an_old_index_is_dropped_on_merge(tmp_path):
    """Even a stale index written before the privacy rule gets cleaned up."""
    day = tmp_path / "2026-07-31"
    day.mkdir(parents=True)
    (day / "index.json").write_text(
        json.dumps(
            {"date": "2026-07-31", "reports": [{"id": "daily_ops_briefing", "name": "x"}]}
        ),
        encoding="utf-8",
    )
    reports.publish(_supervision(_briefing()), root=str(tmp_path), now=NOW)
    index = json.loads((day / "index.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in index["reports"]] == ["leadership_coach"]


# --- headline extraction ----------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("**Öne çıkan:** Ritmi sabitle.\n\nDevamı…", "Ritmi sabitle."),
        ("Öne çıkan: Ritmi sabitle.", "Ritmi sabitle."),
        ("*Öne Çıkan:* Ritmi sabitle.", "Ritmi sabitle."),
        ("**ÖNE ÇIKAN BULGU:** Ritmi sabitle.", "Ritmi sabitle."),
        ("**One cikan:** Ritmi sabitle.", "Ritmi sabitle."),
        ("**Öne çıkan** - Ritmi sabitle.", "Ritmi sabitle."),
    ],
)
def test_headline_is_lifted_from_the_marker_line(text, expected):
    assert reports.extract_headline(text) == expected


def test_headline_finds_the_marker_below_a_heading():
    text = "## Liderlik\n\n**Öne çıkan:** Ritmi sabitle.\n\nDevamı."
    assert reports.extract_headline(text) == "Ritmi sabitle."


def test_headline_falls_back_to_the_first_sentence():
    text = "# Başlık\n\nRitmi sabitlemek en hızlı kazanç. İkinci cümle burada."
    assert reports.extract_headline(text) == "Ritmi sabitlemek en hızlı kazanç."


def test_headline_falls_back_past_markdown_decoration():
    text = "- **Önemli:** bir madde\n"
    assert reports.extract_headline(text) == "Önemli: bir madde"


def test_headline_is_empty_for_an_empty_section():
    assert reports.extract_headline("") == ""
    assert reports.extract_headline("   \n\n  ") == ""


def test_headline_is_clipped():
    long = "**Öne çıkan:** " + ("kelime " * 200)
    headline = reports.extract_headline(long)
    assert len(headline) <= reports.MAX_HEADLINE_CHARS + 1
    assert headline.endswith("…")


def test_read_minutes_never_reaches_zero():
    assert reports.read_minutes(0) == 1
    assert reports.read_minutes(10) == 1
    assert reports.read_minutes(1000) == 5


# --- structured schema: key metrics, sections, action items, sources --------


def test_derive_key_metrics_reads_only_the_labelled_figure_shape():
    text = (
        "**Sıcaklık:** 23 °C ↑\n"
        "- **Nem:** 61 % →\n"
        "Rüzgar hızı bugün oldukça yüksek olacak.\n"
        "**Basınç:** 1012 hPa ↓\n"
    )
    metrics = reports.derive_key_metrics(text)
    assert [m.label for m in metrics] == ["Sıcaklık", "Nem", "Basınç"]
    assert metrics[0].value == "23"
    assert metrics[0].unit == "°C"
    assert metrics[0].trend == "up"
    assert metrics[1].trend == "flat"
    assert metrics[2].trend == "down"


def test_derive_key_metrics_ignores_running_prose():
    text = "Bugün üç toplantı var ve saat 14:00'te bir görüşme planlandı."
    assert reports.derive_key_metrics(text) == []


def test_derive_key_metrics_caps_and_dedupes_by_label():
    lines = "\n".join(f"**Gösterge {i}:** {i} birim" for i in range(10))
    lines += f"\n**Gösterge 0:** 999 birim"  # a repeat of the first label
    metrics = reports.derive_key_metrics(lines)
    assert len(metrics) == reports.MAX_KEY_METRICS
    assert metrics[0].value == "0"  # the first occurrence wins, not the repeat


def test_extract_sources_prefers_link_labels_and_dedupes_by_url():
    text = (
        "Bkz. [Gartner](https://www.gartner.com/report) için detaylar. "
        "Ayrıca https://www.gartner.com/report tekrar geçiyor. "
        "Ham bağlantı: https://example.com/whitepaper.pdf"
    )
    sources = reports.extract_sources(text)
    assert [s.url for s in sources] == [
        "https://www.gartner.com/report",
        "https://example.com/whitepaper.pdf",
    ]
    assert sources[0].title == "Gartner"
    assert sources[1].title == "example.com"  # bare URL titled by its domain


def test_extract_sources_caps_at_the_configured_limit():
    text = "\n".join(f"https://example.com/{i}" for i in range(reports.MAX_SOURCES + 5))
    sources = reports.extract_sources(text)
    assert len(sources) == reports.MAX_SOURCES


def test_split_sections_lifts_the_task_heading_into_action_items():
    text = (
        "**Öne çıkan:** Ritmi sabitle.\n\n"
        "Açılış paragrafı burada.\n\n"
        "#### ✅ Bugünün görevi\n"
        "- Ekip toplantısını planla (son tarih: bugün) (sorumlu: Sen)\n"
        "- Notları paylaş\n\n"
        "## Ek düşünceler\n"
        "Bu bölüm sıradan metin olarak kalır.\n"
    )
    sections, actions, sources = reports.split_sections(text)

    assert len(actions) == 2
    assert actions[0].text == "Ekip toplantısını planla"
    assert actions[0].deadline == "bugün"
    assert actions[0].owner == "Sen"
    assert actions[1].text == "Notları paylaş"

    # The action heading itself never becomes a body section, but everything
    # else the advisor wrote keeps its place.
    titles = [s.title for s in sections]
    assert "Ek düşünceler" in titles
    assert not any("görevi" in (t or "").lower() for t in titles)

    # The opening "Öne çıkan" line is dropped from the section body — it is
    # already the document's lead — but the rest of the opening paragraph stays.
    assert sections[0].title == ""
    assert "Açılış paragrafı burada." in sections[0].body
    assert "Öne çıkan" not in sections[0].body


def test_split_sections_lifts_a_sources_heading_into_the_reference_list():
    text = (
        "Gövde metni.\n\n"
        "## Kaynaklar\n"
        "- **Kuruluş:** *Harvard Business Review* — müşteri sadakati stratejileri "
        "[makale](https://hbr.org/article)\n"
        "- [McKinsey](https://mckinsey.com/insight)\n"
    )
    sections, actions, sources = reports.split_sections(text)
    assert not actions
    assert [s.url for s in sources] == [
        "https://hbr.org/article",
        "https://mckinsey.com/insight",
    ]
    assert sources[0].note == "müşteri sadakati stratejileri"
    assert not any((s.title or "").lower() == "kaynaklar" for s in sections)


def test_split_sections_with_no_headings_is_one_untitled_section():
    """A report with zero headings must render exactly as it always did."""
    text = "**Öne çıkan:** Kısa bulgu.\n\nSade bir paragraf, başlıksız."
    sections, actions, sources = reports.split_sections(text)
    assert not actions
    assert not sources
    assert len(sections) == 1
    assert sections[0].title == ""
    assert "Sade bir paragraf" in sections[0].body


def test_coerce_helpers_prefer_advisor_supplied_structure_over_derivation():
    """An advisor that hands over its own structure wins; nothing is derived."""
    from types import SimpleNamespace

    briefing = SimpleNamespace(
        key="market_intelligence",
        title="Piyasa İstihbaratı",
        status=STATUS_OK,
        text="**Öne çıkan:** Metinden türetilecek başlık.\n\nGövde metni burada.",
        report={
            "headline": "Advisor'ın kendi başlığı.",
            "key_metrics": [{"label": "Endeks", "value": "1234", "trend": "up"}],
            "action_items": ["Bugün fiyat listesini gözden geçir (deadline: yarın)"],
            "sources": ["https://www.imf.org/reports"],
        },
    )
    report = reports.build_report(briefing, "2026-07-31", NOW)

    assert report.headline == "Advisor'ın kendi başlığı."
    assert [m.label for m in report.key_metrics] == ["Endeks"]
    assert report.key_metrics[0].trend == "up"
    assert [a.text for a in report.action_items] == [
        "Bugün fiyat listesini gözden geçir"
    ]
    assert report.action_items[0].deadline == "yarın"
    assert [s.url for s in report.sources] == ["https://www.imf.org/reports"]


def test_build_report_falls_back_to_derivation_when_nothing_is_supplied():
    """Every advisor of the current roster: prose only, still a full document."""
    report = reports.build_report(_briefing(), "2026-07-31", NOW)
    assert report.sections
    assert report.sources  # the Coursera link in SECTION
    assert report.headline == "Ekibinin haftalık ritmini 20 dakikalık bir kontrol"


# --- markdown export (Drive / Slack previews) --------------------------------


def test_render_markdown_document_mirrors_the_reading_view_structure():
    report = reports.build_report(
        _briefing(
            text=(
                "**Öne çıkan:** Ritmi sabitle.\n\n"
                "**Sıcaklık:** 23 °C ↑\n\n"
                "## Neden önemli\n"
                "Gövde metni burada.\n\n"
                "#### ✅ Bugünün görevi\n"
                "- Ekip toplantısını planla (son tarih: bugün)\n\n"
                "## Kaynaklar\n"
                "- **Kuruluş:** *Gartner* — piyasa analizi "
                "[rapor](https://www.gartner.com/report)\n"
            )
        ),
        "2026-07-31",
        NOW,
    )
    markdown = report.to_markdown()

    # Title block.
    assert markdown.startswith(f"# {report.emoji} {report.name}")
    assert "**Tarih:** 2026-07-31" in markdown
    assert "**Öne çıkan:** Ritmi sabitle." in markdown

    # A real Markdown table for the key metrics, not a prose recap.
    assert "## Öne çıkan göstergeler" in markdown
    assert "| Gösterge | Değer | Eğilim |" in markdown
    assert "| Sıcaklık | 23 °C | ↑ |" in markdown

    # The body section survives verbatim.
    assert "## Neden önemli" in markdown
    assert "Gövde metni burada." in markdown

    # The action checklist renders as real Markdown checkboxes.
    assert "## Aksiyonlar" in markdown
    assert "- [ ] Ekip toplantısını planla" in markdown
    assert "(son tarih: bugün)" in markdown

    # The sources list is numbered and keeps the advisor's note.
    assert "## Kaynaklar" in markdown
    assert (
        "1. [Kuruluş: Gartner](https://www.gartner.com/report) — piyasa analizi"
        in markdown
    )

    # A generation stamp closes the document.
    assert "Hazırlanma:" in markdown


def test_render_markdown_document_degrades_cleanly_for_prose_only_input():
    """The Drive export of a plain report is still one clean file, not a dump."""
    report = reports.build_report(
        _briefing(text="Sade bir paragraf, hiç başlık veya liste yok."),
        "2026-07-31",
        NOW,
    )
    markdown = report.to_markdown()
    assert "Sade bir paragraf" in markdown
    assert "## Öne çıkan göstergeler" not in markdown  # nothing to tabulate
    assert "## Aksiyonlar" not in markdown
    assert "## Kaynaklar" not in markdown


def test_published_document_carries_every_structured_field():
    report = reports.build_report(_briefing(), "2026-07-31", NOW)
    document = report.document()
    assert document["schema_version"] == reports.SCHEMA_VERSION
    for field in ("key_metrics", "sections", "action_items", "sources", "meta"):
        assert field in document
    assert isinstance(document["sections"], list) and document["sections"]


def test_real_archived_legacy_reports_have_no_structured_fields():
    """Locks in the assumption the frontend degrades against: a day published
    before schema 2 existed is a bare markdown blob, nothing more."""
    import glob
    import os

    root = os.path.join(
        os.path.dirname(__file__), "..", "frontend", "reports", "2026-07-30"
    )
    files = sorted(glob.glob(os.path.join(root, "*.json")))
    files = [f for f in files if not f.endswith("index.json")]
    assert len(files) >= 2, "expected at least two real legacy documents on disk"
    for path in files:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data.get("schema_version") == 1
        assert "markdown" in data
        for field in ("key_metrics", "sections", "action_items", "sources"):
            assert field not in data


# --- pruning ----------------------------------------------------------------


def _seed_days(root, count, start=datetime(2026, 6, 1, 10, 0, tzinfo=ISTANBUL)):
    for offset in range(count):
        day = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
        folder = root / day
        folder.mkdir(parents=True)
        (folder / "index.json").write_text(
            json.dumps({"date": day, "reports": []}), encoding="utf-8"
        )


def test_prune_keeps_the_rolling_window_and_drops_the_oldest(tmp_path):
    _seed_days(tmp_path, 35)
    removed = reports.prune(str(tmp_path), keep=30)

    assert len(removed) == 5
    assert removed == ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
    remaining = sorted(p.name for p in tmp_path.iterdir() if p.is_dir())
    assert len(remaining) == 30
    assert remaining[0] == "2026-06-06"


def test_prune_is_a_no_op_inside_the_window(tmp_path):
    _seed_days(tmp_path, 3)
    assert reports.prune(str(tmp_path), keep=30) == []
    assert len(list(tmp_path.iterdir())) == 3


def test_prune_ignores_anything_that_is_not_a_day(tmp_path):
    _seed_days(tmp_path, 2)
    (tmp_path / "index.json").write_text("{}", encoding="utf-8")
    (tmp_path / "not-a-day").mkdir()
    assert reports.prune(str(tmp_path), keep=1) == ["2026-06-01"]
    assert (tmp_path / "not-a-day").exists()
    assert (tmp_path / "index.json").exists()


def test_publish_prunes_and_rebuilds_the_archive(tmp_path):
    _seed_days(tmp_path, 3)
    publication = reports.publish(_supervision(_briefing()), root=str(tmp_path), now=NOW)
    assert publication.pruned == []

    archive = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert [day["date"] for day in archive["days"]][0] == "2026-07-31"  # newest first
    assert len(archive["days"]) == 4


def test_retention_is_configurable(monkeypatch):
    monkeypatch.setenv(reports.RETENTION_ENV, "7")
    assert reports.retention_days() == 7
    monkeypatch.setenv(reports.RETENTION_ENV, "sıfır")
    assert reports.retention_days() == reports.DEFAULT_RETENTION_DAYS
    monkeypatch.setenv(reports.RETENTION_ENV, "0")
    assert reports.retention_days() == reports.DEFAULT_RETENTION_DAYS


# --- safety -----------------------------------------------------------------


def test_publish_never_raises_on_an_unwritable_root(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    publication = reports.publish(
        _supervision(_briefing()), root=str(blocker), now=NOW
    )
    assert isinstance(publication, reports.Publication)


def test_a_key_shape_is_redacted_from_a_published_body(tmp_path):
    leaked = "**Öne çıkan:** hata\n\nHata: AIzaSyA1234567890abcdefghijklmnop çağrısı."
    reports.publish(
        _supervision(_briefing(text=leaked)), root=str(tmp_path), now=NOW
    )
    blob = (tmp_path / "2026-07-31" / "leadership_coach.json").read_text(
        encoding="utf-8"
    )
    assert "AIzaSyA1234567890abcdefghijklmnop" not in blob
    assert "***" in blob


def test_scrubbing_keeps_the_markdown_readable(tmp_path):
    reports.publish(_supervision(_briefing()), root=str(tmp_path), now=NOW)
    document = json.loads(
        (tmp_path / "2026-07-31" / "leadership_coach.json").read_text(encoding="utf-8")
    )
    assert "## Neden önemli" in document["markdown"]
    assert "- Birinci madde" in document["markdown"]
    assert "https://www.coursera.org" in document["markdown"]
