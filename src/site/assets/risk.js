(function () {
  "use strict";
  var data = window.__riskData;
  if (!data || typeof echarts === "undefined") return;

  var ink = "#0f1e33", ink2 = "#4a5a72", brand = "#5d4fff", grid = "#e4eaf2";

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

  // ---- agency risk-tier distribution ----
  var tiers = data.tiers || [];
  var counts = { low: 0, medium: 0, high: 0 };
  tiers.forEach(function (t) { if (counts[t.tier] != null) counts[t.tier] += 1; });

  var tcEl = document.getElementById("tier-chart");
  if (tcEl && tiers.length) {
    var tc = echarts.init(tcEl);
    tc.setOption({
      color: ["#16a34a", "#ea580c", "#dc2626"],
      grid: { left: 48, right: 16, top: 24, bottom: 32 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category",
               data: ["Low risk", "Medium risk", "High risk"],
               axisLabel: { color: ink2 } },
      yAxis: { type: "value", name: "Agencies", axisLabel: { color: ink2 },
               splitLine: { lineStyle: { color: grid } } },
      series: [{ type: "bar", data: [counts.low, counts.medium, counts.high],
                 barMaxWidth: 48, label: { show: true, position: "top",
                                          color: ink2 } }]
    });
  }

  // ---- searchable agency table ----
  var search = document.getElementById("risk-search-in");
  var table = document.getElementById("risk-table");
  if (search && table) {
    search.addEventListener("input", function () {
      var q = search.value.trim().toLowerCase();
      var rows = table.querySelectorAll("tbody tr");
      for (var i = 0; i < rows.length; i++) {
        var name = rows[i].getAttribute("data-name") || "";
        rows[i].style.display = (q && name.indexOf(q) === -1) ? "none" : "";
      }
    });
  }
})();
