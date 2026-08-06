"""LinkedIn sekmesi: beş bölüm, tek çatı, sıfır sahte veri.

Bu sekmenin verisi (`frontend/linkedin.json`) HENÜZ YOK — erişim jetonu
alınmadı. Testlerin işi bu yüzden iki başlık altında toplanıyor:

1. Sekme mevcut kalıba bağlanmış mı (tab düğmesi, panel, rota, yükleme)?
2. Veri yokken pano dürüst mü — yani repoda örnek bir gönderi, uydurma bir
   takipçi sayısı ya da gömülü bir demo dizisi kalmış mı?
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
APP = FRONTEND / "app.js"
INDEX = FRONTEND / "index.html"
STYLES = FRONTEND / "styles.css"


@pytest.fixture(scope="module")
def app() -> str:
    return APP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return STYLES.read_text(encoding="utf-8")


class TestTabWiring:
    """Sekme, panoda zaten kurulu olan sekme kalıbına bağlanır."""

    def test_tab_button_exists(self, html):
        assert 'id="tab-linkedin"' in html
        assert 'data-tab="linkedin"' in html
        assert 'aria-controls="panel-linkedin"' in html

    def test_panel_is_a_tabpanel_labelled_by_its_tab(self, html):
        panel = html.split('id="panel-linkedin"', 1)[1][:400]
        assert 'role="tabpanel"' in panel
        assert 'aria-labelledby="tab-linkedin"' in panel
        assert "hidden" in panel

    def test_tab_is_in_the_routing_table(self, app):
        tabs = re.search(r"var TABS = \[(.*?)\];", app, re.S).group(1)
        assert '"linkedin"' in tabs

    def test_data_file_is_optional(self, app):
        """Dosya yoksa pano çökmez: fetchOptional, fetchJson değil."""
        assert 'var LINKEDIN_URL = "./linkedin.json";' in app
        assert "fetchOptional(LINKEDIN_URL)" in app
        assert "fetchJson(LINKEDIN_URL)" not in app

    def test_render_runs_on_every_load(self, app):
        assert app.count("renderLinkedIn();") >= 2

    def test_state_slot_exists(self, app):
        assert re.search(r"linkedin: null", app)


class TestFiveSections:
    """Kullanıcının istediği beş bölümün hepsi ayrı ayrı var."""

    @pytest.mark.parametrize(
        "anchor",
        [
            "li-pending-title",  # 1 onay bekleyen paylaşımlar
            "li-published-title",  # 2 yayınlananlar
            "li-engagement-title",  # 3 etkileşim trendi
            "li-followers-title",  # 4 takipçi trendi
            "li-profile-title",  # 5 profil sağlığı
        ],
    )
    def test_section_heading_exists(self, html, anchor):
        assert 'id="%s"' % anchor in html

    @pytest.mark.parametrize(
        "host",
        [
            "li-pending",
            "li-published",
            "chart-li-engagement",
            "table-li-engagement",
            "chart-li-followers",
            "li-profile-tiles",
            "li-profile-gaps",
        ],
    )
    def test_render_host_exists(self, html, host):
        assert 'id="%s"' % host in html

    @pytest.mark.parametrize(
        "fn",
        [
            "renderLinkedInPending",
            "renderLinkedInPublished",
            "renderLinkedInEngagement",
            "renderLinkedInFollowers",
            "renderLinkedInProfile",
        ],
    )
    def test_render_function_exists(self, app, fn):
        assert "function %s(" % fn in app


class TestNoFakeData:
    """Veri gelmiyor; o hâlde hiçbir yerde veri VARMIŞ gibi durmamalı."""

    def test_no_linkedin_json_is_shipped(self):
        assert not (FRONTEND / "linkedin.json").exists(), (
            "frontend/linkedin.json repoya girmiş — token yokken bu dosya "
            "ancak uydurma veri içerebilir"
        )

    def test_every_section_has_an_honest_empty_string(self, app):
        block = app.split("TAB 9 — 💼 LinkedIn", 1)[1].split("function renderAll(", 1)[0]
        assert block.count("LINKEDIN_EMPTY") >= 7

    def test_empty_message_says_the_integration_is_gone(self, app):
        assert (
            "LinkedIn API entegrasyonu kaldırıldı — ajan yalnızca öneri üretir."
            in app
        )

    def test_connection_state_is_in_the_markup(self, html):
        """The panel must say out loud that the agent cannot publish."""
        assert 'id="li-connection"' in html
        block = html.split('id="li-connection"', 1)[1][:800]
        assert "Otomatik paylaşım devre dışı" in block
        assert "paylaşmaz" in block

    def test_published_section_is_hidden(self, html):
        """Nothing can publish, so that list can never fill — keep it hidden."""
        block = html.split('id="li-published-title"', 1)[0]
        assert 'aria-labelledby="li-published-title" hidden' in block

    def test_no_sample_post_or_follower_count_in_the_source(self, app):
        block = app.split("TAB 9 — 💼 LinkedIn", 1)[1].split("function renderAll(", 1)[0]
        # Gömülü bir demo dizisi olsaydı burada dört haneli bir takipçi sayısı
        # ya da bir '#hashtag' sabiti dururdu.
        assert not re.search(r"followers:\s*\d", block)
        assert not re.search(r'"#\w', block)

    def test_missing_counts_render_as_a_dash_not_zero(self, app):
        """Ölçülmemiş beğeni ile sıfır beğeni aynı görünmemeli."""
        assert "function liNum(" in app
        assert 'liNum(value) == null ? "—"' in app


class TestReusesExistingBuilders:
    """Yeni kütüphane yok: mevcut charts.js ve mevcut sınıflar kullanılır."""

    def test_charts_come_from_charts_js(self, app):
        block = app.split("TAB 9 — 💼 LinkedIn", 1)[1].split("function renderAll(", 1)[0]
        assert "charts.lineChart(" in block
        assert "charts.dataTable(" in block

    def test_no_new_script_or_stylesheet_tag(self, html):
        scripts = re.findall(r'<script[^>]*src="([^"]+)"', html)
        assert sorted(scripts) == ["./app.js", "./charts.js", "./markdown.js"]
        links = re.findall(r'<link[^>]*href="([^"]+)"[^>]*rel="stylesheet"', html)
        links += re.findall(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"', html)
        assert all(not href.startswith("http") for href in links)

    def test_post_card_styles_allow_the_card_to_shrink(self, css):
        """390px'de uzun bir başlık sayfayı yatay kaydırmaya sokmamalı."""
        assert ".li-post > * {" in css
        assert "min-width: 0" in css.split(".li-post > * {", 1)[1][:80]
        assert "overflow-wrap: anywhere" in css.split(".li-post__title {", 1)[1][:220]
