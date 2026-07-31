/* AI Executive Assistant — inline SVG charts, zero dependencies.
 *
 * No charting library, no CDN, no build step: every chart below is SVG built
 * with `document.createElementNS`, which is why the dashboard still deploys as
 * a folder of static files on GitHub Pages and Vercel.
 *
 * THE RULES THESE BUILDERS ENFORCE (so no caller has to remember them):
 *
 *   * Marks are thin. Bars cap at 24px and never fill their slot — the leftover
 *     band is air.
 *   * A stacked bar's segments are separated by a 2px gap IN THE SURFACE
 *     COLOUR, never by a stroke. The gap is the separator; a border would add
 *     ink that is not data.
 *   * The data-end of a bar is 4px rounded; the baseline end is square.
 *   * Gridlines and axes are SOLID hairlines one step off the surface. Never
 *     dashed — dashing reads as "projection" when it is just a grid.
 *   * Text wears text tokens, never a series colour. Identity comes from the
 *     coloured mark beside the label, so a light hue is never used as type.
 *   * ONE y-axis. There is no dual-axis builder here on purpose: two scales on
 *     one plot invent a correlation the data does not contain.
 *   * Every chart gets a hover/focus layer with a hit target LARGER than the
 *     mark, and every chart ships an equivalent table view (`table()`), which
 *     is what keeps the light-mode aqua series readable.
 *
 * Colours come from CSS custom properties, so the light/dark swap happens in
 * one place and these builders never name a hex.
 */
(function (global) {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";

  /* --- tiny SVG helpers -------------------------------------------------- */

  function el(name, attrs) {
    var node = document.createElementNS(NS, name);
    for (var key in attrs || {}) {
      if (Object.prototype.hasOwnProperty.call(attrs, key)) {
        node.setAttribute(key, String(attrs[key]));
      }
    }
    return node;
  }

  function svgRoot(width, height) {
    var svg = el("svg", {
      viewBox: "0 0 " + width + " " + height,
      preserveAspectRatio: "xMidYMid meet",
      role: "presentation",
      focusable: "false"
    });
    return svg;
  }

  /** A rectangle whose TOP end is rounded and whose baseline end is square. */
  function columnPath(x, y, w, h, radius) {
    var r = Math.max(0, Math.min(radius, w / 2, h));
    if (h <= 0) return "";
    return (
      "M" + x + " " + (y + h) +
      "V" + (y + r) +
      "a" + r + " " + r + " 0 0 1 " + r + " " + -r +
      "h" + (w - 2 * r) +
      "a" + r + " " + r + " 0 0 1 " + r + " " + r +
      "V" + (y + h) +
      "Z"
    );
  }

  /** The same shape rotated: rounded at the RIGHT end, square at the left. */
  function barPath(x, y, w, h, radius) {
    var r = Math.max(0, Math.min(radius, h / 2, w));
    if (w <= 0) return "";
    return (
      "M" + x + " " + y +
      "h" + (w - r) +
      "a" + r + " " + r + " 0 0 1 " + r + " " + r +
      "v" + (h - 2 * r) +
      "a" + r + " " + r + " 0 0 1 " + -r + " " + r +
      "H" + x +
      "Z"
    );
  }

  function niceMax(value) {
    // Round the axis top to a clean number so the ticks read 0 / 5k / 10k.
    if (!value || value <= 0) return 1;
    var magnitude = Math.pow(10, Math.floor(Math.log10(value)));
    var steps = [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10];
    for (var i = 0; i < steps.length; i += 1) {
      if (steps[i] * magnitude >= value) return steps[i] * magnitude;
    }
    return 10 * magnitude;
  }

  function compact(value) {
    var n = Number(value) || 0;
    if (Math.abs(n) >= 1000000) return (n / 1000000).toFixed(1).replace(".", ",") + "M";
    if (Math.abs(n) >= 1000) {
      var k = n / 1000;
      return (k >= 10 ? Math.round(k) : k.toFixed(1).replace(".", ",")) + "K";
    }
    return String(Math.round(n));
  }

  /** Attach the shared tooltip behaviour to a hit rect. */
  function hoverable(node, label) {
    node.setAttribute("tabindex", "0");
    node.setAttribute("role", "img");
    node.setAttribute("aria-label", label);
    node.dataset.tip = label;
    return node;
  }

  function emptyBox(host, message) {
    host.innerHTML = "";
    var box = document.createElement("p");
    box.className = "chart-empty";
    box.textContent = message;
    host.appendChild(box);
  }

  /* --- 1. stacked columns (run history: ok / failed / skipped) ------------ */
  /*
   * These three are STATUS, not identity, so they use the status palette and
   * every one of them is named in the legend with an icon — colour never
   * carries the meaning alone.
   */

  function stackedRuns(host, runs, options) {
    var opts = options || {};
    if (!host) return;
    if (!runs || !runs.length) {
      emptyBox(host, opts.empty || "Henüz çalıştırma geçmişi yok.");
      return;
    }

    var W = 720;
    var H = 200;
    var padL = 34;
    var padR = 8;
    var padT = 10;
    var padB = 26; // the x-axis band lives INSIDE the box, never cropped
    var plotW = W - padL - padR;
    var plotH = H - padT - padB;

    var max = niceMax(
      runs.reduce(function (acc, r) {
        return Math.max(acc, (r.ok || 0) + (r.failed || 0) + (r.skipped || 0));
      }, 0)
    );

    var svg = svgRoot(W, H);

    // Gridlines: solid hairlines, recessive, with clean tick values.
    var ticks = 4;
    for (var t = 0; t <= ticks; t += 1) {
      var value = (max / ticks) * t;
      var y = padT + plotH - (value / max) * plotH;
      svg.appendChild(
        el("line", {
          class: "chart__grid",
          x1: padL,
          x2: W - padR,
          y1: y,
          y2: y
        })
      );
      var tick = el("text", { class: "chart__tick", x: padL - 6, y: y + 3, "text-anchor": "end" });
      tick.textContent = String(Math.round(value));
      svg.appendChild(tick);
    }

    var band = plotW / runs.length;
    var width = Math.min(24, Math.max(4, band - 6));
    var GAP = 2; // the surface gap between stacked segments

    runs.forEach(function (run, index) {
      var x = padL + band * index + (band - width) / 2;
      var segments = [
        ["ok", run.ok || 0, "var(--good)"],
        ["failed", run.failed || 0, "var(--critical)"],
        ["skipped", run.skipped || 0, "var(--neutral)"]
      ].filter(function (pair) {
        return pair[1] > 0;
      });

      var cursor = padT + plotH;
      segments.forEach(function (pair, order) {
        var h = (pair[1] / max) * plotH;
        var top = cursor - h;
        // Only the topmost segment gets the rounded data-end.
        var isTop = order === segments.length - 1;
        var path = el("path", {
          d: isTop
            ? columnPath(x, top, width, h, 4)
            : "M" + x + " " + top + "h" + width + "v" + h + "h" + -width + "Z",
          fill: pair[2]
        });
        svg.appendChild(path);
        cursor = top - GAP;
      });

      if (!segments.length) {
        svg.appendChild(
          el("rect", { x: x, y: padT + plotH - 2, width: width, height: 2, fill: "var(--neutral)" })
        );
      }

      var label =
        (run.at_istanbul || run.at || "—") +
        "\n✅ " + (run.ok || 0) + " çalıştı · ⚠️ " + (run.failed || 0) +
        " hata · ⏭️ " + (run.skipped || 0) + " atlandı" +
        (run.duration_seconds != null ? "\n⏱️ " + Math.round(run.duration_seconds) + " sn" : "");

      // The hit target spans the whole band, so a 4px bar is still easy to hit.
      svg.appendChild(
        hoverable(
          el("rect", {
            class: "chart__hit",
            x: padL + band * index,
            y: padT,
            width: band,
            height: plotH
          }),
          label
        )
      );
    });

    // Baseline.
    svg.appendChild(
      el("line", { class: "chart__axis", x1: padL, x2: W - padR, y1: padT + plotH, y2: padT + plotH })
    );

    // Label only the first and last column: a label on every one is chaos.
    [0, runs.length - 1].forEach(function (index, order) {
      if (runs.length < 2 && order === 1) return;
      var run = runs[index];
      var text = el("text", {
        class: "chart__tick",
        x: padL + band * index + band / 2,
        y: H - 8,
        "text-anchor": order === 0 ? "start" : "end"
      });
      text.textContent = (run.at_istanbul || "").slice(0, 10) || "—";
      svg.appendChild(text);
    });

    host.innerHTML = "";
    host.appendChild(svg);
  }

  /* --- 2. line / area trend (one series: tokens, latency) ----------------- */
  /*
   * ONE series, so no legend box: the card title already says what is plotted.
   * The endpoint is the only labelled point — the axis and the tooltip carry
   * the rest.
   */

  function trend(host, points, options) {
    var opts = options || {};
    if (!host) return;
    var data = (points || []).filter(function (p) {
      return p && isFinite(p.value);
    });
    if (data.length < 2) {
      emptyBox(host, opts.empty || "Grafik için en az iki çalıştırma gerekiyor.");
      return;
    }

    var W = 720;
    var H = 190;
    var padL = 40;
    var padR = 46; // room for the end label
    var padT = 14;
    var padB = 24;
    var plotW = W - padL - padR;
    var plotH = H - padT - padB;
    var color = opts.color || "var(--series-1)";

    var max = niceMax(
      data.reduce(function (acc, p) {
        return Math.max(acc, p.value);
      }, 0)
    );

    var svg = svgRoot(W, H);

    for (var t = 0; t <= 3; t += 1) {
      var value = (max / 3) * t;
      var y = padT + plotH - (value / max) * plotH;
      svg.appendChild(el("line", { class: "chart__grid", x1: padL, x2: W - padR, y1: y, y2: y }));
      var tick = el("text", { class: "chart__tick", x: padL - 6, y: y + 3, "text-anchor": "end" });
      tick.textContent = compact(value);
      svg.appendChild(tick);
    }

    var step = data.length > 1 ? plotW / (data.length - 1) : 0;
    function px(index) {
      return padL + step * index;
    }
    function py(value) {
      return padT + plotH - (value / max) * plotH;
    }

    var line = data
      .map(function (p, i) {
        return (i ? "L" : "M") + px(i).toFixed(1) + " " + py(p.value).toFixed(1);
      })
      .join(" ");

    // Area wash at ~10% opacity — never a saturated block.
    svg.appendChild(
      el("path", {
        class: "chart__area",
        fill: color,
        d: line + " L" + px(data.length - 1) + " " + (padT + plotH) + " L" + padL + " " + (padT + plotH) + " Z"
      })
    );
    svg.appendChild(el("path", { class: "chart__line", stroke: color, d: line }));

    // A marker on the last point only, with the 2px surface ring.
    var last = data[data.length - 1];
    svg.appendChild(
      el("circle", { class: "chart__dot", cx: px(data.length - 1), cy: py(last.value), r: 4, fill: color })
    );
    var endLabel = el("text", {
      class: "chart__value",
      x: Math.min(W - 4, px(data.length - 1) + 8),
      y: py(last.value) + 4
    });
    endLabel.textContent = compact(last.value) + (opts.unit ? " " + opts.unit : "");
    svg.appendChild(endLabel);

    // One hit column per point, wider than the 8px marker.
    data.forEach(function (point, index) {
      svg.appendChild(
        hoverable(
          el("rect", {
            class: "chart__hit",
            x: px(index) - step / 2,
            y: padT,
            width: Math.max(step, 12),
            height: plotH
          }),
          (point.label || "") + "\n" + (opts.name || "") + ": " +
            (opts.format ? opts.format(point.value) : compact(point.value) + (opts.unit ? " " + opts.unit : ""))
        )
      );
    });

    svg.appendChild(
      el("line", { class: "chart__axis", x1: padL, x2: W - padR, y1: padT + plotH, y2: padT + plotH })
    );

    [0, data.length - 1].forEach(function (index, order) {
      var text = el("text", {
        class: "chart__tick",
        x: px(index),
        y: H - 6,
        "text-anchor": order === 0 ? "start" : "middle"
      });
      text.textContent = data[index].short || "";
      svg.appendChild(text);
    });

    host.innerHTML = "";
    host.appendChild(svg);
  }

  /* --- 3. one horizontal stacked bar (part-to-whole token split) ---------- */

  function splitBar(host, parts, options) {
    var opts = options || {};
    if (!host) return;
    var data = (parts || []).filter(function (p) {
      return p && p.value > 0;
    });
    var total = data.reduce(function (acc, p) {
      return acc + p.value;
    }, 0);
    if (!total) {
      emptyBox(host, opts.empty || "Henüz token verisi yok.");
      return;
    }

    var W = 720;
    var H = 58;
    var GAP = 2;
    var barH = 26;
    var y = 6;

    var svg = svgRoot(W, H);
    var usable = W - GAP * (data.length - 1);
    var cursor = 0;

    data.forEach(function (part, index) {
      var w = (part.value / total) * usable;
      var isFirst = index === 0;
      var isLast = index === data.length - 1;
      var d;
      if (isFirst && isLast) {
        d = barPath(cursor, y, w, barH, 4);
      } else if (isLast) {
        d = barPath(cursor, y, w, barH, 4);
      } else if (isFirst) {
        // Rounded left end, square right (the stack continues).
        d =
          "M" + (cursor + 4) + " " + y + "h" + (w - 4) + "v" + barH + "h" + -(w - 4) +
          "a4 4 0 0 1 -4 -4v" + -(barH - 8) + "a4 4 0 0 1 4 -4Z";
      } else {
        d = "M" + cursor + " " + y + "h" + w + "v" + barH + "h" + -w + "Z";
      }
      svg.appendChild(el("path", { d: d, fill: part.color }));

      var share = (part.value / total) * 100;
      var text = compact(part.value);
      // Only label INSIDE the segment when the text comfortably fits.
      if (w > text.length * 7 + 16) {
        var inside = el("text", {
          x: cursor + w / 2,
          y: y + barH / 2 + 4,
          "text-anchor": "middle",
          class: "chart__value",
          fill: "#ffffff"
        });
        inside.textContent = text;
        svg.appendChild(inside);
      }

      svg.appendChild(
        hoverable(
          el("rect", { class: "chart__hit", x: cursor, y: 0, width: w, height: H }),
          part.name + ": " + part.value.toLocaleString("tr-TR") + " token (%" +
            share.toFixed(1).replace(".", ",") + ")"
        )
      );

      cursor += w + GAP;
    });

    var caption = el("text", { class: "chart__tick", x: 0, y: H - 4 });
    caption.textContent = "Toplam " + total.toLocaleString("tr-TR") + " token";
    svg.appendChild(caption);

    host.innerHTML = "";
    host.appendChild(svg);
  }

  /* --- 4. grouped horizontal bars (per-agent token vs output share) ------- */
  /*
   * TWO series across the same categories, so a legend is mandatory and both
   * are direct-labelled at the bar tip. One shared x-axis (percent) — never a
   * second scale.
   */

  function groupedShares(host, rows, options) {
    var opts = options || {};
    if (!host) return;
    var data = (rows || []).slice(0, opts.limit || 10);
    if (!data.length) {
      emptyBox(host, opts.empty || "Ajan bazlı token dağılımı henüz yok.");
      return;
    }

    var W = 720;
    var rowH = 44;
    var padT = 6;
    var padB = 22;
    var labelW = 190;
    var padR = 52; // room for the tip labels
    var H = padT + data.length * rowH + padB;
    var plotW = W - labelW - padR;

    var max = niceMax(
      data.reduce(function (acc, row) {
        return Math.max(acc, row.token_share || 0, row.output_share || 0);
      }, 0)
    );

    var svg = svgRoot(W, H);

    for (var t = 0; t <= 4; t += 1) {
      var value = (max / 4) * t;
      var x = labelW + (value / max) * plotW;
      svg.appendChild(
        el("line", { class: "chart__grid", x1: x, x2: x, y1: padT, y2: padT + data.length * rowH })
      );
      var tick = el("text", {
        class: "chart__tick",
        x: x,
        y: H - 6,
        "text-anchor": t === 0 ? "start" : "middle"
      });
      tick.textContent = "%" + Math.round(value);
      svg.appendChild(tick);
    }

    var barH = 11;
    var GAP = 2;

    data.forEach(function (row, index) {
      var top = padT + index * rowH;

      var name = el("text", { class: "chart__label", x: 0, y: top + rowH / 2 + 4 });
      var full = row.name || row.id;
      name.textContent = full.length > 26 ? full.slice(0, 25) + "…" : full;
      svg.appendChild(name);

      [
        ["token_share", "var(--series-1)", "token payı"],
        ["output_share", "var(--series-2)", "çıktı payı"]
      ].forEach(function (pair, order) {
        var value = row[pair[0]] || 0;
        var w = (value / max) * plotW;
        var y = top + rowH / 2 - barH - GAP / 2 + order * (barH + GAP);
        svg.appendChild(el("path", { d: barPath(labelW, y, Math.max(w, 1), barH, 4), fill: pair[1] }));

        var label = el("text", { class: "chart__tick", x: labelW + w + 6, y: y + barH - 1 });
        label.textContent = "%" + String(value).replace(".", ",");
        svg.appendChild(label);
      });

      svg.appendChild(
        hoverable(
          el("rect", { class: "chart__hit", x: 0, y: top, width: W, height: rowH }),
          (row.name || row.id) +
            "\nTahmini token payı: %" + String(row.token_share || 0).replace(".", ",") +
            "\nÜretilen metin payı: %" + String(row.output_share || 0).replace(".", ",") +
            "\n≈ " + (row.tokens || 0).toLocaleString("tr-TR") + " token"
        )
      );
    });

    svg.appendChild(
      el("line", {
        class: "chart__axis",
        x1: labelW,
        x2: labelW,
        y1: padT,
        y2: padT + data.length * rowH
      })
    );

    host.innerHTML = "";
    host.appendChild(svg);
  }

  /* --- 5. the table view every chart ships with -------------------------- */

  function table(host, columns, rows, caption) {
    if (!host) return;
    host.innerHTML = "";
    var wrap = document.createElement("div");
    wrap.className = "table-wrap";
    var tableEl = document.createElement("table");
    tableEl.className = "table";

    if (caption) {
      var cap = document.createElement("caption");
      cap.className = "visually-hidden";
      cap.textContent = caption;
      tableEl.appendChild(cap);
    }

    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    columns.forEach(function (column) {
      var th = document.createElement("th");
      th.scope = "col";
      th.textContent = column.label;
      if (column.num) th.className = "num";
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    tableEl.appendChild(thead);

    var tbody = document.createElement("tbody");
    rows.forEach(function (row) {
      var tr = document.createElement("tr");
      columns.forEach(function (column, index) {
        var td = document.createElement("td");
        var value = row[index];
        if (value && value.nodeType) {
          td.appendChild(value);
        } else {
          td.textContent = value == null ? "—" : String(value);
        }
        if (column.num) td.className = "num";
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    tableEl.appendChild(tbody);

    wrap.appendChild(tableEl);
    host.appendChild(wrap);
  }

  global.AIACharts = {
    stackedRuns: stackedRuns,
    trend: trend,
    splitBar: splitBar,
    groupedShares: groupedShares,
    table: table,
    compact: compact
  };
})(typeof window !== "undefined" ? window : this);
