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


def test_every_hand_written_legend_names_its_series(html):
    """Identity must never depend on colour matching alone.

    This used to count the hand-written legends in the HTML and demand at
    least three. That count stopped being a measure of anything when the v2
    builders landed: the "token payı / çıktı payı" pair became a donutChart,
    whose legend — with a swatch AND the slice's per cent next to every name —
    is BUILT AT RUNTIME by ``legendList`` in charts.js, so its hard-coded
    ``<ul class="legend">`` was correctly deleted from the markup. Counting
    literals therefore punished the change that added legends.

    The invariant is split in two instead: every legend that IS written by
    hand must name its series (here), and every multi-series builder must emit
    one at runtime (:func:`test_every_multi_series_builder_emits_a_legend`).
    """
    legends = re.findall(r'<ul class="legend"[^>]*>(.*?)</ul>', html, re.DOTALL)
    assert legends, "no hand-written legend left in the markup"
    for legend in legends:
        assert "swatch" in legend
        # A swatch with no words next to it is exactly the failure mode this
        # guards against, so every item must carry text as well.
        for item in re.findall(r"<li>(.*?)</li>", legend, re.DOTALL):
            assert re.sub(r"<[^>]+>", "", item).strip(), f"legend item with no label: {item}"


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


# --- reading view (per-advisor report document) ------------------------------


def test_the_reading_view_has_a_title_block_lead_metrics_body_and_blocks(html):
    """Every element the structured document renderer reaches for exists."""
    for element_id in [
        "doc-kicker",
        "doc-emoji",
        "doc-title",
        "doc-meta",
        "doc-facts",
        "doc-lead",
        "doc-metrics",
        "doc-body",
        "doc-actions",
        "doc-actions-list",
        "doc-sources",
        "doc-sources-list",
        "doc-stamp",
        "doc-print",
        "doc-back-day",
    ]:
        assert f'id="{element_id}"' in html


def test_the_action_checklist_renders_deadline_and_owner_as_badges(app):
    """Gap check: the schema's ActionItem.deadline/owner must reach the DOM,
    not stop at the JSON — a deadline is a badge, never plain trailing text."""
    block = app.split("function renderDocActions(doc)", 1)[1].split(
        "\n  function ", 1
    )[0]
    assert "checklist__item" in block
    assert "badge--deadline" in block
    assert "badge--owner" in block
    assert "📅" in block and "👤" in block


def test_schema_1_archives_do_not_repeat_the_headline_inside_the_body(app):
    """A legacy (schema 1) document has no `sections`, so its raw markdown
    still opens with the same "Öne çıkan:" line `doc-lead` already shows.
    Without stripping it, every report published before schema 2 existed
    prints its lead sentence twice, one line apart."""
    assert "function stripLeadingHeadlineLine(markdown)" in app
    assert "HEADLINE_LINE_RE" in app
    block = app.split("function renderDocBody(doc)", 1)[1].split("sections.forEach", 1)[0]
    assert "stripLeadingHeadlineLine" in block


def test_strip_leading_headline_line_only_drops_the_explicit_marker():
    """Executes the real regex/function under node — not just a string check.

    Only the leading, EXPLICIT "Öne çıkan:" marker line is ever removed; a
    schema 1 body with no such marker (the common case: a plain first
    sentence with no bolded lead) must be returned untouched, or a legacy
    report with no explicit marker would silently lose its opening line.
    """
    if shutil_which_node() is None:
        pytest.skip("node is not installed")
    body = APP.read_text(encoding="utf-8")
    func_match = re.search(
        r"function stripLeadingHeadlineLine\(markdown\) \{.*?\n  \}\n", body, re.DOTALL
    )
    re_match = re.search(r"var HEADLINE_LINE_RE = .*?;\n", body)
    assert func_match and re_match

    script = (
        re_match.group(0)
        + func_match.group(0)
        + "var cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        + "process.stdout.write(JSON.stringify(cases.map(stripLeadingHeadlineLine)));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps(
            [
                "**Öne çıkan:** Ritmi sabitle.\n\nDevamı burada.",
                "Öne çıkan: Ritmi sabitle.\nDevamı burada.",
                "Sıradan bir ilk cümle, işaret yok.\nDevamı burada.",
                "",
            ]
        ),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out[0] == "Devamı burada."
    assert out[1] == "Devamı burada."
    # No marker line at all: the whole body must survive unchanged.
    assert out[2] == "Sıradan bir ilk cümle, işaret yok.\nDevamı burada."
    assert out[3] == ""


def test_print_stylesheet_hides_the_app_chrome_and_forces_ink_on_white(css):
    assert "@media print" in css
    block = css.split("@media print {", 1)[1]
    # The shell never survives to paper: nav, tab bar, buttons, banners.
    for selector in [".topbar", ".tabbar", ".banner", ".doc-nav", ".no-print"]:
        assert selector in block
    # A dark theme printed as-is wastes a cartridge and reads worse — colours
    # are forced to ink on white regardless of which theme was active.
    assert "#ffffff" in block and "#000000" in block
    # Sensible page breaks: a card must not split mid-block, a heading must
    # not end a page with nothing under it.
    assert "break-inside: avoid" in block
    assert "break-after: avoid" in block


def test_mobile_reading_view_stays_single_column_at_375px(css):
    """The prose measure is capped for readability, and the phone breakpoint
    covers a 375px viewport comfortably (the common iPhone width)."""
    assert "max-width: 68ch" in css
    assert "@media (max-width: 480px)" in css
    mobile = css.split("@media (max-width: 480px)", 1)[1].split("@media", 1)[0]
    assert ".doc " in mobile or ".doc {" in mobile
    assert ".doc__metrics" in mobile


def test_a_sections_table_degrades_through_the_shared_data_table_builder(app):
    """A section's `table` spec must go through the same `dataTable` that
    already collapses to a card stack below 640px — not a bespoke markup."""
    assert "function mountSectionTable(host, spec)" in app
    block = app.split("function mountSectionTable(host, spec)", 1)[1].split(
        "function mountSectionChart", 1
    )[0]
    assert "charts.dataTable" in block


def shutil_which_node():
    return shutil.which("node")


# --- charts.js under node ---------------------------------------------------

node_only = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed"
)

# A DOM shim just rich enough for the builders: they create elements, set
# attributes, append children and — in the v2 builders — bind hover/focus
# handlers, which are registered and never fired.
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
    appendChild(child) {
      // A text node is content, not a child element: folding it into the
      // parent's text is what makes `walk()` see "swatch + label".
      if (child && child.tagName === "#text") { this._text += child._text; return child; }
      this.children.push(child);
      return child;
    },
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return null; },
    focus() {},
    classList: { add() {}, remove() {}, toggle() {} }
  };
}
global.document = {
  createElementNS: function (ns, name) { return makeNode(name); },
  createElement: function (name) { return makeNode(name); },
  createTextNode: function (value) {
    var node = makeNode("#text");
    node.textContent = value;
    return node;
  }
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


def _legend_labels(nodes: list) -> list:
    """Every ``<li>`` of a rendered legend, as (has_swatch, label) pairs."""
    out = []
    for index, node in enumerate(nodes):
        if node["tag"] != "li":
            continue
        # walk() flattens depth-first, so an item's swatch is the node right
        # after it when there is one.
        following = nodes[index + 1] if index + 1 < len(nodes) else {}
        out.append(("swatch" in str(following.get("cls") or ""), node["text"]))
    return out


@node_only
@pytest.mark.parametrize(
    "builder,args,series",
    [
        (
            "lineChart",
            [
                [
                    {
                        "name": "Tamamlanma",
                        "points": [
                            {"value": 40, "label": "1", "short": "1"},
                            {"value": 60, "label": "2", "short": "2"},
                        ],
                    },
                    {
                        "name": "Başarı",
                        "points": [
                            {"value": 80, "label": "1", "short": "1"},
                            {"value": 70, "label": "2", "short": "2"},
                        ],
                    },
                ],
                {},
            ],
            2,
        ),
        (
            "donutChart",
            [
                [
                    {"name": "Ajan A", "value": 5200},
                    {"name": "Ajan B", "value": 4800},
                    {"name": "Ajan C", "value": 1000},
                ],
                {},
            ],
            3,
        ),
        (
            "stackedRuns",
            [[{"at_istanbul": "31.07.2026 10:04", "ok": 2, "failed": 1, "skipped": 1}], {}],
            0,  # its three statuses are named in the hand-written legend
        ),
    ],
)
def test_every_multi_series_builder_emits_a_legend(builder, args, series):
    """The other half of the legend invariant, checked where it now lives.

    A chart that plots more than one series must SAY which is which, and the
    v2 builders do that at runtime rather than in the markup. ``stackedRuns``
    is the exception the parametrisation records: it is fed from a hand-written
    legend in index.html (its three colours are statuses, not series), so it
    correctly builds none of its own.
    """
    nodes = run_chart(builder, args)
    items = _legend_labels(nodes)
    assert len(items) == series
    for has_swatch, label in items:
        assert has_swatch, f"{builder} legend item without a swatch"
        assert label.strip(), f"{builder} legend item without a label"


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


# --- the files actually parse ----------------------------------------------
#
# Every test above reads app.js as TEXT, so a file that node refuses to parse
# still passes all of them while the dashboard renders nothing at all. This is
# not hypothetical: a round of "smart quotes" once turned ~40 lines of
# `$("report-grid")` into `$(“report-grid”)`, which is a SyntaxError at load.
# These two tests hand the real files to a real parser.


@node_only
@pytest.mark.parametrize("script", ["app.js", "charts.js"], ids=["app", "charts"])
def test_the_shipped_javascript_parses(script):
    """`node --check` on the real file, not a string match on its text."""
    result = subprocess.run(
        ["node", "--check", str(FRONTEND / script)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"frontend/{script} does not parse:\n{result.stderr}"
    )


@node_only
def test_no_typographic_quote_sits_in_javascript_syntax_position(app):
    """U+201C/U+201D are fine INSIDE a Turkish string, fatal as a delimiter.

    `node --check` is the real guard (a smart quote used as a delimiter is a
    SyntaxError), so this asserts the file parses and then pins the shapes
    that a quote-mangling editor produces, to fail with a readable message
    rather than a parser dump.
    """
    result = subprocess.run(
        ["node", "--check", str(APP)], capture_output=True, text=True
    )
    assert result.returncode == 0, f"frontend/app.js does not parse:\n{result.stderr}"

    for pattern in (r"\$\(\s*[“”]", r"[“”]\s*\)\s*;", r"\bvar\s+\w+\s*=\s*[“”]"):
        offenders = re.findall(pattern, app)
        assert not offenders, f"typographic quote in syntax position: {offenders[:5]}"


# --- the [hidden] attribute actually hides ----------------------------------
#
# `selectTab()` hides inactive panels with `panel.hidden = true`, and every
# panel also carries `class="stack"` — `display: grid`. An author rule beats
# the UA stylesheet's `[hidden] { display: none }`, so without a reset of our
# own the attribute is a no-op and all eight panels render at once as one
# endless page. The jsdom-backed tests cannot see this: jsdom applies the UA
# rule with a different cascade priority than a real browser, so it reports the
# panel as hidden either way. The assertion has to be made against the CSS
# source itself.


def test_the_hidden_attribute_is_reset_so_a_display_class_cannot_beat_it(css):
    """`[hidden] { display: none !important }` must exist in styles.css."""
    source = re.sub(r"/\*.*?\*/", "", css, flags=re.S)  # comments are not rules
    bodies = re.findall(r"(?:^|[,}])\s*\[hidden\]\s*\{([^}]*)\}", source)
    assert bodies, "styles.css has no [hidden] rule; .stack/.tile would win"
    assert any(re.search(r"display\s*:\s*none", b) for b in bodies), (
        f"[hidden] must set display: none, got: {[b.strip() for b in bodies]}"
    )
    assert any(
        re.search(r"display\s*:\s*none\s*!important", b) for b in bodies
    ), (
        "[hidden] must use !important — any component class that declares a "
        "display would otherwise defeat the attribute"
    )


# --- the metrics history outlives the roster --------------------------------
#
# `frontend/metrics.json` is an append-only measurement log, so it keeps rows
# for advisors that have since been retired (`weather` is the live example) and
# has no rows at all for advisors added after the last run. Both directions can
# mislead: a retired agent renders as a slice of the token ring as if it were
# still on staff, and a new advisor's absence reads as "costs nothing".
#
# Deleting the stale runs was the alternative and was rejected — those calls
# genuinely happened, and dropping them would both destroy real measurements
# and skew the run-level totals. The dashboard labels instead.


def test_a_retired_advisor_is_marked_archive_in_the_agent_charts():
    """Runs the real `aggregateAgents` under node against the real data files.

    Asserts against the shipped `metrics.json`/`advisors.json` rather than a
    fixture: the point is that TODAY's data is labelled correctly.
    """
    if shutil_which_node() is None:
        pytest.skip("node is not installed")
    body = APP.read_text(encoding="utf-8")
    num = re.search(r"function num\(value\) \{.*?\n  \}\n", body, re.DOTALL)
    roster = re.search(r"function rosterAdvisorIds\(\) \{.*?\n  \}\n", body, re.DOTALL)
    agg = re.search(r"function aggregateAgents\(runs\) \{.*?\n  \}\n", body, re.DOTALL)
    assert num and roster and agg

    metrics = json.loads((FRONTEND / "metrics.json").read_text(encoding="utf-8"))
    advisors = json.loads((FRONTEND / "advisors.json").read_text(encoding="utf-8"))
    # EXPERTISE_AREAS as applyAdvisorManifest() builds it: keyed by the hyphen
    # id, carrying the underscore `advisor_id` that metrics.json agents use.
    expertise = {
        row["advisor_id"].replace("_", "-"): {"advisor_id": row["advisor_id"]}
        for row in advisors["advisors"]
    }

    script = (
        "var input = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
        + "var EXPERTISE_AREAS = input.expertise;"
        + num.group(0)
        + roster.group(0)
        + agg.group(0)
        + "process.stdout.write(JSON.stringify(aggregateAgents(input.runs)));"
    )
    result = subprocess.run(
        ["node", "-e", script],
        input=json.dumps({"expertise": expertise, "runs": metrics["runs"]}),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    rows = {row["id"]: row for row in json.loads(result.stdout)}
    assert rows, "the shipped metrics.json produced no agent rows"

    roster_ids = {row["advisor_id"] for row in advisors["advisors"]}
    for agent_id, row in rows.items():
        expected = agent_id not in roster_ids
        assert row["retired"] is expected, f"{agent_id}: retired={row['retired']}"
        # The label the charts draw carries the marker, so a reader of the ring
        # never has to cross-check the roster by hand.
        assert row["label"].endswith(" (arşiv)") is expected, row["label"]

    # The regression this guards: `weather` was retired but still bills tokens
    # in the most recent full runs, so it is inside the 7-run chart window.
    assert "weather" in rows and rows["weather"]["retired"] is True


def test_the_roster_note_element_exists_and_is_filled_by_the_renderer(html, app):
    """The stale-data caveat must be rendered, not just present in the HTML."""
    assert 'id="agents-roster-note"' in html
    assert 'text($("agents-roster-note")' in app
