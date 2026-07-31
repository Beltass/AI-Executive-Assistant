/* AI Executive Assistant — dashboard app.
 *
 * Vanilla JS, no framework, no build, no CDN. It reads four static JSON files
 * written by the Python side and renders five tabs:
 *
 *   status.json   — how the last briefing run went (ai_assistant.status_report)
 *   metrics.json  — the rolling token/latency history (ai_assistant.metrics)
 *   health.json   — the watchdog's technical verdict (ai_assistant.watchdog)
 *   reports/…     — one readable document per advisor (ai_assistant.reports)
 *
 * ROUTING. The active tab lives in the URL hash, so a tab is shareable,
 * bookmarkable and the browser's back button works:
 *
 *   #/sistem                      🖥️  Sistem & Ajanlar   (default)
 *   #/icerik                      📄  İçerik & Raporlar
 *   #/performans                  📊  Performans & Token
 *   #/isler                       ✅  İşler & Takip
 *   #/fikirler                    💡  Öneriler & Fikirler
 *   #/raporlar                    arşiv (İçerik sekmesi içinde)
 *   #/raporlar/2026-07-31         o günün raporları
 *   #/rapor/2026-07-31/ajan_id    tek rapor (okuma görünümü)
 *
 * The Markdown the advisors emit is rendered by markdown.js, which ESCAPES the
 * source before it applies a safe subset — which is what makes it safe to feed
 * model-generated text into innerHTML.
 */
(function () {
  "use strict";

  var STATUS_URL = "./status.json";
  var METRICS_URL = "./metrics.json";
  var HEALTH_URL = "./health.json";
  var ARCHIVE_URL = "./reports/index.json";

  var REFRESH_MS = 60000; // live monitor: re-read the files every minute
  var CLOCK_MS = 20000; // how often the "x dk önce" label is recomputed
  var STALE_HOURS = 12; // older than this and we say so, loudly

  var TABS = ["sistem", "icerik", "performans", "isler", "fikirler", "entegrasyonlar", "gmail", "analiz"];
  var DEFAULT_TAB = "sistem";

  var STATUS_LABEL = { ok: "Çalıştı", failed: "Hata", skipped: "Atlandı" };
  var STATUS_ICON = { ok: "✅", failed: "⚠️", skipped: "⏭️" };
  var CONCLUSION = {
    ok: { label: "Başarılı", cls: "ok", icon: "✅" },
    partial: { label: "Kısmi", cls: "partial", icon: "⚠️" },
    failed: { label: "Hata", cls: "failed", icon: "⛔" },
    idle: { label: "Boş geçti", cls: "skipped", icon: "⏭️" }
  };
  var SLACK_LABEL = {
    ok: { label: "Gönderildi", cls: "ok", icon: "✅" },
    failed: { label: "Gönderilemedi", cls: "failed", icon: "⚠️" },
    skipped: { label: "Atlanmış", cls: "skipped", icon: "⏭️" }
  };
  var MODE = {
    full: { label: "Tam brifing", icon: "🗓️", cls: "ok" },
    incremental: { label: "Artımlı", icon: "🔄", cls: "partial" }
  };
  // The watchdog's three severities. Icon + Turkish word, never colour alone.
  var SEVERITY = {
    ok: { icon: "🟢", label: "Sağlıklı", cls: "ok" },
    warn: { icon: "🟡", label: "Dikkat", cls: "warn" },
    critical: { icon: "🔴", label: "Müdahale gerek", cls: "critical" }
  };
  var RECO_ICON = { good: "✅", warn: "⚠️", info: "ℹ️" };

  /* The advisor whose report fills the "Öneriler & Fikirler" tab.
   *
   * The consolidation renamed it, so the CURRENT key is first and the retired
   * one is kept as a fallback: an archived day published before the rename
   * only has `innovation_lab` in its index, and that day must still open in
   * this tab. The reading view (#/rapor/<date>/<id>) is driven by the URL and
   * never consults this list, so no historical permalink depends on it. */
  var INNOVATION_IDS = ["ai_innovation", "innovation_lab"];

  var DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  var ID_RE = /^[A-Za-z0-9_-]+$/;

  var state = {
    status: null,
    metrics: null,
    health: null,
    archive: null,
    days: {}, // date -> day index
    docs: {}, // "date/id" -> document
    category: "*",
    search: "",
    lastFetch: null,
    tab: DEFAULT_TAB,
    route: { name: "tab", tab: DEFAULT_TAB },
    loaded: false
  };

  var charts = window.AIACharts || {};

  /* ====================================================================== */
  /* helpers                                                                */
  /* ====================================================================== */

  function $(id) {
    return document.getElementById(id);
  }

  function text(el, value) {
    if (el) el.textContent = value;
  }

  function show(el, visible) {
    if (el) el.hidden = !visible;
  }

  function make(tag, className, content) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (content != null) node.textContent = String(content);
    return node;
  }

  function num(value) {
    var n = Number(value);
    return isFinite(n) ? n : 0;
  }

  function trNumber(value) {
    return num(value).toLocaleString("tr-TR");
  }

  /** Turkish decimal (comma separator) with a fixed number of digits. */
  function trDecimal(value, digits) {
    return num(value).toLocaleString("tr-TR", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    });
  }

  function pad2(value) {
    return (value < 10 ? "0" : "") + value;
  }

  function duration(seconds) {
    if (seconds === null || seconds === undefined || isNaN(seconds)) return "–";
    var s = Number(seconds);
    if (s < 60) return s.toFixed(s < 10 ? 1 : 0) + " sn";
    var minutes = Math.floor(s / 60);
    var rest = Math.round(s % 60);
    return minutes + " dk " + (rest < 10 ? "0" : "") + rest + " sn";
  }

  function bytesish(chars) {
    if (!chars) return "içerik yok";
    if (chars < 1000) return chars + " karakter";
    return (chars / 1000).toFixed(1).replace(".", ",") + "b karakter";
  }

  function relativeTime(iso) {
    var then = Date.parse(iso);
    if (isNaN(then)) return "";
    var diff = Math.round((Date.now() - then) / 1000);
    if (diff < 0) diff = 0;
    if (diff < 60) return diff + " sn önce";
    if (diff < 3600) return Math.floor(diff / 60) + " dk önce";
    if (diff < 86400) return Math.floor(diff / 3600) + " sa önce";
    return Math.floor(diff / 86400) + " gün önce";
  }

  var TR_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"
  ];

  function prettyDate(iso) {
    if (!DATE_RE.test(String(iso || ""))) return String(iso || "");
    var parts = iso.split("-");
    var month = TR_MONTHS[Number(parts[1]) - 1] || parts[1];
    return Number(parts[2]) + " " + month + " " + parts[0];
  }

  function todayIso() {
    // The reports are dated in Istanbul time (UTC+3, fixed since 2016), so the
    // "bugün" badge must be too — otherwise a 01:00 visit from Europe would
    // call yesterday's briefing today's.
    return new Date(Date.now() + 3 * 3600 * 1000).toISOString().slice(0, 10);
  }

  function shortStamp(entry) {
    var label = entry.at_istanbul || entry.at || "";
    // "31.07.2026 10:04" -> "10:04"
    var parts = label.split(" ");
    return parts.length > 1 ? parts[1] : label.slice(0, 10);
  }

  var renderMarkdown =
    typeof AIAMarkdown !== "undefined" && AIAMarkdown.renderMarkdown
      ? AIAMarkdown.renderMarkdown
      : function () {
          // markdown.js failed to load: render nothing rather than raw HTML.
          return "";
        };

  function fetchJson(url) {
    // Cache-bust: a static host (Pages, Vercel) will happily serve a stale copy.
    return fetch(url + (url.indexOf("?") === -1 ? "?" : "&") + "t=" + Date.now(), {
      cache: "no-store"
    })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.text();
      })
      .then(function (raw) {
        if (!raw.trim()) throw new Error("empty");
        return JSON.parse(raw);
      });
  }

  /** Fetch that resolves to null instead of rejecting — for optional files. */
  function fetchOptional(url) {
    return fetchJson(url).catch(function () {
      return null;
    });
  }

  /* ====================================================================== */
  /* theme                                                                  */
  /* ====================================================================== */

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") === "light"
      ? "light"
      : "dark";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var toggle = $("theme-toggle");
    var light = theme === "light";
    text($("theme-icon"), light ? "🌙" : "☀️");
    if (toggle) {
      toggle.setAttribute("aria-label", light ? "Koyu temaya geç" : "Açık temaya geç");
    }
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", light ? "#f9f9f7" : "#0d0d0d");
    try {
      localStorage.setItem("aia-theme", theme);
    } catch (error) {
      /* storage disabled: the choice just does not persist */
    }
    // The charts read their colours from CSS custom properties, so they must be
    // rebuilt for the new theme's values.
    if (state.loaded) renderCharts();
  }

  /* ====================================================================== */
  /* TAB 1 — 🖥️ Sistem & Ajanlar                                            */
  /* ====================================================================== */

  function successRate(history) {
    var scored = history.filter(function (entry) {
      return entry.conclusion && entry.conclusion !== "idle";
    });
    if (!scored.length) return null;
    var good = scored.filter(function (entry) {
      return entry.conclusion === "ok";
    }).length;
    return { rate: Math.round((good / scored.length) * 100), total: scored.length };
  }

  function renderHealthHeader(data) {
    var run = data.run || {};
    var conclusion = CONCLUSION[run.conclusion] || CONCLUSION.idle;
    var slack = SLACK_LABEL[(data.slack || {}).status] || SLACK_LABEL.skipped;
    var mode = MODE[run.mode] || MODE.full;
    var health = state.health || {};
    var severity = SEVERITY[health.severity] || null;

    // The dot prefers the watchdog's verdict (it knows about staleness and
    // quota too); without it the run's own conclusion is the honest fallback.
    text($("health-dot"), severity ? severity.icon : conclusion.icon);
    text(
      $("health-headline"),
      severity ? severity.label + " — " + (health.headline || "") : conclusion.label
    );
    var badge = $("health-badge");
    badge.className = "badge badge--" + (severity ? severity.cls : conclusion.cls);
    badge.textContent = conclusion.icon + " " + conclusion.label;

    text(
      $("hh-last"),
      (data.generated_at_istanbul || "–") +
        (data.generated_at ? " · " + relativeTime(data.generated_at) : "")
    );
    text($("hh-duration"), duration(run.duration_seconds));
    text($("hh-mode"), mode.icon + " " + mode.label);
    text($("hh-slack"), slack.icon + " " + slack.label);

    var history = Array.isArray(data.history) ? data.history : [];
    var rate = successRate(history);
    text(
      $("hh-uptime"),
      rate ? "%" + rate.rate + " (son " + rate.total + " çalıştırma)" : "—"
    );

    var batch = run.batch || {};
    text($("hh-model"), batch.model || batch.provider || "—");

    var tokens = run.tokens || {};
    text(
      $("hh-tokens"),
      tokens.called && tokens.total
        ? trNumber(tokens.total) + " token"
        : "model çağrısı yok"
    );

    text(
      $("last-run-label"),
      conclusion.icon + " " + conclusion.label + " · " +
        (data.generated_at_istanbul || "–") + " (İstanbul)"
    );
  }

  function renderWatchdog() {
    var health = state.health;
    var host = $("watchdog-checks");
    var badge = $("watchdog-badge");
    host.innerHTML = "";

    if (!health) {
      show(badge, false);
      text(
        $("watchdog-note"),
        "Teknik nöbetçi henüz çalışmadı. Saat başı çalışan kontrol iş akışı " +
          "health.json dosyasını oluşturduğunda buraya teknik bulgular gelecek."
      );
      return;
    }

    var severity = SEVERITY[health.severity] || SEVERITY.ok;
    show(badge, true);
    badge.className = "badge badge--" + severity.cls;
    badge.textContent = severity.icon + " " + severity.label;

    text(
      $("watchdog-note"),
      (health.headline || "") +
        (health.generated_at_istanbul
          ? " · kontrol: " + health.generated_at_istanbul
          : "")
    );

    var checks = Array.isArray(health.checks) ? health.checks : [];
    // Problems first: a green list is reassuring, a red line is actionable.
    var order = { critical: 0, warn: 1, ok: 2 };
    checks
      .slice()
      .sort(function (a, b) {
        return (order[a.severity] || 3) - (order[b.severity] || 3);
      })
      .forEach(function (check) {
        var kind = SEVERITY[check.severity] || SEVERITY.ok;
        var card = make("div", "check check--" + kind.cls);
        card.appendChild(make("span", "check__icon", kind.icon));

        var body = make("div");
        body.appendChild(make("h3", "check__name", check.name || check.id || "Kontrol"));
        body.appendChild(make("p", "check__detail", check.detail || ""));
        if (check.remedy && check.severity !== "ok") {
          body.appendChild(make("p", "check__fix", "🔧 " + check.remedy));
        }
        card.appendChild(body);
        host.appendChild(card);
      });
  }

  function renderSummaryTiles(data) {
    var run = data.run || {};
    text($("stat-total"), run.total != null ? run.total : "–");
    text($("stat-ok"), run.ok != null ? run.ok : "–");
    text($("stat-failed"), run.failed != null ? run.failed : "–");
    text($("stat-skipped"), run.skipped != null ? run.skipped : "–");
    text($("stat-new"), run.new_findings != null ? run.new_findings : "–");
    var batch = run.batch || {};
    text(
      $("stat-batch"),
      (batch.sections_produced || 0) + "/" + (batch.sections_requested || 0)
    );

    // A failure count on the tab itself, so a problem is visible from any tab.
    var badge = $("badge-sistem");
    if (run.failed > 0) {
      badge.hidden = false;
      badge.className = "tab__badge tab__badge--alert";
      badge.textContent = String(run.failed);
    } else {
      badge.hidden = true;
    }
  }

  function renderFilters(advisors) {
    var host = $("filters");
    host.innerHTML = "";
    var seen = [];
    advisors.forEach(function (a) {
      if (a.category && seen.indexOf(a.category) === -1) seen.push(a.category);
    });

    var options = [{ key: "*", label: "Tümü (" + advisors.length + ")" }];
    seen.forEach(function (category) {
      var count = advisors.filter(function (a) {
        return a.category === category;
      }).length;
      options.push({ key: category, label: category + " (" + count + ")" });
    });

    options.forEach(function (option) {
      var button = make("button", "chip", option.label);
      button.type = "button";
      button.setAttribute(
        "aria-pressed",
        state.category === option.key ? "true" : "false"
      );
      button.addEventListener("click", function () {
        state.category = option.key;
        renderFilters(advisors);
        renderAgentCards(advisors);
      });
      host.appendChild(button);
    });
  }

  function renderAgentCards(advisors) {
    var grid = $("advisor-grid");
    grid.innerHTML = "";
    var visible = advisors.filter(function (a) {
      return state.category === "*" || a.category === state.category;
    });
    show($("advisors-empty"), visible.length === 0);

    visible.forEach(function (advisor) {
      var status = STATUS_LABEL[advisor.status] ? advisor.status : "skipped";
      // "Nothing new" is not the same as "not configured": the advisor ran and
      // deliberately stayed quiet because the user already knows.
      var quiet = advisor.nothing_new === true;

      var card = make("article", "agent agent--" + status);
      var head = make("div", "agent__head");
      var emoji = make("span", "agent__emoji", advisor.emoji || "🧩");
      emoji.setAttribute("aria-hidden", "true");

      var name = make("h3", "agent__name", advisor.name || advisor.id);
      name.appendChild(make("span", "agent__id", advisor.id));

      var badge = make(
        "span",
        "badge badge--" + status,
        quiet ? "🟰 Yeni bulgu yok" : STATUS_ICON[status] + " " + STATUS_LABEL[status]
      );

      head.appendChild(emoji);
      head.appendChild(name);
      head.appendChild(badge);
      card.appendChild(head);

      if (advisor.detail) {
        card.appendChild(make("p", "agent__detail", advisor.detail));
      }

      var foot = make("div", "agent__foot");
      foot.appendChild(make("span", "tag", advisor.category || "—"));
      var size = make("span");
      if (quiet) {
        size.textContent = "0 yeni bulgu";
      } else if (status === "ok") {
        size.textContent =
          bytesish(advisor.content_length) +
          (advisor.new_findings ? " · 🆕 " + advisor.new_findings : "");
      } else {
        size.textContent = "—";
      }
      foot.appendChild(size);
      card.appendChild(foot);

      grid.appendChild(card);
    });
  }

  function renderHistory(history) {
    var recent = history.slice(-24);
    if (charts.stackedRuns) charts.stackedRuns($("chart-history"), recent);
    text(
      $("history-sub"),
      recent.length ? "son " + recent.length + " çalıştırma" : ""
    );

    if (!charts.table) return;
    charts.table(
      $("table-history"),
      [
        { label: "Zaman" },
        { label: "Sonuç" },
        { label: "✅", num: true },
        { label: "⚠️", num: true },
        { label: "⏭️", num: true },
        { label: "Süre", num: true },
        { label: "Slack" }
      ],
      history
        .slice(-12)
        .reverse()
        .map(function (entry) {
          var conclusion = CONCLUSION[entry.conclusion] || CONCLUSION.idle;
          var slack = SLACK_LABEL[entry.slack] || SLACK_LABEL.skipped;
          var mode = MODE[entry.mode];
          return [
            (mode ? mode.icon + " " : "") + (entry.at_istanbul || entry.at || "—"),
            conclusion.icon + " " + conclusion.label,
            entry.ok || 0,
            entry.failed || 0,
            entry.skipped || 0,
            duration(entry.duration_seconds),
            slack.icon + " " + slack.label
          ];
        }),
      "Son çalıştırmaların tablo görünümü"
    );
  }

  /* ---------------------------------------------------------------------- */
  /* run activity heatmap                                                    */
  /* ---------------------------------------------------------------------- */

  var WEEKDAYS = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"];
  var WEEKDAYS_LONG = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"];

  /**
   * Read the Istanbul weekday + hour out of a history entry.
   *
   * `at_istanbul` is already local ("30.07.2026 18:01"), so it is preferred:
   * deriving the hour from the UTC `at` would smear an 18:00 run into 15:00.
   * Returns null when neither field parses — the caller just skips the entry.
   */
  function istanbulSlot(entry) {
    if (!entry) return null;
    var local = /^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})/.exec(entry.at_istanbul || "");
    if (local) {
      var day = Number(local[1]);
      var month = Number(local[2]);
      var year = Number(local[3]);
      var stamp = new Date(Date.UTC(year, month - 1, day));
      if (isNaN(stamp.getTime())) return null;
      // getUTCDay() is 0=Sunday; our rows start on Monday.
      return { row: (stamp.getUTCDay() + 6) % 7, hour: Number(local[4]) };
    }
    var iso = entry.at ? new Date(entry.at) : null;
    if (!iso || isNaN(iso.getTime())) return null;
    return { row: (iso.getUTCDay() + 6) % 7, hour: iso.getUTCHours() };
  }

  function renderActivity(history) {
    var host = $("chart-activity");
    if (!host || !charts.heatmap) return;

    var matrix = [];
    var r;
    var c;
    for (r = 0; r < 7; r += 1) {
      matrix.push([]);
      for (c = 0; c < 24; c += 1) matrix[r].push(0);
    }

    var counted = 0;
    history.forEach(function (entry) {
      var slot = istanbulSlot(entry);
      if (!slot || slot.hour < 0 || slot.hour > 23) return;
      matrix[slot.row][slot.hour] += 1;
      counted += 1;
    });

    // A tick on every hour is unreadable at phone width; every third is enough
    // to place a cell, and the tooltip carries the exact hour anyway.
    var colLabels = [];
    for (c = 0; c < 24; c += 1) colLabels.push(c % 3 === 0 ? pad2(c) : "");

    var cells = [];
    for (r = 0; r < 7; r += 1) {
      cells.push([]);
      for (c = 0; c < 24; c += 1) {
        cells[r].push({
          value: matrix[r][c],
          label: WEEKDAYS_LONG[r] + " " + pad2(c) + ":00"
        });
      }
    }

    charts.heatmap(host, cells, {
      rowLabels: WEEKDAYS,
      colLabels: colLabels,
      aria: "Haftanın günü ve saate göre çalıştırma yoğunluğu",
      unit: "çalıştırma",
      zeroLabel: "çalıştırma yok",
      lowLabel: "az",
      highLabel: "çok",
      empty: "Veri yok."
    });

    text(
      $("activity-sub"),
      counted ? counted + " çalıştırma işaretlendi" : ""
    );
  }

  /* ---------------------------------------------------------------------- */
  /* per-advisor scorecard                                                   */
  /* ---------------------------------------------------------------------- */

  var ADVISOR_TONE = { ok: "ok", failed: "failed", skipped: "skipped" };

  /**
   * Fold the metrics history into one row per advisor id.
   *
   * Neither status.json nor metrics.json measures an advisor's WALL CLOCK time
   * — only the whole run's latency is timed. So "süre" here is that latency
   * split across the advisors of the same run in proportion to their estimated
   * tokens, which is the same attribution metrics.py already uses for the
   * token column and is labelled "tahmini" in the table's note. Nothing on the
   * Python side changes.
   */
  function advisorMetrics(runs) {
    var bucket = {};
    runs.slice(-7).forEach(function (run) {
      var runTokens = num(run.total_tokens);
      var latency = num(run.latency_seconds);
      (run.agents || []).forEach(function (agent) {
        if (!agent || !agent.id) return;
        var entry = bucket[agent.id] || {
          id: agent.id,
          name: agent.name || agent.id,
          tokens: 0,
          chars: 0,
          seconds: 0,
          lastAt: "",
          lastOrder: 0
        };
        var tokens = num(agent.est_total_tokens);
        entry.tokens += tokens;
        entry.chars += num(agent.output_chars);
        if (runTokens > 0 && latency > 0) entry.seconds += latency * (tokens / runTokens);
        if (agent.name) entry.name = agent.name;

        var order = Date.parse(run.at || "");
        if (!isFinite(order)) order = 0;
        if (!entry.lastAt || order >= entry.lastOrder) {
          entry.lastAt = run.at_istanbul || run.at || "";
          entry.lastOrder = order;
        }
        bucket[agent.id] = entry;
      });
    });
    return bucket;
  }

  function renderAdvisorTable(advisors) {
    var host = $("table-advisors");
    if (!host || !charts.dataTable) return;

    var runs = metricRuns();
    var perAdvisor = advisorMetrics(runs);

    var rows = advisors.map(function (advisor) {
      var m = perAdvisor[advisor.id] || {};
      var status = ADVISOR_TONE[advisor.status] ? advisor.status : "skipped";
      var quiet = advisor.nothing_new === true;
      var tokens = num(m.tokens);
      var chars = num(m.chars);
      return {
        id: advisor.id,
        advisor: (advisor.emoji ? advisor.emoji + " " : "") + (advisor.name || advisor.id),
        sortName: advisor.name || advisor.id,
        durum: {
          tone: status,
          icon: quiet ? "🟰" : STATUS_ICON[status],
          label: quiet ? "Yeni bulgu yok" : STATUS_LABEL[status],
          // Sorting a badge needs an explicit order — alphabetical on the
          // Turkish label would put "Atlandı" above "Çalıştı".
          order: status === "failed" ? 0 : status === "ok" ? 1 : 2
        },
        sure: m.seconds != null ? num(m.seconds) : 0,
        token: tokens,
        verim: tokens > 0 ? Math.round((chars / tokens) * 1000) : 0,
        son: m.lastAt || "",
        sonOrder: num(m.lastOrder)
      };
    });

    var verimMax = rows.reduce(function (acc, row) {
      return Math.max(acc, row.verim);
    }, 0);

    charts.dataTable(
      host,
      [
        { key: "advisor", label: "Ajan", sortValue: function (row) { return row.sortName; } },
        { key: "durum", label: "Durum", type: "badge" },
        {
          key: "sure",
          label: "Süre",
          type: "num",
          format: function (value) {
            return value > 0 ? duration(value) : "—";
          }
        },
        {
          key: "token",
          label: "Token",
          type: "num",
          format: function (value) {
            return value > 0 ? trNumber(Math.round(value)) : "—";
          }
        },
        {
          key: "verim",
          label: "Verim",
          type: "pct",
          barMax: verimMax || 1,
          color: "var(--series-3)",
          format: function (value) {
            return value > 0 ? trNumber(value) + " kr./1K" : "—";
          }
        },
        {
          key: "son",
          label: "Son çalışma",
          sortValue: function (row) { return row.sonOrder; },
          format: function (value) {
            return value || "—";
          }
        }
      ],
      rows,
      {
        sort: { key: "token", dir: "desc" },
        caption: "Ajan başına durum, süre, token, verim ve son çalışma",
        empty: "Veri yok.",
        note:
          "Süre ve token ajan başına ölçülmez: son 7 çalıştırmanın toplam " +
          "gecikmesi ve token'ı, ajanların tahmini payına göre bölüştürülmüştür. " +
          "Verim = 1.000 token başına üretilen karakter (yüksek olan iyi). " +
          "Başlığa tıklayarak sıralayabilirsin."
      }
    );

    text(
      $("advisor-table-sub"),
      rows.length ? rows.length + " ajan · sıralanabilir" : ""
    );
  }

  function renderSistem() {
    var data = state.status;
    if (!data) return;
    show($("sistem-state"), false);
    show($("sistem-error"), false);
    show($("sistem-body"), true);

    var advisors = Array.isArray(data.advisors) ? data.advisors : [];
    var history = Array.isArray(data.history) ? data.history : [];

    renderHealthHeader(data);
    renderWatchdog();
    renderSummaryTiles(data);
    renderFilters(advisors);
    renderAgentCards(advisors);
    renderHistory(history);
    renderActivity(history);
    renderAdvisorTable(advisors);
  }

  /* ====================================================================== */
  /* TAB 2 — 📄 İçerik & Raporlar                                           */
  /* ====================================================================== */

  function reportCard(entry, date) {
    var link = make("a", "report-card");
    link.href = "#/rapor/" + date + "/" + entry.id;

    var head = make("div", "report-card__head");
    var emoji = make("span", "report-card__emoji", entry.emoji || "📄");
    emoji.setAttribute("aria-hidden", "true");
    head.appendChild(emoji);
    head.appendChild(make("h3", "report-card__name", entry.name || entry.id));
    link.appendChild(head);

    link.appendChild(
      make("p", "report-card__lead", entry.headline || entry.excerpt || "")
    );

    var foot = make("div", "report-card__foot");
    foot.appendChild(make("span", "tag", entry.category || "—"));
    foot.appendChild(
      make(
        "span",
        null,
        "⏱️ ~" + (entry.read_minutes || 1) + " dk okuma · " + (entry.words || 0) + " kelime"
      )
    );
    link.appendChild(foot);
    return link;
  }

  function matchesSearch(entry, query) {
    if (!query) return true;
    var haystack = [
      entry.name,
      entry.id,
      entry.category,
      entry.headline,
      entry.excerpt
    ]
      .join(" ")
      .toLocaleLowerCase("tr");
    return haystack.indexOf(query) !== -1;
  }

  function renderReportsList() {
    var host = $("report-grid");
    host.innerHTML = "";
    var day = state.days[latestDay()];
    var entries = day && Array.isArray(day.reports) ? day.reports : [];
    var query = state.search.trim().toLocaleLowerCase("tr");
    var visible = entries.filter(function (entry) {
      return matchesSearch(entry, query);
    });

    if (!entries.length) {
      text(
        $("reports-note"),
        "Bu çalıştırmada yayınlanmış rapor yok. Tam brifing İstanbul saatiyle " +
          "10:00'da hazırlanır."
      );
      show($("reports-empty"), true);
      $("reports-empty").textContent = "Henüz yayınlanmış rapor yok.";
      return;
    }

    var isToday = day.date === todayIso();
    text(
      $("reports-note"),
      (isToday ? "Bugünün brifingi" : prettyDate(day.date) + " brifingi") +
        " · " + entries.length + " rapor" +
        (day.generated_at_istanbul ? " · " + day.generated_at_istanbul + " (İstanbul)" : "")
    );

    if (!visible.length) {
      show($("reports-empty"), true);
      $("reports-empty").textContent =
        "“" + state.search + "” için rapor bulunamadı.";
      return;
    }
    show($("reports-empty"), false);

    visible.forEach(function (entry) {
      host.appendChild(reportCard(entry, day.date));
    });

    var badge = $("badge-icerik");
    badge.hidden = false;
    badge.className = "tab__badge";
    badge.textContent = String(entries.length);
  }

  function renderArchive() {
    var archive = state.archive;
    var host = $("archive-list");
    host.innerHTML = "";
    var days = archive && Array.isArray(archive.days) ? archive.days : [];
    show($("archive-empty"), days.length === 0);

    days.forEach(function (day) {
      var link = make("a", "archive-row");
      link.href = "#/raporlar/" + day.date;

      var left = make("span", "archive-row__date", prettyDate(day.date));
      if (day.date === todayIso()) {
        left.appendChild(make("span", "badge badge--ok", "bugün"));
      }
      link.appendChild(left);
      link.appendChild(make("span", "archive-row__meta", (day.count || 0) + " rapor"));
      host.appendChild(link);
    });

    text(
      $("archive-note"),
      days.length
        ? days.length + " gün arşivde (son " + (archive.retention_days || 30) + " gün saklanır)."
        : ""
    );
  }

  /* ---------------------------------------------------------------------- */
  /* the reading view — one advisor's document as a deliverable              */
  /* ---------------------------------------------------------------------- */
  /*
   * A document is either SCHEMA 2 (headline · key_metrics · sections ·
   * action_items · sources · meta, see ai_assistant.reports) or the SCHEMA 1
   * blob of markdown every archived day before it carries. Both render here,
   * and every block below the title is drawn only when the document actually
   * has one — a plain-text report degrades to lead + body, which is exactly
   * the clean document it always was, and never to a page of empty furniture.
   *
   * Nothing model-generated reaches innerHTML except through renderMarkdown(),
   * which escapes before it marks up; every other value goes in as text.
   */

  var TREND_GLYPH = { up: "↑", down: "↓", flat: "→" };
  var TREND_WORD = { up: "arttı", down: "azaldı", flat: "değişmedi" };

  var safeUrl =
    typeof AIAMarkdown !== "undefined" && AIAMarkdown.safeUrl
      ? AIAMarkdown.safeUrl
      : function () {
          return "";
        };

  // Mirrors ai_assistant.reports._HEADLINE_RE: the explicit "**Öne çıkan:** …"
  // marker line, decoration and all, so it can be recognised at the START of
  // a raw markdown blob.
  var HEADLINE_LINE_RE = /^[\s>#*\-+_`•·]*(?:o|ö)ne\s*(?:c|ç)(?:i|ı)kan(?:\s+bulgu)?\s*[:\-–—]/i;

  /**
   * Drop a leading "Öne çıkan:" line from a SCHEMA 1 document's raw markdown.
   *
   * A schema 2 document never needs this: the Python side already lifts that
   * sentence into `headline` and removes it from the derived `sections`. A
   * schema 1 archive never went through that split, so its `markdown` still
   * opens with the same line `doc-lead` already shows above it — without this,
   * every legacy report in the archive prints its lead sentence twice, one
   * line apart. Only that one line is ever removed; the rest of the body,
   * including a first sentence with no such marker, is untouched.
   */
  function stripLeadingHeadlineLine(markdown) {
    var text = String(markdown || "");
    var lines = text.split("\n");
    for (var i = 0; i < lines.length; i += 1) {
      if (!lines[i].trim()) continue;
      if (HEADLINE_LINE_RE.test(lines[i])) {
        return lines.slice(i + 1).join("\n").replace(/^\n+/, "");
      }
      break;
    }
    return text;
  }

  /** A document's list field, or [] — an old document simply has none. */
  function docList(doc, name) {
    var value = doc ? doc[name] : null;
    return Array.isArray(value) ? value : [];
  }

  function docMeta(doc) {
    return doc && doc.meta && typeof doc.meta === "object" ? doc.meta : {};
  }

  /** A "⏱️ ~3 dk okuma" chip in the title block. */
  function docFact(icon, label, title) {
    var li = make("li", "doc__fact");
    var glyph = make("span", "doc__fact-icon", icon);
    glyph.setAttribute("aria-hidden", "true");
    li.appendChild(glyph);
    li.appendChild(make("span", null, label));
    if (title) li.title = title;
    return li;
  }

  function renderDocFacts(doc) {
    var host = $("doc-facts");
    host.innerHTML = "";
    var meta = docMeta(doc);
    host.appendChild(
      docFact("⏱️", "~" + (doc.read_minutes || meta.read_minutes || 1) + " dk okuma")
    );
    var words = num(doc.words || meta.words);
    if (words) host.appendChild(docFact("📝", trNumber(words) + " kelime"));
    var tokens = num(meta.tokens);
    if (tokens) {
      host.appendChild(
        docFact(
          "🎟️",
          "~" + trNumber(tokens) + " token",
          "Tahmini: ajanlar tek bir toplu çağrıyı paylaşır, maliyet üretilen " +
            "metin payına göre dağıtılır."
        )
      );
    }
    var actions = docList(doc, "action_items").length;
    if (actions) host.appendChild(docFact("✅", actions + " aksiyon"));
  }

  /** The metric strip: 2–4 figures, each with the shared metric card. */
  function renderDocMetrics(doc) {
    var host = $("doc-metrics");
    host.innerHTML = "";
    var metrics = docList(doc, "key_metrics").slice(0, 4);
    if (!metrics.length) {
      show(host, false);
      return;
    }
    show(host, true);
    metrics.forEach(function (metric, index) {
      var trend = TREND_GLYPH[metric.trend] || "";
      var card = renderMetricCard(
        metric.label || "—",
        metric.value == null ? "—" : metric.value,
        metric.unit || "",
        trend,
        Array.isArray(metric.spark) ? metric.spark : null,
        "var(--series-" + ((index % 8) + 1) + ")",
        true // the advisor's own formatting; never re-punctuated
      );
      if (trend) card.title = (metric.label || "") + " " + TREND_WORD[metric.trend];
      if (metric.note) card.appendChild(make("p", "metric-card__note", metric.note));
      mountMetricCard(host, card);
    });
  }

  /** A section's table spec, drawn by the shared dataTable renderer. */
  function mountSectionTable(host, spec) {
    if (!spec || typeof spec !== "object" || !charts.dataTable) return;
    var columns = Array.isArray(spec.columns) ? spec.columns : [];
    var rows = Array.isArray(spec.rows) ? spec.rows : [];
    if (!columns.length || !rows.length) return;

    // A row may arrive as an array (spreadsheet order) or as an object keyed
    // by column; dataTable wants the object form.
    var data = rows.map(function (row) {
      if (!Array.isArray(row)) return row;
      var out = {};
      columns.forEach(function (column, index) {
        out[column.key || String(index)] = row[index];
      });
      return out;
    });

    var box = make("div", "doc-exhibit");
    if (spec.title) box.appendChild(make("p", "doc-exhibit__title", spec.title));
    var tableHost = make("div");
    box.appendChild(tableHost);
    host.appendChild(box);
    try {
      charts.dataTable(tableHost, columns, data, {
        caption: spec.caption || spec.title || "Veri tablosu",
        note: spec.note,
        sort: spec.sort
      });
    } catch (err) {
      tableHost.appendChild(make("p", "chart-empty", "Tablo çizilemedi."));
    }
  }

  /** A section's chart spec. An unknown type draws nothing, never throws. */
  function mountSectionChart(host, spec) {
    if (!spec || typeof spec !== "object") return;
    var builders = {
      line: charts.lineChart,
      bar: charts.barChart,
      donut: charts.donutChart,
      sparkline: charts.sparkline,
      heatmap: charts.heatmap
    };
    var builder = builders[String(spec.type || "").toLowerCase()];
    if (!builder) return;

    var box = make("div", "doc-exhibit");
    if (spec.title) box.appendChild(make("p", "doc-exhibit__title", spec.title));
    var plot = make("div", "chart");
    box.appendChild(plot);
    host.appendChild(box); // in the DOM first: the v2 builders measure it
    try {
      builder(plot, spec.data, spec.options || {});
    } catch (err) {
      plot.innerHTML = "";
      plot.appendChild(make("p", "chart-empty", "Grafik çizilemedi."));
    }
    if (spec.caption) box.appendChild(make("p", "doc-exhibit__caption", spec.caption));
  }

  function renderDocBody(doc) {
    var host = $("doc-body");
    host.innerHTML = "";
    var sections = docList(doc, "sections");

    if (!sections.length) {
      // Schema 1, or an advisor that wrote nothing but prose. The lead above
      // already shows the headline, so a schema 1 blob that opens with the
      // same explicit marker line must not print that sentence twice.
      var prose = make("div", "doc-prose");
      var raw = doc.markdown || "";
      if (doc.headline) raw = stripLeadingHeadlineLine(raw);
      prose.innerHTML = renderMarkdown(raw);
      host.appendChild(prose);
      return;
    }

    sections.forEach(function (section) {
      if (!section || typeof section !== "object") return;
      var block = make("section", "doc-section");
      if (section.title) {
        block.appendChild(make("h2", "doc-section__title", section.title));
      }
      if (section.body) {
        var body = make("div", "doc-prose");
        body.innerHTML = renderMarkdown(section.body);
        block.appendChild(body);
      }
      host.appendChild(block);
      mountSectionTable(block, section.table);
      mountSectionChart(block, section.chart);
    });
  }

  function renderDocActions(doc) {
    var block = $("doc-actions");
    var host = $("doc-actions-list");
    host.innerHTML = "";
    var items = docList(doc, "action_items");
    if (!items.length) {
      show(block, false);
      return;
    }
    show(block, true);
    items.forEach(function (item) {
      if (!item || !item.text) return;
      var li = make("li", "checklist__item");
      var box = make("span", "checklist__box", "☐");
      box.setAttribute("aria-hidden", "true");
      li.appendChild(box);

      var body = make("div", "checklist__body");
      body.appendChild(make("p", "checklist__text", item.text));
      if (item.deadline || item.owner) {
        var badges = make("p", "checklist__badges");
        if (item.deadline) {
          badges.appendChild(
            make("span", "badge badge--deadline", "📅 " + item.deadline)
          );
        }
        if (item.owner) {
          badges.appendChild(make("span", "badge badge--owner", "👤 " + item.owner));
        }
        body.appendChild(badges);
      }
      li.appendChild(body);
      host.appendChild(li);
    });
  }

  function renderDocSources(doc) {
    var block = $("doc-sources");
    var host = $("doc-sources-list");
    host.innerHTML = "";
    var sources = docList(doc, "sources");
    var drawn = 0;
    sources.forEach(function (source) {
      if (!source || !source.url) return;
      var href = safeUrl(source.url);
      if (!href) return; // only http(s)/mailto ever becomes clickable
      var li = make("li", "sourcelist__item");
      var link = make("a", "sourcelist__link", source.title || href);
      link.href = href;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      li.appendChild(link);
      if (source.note) li.appendChild(make("p", "sourcelist__note", source.note));
      li.appendChild(make("p", "sourcelist__url", href));
      host.appendChild(li);
      drawn += 1;
    });
    show(block, drawn > 0);
  }

  /** Empty every optional block, so the previous document cannot bleed in. */
  function resetDocument() {
    ["doc-metrics", "doc-actions-list", "doc-sources-list", "doc-facts"].forEach(
      function (id) {
        $(id).innerHTML = "";
      }
    );
    $("doc-body").textContent = "";
    show($("doc-metrics"), false);
    show($("doc-actions"), false);
    show($("doc-sources"), false);
    $("doc-lead").hidden = true;
    text($("doc-kicker"), "");
    text($("doc-stamp"), "");
  }

  function renderDocument(doc) {
    resetDocument();
    var meta = docMeta(doc);

    text($("doc-emoji"), doc.emoji || "📄");
    text($("doc-title"), doc.name || doc.id);
    text($("doc-kicker"), (doc.category || "rapor").toLocaleUpperCase("tr"));
    text(
      $("doc-meta"),
      prettyDate(doc.date) +
        (doc.generated_at_istanbul || meta.generated_at_istanbul
          ? " · " + (doc.generated_at_istanbul || meta.generated_at_istanbul) +
            " (İstanbul)"
          : "")
    );
    renderDocFacts(doc);

    var lead = $("doc-lead");
    if (doc.headline) {
      lead.hidden = false;
      lead.textContent = doc.headline;
    }

    renderDocMetrics(doc);
    renderDocBody(doc);
    renderDocActions(doc);
    renderDocSources(doc);

    text(
      $("doc-stamp"),
      (doc.name || doc.id) +
        " · " + prettyDate(doc.date) +
        " · AI Executive Assistant"
    );
    $("doc-back-day").href = "#/raporlar/" + doc.date;
  }

  function latestDay() {
    var days = state.archive && Array.isArray(state.archive.days) ? state.archive.days : [];
    return days.length ? days[0].date : "";
  }

  function loadArchive() {
    return fetchJson(ARCHIVE_URL)
      .then(function (archive) {
        state.archive = archive;
        return archive;
      })
      .catch(function () {
        state.archive = { days: [] };
        return state.archive;
      });
  }

  function loadDay(date) {
    if (!date) return Promise.resolve(null);
    if (state.days[date]) return Promise.resolve(state.days[date]);
    return fetchJson("./reports/" + date + "/index.json")
      .then(function (day) {
        state.days[date] = day;
        return day;
      })
      .catch(function () {
        return null;
      });
  }

  function refreshReports() {
    return loadArchive().then(function () {
      var date = latestDay();
      if (!date) {
        renderReportsList();
        renderIdeas();
        return null;
      }
      // Always re-read the newest day: an incremental run adds to it.
      delete state.days[date];
      return loadDay(date).then(function (day) {
        renderReportsList();
        renderIdeas();
        return day;
      });
    });
  }

  /* ====================================================================== */
  /* TAB 3 — 📊 Performans & Token                                          */
  /* ====================================================================== */

  function metricRuns() {
    var metrics = state.metrics;
    var runs = metrics && Array.isArray(metrics.runs) ? metrics.runs : [];
    return runs.filter(function (run) {
      return run && num(run.total_tokens) > 0;
    });
  }

  function renderRecommendations() {
    var host = $("recos");
    host.innerHTML = "";
    var tips =
      state.metrics && Array.isArray(state.metrics.recommendations)
        ? state.metrics.recommendations
        : [];
    show($("recos-empty"), tips.length === 0);

    tips.forEach(function (tip) {
      var card = make("div", "reco reco--" + (tip.severity || "info"));
      card.appendChild(
        make("span", "reco__icon", RECO_ICON[tip.severity] || RECO_ICON.info)
      );
      var body = make("div");
      var title = make("h3", "reco__title");
      title.appendChild(document.createTextNode(tip.title || ""));
      if (tip.metric) title.appendChild(make("span", "reco__metric", tip.metric));
      body.appendChild(title);
      body.appendChild(make("p", "reco__detail", tip.detail || ""));
      card.appendChild(body);
      host.appendChild(card);
    });
  }

  function renderPerformans() {
    var runs = metricRuns();
    var totals = (state.metrics && state.metrics.totals) || {};

    if (!runs.length) {
      show($("perf-empty"), true);
      show($("perf-body"), false);
      return;
    }
    show($("perf-empty"), false);
    show($("perf-body"), true);

    var last = runs[runs.length - 1];

    // The one hero figure of this view.
    text($("perf-hero"), trNumber(last.total_tokens));
    text($("perf-hero-note"), "token");
    text(
      $("perf-hero-sub"),
      (last.at_istanbul || "") + " · " + (last.mode_label || last.mode || "") +
        " · " + (last.model || "—") + " · " + (last.sections || 0) + " bölüm üretildi"
    );

    text($("perf-efficiency"), trNumber(Math.round(last.chars_per_1k_tokens || 0)));
    text($("perf-per-section"), trNumber(Math.round(last.tokens_per_section || 0)));
    text($("perf-latency"), (totals.avg_latency_seconds || 0).toFixed(0) + " sn");
    text(
      $("perf-resilience"),
      (totals.fallback_runs || 0) + " / " + (totals.retry_total || 0)
    );
    text(
      $("perf-resilience-note"),
      "yedek modele düşen çalıştırma / toplam yeniden deneme"
    );

    renderRecommendations();
    renderPerfCharts(runs, last);

    var notes = [(state.metrics && state.metrics.attribution_note) || ""];
    // Seeded history is labelled out loud, so nobody mistakes the first-publish
    // sample for a measurement.
    if (state.metrics && state.metrics.sample_note) {
      notes.push("⚠️ " + state.metrics.sample_note);
    }
    text($("attribution-note"), notes.filter(Boolean).join(" "));
  }

  function renderPerfCharts(runs, last) {
    if (!charts.splitBar) return;

    /* --- trend over recent runs -------------------------------------------
     * Token count and latency are two different scales, so they are two plots
     * and never one dual-axis chart: overlaying them would invent a
     * correlation the numbers do not contain.
     * ---------------------------------------------------------------------- */
    var recent = runs.slice(-24);

    if (charts.lineChart) {
      charts.lineChart(
        $("chart-tokens"),
        recent.map(function (run) {
          return {
            value: num(run.total_tokens),
            label: (run.at_istanbul || "") + " · " + (run.mode_label || ""),
            short: shortStamp(run)
          };
        }),
        {
          name: "Toplam token",
          aria: "Çalıştırma başına toplam token eğilimi",
          color: "var(--series-1)",
          format: function (value) {
            return trNumber(Math.round(value)) + " token";
          }
        }
      );

      charts.lineChart(
        $("chart-latency"),
        recent.map(function (run) {
          return {
            value: num(run.latency_seconds),
            label: run.at_istanbul || "",
            short: shortStamp(run)
          };
        }),
        {
          name: "Gecikme",
          aria: "Model çağrısı gecikmesi eğilimi",
          color: "var(--series-3)",
          format: function (value) {
            return Math.round(value) + " sn";
          }
        }
      );
    }

    charts.splitBar(
      $("chart-split"),
      [
        { name: "Girdi (prompt)", value: num(last.prompt_tokens), color: "var(--series-1)" },
        { name: "Çıktı (yanıt)", value: num(last.output_tokens), color: "var(--series-2)" },
        { name: "Düşünme", value: num(last.thoughts_tokens), color: "var(--series-3)" }
      ],
      {}
    );
    text(
      $("split-sub"),
      "son çalıştırma · düşünme payı %" +
        String(last.thoughts_share || 0).replace(".", ",")
    );

    var agents = aggregateAgents(runs);

    /* --- token distribution by advisor ------------------------------------
     * Part-to-whole, so a ring with the total in the middle. The builder caps
     * the ring at six slices and folds the tail into one honest "Diğer" —
     * past six the hues stop being reliably distinguishable.
     * ---------------------------------------------------------------------- */
    if (charts.donutChart) {
      var tokenTotal = agents.reduce(function (acc, row) {
        return acc + num(row.tokens);
      }, 0);
      charts.donutChart(
        $("chart-agents"),
        agents.map(function (row) {
          return { name: row.name || row.id, value: num(row.tokens) };
        }),
        {
          aria: "Ajan başına tahmini token dağılımı",
          centerValue: charts.compact ? charts.compact(tokenTotal) : String(tokenTotal),
          centerLabel: "toplam token",
          legendLabel: "Ajan dağılımı göstergesi",
          format: function (value) {
            return trNumber(Math.round(value)) + " token";
          }
        }
      );
      text(
        $("agents-donut-sub"),
        agents.length
          ? "tahmini · " + agents.length + " ajan · son " + Math.min(runs.length, 7) + " çalıştırma"
          : "tahmini"
      );
    }

    /* --- the same advisors, ranked ---------------------------------------- */
    if (charts.barChart) {
      charts.barChart(
        $("chart-agent-bars"),
        agents.map(function (row) {
          return {
            label: row.name || row.id,
            value: num(row.tokens),
            note:
              "token payı %" + String(row.token_share).replace(".", ",") +
              " · çıktı payı %" + String(row.output_share).replace(".", ",")
          };
        }),
        {
          limit: 10,
          aria: "Ajan başına tahmini token karşılaştırması",
          color: "var(--series-1)",
          format: function (value) {
            return trNumber(Math.round(value));
          }
        }
      );

      // Chars produced per 1.000 tokens spent: the "is it worth it" measure.
      // Different question, different scale — so it is its own chart.
      charts.barChart(
        $("chart-agent-efficiency"),
        agents
          .map(function (row) {
            return {
              label: row.name || row.id,
              value: num(row.tokens) ? Math.round((num(row.chars) / num(row.tokens)) * 1000) : 0,
              note: trNumber(Math.round(num(row.chars))) + " karakter · " +
                trNumber(Math.round(num(row.tokens))) + " token"
            };
          })
          .sort(function (a, b) {
            return b.value - a.value;
          }),
        {
          limit: 10,
          aria: "Ajan başına 1000 token başına üretilen karakter",
          color: "var(--series-3)",
          format: function (value) {
            return trNumber(Math.round(value)) + " kr.";
          }
        }
      );
    }

    if (charts.table) {
      charts.table(
        $("table-agents"),
        [
          { label: "Ajan" },
          { label: "Tahmini token", num: true },
          { label: "Token payı", num: true },
          { label: "Çıktı payı", num: true },
          { label: "Fark", num: true }
        ],
        agents.map(function (row) {
          return [
            row.name,
            trNumber(row.tokens),
            "%" + String(row.token_share).replace(".", ","),
            "%" + String(row.output_share).replace(".", ","),
            (row.gap > 0 ? "+" : "") + String(row.gap).replace(".", ",")
          ];
        }),
        "Ajan başına tahmini token ve çıktı payları"
      );

      charts.table(
        $("table-runs"),
        [
          { label: "Zaman" },
          { label: "Mod" },
          { label: "Girdi", num: true },
          { label: "Çıktı", num: true },
          { label: "Düşünme", num: true },
          { label: "Toplam", num: true },
          { label: "Bölüm", num: true },
          { label: "Gecikme", num: true },
          { label: "Yedek" }
        ],
        runs
          .slice()
          .reverse()
          .map(function (run) {
            return [
              run.at_istanbul || run.at || "—",
              (MODE[run.mode] || MODE.full).label,
              trNumber(run.prompt_tokens),
              trNumber(run.output_tokens),
              trNumber(run.thoughts_tokens),
              trNumber(run.total_tokens),
              run.sections || 0,
              Math.round(num(run.latency_seconds)) + " sn",
              run.fallback_used ? "⚠️ evet" : "✅ hayır"
            ];
          }),
        "Çalıştırma başına token ve gecikme"
      );
    }
  }

  /** Sum the per-run agent estimates into one table, mirroring metrics.py. */
  function aggregateAgents(runs) {
    var bucket = {};
    runs.slice(-7).forEach(function (run) {
      (run.agents || []).forEach(function (row) {
        if (!row || !row.id) return;
        var entry = bucket[row.id] || { id: row.id, name: row.name || row.id, tokens: 0, chars: 0 };
        entry.tokens += num(row.est_total_tokens);
        entry.chars += num(row.output_chars);
        if (row.name) entry.name = row.name;
        bucket[row.id] = entry;
      });
    });

    var rows = Object.keys(bucket).map(function (key) {
      return bucket[key];
    });
    var tokenTotal = rows.reduce(function (acc, row) {
      return acc + row.tokens;
    }, 0);
    var charTotal = rows.reduce(function (acc, row) {
      return acc + row.chars;
    }, 0);

    rows.forEach(function (row) {
      row.token_share = tokenTotal ? Math.round((row.tokens / tokenTotal) * 1000) / 10 : 0;
      row.output_share = charTotal ? Math.round((row.chars / charTotal) * 1000) / 10 : 0;
      row.gap = Math.round((row.token_share - row.output_share) * 10) / 10;
    });
    rows.sort(function (a, b) {
      return b.tokens - a.tokens;
    });
    return rows;
  }

  /* ====================================================================== */
  /* TAB 4 — ✅ İşler & Takip                                               */
  /* ====================================================================== */

  function renderIsler() {
    var acc = (state.status && state.status.accountability) || {};
    var tasks = Array.isArray(acc.tasks) ? acc.tasks : [];

    if (!acc.available || (!tasks.length && !acc.streak)) {
      show($("isler-empty"), true);
      show($("isler-body"), false);
      return;
    }
    show($("isler-empty"), false);
    show($("isler-body"), true);

    text($("streak-value"), acc.streak || 0);
    text($("task-count"), tasks.length || acc.today_task_count || 0);
    text($("task-days"), acc.history_days || 0);
    text($("task-last"), acc.last_date ? "son kayıt " + acc.last_date : "");

    var host = $("task-list");
    host.innerHTML = "";

    if (!tasks.length) {
      // A status file written before the task list was published still knows
      // the COUNT. Say so plainly rather than showing an empty box that looks
      // broken.
      host.appendChild(
        make(
          "p",
          "chart-empty",
          acc.today_task_count
            ? acc.today_task_count +
                " görev kayıtlı, ancak listesi bu çalıştırmada yayınlanmamış. " +
                "Bir sonraki tam brifingden sonra maddeler burada görünecek."
            : "Bugün için görev üretilmedi."
        )
      );
    }

    tasks.forEach(function (task, index) {
      var row = make("div", "task");
      row.appendChild(make("span", "task__num", index + 1));

      var body = make("div", "task__body");
      // The coach writes "*Advisor Title* — the task".
      var match = /^\*(.+?)\*\s*[—-]\s*([\s\S]*)$/.exec(task);
      if (match) {
        body.appendChild(make("span", "task__owner", match[1]));
        body.appendChild(make("p", "task__text", match[2]));
      } else {
        body.appendChild(make("p", "task__text", task));
      }
      row.appendChild(body);
      host.appendChild(row);
    });

    var badge = $("badge-isler");
    if (tasks.length) {
      badge.hidden = false;
      badge.className = "tab__badge";
      badge.textContent = String(tasks.length);
    } else {
      badge.hidden = true;
    }
  }

  /* ====================================================================== */
  /* TAB 5 — 💡 Öneriler & Fikirler                                         */
  /* ====================================================================== */

  function renderIdeas() {
    var date = latestDay();
    var day = state.days[date];
    var entries = day && Array.isArray(day.reports) ? day.reports : [];
    // Take the first id that the day actually published: the current key wins,
    // and an archived day from before the rename still resolves.
    var card = entries.filter(function (entry) {
      return INNOVATION_IDS.indexOf(entry.id) !== -1;
    })[0];

    if (!card) {
      show($("fikirler-empty"), true);
      show($("fikirler-body"), false);
      return;
    }
    var id = card.id;

    show($("fikirler-empty"), false);
    show($("fikirler-body"), true);
    text(
      $("fikirler-note"),
      prettyDate(date) + " · " + (card.headline || "") +
        " · ⏱️ ~" + (card.read_minutes || 1) + " dk okuma"
    );
    $("fikirler-link").href = "#/rapor/" + date + "/" + id;

    var key = date + "/" + id;
    if (state.docs[key]) {
      $("fikirler-body-text").innerHTML = renderMarkdown(state.docs[key].markdown || "");
      return;
    }
    fetchJson("./reports/" + date + "/" + id + ".json")
      .then(function (doc) {
        state.docs[key] = doc;
        $("fikirler-body-text").innerHTML = renderMarkdown(doc.markdown || "");
      })
      .catch(function () {
        $("fikirler-body-text").textContent =
          "Öneri belgesi okunamadı. Tam raporu açmayı deneyebilirsin.";
      });
  }

  /* ====================================================================== */
  /* TAB 6 — 🔗 İntegrasyonlar & Bağlantılar                                */
  /* ====================================================================== */

  function renderIntegrationCard(title, emoji, items, color) {
    var card = make("div", "integration-card integration-card--" + color);
    var head = make("div", "integration-card__head");
    head.appendChild(make("span", "integration-card__emoji", emoji));
    head.appendChild(make("h3", "integration-card__title", title));
    card.appendChild(head);

    var body = make("div", "integration-card__body");
    items.forEach(function (item) {
      var row = make("div", "integration-item");
      row.appendChild(make("span", "integration-item__label", item.label));
      row.appendChild(make("span", "integration-item__value", item.value));
      if (item.status) {
        row.appendChild(make("span", "integration-item__status integration-item__status--" + item.status,
          item.status === "ok" ? "✓" : (item.status === "warning" ? "⚠" : "✗")));
      }
      body.appendChild(row);
    });
    card.appendChild(body);
    return card;
  }

  function renderEntegrasyonlar() {
    var data = state.status;
    if (!data) return;

    var integrations = (data.integrations || {});
    var slack = integrations.slack || {};
    var asana = integrations.asana || {};
    var drive = integrations.drive || {};
    var distribution = integrations.distribution || {};

    var host = $("integrations-grid");
    host.innerHTML = "";

    // Slack Channels
    var slackItems = [
      {
        label: "Yapılandırılmış kanallar",
        value: slack.configured_channels || "0"
      },
      {
        label: "Son ileti",
        value: slack.last_post ? relativeTime(slack.last_post) : "Hiçbir zaman",
        status: (slack.failures && slack.failures.length) ? "error" : "ok"
      }
    ];
    if (slack.failures && slack.failures.length) {
      slackItems.push({
        label: "Hatalar",
        value: slack.failures.join(", "),
        status: "error"
      });
    }
    host.appendChild(renderIntegrationCard("Slack Kanalları", "💬", slackItems, "slack"));

    // Asana Projects
    var asanaItems = [
      {
        label: "Aktif projeler",
        value: asana.projects || "0"
      },
      {
        label: "Toplam görev",
        value: asana.tasks || "0"
      },
      {
        label: "Son güncelleme",
        value: asana.last_update ? relativeTime(asana.last_update) : "—",
        status: (asana.failures && asana.failures.length) ? "error" : "ok"
      }
    ];
    if (asana.workspace_url) {
      asanaItems.push({
        label: "Çalışma alanı",
        value: "Asana'da aç"
      });
    }
    if (asana.failures && asana.failures.length) {
      asanaItems.push({
        label: "Hatalar",
        value: asana.failures.join(", "),
        status: "error"
      });
    }
    host.appendChild(renderIntegrationCard("Asana Projeleri", "📌", asanaItems, "asana"));

    // Google Drive
    var driveItems = [
      {
        label: "Toplam belgeler",
        value: drive.total_docs || "0"
      },
      {
        label: "Arşiv belgeleri",
        value: (drive.archive_docs || "0") + " / " + (drive.total_docs || "0")
      },
      {
        label: "Son senkronizasyon",
        value: drive.last_sync ? relativeTime(drive.last_sync) : "—",
        status: (drive.failures && drive.failures.length) ? "error" : "ok"
      }
    ];
    if (drive.folder_size) {
      driveItems.push({
        label: "Klasör boyutu",
        value: drive.folder_size
      });
    }
    if (drive.failures && drive.failures.length) {
      driveItems.push({
        label: "Hatalar",
        value: drive.failures.join(", "),
        status: "error"
      });
    }
    host.appendChild(renderIntegrationCard("Google Drive", "📁", driveItems, "drive"));

    // Distribution Status
    var distItems = [
      {
        label: "Toplam dağıtım",
        value: distribution.total_attempts || "0"
      },
      {
        label: "Başarılı",
        value: distribution.success_count || "0",
        status: "ok"
      },
      {
        label: "Başarısız",
        value: distribution.failure_count || "0",
        status: (distribution.failure_count && distribution.failure_count > 0) ? "error" : "ok"
      }
    ];
    if (distribution.failed_advisors && distribution.failed_advisors.length) {
      distItems.push({
        label: "Başarısız ajanlar",
        value: distribution.failed_advisors.join(", "),
        status: "error"
      });
    }
    if (distribution.last_attempt) {
      distItems.push({
        label: "Son deneme",
        value: relativeTime(distribution.last_attempt)
      });
    }
    host.appendChild(renderIntegrationCard("Dağıtım Durumu", "📤", distItems, "distribution"));

    show($("entegrasyonlar-empty"), false);
    show($("entegrasyonlar-body"), true);
  }

  /* ====================================================================== */
  /* TAB 7 — 📧 Gmail & Takvim                                              */
  /* ====================================================================== */

  function renderGmailCalendar() {
    var data = state.status;
    if (!data) return;

    var gmail = (data.gmail || {});
    var calendar = (data.calendar || {});
    var hasData = gmail.unread_count != null || calendar.today_meetings != null;

    if (!hasData) {
      show($("gmail-empty"), true);
      show($("gmail-body"), false);
      return;
    }
    show($("gmail-empty"), false);
    show($("gmail-body"), true);

    // --- Gmail Stats ---
    text($("gmail-unread"), gmail.unread_count || 0);
    text($("gmail-total-24h"), gmail.total_emails_24h || 0);
    text($("gmail-urgent"), gmail.urgent_count || 0);
    text($("gmail-action-items"), gmail.action_items || 0);
    text($("gmail-vip-count"), (gmail.vip_emails && gmail.vip_emails.length) || 0);

    // --- Calendar Stats ---
    text($("calendar-today-meetings"), calendar.today_meetings || 0);
    text($("calendar-total-time"), calendar.total_meeting_time_hours != null
      ? calendar.total_meeting_time_hours.toFixed(1) + " sa"
      : "—");
    text($("calendar-focus-blocks"), calendar.focus_blocks || 0);

    // Next meeting display
    var nextMeetingContainer = $("calendar-next-meeting-container");
    var nextMeetingEl = $("calendar-next-meeting");
    if (nextMeetingEl) {
      if (calendar.next_meeting) {
        nextMeetingEl.textContent = calendar.next_meeting;
        if (nextMeetingContainer) nextMeetingContainer.hidden = false;
      } else {
        if (nextMeetingContainer) nextMeetingContainer.hidden = true;
      }
    }

    // Available slots display
    var slotsContainer = $("calendar-available-slots");
    slotsContainer.innerHTML = "";
    if (calendar.available_slots && Array.isArray(calendar.available_slots)) {
      if (calendar.available_slots.length > 0) {
        calendar.available_slots.forEach(function (slot) {
          var badge = make("span", "badge badge--calendar", slot);
          slotsContainer.appendChild(badge);
        });
      } else {
        slotsContainer.textContent = "Boş slot yok";
      }
    } else {
      slotsContainer.textContent = "—";
    }

    // --- Recent Emails ---
    var emailsList = $("gmail-recent-emails");
    emailsList.innerHTML = "";
    if (gmail.vip_emails && Array.isArray(gmail.vip_emails)) {
      gmail.vip_emails.slice(0, 5).forEach(function (email) {
        var row = make("div", "gmail-email-row");

        var from = make("div", "gmail-email-from");
        from.textContent = email.from || "—";
        row.appendChild(from);

        var subject = make("div", "gmail-email-subject");
        subject.textContent = email.subject || "(Konu yok)";
        if (email.urgent) {
          subject.appendChild(make("span", "badge badge--urgent", "🔴 ACIL"));
        } else if (email.important) {
          subject.appendChild(make("span", "badge badge--important", "⭐ ÖNEMLİ"));
        }
        row.appendChild(subject);

        var time = make("div", "gmail-email-time");
        time.textContent = email.time || "—";
        row.appendChild(time);

        emailsList.appendChild(row);
      });
    }

    // Update last sync time
    if (gmail.last_update || calendar.last_update) {
      var lastUpdate = gmail.last_update || calendar.last_update;
      text($("gmail-last-update"), "Son güncelleme: " + relativeTime(lastUpdate));
    }
  }

  /* ====================================================================== */
  /* TAB 8 — 📊 Performans & Analiz                                         */
  /* ====================================================================== */

  function renderTrendArrow(current, previous) {
    if (previous === null || previous === undefined) return "→";
    var diff = current - previous;
    if (diff > 0.5) return "↑";
    if (diff < -0.5) return "↓";
    return "→";
  }

  /**
   * A metric card, optionally with its own history riding underneath it.
   *
   * `spark` is the raw 7-day series (or null). The sparkline is appended AFTER
   * the card is in the DOM by the caller — charts.sparkline measures its host,
   * so drawing into a detached node would size it against nothing.
   *
   * `literal` prints the value EXACTLY as given. The dashboard's own metrics
   * arrive from toFixed() and want the Turkish decimal comma; a report's
   * metric is a string the advisor wrote ("1.250", "23°C") and re-punctuating
   * it would corrupt it.
   */
  function renderMetricCard(label, value, unit, trend, spark, color, literal) {
    var card = make("div", "metric-card");
    var head = make("div", "metric-card__head");
    head.appendChild(make("span", "metric-card__label", label));
    if (trend) {
      head.appendChild(make("span", "metric-card__trend", trend));
    }
    card.appendChild(head);

    var body = make("div", "metric-card__body");
    body.appendChild(
      make(
        "span",
        "metric-card__value",
        literal ? String(value) : String(value).replace(".", ",")
      )
    );
    if (unit) {
      body.appendChild(make("span", "metric-card__unit", unit));
    }
    card.appendChild(body);

    if (charts.sparkline && Array.isArray(spark) && spark.length >= 2) {
      var host = make("div", "metric-card__spark");
      card.appendChild(host);
      card.__aiaSpark = function () {
        charts.sparkline(host, spark, {
          name: label,
          color: color || "var(--series-1)",
          digits: 1,
          height: 34
        });
      };
    }
    return card;
  }

  /** Append a metric card and draw its sparkline once it can measure itself. */
  function mountMetricCard(host, card) {
    host.appendChild(card);
    if (card.__aiaSpark) card.__aiaSpark();
  }

  function renderAlertItem(severity, message) {
    var item = make("div", "alert-item alert-item--" + severity);
    var icon = make("span", "alert-item__icon",
      severity === "critical" ? "🔴" :
      severity === "warning" ? "🟠" :
      severity === "info" ? "🟡" : "🟢");
    item.appendChild(icon);
    item.appendChild(make("span", "alert-item__text", message));
    return item;
  }

  /* The 7-day series a metric card rides on. `trends` is written by the Python
   * side as { completion_7d: [...], deadline_7d: [...], success_7d: [...] };
   * anything else falls back to "<key>_7d", so a new metric picks its own
   * history up without a change here. */
  function trendSeries(trends, key, explicit) {
    var raw = trends[explicit || key + "_7d"];
    if (!Array.isArray(raw)) return null;
    var values = raw
      .map(function (v) {
        return typeof v === "object" && v ? Number(v.value) : Number(v);
      })
      .filter(function (v) {
        return isFinite(v);
      });
    return values.length >= 2 ? values : null;
  }

  var TREND_SERIES = [
    { key: "completion_7d", name: "Tamamlanma", color: "var(--series-1)" },
    { key: "deadline_7d", name: "Tarih uyumu", color: "var(--series-2)" },
    { key: "success_7d", name: "Başarı", color: "var(--series-3)" }
  ];

  /**
   * The 7-day rates as one multi-series line.
   *
   * All three are per cent, which is the ONLY reason they share a plot — a
   * common unit is what makes a single y-axis honest. The crosshair reads all
   * three at the same day, which is the whole point of stacking them here.
   */
  function renderTrendChart(trends) {
    var host = $("chart-trends-7d");
    if (!host) return;
    if (!charts.lineChart) {
      host.textContent = "Veri yok.";
      return;
    }

    var longest = 0;
    var series = TREND_SERIES.map(function (spec) {
      var values = trendSeries(trends || {}, spec.key, spec.key);
      if (!values) return null;
      longest = Math.max(longest, values.length);
      return { spec: spec, values: values };
    }).filter(Boolean);

    // Days are labelled backwards from today: the last reading is "bugün".
    function dayLabel(index, length) {
      var back = length - 1 - index;
      if (back === 0) return { short: "bugün", label: "bugün" };
      if (back === 1) return { short: "dün", label: "dün" };
      var d = new Date();
      d.setDate(d.getDate() - back);
      var short = pad2(d.getDate()) + "." + pad2(d.getMonth() + 1);
      return { short: short, label: short + " (" + back + " gün önce)" };
    }

    charts.lineChart(
      host,
      series.map(function (item) {
        return {
          name: item.spec.name,
          color: item.spec.color,
          points: item.values.map(function (value, index) {
            var stamp = dayLabel(index, item.values.length);
            return { value: value, label: stamp.label, short: stamp.short };
          })
        };
      }),
      {
        aria: "Son 7 günün tamamlanma, tarih uyumu ve başarı oranları",
        legendLabel: "Eğilim göstergesi",
        single: "Eğilim için en az iki günlük ölçüm gerekiyor.",
        format: function (value) {
          return "%" + trDecimal(value, 1);
        }
      }
    );

    text(
      $("trends-sub"),
      series.length ? "son " + longest + " gün · %" : "son 7 gün · %"
    );
  }

  function renderPerformance() {
    var data = state.status;
    if (!data) return;

    var perf = (data.performance || {});
    var daily = (perf.daily_metrics || {});
    var work = (perf.work_status || {});
    var trends = (perf.trends || {});
    var alerts = Array.isArray(perf.alerts) ? perf.alerts : [];
    var feedback = perf.feedback || "";

    var hasData = Object.keys(daily).length > 0 || Object.keys(work).length > 0;

    if (!hasData) {
      show($("analiz-empty"), true);
      show($("analiz-body"), false);
      return;
    }
    show($("analiz-empty"), false);
    show($("analiz-body"), true);

    // === DAILY METRICS ===
    var dailyHost = $("daily-metrics");
    dailyHost.innerHTML = "";

    // Each card carries its own 7-day history, so the single number is read
    // against where it came from instead of on its own.
    var metricsList = [
      { key: "completion_rate", label: "Tamamlanma Oranı", unit: "%", spark: "completion_7d", color: "var(--series-1)" },
      { key: "deadline_adherence", label: "Tarih Uyumu", unit: "%", spark: "deadline_7d", color: "var(--series-2)" },
      { key: "success_rate", label: "Başarı Oranı", unit: "%", spark: "success_7d", color: "var(--series-3)" },
      { key: "token_efficiency", label: "Token Verimliği", unit: "token/çıktı", color: "var(--series-4)" }
    ];

    metricsList.forEach(function (metric) {
      var value = daily[metric.key];
      if (value == null || !isFinite(Number(value))) return;
      var trend = renderTrendArrow(Number(value), daily[metric.key + "_prev"] != null ? Number(daily[metric.key + "_prev"]) : null);
      mountMetricCard(
        dailyHost,
        renderMetricCard(
          metric.label,
          Number(value).toFixed(1),
          metric.unit,
          trend,
          trendSeries(trends, metric.key, metric.spark),
          metric.color
        )
      );
    });

    // === WORK STATUS ===
    var workHost = $("work-status");
    workHost.innerHTML = "";

    var workList = [
      { key: "meeting_hours", label: "Toplantı Saati", unit: "sa" },
      { key: "focus_time_hours", label: "Odak Zamanı", unit: "sa" },
      { key: "email_response_time", label: "E-posta Yanıt", unit: "sa" }
    ];

    workList.forEach(function (item) {
      var value = work[item.key];
      if (value == null || !isFinite(Number(value))) return;
      mountMetricCard(
        workHost,
        renderMetricCard(
          item.label,
          Number(value).toFixed(1),
          item.unit,
          null,
          trendSeries(trends, item.key, item.spark),
          item.color || "var(--series-5)"
        )
      );
    });

    // Add alert count if available
    if (alerts.length > 0) {
      var alertCount = alerts.filter(function (a) { return a.severity === "critical"; }).length;
      if (alertCount > 0) {
        mountMetricCard(workHost, renderMetricCard("Kritik Uyarı", alertCount, "adet"));
      }
    }

    // === TRENDS (7 days, three rates, one axis) ===
    renderTrendChart(trends);

    // === ALERTS PANEL ===
    var alertsHost = $("alerts-panel");
    alertsHost.innerHTML = "";

    if (alerts.length > 0) {
      // Group alerts by severity
      var critical = alerts.filter(function (a) { return a.severity === "critical"; });
      var warning = alerts.filter(function (a) { return a.severity === "warning"; });
      var info = alerts.filter(function (a) { return a.severity === "info"; });
      var success = alerts.filter(function (a) { return a.severity === "success"; });

      // Render alerts grouped by severity
      critical.forEach(function (alert) {
        alertsHost.appendChild(renderAlertItem("critical", alert.message || alert.title || "Kritik uyarı"));
      });
      warning.forEach(function (alert) {
        alertsHost.appendChild(renderAlertItem("warning", alert.message || alert.title || "Uyarı"));
      });
      info.forEach(function (alert) {
        alertsHost.appendChild(renderAlertItem("info", alert.message || alert.title || "Bilgi"));
      });
      success.forEach(function (alert) {
        alertsHost.appendChild(renderAlertItem("success", alert.message || alert.title || "Başarı"));
      });
    } else {
      alertsHost.appendChild(make("p", "chart-empty", "Uyarı veya ileti yok — hepsi normal!"));
    }

    // === DAILY FEEDBACK ===
    if (feedback) {
      text($("feedback-text"), feedback);
      show($("feedback-section"), true);
    } else {
      show($("feedback-section"), false);
    }
  }

  /* ====================================================================== */
  /* routing                                                                */
  /* ====================================================================== */

  function parseRoute() {
    var raw = (window.location.hash || "").replace(/^#\/?/, "");
    var parts = raw.split("/").filter(Boolean).map(decodeURIComponent);
    if (!parts.length) return { name: "tab", tab: DEFAULT_TAB };

    if (parts[0] === "raporlar") {
      if (parts[1] && DATE_RE.test(parts[1])) {
        return { name: "day", tab: "icerik", date: parts[1] };
      }
      return { name: "archive", tab: "icerik" };
    }
    if (
      parts[0] === "rapor" &&
      DATE_RE.test(parts[1] || "") &&
      ID_RE.test(parts[2] || "")
    ) {
      return { name: "report", tab: "icerik", date: parts[1], id: parts[2] };
    }
    if (TABS.indexOf(parts[0]) !== -1) return { name: "tab", tab: parts[0] };
    return { name: "tab", tab: DEFAULT_TAB };
  }

  function selectTab(name) {
    state.tab = name;
    TABS.forEach(function (tab) {
      var button = $("tab-" + tab);
      var panel = $("panel-" + tab);
      var active = tab === name;
      if (button) {
        button.setAttribute("aria-selected", active ? "true" : "false");
        button.tabIndex = active ? 0 : -1;
      }
      if (panel) panel.hidden = !active;
    });
  }

  /** Inside the İçerik tab, choose between list / doc / archive / day. */
  function showContentView(view) {
    ["list", "doc", "archive", "day"].forEach(function (name) {
      show($("icerik-" + name), name === view);
    });
  }

  function routeToReport(route) {
    showContentView("doc");
    var key = route.date + "/" + route.id;
    if (state.docs[key]) {
      renderDocument(state.docs[key]);
      return;
    }
    resetDocument();
    text($("doc-title"), "Yükleniyor…");
    fetchJson("./reports/" + route.date + "/" + route.id + ".json")
      .then(function (doc) {
        state.docs[key] = doc;
        renderDocument(doc);
      })
      .catch(function (error) {
        resetDocument();
        text($("doc-emoji"), "⚠️");
        text($("doc-title"), "Rapor bulunamadı");
        text($("doc-meta"), "");
        $("doc-body").textContent =
          "Bu rapor okunamadı (" +
          (error && error.message ? error.message : "bilinmeyen hata") +
          "). Arşivden başka bir gün deneyebilirsin.";
        $("doc-back-day").href = "#/raporlar";
      });
  }

  function routeToDay(route) {
    showContentView("day");
    text($("day-title"), prettyDate(route.date));
    var host = $("day-grid");
    host.innerHTML = "";
    text($("day-note"), "Yükleniyor…");
    loadDay(route.date).then(function (day) {
      var entries = day && Array.isArray(day.reports) ? day.reports : [];
      text(
        $("day-note"),
        entries.length
          ? entries.length + " rapor · " + (day.generated_at_istanbul || "")
          : "Bu güne ait rapor bulunamadı."
      );
      entries.forEach(function (entry) {
        host.appendChild(reportCard(entry, route.date));
      });
    });
  }

  function applyRoute() {
    var route = parseRoute();
    var changed = state.route.name !== route.name || state.route.tab !== route.tab;
    state.route = route;
    selectTab(route.tab);

    if (route.name === "report") routeToReport(route);
    else if (route.name === "day") routeToDay(route);
    else if (route.name === "archive") {
      showContentView("archive");
      loadArchive().then(renderArchive);
    } else {
      showContentView("list");
    }

    if (changed && route.name !== "tab") window.scrollTo(0, 0);
  }

  /* ====================================================================== */
  /* freshness                                                              */
  /* ====================================================================== */

  function updateFreshness() {
    var data = state.status;
    var banner = $("stale-banner");
    if (!data || !data.generated_at) {
      banner.hidden = true;
      return;
    }

    var age = Date.now() - Date.parse(data.generated_at);
    var stale = !isNaN(age) && age > STALE_HOURS * 3600 * 1000;
    var veryStale = !isNaN(age) && age > 26 * 3600 * 1000;

    banner.hidden = !stale;
    banner.className = "banner" + (veryStale ? " banner--critical" : "");
    if (stale) {
      text(
        $("stale-text"),
        "⚠️ Veri eski görünüyor — son çalıştırma " +
          relativeTime(data.generated_at) + " (" +
          (data.generated_at_istanbul || data.generated_at) + ", İstanbul). " +
          (veryStale
            ? "Planlı çalıştırma bir günden uzun süredir gelmedi."
            : "Yayın gecikmiş ya da çalıştırma atlanmış olabilir.")
      );
    }

    $("live-dot").classList.toggle("live--stale", stale);
    $("live-dot").title = stale
      ? "Son veri " + STALE_HOURS + " saatten eski — planlı çalıştırma gecikmiş olabilir."
      : "Her 60 saniyede bir otomatik yenilenir";
  }

  /* ====================================================================== */
  /* tooltip                                                                */
  /* ====================================================================== */

  function initTooltip() {
    var tip = $("tooltip");

    function place(target) {
      tip.hidden = false;
      tip.textContent = target.dataset.tip;
      var rect = target.getBoundingClientRect();
      var top = rect.top - tip.offsetHeight - 8;
      tip.style.top = (top < 8 ? rect.bottom + 8 : top) + "px";
      var left = rect.left + rect.width / 2 - tip.offsetWidth / 2;
      tip.style.left =
        Math.max(8, Math.min(left, window.innerWidth - tip.offsetWidth - 8)) + "px";
    }

    function onShow(event) {
      var target = event.target.closest ? event.target.closest("[data-tip]") : null;
      if (!target || !target.dataset.tip) return;
      place(target);
    }

    function hide() {
      tip.hidden = true;
    }

    document.addEventListener("mouseover", onShow);
    document.addEventListener("mouseout", hide);
    document.addEventListener("focusin", onShow);
    document.addEventListener("focusout", hide);
    window.addEventListener("scroll", hide, { passive: true });
  }

  /* ====================================================================== */
  /* loading                                                                */
  /* ====================================================================== */

  function renderCharts() {
    // Called on load and whenever the theme changes (the charts read their
    // colours from CSS custom properties).
    if (state.status) renderHistory(Array.isArray(state.status.history) ? state.status.history : []);
    if (state.metrics) renderPerformans();
    if (state.status) renderPerformance();
  }

  function renderAll() {
    state.loaded = true;
    renderSistem();
    renderPerformans();
    renderIsler();
    renderEntegrasyonlar();
    renderGmailCalendar();
    renderPerformance();
    updateFreshness();
  }

  function showStatusError(error) {
    show($("sistem-state"), false);
    show($("sistem-body"), false);
    show($("sistem-error"), true);
    var missing = error && (error.message === "HTTP 404" || error.message === "empty");
    text(
      $("sistem-error-title"),
      missing ? "Henüz veri yok" : "Durum dosyası okunamadı"
    );
    text(
      $("sistem-error-text"),
      missing
        ? "status.json henüz oluşturulmamış. Brifing bir kez çalıştığında " +
            "(İstanbul saatiyle 10:00 / 14:00 / 18:00 / 22:00) bu pano dolacak."
        : "status.json alınamadı: " +
            (error && error.message ? error.message : "bilinmeyen hata")
    );
  }

  function load(manual) {
    var button = $("refresh");
    if (manual) button.dataset.busy = "true";

    Promise.all([
      fetchJson(STATUS_URL).catch(function (error) {
        return { __error: error };
      }),
      fetchOptional(METRICS_URL),
      fetchOptional(HEALTH_URL)
    ])
      .then(function (results) {
        state.lastFetch = new Date().toISOString();
        state.metrics = results[1];
        state.health = results[2];

        if (results[0] && results[0].__error) {
          // Keep showing the last good data; only freshness changes.
          if (!state.status) showStatusError(results[0].__error);
          else updateFreshness();
        } else {
          state.status = results[0];
        }
        if (state.status) renderAll();
        else {
          renderPerformans();
          renderIsler();
        }
      })
      .then(function () {
        button.dataset.busy = "false";
        return refreshReports();
      })
      .catch(function () {
        button.dataset.busy = "false";
      });
  }

  /* ====================================================================== */
  /* init                                                                   */
  /* ====================================================================== */

  function initTabs() {
    var list = $("tablist");
    list.addEventListener("click", function (event) {
      var button = event.target.closest ? event.target.closest(".tab") : null;
      if (!button) return;
      window.location.hash = "#/" + button.dataset.tab;
    });

    // Left/right arrows move between tabs, Home/End jump to the ends.
    list.addEventListener("keydown", function (event) {
      var index = TABS.indexOf(state.tab);
      var next = null;
      if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
      else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = TABS.length - 1;
      if (next === null) return;
      event.preventDefault();
      window.location.hash = "#/" + TABS[next];
      var button = $("tab-" + TABS[next]);
      if (button) button.focus();
    });
  }

  function init() {
    applyTheme(currentTheme());
    initTooltip();
    initTabs();

    $("theme-toggle").addEventListener("click", function () {
      applyTheme(currentTheme() === "light" ? "dark" : "light");
    });

    $("refresh").addEventListener("click", function () {
      load(true);
    });

    $("report-search").addEventListener("input", function (event) {
      state.search = event.target.value || "";
      renderReportsList();
    });

    // The browser's own print dialog is the PDF export: `@media print` in
    // styles.css strips the shell and lays the article out for paper.
    $("doc-print").addEventListener("click", function () {
      window.print();
    });

    window.addEventListener("hashchange", applyRoute);
    applyRoute();
    load(false);

    setInterval(function () {
      load(false);
    }, REFRESH_MS);
    setInterval(updateFreshness, CLOCK_MS);
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) load(false);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
