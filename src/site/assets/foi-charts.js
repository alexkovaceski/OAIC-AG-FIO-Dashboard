/* foi-charts.js — ECharts init + live filters for the FOI Insights pages.

 * Reads window.__pageData (the platform-computed figures + canonical facts,
 * emitted by site/pages.py into a <script> before </body>), mounts an ECharts
 * instance on every `.chartbox` (keyed by its data-figure attribute), and wires
 * the live filter bar (Task 4).
 *
 * Filter contract: a filter SELECTS rows from window.__pageData.facts and
 * RE-DERIVES each figure from that subset — but only when the re-derivation
 * reproduces a figure the platform already derived for the same subset. It
 * never computes a new aggregate. Every figure the platform derived consumes
 * the bucket="total" rows (the trend = total per FY; the top-N = total for one
 * FY), so a selection that removes those rows (a personal/other type filter) has
 * no platform-derived figure — the chart shows an honest note that the facts
 * are unchanged rather than inventing a new total.
 *
 * A `.chartbox` that already holds a server-rendered `.nodata` placeholder is
 * left untouched — the honest "no data" text is more truthful than an empty
 * chart initialised over it. One bad figure never takes down the page.
 */
(function () {
  "use strict";

  // Brand palette (validated categorical slots — see site.css tokens).
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

  var charts = {};       // figure key -> live ECharts instance (null = dead)
  var resizeWired = {};  // figure key -> true once its resize listener exists

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

  // attachResize — one resize listener per figure key, ever. The charts[key]
  // truthiness guard inside the listener means a disposed chart is never
  // resized, and the resizeWired guard means repeated filter re-renders never
  // stack listeners on window.
  function attachResize(key) {
    if (resizeWired[key]) return;
    resizeWired[key] = true;
    window.addEventListener("resize", function () {
      if (charts[key]) charts[key].resize();
    });
  }

  // mountChart — (re)mount one ECharts instance on a chartbox from a
  // figureOption-shaped {categories, series} value. Any live instance is
  // disposed first, so echarts.init on an already-initialised DOM never warns
  // and stale canvas state is cleared before re-init.
  function mountChart(el, key, figValue) {
    if (charts[key]) {
      charts[key].dispose();
      charts[key] = null;
    }
    el.innerHTML = "";
    el.setAttribute("aria-label", chartLabel(el, key));
    charts[key] = echarts.init(el);
    charts[key].setOption(figureOption(key, figValue));
    attachResize(key);
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
      mountChart(el, key, fig.value);
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

  // --- live filters (Task 4) ------------------------------------------------

  // TREND_MEASURES — figure key -> the fact measure its FY series sums. Only
  // the single-measure trends that appear on the data pages are re-derivable;
  // any other key falls back to the honest "no derived aggregate" note.
  var TREND_MEASURES = {
    requests_received_trend: "received",
    requests_finalised_trend: "finalised",
  };

  // TOP_N — figure key -> {measure, fy}. The top-N figures pin one FY (the
  // latest complete annual-file year); a filter that removes that FY's rows
  // makes the figure non-recomputable.
  var TOP_N = {
    received_top20: { measure: "received", fy: "2024-25" },
    decided_top20: { measure: "decided", fy: "2024-25" },
  };

  // rederiveFigure — recompute a figure from a subset of facts using the SAME
  // derivation the platform used (annual quarter=None rows, bucket="total" for
  // trends; a pinned FY, bucket="total" for the top-N). Returns a
  // figureOption-shaped {categories, series}, or undefined when the selection
  // removes the rows the figure consumes (e.g. a personal/other type filter
  // takes out every bucket="total" row, and the platform never derived a
  // personal-only total). It never invents an aggregate — every value is a
  // sum of published fact rows the platform would have summed itself.
  function rederiveFigure(key, facts) {
    var i, row, by, cats, ranked, measure, pin, vals, nonNull;
    if (TREND_MEASURES[key]) {
      measure = TREND_MEASURES[key];
      by = {};
      cats = [];
      for (i = 0; i < facts.length; i++) {
        row = facts[i];
        if (row.quarter !== null) continue;
        if (cats.indexOf(row.fy) === -1) cats.push(row.fy);
        if (row.measure === measure && row.bucket === "total") {
          by[row.fy] = (by[row.fy] || 0) + row.value;
        }
      }
      cats.sort();
      if (!cats.length) return undefined;
      vals = cats.map(function (y) {
        return by[y] !== undefined ? Math.round(by[y]) : null;
      });
      // A selection that removes every bucket="total" row for the measure (e.g.
      // a personal/other type filter) yields only nulls — the platform never
      // derived a non-total trend, so there is no figure to recompute.
      nonNull = vals.some(function (v) { return v !== null; });
      if (!nonNull) return undefined;
      return { categories: cats, series: [{ name: measure, values: vals }] };
    }
    if (TOP_N[key]) {
      pin = TOP_N[key];
      by = {};
      for (i = 0; i < facts.length; i++) {
        row = facts[i];
        if (row.fy !== pin.fy || row.measure !== pin.measure ||
            row.bucket !== "total") continue;
        by[row.agency_name] = (by[row.agency_name] || 0) + row.value;
      }
      ranked = Object.keys(by).map(function (a) {
        return { name: a, v: by[a] };
      }).sort(function (a, b) { return b.v - a.v; }).slice(0, 20);
      if (!ranked.length) return undefined;
      return {
        categories: ranked.map(function (x) { return x.name; }),
        series: [{ name: pin.measure,
                   values: ranked.map(function (x) { return Math.round(x.v); }) }],
      };
    }
    return undefined;
  }

  // showNote — replace a chartbox's live chart with the honest "facts
  // unchanged" note: a filter can't conjure a new aggregate the platform did
  // not derive, so the box says so and the underlying facts stay untouched.
  function showNote(el, key, rowCount) {
    if (charts[key]) {
      charts[key].dispose();
      charts[key] = null;
    }
    el.innerHTML =
      '<div class="nodata">No published aggregate for this filter selection. ' +
      'The underlying ' + rowCount.toLocaleString() +
      ' fact rows are unchanged.</div>';
    el.setAttribute("aria-label", chartLabel(el, key));
  }

  // mountFigure — mount a figure value on one chartbox, or fall back to the
  // honest note. Shared by the filter paths; never touches server-rendered
  // placeholders (a box whose figure has no data stays on its own honest text).
  function mountFigure(el, key, figValue, rowCount) {
    if (figValue) {
      mountChart(el, key, figValue);
    } else {
      showNote(el, key, rowCount);
    }
  }

  // applyFilters — read the three selects, filter __pageData.facts, and
  // re-render every chartbox. With no active filter the platform's original
  // figures (the aggregate view) are restored. With a filter, each figure is
  // re-derived from the selected rows where the platform's derivation still
  // holds; where it cannot, the box shows the note instead of a made-up total.
  function applyFilters() {
    var data = window.__pageData;
    var row = document.querySelector(".filters");
    if (!data || !data.facts || !row) return;

    var active = {};
    row.querySelectorAll("select").forEach(function (sel) {
      if (sel.value !== "") active[sel.dataset.filter] = sel.value;
    });

    var boxes = document.querySelectorAll(".chartbox");
    var box, key, fig, err;

    if (Object.keys(active).length === 0) {
      // Restore the platform's original figures.
      boxes.forEach(function (el) {
        key = el.dataset.figure;
        if (!key) return;
        fig = data.figures ? data.figures[key] : undefined;
        try {
          mountFigure(el, key, fig && fig.value, data.facts.length);
        } catch (e) {
          err = e;
          charts[key] = null;
          if (window.console && typeof console.warn === "function") {
            console.warn("foi-charts: could not render chart '" + key + "'", err);
          }
        }
      });
      return;
    }

    var facts = data.facts.filter(function (f) {
      if (active.agency && f.agency_name !== active.agency) return false;
      if (active.type && f.bucket !== active.type) return false;
      if (active.fy && f.fy !== active.fy) return false;
      return true;
    });

    boxes.forEach(function (el) {
      key = el.dataset.figure;
      if (!key) return;
      var derived;
      try {
        derived = rederiveFigure(key, facts);
        mountFigure(el, key, derived, facts.length);
      } catch (e) {
        err = e;
        charts[key] = null;
        if (window.console && typeof console.warn === "function") {
          console.warn("foi-charts: could not render chart '" + key + "'", err);
        }
      }
    });
  }

  // wireFilters — bind a change handler on each filter select; re-filter the
  // facts and re-render the charts from the selection. Tolerates a page with
  // no .filters row (no-data pages render no filter bar).
  function wireFilters() {
    var row = document.querySelector(".filters");
    if (!row) return;
    row.querySelectorAll("select").forEach(function (sel) {
      sel.addEventListener("change", applyFilters);
    });
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
