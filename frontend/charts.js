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
    // Drop any repaint callback a previous (non-empty) render left behind, so a
    // resize cannot bring stale marks back on top of the empty state.
    host.__aiaDraw = null;
    var box = document.createElement("p");
    box.className = "chart-empty";
    box.textContent = message || "Veri yok.";
    host.appendChild(box);
  }

  /* --- shared plumbing for the v2 builders -------------------------------- */
  /*
   * Two things every v2 chart gets for free:
   *
   *   1. TRUE-SIZE GEOMETRY. The viewBox is built at the host's measured pixel
   *      width, so one user unit is one CSS pixel and an 11px axis label is
   *      actually 11px — on a 375px phone as much as on a 1200px desktop. A
   *      fixed 720-wide viewBox squeezed into 343px would render that label at
   *      5px. A ResizeObserver repaints when the column genuinely changes width
   *      (and only then), so the chart stays responsive without a resize storm.
   *   2. FIRST-PAINT-ONLY ANIMATION. The dashboard repaints every 60 seconds
   *      and on every theme flip; replaying an entrance animation each time is
   *      noise. The host remembers that it has been painted, so the animation
   *      class is added exactly once.
   */

  var HasRO = typeof ResizeObserver !== "undefined";

  function measure(host) {
    var w = host.clientWidth || 0;
    if (!w) w = 640; // hidden tab: draw something sane, repaint when shown
    return Math.max(260, Math.min(920, Math.round(w)));
  }

  function mount(host, draw) {
    host.__aiaDraw = draw;
    if (HasRO && !host.__aiaRO) {
      var lastW = host.clientWidth;
      host.__aiaRO = new ResizeObserver(function () {
        var w = host.clientWidth;
        // Height changes are OUR OWN repaint echoing back — ignore them.
        if (Math.abs(w - lastW) < 24) return;
        lastW = w;
        if (host.__aiaDraw) host.__aiaDraw(measure(host));
      });
      host.__aiaRO.observe(host);
    }
    draw(measure(host));
  }

  /** True once per host: the entrance animation is not replayed on refresh. */
  function firstPaint(host) {
    if (host.dataset.painted === "1") return false;
    // A chart drawn while its tab is hidden has no real width yet; let the
    // first VISIBLE paint be the animated one.
    if (!host.clientWidth) return false;
    host.dataset.painted = "1";
    return true;
  }

  function figure(width, height, label, animate) {
    var svg = el("svg", {
      viewBox: "0 0 " + width + " " + height,
      width: width,
      height: height,
      preserveAspectRatio: "xMidYMid meet",
      role: "img",
      "aria-label": label || ""
    });
    if (animate) svg.setAttribute("class", "chart--anim");
    var title = el("title");
    title.textContent = label || "";
    svg.appendChild(title);
    return svg;
  }

  function titled(node, label) {
    var t = el("title");
    t.textContent = label;
    node.appendChild(t);
    return node;
  }

  function group(className) {
    return el("g", className ? { class: className } : {});
  }

  function tr(value, digits) {
    var n = Number(value);
    if (!isFinite(n)) n = 0;
    return n.toLocaleString("tr-TR", {
      minimumFractionDigits: digits || 0,
      maximumFractionDigits: digits == null ? 0 : digits
    });
  }

  /** Rough px width of a label at a given font size — enough to size a gutter. */
  function textWidth(str, size) {
    return String(str == null ? "" : str).length * size * 0.58;
  }

  function clip(str, chars) {
    var s = String(str == null ? "" : str);
    return s.length > chars ? s.slice(0, chars - 1) + "…" : s;
  }

  /** Legend as real HTML above the plot — the dependable identity channel. */
  function legendList(items, label) {
    var ul = document.createElement("ul");
    ul.className = "legend";
    ul.setAttribute("aria-label", label || "Grafik göstergesi");
    items.forEach(function (item) {
      var li = document.createElement("li");
      var dot = document.createElement("span");
      dot.className = "swatch";
      dot.setAttribute("aria-hidden", "true");
      dot.style.background = item.color;
      li.appendChild(dot);
      li.appendChild(document.createTextNode(" " + item.name));
      if (item.value != null) {
        var v = document.createElement("span");
        v.className = "legend__value";
        v.textContent = item.value;
        li.appendChild(v);
      }
      ul.appendChild(li);
    });
    return ul;
  }

  var SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)",
    "var(--series-5)", "var(--series-6)", "var(--series-7)", "var(--series-8)"];

  /* ======================================================================== */
  /* lineChart — multi-series trend, area fill, crosshair tooltip             */
  /* ======================================================================== */
  /*
   * `series` is either a flat list of points (one series) or a list of
   * { name, color, points } objects. A point is { value, label, short }:
   * `label` is what the tooltip says (the full date), `short` is the axis tick.
   */

  function normalizeSeries(input) {
    if (!input || !input.length) return [];
    if (input[0] && Object.prototype.hasOwnProperty.call(input[0], "points")) {
      return input
        .map(function (s, i) {
          return {
            name: s.name || "Seri " + (i + 1),
            color: s.color || SERIES[i % SERIES.length],
            points: (s.points || []).filter(function (p) {
              return p && isFinite(p.value);
            })
          };
        })
        .filter(function (s) {
          return s.points.length;
        });
    }
    var points = input.filter(function (p) {
      return p && isFinite(p.value);
    });
    return points.length ? [{ name: "", color: SERIES[0], points: points }] : [];
  }

  function lineChart(host, series, options) {
    var opts = options || {};
    if (!host) return;
    var list = normalizeSeries(series);
    var longest = list.reduce(function (acc, s) {
      return Math.max(acc, s.points.length);
    }, 0);

    // Nothing at all and "only one reading" are different problems, and the
    // empty state says which: a missing file is not a young history.
    if (!list.length) {
      emptyBox(host, opts.empty || "Veri yok.");
      return;
    }
    if (longest < 2) {
      emptyBox(host, opts.single || "Eğilim için en az iki ölçüm gerekiyor.");
      return;
    }

    var fmt = opts.format || function (v) {
      return compact(v) + (opts.unit ? " " + opts.unit : "");
    };

    mount(host, function (W) {
      var animate = firstPaint(host);
      var H = opts.height || (W < 420 ? 190 : 230);

      var max = niceMax(
        list.reduce(function (acc, s) {
          return s.points.reduce(function (m, p) {
            return Math.max(m, p.value);
          }, acc);
        }, 0)
      );

      var tickCount = H < 200 ? 3 : 4;
      var widestTick = 0;
      for (var i = 0; i <= tickCount; i += 1) {
        widestTick = Math.max(widestTick, textWidth(compact((max / tickCount) * i), 11));
      }

      var padL = Math.ceil(widestTick) + 10;
      var padR = 12;
      var padT = 12;
      var padB = 26;
      var plotW = W - padL - padR;
      var plotH = H - padT - padB;

      var svg = figure(W, H, opts.aria || opts.name || "Eğilim grafiği", animate);

      var grid = group("chart__grid-g");
      for (var t = 0; t <= tickCount; t += 1) {
        var value = (max / tickCount) * t;
        var gy = padT + plotH - (value / max) * plotH;
        grid.appendChild(el("line", { class: "chart__grid", x1: padL, x2: W - padR, y1: gy, y2: gy }));
        var tick = el("text", { class: "chart__tick", x: padL - 6, y: gy + 3.5, "text-anchor": "end" });
        tick.textContent = compact(value);
        grid.appendChild(tick);
      }
      svg.appendChild(grid);

      var step = longest > 1 ? plotW / (longest - 1) : 0;
      function px(index) {
        return padL + step * index;
      }
      function py(value) {
        return padT + plotH - (value / max) * plotH;
      }

      // Area is a wash under a SINGLE series; with more than two lines stacked
      // washes turn into mud, so they are dropped and the lines carry it.
      var wantArea = opts.area != null ? opts.area : list.length <= 2;

      var marks = group("chart__marks");
      list.forEach(function (s) {
        var d = s.points
          .map(function (p, i) {
            return (i ? "L" : "M") + px(i).toFixed(1) + " " + py(p.value).toFixed(1);
          })
          .join(" ");

        if (wantArea) {
          marks.appendChild(
            el("path", {
              class: "chart__area",
              fill: s.color,
              d: d + " L" + px(s.points.length - 1).toFixed(1) + " " + (padT + plotH) +
                " L" + padL + " " + (padT + plotH) + " Z"
            })
          );
        }
        marks.appendChild(el("path", { class: "chart__line", stroke: s.color, d: d }));

        // Endpoint marker only — a dot on every point is noise.
        var last = s.points[s.points.length - 1];
        marks.appendChild(
          el("circle", {
            class: "chart__dot",
            cx: px(s.points.length - 1),
            cy: py(last.value),
            r: 4,
            fill: s.color
          })
        );
      });
      svg.appendChild(marks);

      svg.appendChild(
        el("line", { class: "chart__axis", x1: padL, x2: W - padR, y1: padT + plotH, y2: padT + plotH })
      );

      // X ticks: as many as comfortably fit, never more than five.
      var base = list[0].points;
      var slots = Math.max(2, Math.min(5, Math.floor(plotW / 74)));
      var seen = {};
      for (var k = 0; k < slots; k += 1) {
        var idx = Math.round((longest - 1) * (k / (slots - 1)));
        if (seen[idx]) continue;
        seen[idx] = true;
        var point = base[Math.min(idx, base.length - 1)];
        if (!point || !point.short) continue;
        var anchor = idx === 0 ? "start" : idx === longest - 1 ? "end" : "middle";
        var xt = el("text", { class: "chart__tick", x: px(idx), y: H - 8, "text-anchor": anchor });
        xt.textContent = point.short;
        svg.appendChild(xt);
      }

      /* --- crosshair + tooltip --------------------------------------------- */
      var cross = el("line", {
        class: "chart__cross",
        x1: 0, x2: 0, y1: padT, y2: padT + plotH,
        opacity: 0
      });
      svg.appendChild(cross);
      var focus = group("chart__focus");
      focus.setAttribute("opacity", "0");
      list.forEach(function (s) {
        focus.appendChild(el("circle", { class: "chart__dot", r: 4, fill: s.color, cx: -20, cy: -20 }));
      });
      svg.appendChild(focus);

      var hits = group();
      for (var h = 0; h < longest; h += 1) {
        (function (index) {
          var lines = [];
          var stamp = "";
          list.forEach(function (s) {
            var p = s.points[index];
            if (!p) return;
            if (!stamp) stamp = p.label || p.short || "";
            lines.push((s.name ? s.name + ": " : "") + fmt(p.value));
          });
          if (!lines.length) return;

          var rect = hoverable(
            el("rect", {
              class: "chart__hit",
              x: Math.max(0, px(index) - step / 2),
              y: padT,
              width: Math.max(step, 16),
              height: plotH
            }),
            (stamp ? stamp + "\n" : "") + lines.join("\n")
          );
          function on() {
            cross.setAttribute("x1", px(index));
            cross.setAttribute("x2", px(index));
            cross.setAttribute("opacity", "1");
            focus.setAttribute("opacity", "1");
            var dots = focus.childNodes;
            list.forEach(function (s, si) {
              var p = s.points[index];
              var dot = dots[si];
              if (!dot) return;
              if (!p) {
                dot.setAttribute("cx", -20);
                return;
              }
              dot.setAttribute("cx", px(index));
              dot.setAttribute("cy", py(p.value));
            });
          }
          function off() {
            cross.setAttribute("opacity", "0");
            focus.setAttribute("opacity", "0");
          }
          rect.addEventListener("mouseenter", on);
          rect.addEventListener("focus", on);
          rect.addEventListener("mouseleave", off);
          rect.addEventListener("blur", off);
          hits.appendChild(rect);
        })(h);
      }
      svg.appendChild(hits);

      host.innerHTML = "";
      if (list.length > 1 && opts.legend !== false) {
        host.appendChild(
          legendList(
            list.map(function (s) {
              return { name: s.name, color: s.color };
            }),
            opts.legendLabel || "Seri göstergesi"
          )
        );
      }
      host.appendChild(svg);
    });
  }

  /* ======================================================================== */
  /* barChart — horizontal (default) and vertical variants                    */
  /* ======================================================================== */
  /*
   * `data` is [{ label, value, color?, note? }]. Horizontal is the default
   * because category names are words, and words want a horizontal baseline;
   * `orientation: "vertical"` is for a time-ordered measure per run.
   */

  function barChart(host, data, options) {
    var opts = options || {};
    if (!host) return;
    var rows = (data || []).filter(function (row) {
      return row && isFinite(row.value);
    });
    if (opts.limit) rows = rows.slice(0, opts.limit);
    if (!rows.length) {
      emptyBox(host, opts.empty || "Veri yok.");
      return;
    }

    var fmt = opts.format || function (v) {
      return compact(v) + (opts.unit ? " " + opts.unit : "");
    };
    var vertical = opts.orientation === "vertical";

    mount(host, function (W) {
      var animate = firstPaint(host);
      var max = niceMax(
        rows.reduce(function (acc, row) {
          return Math.max(acc, row.value);
        }, 0)
      );
      var svg;

      if (!vertical) {
        var narrow = W < 460;
        var rowH = narrow ? 40 : 34;
        var padT = 4;
        var padB = 22;
        // On a phone the name sits ABOVE its bar instead of eating half the width.
        var labelW = narrow ? 0 : Math.min(200, Math.max(90, Math.round(W * 0.3)));
        var valueW = Math.ceil(textWidth(fmt(max), 11)) + 10;
        var plotW = W - labelW - valueW - 4;
        var H = padT + rows.length * rowH + padB;

        svg = figure(W, H, opts.aria || "Yatay çubuk grafik", animate);

        for (var t = 0; t <= 4; t += 1) {
          var gv = (max / 4) * t;
          var gx = labelW + (gv / max) * plotW;
          svg.appendChild(
            el("line", { class: "chart__grid", x1: gx, x2: gx, y1: padT, y2: padT + rows.length * rowH })
          );
          var gt = el("text", {
            class: "chart__tick",
            x: gx,
            y: H - 7,
            "text-anchor": t === 0 ? "start" : t === 4 ? "end" : "middle"
          });
          gt.textContent = compact(gv);
          svg.appendChild(gt);
        }

        var barH = narrow ? 12 : Math.min(16, rowH - 16);
        var marks = group("chart__marks chart__marks--h");
        // Hit targets go in their OWN group appended last: painted under the
        // bars they would never receive the pointer, and the tooltip (which is
        // delegated off `[data-tip]`) would silently never fire.
        var hits = group("chart__hits");
        rows.forEach(function (row, index) {
          var top = padT + index * rowH;
          var color = row.color || opts.color || SERIES[0];
          var w = Math.max(2, (row.value / max) * plotW);
          var by = narrow ? top + rowH - barH - 8 : top + (rowH - barH) / 2;

          var name = el("text", {
            class: "chart__label",
            x: narrow ? 0 : 0,
            y: narrow ? top + 12 : by + barH - 3
          });
          name.textContent = clip(row.label, narrow ? Math.floor(W / 7) : 24);
          svg.appendChild(name);

          marks.appendChild(
            el("path", { d: barPath(labelW, by, w, barH, 4), fill: color, class: "chart__bar" })
          );

          var value = el("text", {
            class: "chart__value",
            x: labelW + w + 6,
            y: by + barH - 2
          });
          value.textContent = fmt(row.value);
          marks.appendChild(value);

          hits.appendChild(
            hoverable(
              el("rect", { class: "chart__hit", x: 0, y: top, width: W, height: rowH }),
              row.label + "\n" + fmt(row.value) + (row.note ? "\n" + row.note : "")
            )
          );
        });
        svg.appendChild(marks);
        svg.appendChild(
          el("line", {
            class: "chart__axis",
            x1: labelW, x2: labelW, y1: padT, y2: padT + rows.length * rowH
          })
        );
        svg.appendChild(hits);
      } else {
        var H2 = opts.height || (W < 420 ? 180 : 210);
        var padT2 = 14;
        var padB2 = 26;
        var widest = 0;
        for (var q = 0; q <= 4; q += 1) widest = Math.max(widest, textWidth(compact((max / 4) * q), 11));
        var padL2 = Math.ceil(widest) + 10;
        var padR2 = 8;
        var plotW2 = W - padL2 - padR2;
        var plotH2 = H2 - padT2 - padB2;

        svg = figure(W, H2, opts.aria || "Dikey çubuk grafik", animate);

        for (var g = 0; g <= 4; g += 1) {
          var v2 = (max / 4) * g;
          var y2 = padT2 + plotH2 - (v2 / max) * plotH2;
          svg.appendChild(el("line", { class: "chart__grid", x1: padL2, x2: W - padR2, y1: y2, y2: y2 }));
          var yt = el("text", { class: "chart__tick", x: padL2 - 6, y: y2 + 3.5, "text-anchor": "end" });
          yt.textContent = compact(v2);
          svg.appendChild(yt);
        }

        var band = plotW2 / rows.length;
        var colW = Math.min(24, Math.max(4, band - 6));
        var vmarks = group("chart__marks chart__marks--v");
        var vhits = group("chart__hits");
        rows.forEach(function (row, index) {
          var x = padL2 + band * index + (band - colW) / 2;
          var h = (row.value / max) * plotH2;
          vmarks.appendChild(
            el("path", {
              d: columnPath(x, padT2 + plotH2 - h, colW, h, 4),
              fill: row.color || opts.color || SERIES[0],
              class: "chart__bar"
            })
          );
          vhits.appendChild(
            hoverable(
              el("rect", {
                class: "chart__hit",
                x: padL2 + band * index,
                y: padT2,
                width: band,
                height: plotH2
              }),
              row.label + "\n" + fmt(row.value) + (row.note ? "\n" + row.note : "")
            )
          );
        });
        svg.appendChild(vmarks);
        svg.appendChild(
          el("line", {
            class: "chart__axis",
            x1: padL2, x2: W - padR2, y1: padT2 + plotH2, y2: padT2 + plotH2
          })
        );
        svg.appendChild(vhits);

        var every = Math.max(1, Math.ceil(rows.length / Math.max(2, Math.floor(plotW2 / 60))));
        rows.forEach(function (row, index) {
          if (index % every !== 0 && index !== rows.length - 1) return;
          var xt2 = el("text", {
            class: "chart__tick",
            x: padL2 + band * index + band / 2,
            y: H2 - 8,
            "text-anchor": "middle"
          });
          xt2.textContent = clip(row.short || row.label, 8);
          svg.appendChild(xt2);
        });
      }

      host.innerHTML = "";
      host.appendChild(svg);
    });
  }

  /* ======================================================================== */
  /* donutChart — part-to-whole with the total in the middle                  */
  /* ======================================================================== */

  function polar(cx, cy, r, angle) {
    return [cx + r * Math.cos(angle), cy + r * Math.sin(angle)];
  }

  function ringPath(cx, cy, rOut, rIn, a0, a1) {
    var large = a1 - a0 > Math.PI ? 1 : 0;
    var p0 = polar(cx, cy, rOut, a0);
    var p1 = polar(cx, cy, rOut, a1);
    var p2 = polar(cx, cy, rIn, a1);
    var p3 = polar(cx, cy, rIn, a0);
    return (
      "M" + p0[0].toFixed(2) + " " + p0[1].toFixed(2) +
      "A" + rOut + " " + rOut + " 0 " + large + " 1 " + p1[0].toFixed(2) + " " + p1[1].toFixed(2) +
      "L" + p2[0].toFixed(2) + " " + p2[1].toFixed(2) +
      "A" + rIn + " " + rIn + " 0 " + large + " 0 " + p3[0].toFixed(2) + " " + p3[1].toFixed(2) +
      "Z"
    );
  }

  function donutChart(host, segments, options) {
    var opts = options || {};
    if (!host) return;
    var parts = (segments || []).filter(function (p) {
      return p && Number(p.value) > 0;
    });
    if (!parts.length) {
      emptyBox(host, opts.empty || "Veri yok.");
      return;
    }

    parts = parts.slice().sort(function (a, b) {
      return b.value - a.value;
    });

    // Past six slices the ring stops being readable and the hues stop being
    // reliably distinguishable — the tail folds into one honest "Diğer".
    var cap = opts.maxSegments || 6;
    if (parts.length > cap) {
      var rest = parts.slice(cap - 1);
      parts = parts.slice(0, cap - 1);
      parts.push({
        name: "Diğer (" + rest.length + " ajan)",
        value: rest.reduce(function (acc, p) {
          return acc + Number(p.value);
        }, 0),
        color: "var(--neutral)"
      });
    }
    parts.forEach(function (p, i) {
      if (!p.color) p.color = SERIES[i % SERIES.length];
    });

    var total = parts.reduce(function (acc, p) {
      return acc + Number(p.value);
    }, 0);
    var fmt = opts.format || function (v) {
      return compact(v) + (opts.unit ? " " + opts.unit : "");
    };

    mount(host, function (W) {
      var animate = firstPaint(host);
      var size = Math.min(W, opts.size || 260);
      var cx = W / 2;
      var cy = size / 2;
      var rOut = size / 2 - 6;
      var rIn = rOut - Math.max(20, Math.round(size * 0.13));

      var svg = figure(W, size, opts.aria || "Halka grafik — " + fmt(total), animate);
      var marks = group("chart__marks chart__marks--ring");

      if (parts.length === 1) {
        var ring = el("circle", {
          cx: cx, cy: cy, r: (rOut + rIn) / 2,
          fill: "none",
          stroke: parts[0].color,
          "stroke-width": rOut - rIn,
          class: "chart__arc"
        });
        titled(ring, parts[0].name + ": " + fmt(parts[0].value) + " (%100)");
        marks.appendChild(ring);
        hoverable(ring, parts[0].name + "\n" + fmt(parts[0].value) + " · %100");
      } else {
        var gap = 2 / rOut; // the 2px surface gap, expressed as an angle
        var cursor = -Math.PI / 2;
        parts.forEach(function (part, index) {
          var sweep = (Number(part.value) / total) * Math.PI * 2;
          var a0 = cursor + gap / 2;
          var a1 = cursor + sweep - gap / 2;
          cursor += sweep;
          if (a1 <= a0) return;
          var share = (Number(part.value) / total) * 100;
          var tip = part.name + "\n" + fmt(part.value) + " · %" + tr(share, 1);
          var arc = el("path", {
            d: ringPath(cx, cy, rOut, rIn, a0, a1),
            fill: part.color,
            class: "chart__arc"
          });
          titled(arc, tip.replace("\n", " — "));
          hoverable(arc, tip);
          marks.appendChild(arc);
          part.__share = share;
        });
      }
      svg.appendChild(marks);

      var centerValue = el("text", {
        class: "chart__center-value",
        x: cx, y: cy + 2, "text-anchor": "middle"
      });
      centerValue.textContent = opts.centerValue || compact(total);
      svg.appendChild(centerValue);

      var centerLabel = el("text", {
        class: "chart__center-label",
        x: cx, y: cy + 20, "text-anchor": "middle"
      });
      centerLabel.textContent = opts.centerLabel || "toplam";
      svg.appendChild(centerLabel);

      host.innerHTML = "";
      host.appendChild(svg);
      if (opts.legend !== false) {
        host.appendChild(
          legendList(
            parts.map(function (p) {
              return {
                name: clip(p.name, 30),
                color: p.color,
                value: "%" + tr((Number(p.value) / total) * 100, 1)
              };
            }),
            opts.legendLabel || "Dağılım göstergesi"
          )
        );
      }
    });
  }

  /* ======================================================================== */
  /* sparkline — the inline mini-trend that rides a metric card               */
  /* ======================================================================== */

  function sparkline(host, values, options) {
    var opts = options || {};
    if (!host) return;
    var data = (values || [])
      .map(function (v) {
        return typeof v === "object" && v ? Number(v.value) : Number(v);
      })
      .filter(function (v) {
        return isFinite(v);
      });
    if (data.length < 2) {
      host.innerHTML = "";
      host.__aiaDraw = null;
      var none = document.createElement("span");
      none.className = "spark-empty";
      // Inline inside a metric card, so this is a span and not the boxed
      // `.chart-empty` — same words, a size that fits where it lives.
      none.textContent = opts.empty || "Veri yok.";
      host.appendChild(none);
      return;
    }

    mount(host, function (W) {
      var animate = firstPaint(host);
      var H = opts.height || 40;
      var color = opts.color || SERIES[0];
      var pad = 5;
      var min = Math.min.apply(null, data);
      var max = Math.max.apply(null, data);
      // A flat series must read as flat, not as a random walk through noise.
      var span = max - min || Math.abs(max) || 1;
      var lo = max === min ? min - span / 2 : min;
      var range = max === min ? span : max - min;

      var step = (W - pad * 2) / (data.length - 1);
      function px(i) {
        return pad + step * i;
      }
      function py(v) {
        return H - pad - ((v - lo) / range) * (H - pad * 2);
      }

      var label =
        (opts.name ? opts.name + " — " : "") +
        data.length + " ölçüm · en düşük " + tr(min, opts.digits) +
        " · en yüksek " + tr(max, opts.digits) +
        " · son " + tr(data[data.length - 1], opts.digits);

      var svg = figure(W, H, label, animate);
      svg.setAttribute("class", (animate ? "chart--anim " : "") + "spark__svg");

      var d = data
        .map(function (v, i) {
          return (i ? "L" : "M") + px(i).toFixed(1) + " " + py(v).toFixed(1);
        })
        .join(" ");

      var marks = group("chart__marks");
      if (opts.area !== false) {
        marks.appendChild(
          el("path", {
            class: "chart__area",
            fill: color,
            d: d + " L" + px(data.length - 1).toFixed(1) + " " + H + " L" + pad + " " + H + " Z"
          })
        );
      }
      marks.appendChild(el("path", { class: "spark__line", stroke: color, d: d }));
      marks.appendChild(
        el("circle", {
          class: "chart__dot",
          cx: px(data.length - 1),
          cy: py(data[data.length - 1]),
          r: 3,
          fill: color
        })
      );
      svg.appendChild(marks);

      host.innerHTML = "";
      host.appendChild(svg);
    });
  }

  /* ======================================================================== */
  /* heatmap — run activity as a grid (7×24 week-hour, or a 30-day calendar)  */
  /* ======================================================================== */
  /*
   * `matrix` is an array of rows; a cell is a number, null, or { value, label }.
   * Magnitude, so the colour is SEQUENTIAL: one hue, light→dark on the light
   * surface and dark→bright on the dark one (each ramp selected for its own
   * surface, never an inversion).
   */

  var RAMP = ["var(--ramp-1)", "var(--ramp-2)", "var(--ramp-3)", "var(--ramp-4)", "var(--ramp-5)"];

  function heatmap(host, matrix, options) {
    var opts = options || {};
    if (!host) return;
    var rows = (matrix || []).filter(Array.isArray);
    var cols = rows.reduce(function (acc, row) {
      return Math.max(acc, row.length);
    }, 0);

    function cellValue(cell) {
      if (cell == null) return null;
      if (typeof cell === "object") return isFinite(cell.value) ? Number(cell.value) : null;
      return isFinite(cell) ? Number(cell) : null;
    }

    var max = 0;
    var any = false;
    rows.forEach(function (row) {
      row.forEach(function (cell) {
        var v = cellValue(cell);
        if (v == null) return;
        if (v > 0) any = true;
        if (v > max) max = v;
      });
    });

    if (!rows.length || !cols || !any) {
      emptyBox(host, opts.empty || "Veri yok.");
      return;
    }

    mount(host, function (W) {
      var animate = firstPaint(host);
      var rowLabels = opts.rowLabels || [];
      var colLabels = opts.colLabels || [];
      var gap = 2;
      // Size the gutter to the WIDEST row label actually passed, not to a
      // hard-coded sample: "Pazartesi" and "Pzt" want different gutters.
      var labelW = rowLabels.length
        ? Math.ceil(
            rowLabels.reduce(function (acc, label) {
              return Math.max(acc, textWidth(label, 11));
            }, 0)
          ) + 8
        : 0;
      var headH = colLabels.length ? 16 : 0;

      var cell = Math.floor((W - labelW - gap) / cols) - gap;
      cell = Math.max(6, Math.min(opts.maxCell || 26, cell));
      var gridW = cols * (cell + gap);
      var H = headH + rows.length * (cell + gap) + 2;

      var svg = figure(W, H, opts.aria || "Etkinlik ısı haritası", animate);
      var marks = group("chart__marks chart__marks--cells");

      colLabels.forEach(function (label, c) {
        if (!label) return;
        var ct = el("text", {
          class: "chart__tick",
          x: labelW + c * (cell + gap) + cell / 2,
          y: headH - 5,
          "text-anchor": "middle"
        });
        ct.textContent = label;
        svg.appendChild(ct);
      });

      rows.forEach(function (row, r) {
        var y = headH + r * (cell + gap);
        if (rowLabels[r]) {
          var rt = el("text", {
            class: "chart__tick",
            x: labelW - 7,
            y: y + cell / 2 + 3.5,
            "text-anchor": "end"
          });
          rt.textContent = rowLabels[r];
          svg.appendChild(rt);
        }
        for (var c = 0; c < cols; c += 1) {
          var raw = row[c];
          var v = cellValue(raw);
          var x = labelW + c * (cell + gap);
          var bucket = v == null || v <= 0 ? -1 : Math.min(RAMP.length - 1, Math.floor((v / max) * RAMP.length - 1e-9));
          var rect = el("rect", {
            class: "chart__cell",
            x: x, y: y, width: cell, height: cell, rx: 3,
            fill: bucket < 0 ? "var(--ramp-0)" : RAMP[bucket]
          });
          if (animate) rect.style.animationDelay = Math.min(240, c * 8) + "ms";
          var tip =
            (raw && typeof raw === "object" && raw.label ? raw.label : (rowLabels[r] || "") + " " + (colLabels[c] || c)) +
            "\n" + (v == null || v <= 0 ? (opts.zeroLabel || "çalıştırma yok") : tr(v) + " " + (opts.unit || "çalıştırma"));
          titled(rect, tip.replace("\n", " — "));
          hoverable(rect, tip);
          marks.appendChild(rect);
        }
      });
      svg.appendChild(marks);

      host.innerHTML = "";
      host.appendChild(svg);

      var scale = document.createElement("div");
      scale.className = "heat-scale";
      var lo = document.createElement("span");
      lo.textContent = opts.lowLabel || "az";
      scale.appendChild(lo);
      ["var(--ramp-0)"].concat(RAMP).forEach(function (color) {
        var sw = document.createElement("span");
        sw.className = "heat-scale__swatch";
        sw.style.background = color;
        sw.setAttribute("aria-hidden", "true");
        scale.appendChild(sw);
      });
      var hi = document.createElement("span");
      hi.textContent = (opts.highLabel || "çok") + " (en fazla " + tr(max) + ")";
      scale.appendChild(hi);
      host.appendChild(scale);
      // gridW is informational: the grid never exceeds the measured width.
      void gridW;
    });
  }

  /* ======================================================================== */
  /* dataTable — the sortable, sticky-headed, phone-friendly analysis table   */
  /* ======================================================================== */
  /*
   * columns: [{ key, label, type, align, format, sortValue, barMax, width }]
   *   type "text"  (default) · "num" · "pct" (mini bar cell) ·
   *        "trend" (↑ ↓ → with a semantic colour) · "badge" ({tone,icon,label})
   * rows: plain objects keyed by `column.key`.
   * opts: { sort:{key,dir}, empty, caption, maxHeight, primary }
   *
   * Below 640px the table stops being a table and becomes a stack of key/value
   * cards — a horizontal scrollbar inside a vertical scroll is the worst of
   * both, and on a phone a nine-column grid is unreadable either way.
   */

  var TREND = {
    up: { glyph: "↑", cls: "trend--up", word: "arttı" },
    down: { glyph: "↓", cls: "trend--down", word: "azaldı" },
    flat: { glyph: "→", cls: "trend--flat", word: "değişmedi" }
  };

  function trendOf(value, column) {
    if (value == null || value === "" || !isFinite(Number(value))) return null;
    var n = Number(value);
    var threshold = column.threshold || 0;
    var dir = n > threshold ? "up" : n < -threshold ? "down" : "flat";
    var spec = TREND[dir];
    // "Up" is not automatically good — the caller says which way is better.
    var good = column.betterWhen === "down" ? dir === "down" : dir === "up";
    var tone = dir === "flat" ? "flat" : good ? "up" : "down";
    return { dir: dir, glyph: spec.glyph, word: spec.word, tone: tone, value: n };
  }

  function cellContent(column, row) {
    var value = row[column.key];
    var td = document.createElement("td");
    td.setAttribute("data-label", column.label);

    if (column.type === "num" || column.type === "pct") td.className = "num";
    if (column.align === "right") td.className = "num";

    if (column.type === "trend") {
      var t = trendOf(value, column);
      if (!t) {
        td.textContent = "—";
        return td;
      }
      var span = document.createElement("span");
      span.className = "trend trend--" + t.tone;
      var glyph = document.createElement("span");
      glyph.setAttribute("aria-hidden", "true");
      glyph.textContent = t.glyph;
      span.appendChild(glyph);
      span.appendChild(
        document.createTextNode(
          " " + (column.format ? column.format(t.value, row) : tr(Math.abs(t.value), column.digits))
        )
      );
      span.title = t.word;
      var sr = document.createElement("span");
      sr.className = "visually-hidden";
      sr.textContent = " " + t.word;
      span.appendChild(sr);
      td.appendChild(span);
      td.className = "num";
      return td;
    }

    if (column.type === "badge") {
      var badge = value || {};
      var el2 = document.createElement("span");
      el2.className = "badge badge--" + (badge.tone || "info");
      el2.textContent = (badge.icon ? badge.icon + " " : "") + (badge.label || "—");
      td.appendChild(el2);
      return td;
    }

    if (column.type === "pct") {
      var n = Number(value);
      if (!isFinite(n)) {
        td.textContent = "—";
        return td;
      }
      var wrap = document.createElement("span");
      wrap.className = "cell-bar";
      var track = document.createElement("span");
      track.className = "cell-bar__track";
      var fill = document.createElement("span");
      fill.className = "cell-bar__fill";
      var pctMax = column.barMax || 100;
      fill.style.width = Math.max(2, Math.min(100, (Math.abs(n) / pctMax) * 100)) + "%";
      if (column.color) fill.style.background = column.color;
      track.appendChild(fill);
      var text = document.createElement("span");
      text.className = "cell-bar__value";
      text.textContent = column.format ? column.format(n, row) : "%" + tr(n, column.digits == null ? 1 : column.digits);
      wrap.appendChild(text);
      wrap.appendChild(track);
      td.appendChild(wrap);
      return td;
    }

    var out = column.format
      ? column.format(value, row)
      : column.type === "num"
        ? tr(value, column.digits)
        : value == null || value === "" ? "—" : String(value);
    if (out && out.nodeType) td.appendChild(out);
    else td.textContent = out;
    return td;
  }

  function sortKey(column, row) {
    if (column.sortValue) return column.sortValue(row);
    var v = row[column.key];
    if (v && typeof v === "object") return v.order != null ? v.order : v.label || "";
    return v;
  }

  function dataTable(host, columns, rows, options) {
    var opts = options || {};
    if (!host) return;
    var cols = (columns || []).filter(Boolean);
    var data = (rows || []).slice();

    if (!cols.length || !data.length) {
      emptyBox(host, opts.empty || "Veri yok.");
      return;
    }

    var sort = host.__aiaSort || opts.sort || null;

    function paint() {
      host.innerHTML = "";
      var wrap = document.createElement("div");
      wrap.className = "dtable-wrap";
      if (opts.maxHeight) wrap.style.maxHeight = opts.maxHeight;

      var table = document.createElement("table");
      table.className = "dtable";

      var caption = document.createElement("caption");
      caption.className = "visually-hidden";
      caption.textContent = opts.caption || "Veri tablosu";
      table.appendChild(caption);

      var thead = document.createElement("thead");
      var headRow = document.createElement("tr");
      cols.forEach(function (column) {
        var th = document.createElement("th");
        th.scope = "col";
        if (column.type === "num" || column.type === "pct" || column.type === "trend" || column.align === "right") {
          th.className = "num";
        }
        if (column.width) th.style.width = column.width;

        if (column.sortable === false) {
          // Marked so the <640px chip row can drop it: a header with nothing
          // to click is noise once the table has become a stack of cards.
          th.className = (th.className ? th.className + " " : "") + "dtable__th--static";
          th.textContent = column.label;
        } else {
          var active = sort && sort.key === column.key;
          th.setAttribute("aria-sort", active ? (sort.dir === "asc" ? "ascending" : "descending") : "none");
          var button = document.createElement("button");
          button.type = "button";
          button.className = "dtable__sort" + (active ? " is-active" : "");
          button.appendChild(document.createTextNode(column.label));
          var arrow = document.createElement("span");
          arrow.className = "dtable__arrow";
          arrow.setAttribute("aria-hidden", "true");
          arrow.textContent = active ? (sort.dir === "asc" ? "▲" : "▼") : "↕";
          button.appendChild(arrow);
          button.title = "Sırala: " + column.label;
          button.addEventListener("click", function () {
            // First click on a column sorts biggest-first (what you want from a
            // "who spends the most" table); clicking the active column flips it.
            host.__aiaSort = {
              key: column.key,
              dir: active && sort.dir === "desc" ? "asc" : "desc"
            };
            sort = host.__aiaSort;
            paint();
            // Sorting is a keyboard action too: keep focus on the header the
            // user just pressed instead of dumping it back to <body>.
            var again = host.querySelector(".dtable__sort.is-active");
            if (again) again.focus();
          });
          th.appendChild(button);
        }
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var ordered = data;
      if (sort) {
        var column = cols.filter(function (c) {
          return c.key === sort.key;
        })[0];
        if (column) {
          ordered = data.slice().sort(function (a, b) {
            var x = sortKey(column, a);
            var y = sortKey(column, b);
            var nx = Number(x);
            var ny = Number(y);
            var cmp;
            if (isFinite(nx) && isFinite(ny)) cmp = nx - ny;
            else cmp = String(x == null ? "" : x).localeCompare(String(y == null ? "" : y), "tr");
            return sort.dir === "asc" ? cmp : -cmp;
          });
        }
      }

      var tbody = document.createElement("tbody");
      ordered.forEach(function (row) {
        var tr2 = document.createElement("tr");
        cols.forEach(function (column, index) {
          var td = cellContent(column, row);
          if (index === 0) td.classList.add("dtable__key");
          tr2.appendChild(td);
        });
        tbody.appendChild(tr2);
      });
      table.appendChild(tbody);
      wrap.appendChild(table);
      host.appendChild(wrap);

      if (opts.note) {
        var note = document.createElement("p");
        note.className = "dtable__note";
        note.textContent = opts.note;
        host.appendChild(note);
      }
    }

    paint();
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
    /* v2 — responsive (viewBox at measured width), hoverable, empty-safe */
    lineChart: lineChart,
    barChart: barChart,
    donutChart: donutChart,
    sparkline: sparkline,
    heatmap: heatmap,
    dataTable: dataTable,

    /* v1 — still rendered by app.js; fixed-viewBox but battle-tested */
    stackedRuns: stackedRuns,
    trend: trend,
    splitBar: splitBar,
    groupedShares: groupedShares,
    table: table,

    /* formatting helper shared with the caller */
    compact: compact
  };
})(typeof window !== "undefined" ? window : this);
