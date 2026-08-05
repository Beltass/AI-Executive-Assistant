"""Aksiyon Merkezi panosu: roster manifestten türer, bölümler gerçek veriden dolar."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ai_assistant import frontend_manifest, reports
from ai_assistant.status_report import ADVISOR_META, live_advisor_keys

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "app.js"
INDEX = FRONTEND / "index.html"
ADVISORS_JSON = FRONTEND / "advisors.json"


@pytest.fixture(scope="module")
def app() -> str:
    return APP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX.read_text(encoding="utf-8")


# --- roster tek kaynaktan ----------------------------------------------------


class TestManifestDerivedRoster:
    def test_advisors_json_matches_advisor_meta(self):
        """Elle senkronizasyon kalmadı: dosya manifestin aynısı olmalı."""
        assert not frontend_manifest.is_stale(str(ADVISORS_JSON)), (
            "frontend/advisors.json bayat — "
            "`python -m ai_assistant.frontend_manifest` ile yeniden üret"
        )

    def test_manifest_has_every_live_advisor_in_dashboard_order(self):
        payload = json.loads(ADVISORS_JSON.read_text(encoding="utf-8"))
        keys = [row["advisor_id"] for row in payload["advisors"]]
        assert keys == list(live_advisor_keys())
        assert payload["count"] == len(keys)
        orders = [row["dashboard_order"] for row in payload["advisors"]]
        assert orders == sorted(orders)

    def test_manifest_carries_the_fields_the_dashboard_reads(self):
        payload = frontend_manifest.build_manifest()
        for row in payload["advisors"]:
            meta = ADVISOR_META[row["advisor_id"]]
            assert row["name_tr"] == meta["title"]
            assert row["emoji"] == meta["emoji"]
            assert row["category"] == meta["category"]
            assert row["trigger"] == meta["trigger"]
            assert row["topic"] in frontend_manifest.TOPIC_COLORS

    def test_app_js_derives_the_roster_instead_of_holding_it(self, app):
        assert 'var ADVISORS_URL = "./advisors.json"' in app
        assert "function applyAdvisorManifest(manifest)" in app
        # Elle tutulan liste artık yalnızca YEDEK.
        assert "var FALLBACK_EXPERTISE_AREAS = {" in app
        assert "var EXPERTISE_AREAS = FALLBACK_EXPERTISE_AREAS;" in app
        assert "fetchOptional(ADVISORS_URL)" in app

    def test_manifest_order_is_used_with_a_defensive_fallback(self, app):
        block = app.split("function applyAdvisorManifest(manifest)", 1)[1].split(
            "\n  var state = {", 1
        )[0]
        assert "dashboard_order" in block
        # dashboard_order yoksa dosyadaki sıraya düşer.
        assert "index + 1" in block
        assert "if (!usable.length) return false;" in block


# --- Aksiyon Merkezi bölümleri ----------------------------------------------


class TestActionCenterSections:
    def test_the_tab_exists_end_to_end(self, app, html):
        assert 'id="tab-aksiyon"' in html
        assert 'id="panel-aksiyon"' in html
        assert 'aria-controls="panel-aksiyon"' in html
        assert 'aria-labelledby="tab-aksiyon"' in html
        tabs = re.search(r"var TABS = \[([^\]]+)\]", app)
        assert tabs and '"aksiyon"' in tabs.group(1)

    @pytest.mark.parametrize(
        "element",
        [
            "ac-priorities",
            "ac-approvals",
            "ac-risks",
            "ac-kpi",
            "ac-kpi-alerts",
            "ac-growth",
            "ac-system",
            "aksiyon-empty",
            "aksiyon-body",
        ],
    )
    def test_every_section_has_a_host_element(self, html, element):
        assert f'id="{element}"' in html

    def test_sections_read_the_real_files_not_a_fixture(self, app):
        block = app.split("/* TAB 0 — 🎯 Aksiyon Merkezi", 1)[1].split(
            "/* TAB 1 —", 1
        )[0]
        code = re.sub(r"/\*.*?\*/", "", block, flags=re.S)  # yorumlar kod değil
        code = re.sub(r"//[^\n]*", "", code)
        # Gerçek kaynaklar
        assert "state.days" in code  # günün rapor index'i
        assert "state.status" in code  # takvim / KPI / alarmlar
        assert "state.metrics" in code or "metricRuns()" in code  # token
        # Sabit örnek veri yok: bölümler hiçbir gömülü aksiyon listesi taşımaz.
        assert not re.search(r"title:\s*\"[^\"]{20,}\"", code)
        assert not re.search(r"owner:\s*\"[^\"]+\"", code)

    def test_top_three_priorities_are_p0_p1_only(self, app):
        block = app.split("function renderActionPriorities(actions)", 1)[1].split(
            "\n  function ", 1
        )[0]
        assert 'action.priority === "P0" || action.priority === "P1"' in block
        assert "slice(0, TOP_PRIORITY_LIMIT)" in block
        assert "var TOP_PRIORITY_LIMIT = 3;" in app

    def test_approvals_section_filters_on_approval_status(self, app):
        block = app.split("function renderActionApprovals(actions)", 1)[1].split(
            "\n  function ", 1
        )[0]
        assert 'action.approval === "pending"' in block

    def test_kpi_section_computes_a_deviation_from_the_series(self, app):
        assert "function deviation(series, current)" in app
        block = app.split("function renderActionKpis()", 1)[1].split(
            "\n  function ", 1
        )[0]
        assert "performance.trends" in block
        assert "performance.alerts" in block or "(performance.alerts" in block

    def test_system_section_reads_metrics_json(self, app):
        block = app.split("function renderActionSystem()", 1)[1].split(
            "\n  function ", 1
        )[0]
        assert "metricRuns()" in block
        assert "total_tokens" in block
        assert "latency_seconds" in block

    def test_growth_section_uses_manifest_categories(self, app):
        assert 'var GROWTH_CATEGORIES = ["kariyer", "kişisel gelişim"];' in app
        for category in ("kariyer", "kişisel gelişim"):
            assert any(
                meta["category"] == category
                for key, meta in ADVISOR_META.items()
                if key in set(live_advisor_keys())
            ), f"{category} kategorisinde canlı ajan yok"


# --- panonun okuduğu veri gerçekten yazılıyor mu -----------------------------


class TestDayIndexCarriesActions:
    def _report(self, actions):
        report = reports.PublishedReport(
            id="market_intelligence",
            name="Pazar İstihbaratı",
            emoji="📊",
            category="sektör",
            date="2026-08-05",
            headline="h",
            excerpt="e",
            words=10,
            read_minutes=1,
        )
        report.action_items = actions
        return report

    def test_card_publishes_action_center_items(self):
        card = self._report(
            [reports.ActionItem(text="Raporu bugün gönder", owner="Burak")]
        ).card()
        assert card["action_count"] == 1
        action = card["actions"][0]
        assert action["title"] == "Raporu bugün gönder"
        assert action["source_advisor"] == "market_intelligence"
        assert action["priority"] == "P0"  # "bugün" danışmanın kendi kelimesi

    def test_priority_falls_back_to_the_written_deadline(self):
        card = self._report(
            [reports.ActionItem(text="Sunumu hazırla", deadline="bu hafta")]
        ).card()
        assert card["actions"][0]["priority"] == "P1"
        assert card["actions"][0]["due_date"] == "bu hafta"

    def test_a_plain_action_stays_p2_and_needs_no_approval(self):
        card = self._report([reports.ActionItem(text="Makaleyi oku")]).card()
        assert card["actions"][0]["priority"] == "P2"
        assert card["actions"][0]["approval_status"] == "not_required"

    def test_an_action_that_asks_for_approval_is_marked_pending(self):
        card = self._report(
            [reports.ActionItem(text="Bütçe için yöneticiden onay al")]
        ).card()
        assert card["actions"][0]["approval_status"] == "pending"

    def test_app_js_reads_the_same_key_the_card_writes(self, app):
        card = self._report([reports.ActionItem(text="x")]).card()
        assert "actions" in card
        assert "Array.isArray(entry.actions)" in app
