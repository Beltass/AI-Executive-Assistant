"""Tests for the dashboard shell — ``frontend/index.html``, ``app.js``, ``charts.js``.

The dashboard is a static site with NO build step, so nothing type-checks it and
nothing catches a renamed element id or an accidental CDN import. These tests
are that safety net. They cover the promises the frontend makes:

* zero dependencies — no CDN, no import, no bundler;
* every element ``app.js`` reaches for actually exists in the HTML;
* the tab contract holds (five tabs, ARIA wired both ways, hash-routed);
* the chart builders produce real SVG for real data and a graceful empty box
  for no data;
* accessibility invariants: a status is never colour alone, every chart has a
  table view, dark mode is the default with a persisted toggle.

``charts.js`` is exercised under node with a minimal DOM shim, so the geometry
is genuinely executed rather than eyeballed. Without node those tests skip —
this is a Python package and node is not one of its dependencies.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
INDEX = FRONTEND / "index.html"
APP = FRONTEND / "app.js"
CHARTS = FRONTEND / "charts.js"
STYLES = FRONTEND / "styles.css"

TABS = ["sistem", "icerik", "performans", "isler", "fikirler"]


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app() -> str:
    return APP.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def css() -> str:
    return STYLES.read_text(encoding="utf-8")


# --- zero dependencies ------------------------------------------------------


def test_no_cdn_or_external_asset_is_loaded(html):
    """It must deploy as-is on GitHub Pages and Vercel, offline included."""
    for tag in re.findall(r'<(?:script|link)\b[^>]*>', html):
        url = re.search(r'(?:src|href)="([^"]+)"', tag)
        if not url:
            continue
        target = url.group(1)
        assert target.startswith("./") or target.startswith("data:"), (
            f"external asset in {tag}"
        )


def test_no_module_system_or_bundler_syntax(app):
    body = APP.read_text(encoding="utf-8")
    assert "import " not in body
    assert "require(" not in body
    assert "export " not in body


def test_every_referenced_script_exists(html):
    for src in re.findall(r'<script src="\./([^"]+)"', html):
        assert (FRONTEND / src).exists(), f"missing {src}"


# --- the element contract ---------------------------------------------------


def test_every_element_app_js_reaches_for_exists(html, app):
    """A renamed id is otherwise a silent null-dereference at runtime."""
    ids = set(re.findall(r'id="([^"]+)"', html))
    wanted = set(re.findall(r'\$\("([^"]+)"\)', app))
    assert wanted <= ids, f"app.js refers to missing ids: {sorted(wanted - ids)}"


def test_every_tab_has_a_button_and_a_panel(html):
    for tab in TABS:
        assert f'id="tab-{tab}"' in html
        assert f'id="panel-{tab}"' in html


def test_tabs_are_wired_for_screen_readers_in_both_directions(html):
    """`aria-controls` and `aria-labelledby` must point at each other."""
    for tab in TABS:
        button = re.search(
            r'<button[^>]*id="tab-%s"[^>]*>' % tab, html, re.DOTALL
        )
        assert button, f"tab-{tab} button missing"
        assert f'aria-controls="panel-{tab}"' in button.group(0)
        assert 'role="tab"' in button.group(0)

        panel = re.search(r'<section[^>]*id="panel-%s"[^>]*>' % tab, html, re.DOTALL)
        assert panel, f"panel-{tab} missing"
        assert 'role="tabpanel"' in panel.group(0)
        assert f'aria-labelledby="tab-{tab}"' in panel.group(0)


def test_exactly_one_tab_starts_selected(html):
    selected = re.findall(r'aria-selected="true"', html)
    assert len(selected) == 1


def test_the_tablist_is_labelled(html):
    tablist = re.search(r'<div[^>]*role="tablist"[^>]*>', html)
    assert tablist and "aria-label" in tablist.group(0)


# --- routing ----------------------------------------------------------------


def test_every_tab_is_a_hash_route(app):
    """Tabs are shareable and the back button works only if they are routed."""
    tab_list = re.search(r'var TABS = \[([^\]]+)\]', app)
    assert tab_list
    for tab in TABS:
        assert f'"{tab}"' in tab_list.group(1)
    assert 'window.location.hash = "#/" + button.dataset.tab' in app
    assert 'window.addEventListener("hashchange", applyRoute)' in app


def test_the_report_routes_are_still_supported(app):
    """The existing deep links in old Slack messages must keep working."""
    assert '"raporlar"' in app
    assert '"rapor"' in app
    assert 'name: "report"' in app


def test_routes_validate_their_parameters(app):
    """A hash is user input; a report id goes straight into a fetch path."""
    assert "DATE_RE" in app and "ID_RE" in app
    assert re.search(r"var DATE_RE = /\^\\d\{4\}-\\d\{2\}-\\d\{2\}\$/", app)


def test_keyboard_navigation_between_tabs_exists(app):
    for key in ["ArrowRight", "ArrowLeft", "Home", "End"]:
        assert key in app


# --- theme ------------------------------------------------------------------


def test_dark_is_the_default_theme(html):
    assert 'data-theme="dark"' in html


def test_the_theme_choice_is_applied_before_first_paint(html):
    """Otherwise a light-mode user gets a dark flash on every load."""
    head = html.split("</head>", 1)[0]
    assert "localStorage.getItem(\"aia-theme\")" in head


def test_the_theme_toggle_persists_its_choice(app):
    assert 'localStorage.setItem("aia-theme", theme)' in app


def test_light_mode_repoints_the_same_roles(css):
    """Light mode is SELECTED steps, not an automatic filter/invert flip."""
    assert ':root[data-theme="light"]' in css
    assert "invert(" not in css
    light = css.split(':root[data-theme="light"]', 1)[1].split("}", 1)[0]
    for role in ["--plane", "--surface-1", "--text-1", "--series-1", "--grid"]:
        assert role in light


# --- accessibility ----------------------------------------------------------


def test_status_is_never_colour_alone(app):
    """Every status label ships with an icon AND a Turkish word."""
    for table in ["STATUS_LABEL", "CONCLUSION", "SLACK_LABEL", "SEVERITY"]:
        assert table in app
    # The severity table is what the watchdog renders; check it carries both.
    block = app.split("var SEVERITY = {", 1)[1].split("};", 1)[0]
    for key in ["🟢", "🟡", "🔴", "Sağlıklı", "Dikkat"]:
        assert key in block


def test_reduced_motion_is_respected(css):
    assert "prefers-reduced-motion" in css
    block = css.split("prefers-reduced-motion", 1)[1]
    assert "transition: none" in block


def test_focus_is_always_visible(css):
    assert ":focus-visible" in css
    assert "outline: none" not in css.replace("outline: none;", "")


def test_charts_ship_a_table_view(html):
    """Three light-mode series colours sit below 3:1 — the table is the relief."""
    for host in ["table-history", "table-agents", "table-runs"]:
        assert f'id="{host}"' in html


def test_every_multi_series_chart_has_a_legend(html):
    """Identity must never depend on colour matching alone."""
    legends = re.findall(r'<ul class="legend"[^>]*>(.*?)</ul>', html, re.DOTALL)
    assert len(legends) >= 3
    for legend in legends:
        assert "swatch" in legend


def test_there_is_a_skip_link_and_a_main_landmark(html):
    assert 'class="skip-link"' in html
    assert 'id="main"' in html


# --- empty / error states ---------------------------------------------------


@pytest.mark.parametrize(
    "element",
    ["perf-empty", "isler-empty", "fikirler-empty", "sistem-error", "reports-empty"],
)
def test_every_tab_has_a_designed_empty_or_error_state(html, element):
    assert f'id="{element}"' in html


def test_the_stale_data_warning_exists_with_a_threshold(html, app):
    assert 'id="stale-banner"' in html
    assert "var STALE_HOURS = 12" in app
    assert "Veri eski görünüyor" in app


def test_loading_shows_a_skeleton_not_a_blank_page(html, css):
    assert 'class="skeleton' in html
    assert ".skeleton {" in css


# --- privacy ----------------------------------------------------------------


def test_the_dashboard_states_that_private_sections_are_never_published(html):
    assert "Kişisel veri içerebilecek" in html


def test_no_secret_shaped_string_is_hardcoded_in_the_frontend():
    for path in [INDEX, APP, CHARTS, STYLES]:
        body = path.read_text(encoding="utf-8")
        assert not re.search(r"AIza[0-9A-Za-z\-_]{10,}", body)
        assert not re.search(r"xox[baprs]-[A-Za-z0-9\-]{8,}", body)
        assert "hooks.slack.com" not in body


# --- charts.js under node ---------------------------------------------------

node_only = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed"
)

# A DOM shim just rich enough for the builders: they only ever create elements,
# set attributes and append children.
DOM_SHIM = """
function makeNode(name) {
  return {
    tagName: name,
    attrs: {},
    children: [],
    dataset: {},
    style: {},
    className: "",
    _text: "",
    set textContent(v) { this._text = String(v); },
    get textContent() { return this._text; },
    set innerHTML(v) { if (!v) this.children = []; },
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "class") this.className = String(v); },
    getAttribute(k) { return this.attrs[k]; },
    appendChild(child) { this.children.push(child); return child; }
  };
}
global.document = {
  createElementNS: function (ns, name) { return makeNode(name); },
  createElement: function (name) { return makeNode(name); }
};
global.window = {};
function walk(node, out) {
  out.push({ tag: node.tagName, attrs: node.attrs, cls: node.className, text: node.textContent });
  (node.children || []).forEach(function (child) { walk(child, out); });
  return out;
}
"""


def run_chart(builder: str, args: list) -> list:
    """Build a chart under node and return every node it produced, flattened."""
    script = (
        DOM_SHIM
        + "require(process.argv[1]);"
        + "var host = makeNode('div');"
        + "var args = JSON.parse(process.argv[2]);"
        + f"global.window.AIACharts.{builder}.apply(null, [host].concat(args));"
        + "process.stdout.write(JSON.stringify(walk(host, [])));"
    )
    result = subprocess.run(
        ["node", "-e", script, str(CHARTS), json.dumps(args)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@node_only
def test_charts_file_pulls_in_nothing():
    body = CHARTS.read_text(encoding="utf-8")
    assert "import " not in body
    assert "https://" not in body.split("*/", 1)[1] or "w3.org/2000/svg" in body


@node_only
def test_stacked_runs_draws_one_hit_target_per_run():
    nodes = run_chart(
        "stackedRuns",
        [
            [
                {"at_istanbul": "31.07.2026 10:04", "ok": 12, "failed": 1, "skipped": 2},
                {"at_istanbul": "31.07.2026 14:04", "ok": 3, "failed": 0, "skipped": 12},
            ],
            {},
        ],
    )
    hits = [n for n in nodes if n["cls"] == "chart__hit"]
    assert len(hits) == 2
    # Each hit target carries the full reading as an accessible label.
    assert all("çalıştı" in hit["attrs"]["aria-label"] for hit in hits)
    assert all(hit["attrs"]["tabindex"] == "0" for hit in hits)


@node_only
def test_stacked_runs_uses_status_colours_not_categorical_ones():
    nodes = run_chart(
        "stackedRuns", [[{"at_istanbul": "x", "ok": 2, "failed": 1, "skipped": 1}], {}]
    )
    fills = {n["attrs"].get("fill") for n in nodes if n["tag"] == "path"}
    assert "var(--good)" in fills
    assert "var(--critical)" in fills
    assert not any(f and "series" in f for f in fills)


@node_only
def test_an_empty_history_renders_a_message_not_a_broken_axis():
    nodes = run_chart("stackedRuns", [[], {}])
    assert any(n["cls"] == "chart-empty" for n in nodes)
    assert not any(n["tag"] == "svg" for n in nodes)


@node_only
def test_a_trend_needs_two_points_to_be_a_trend():
    single = run_chart("trend", [[{"value": 5, "label": "a", "short": "a"}], {}])
    assert any(n["cls"] == "chart-empty" for n in single)

    pair = run_chart(
        "trend",
        [
            [
                {"value": 5000, "label": "a", "short": "10:04"},
                {"value": 7000, "label": "b", "short": "14:04"},
            ],
            {"name": "Token"},
        ],
    )
    assert any(n["tag"] == "svg" for n in pair)
    # 2px line, round caps — the fixed mark spec.
    line = [n for n in pair if n["cls"] == "chart__line"]
    assert line


@node_only
def test_a_trend_labels_only_its_endpoint():
    nodes = run_chart(
        "trend",
        [
            [
                {"value": v, "label": str(v), "short": str(v)}
                for v in [1000, 2000, 3000, 4000, 5000]
            ],
            {"name": "Token"},
        ],
    )
    # A number on every point is chaos; exactly one direct value label.
    values = [n for n in nodes if n["cls"] == "chart__value"]
    assert len(values) == 1


@node_only
def test_split_bar_labels_only_segments_wide_enough_to_hold_the_text():
    nodes = run_chart(
        "splitBar",
        [
            [
                {"name": "Girdi", "value": 9000, "color": "var(--series-1)"},
                {"name": "Çıktı", "value": 3000, "color": "var(--series-2)"},
                {"name": "Düşünme", "value": 40, "color": "var(--series-3)"},
            ],
            {},
        ],
    )
    hits = [n for n in nodes if n["cls"] == "chart__hit"]
    assert len(hits) == 3
    # The 40-token sliver is far too narrow for an inside label; it must not be
    # drawn (and therefore cannot be clipped).
    inside = [n for n in nodes if n["cls"] == "chart__value"]
    assert len(inside) < 3


@node_only
def test_split_bar_reports_the_real_share_in_its_tooltip():
    nodes = run_chart(
        "splitBar",
        [
            [
                {"name": "Girdi", "value": 750, "color": "var(--series-1)"},
                {"name": "Çıktı", "value": 250, "color": "var(--series-2)"}
            ],
            {},
        ],
    )
    labels = [n["attrs"]["aria-label"] for n in nodes if n["cls"] == "chart__hit"]
    assert any("%75" in label for label in labels)


@node_only
def test_grouped_shares_draws_two_bars_per_agent_with_one_shared_scale():
    nodes = run_chart(
        "groupedShares",
        [
            [
                {"id": "a", "name": "Ajan A", "token_share": 52.0, "output_share": 38.0, "tokens": 5200},
                {"id": "b", "name": "Ajan B", "token_share": 48.0, "output_share": 62.0, "tokens": 4800},
            ],
            {},
        ],
    )
    paths = [n for n in nodes if n["tag"] == "path"]
    assert len(paths) == 4  # two agents x two series
    fills = {n["attrs"]["fill"] for n in paths}
    assert fills == {"var(--series-1)", "var(--series-2)"}
    # Both shares are in the tooltip, which is the whole comparison.
    labels = [n["attrs"]["aria-label"] for n in nodes if n["cls"] == "chart__hit"]
    assert any("%52" in label and "%38" in label for label in labels)


@node_only
def test_grouped_shares_truncates_a_long_agent_name_instead_of_overflowing():
    nodes = run_chart(
        "groupedShares",
        [
            [
                {
                    "id": "cx",
                    "name": "Çağrı Merkezi & Müşteri Deneyimi Araştırmacısı",
                    "token_share": 20.0,
                    "output_share": 20.0,
                    "tokens": 100,
                }
            ],
            {},
        ],
    )
    label = [n for n in nodes if n["cls"] == "chart__label"][0]
    assert label["text"].endswith("…")
    assert len(label["text"]) <= 26


@node_only
def test_the_table_builder_produces_a_real_table_with_a_caption():
    nodes = run_chart(
        "table",
        [
            [{"label": "Ajan"}, {"label": "Token", "num": True}],
            [["Ajan A", "5.200"], ["Ajan B", "4.800"]],
            "Tablo görünümü",
        ],
    )
    tags = [n["tag"] for n in nodes]
    assert tags.count("tr") == 3  # header + two rows
    assert "caption" in tags
    assert any(n["cls"] == "visually-hidden" for n in nodes)
