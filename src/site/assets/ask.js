(function () {
  "use strict";
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function num(n) { return Number(n).toLocaleString(); }

  function inline(s) {
    return esc(s)
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  }

  function mdToHtml(text) {
    var lines = String(text || "").split("\n");
    var out = [], inList = false;
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];
      if (/^\s*[-*]\s+/.test(line)) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + inline(line.replace(/^\s*[-*]\s+/, "")) + "</li>");
      } else {
        if (inList) { out.push("</ul>"); inList = false; }
        if (line.trim()) out.push("<p>" + inline(line) + "</p>");
      }
    }
    if (inList) out.push("</ul>");
    return out.join("");
  }

  function citeHref(path) {
    if (path.indexOf("catalog:") === 0) {
      return "/provenance.html?key=" + encodeURIComponent(path.slice(8));
    }
    if (path.indexOf("data/corpus/data-notes.md") === 0) {
      return "/data-notes.html";
    }
    return null;
  }

  // A platform-computed stat value, verbatim — never a model number.
  function statData(data) {
    if (data === null || data === undefined) {
      return '<p class="nodata">No figure could be computed for this question.</p>';
    }
    if (typeof data === "number") return '<p class="value">' + num(data) + "</p>";
    if (Array.isArray(data)) {
      if (!data.length) return '<p class="nodata">No data for this figure.</p>';
      var keys = Object.keys(data[0]);
      var rows = data.map(function (r) {
        return "<tr>" + keys.map(function (k) { return "<td>" + esc(r[k]) + "</td>"; }).join("") + "</tr>";
      }).join("");
      var head = keys.map(function (k) { return "<th>" + esc(k) + "</th>"; }).join("");
      return '<table class="report-table"><thead><tr>' + head + "</tr></thead><tbody>" + rows + "</tbody></table>";
    }
    if (data.compare) {
      // named-agency table: Measure | FY | one column per agency
      var c = data.compare;
      var head = "<tr><th>Measure</th><th>FY</th>" +
        c.agencies.map(function (a) { return "<th>" + esc(a) + "</th>"; }).join("") +
        "</tr>";
      var crows = c.rows.map(function (r) {
        return "<tr><td>" + esc(r.measure) + "</td><td>" + esc(r.fy) +
          "</td>" + r.values.map(function (v) {
            return "<td>" + (v == null ? "—" : num(v)) + "</td>";
          }).join("") + "</tr>";
      }).join("");
      return '<table class="report-table"><thead>' + head +
        "</thead><tbody>" + crows + "</tbody></table>";
    }
    if (data.movers) {
      var shown = data.movers.slice(0, 10);
      var mrows = shown.map(function (m) {
        var ch = (m.change > 0 ? "+" : "") + num(m.change);
        return "<tr><td>" + esc(m.agency) + "</td><td>" + num(m.fy_a_value) +
          "</td><td>" + num(m.fy_b_value) + "</td><td>" + ch + "</td></tr>";
      }).join("");
      var mfoot = data.movers.length > shown.length
        ? '<p class="fignote">Top ' + shown.length + " of " +
          data.movers.length + " agencies.</p>" : "";
      return '<table class="report-table"><thead><tr><th>Agency</th><th>' +
        esc(data.fy_a) + " requests</th><th>" + esc(data.fy_b) +
        " requests</th><th>Change</th></tr></thead><tbody>" + mrows +
        "</tbody></table>" + mfoot;
    }
    if (data.categories && data.series) {
      var series = data.series[0] || { name: "", values: [] };
      var rows2 = data.categories.map(function (c, i) {
        var v = series.values[i];
        return "<tr><td>" + esc(c) + "</td><td>" + (v == null ? "—" : num(v)) + "</td></tr>";
      }).join("");
      return '<table class="report-table"><thead><tr><th>Category</th><th>' + esc(series.name) + "</th></tr></thead><tbody>" + rows2 + "</tbody></table>";
    }
    return "<pre>" + esc(JSON.stringify(data, null, 2)) + "</pre>";
  }

  var log = document.getElementById("ask-log");
  var input = document.getElementById("ask-in");
  var send = document.getElementById("ask-send");

  var history = [];

  function addUser(q) {
    var d = document.createElement("div");
    d.className = "msg user";
    d.textContent = q;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }

  function renderText(r) {
    var d = document.createElement("div");
    d.className = "msg assistant";
    d.innerHTML = mdToHtml(r.answer || "");
    var cites = r.citations || [];
    if (cites.length) {
      var c = document.createElement("div");
      c.className = "cite";
      c.innerHTML = "Sources: " + cites.map(function (p) {
        var href = citeHref(p);
        return href ? '<a href="' + href + '">' + esc(p) + '</a>' : esc(p);
      }).join(" &middot; ");
      d.appendChild(c);
    }
    log.appendChild(d);
  }

  function renderScope(r) {
    renderText(r);
    var e = document.createElement("div");
    e.className = "escalate";
    e.innerHTML = 'For a custom FOI report, email <a href="mailto:contact@bluebirdadvisory.com.au">contact@bluebirdadvisory.com.au</a>.';
    log.appendChild(e);
  }

  function renderStat(r) {
    var d = document.createElement("div");
    d.className = "msg assistant";
    var html = '<div class="report-card"><h2>' +
      esc(r.stat_label || r.stat_key || "Answer") + "</h2>";
    if (r.note) html += '<p class="note">' + esc(r.note) + "</p>";
    html += statData(r.data);
    if (r.basis) html += '<p class="basis">basis: ' + esc(r.basis) + "</p>";
    var reg = r.dataset_registry || {};
    html += '<p class="cite">sources: ' + esc(reg.source_rows || 0) +
      " rows, hash " + esc(reg.rows_hash || "") + "</p></div>";
    d.innerHTML = html;
    log.appendChild(d);
  }

  function renderDashboard(r) {
    var d = document.createElement("div");
    d.className = "msg assistant";
    d.innerHTML = '<div class="report-card"><h2>Report built</h2>' +
      '<p>This question was built into a dashboard from the published data.</p>' +
      '<a class="cta" href="' + esc(r.dashboard_url) + '">Open the dashboard</a> ' +
      '<a class="nav-link" href="' + esc(r.lineage_url) + '">View lineage</a></div>';
    log.appendChild(d);
    refreshBoard();
  }

  // ---- the build theatre: a queued job card that ticks through steps ----
  function jobStatusLabel(s) {
    return s === "building" ? "Building…" : s === "ready" ? "Ready"
      : s === "queued" ? "Queued" : s === "error" ? "Failed" : String(s || "…");
  }

  function jobStepsHtml(progress) {
    var steps = (progress || []).slice(-8);
    if (!steps.length) return "";
    return '<ul class="job-steps">' + steps.map(function (p) {
      return "<li>" + esc(p.detail || p.step || "") + "</li>";
    }).join("") + "</ul>";
  }

  function renderJobCard(r) {
    var d = document.createElement("div");
    d.className = "msg assistant";
    d.innerHTML = '<div class="report-card job-card" id="job-' + esc(String(r.job_id)) + '">' +
      "<h2>Building your dashboard</h2>" +
      '<p class="statusline"><span class="spin" aria-hidden="true"></span> ' +
      '<span class="job-status">Queued</span></p>' +
      '<div class="job-steps-wrap">' + jobStepsHtml([{ detail: "waiting for the builder" }]) + "</div></div>";
    log.appendChild(d);
    pollJob(r.job_id, d.querySelector(".job-card"));
  }

  async function pollJob(jobId, card) {
    if (!card || !card.isConnected) return;
    try {
      var resp = await fetch("/dashboards/" + encodeURIComponent(jobId) + "/status");
      if (resp.redirected) { window.location = "/login"; return; }
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      var st = await resp.json();
      var statusEl = card.querySelector(".job-status");
      var wrap = card.querySelector(".job-steps-wrap");
      if (st.status === "queued" || st.status === "building") {
        if (statusEl) statusEl.textContent = jobStatusLabel(st.status);
        if (wrap) wrap.innerHTML = jobStepsHtml(st.progress);
        refreshBoard();
        window.setTimeout(function () { pollJob(jobId, card); }, 1500);
        return;
      }
      if (st.status === "ready") {
        card.innerHTML = '<h2>Report built</h2>' +
          "<p>Your dashboard is ready, built from the published data.</p>" +
          '<a class="cta" href="' + esc(st.dashboard_url) + '">Open the dashboard</a> ' +
          '<a class="nav-link" href="' + esc(st.lineage_url) + '">View lineage</a>' +
          jobStepsHtml(st.progress);
        refreshBoard();
        return;
      }
      var html = "<h2>Dashboard build failed</h2>";
      var res = st.result || {};
      if (res.data != null || res.note) {
        html += '<p class="note">The dashboard build did not finish, so here ' +
          "is the computed figure for your question instead.</p>";
        if (res.note) html += '<p class="note">' + esc(res.note) + "</p>";
        html += "<h3>" + esc(res.stat_label || res.stat_key || "Answer") + "</h3>";
        html += statData(res.data);
        if (res.basis) html += '<p class="basis">basis: ' + esc(res.basis) + "</p>";
        var reg = res.dataset_registry || {};
        html += '<p class="cite">sources: ' + esc(reg.source_rows || 0) +
          " rows, hash " + esc(reg.rows_hash || "") + "</p>";
      } else {
        html += '<p class="nodata">No dashboard and no computed figure could ' +
          "be produced for this question.</p>";
      }
      html += jobStepsHtml(st.progress);
      html += '<button class="job-retry" type="button" data-id="' +
        esc(String(jobId)) + '">Try again</button>';
      card.innerHTML = html;
      refreshBoard();
    } catch (e) {
      // transient poll failure: keep polling, the job is in the DB
      window.setTimeout(function () { pollJob(jobId, card); }, 3000);
    }
  }

  // "Try again" on a failed build (delegated, like the delete handler)
  document.addEventListener("click", async function (ev) {
    var btn = ev.target.closest ? ev.target.closest(".job-retry") : null;
    if (!btn) return;
    ev.preventDefault();
    var id = btn.getAttribute("data-id");
    var card = btn.closest(".job-card");
    try {
      var resp = await fetch("/dashboards/" + encodeURIComponent(id) + "/retry",
                             { method: "POST" });
      if (resp.redirected) { window.location = "/login"; return; }
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      card.innerHTML = "<h2>Building your dashboard</h2>" +
        '<p class="statusline"><span class="spin" aria-hidden="true"></span> ' +
        '<span class="job-status">Queued</span></p>' +
        '<div class="job-steps-wrap">' +
        jobStepsHtml([{ detail: "waiting for the builder" }]) + "</div>";
      pollJob(id, card);
    } catch (e) {
      window.alert("Could not retry the build: " + e.message);
    }
  });

  function boardRow(a) {
    var status = (a.status === "ready" && !a.panel_count) ? "error" : a.status;
    var labels = { building: "Building…", ready: "Ready", error: "Failed",
                   queued: "Queued" };
    var cls = status === "building" ? "status-building"
      : status === "ready" ? "status-ready"
      : status === "error" ? "status-error"
      : status === "queued" ? "status-building" : "status-unknown";
    var open = status === "ready"
      ? '<a class="nav-link" href="/dashboards/' + a.id + '">Open</a>'
      : '<span class="meta">—</span>';
    var when = String(a.created_at || "").slice(0, 16).replace("T", " ");
    var steps = a.progress || [];
    var last = steps.length ? steps[steps.length - 1] : null;
    var step = (status === "queued" || status === "building") && last
      ? '<span class="meta job-step">' + esc(last.detail || last.step || "") + "</span>"
      : "";
    return '<tr data-id="' + a.id + '"><td class="report-req">' +
      esc(a.request_text || "") + '</td><td><span class="status-badge ' + cls +
      '">' + esc(labels[status] || status || "Unknown") +
      "</span> " + step +
      '</td><td class="report-when">' + esc(when) +
      '</td><td class="report-actions">' + open +
      ' <button class="report-delete" type="button" data-id="' + a.id +
      '">Delete</button></td></tr>';
  }

  async function refreshBoard() {
    var box = document.getElementById("ask-reports");
    if (!box) return;
    try {
      var resp = await fetch("/reports.json");
      if (resp.redirected) { window.location = "/login"; return; }
      if (!resp.ok) return;
      var list = await resp.json();
      if (!list.length) {
        box.innerHTML = '<p class="nodata">No reports yet. Say "build a ' +
          'dashboard…" and it will be built here.</p>';
        return;
      }
      box.innerHTML = '<table class="report-table reports-index"><thead>' +
        '<tr><th>Report</th><th>Status</th><th>Created</th>' +
        '<th class="actions">Actions</th></tr></thead><tbody>' +
        list.map(boardRow).join("") + "</tbody></table>";
    } catch (e) { /* board refresh is best-effort */ }
  }

  async function submit() {
    var q = input.value.trim();
    if (!q) return;
    input.value = "";
    addUser(q);
    var hist = history.slice();
    history.push({ role: "user", content: q });
    var typing = document.createElement("div");
    typing.className = "typing";
    typing.textContent = "Reviewing the question…";
    log.appendChild(typing);
    log.scrollTop = log.scrollHeight;
    try {
      var resp = await fetch("/ask-question", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q, history: hist }),
      });
      if (resp.redirected) { window.location = "/login"; return; }
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      var r = await resp.json();
      typing.remove();
      if (r.kind === "scope") {
        renderScope(r);
        history.push({ role: "assistant", content: r.answer || "" });
      } else if (r.kind === "stat" || r.kind === "note") {
        renderStat(r);
        history.push({ role: "assistant", content: r.stat_label || "" });
      } else if (r.kind === "dashboard") {
        renderDashboard(r);
        history.push({ role: "assistant", content: r.dashboard_url || "" });
      } else if (r.kind === "queued") {
        renderJobCard(r);
        history.push({ role: "assistant", content: "queued dashboard build" });
      } else {
        renderText(r);
        history.push({ role: "assistant", content: r.answer || "" });
      }
      if (history.length > 12) history.splice(0, history.length - 12);
    } catch (err) {
      typing.remove();
      var d = document.createElement("div");
      d.className = "msg assistant";
      d.innerHTML = '<div class="nodata">' +
        esc("Sorry — the answer is temporarily unavailable. " + err.message) +
        "</div>";
      log.appendChild(d);
    }
    log.scrollTop = log.scrollHeight;
  }

  send.addEventListener("click", submit);
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); submit(); }
  });

  // Delete a report from the board (delegated, works on refreshed rows too).
  document.addEventListener("click", async function (ev) {
    var btn = ev.target.closest ? ev.target.closest(".report-delete") : null;
    if (!btn) return;
    ev.preventDefault();
    var id = btn.getAttribute("data-id");
    if (!window.confirm("Delete this report?")) return;
    try {
      var resp = await fetch("/dashboards/" + encodeURIComponent(id) + "/delete",
                             { method: "POST" });
      if (resp.redirected) { window.location = "/login"; return; }
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      var row = btn.closest("tr");
      if (row) row.remove();
    } catch (e) {
      window.alert("Could not delete the report: " + e.message);
    }
  });
})();
