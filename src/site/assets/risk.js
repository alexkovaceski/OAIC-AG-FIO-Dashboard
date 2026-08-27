(function () {
  "use strict";
  var data = window.__riskData;
  if (!data || typeof echarts === "undefined") return;

  var ink = "#0f1e33", ink2 = "#4a5a72", brand = "#5d4fff", grid = "#e4eaf2";
  var tierLabel = { low: "Low risk", medium: "Medium risk", high: "High risk" };

  // ---- request-volume forecast (actual bars + forecast bars + range band) ----
  var f = data.forecast || {};
  var hist = f.historical || { fy: [], values: [] };
  var pts = f.points || [];
  var cats = (hist.fy || []).concat(pts.map(function (p) { return p.fy; }));
  var actual = (hist.values || []).map(function (v) { return v == null ? null : v; });
  var fcVals = (hist.values || []).map(function () { return null; })
    .concat(pts.map(function (p) { return Math.round(p.value); }));
  var lo = (hist.values || []).map(function () { return null; })
    .concat(pts.map(function (p) { return Math.round(p.lo); }));
  var hi = (hist.values || []).map(function () { return null; })
    .concat(pts.map(function (p) { return Math.round(p.hi); }));
  var band = hi.map(function (v, i) {
    return (v == null || lo[i] == null) ? null : v - lo[i];
  });

  var fcEl = document.getElementById("forecast-chart");
  if (fcEl && pts.length) {
    var fc = echarts.init(fcEl);
    fc.setOption({
      color: [ink, brand],
      grid: { left: 64, right: 24, top: 40, bottom: 32 },
      tooltip: {
        trigger: "axis",
        formatter: function (params) {
          var i = params[0].dataIndex;
          var lines = [cats[i]];
          for (var k = 0; k < params.length; k++) {
            var p = params[k];
            if (p.value == null) continue;
            if (p.seriesName === "Actual") {
              lines.push("Actual: " + p.value.toLocaleString());
            } else if (p.seriesName === "Forecast") {
              lines.push("Forecast: " + p.value.toLocaleString() +
                " (range " + lo[i].toLocaleString() + " \u2013 " +
                hi[i].toLocaleString() + ")");
            }
          }
          return lines.join("<br>");
        }
      },
      legend: { data: ["Actual", "Forecast"], top: 0 },
      xAxis: { type: "category", data: cats, axisLabel: { color: ink2 } },
      yAxis: { type: "value", name: "Requests", axisLabel: { color: ink2 },
               splitLine: { lineStyle: { color: grid } } },
      series: [
        { name: "Actual", type: "bar", data: actual, barMaxWidth: 28,
          itemStyle: { color: ink } },
        { name: "Forecast", type: "bar", data: fcVals, barMaxWidth: 28,
          itemStyle: { color: brand } },
        { name: "Range low", type: "line", data: lo, stack: "band",
          symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false } },
        { name: "Range", type: "line", data: band, stack: "band",
          symbol: "none", lineStyle: { opacity: 0 },
          areaStyle: { color: brand, opacity: 0.14 }, tooltip: { show: false } }
      ]
    });
  }

  // ---- timeliness distribution (histogram, 10% bins) ----
  var benchmark = data.benchmark || [];
  var shares = benchmark.map(function (b) { return b.share; })
    .filter(function (s) { return s != null; });
  var bins = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
  shares.forEach(function (s) { bins[Math.min(9, Math.floor(s * 10))] += 1; });
  var binLabels = ["0-10", "10-20", "20-30", "30-40", "40-50", "50-60",
                   "60-70", "70-80", "80-90", "90-100"];

  var tcEl = document.getElementById("tier-chart");
  if (tcEl && shares.length) {
    var tc = echarts.init(tcEl);
    tc.setOption({
      color: [brand],
      grid: { left: 48, right: 16, top: 24, bottom: 40 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: binLabels, name: "Within statutory %",
               nameLocation: "middle", nameGap: 30,
               axisLabel: { color: ink2, rotate: 45 } },
      yAxis: { type: "value", name: "Agencies", axisLabel: { color: ink2 },
               splitLine: { lineStyle: { color: grid } } },
      series: [{ type: "bar", data: bins, barMaxWidth: 40 }]
    });
  }

  // ---- sortable, filterable ranking + per-agency detail ----
  var search = document.getElementById("risk-search-in");
  var tierFilter = document.getElementById("risk-tier-filter");
  var table = document.getElementById("risk-table");
  var detail = document.getElementById("agency-detail");
  var trend = data.trend || {};
  var agencyFc = data.agency_forecast || {};
  var sortCol = null;
  var sortDir = "asc";
  var selectedRow = null;

  function tierOrder(t) {
    return t === "low" ? 0 : t === "medium" ? 1 : t === "high" ? 2 : 3;
  }

  function rowKey(tr, col) {
    if (col === "agency") return (tr.getAttribute("data-name") || "").toLowerCase();
    if (col === "tier") return tierOrder(tr.getAttribute("data-tier"));
    var s = tr.getAttribute("data-share");
    return s === null || s === "" ? null : parseFloat(s);
  }

  function applyFilters() {
    var q = search && search.value ? search.value.trim().toLowerCase() : "";
    var tq = tierFilter && tierFilter.value ? tierFilter.value : "";
    var rows = table.querySelectorAll("tbody tr");
    for (var i = 0; i < rows.length; i++) {
      var name = rows[i].getAttribute("data-name") || "";
      var tier = rows[i].getAttribute("data-tier") || "";
      var ok = (!q || name.indexOf(q) !== -1) && (!tq || tier === tq);
      rows[i].style.display = ok ? "" : "none";
    }
  }

  function sortRows(col) {
    if (sortCol === col) { sortDir = sortDir === "asc" ? "desc" : "asc"; }
    else { sortCol = col; sortDir = "asc"; }
    var tbody = table.querySelector("tbody");
    var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
    rows.sort(function (a, b) {
      var va = rowKey(a, col);
      var vb = rowKey(b, col);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;   // missing values always last
      if (vb == null) return -1;
      var cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
    for (var i = 0; i < rows.length; i++) tbody.appendChild(rows[i]);
    var heads = table.querySelectorAll("thead th.sortable");
    for (var j = 0; j < heads.length; j++) {
      var h = heads[j];
      h.classList.remove("sort-asc", "sort-desc");
      h.removeAttribute("aria-sort");
      if (h.getAttribute("data-sort") === sortCol) {
        h.classList.add(sortDir === "asc" ? "sort-asc" : "sort-desc");
        h.setAttribute("aria-sort",
                       sortDir === "asc" ? "ascending" : "descending");
      }
    }
  }

  function closeDetail() {
    if (selectedRow) { selectedRow.classList.remove("selected"); selectedRow = null; }
    if (detail) detail.innerHTML = "";
  }

  function openAgency(agency) {
    if (!agency) return;
    if (table) {
      var rows = table.querySelectorAll("tbody tr");
      for (var i = 0; i < rows.length; i++) {
        if (rows[i].getAttribute("data-agency") === agency) {
          if (selectedRow) selectedRow.classList.remove("selected");
          selectedRow = rows[i];
          rows[i].classList.add("selected");
          if (rows[i].style.display === "none") rows[i].style.display = "";
          break;
        }
      }
    }
    showAgency(agency);
    if (detail && detail.scrollIntoView) {
      detail.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  function showAgency(agency) {
    var b = null;
    for (var i = 0; i < benchmark.length; i++) {
      if (benchmark[i].agency === agency) { b = benchmark[i]; break; }
    }
    if (!b) return;
    var share = b.share == null ? "\u2014" : Math.round(b.share * 100) + "%";
    var tier = b.tier || "low";
    var tr = trend[agency] || [];
    var afc = agencyFc[agency] || [];
    var fcHtml = "";
    if (afc.length) {
      var fcText = afc.map(function (p) {
        return p.fy + ": " + Math.round(p.value).toLocaleString();
      }).join(", ");
      fcHtml = '<p>Forecast requests received: <strong>' + fcText +
        '</strong>.</p><div class="chartbox chartbox-sm" id="agency-fc-chart"></div>';
    }
    detail.innerHTML = '<div class="report-card"><h3>' + agency +
      '<button class="detail-close" type="button">Close</button></h3>' +
      '<p><strong>' + share + '</strong> of decisions were made within the ' +
      'statutory period this year' +
      (b.decided ? ' (' + b.decided.toLocaleString() + ' decisions)' : '') +
      '. Next-year expectation: <span class="tier tier-' + tier + '">' +
      (tierLabel[tier] || tier) + '</span>.</p>' +
      fcHtml +
      '<div class="chartbox chartbox-sm" id="agency-trend-chart"></div></div>';

    // per-agency request-volume forecast (actual + forecast bars)
    var fcEl = document.getElementById("agency-fc-chart");
    if (fcEl && afc.length) {
      var fcCh = echarts.init(fcEl);
      var actVals = tr.map(function (t) { return t.received == null ? null : t.received; });
      var fcVals = tr.map(function () { return null; })
        .concat(afc.map(function (p) { return Math.round(p.value); }));
      var fcCats = tr.map(function (t) { return t.fy; })
        .concat(afc.map(function (p) { return p.fy; }));
      fcCh.setOption({
        color: [ink, brand],
        grid: { left: 64, right: 16, top: 24, bottom: 32 },
        tooltip: { trigger: "axis" },
        legend: { data: ["Actual", "Forecast"], top: 0 },
        xAxis: { type: "category", data: fcCats, axisLabel: { color: ink2 } },
        yAxis: { type: "value", name: "Requests received",
                 axisLabel: { color: ink2 }, splitLine: { lineStyle: { color: grid } } },
        series: [
          { name: "Actual", type: "bar", data: actVals, barMaxWidth: 24,
            itemStyle: { color: ink } },
          { name: "Forecast", type: "bar", data: fcVals, barMaxWidth: 24,
            itemStyle: { color: brand } }
        ]
      });
    }

    var el = document.getElementById("agency-trend-chart");
    if (el && tr.length) {
      var ch = echarts.init(el);
      var fys = tr.map(function (t) { return t.fy; });
      var vals = tr.map(function (t) {
        return t.share == null ? null : Math.round(t.share * 100);
      });
      ch.setOption({
        color: [brand],
        grid: { left: 48, right: 16, top: 24, bottom: 32 },
        tooltip: {
          trigger: "axis",
          formatter: function (p) {
            var r = tr[p[0].dataIndex];
            var s = r.share == null ? "\u2014" : Math.round(r.share * 100) + "%";
            var out = fys[p[0].dataIndex] + "<br>Within statutory: " + s;
            if (r.decided != null) out += "<br>Decisions: " + r.decided.toLocaleString();
            if (r.received != null) out += "<br>Received: " + r.received.toLocaleString();
            return out;
          }
        },
        xAxis: { type: "category", data: fys, axisLabel: { color: ink2 } },
        yAxis: { type: "value", name: "Within statutory %", min: 0, max: 100,
                 axisLabel: { color: ink2 }, splitLine: { lineStyle: { color: grid } } },
        series: [{ type: "line", data: vals, name: "Within statutory" }]
      });
    }
  }

  if (search) search.addEventListener("input", applyFilters);
  if (tierFilter) tierFilter.addEventListener("change", applyFilters);
  if (table) {
    table.addEventListener("click", function (ev) {
      var th = ev.target.closest("th");
      if (th && th.classList.contains("sortable")) {
        sortRows(th.getAttribute("data-sort"));
        applyFilters();
        return;
      }
      var tr = ev.target.closest("tr");
      if (tr && tr.getAttribute("data-agency")) {
        openAgency(tr.getAttribute("data-agency"));
      }
    });
    table.addEventListener("keydown", function (ev) {
      var tr = ev.target.closest("tr");
      if (tr && tr.getAttribute("data-agency") &&
          (ev.key === "Enter" || ev.key === " ")) {
        ev.preventDefault();
        openAgency(tr.getAttribute("data-agency"));
      }
    });
  }
  // the forecast section's top-10 agency table drills into the same detail
  var fcTable = document.getElementById("agency-fc-table");
  if (fcTable) {
    fcTable.addEventListener("click", function (ev) {
      var tr = ev.target.closest("tr");
      if (tr && tr.getAttribute("data-agency")) {
        openAgency(tr.getAttribute("data-agency"));
      }
    });
    fcTable.addEventListener("keydown", function (ev) {
      var tr = ev.target.closest("tr");
      if (tr && tr.getAttribute("data-agency") &&
          (ev.key === "Enter" || ev.key === " ")) {
        ev.preventDefault();
        openAgency(tr.getAttribute("data-agency"));
      }
    });
  }
  document.addEventListener("click", function (ev) {
    if (ev.target.closest && ev.target.closest(".detail-close")) closeDetail();
  });
})();
