/* AI Executive Assistant — Ajan Panosu
 *
 * Vanilla JS, no framework, no build. It does exactly one thing: fetch
 * ./status.json (written by ai_assistant.status_report after every briefing
 * run) and render it. There is no backend and no API — the JSON sits next to
 * this file, so the page works from any static host and offline once cached.
 */
(function () {
  "use strict";

  var STATUS_URL = "./status.json";
  var REFRESH_MS = 60000; // live monitor: re-read the file every minute
  var CLOCK_MS = 20000; // how often the "x dk önce" label is recomputed

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

  var state = { data: null, category: "*", lastFetch: null };

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
    // the raw timestamp so an older file still renders.
    return entry.at_istanbul || entry.at || "–";
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

  /* --- rendering --------------------------------------------------------- */

  function renderSummary(data) {
    var run = data.run || {};
    text($("stat-total"), run.total != null ? run.total : "–");
    text($("stat-ok"), run.ok != null ? run.ok : "–");
    text($("stat-failed"), run.failed != null ? run.failed : "–");
    text($("stat-skipped"), run.skipped != null ? run.skipped : "–");
    text($("stat-duration"), duration(run.duration_seconds));

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
      badge.textContent = STATUS_ICON[status] + " " + STATUS_LABEL[status];

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
      size.textContent = status === "ok" ? bytesish(advisor.content_length) : "—";
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

  /* --- freshness --------------------------------------------------------- */

  function updateFreshness() {
    var parts = [];
    if (state.data && state.data.generated_at) {
      parts.push("veri " + relativeTime(state.data.generated_at));
    }
    if (state.lastFetch) {
      parts.push("son güncelleme " + relativeTime(state.lastFetch));
    }
    text($("freshness"), parts.join(" · "));

    // A run older than ~26 hours means the daily job did not land.
    var stale = false;
    if (state.data && state.data.generated_at) {
      var age = Date.now() - Date.parse(state.data.generated_at);
      stale = !isNaN(age) && age > 26 * 3600 * 1000;
    }
    $("live-dot").classList.toggle("live--stale", stale);
    $("live-dot").title = stale
      ? "Son veri 26 saatten eski — planlı çalıştırma gecikmiş olabilir."
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

    // Cache-bust: a static host will happily serve a stale status.json.
    fetch(STATUS_URL + "?t=" + Date.now(), { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.text();
      })
      .then(function (raw) {
        if (!raw.trim()) throw new Error("empty");
        return JSON.parse(raw);
      })
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
            ? "status.json henüz oluşturulmamış. Günlük brifing bir kez " +
              "çalıştığında (her gün 10:00 İstanbul) bu pano dolacak."
            : "status.json alınamadı: " + (error && error.message ? error.message : "bilinmeyen hata")
        );
      })
      .then(function () {
        button.dataset.busy = "false";
      });
  }

  function init() {
    showState("⏳", "Yükleniyor…", "Durum dosyası okunuyor.");
    initTooltip();
    $("refresh").addEventListener("click", function () {
      load(true);
    });
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
