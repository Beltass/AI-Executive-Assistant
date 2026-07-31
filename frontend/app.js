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

  var TABS = ["sistem", "icerik", "performans", "isler", "fikirler", "entegrasyonlar", "gmail"];
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

  var INNOVATION_ID = "innovation_lab";

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

  function renderDocument(doc) {
    text($("doc-emoji"), doc.emoji || "📄");
    text($("doc-title"), doc.name || doc.id);
    text(
      $("doc-meta"),
      prettyDate(doc.date) +
        " · " + (doc.category || "—") +
        " · ⏱️ ~" + (doc.read_minutes || 1) + " dk okuma"
    );
    var lead = $("doc-lead");
    if (doc.headline) {
      lead.hidden = false;
      lead.textContent = doc.headline;
    } else {
      lead.hidden = true;
    }
    // The ONLY innerHTML with model-generated input in this file, and it went
    // through renderMarkdown(), which escapes before it marks up.
    $("doc-body").innerHTML = renderMarkdown(doc.markdown || "");
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
    if (!charts.trend) return;

    var points = runs.map(function (run) {
      return {
        value: num(run.total_tokens),
        label: (run.at_istanbul || "") + " · " + (run.mode_label || ""),
        short: shortStamp(run)
      };
    });
    charts.trend($("chart-tokens"), points, {
      name: "Toplam token",
      unit: "",
      color: "var(--series-1)"
    });

    charts.trend(
      $("chart-latency"),
      runs.map(function (run) {
        return {
          value: num(run.latency_seconds),
          label: run.at_istanbul || "",
          short: shortStamp(run)
        };
      }),
      {
        name: "Gecikme",
        unit: "sn",
        color: "var(--series-3)",
        format: function (value) {
          return Math.round(value) + " sn";
        }
      }
    );

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
    charts.groupedShares($("chart-agents"), agents, { limit: 10 });

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
    var card = entries.filter(function (entry) {
      return entry.id === INNOVATION_ID;
    })[0];

    if (!card) {
      show($("fikirler-empty"), true);
      show($("fikirler-body"), false);
      return;
    }

    show($("fikirler-empty"), false);
    show($("fikirler-body"), true);
    text(
      $("fikirler-note"),
      prettyDate(date) + " · " + (card.headline || "") +
        " · ⏱️ ~" + (card.read_minutes || 1) + " dk okuma"
    );
    $("fikirler-link").href = "#/rapor/" + date + "/" + INNOVATION_ID;

    var key = date + "/" + INNOVATION_ID;
    if (state.docs[key]) {
      $("fikirler-body-text").innerHTML = renderMarkdown(state.docs[key].markdown || "");
      return;
    }
    fetchJson("./reports/" + date + "/" + INNOVATION_ID + ".json")
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
    var nextMeetingEl = $("calendar-next-meeting");
    if (calendar.next_meeting) {
      nextMeetingEl.textContent = calendar.next_meeting;
      nextMeetingEl.parentElement.hidden = false;
    } else {
      nextMeetingEl.parentElement.hidden = true;
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
    text($("doc-title"), "Yükleniyor…");
    $("doc-body").textContent = "";
    fetchJson("./reports/" + route.date + "/" + route.id + ".json")
      .then(function (doc) {
        state.docs[key] = doc;
        renderDocument(doc);
      })
      .catch(function (error) {
        text($("doc-emoji"), "⚠️");
        text($("doc-title"), "Rapor bulunamadı");
        text($("doc-meta"), "");
        $("doc-lead").hidden = true;
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
  }

  function renderAll() {
    state.loaded = true;
    renderSistem();
    renderPerformans();
    renderIsler();
    renderEntegrasyonlar();
    renderGmailCalendar();
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
