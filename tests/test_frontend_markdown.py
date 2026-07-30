"""Tests for the dashboard's Markdown renderer (``frontend/markdown.js``).

The reading view feeds MODEL-GENERATED text into ``innerHTML``. That is only
safe because the renderer escapes its input before it marks anything up, so the
escaping is worth testing for real rather than by inspection.

The renderer is plain CommonJS-compatible JavaScript with no DOM access, so it
is exercised under ``node`` (present on every GitHub Actions runner and on any
machine that can serve the dashboard). Without node the tests skip rather than
fail — this is a Python package, node is not one of its dependencies.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MARKDOWN_JS = Path(__file__).resolve().parents[1] / "frontend" / "markdown.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not installed"
)


def render(source: str) -> str:
    """Run ``renderMarkdown(source)`` under node and return the HTML."""
    script = (
        "const md = require(process.argv[1]);"
        "const input = JSON.parse(process.argv[2]);"
        "process.stdout.write(md.renderMarkdown(input));"
    )
    result = subprocess.run(
        ["node", "-e", script, str(MARKDOWN_JS), json.dumps(source)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout


def test_the_renderer_file_exists_and_pulls_in_nothing():
    body = MARKDOWN_JS.read_text(encoding="utf-8")
    assert "require(" not in body
    assert "cdn" not in body.lower() or "CDN would add" in body
    assert "https://" not in body.split("*/", 1)[1]  # no network in the code


# --- ESCAPING: the reason this file exists ---------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "<iframe src='https://evil.test'></iframe>",
        "</p><script>alert(1)</script><p>",
        "<svg/onload=alert(1)>",
    ],
)
def test_html_in_a_report_is_escaped_not_executed(payload):
    html = render(f"Bir bulgu: {payload}")
    assert "<script" not in html
    assert "<img" not in html
    assert "<iframe" not in html
    assert "<svg" not in html
    assert "onerror" not in html or "&lt;img" in html
    assert "&lt;" in html


def test_html_inside_every_block_type_is_escaped():
    source = (
        "# <script>a</script>\n\n"
        "- <script>b</script>\n\n"
        "> <script>c</script>\n\n"
        "1. <script>d</script>\n\n"
        "```\n<script>e</script>\n```\n"
    )
    html = render(source)
    assert "<script" not in html
    assert html.count("&lt;script&gt;") == 5


def test_quotes_and_ampersands_are_escaped():
    html = render('Tırnak " ve tek \' ve & işareti')
    assert "&quot;" in html
    assert "&#39;" in html
    assert "&amp;" in html


def test_a_javascript_url_never_becomes_a_link():
    html = render("[tıkla](javascript:alert(1))")
    assert "javascript:" not in html or "<a " not in html
    assert "<a " not in html


def test_a_data_url_never_becomes_a_link():
    html = render("[tıkla](data:text/html;base64,PHNjcmlwdD4=)")
    assert "<a " not in html


def test_an_http_link_is_kept_and_hardened():
    html = render("[Coursera](https://www.coursera.org)")
    assert '<a href="https://www.coursera.org"' in html
    assert 'rel="noreferrer noopener"' in html
    assert 'target="_blank"' in html


# --- the supported subset ---------------------------------------------------


def test_headings_start_at_h2():
    html = render("# Bir\n\n## İki\n\n### Üç\n\n###### Altı")
    assert "<h2>Bir</h2>" in html
    assert "<h3>İki</h3>" in html
    assert "<h4>Üç</h4>" in html
    assert "<h5>Altı</h5>" in html
    assert "<h1>" not in html
    assert "<h6>" not in html


def test_bold_italic_and_code():
    html = render("**kalın** ve _eğik_ ve `kod` ve ~~üstü çizili~~")
    assert "<strong>kalın</strong>" in html
    assert "<em>eğik</em>" in html
    assert "<code>kod</code>" in html
    assert "<del>üstü çizili</del>" in html


def test_markup_inside_a_code_span_is_not_interpreted():
    html = render("`**bu kalın olmamalı**`")
    assert "<strong>" not in html
    assert "<code>**bu kalın olmamalı**</code>" in html


def test_lists():
    html = render("- bir\n- iki\n\n1. üç\n2. dört")
    assert "<ul>\n<li>bir</li>\n<li>iki</li>\n</ul>" in html
    assert "<ol>\n<li>üç</li>\n<li>dört</li>\n</ol>" in html


def test_blockquote_and_rule_and_paragraphs():
    html = render("Bir paragraf.\n\n> alıntı\n\n---\n\nİkinci paragraf.")
    assert "<p>Bir paragraf.</p>" in html
    assert "<blockquote>alıntı</blockquote>" in html
    assert "<hr />" in html
    assert "<p>İkinci paragraf.</p>" in html


def test_a_fenced_block_is_preformatted():
    html = render("```\nsatır bir\nsatır iki\n```")
    assert "<pre><code>satır bir\nsatır iki</code></pre>" in html


def test_a_real_advisor_section_renders_end_to_end():
    source = (
        "**Öne çıkan:** Ritmi sabitle.\n\n"
        "## Neden işe yarar\n\n"
        "Sabit ritim sürprizleri azaltır.\n\n"
        "### 📚 Kaynaklar\n\n"
        "- [Coursera](https://www.coursera.org) — neden bu?\n"
        "- Kitap: *Radical Candor*\n\n"
        "### ✅ Bugünün görevi\n\n"
        "20 dakikalık bir kontrol toplantısı koy.\n"
    )
    html = render(source)
    assert "<strong>Öne çıkan:</strong>" in html
    assert "<h3>Neden işe yarar</h3>" in html
    assert "<h4>📚 Kaynaklar</h4>" in html
    assert '<a href="https://www.coursera.org"' in html
    assert "<em>Radical Candor</em>" in html


def test_empty_input_is_empty_output():
    assert render("") == ""
