/* foi-charts.js — spec-driven ECharts engine for the Bluebird FOI Insights pages.
 *
 * Reads window.__pageData: platform-computed figures, their FIGURE_SPECS, a
 * facts slice scoped to the page's measures, and the global filter options.
 * Mounts ECharts on every `.chartbox`, wires the filter bar, and re-derives
 * figures from the fact slice by interpreting each figure's spec — the same
 * vocabulary the server's stats/catalog.py engine interprets.
 *
 * Filter contract: a filter SELECTS published fact rows and re-derives the
 * figure with the SAME derivation the platform uses (per-FY bucket sums, ratio
 * of sums, one-FY agency ranking). It never invents an aggregate: a selection
 * with no published rows shows an honest note. Bucket-scoped derivations
 * (personal/other) are platform derivations too — every summed row is a
 * published fact (spec S2.2, feedback B2).
 *
 * A `.chartbox` holding a server-rendered `.nodata` placeholder is left
 * untouched. One bad figure never takes down the page.
 */
(function () {
  "use strict";

  var PAL = {
    violet: "#5d4fff", blue: "#0787d9", sky: "#0ea5e9",
    indigo: "#6366f1", slate: "#334155", purple: "#7c3aed",
    ink: "#0f1e33",
    hair: "#e4eaf2",
  };
  var SLOTS = ["violet", "blue", "sky", "indigo", "slate", "purple"];

  var REDUCED_MOTION =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var charts = {};       // figure key -> live ECharts instance (null = dead)
  var resizeWired = {};  // figure key -> true once its resize listener exists
  var baselineMax = {};  // figure key -> max value of the unfiltered figure

  function specFor(key) {
    var data = window.__pageData;
    return (data && data.specs && data.specs[key]) || null;
  }

  // seriesMax — the largest numeric value across a figure's series (for the
  // pinned-axis baseline). null when the figure has no numeric values.
  function seriesMax(fig) {
    var max = null;
    (fig.series || []).forEach(function (s) {
      (s.values || []).forEach(function (v) {
        if (v !== null && v !== undefined && (max === null || v > max)) max = v;
      });
    });
    return max;
  }

  // figureOption — map {categories, series} to an ECharts option.
  // opts: { horizontal: bool, pinMax: number|null }
  // Chart type comes from the spec kind; keys without a spec (AI-built
  // dashboard figures) fall back to the legacy key-suffix heuristic.
  function figureOption(key, fig, opts) {
    opts = opts || {};
    var spec = specFor(key);
    var kind = spec ? spec.kind : null;
    var type;
    if (kind === "top_n") type = "bar";
    else if (kind) type = "line";
    else type = key.endsWith("_trend") || key.indexOf("_change") > -1
      ? "line" : "bar";
    var horizontal = !!opts.horizontal;
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
    var manyCats = cats.length > 8;

    var catAxis = {
      type: "category",
      data: cats,
      axisLine: { lineStyle: { color: PAL.hair } },
      axisLabel: { color: PAL.ink },
    };
    var valAxis = {
      type: "value",
      axisLine: { show: false },
      splitLine: { lineStyle: { color: PAL.hair } },
      axisLabel: { color: PAL.ink },
    };
    if (opts.pinMax) valAxis.max = opts.pinMax;

    if (horizontal) {
      // top-N: agencies on the y axis, rank 1 on top, room for full names
      catAxis.inverse = true;
      catAxis.axisLabel = {
        color: PAL.ink, fontSize: 11, width: 210, overflow: "truncate",
      };
      return {
        color: colors,
        animation: !REDUCED_MOTION,
        aria: { enabled: true },
        tooltip: { trigger: "axis" },
        legend: series.length > 1 ? { top: 0 } : undefined,
        grid: { left: 230, right: 30, top: 10, bottom: 30 },
        xAxis: valAxis,
        yAxis: catAxis,
        series: series,
      };
    }
    if (manyCats) {
      catAxis.axisLabel = {
        color: PAL.ink, interval: 0, rotate: 30, fontSize: 10,
      };
    }
    return {
      color: colors,
      animation: !REDUCED_MOTION,
      aria: { enabled: true },
      tooltip: { trigger: "axis" },
      legend: series.length > 1 ? { top: 0 } : undefined,
      grid: { left: 50, right: 20, top: 30, bottom: manyCats ? 70 : 40 },
      xAxis: catAxis,
      yAxis: valAxis,
      series: series,
    };
  }

  function chartLabel(el, key) {
    var section = el.parentElement;
    var h = section && section.querySelector("h2");
    var text = h && h.textContent ? h.textContent.trim() : "";
    return text || key;
  }

  function attachResize(key) {
    if (resizeWired[key]) return;
    resizeWired[key] = true;
    window.addEventListener("resize", function () {
      if (charts[key]) charts[key].resize();
    });
  }

  function mountChart(el, key, figValue, opts) {
    if (charts[key]) {
      charts[key].dispose();
      charts[key] = null;
    }
    delete el.dataset.jsNote;
    el.innerHTML = "";
    el.setAttribute("aria-label", chartLabel(el, key));
    charts[key] = echarts.init(el);
    charts[key].setOption(figureOption(key, figValue, opts));
    attachResize(key);
  }

  // setNote — one managed note line per figure card, after the chartbox.
  // Text content only (never HTML) — agency names flow through here.
  function setNote(el, text) {
    var section = el.parentElement;
    if (!section) return;
    var note = section.querySelector(".fignote");
    if (!text) {
      if (note) note.remove();
      return;
    }
    if (!note) {
      note = document.createElement("p");
      note.className = "fignote";
      el.insertAdjacentElement("afterend", note);
    }
    note.textContent = text;
  }

  // --- the derivation engine ------------------------------------------------

  // dimFilter — apply the shared row dimensions. Which dimensions apply is the
  // kind's call: trends consume fy as a category axis (skipFy), top-N consumes
  // fy as its ranking year (skipFy) and agency via the degenerate guard
  // (skipAgency handled by the caller).
  function dimFilter(facts, active, skip) {
    skip = skip || {};
    return facts.filter(function (f) {
      if (!skip.agency && active.agency && f.agency_name !== active.agency) return false;
      if (active.portfolio && f.portfolio !== active.portfolio) return false;
      if (!skip.type && active.type && f.bucket !== active.type) return false;
      if (!skip.fy && active.fy && f.fy !== active.fy) return false;
      return true;
    });
  }

  // trendSeries — per-FY sums of one measure over annual rows for one bucket.
  // Returns {cats, values} with null for FYs the selection has no rows for.
  function trendSeries(facts, measure, bucket) {
    var by = {}, cats = [], i, row;
    for (i = 0; i < facts.length; i++) {
      row = facts[i];
      if (row.quarter !== null) continue;
      if (cats.indexOf(row.fy) === -1) cats.push(row.fy);
      if (row.measure === measure && row.bucket === bucket) {
        by[row.fy] = (by[row.fy] || 0) + row.value;
      }
    }
    cats.sort();
    return {
      cats: cats,
      values: cats.map(function (y) {
        return by[y] !== undefined ? by[y] : null;
      }),
    };
  }

  function anyNumeric(values) {
    return values.some(function (v) { return v !== null; });
  }

  // rederiveFigure — recompute a figure from the page's fact slice by
  // interpreting its spec under the active filters. Returns
  //   {fig, note}          — a mountable figure (+ optional fignote text)
  //   undefined            — no published rows for this selection (honest note)
  function rederiveFigure(key, spec, facts, active) {
    var bucket = active.type || "total";
    var rows, t, i, series, den, values, parts, fy, by, ranked, universe,
        reported, missing;

    if (spec.kind === "trend" || spec.kind === "multi_trend") {
      rows = dimFilter(facts, active, { type: true, fy: false });
      // fy filter narrows the axis to that year; type handled via bucket
      series = spec.measures.map(function (m) {
        t = trendSeries(rows, m, bucket);
        return { name: m, values: t.values, _cats: t.cats };
      });
      if (!series.length || !series[0]._cats.length) return undefined;
      var cats = series[0]._cats;
      var ok = series.some(function (s) { return anyNumeric(s.values); });
      if (!ok) return undefined;
      return {
        fig: {
          categories: cats,
          series: series.map(function (s) {
            return { name: s.name, values: s.values.map(function (v) {
              return v === null ? null : Math.round(v);
            }) };
          }),
        },
      };
    }

    if (spec.kind === "ratio_trend") {
      rows = dimFilter(facts, active, { type: true, fy: false });
      var numT = spec.numerators.map(function (m) {
        return trendSeries(rows, m, bucket);
      });
      den = trendSeries(rows, spec.denominator, bucket);
      if (!den.cats.length) return undefined;
      values = [];
      for (i = 0; i < den.cats.length; i++) {
        parts = numT.map(function (t2) { return t2.values[i]; });
        var d = den.values[i];
        if (parts.some(function (p) { return p === null; }) || !d) {
          values.push(null);
        } else {
          values.push(Math.round(1000 * parts.reduce(function (a, b) {
            return a + b;
          }, 0) / d) / 10);
        }
      }
      if (!anyNumeric(values)) return undefined;
      return { fig: { categories: den.cats,
                      series: [{ name: spec.name, values: values }] } };
    }

    if (spec.kind === "top_n") {
      // agency filter: a one-agency ranking is meaningless — show that
      // agency's own FY trend for the measure instead (degenerate guard)
      if (active.agency) {
        rows = dimFilter(facts, active, { type: true, fy: true });
        t = trendSeries(rows, spec.measure, bucket);
        if (!t.cats.length || !anyNumeric(t.values)) return undefined;
        return {
          fig: { categories: t.cats,
                 series: [{ name: spec.measure, values: t.values.map(
                   function (v) { return v === null ? null : Math.round(v); }) }] },
          note: "Showing the FY trend for " + active.agency +
                " (a one-agency ranking is not a top-" + spec.n + "). " +
                "Axis rescaled for the selected agency.",
          asTrend: true,
        };
      }
      fy = active.fy || spec.default_fy;
      rows = dimFilter(facts, active, { type: true, fy: true });
      by = {};
      for (i = 0; i < rows.length; i++) {
        var r = rows[i];
        if (r.fy !== fy || r.measure !== spec.measure ||
            r.bucket !== bucket) continue;
        by[r.agency_name] = (by[r.agency_name] || 0) + r.value;
      }
      ranked = Object.keys(by).map(function (a) {
        return { name: a, v: by[a] };
      }).sort(function (a, b) { return b.v - a.v; }).slice(0, spec.n);
      if (!ranked.length) return undefined;
      // B8 footnote: agencies with no published row for (measure, fy)
      var data = window.__pageData;
      universe = (data.filters && data.filters.agencies || []).length;
      reported = Object.keys(by).length;
      missing = universe - reported;
      return {
        fig: {
          categories: ranked.map(function (x) { return x.name; }),
          series: [{ name: spec.measure, values: ranked.map(function (x) {
            return Math.round(x.v);
          }) }],
        },
        note: missing > 0
          ? missing + " of " + universe + " agencies reported no data for FY " +
            fy + " and are not ranked."
          : null,
      };
    }

    return undefined;
  }

  function showNote(el, key, rowCount) {
    if (charts[key]) {
      charts[key].dispose();
      charts[key] = null;
    }
    setNote(el, null);
    el.dataset.jsNote = "1"; // JS-injected note: the restore path may replace it
    el.innerHTML =
      '<div class="nodata">No published aggregate for this filter selection. ' +
      'The underlying ' + rowCount.toLocaleString() +
      ' fact rows are unchanged.</div>';
    el.setAttribute("aria-label", chartLabel(el, key));
  }

  // renderFigure — mount one figure under the current filter state.
  function renderFigure(el, key, active) {
    // a SERVER-rendered no-data placeholder is permanent (the figure has no
    // data at all); a JS-injected note (dataset.jsNote) must be replaceable
    // when filters clear, or the chart could never come back
    if (el.querySelector(".nodata") && !el.dataset.jsNote &&
        Object.keys(active).length === 0) return;
    var data = window.__pageData;
    var spec = specFor(key);
    var hasFilters = Object.keys(active).length > 0;

    try {
      if (!hasFilters) {
        var fig = data.figures ? data.figures[key] : undefined;
        if (!fig || !fig.value) {
          el.innerHTML =
            '<div class="nodata">No published data for this measure.</div>';
          return;
        }
        if (baselineMax[key] === undefined) {
          baselineMax[key] = seriesMax(fig.value);
        }
        var isTopN = spec && spec.kind === "top_n";
        mountChart(el, key, fig.value, { horizontal: isTopN, pinMax: null });
        if (isTopN && data.filters) {
          // B8 footnote on the default view too
          var derived = rederiveFigure(key, spec, data.facts, {});
          setNote(el, derived && derived.note || null);
        } else {
          setNote(el, null);
        }
        return;
      }

      if (!spec) { showNote(el, key, data.facts.length); return; }
      var out = rederiveFigure(key, spec, data.facts, active);
      if (!out) { showNote(el, key, data.facts.length); return; }
      var pin = !active.agency && baselineMax[key] ? baselineMax[key] : null;
      var horizontal = spec.kind === "top_n" && !out.asTrend;
      mountChart(el, key, out.fig, { horizontal: horizontal, pinMax: pin });
      var noteText = out.note || null;
      if (active.agency && !noteText) {
        noteText = "Axis rescaled for the selected agency.";
      }
      setNote(el, noteText);
    } catch (err) {
      charts[key] = null;
      if (window.console && typeof console.warn === "function") {
        console.warn("foi-charts: could not render chart '" + key + "'", err);
      }
    }
  }

  function currentFilters() {
    var active = {};
    var row = document.querySelector(".filters");
    if (!row) return active;
    row.querySelectorAll("select").forEach(function (sel) {
      if (sel.value !== "") active[sel.dataset.filter] = sel.value;
    });
    return active;
  }

  function renderAll() {
    var active = currentFilters();
    document.querySelectorAll(".chartbox").forEach(function (el) {
      var key = el.dataset.figure;
      if (!key) return;
      renderFigure(el, key, active);
    });
  }

  function init() { renderAll(); }

  function wireFilters() {
    var row = document.querySelector(".filters");
    if (!row) return;
    row.querySelectorAll("select").forEach(function (sel) {
      sel.addEventListener("change", renderAll);
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
