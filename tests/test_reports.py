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
        "ai_innovation",
        "executive_coaching",
        "work_analyst",
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
