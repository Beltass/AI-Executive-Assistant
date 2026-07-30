/* AI Executive Assistant — Ajan Panosu
 *
 * Vanilla JS, no framework, no build, no CDN. Two jobs:
 *
 *   1. MONITOR — fetch ./status.json (written by ai_assistant.status_report
 *      after every briefing run) and render how the run went.
 *   2. READ — fetch ./reports/<gün>/<ajan>.json (written by
 *      ai_assistant.reports) and typeset each advisor's briefing as its own
 *      document, so a 400-word report is comfortable to read on a phone
 *      instead of being a wall of text in Slack.
 *
 * A hash router keeps the whole thing in one static page:
 *   #/                            pano
 *   #/raporlar                    arşiv (son 30 gün)
 *   #/raporlar/2026-07-31         o günün raporları
 *   #/rapor/2026-07-31/ajan_id    tek rapor (okuma görünümü)
 *
 * The Markdown the advisors emit is rendered by the small, deliberately
 * limited renderer below. It ESCAPES the source first and only then applies a
 * safe subset of Markdown, so a report can never inject HTML into this page.
 */
(function () {
  "use strict";

  var STATUS_URL = "./status.json";
  var REPORTS_URL = "./reports/index.json";
  var REFRESH_MS = 60000; // live monitor: re-read the file every minute
  var CLOCK_MS = 20000; // how often the "x dk önce" label is recomputed
  var STALE_HOURS = 12; // older than this and we say so, loudly

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
    skipped: { label: "Atlandı", cls: "skipped", icon: "⏭️" }
  };
  // The 10:00 run is the full briefing; the 14:00/18:00/22:00 ones only carry
  // what is new since the previous run.
  var MODE = {
    full: {
      label: "Tam brifing",
      icon: "🗓️",
      cls: "ok",
      note: "Tüm ajanlar, tüm bölümler."
    },
    incremental: {
      label: "Artımlı",
      icon: "🔄",
      cls: "partial",
      note: "Yalnızca önceki çalıştırmadan sonraki yeni bulgular."
    }
  };

  var DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
  var ID_RE = /^[A-Za-z0-9_-]+$/;

  var state = {
    data: null,
    category: "*",
    lastFetch: null,
    archive: null, // reports/index.json
    days: {}, // date -> day index
    docs: {}, // "date/id" -> document
    route: { name: "dashboard" }
  };

  function $(id) {
    return document.getElementById(id);
  }

  function text(el, value) {
    if (el) el.textContent = value;
  }

  /* --- small formatters -------------------------------------------------- */

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

  function shortTime(entry) {
    // Prefer the pre-formatted Istanbul label the producer wrote; fall back to
    // the raw timestamp so an older file still renders. The mode icon tells the
    // 10:00 full briefing apart from the incremental top-ups at a glance.
    var label = entry.at_istanbul || entry.at || "–";
    var mode = MODE[entry.mode];
    return mode ? mode.icon + " " + label : label;
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
    var now = new Date(Date.now() + 3 * 3600 * 1000);
    return now.toISOString().slice(0, 10);
  }

  /* --- markdown ----------------------------------------------------------- */
  /*
   * Lives in markdown.js so it can be unit-tested outside a browser (see
   * tests/test_frontend_markdown.py). It ESCAPES before it marks up, which is
   * what makes it safe to feed model-generated text into innerHTML below.
   */
  var renderMarkdown = (typeof AIAMarkdown !== "undefined" && AIAMarkdown.renderMarkdown)
    ? AIAMarkdown.renderMarkdown
    : function (source) {
        // markdown.js failed to load: show the raw text rather than nothing,
        // and never touch innerHTML with it.
        return "";
      };

  /* --- fetching ----------------------------------------------------------- */

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

  /* --- state screens ----------------------------------------------------- */

  function showState(icon, title, body) {
    $("content").hidden = true;
    var box = $("state");
    box.hidden = false;
    text($("state-icon"), icon);
    text($("state-title"), title);
    text($("state-text"), body || "");
  }

  function showContent() {
    $("state").hidden = true;
    $("content").hidden = false;
  }

  /* --- rendering: the monitor -------------------------------------------- */

  function renderSummary(data) {
    var run = data.run || {};
    text($("stat-total"), run.total != null ? run.total : "–");
    text($("stat-ok"), run.ok != null ? run.ok : "–");
    text($("stat-failed"), run.failed != null ? run.failed : "–");
    text($("stat-skipped"), run.skipped != null ? run.skipped : "–");
    text($("stat-duration"), duration(run.duration_seconds));

    // Run mode. Older status files have no mode at all — they were all full
    // briefings back then, so that is the safe fallback.
    var mode = MODE[run.mode] || MODE.full;
    var modeBadge = $("mode-badge");
    modeBadge.className = "badge badge--" + mode.cls;
    modeBadge.textContent = mode.icon + " " + mode.label;
    text($("mode-note"), mode.note);
    text($("stat-new"), run.new_findings != null ? run.new_findings : "–");

    var conclusion = CONCLUSION[run.conclusion] || CONCLUSION.idle;
    var slack = SLACK_LABEL[(data.slack || {}).status] || SLACK_LABEL.skipped;
    var badge = $("slack-badge");
    badge.className = "badge badge--" + slack.cls;
    badge.textContent = slack.icon + " " + slack.label;
    text($("slack-detail"), (data.slack || {}).detail || "");

    text(
      $("last-run-label"),
      conclusion.icon +
        " " +
        conclusion.label +
        " · son çalıştırma " +
        (data.generated_at_istanbul || "–") +
        " (İstanbul)"
    );

    var batch = run.batch || {};
    text($("batch-used"), batch.used ? "✅ kullanıldı" : batch.attempted ? "⚠️ denendi, düştü" : "⏭️ kullanılmadı");
    text(
      $("batch-sections"),
      (batch.sections_produced || 0) + " / " + (batch.sections_requested || 0)
    );
    text($("batch-model"), batch.model || (batch.provider ? batch.provider : "—"));
  }

  function renderAccountability(data) {
    var acc = data.accountability || {};
    text($("streak-value"), acc.streak || 0);
    text($("task-count"), acc.today_task_count || 0);
    text(
      $("streak-note"),
      acc.available
        ? acc.last_date
          ? "Son kayıt: " + acc.last_date
          : ""
        : "Henüz kayıtlı seri yok — ilk görev listesiyle birlikte başlayacak."
    );
  }

  function categories(advisors) {
    var seen = [];
    advisors.forEach(function (a) {
      if (a.category && seen.indexOf(a.category) === -1) seen.push(a.category);
    });
    return seen;
  }

  function renderFilters(advisors) {
    var host = $("filters");
    host.innerHTML = "";
    var options = [{ key: "*", label: "Tümü (" + advisors.length + ")" }];
    categories(advisors).forEach(function (cat) {
      var count = advisors.filter(function (a) {
        return a.category === cat;
      }).length;
      options.push({ key: cat, label: cat + " (" + count + ")" });
    });

    options.forEach(function (option) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "chip";
      button.textContent = option.label;
      button.setAttribute("aria-pressed", state.category === option.key ? "true" : "false");
      button.addEventListener("click", function () {
        state.category = option.key;
        renderFilters(advisors);
        renderCards(advisors);
      });
      host.appendChild(button);
    });
  }

  function renderCards(advisors) {
    var grid = $("advisor-grid");
    grid.innerHTML = "";
    var visible = advisors.filter(function (a) {
      return state.category === "*" || a.category === state.category;
    });

    $("empty-filter").hidden = visible.length > 0;

    visible.forEach(function (advisor) {
      var status = STATUS_LABEL[advisor.status] ? advisor.status : "skipped";
      // "Nothing new" is not the same as "not configured": the advisor ran and
      // deliberately stayed quiet because the user already knows.
      var quiet = advisor.nothing_new === true;
      var card = document.createElement("article");
      card.className = "card card--" + status;

      var head = document.createElement("div");
      head.className = "card__head";

      var emoji = document.createElement("span");
      emoji.className = "card__emoji";
      emoji.setAttribute("aria-hidden", "true");
      emoji.textContent = advisor.emoji || "🧩";

      var name = document.createElement("h3");
      name.className = "card__name";
      name.textContent = advisor.name || advisor.id;
      var id = document.createElement("span");
      id.className = "card__id";
      id.textContent = advisor.id;
      name.appendChild(id);

      // Icon + word, never color alone.
      var badge = document.createElement("span");
      badge.className = "badge badge--" + status;
      badge.textContent = quiet
        ? "🟰 Yeni bulgu yok"
        : STATUS_ICON[status] + " " + STATUS_LABEL[status];

      head.appendChild(emoji);
      head.appendChild(name);
      head.appendChild(badge);
      card.appendChild(head);

      if (advisor.detail) {
        var detail = document.createElement("p");
        detail.className = "card__detail";
        detail.textContent = advisor.detail;
        card.appendChild(detail);
      }

      var foot = document.createElement("div");
      foot.className = "card__foot";
      var tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = advisor.category || "—";
      var size = document.createElement("span");
      if (quiet) {
        size.textContent = "0 yeni bulgu";
      } else if (status === "ok") {
        size.textContent =
          bytesish(advisor.content_length) +
          (advisor.new_findings ? " · 🆕 " + advisor.new_findings : "");
      } else {
        size.textContent = "—";
      }
      foot.appendChild(tag);
      foot.appendChild(size);
      card.appendChild(foot);

      grid.appendChild(card);
    });
  }

  function renderChart(history) {
    var chart = $("chart");
    chart.innerHTML = "";
    if (!history.length) {
      text($("chart-caption"), "Henüz geçmiş kaydı yok.");
      return;
    }

    var max = history.reduce(function (acc, entry) {
      return Math.max(acc, (entry.ok || 0) + (entry.failed || 0) + (entry.skipped || 0), 1);
    }, 1);

    history.forEach(function (entry) {
      var ok = entry.ok || 0;
      var failed = entry.failed || 0;
      var skipped = entry.skipped || 0;
      var total = ok + failed + skipped;

      var bar = document.createElement("div");
      bar.className = "bar";
      bar.tabIndex = 0;
      var summary =
        shortTime(entry) +
        " — ✅ " + ok + " · ⚠️ " + failed + " · ⏭️ " + skipped +
        (entry.duration_seconds != null ? " · " + duration(entry.duration_seconds) : "");
      bar.setAttribute("aria-label", summary);
      bar.dataset.tip = summary;

      // Stack order top→bottom: skipped, failed, ok (ok anchored to baseline).
      [
        ["skipped", skipped],
        ["failed", failed],
        ["ok", ok]
      ].forEach(function (pair) {
        if (!pair[1]) return;
        var seg = document.createElement("div");
        seg.className = "seg seg--" + pair[0];
        // Scale against the tallest run so bars stay comparable.
        seg.style.height = ((pair[1] / max) * 100).toFixed(2) + "%";
        bar.appendChild(seg);
      });

      if (!total) {
        var empty = document.createElement("div");
        empty.className = "seg seg--skipped";
        empty.style.height = "2px";
        bar.appendChild(empty);
      }

      chart.appendChild(bar);
    });

    text(
      $("chart-caption"),
      "Son " + history.length + " çalıştırma (en yenisi sağda). Bir sütunun " +
        "üzerine gelerek sayıları görebilirsin."
    );
  }

  function renderTable(history) {
    var body = $("history-body");
    body.innerHTML = "";
    var recent = history.slice(-10).reverse();
    recent.forEach(function (entry) {
      var row = document.createElement("tr");
      var conclusion = CONCLUSION[entry.conclusion] || CONCLUSION.idle;
      var slack = SLACK_LABEL[entry.slack] || SLACK_LABEL.skipped;

      [
        shortTime(entry),
        null, // conclusion badge, built below
        entry.ok || 0,
        entry.failed || 0,
        entry.skipped || 0,
        duration(entry.duration_seconds),
        slack.icon + " " + slack.label
      ].forEach(function (value, index) {
        var cell = document.createElement("td");
        if (index === 1) {
          var badge = document.createElement("span");
          badge.className = "badge badge--" + conclusion.cls;
          badge.textContent = conclusion.icon + " " + conclusion.label;
          cell.appendChild(badge);
        } else {
          cell.textContent = String(value);
          if (index >= 2 && index <= 5) cell.className = "num";
        }
        row.appendChild(cell);
      });
      body.appendChild(row);
    });
  }

  function render(data) {
    state.data = data;
    var advisors = Array.isArray(data.advisors) ? data.advisors : [];
    var history = Array.isArray(data.history) ? data.history : [];

    if (!advisors.length && !history.length) {
      showState(
        "🕰️",
        "Henüz veri yok",
        "Danışman ekibi henüz çalışmadı ya da durum dosyası oluşturulmadı. " +
          "İlk brifing çalıştırmasından sonra bu pano dolacak."
      );
      updateFreshness();
      return;
    }

    showContent();
    renderSummary(data);
    renderAccountability(data);
    renderFilters(advisors);
    renderCards(advisors);
    renderChart(history);
    renderTable(history);
    updateFreshness();
  }

  /* --- rendering: the reports -------------------------------------------- */

  function reportCard(entry, date) {
    var link = document.createElement("a");
    link.className = "report-card";
    link.href = "#/rapor/" + date + "/" + entry.id;

    var head = document.createElement("div");
    head.className = "report-card__head";

    var emoji = document.createElement("span");
    emoji.className = "report-card__emoji";
    emoji.setAttribute("aria-hidden", "true");
    emoji.textContent = entry.emoji || "📄";

    var name = document.createElement("h3");
    name.className = "report-card__name";
    name.textContent = entry.name || entry.id;

    head.appendChild(emoji);
    head.appendChild(name);
    link.appendChild(head);

    var lead = document.createElement("p");
    lead.className = "report-card__lead";
    lead.textContent = entry.headline || entry.excerpt || "";
    link.appendChild(lead);

    var foot = document.createElement("div");
    foot.className = "report-card__foot";
    var tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = entry.category || "—";
    var meta = document.createElement("span");
    meta.textContent =
      "⏱️ ~" + (entry.read_minutes || 1) + " dk okuma · " + (entry.words || 0) + " kelime";
    foot.appendChild(tag);
    foot.appendChild(meta);
    link.appendChild(foot);

    return link;
  }

  function renderReportsSection(day) {
    var host = $("report-grid");
    host.innerHTML = "";
    var note = $("reports-note");
    var entries = day && Array.isArray(day.reports) ? day.reports : [];

    if (!entries.length) {
      text(
        note,
        "Bu çalıştırmada yayınlanmış rapor yok. Tam brifing İstanbul saatiyle " +
          "10:00'da hazırlanır."
      );
      $("reports-empty").hidden = false;
      return;
    }
    $("reports-empty").hidden = true;
    var isToday = day.date === todayIso();
    text(
      note,
      (isToday ? "Bugünün brifingi" : prettyDate(day.date) + " brifingi") +
        " · " + entries.length + " rapor · " +
        (day.generated_at_istanbul || "") +
        (day.generated_at_istanbul ? " (İstanbul)" : "")
    );
    entries.forEach(function (entry) {
      host.appendChild(reportCard(entry, day.date));
    });
  }

  function renderArchive(archive) {
    var host = $("archive-list");
    host.innerHTML = "";
    var days = archive && Array.isArray(archive.days) ? archive.days : [];
    $("archive-empty").hidden = days.length > 0;

    days.forEach(function (day) {
      var link = document.createElement("a");
      link.className = "archive-row";
      link.href = "#/raporlar/" + day.date;

      var left = document.createElement("span");
      left.className = "archive-row__date";
      left.textContent = prettyDate(day.date);
      if (day.date === todayIso()) {
        var badge = document.createElement("span");
        badge.className = "badge badge--ok";
        badge.textContent = "bugün";
        left.appendChild(badge);
      }

      var right = document.createElement("span");
      right.className = "archive-row__meta";
      right.textContent = (day.count || 0) + " rapor";

      link.appendChild(left);
      link.appendChild(right);
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
    // The ONLY innerHTML in this file, and its input went through
    // renderMarkdown(), which escapes before it marks up.
    $("doc-body").innerHTML = renderMarkdown(doc.markdown || "");
    $("doc-back-day").href = "#/raporlar/" + doc.date;
  }

  function loadArchive() {
    return fetchJson(REPORTS_URL)
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

  function latestDay() {
    var days = state.archive && Array.isArray(state.archive.days) ? state.archive.days : [];
    return days.length ? days[0].date : "";
  }

  function refreshReports() {
    return loadArchive().then(function () {
      var date = latestDay();
      if (!date) {
        renderReportsSection(null);
        return null;
      }
      // Always re-read the newest day: an incremental run adds to it.
      delete state.days[date];
      return loadDay(date).then(function (day) {
        renderReportsSection(day);
        return day;
      });
    });
  }

  /* --- router ------------------------------------------------------------- */

  var VIEWS = ["view-dashboard", "view-report", "view-archive", "view-day"];

  function showView(id) {
    VIEWS.forEach(function (name) {
      var el = $(name);
      if (el) el.hidden = name !== id;
    });
    if (id !== "view-dashboard") window.scrollTo(0, 0);
  }

  function parseRoute() {
    var raw = (window.location.hash || "").replace(/^#\/?/, "");
    var parts = raw.split("/").filter(Boolean).map(decodeURIComponent);
    if (!parts.length) return { name: "dashboard" };
    if (parts[0] === "raporlar") {
      if (parts[1] && DATE_RE.test(parts[1])) return { name: "day", date: parts[1] };
      return { name: "archive" };
    }
    if (parts[0] === "rapor" && DATE_RE.test(parts[1] || "") && ID_RE.test(parts[2] || "")) {
      return { name: "report", date: parts[1], id: parts[2] };
    }
    return { name: "dashboard" };
  }

  function showDocError(message) {
    text($("doc-emoji"), "⚠️");
    text($("doc-title"), "Rapor bulunamadı");
    text($("doc-meta"), "");
    $("doc-lead").hidden = true;
    $("doc-body").textContent = message;
    $("doc-back-day").href = "#/raporlar";
  }

  function routeToReport(route) {
    showView("view-report");
    var cacheKey = route.date + "/" + route.id;
    if (state.docs[cacheKey]) {
      renderDocument(state.docs[cacheKey]);
      return;
    }
    text($("doc-title"), "Yükleniyor…");
    $("doc-body").textContent = "";
    fetchJson("./reports/" + route.date + "/" + route.id + ".json")
      .then(function (doc) {
        state.docs[cacheKey] = doc;
        renderDocument(doc);
      })
      .catch(function (error) {
        showDocError(
          "Bu rapor okunamadı (" +
            (error && error.message ? error.message : "bilinmeyen hata") +
            "). Arşivden başka bir gün deneyebilirsin."
        );
      });
  }

  function routeToDay(route) {
    showView("view-day");
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
    state.route = route;
    if (route.name === "report") return routeToReport(route);
    if (route.name === "day") return routeToDay(route);
    if (route.name === "archive") {
      showView("view-archive");
      loadArchive().then(renderArchive);
      return;
    }
    showView("view-dashboard");
  }

  /* --- freshness ---------------------------------------------------------- */

  function dataAgeMs() {
    if (!state.data || !state.data.generated_at) return NaN;
    return Date.now() - Date.parse(state.data.generated_at);
  }

  function updateFreshness() {
    var parts = [];
    if (state.data && state.data.generated_at) {
      parts.push("veri " + relativeTime(state.data.generated_at));
    }
    if (state.lastFetch) {
      parts.push("son güncelleme " + relativeTime(state.lastFetch));
    }
    text($("freshness"), parts.join(" · "));

    // The timestamp, spelled out, where nobody can miss it.
    var stampValue = state.data
      ? (state.data.generated_at_istanbul || state.data.generated_at || "–")
      : "–";
    text($("stamp-value"), stampValue);
    text(
      $("stamp-relative"),
      state.data && state.data.generated_at
        ? relativeTime(state.data.generated_at)
        : ""
    );

    var age = dataAgeMs();
    var stale = !isNaN(age) && age > STALE_HOURS * 3600 * 1000;
    var veryStale = !isNaN(age) && age > 26 * 3600 * 1000;

    var banner = $("stale-banner");
    banner.hidden = !stale;
    if (stale) {
      text(
        $("stale-text"),
        "⚠️ Veri eski görünüyor — son çalıştırma " +
          relativeTime(state.data.generated_at) +
          " (" + stampValue + ", İstanbul). " +
          (veryStale
            ? "Planlı çalıştırma bir günden uzun süredir gelmedi."
            : "Yayın gecikmiş ya da çalıştırma atlanmış olabilir.")
      );
    }
    $("stamp").classList.toggle("stamp--stale", stale);

    $("live-dot").classList.toggle("live--stale", stale);
    $("live-dot").title = stale
      ? "Son veri " + STALE_HOURS + " saatten eski — planlı çalıştırma gecikmiş olabilir."
      : "Her 60 saniyede bir otomatik yenilenir";
  }

  /* --- tooltip ----------------------------------------------------------- */

  function initTooltip() {
    var tip = $("tooltip");

    function show(event) {
      var target = event.target.closest ? event.target.closest(".bar") : null;
      if (!target || !target.dataset.tip) return;
      tip.hidden = false;
      tip.textContent = target.dataset.tip;
      var rect = target.getBoundingClientRect();
      var top = rect.top - tip.offsetHeight - 8;
      tip.style.top = (top < 8 ? rect.bottom + 8 : top) + "px";
      var left = rect.left + rect.width / 2 - tip.offsetWidth / 2;
      left = Math.max(8, Math.min(left, window.innerWidth - tip.offsetWidth - 8));
      tip.style.left = left + "px";
    }

    function hide() {
      tip.hidden = true;
    }

    document.addEventListener("mouseover", show);
    document.addEventListener("mouseout", hide);
    document.addEventListener("focusin", show);
    document.addEventListener("focusout", hide);
    window.addEventListener("scroll", hide, { passive: true });
  }

  /* --- loading ----------------------------------------------------------- */

  function load(manual) {
    var button = $("refresh");
    if (manual) button.dataset.busy = "true";

    fetchJson(STATUS_URL)
      .then(function (data) {
        state.lastFetch = new Date().toISOString();
        render(data);
      })
      .catch(function (error) {
        state.lastFetch = new Date().toISOString();
        if (state.data) {
          // Keep showing the last good data; only the freshness line changes.
          updateFreshness();
          return;
        }
        var missing =
          error && (error.message === "HTTP 404" || error.message === "empty");
        showState(
          missing ? "🕰️" : "⚠️",
          missing ? "Henüz veri yok" : "Durum dosyası okunamadı",
          missing
            ? "status.json henüz oluşturulmamış. Brifing bir kez " +
              "çalıştığında (İstanbul saatiyle 10:00 / 14:00 / 18:00 / 22:00) " +
              "bu pano dolacak."
            : "status.json alınamadı: " + (error && error.message ? error.message : "bilinmeyen hata")
        );
      })
      .then(function () {
        button.dataset.busy = "false";
        refreshReports();
      });
  }

  function init() {
    showState("⏳", "Yükleniyor…", "Durum dosyası okunuyor.");
    initTooltip();
    $("refresh").addEventListener("click", function () {
      load(true);
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
