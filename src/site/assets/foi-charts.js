/* foi-charts.js — ECharts init + live filters for the FOI Insights pages.

 * Reads window.__pageData (the platform-computed figures + canonical facts,
 * emitted by site/pages.py into a <script> before </body>), mounts an ECharts
 * instance on every `.chartbox` (keyed by its data-figure attribute), and
 * exposes the filter surface for Task 4.
 *
 * Filter contract: a filter SELECTS or RE-GROUPS rows from
 * window.__pageData.facts — the platform-derived canonical facts. It never
 * computes a new aggregate; it only narrows or regroups what the platform
 * already derived. No summing into a total that is not already a fact row.
 *
 * A `.chartbox` that already holds a server-rendered `.nodata` placeholder is
 * left untouched — the honest "no data" text is more truthful than an empty
 * chart initialised over it. One bad figure never takes down the page.
 */
(function () {
  "use strict";

  // OAIC brand palette (validated categorical slots — see site.css tokens).
  var PAL = {
    teal: "#00567d", blue: "#26547b", gold: "#ffcc00",
    orange: "#eb6834", green: "#1baf7a", ink: "#0c3c60",
    hair: "#e6e6e6",
  };
  var SLOTS = ["teal", "blue", "gold", "orange", "green"];

  // Reduced-motion users get static charts (ECharts `animation: false`).
  var REDUCED_MOTION =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var charts = {};

  // figureOption — map a platform figure {categories, series:[{name, values}]}
  // to an ECharts option. The chart type is derived from the figure KEY:
  //   *_trend  -> line    (an FY series over time)
  //   *_change -> line    (a change series over time)
  //   else     -> bar     (a top-N / breakdown figure)
  // A single-series figure renders without a legend.
  function figureOption(key, fig) {
    var type = key.endsWith("_trend") || key.indexOf("_change") > -1
      ? "line" : "bar";
    var cats = fig.categories || [];
    var series = (fig.series || []).map(function (s, i) {
      var opt = {
        name: s.name || "series",
        type: type,
        data: s.values,
        itemStyle: { color: PAL[SLOTS[i % SLOTS.length]] },
      };
      if (type === "line") opt.smooth = true;
      return opt;
    });
    var colors = series.map(function (s) { return s.itemStyle.color; });
    var manyCats = cats.length > 8; // e.g. the top-20 agency lists
    return {
      color: colors,
      animation: !REDUCED_MOTION,
      aria: { enabled: true },
      tooltip: { trigger: "axis" },
      legend: series.length > 1 ? { top: 0 } : undefined,
      grid: { left: 50, right: 20, top: 30, bottom: manyCats ? 70 : 40 },
      xAxis: {
        type: "category",
        data: cats,
        axisLine: { lineStyle: { color: PAL.hair } },
        ...(manyCats
          ? { axisLabel: { interval: 0, rotate: 30, fontSize: 10 } }
          : {}),
      },
      yAxis: {
        type: "value",
        axisLine: { show: false },
        splitLine: { lineStyle: { color: PAL.hair } },
      },
      series: series,
    };
  }

  // chartLabel — the chartbox's accessible name: the figure-card caption (the
  // <h2> above the box) when there is one, else the figure key.
  function chartLabel(el, key) {
    var section = el.parentElement;
    var h = section && section.querySelector("h2");
    var text = h && h.textContent ? h.textContent.trim() : "";
    return text || key;
  }

  // renderChart — mount one ECharts figure on a single .chartbox.
  function renderChart(el) {
    var key = el.dataset.figure;
    // A server-rendered no-data placeholder is the honest answer — never init
    // an empty chart over it.
    if (el.querySelector(".nodata")) return;

    var data = window.__pageData;
    var fig = data && data.figures ? data.figures[key] : undefined;
    if (!fig || !fig.value) {
      // Genuinely absent figure: render the same honest placeholder the server
      // would have, so the box reads as "no data", not broken.
      el.innerHTML =
        '<div class="nodata">No published data for this measure.</div>';
      return;
    }

    try {
      el.setAttribute("aria-label", chartLabel(el, key));
      charts[key] = echarts.init(el);
      charts[key].setOption(figureOption(key, fig.value));
      window.addEventListener("resize", function () {
        if (charts[key]) charts[key].resize();
      });
    } catch (err) {
      // One bad figure never takes down the page.
      charts[key] = null;
      if (window.console && typeof console.warn === "function") {
        console.warn("foi-charts: could not render chart '" + key + "'", err);
      }
    }
  }

  // init — mount every .chartbox on the page.
  function init() {
    document.querySelectorAll(".chartbox").forEach(renderChart);
  }

  // wireFilters — LIVE FILTERS (wired in Task 4). This task ships the
  // signature and the read-only contract only.
  //
  // Contract: a filter SELECTS or RE-GROUPS rows from window.__pageData.facts
  // (the platform-derived canonical facts) and re-renders the charts from that
  // subset. It NEVER sums into a new aggregate the platform did not derive.
  // The option values ship in window.__pageData.filters.
  function wireFilters() {
    // No-op in Task 3: tolerate a page with no .filters row, and document the
    // contract for Task 4, which reads the selects and re-runs renderChart.
    var row = document.querySelector(".filters");
    if (!row) return;
    // Task 4: bind change handlers on row.querySelectorAll("select") that
    // re-filter window.__pageData.facts and re-render each chartbox.
  }

  window.FoiCharts = { init: init, wireFilters: wireFilters };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      init();
      wireFilters();
    });
  } else {
    init();
    wireFilters();
  }
})();
