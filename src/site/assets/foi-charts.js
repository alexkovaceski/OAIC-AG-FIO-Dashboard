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
 * Axis contract: a filtered figure is drawn against an interval that never
 * SHRINKS below the unfiltered baseline (so two selections stay comparable)
 * and never falls below the selection's own largest value (so no bar or point
 * is ever drawn shorter than the number it represents). ECharts clips a series
 * at axis.max, so those two rules are the same rule: pin to the larger of the
 * two, and say so in the note when the interval had to grow. The UNFILTERED
 * view is pinned to its own maximum for the same reason — left to auto-scale
 * it picked a rounded top (7,000 for a 6,228 maximum) and jumped to an exact
 * one on the first selection. A single-agency view is the deliberate
 * exception: it auto-scales, and its note says so.
 *
 * Every number the engine prints is rounded the way the server rounds it
 * (half to EVEN, Python's rule) so the chart and the published figure can
 * never disagree in the last digit.
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

  // the server's own placeholder copy, verbatim (site/pages.py _chart_container)
  var NO_DATA_TEXT =
    "No published data for this measure. The source files do not report this " +
    "breakdown for the financial years covered.";

  var REDUCED_MOTION =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var charts = {};       // figure key -> live ECharts instance (null = dead)
  var resizeWired = {};  // figure key -> true once its resize listener exists
  var baselineMax = {};  // figure key -> max value of the unfiltered figure
  var mounted = {};      // figure key -> {el, horizontal} for the resize relayout

  function specFor(key) {
    var data = window.__pageData;
    return (data && data.specs && data.specs[key]) || null;
  }

  // roundTo — a port of Python's round(x, dp) for the same double: round to
  // nearest on the value the double actually holds, ties to EVEN. The server
  // rounds counts with round(v) and ratios with round(x, 1), so any other rule
  // makes the chart and the published figure disagree in the last digit.
  //
  // Two traps, both measured (2,003,000 num/den pairs, den <= 2000):
  //   * Scaling by 10 FIRST invents ties. 100*1009/2000 is held as
  //     50.450000000000003, which Python rounds UP to 50.5 — but x * 10 lands
  //     on exactly 504.5, so a tie test after the multiply saw a tie and
  //     half-to-even gave 50.4. 402 of the 2,003,000 pairs diverged this way.
  //   * toFixed alone breaks the real ties. It rounds half AWAY from zero
  //     (ECMA-262: "if there are two such n, pick the larger"), so 6.25 becomes
  //     6.3 where Python gives 6.2. 17 of the 2,170 operand pairs reachable on
  //     today's frame sit exactly on such a tie.
  // So: detect the tie by scaling by a power of TWO (exact, never invents one),
  // and let toFixed — which reads the double's exact decimal value — do the
  // rest. Verified identical to Python's round() over all 2,003,000 pairs at
  // dp=0 and dp=1 (sha256 of the packed results matches).
  function roundTo(x, dp) {
    var f = dp ? Math.pow(10, dp) : 1;
    // an exact tie is an odd multiple of 1/2^(dp+1) — the only doubles whose
    // exact value ends in a 5 one digit past dp
    var halves = x * Math.pow(2, dp + 1);
    if (halves === Math.floor(halves) && halves % 2 !== 0) {
      var down = Math.floor(x * f);
      return (down % 2 === 0 ? down : down + 1) / f;
    }
    return dp ? Number(x.toFixed(dp)) : Math.round(x);
  }

  // seriesMax — the largest numeric value across a figure's series (the pinned
  // -axis baseline, and the floor no axis may sit below). null when the figure
  // has no numeric values.
  function seriesMax(fig) {
    var max = null;
    ((fig && fig.series) || []).forEach(function (s) {
      (s.values || []).forEach(function (v) {
        if (v !== null && v !== undefined && (max === null || v > max)) max = v;
      });
    });
    return max;
  }

  // figHasData — a figure OBJECT is always truthy; what matters is whether any
  // series carries values. An empty-series figure must keep the honest
  // placeholder rather than mount a blank canvas over it.
  function figHasData(fig) {
    return !!fig && ((fig.series || []).some(function (s) {
      return (s.values || []).length > 0;
    }));
  }

  // gridLeft — the label gutter for a horizontal ranking. A fixed 230px starved
  // the plot on a phone: at the 900px breakpoint a 390px viewport leaves a
  // ~294px chartbox, and 230 + 30 left ~34px of bar for a 20-agency ranking.
  // The gutter is a share of the container, clamped so a desktop still fits
  // full agency names.
  function gridLeft(width) {
    if (!width) return 230;
    return Math.max(90, Math.min(230, Math.round(width * 0.42)));
  }

  function labelWidth(left) {
    return Math.max(70, left - 20);
  }

  // figureOption — map {categories, series} to an ECharts option.
  // opts: { horizontal: bool, pinMax: number|null, asTrend: bool }
  // width: the mount's pixel width, for the responsive ranking gutter.
  // Chart type comes from the spec kind, except that the degenerate one-agency
  // view IS a trend whatever its spec says (opts.asTrend). A key with no spec
  // at all falls back to the legacy key-suffix heuristic — a defensive default
  // for a figure shipped without a spec entry, not a live code path (every
  // chart page ships a spec per figure; the AI-built dashboards are rendered by
  // agentic/render.py into `.chart` divs and never load this file).
  function figureOption(key, fig, opts, width) {
    opts = opts || {};
    var spec = specFor(key);
    var kind = spec ? spec.kind : null;
    var type;
    if (opts.asTrend) type = "line";
    else if (kind === "top_n") type = "bar";
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
      if (type === "line") {
        opt.smooth = true;
        // a single-year selection is one point: draw a symbol big enough to read
        if (cats.length === 1) opt.symbolSize = 9;
      }
      if (type === "bar" && horizontal) opt.barMaxWidth = 28;
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
      // top-N: agencies on the y axis, rank 1 on top, room for full names.
      // interval: 0 is load-bearing — without it ECharts thins the category
      // labels to fit and a 20-bar ranking renders with about half its names.
      var left = gridLeft(width);
      catAxis.inverse = true;
      catAxis.axisLabel = {
        color: PAL.ink, fontSize: 11, interval: 0,
        width: labelWidth(left), overflow: "truncate",
      };
      return {
        color: colors,
        animation: !REDUCED_MOTION,
        aria: { enabled: true },
        tooltip: { trigger: "axis" },
        legend: series.length > 1 ? { top: 0 } : undefined,
        grid: { left: left, right: 30, top: 10, bottom: 30 },
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
      var chart = charts[key];
      var m = mounted[key];
      if (!chart) return;
      if (m && m.horizontal) {
        // the gutter is a share of the container, so a rotate or a window drag
        // must re-derive it — resize() alone would keep the old pixel value
        var left = gridLeft(m.el.clientWidth);
        chart.setOption({
          grid: { left: left },
          yAxis: { axisLabel: { width: labelWidth(left) } },
        });
      }
      chart.resize();
    });
  }

  function mountChart(el, key, figValue, opts) {
    if (charts[key]) {
      charts[key].dispose();
      charts[key] = null;
    }
    delete el.dataset.jsNote;
    el.innerHTML = "";
    // a 20-band ranking needs the taller box or interval:0 stacks its labels.
    // The server already writes `topn` on a top_n chartbox (pages.py
    // _chart_container), so this add is normally a no-op — it stays because the
    // REMOVE is load-bearing: a one-agency selection turns the ranking into a
    // trend, and the box goes back to 320px.
    if (opts.horizontal) el.classList.add("topn");
    else el.classList.remove("topn");
    el.setAttribute("aria-label", chartLabel(el, key));
    mounted[key] = { el: el, horizontal: !!opts.horizontal };
    charts[key] = echarts.init(el);
    charts[key].setOption(figureOption(key, figValue, opts, el.clientWidth));
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

  // noData — replace a chartbox with an honest placeholder. dataset.jsNote
  // marks it JS-injected, so a later render may replace it; a SERVER-rendered
  // placeholder carries no such mark and renderFigure leaves it alone.
  // The message is set as text, never concatenated into markup.
  function noData(el, key, text) {
    if (charts[key]) {
      charts[key].dispose();
      charts[key] = null;
    }
    mounted[key] = null;
    setNote(el, null);
    el.classList.remove("topn");
    el.dataset.jsNote = "1";
    el.innerHTML = '<div class="nodata"></div>';
    el.firstChild.textContent = text;
    el.setAttribute("aria-label", chartLabel(el, key));
  }

  // --- the derivation engine ------------------------------------------------

  // dimFilter — apply the shared row dimensions. Agency and portfolio always
  // apply; which of the other two apply is the kind's call, declared by the
  // caller's `skip`:
  //   trend / ratio_trend — {type: true}. fy IS applied (selecting a year
  //     narrows the category axis to that year, and the caller emits the note
  //     that explains the resulting single point); type is skipped because
  //     those kinds carry the bucket through trendSeries instead.
  //   top_n — {type: true, fy: true}. The ranking loop consumes fy as the
  //     ranking year, and the degenerate one-agency view plots every published
  //     year (its note says the FY selection is not applied there).
  // The agency dimension has no skip: in the degenerate view it is exactly what
  // selects the agency's rows, and in the ranking loop no agency can be
  // selected — the degenerate guard returned before that point.
  function dimFilter(facts, active, skip) {
    skip = skip || {};
    return facts.filter(function (f) {
      if (active.agency && f.agency_name !== active.agency) return false;
      if (active.portfolio && f.portfolio !== active.portfolio) return false;
      if (!skip.type && active.type && f.bucket !== active.type) return false;
      if (!skip.fy && active.fy && f.fy !== active.fy) return false;
      return true;
    });
  }

  // isReportingAgency — the client twin of stats/catalog.py's
  // is_reporting_agency, and it must stay identical to it, BOTH halves.
  // "Total" is a national total-level fact, not an agency; an x-prefixed name
  // is the normaliser's placeholder row. The frame carries no x-prefixed
  // agency name today, so that half is inert — it is here because the two
  // engines are documented as mirrors, and a guard that is only inert cannot
  // be relied on to stay correct when one appears.
  function isReportingAgency(name) {
    return !!name && name.toLowerCase() !== "total" && name.charAt(0) !== "x";
  }

  // trendSeries — per-FY sums of one measure over annual rows for one bucket.
  // Returns {cats, values} with null for FYs the selection has no rows for.
  function trendSeries(facts, measure, bucket) {
    var totalsByFy = {}, cats = [], idx, row;
    for (idx = 0; idx < facts.length; idx++) {
      row = facts[idx];
      if (row.quarter !== null) continue;
      if (cats.indexOf(row.fy) === -1) cats.push(row.fy);
      if (row.measure === measure && row.bucket === bucket) {
        totalsByFy[row.fy] = (totalsByFy[row.fy] || 0) + row.value;
      }
    }
    cats.sort();
    return {
      cats: cats,
      values: cats.map(function (fy) {
        return totalsByFy[fy] !== undefined ? totalsByFy[fy] : null;
      }),
    };
  }

  function anyNumeric(values) {
    return values.some(function (v) { return v !== null; });
  }

  // oneFyNote — an FY selection narrows a trend or a ratio to a single point.
  // That renders honestly, but a single dot on a full axis needs the same
  // explanation the one-agency ranking gets, or it reads as a broken chart.
  function oneFyNote(cats, active) {
    if (cats.length !== 1 || !active.fy) return null;
    return "FY " + active.fy + " selected: a trend across a single financial " +
      "year is one point. Clear the FY filter to see the whole series.";
  }

  // rankingPoolNote — how many agencies the ranking was drawn from, counted
  // under the SAME predicate that produced the ranking. The earlier footnote
  // subtracted this count from the GLOBAL agency list and described the
  // remainder as a reporting failure. It was wrong twice: under a portfolio
  // filter the remainder is mostly agencies in other portfolios, and the
  // genuinely absent ones are overwhelmingly abolished, renamed or not yet
  // created in the selected year. Numerator and denominator must come from the
  // same rows, and a compliance claim needs evidence the data does not carry —
  // so this states the pool, and nothing about the agencies outside it.
  function rankingPoolNote(reported, fy, active) {
    return "Ranked from the " + reported + " agenc" +
      (reported === 1 ? "y" : "ies") +
      (active.portfolio ? " in the " + active.portfolio + " portfolio" : "") +
      " with published FY " + fy + " data for this measure" +
      (active.type ? " (type: " + active.type + ")" : "") + ".";
  }

  // rederiveFigure — recompute a figure from the page's fact slice by
  // interpreting its spec under the active filters. Returns
  //   {fig, note}          — a mountable figure (+ optional fignote text)
  //   undefined            — no published rows for this selection (honest note)
  function rederiveFigure(key, spec, facts, active) {
    var bucket = active.type || "total";
    var rows, trend, idx, series, den, values, parts, fy, totalsByAgency,
        ranked, reported;

    if (spec.kind === "trend" || spec.kind === "multi_trend") {
      rows = dimFilter(facts, active, { type: true });
      series = spec.measures.map(function (measure) {
        trend = trendSeries(rows, measure, bucket);
        return { name: measure, values: trend.values, _cats: trend.cats };
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
              return v === null ? null : roundTo(v, 0);
            }) };
          }),
        },
        note: oneFyNote(cats, active),
      };
    }

    if (spec.kind === "ratio_trend") {
      rows = dimFilter(facts, active, { type: true });
      var numeratorTrends = spec.numerators.map(function (measure) {
        return trendSeries(rows, measure, bucket);
      });
      den = trendSeries(rows, spec.denominator, bucket);
      if (!den.cats.length) return undefined;
      values = [];
      for (idx = 0; idx < den.cats.length; idx++) {
        parts = numeratorTrends.map(function (numeratorTrend) {
          return numeratorTrend.values[idx];
        });
        var denominator = den.values[idx];
        if (parts.some(function (p) { return p === null; }) || !denominator) {
          values.push(null);
        } else {
          // the server computes round(100 * sum(parts) / d, 1) — same operand
          // order, same rounding rule, so the two views agree to the digit
          values.push(roundTo(100 * parts.reduce(function (sum, part) {
            return sum + part;
          }, 0) / denominator, 1));
        }
      }
      if (!anyNumeric(values)) return undefined;
      return { fig: { categories: den.cats,
                      series: [{ name: spec.name, values: values }] },
               note: oneFyNote(den.cats, active) };
    }

    if (spec.kind === "top_n") {
      // agency filter: a one-agency ranking is meaningless — show that
      // agency's own FY trend for the measure instead (degenerate guard).
      // trendSeries reads annual rows only, so the golden single-quarter rows
      // (the "Total" pseudo-agency) can never reach this path: selecting it
      // yields no annual rows and falls through to the honest no-data note.
      if (active.agency) {
        rows = dimFilter(facts, active, { type: true, fy: true });
        trend = trendSeries(rows, spec.measure, bucket);
        if (!trend.cats.length || !anyNumeric(trend.values)) return undefined;
        // the FY selection is dropped on this path (the trend spans every
        // published year). Saying so is the same rule the one-year trend note
        // follows: a select that visibly ignores its input reads as broken.
        return {
          fig: { categories: trend.cats,
                 series: [{ name: spec.measure, values: trend.values.map(
                   function (v) { return v === null ? null : roundTo(v, 0); }) }] },
          note: "Showing the FY trend for " + active.agency +
                " (a one-agency ranking is not a top-" + spec.n + ")." +
                (active.fy
                  ? " The FY " + active.fy + " selection is not applied here: " +
                    "the trend covers every published year."
                  : ""),
          asTrend: true,
        };
      }
      fy = active.fy || spec.default_fy;
      rows = dimFilter(facts, active, { type: true, fy: true });
      totalsByAgency = {};
      for (idx = 0; idx < rows.length; idx++) {
        var row = rows[idx];
        // An FY ranking sums ANNUAL rows only and ranks real agencies only.
        // The golden Q1 rows are a single-quarter NATIONAL figure published
        // under a "Total" pseudo-agency: left in, it outranks every agency in
        // the latest FY and puts one quarter's number on a bar chart labelled
        // "basis: financial year". Both guards mirror the platform — the FY
        // series skip quarter-carrying rows, and isReportingAgency is the twin
        // of the predicate every per-agency op in stats/ applies.
        if (row.quarter !== null) continue;
        if (!isReportingAgency(row.agency_name)) continue;
        if (row.fy !== fy || row.measure !== spec.measure ||
            row.bucket !== bucket) continue;
        totalsByAgency[row.agency_name] =
          (totalsByAgency[row.agency_name] || 0) + row.value;
      }
      ranked = Object.keys(totalsByAgency).map(function (agency) {
        return { name: agency, total: totalsByAgency[agency] };
      }).sort(function (left, right) {
        return right.total - left.total;
      }).slice(0, spec.n);
      if (!ranked.length) return undefined;
      // B8 footnote: the ranking pool, on the same rows the ranking used
      reported = Object.keys(totalsByAgency).length;
      return {
        fig: {
          categories: ranked.map(function (entry) { return entry.name; }),
          series: [{ name: spec.measure, values: ranked.map(function (entry) {
            return roundTo(entry.total, 0);
          }) }],
        },
        note: rankingPoolNote(reported, fy, active),
      };
    }

    return undefined;
  }

  function showNote(el, key, rowCount) {
    noData(el, key,
      "No published aggregate for this filter selection. The underlying " +
      rowCount.toLocaleString() + " fact rows are unchanged.");
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
        // a figure object with empty series is NOT data — mounting it would
        // paint a blank canvas over an honest placeholder
        if (!figHasData(fig && fig.value)) {
          noData(el, key, NO_DATA_TEXT);
          return;
        }
        if (baselineMax[key] === undefined) {
          baselineMax[key] = seriesMax(fig.value);
        }
        var isTopN = spec && spec.kind === "top_n";
        // pin the default view to its own maximum, so the interval a reader
        // starts from is the one every filtered view is compared against
        mountChart(el, key, fig.value,
                   { horizontal: isTopN, pinMax: baselineMax[key] });
        if (isTopN) {
          // the ranking-pool footnote applies to the default view too
          var derived = rederiveFigure(key, spec, data.facts, {});
          setNote(el, (derived && derived.note) || null);
        } else {
          setNote(el, null);
        }
        return;
      }

      if (!spec) { showNote(el, key, data.facts.length); return; }
      var out = rederiveFigure(key, spec, data.facts, active);
      if (!out) { showNote(el, key, data.facts.length); return; }
      // the axis may not shrink below the unfiltered baseline (selections stay
      // comparable) and may not sit below this selection's own largest value
      // (ECharts CLIPS a series at axis.max, so a lower pin would draw a real
      // number short). An agency view auto-scales by design, and auto-scaling
      // cannot truncate either.
      var own = seriesMax(out.fig);
      var pin = active.agency ? null
        : (Math.max(baselineMax[key] || 0, own === null ? 0 : own) || null);
      var horizontal = spec.kind === "top_n" && !out.asTrend;
      mountChart(el, key, out.fig, { horizontal: horizontal, pinMax: pin,
                                     asTrend: !!out.asTrend });
      var notes = [];
      if (out.note) notes.push(out.note);
      if (active.agency) notes.push("Axis rescaled for the selected agency.");
      if (pin && baselineMax[key] && pin > baselineMax[key]) {
        notes.push("Axis extended past the unfiltered maximum to fit this " +
                   "selection.");
      }
      setNote(el, notes.length ? notes.join(" ") : null);
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
