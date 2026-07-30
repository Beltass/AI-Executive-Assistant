/* Minimal, SAFE Markdown renderer for the report reading view.
 *
 * WHY THIS EXISTS instead of a library: the dashboard is a dependency-free
 * static page. Pulling marked.js off a CDN would add a third-party script to a
 * page that renders text produced by a language model — exactly the input you
 * do not want anywhere near an unaudited HTML pipeline.
 *
 * THE SAFETY RULE, in one line: the source is HTML-ESCAPED FIRST, and only the
 * handful of constructs below is turned back into markup afterwards. There is
 * no path by which a `<script>` in a report becomes a tag on the page. Links
 * are additionally restricted to http(s)/mailto, so `javascript:` URLs cannot
 * become clickable payloads.
 *
 * Supported subset: headings, bold, italic, strikethrough, inline code, fenced
 * code, unordered/ordered lists, blockquotes, horizontal rules, links and
 * paragraphs. Everything else degrades to plain text, which is the correct
 * failure mode for a reading page.
 *
 * Loaded as a plain <script> by index.html (exposes ``window.AIAMarkdown``) and
 * as a CommonJS module by tests/test_frontend_markdown.py (which runs it under
 * node), so it must not touch the DOM.
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.AIAMarkdown = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  // Sentinels used to park code spans while the inline rules run. They are
  // control characters, which are stripped from the source beforehand, so no
  // report can forge one.
  var CODE_OPEN = "\u0001";
  var CODE_CLOSE = "\u0002";

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeUrl(raw) {
    var url = String(raw || "").trim();
    // The value is already HTML-escaped, so it cannot break out of the
    // attribute; this check is about the SCHEME only.
    if (/^https?:\/\/[^\s]+$/i.test(url)) return url;
    if (/^mailto:[^\s]+$/i.test(url)) return url;
    return "";
  }

  function inlineMd(escaped) {
    var codes = [];
    var out = String(escaped);

    // Code spans first, so their contents are never touched by the rules below.
    out = out.replace(/`([^`]+)`/g, function (_m, code) {
      codes.push(code);
      return CODE_OPEN + (codes.length - 1) + CODE_CLOSE;
    });

    out = out.replace(/\[([^\]\n]*)\]\(([^)\s]+)\)/g, function (_m, label, url) {
      var href = safeUrl(url);
      if (!href) return label || url;
      return (
        '<a href="' + href + '" rel="noreferrer noopener" target="_blank">' +
        (label || href) +
        "</a>"
      );
    });

    out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/__([^_\n]+)__/g, "<strong>$1</strong>");
    out = out.replace(/(^|[\s(«"])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    out = out.replace(/(^|[\s(«"])_([^_\n]+)_/g, "$1<em>$2</em>");
    out = out.replace(/~~([^~\n]+)~~/g, "<del>$1</del>");

    out = out.replace(new RegExp(CODE_OPEN + "(\\d+)" + CODE_CLOSE, "g"), function (
      _m,
      index
    ) {
      return "<code>" + codes[Number(index)] + "</code>";
    });
    return out;
  }

  function renderMarkdown(source) {
    // Control characters are stripped up front: they carry no meaning in a
    // briefing and they are what the code-span sentinels are made of.
    var clean = String(source == null ? "" : source).replace(
      /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g,
      ""
    );
    var lines = clean.split(/\r?\n/);
    var html = [];
    var paragraph = [];
    var list = null; // "ul" | "ol"
    var quote = [];
    var fence = null;

    function flushParagraph() {
      if (!paragraph.length) return;
      html.push("<p>" + inlineMd(escapeHtml(paragraph.join(" "))) + "</p>");
      paragraph = [];
    }
    function flushList() {
      if (!list) return;
      html.push("</" + list + ">");
      list = null;
    }
    function flushQuote() {
      if (!quote.length) return;
      html.push("<blockquote>" + inlineMd(escapeHtml(quote.join(" "))) + "</blockquote>");
      quote = [];
    }
    function flushAll() {
      flushParagraph();
      flushList();
      flushQuote();
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      var trimmed = line.trim();

      // Fenced code blocks swallow everything until the closing fence.
      if (/^(```|~~~)/.test(trimmed)) {
        if (fence === null) {
          flushAll();
          fence = [];
        } else {
          html.push("<pre><code>" + escapeHtml(fence.join("\n")) + "</code></pre>");
          fence = null;
        }
        continue;
      }
      if (fence !== null) {
        fence.push(line);
        continue;
      }

      if (!trimmed) {
        flushAll();
        continue;
      }

      if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
        flushAll();
        html.push("<hr />");
        continue;
      }

      var heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
      if (heading) {
        flushAll();
        // The page already owns <h1>; report headings start at <h2> and never
        // go deeper than <h5>, which keeps the document outline sane.
        var level = Math.min(5, heading[1].length + 1);
        html.push(
          "<h" + level + ">" + inlineMd(escapeHtml(heading[2])) + "</h" + level + ">"
        );
        continue;
      }

      if (/^>\s?/.test(trimmed)) {
        flushParagraph();
        flushList();
        quote.push(trimmed.replace(/^>\s?/, ""));
        continue;
      }
      flushQuote();

      var bullet = /^[-*+]\s+(.*)$/.exec(trimmed);
      if (bullet) {
        flushParagraph();
        if (list !== "ul") {
          flushList();
          html.push("<ul>");
          list = "ul";
        }
        html.push("<li>" + inlineMd(escapeHtml(bullet[1])) + "</li>");
        continue;
      }

      var numbered = /^(\d{1,3})[.)]\s+(.*)$/.exec(trimmed);
      if (numbered) {
        flushParagraph();
        if (list !== "ol") {
          flushList();
          html.push("<ol>");
          list = "ol";
        }
        html.push("<li>" + inlineMd(escapeHtml(numbered[2])) + "</li>");
        continue;
      }

      flushList();
      paragraph.push(trimmed);
    }

    if (fence !== null) {
      html.push("<pre><code>" + escapeHtml(fence.join("\n")) + "</code></pre>");
    }
    flushAll();
    return html.join("\n");
  }

  return {
    escapeHtml: escapeHtml,
    safeUrl: safeUrl,
    inlineMd: inlineMd,
    renderMarkdown: renderMarkdown
  };
});
