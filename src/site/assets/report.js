(function () {
  "use strict";
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function num(n) { return Number(n).toLocaleString(); }
  var input = document.getElementById("report-in");
  var send = document.getElementById("report-send");
  var out = document.getElementById("report-out");

  async function generate() {
    var q = input.value.trim();
    if (!q) return;
    out.innerHTML = '<div class="typing">Computing the figure from the published data…</div>';
    var resp = await fetch("/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request: q }),
    });
    if (resp.redirected) { window.location = "/login"; throw new Error("redirect"); }
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return resp.json();
  }

  function renderData(data) {
    // Never renders a model number — data IS the platform figure verbatim.
    if (data === null || data === undefined) {
      return '<p class="nodata">No figure could be computed for this request.</p>';
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

  function render(r) {
    if (!r) return;  // blank input -> generate() returns undefined; never crash
    if (r.built) {
      out.innerHTML = '<div class="report-card"><h2>Report built</h2>' +
        '<p>The deterministic router could not map this to a fixed figure, so it ' +
        'was built from the published data. ' +
        '<a href="' + r.dashboard_url + '">Open the dashboard</a> &middot; ' +
        '<a href="' + r.lineage_url + '">View lineage</a></p></div>';
      return;
    }
    if (r.escalate) {
      out.innerHTML = '<div class="nodata">' + esc(r.error || "Unfulfillable") +
        ' <a href="mailto:contact@bluebirdadvisory.com.au">contact@bluebirdadvisory.com.au</a></div>';
      return;
    }
    var reg = r.dataset_registry || {};
    out.innerHTML =
      '<div class="report-card">' +
      "<h2>" + esc(r.stat_label || r.stat_key) + "</h2>" +
      renderData(r.data) +
      '<p class="basis">basis: ' + esc(r.basis || "") + "</p>" +
      '<p class="cite">sources: ' + esc(reg.source_rows || 0) +
      " rows, hash " + esc(reg.rows_hash || "") + "</p>" +
      "</div>";
  }

  send.addEventListener("click", async function () {
    try { render(await generate()); }
    catch (e) {
      out.innerHTML = '<div class="nodata">' + esc("Sorry — the report is temporarily unavailable. " + e.message) + "</div>";
    }
  });
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter") { ev.preventDefault(); send.click(); }
  });
})();
