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
 * one on the first selection. Two deliberate exceptions auto-scale and say so
 * in the note: a single-agency view, and a PART-year selection. The part-year
 * exception is the one the comparability rule gets wrong — holding the axis
 * only aids comparison between like windows, and nine months against a full
 * year is not one. Measured 2026-08-26: selecting the part year (a nine-
 * month cumulative file) on received_top20 drew a 12,264 leader against the
 * latest-complete-year pin of 17,120, i.e. at 72% height, which reads as a
 * collapse in FOI activity that did not happen.
 *
 * Category contract: a trend's category axis is the FULL published axis, taken
 * from the unfiltered figure, with null where the selection has no row for a
 * year. It is not rebuilt from the filtered rows: 230 of the 433 agencies with
 * annual rows do not span all seven FYs (measured 2026-08-26), and building
 * the axis from their own rows dropped the gap years entirely — four points
 * spanning six years rendered evenly spaced and connected under smooth:true,
 * which asserts a continuity the data does not carry. This is the client half
 * of the promise site/pages.py makes in its module docstring: "a figure's
 * missing year renders as '—', never '0'".
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

  // what the box says when the RENDER failed — distinct from NO_DATA_TEXT,
  // because a chart that could not be drawn is not a measure the publisher
  // does not report, and saying so would be a data claim the frame contradicts
  var RENDER_FAILED_TEXT =
    "This chart could not be drawn in your browser. The published figures " +
    "behind it are unchanged — the API page serves the same numbers.";

  var REDUCED_MOTION =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var charts = {};       // figure key -> live ECharts instance (null = dead)
  var resizeWired = {};  // figure key -> true once its resize listener exists
  var baselineMax = {};  // figure key -> max value of the unfiltered figure
  var mounted = {};      // figure key -> {el, horizontal} for the resize relayout
  var factFyAxis = null; // the annual FY axis derived from the fact slice, once

  function specFor(key) {
    var data = window.__pageData;
    return (data && data.specs && data.specs[key]) || null;
  }

  // partialFy — the disclosure block for a financial year the source files do
  // not publish in full, or null for a complete year (and for no selection).
  // The engine never names a year: site/pages.py derives the SET from
  // stats/catalog.py's partial_fys (every annual category later than
  // LATEST_COMPLETE_FY) and ships the prose with it, so one constant governs
  // the server's ranking default and the client's disclosure.
  function partialFy(fy) {
    var data = window.__pageData;
    var map = (data && data.partial_fys) || null;
    if (!fy || !map) return null;
    return Object.prototype.hasOwnProperty.call(map, fy) ? map[fy] : null;
  }

  // fyAxis — the FULL published financial-year axis for a figure, taken from
  // the UNFILTERED figure the server computed (see the category contract at the
  // top of this file). A top_n figure's own categories are AGENCY names, so its
  // degenerate one-agency trend falls back to the annual years present in the
  // page's fact slice — measured 2026-08-26, that derivation returns the same
  // seven years as the server's own trend categories on every chart page.
  function fyAxis(key) {
    var data = window.__pageData;
    var spec = specFor(key);
    var fig = data && data.figures ? data.figures[key] : undefined;
    if (spec && spec.kind !== "top_n" && fig && fig.value &&
        (fig.value.categories || []).length) {
      return fig.value.categories.slice();
    }
    if (factFyAxis) return factFyAxis.slice();
    // Object.create(null): an agency or FY named "__proto__" would otherwise
    // write through to Object.prototype instead of registering as a key
    var seen = Object.create(null), out = [], facts = (data && data.facts) || [];
    for (var idx = 0; idx < facts.length; idx++) {
      if (facts[idx].quarter !== null) continue;
      if (seen[facts[idx].fy] === undefined) {
        seen[facts[idx].fy] = 1;
        out.push(facts[idx].fy);
      }
    }
    out.sort();
    factFyAxis = out;
    return out.slice();
  }

  // trendCats — the categories a trend/ratio renders under the active filters.
  // The FY filter narrows the axis to the selected year (one point, and
  // oneFyNote explains it); every other dimension selects ROWS and must leave
  // the axis alone, or a small agency's gap years vanish instead of showing.
  function trendCats(key, active) {
    var cats = fyAxis(key);
    if (!active.fy) return cats;
    return cats.indexOf(active.fy) > -1 ? [active.fy] : [];
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

  // ariaDescription — the whole announcement for one chart, composed here
  // rather than left to ECharts.
  //
  // Two measured facts about the bundled ECharts 5.6.1 drive this. First, it
  // OVERWRITES any aria-label the page sets: with aria.enabled and no
  // aria.label.description it falls through to its own generated string, so
  // every chart announced "This is a chart with type line named received"
  // instead of the heading above it. Second, its generated string enumerates
  // only aria.label.data.maxCount points, default 10 — half of a top-20
  // ranking, with no table fallback anywhere on the page. Setting the
  // description short-circuits both (`if (a.get("description")) return void
  // i.setAttribute("aria-label", ...)`), so the label carries the card's own
  // heading and then EVERY category with its value.
  //
  // A missing year is announced as "no data", which is what the server prints
  // as "—" — the honesty contract has to survive the trip to assistive tech.
  function ariaDescription(label, fig) {
    var cats = fig.categories || [];
    var series = fig.series || [];
    var multi = series.length > 1;
    var parts = series.map(function (s) {
      var values = s.values || [];
      var points = cats.map(function (cat, idx) {
        var v = values[idx];
        return cat + ": " +
          (v === null || v === undefined ? "no data" : v.toLocaleString());
      });
      return (multi ? s.name + ", " : "") + points.join(", ");
    });
    return label + ". " + parts.join(". ") + ".";
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
    var label = chartLabel(el, key);
    // ECharts overwrites this the moment setOption runs; it is set anyway so a
    // box whose init() throws is still named rather than announced as a blank
    // graphic. The live-region marker noData leaves behind is removed here —
    // a mounted chart must not announce itself on every filter change.
    el.setAttribute("aria-label", label);
    el.removeAttribute("aria-live");
    mounted[key] = { el: el, horizontal: !!opts.horizontal };
    charts[key] = echarts.init(el);
    var option = figureOption(key, figValue, opts, el.clientWidth);
    // aria lives here, not in figureOption, because the announcement needs the
    // card's heading and figureOption is given only the figure (see
    // ariaDescription for what ECharts does when the description is absent)
    option.aria = { enabled: true,
                    label: { enabled: true,
                             description: ariaDescription(label, figValue) } };
    charts[key].setOption(option);
    attachResize(key);
  }

  // setNote — one managed note line per figure card, after the chartbox.
  // Text content only (never HTML) — agency names flow through here.
  //
  // The element is server-rendered and PERSISTENT (pages.py _chart_container
  // emits an empty `.fignote` with aria-live="polite", hidden by
  // `.fignote:empty`). Creating and removing it per render made every caveat a
  // brand-new node, which a screen reader does not announce — so a filter
  // selection silently swapped the sentence under the chart. Emptying the
  // existing node is a live-region update and is announced. The create branch
  // stays for a card rendered before that server change (and for any caller
  // that mounts a chartbox of its own).
  function setNote(el, text) {
    var section = el.parentElement;
    if (!section) return;
    var note = section.querySelector(".fignote");
    if (!note) {
      if (!text) return;
      note = document.createElement("p");
      note.className = "fignote";
      note.setAttribute("aria-live", "polite");
      el.insertAdjacentElement("afterend", note);
    }
    note.textContent = text || "";
  }

  // setBasis — the basis line beside the figure's heading. "basis: financial
  // year" is defined on the How to use page as a COMPLETE July-June year, so a
  // part-year selection may not be published under it; the server ships the
  // replacement text per part year in __pageData.partial_fys. The server's own
  // render is cached on first sight, so clearing the filter restores it
  // verbatim rather than reconstructing it here.
  function setBasis(el, partial) {
    var section = el.parentElement;
    var line = section && section.querySelector("p.basis");
    if (!line) return;
    if (line.dataset.basisDefault === undefined) {
      line.dataset.basisDefault = line.textContent;
    }
    line.textContent = partial ? partial.basis : line.dataset.basisDefault;
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
    // ECharts sets role="img" AND aria-label on the container itself (verified
    // in the bundled 5.6.1: `i.setAttribute("role","img")` on getZr().dom), and
    // dispose() leaves both behind. An element with role="img" exposes only its
    // aria-label, so the honest placeholder text underneath was invisible to a
    // screen reader — the site's central honesty mechanism, unavailable to
    // exactly the readers least able to work around it. Both attributes go, and
    // the box becomes a polite live region BEFORE the text lands so a selection
    // that empties a chart is announced rather than silently swapped.
    el.removeAttribute("role");
    el.removeAttribute("aria-label");
    el.setAttribute("aria-live", "polite");
    el.innerHTML = '<div class="nodata"></div>';
    el.firstChild.textContent = text;
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
  //     ranking year, and the degenerate one-agency view plots every year that
  //     agency has published rows for (its note says the FY selection is not
  //     applied there).
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
  // agency name today (measured 2026-08-26: 0 of 54,602 facts), so that half is
  // inert — it is here because catalog.py's per-agency figures apply both
  // halves, and a guard that is only inert cannot be relied on to stay correct
  // when one appears. The ops in stats/dsl.py are a different story; see the
  // is_reporting_agency docstring for which of them are not aligned.
  function isReportingAgency(name) {
    return !!name && name.toLowerCase() !== "total" && name.charAt(0) !== "x";
  }

  // trendSeries — per-FY sums of one measure over annual rows for one bucket,
  // laid out against the CATEGORIES THE CALLER SUPPLIES. Returns the values
  // array, null for every year the selection has no published row for.
  //
  // The categories are an input, not an output, and that is the whole fix: the
  // axis used to be built from the filtered rows, so a year the selection had
  // no row for did not become a gap, it disappeared. See the category contract
  // at the top of this file for the measurement.
  function trendSeries(facts, measure, bucket, cats) {
    var totalsByFy = Object.create(null), idx, row;
    for (idx = 0; idx < facts.length; idx++) {
      row = facts[idx];
      if (row.quarter !== null) continue;
      if (row.measure === measure && row.bucket === bucket) {
        totalsByFy[row.fy] = (totalsByFy[row.fy] || 0) + row.value;
      }
    }
    return cats.map(function (fy) {
      return totalsByFy[fy] !== undefined ? totalsByFy[fy] : null;
    });
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
    var rows, idx, series, den, values, parts, fy, totalsByAgency,
        ranked, reported, cats;

    if (spec.kind === "trend" || spec.kind === "multi_trend") {
      rows = dimFilter(facts, active, { type: true });
      cats = trendCats(key, active);
      if (!cats.length) return undefined;
      series = spec.measures.map(function (measure) {
        return { name: measure, values: trendSeries(rows, measure, bucket, cats) };
      });
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
      cats = trendCats(key, active);
      if (!cats.length) return undefined;
      var numeratorValues = spec.numerators.map(function (measure) {
        return trendSeries(rows, measure, bucket, cats);
      });
      den = trendSeries(rows, spec.denominator, bucket, cats);
      values = [];
      for (idx = 0; idx < cats.length; idx++) {
        parts = numeratorValues.map(function (numeratorTrend) {
          return numeratorTrend[idx];
        });
        var denominator = den[idx];
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
      return { fig: { categories: cats,
                      series: [{ name: spec.name, values: values }] },
               note: oneFyNote(cats, active) };
    }

    if (spec.kind === "top_n") {
      // agency filter: a one-agency ranking is meaningless — show that
      // agency's own FY trend for the measure instead (degenerate guard).
      // trendSeries reads annual rows only, so the golden single-quarter rows
      // (the "Total" pseudo-agency) can never reach this path: selecting it
      // yields no annual rows and falls through to the honest no-data note.
      if (active.agency) {
        rows = dimFilter(facts, active, { type: true, fy: true });
        // the FULL published axis, not this agency's own years: the FY filter
        // is skipped on this path, so narrowing the axis to the agency's rows
        // would silently close its gap years. "Aboriginal Benefit Account
        // Advisory Committee" has annual rows for four of the seven FYs
        // (the four earliest, measured 2026-08-26); it used to draw four evenly
        // spaced connected points, and now draws four points and a gap.
        cats = fyAxis(key);
        values = trendSeries(rows, spec.measure, bucket, cats);
        if (!cats.length || !anyNumeric(values)) return undefined;
        // the FY selection is dropped on this path. Saying so is the same rule
        // the one-year trend note follows: a select that visibly ignores its
        // input reads as broken.
        return {
          fig: { categories: cats,
                 series: [{ name: spec.measure, values: values.map(
                   function (v) { return v === null ? null : roundTo(v, 0); }) }] },
          note: "Showing the FY trend for " + active.agency +
                " (a one-agency ranking is not a top-" + spec.n + ")." +
                (active.fy
                  ? " The FY " + active.fy + " selection is not applied here: " +
                    "the trend spans every published financial year, and a year " +
                    "this agency has no published figure for is drawn as a gap."
                  : ""),
          asTrend: true,
          // the FY selection did not scope this figure, so the part-year
          // disclosure must not ride on it — six of these seven points are
          // complete years (renderFigure reads this)
          fyIgnored: true,
        };
      }
      fy = active.fy || spec.default_fy;
      rows = dimFilter(facts, active, { type: true, fy: true });
      // Object.create(null) — an agency literally named "__proto__" or
      // "toString" would otherwise never register as a key. No such name is in
      // the frame today; the ranking is not the place to depend on that.
      totalsByAgency = Object.create(null);
      for (idx = 0; idx < rows.length; idx++) {
        var row = rows[idx];
        // An FY ranking sums ANNUAL rows only and ranks real agencies only.
        // The golden Q1 rows are a single-quarter NATIONAL figure published
        // under a "Total" pseudo-agency: left in, it outranks every agency in
        // the latest FY and puts one quarter's number on a bar chart labelled
        // "basis: financial year". Both guards mirror the SERVER'S RANKING —
        // stats/catalog.py's top_n branch skips quarter-carrying rows and
        // applies is_reporting_agency, and isReportingAgency is that
        // predicate's twin. It is not the predicate "every per-agency op in
        // stats/ applies": measured 2026-08-26, five of the six ops in
        // stats/dsl.py drop only the "Total" pseudo-agency and keep x-prefixed
        // rows, so this client guard is stricter than they are. No row moves
        // either way on the current frame (0 x-prefixed rows).
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

  // ensureBaseline — the unfiltered figure's maximum, computed on FIRST SIGHT
  // of the figure whatever the filter state.
  //
  // It used to be assigned only inside the unfiltered branch, on the assumption
  // that the first render is always unfiltered. It is not: the filter selects
  // carry no autocomplete="off" and nothing resets them, so a soft reload or a
  // back-navigation restores the reader's selections while module state starts
  // empty. `baselineMax[key] || 0` then collapsed the pin to the selection's
  // own maximum — losing the half of the axis contract that keeps two
  // selections comparable — and, worse, that same falsy value short-circuited
  // the disclaimer test below, so "Axis extended past the unfiltered maximum"
  // was suppressed in exactly the case where the axis was being rescaled.
  function ensureBaseline(key) {
    if (baselineMax[key] !== undefined) return;
    var data = window.__pageData;
    var fig = data && data.figures ? data.figures[key] : undefined;
    baselineMax[key] = fig && fig.value ? seriesMax(fig.value) : null;
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
    ensureBaseline(key);

    try {
      // every path below either restores the server's basis line or replaces it
      // with the part-year one; start from the server's own text so a failed or
      // empty selection never leaves a basis claim from a previous render
      setBasis(el, null);
      if (!hasFilters) {
        var fig = data.figures ? data.figures[key] : undefined;
        // a figure object with empty series is NOT data — mounting it would
        // paint a blank canvas over an honest placeholder
        if (!figHasData(fig && fig.value)) {
          noData(el, key, NO_DATA_TEXT);
          return;
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
      // the part-year disclosure applies only where the FY selection actually
      // scoped what is drawn: the degenerate one-agency ranking ignores the FY
      // filter and plots every year, so calling that a part-year figure would
      // be false for six of its seven points
      var partial = out.fyIgnored ? null : partialFy(active.fy);
      // the axis may not shrink below the unfiltered baseline (selections stay
      // comparable) and may not sit below this selection's own largest value
      // (ECharts CLIPS a series at axis.max, so a lower pin would draw a real
      // number short). An agency view auto-scales by design, and auto-scaling
      // cannot truncate either. A PART-year selection rescales too: the
      // comparability rule assumes the two selections cover like windows, and
      // pinning nine months to a full year's maximum draws a shortfall that is
      // the calendar, not the agencies (received_top20, part year: a 12,264
      // leader at 72% height against the 17,120 complete-year pin).
      var own = seriesMax(out.fig);
      var pin;
      if (active.agency) pin = null;
      else if (partial) pin = own === null ? null : own;
      else pin = Math.max(baselineMax[key] || 0, own === null ? 0 : own) || null;
      var horizontal = spec.kind === "top_n" && !out.asTrend;
      mountChart(el, key, out.fig, { horizontal: horizontal, pinMax: pin,
                                     asTrend: !!out.asTrend });
      // the basis label the server printed says "financial year", which the How
      // to use page defines as a COMPLETE July-June year
      setBasis(el, partial);
      var notes = [];
      if (partial) notes.push(partial.note);
      if (out.note) notes.push(out.note);
      if (active.agency) notes.push("Axis rescaled for the selected agency.");
      else if (partial) notes.push(partial.axis_note);
      else if (pin && baselineMax[key] && pin > baselineMax[key]) {
        notes.push("Axis extended past the unfiltered maximum to fit this " +
                   "selection.");
      }
      setNote(el, notes.length ? notes.join(" ") : null);
    } catch (err) {
      if (window.console && typeof console.warn === "function") {
        console.warn("foi-charts: could not render chart '" + key + "'", err);
      }
      // setNote runs AFTER mountChart, which has already cleared innerHTML — so
      // a throw inside setOption left the PREVIOUS render's caveat ("Ranked
      // from the 303 agencies with published data for that year") sitting over an
      // empty box, describing a chart that is no longer there. noData clears
      // the note, disposes the instance and says what actually happened; it
      // does NOT claim the measure is unpublished, which would be a data claim
      // the frame contradicts.
      try {
        noData(el, key, RENDER_FAILED_TEXT);
      } catch (cleanupErr) {
        charts[key] = null;
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
