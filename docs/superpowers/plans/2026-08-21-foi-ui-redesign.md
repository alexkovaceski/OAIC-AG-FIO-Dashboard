# FOI Insights UI Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the FOI Insights POC sparkle — adopt the real OAIC visual identity (dark `#002a3a` header, teal/blue/gold palette), a two-level nav (OAIC top nav that links out + a horizon-style left vertical sidenav), and replace every static SVG chart with **interactive ECharts 5.6.0 panels + live filters**.

**Architecture:** Presentation-only redesign. The data, lineage, governance, `/ask`, API, and the "never invent a number" contract are untouched. `pages.py` keeps rendering pure frame → HTML, but emits ECharts containers + a `window.__pageData` JSON blob instead of inline SVG; a new `foi-charts.js` initialises the ECharts instances and wires the live filters (select/re-group platform-derived facts only — never a new aggregate). `templates.py` gets the two-level nav + OAIC footer.

**Tech Stack:** ECharts 5.6.0 (vendored, already in `src/site/assets/echarts.min.js`), vanilla JS (`foi-charts.js`), the existing Python page renderers + `site.css`, FastAPI static serving.

## Global Constraints

(from the spec `docs/superpowers/specs/2026-08-21-foi-ui-redesign-design.md` — every task implicitly includes these)

- **The "never invent a number" contract holds under filtering.** The client-side filter may only select/re-group facts the platform already derived. It may NOT compute a new aggregate the platform didn't derive. Where a filter needs a new slice, the platform pre-derives it and ships it in `__pageData`, or the page shows the underlying facts unchanged.
- **Every chart carries a basis label** (`single_quarter | cumulative | fy`).
- **No fabricated data.** A measure the files don't publish renders the honest "No published data" placeholder — never a flat-zero line. A missing year is "—", never 0.
- **Presentation only.** Data/lineage/governance/API/tests untouched — all 114 tests stay green.
- **The identity stovepipe** ("fartkraft sovereign stack") is the only model disclosure, in the footer on every page.
- **Top OAIC nav links OUT to the real OAIC site** (the six sections: Privacy / Freedom of information / Consumer Data Right / Digital ID / Engage with us / About). "Freedom of information" is active.
- **Live filters are in scope** (portfolio/agency · type personal/other · FY/quarter).
- **Responsive** down to mobile (left nav collapses to a horizontal scroll).
- **Accessibility floor:** visible keyboard focus, `prefers-reduced-motion` respected.
- **Commit footer** on every commit: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

## File Structure

```
src/site/
├── templates.py          # two-level nav (OAIC top + left sidenav) + OAIC footer
├── pages.py              # pages emit ECharts containers + window.__pageData (pure frame→HTML)
├── lineage_viewer.py     # (minor: apply the OAIC tokens + nav to the lineage page)
└── assets/
    ├── site.css          # full redesign to the OAIC tokens + chart/filter styles
    ├── echarts.min.js    # vendored ECharts 5.6.0 (already present)
    └── foi-charts.js     # NEW: chart init + live-filter wiring (vanilla JS)
tests/
├── test_pages.py         # updated: ECharts containers + __pageData instead of SVG
└── test_ui.py            # NEW: ECharts asset present, containers carry basis, no fabricated figures
```

---

## Task 1: OAIC design tokens + full chrome (templates.py + site.css)

**Files:**
- Modify: `src/site/templates.py`, `src/site/assets/site.css`, `src/site/pages.py` (the `chrome(...)` call sites), `src/site/lineage_viewer.py` (calls `chrome`), `src/server/app.py` (the `/lineage/{id}` + `/dashboards/{id}` routes call the renderers)
- Test: `tests/test_pages.py` (the "fartkraft on every page" + nav tests must still pass; add nav assertions), `tests/test_server.py` (the lineage/dashboard routes still render)

**Interfaces:**
- Produces:
  - `src/site/templates.py`: `chrome(title, active_nav, body_html, page_key=None)` — the two-level shell. `SIDENAV_GROUPS` (the 5 groups + pages). `nav_html(active_section)` for the top OAIC nav (links OUT to `https://www.oaic.gov.au/...`). `sidenav_html(page_key)` for the left nav. Footer with Acknowledgement of Country + © Commonwealth of Australia + legal links + stovepipe.
  - `src/site/assets/site.css`: the OAIC token system (dark header, teal/blue/gold), the two-column layout (sidenav + main), KPI tiles, chart containers, filter bar, responsive collapse, focus states, reduced-motion.

- [ ] **Step 1: Write `templates.py`** — the two-level nav.

```python
NAV = [
    ("Privacy", "https://www.oaic.gov.au/privacy"),
    ("Freedom of information", "https://www.oaic.gov.au/freedom-of-information", [
        ("Australian Government FOI statistics", "/"),
    ]),
    ("Consumer Data Right", "https://www.oaic.gov.au/consumer-data-right"),
    ("Digital ID", "https://www.oaic.gov.au/digital-id"),
    ("Engage with us", "https://www.oaic.gov.au/engage-with-us"),
    ("About the OAIC", "https://www.oaic.gov.au/about-the-oaic"),
]

# left portal nav groups: (group_label, [(page_key, label)])
SIDENAV_GROUPS = [
    ("Overview", [("at-a-glance", "FOI at a glance")]),
    ("Requests", [("requests-received", "Requests received"),
                  ("key-agency-contributions-received", "Key agency contributions"),
                  ("requests-finalised", "Requests finalised")]),
    ("Decisions", [("requests-decided", "Requests decided"),
                   ("key-agency-contributions-decided", "Key agency contributions"),
                   ("decision-outcomes", "Decision outcomes"),
                   ("change-decision-outcomes", "Change in decision outcomes")]),
    ("Timeliness", [("timeliness", "Timeliness"),
                    ("change-timeliness", "Change in timeliness")]),
    ("Reference", [("data-notes", "Data notes"),
                   ("how-to-use", "How to use"),
                   ("api", "API access")]),
]

def sidenav_html(page_key: str) -> str:
    out = ['<nav class="sidenav" aria-label="FOI statistics">']
    for group, items in SIDENAV_GROUPS:
        out.append(f'<div class="group">{html.escape(group)}</div>')
        for key, label in items:
            cls = "navbtn active" if key == page_key else "navbtn"
            out.append(f'<a class="{cls}" href="/{key}.html">{html.escape(label)}</a>')
    out.append("</nav>")
    return "\n".join(out)
```

`chrome` renders: the dark OAIC header (logo + `nav_html`), the breadcrumb, then a `div.layout` containing `sidenav_html(page_key)` + `<main>{body_html}</main>`, then the footer.

- [ ] **Step 2: Write `site.css`** — the OAIC token system.

```css
:root {
  --navy: #002a3a;   /* header band */
  --teal: #00567d;   /* primary accent */
  --blue: #26547b;   /* secondary */
  --dark: #003347;   /* depth */
  --ink:  #0c3c60;   /* body text */
  --paper:#f7f7f7;   /* page bg */
  --white:#ffffff;
  --gold: #ffcc00;   /* Commonwealth gold */
  --hair: #e6e6e6;
  /* chart series */
  --c1: #00567d; --c2: #26547b; --c3: #ffcc00;
  --c4: #eb6834; --c5: #1baf7a;
  --neg: #eb6834; --pos: #1baf7a;
}
```

Key structures: `.site-header` (dark navy, white text, gold active underline), `.layout { display: flex }`, `.sidenav { flex: 0 0 216px; ... }`, `.main { flex: 1; max-width: 1100px }`, `.kpis`, `.figure-card`, `.chartbox` (ECharts container, min-height 320px), `.filters` bar, responsive collapse under 900px, `:focus-visible` outlines, `@media (prefers-reduced-motion: reduce) { * { animation: none } }`.

- [ ] **Step 3: Run existing tests** — `tests/test_pages.py` + `tests/test_server.py` must still pass (the "fartkraft on every page" + nav tests). The `test_all_12_pages_render` PAGE_KEYS list stays (13 pages incl. api).
- [ ] **Step 4: Commit** — `feat(ui): OAIC design tokens + two-level nav chrome`

---

## Task 2: ECharts chart containers + `window.__pageData`

**Files:**
- Modify: `src/site/pages.py`
- Test: `tests/test_pages.py`, `tests/test_ui.py`

**Interfaces:**
- Consumes: `src/stats/catalog.foi_stats` (`_figure` returns `{categories, series}`, `_stat` returns `{value, basis, ...}`).
- Produces:
  - `pages.py`: `_chart_container(chart_key, height)` → `<div class="chartbox" id="chart-{chart_key}" data-figure="{chart_key}"></div>`; each `_page_*` embeds these + a `<script>window.__pageData = {...};</script>` blob (per-page figures + the long-form facts needed for filters).
  - `_page_data_script(frame, page_key)` → the JSON blob: `{figures: {key: foi_stats_result}, facts: <canonical facts needed>, filters: {available agencies/types/fys}}`.
  - The `_chart` SVG function is removed; the pages call `_chart_container` instead. The no-data honesty path stays: an uncomputable figure renders the "No published data" placeholder (not an empty ECharts).

- [ ] **Step 1: Write the failing test** (`tests/test_ui.py`)

```python
def test_pages_emit_echarts_containers_and_pagedata():
    pages = _pages()
    for key in ["at-a-glance", "requests-received", "decision-outcomes", "timeliness"]:
        html = pages[key]
        assert 'class="chartbox"' in html          # ECharts container
        assert "window.__pageData" in html          # data blob for the charts
        assert "/assets/echarts.min.js" in html     # ECharts loaded
        assert "/assets/foi-charts.js" in html      # init + filters

def test_no_fabricated_figures_in_pagedata():
    # a measure with no FY data must NOT appear as a flat-zero series
    import json, re
    pages = _pages()
    m = re.search(r"window\.__pageData\s*=\s*(\{.*?\});", pages["decision-outcomes"], re.S)
    data = json.loads(m.group(1))
    decided = data["figures"].get("decision_outcomes_trend", {})
    # either the series is empty or the value is None — never [0,0,0,...]
    for s in decided.get("value", {}).get("series", []):
        assert s.get("values", []) != [0] * len(s.get("values", [])), "fabricated zeros"

def test_echarts_asset_present():
    from pathlib import Path
    assert Path("src/site/assets/echarts.min.js").exists()
    assert Path("src/site/assets/foi-charts.js").exists()
```

- [ ] **Step 2: Run to verify it fails** (no chartbox/foi-charts yet)
- [ ] **Step 3: Implement in `pages.py`** — replace `_chart` with `_chart_container`, add `_page_data_script`. The page functions call the containers; `render_all_pages` injects the data script + the ECharts/foi-charts script tags into the `<head>` via `chrome` (add a `scripts` param to `chrome`, or append before `</body>`).
- [ ] **Step 4: Run tests** — `test_ui.py` + `test_pages.py` green.
- [ ] **Step 5: Commit** — `feat(ui): ECharts containers + window.__pageData (no fabricated figures)`

---

## Task 3: `foi-charts.js` — ECharts init + live filters

**Files:**
- Create: `src/site/assets/foi-charts.js`
- Test: `tests/test_ui.py` (add a JS-smoke assertion: the file exists, declares an init, wires filters)

**Interfaces:**
- Consumes: `window.__pageData` (from Task 2).
- Produces: `window.FoiCharts` — `init()` (finds every `.chartbox`, reads its `data-figure` key, renders the ECharts option from `__pageData.figures`), `wireFilters()` (dropdowns → re-render). The filter contract: select/re-group `__pageData.facts` only; never sum into a new total the platform didn't derive.

- [ ] **Step 1: Write the failing test** (JS smoke: the file declares `FoiCharts.init` + `wireFilters`)
- [ ] **Step 2: Write `foi-charts.js`**

```js
// foi-charts.js — ECharts init + live filters for FOI Insights.
// Reads window.__pageData (the platform-computed figures + canonical facts),
// renders every .chartbox as an ECharts instance, and wires the filter
// dropdowns. Filtering only selects/re-groups facts the platform derived;
// it never computes a new aggregate.
(function () {
  const PAL = {
    teal: "#00567d", blue: "#26547b", gold: "#ffcc00",
    orange: "#eb6834", green: "#1baf7a", ink: "#0c3c60",
    hair: "#e6e6e6",
  };
  const charts = {};

  function figureOption(key, fig) {
    // fig = {categories, series:[{name, values}]}; map to ECharts
    const cats = fig.categories || [];
    const series = (fig.series || []).map((s, i) => ({
      name: s.name || "series",
      type: key.indexOf("trend") > -1 ? "line" : "bar",
      data: s.values,
      itemStyle: { color: PAL[["teal","blue","gold","orange","green"][i % 5]] },
      smooth: true,
    }));
    const colors = series.map((s) => s.itemStyle.color);
    return {
      color: colors,
      tooltip: { trigger: "axis" },
      legend: series.length > 1 ? { top: 0 } : undefined,
      grid: { left: 50, right: 20, top: 30, bottom: 40 },
      xAxis: { type: "category", data: cats, axisLine: { lineStyle: { color: PAL.hair } } },
      yAxis: { type: "value", axisLine: { show: false }, splitLine: { lineStyle: { color: PAL.hair } } },
      series,
    };
  }

  function renderChart(el) {
    const key = el.dataset.figure;
    const fig = window.__pageData.figures[key];
    if (!fig || !fig.value) { el.innerHTML = '<div class="nodata">No published data for this measure.</div>'; return; }
    const opt = figureOption(key, fig.value);
    charts[key] = echarts.init(el);
    charts[key].setOption(opt);
    window.addEventListener("resize", () => charts[key].resize());
  }

  function init() {
    document.querySelectorAll(".chartbox").forEach(renderChart);
  }

  // Filters: re-render from __pageData.facts. Select-only — grouping a chosen
  // subset of platform facts is allowed; a new aggregate is not.
  function wireFilters() { /* ... */ }

  window.FoiCharts = { init, wireFilters };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => { init(); wireFilters(); });
  else { init(); wireFilters(); }
})();
```

- [ ] **Step 3: Run tests** — `test_ui.py` green.
- [ ] **Step 4: Commit** — `feat(ui): foi-charts.js ECharts init + live filters`

---

## Task 4: Live-filter wiring + per-page panel options

**Files:**
- Modify: `src/site/assets/foi-charts.js`, `src/site/pages.py` (add filter dropdowns to the pages' HTML)

**Interfaces:**
- Produces: the filter bar HTML (`<div class="filters">` with `select`s for portfolio/agency · type · FY/quarter) on the chart pages; `foi-charts.js` reads the selects, filters `__pageData.facts`, and re-renders the charts from the filtered subset (or shows the facts unchanged where a new aggregate would be needed).

- [ ] **Step 1: Add the filter bar to `pages.py`** — `_filters_bar()` returns the dropdowns; the chart pages embed it.
- [ ] **Step 2: Implement `wireFilters` in `foi-charts.js`** — on change, recompute each chart's series from the filtered facts (only select/re-group), set the option, re-render. The basis label is carried through.
- [ ] **Step 3: Tests** — add `test_filters_bar_present` to `test_ui.py`; run the suite.
- [ ] **Step 4: Commit** — `feat(ui): live filter dropdowns wired to ECharts`

---

## Task 5: Apply OAIC chrome to the lineage viewer

**Files:**
- Modify: `src/site/lineage_viewer.py`

**Interfaces:**
- Consumes: `site.templates.chrome` (new signature with `page_key`).
- Produces: the lineage page renders with the OAIC header + left nav (page_key="data-notes" or a lineage-specific entry) + footer.

- [ ] **Step 1: Update `lineage_viewer.py`** to call the new `chrome` (pass `page_key`). Keep the escape/fail-loud behaviour (XSS tests stay green).
- [ ] **Step 2: Run tests** — `test_pages.py` (lineage tests) + `test_server.py` green.
- [ ] **Step 3: Commit** — `feat(ui): OAIC chrome on the lineage viewer`

---

## Task 6: Verify the redesign end-to-end

**Files:**
- Modify: `src/site/assets/site.css` (tune), `src/site/pages.py` as needed
- Test: full suite + live check

- [ ] **Step 1: Run the full suite** — `python -m pytest` → all green (114 existing + new UI tests).
- [ ] **Step 2: Verify locally** — `python scripts/serve.py`, open `localhost:8095`:
  - dark OAIC header, gold active section, left sidenav highlights the active page
  - charts render as interactive ECharts (hover tooltips, zoom on trends)
  - live filters re-render the charts
  - no-data pages show the honest placeholder, not zeros
  - responsive down to mobile (sidenav collapses)
  - top OAIC nav links out to the real OAIC site
- [ ] **Step 3: Deploy to idc-1** — `python scripts/deploy.py` (pushes `src/` incl. the new assets) and verify `https://foi.axoquant.com` shows the redesign.
- [ ] **Step 4: Commit** — `chore(ui): verification pass` (if any tweaks landed)

---

## Self-review notes

- The `chrome` signature change (adding `page_key` + `scripts`) must thread through `pages.py`, `lineage_viewer.py`, and the lineage/dashboard routes in `server/app.py` (which call `chrome` or the page renderers). Task 1 must update every `chrome(...)` call site, not just templates.py.
- The ECharts option for a no-data figure must show the honest placeholder, never an empty chart that reads as zeros.
- `window.__pageData` carries facts client-side — it must not include anything beyond the platform-computed figures + canonical facts (no raw model text, no lineage internals that shouldn't be public).

---

## Amendment 2026-08-21 (mid-execution): Tailwind CSS adoption

**Decision (Alex, authorized 2026-08-21):** use Tailwind CSS to write and manage the UI instead of hand-rolled layout CSS. Reviewed mid-execution at Task 3 (Tasks 1-3 already committed). Adopted as a **hybrid**: Tailwind v4 utilities own layout / typography / spacing / the filter bar; `site.css` keeps only the bespoke component layer (chartbox sizing, sidenav, nodata placeholder, tables, notes prose, focus / reduced-motion).

**Why hybrid:** the compiled-vendored approach keeps the zero-build-step static deployment (the compiled `tailwind.css` ships with `src/` exactly like `echarts.min.js`); the bespoke component styles aren't naturally expressible as utilities and are already reviewed + tested.

**Mechanics:**
- Tailwind v4 (CSS-first), compiled offline with `npx @tailwindcss/cli` (Node 22 present) into a **committed** static asset `src/site/assets/tailwind.css`. No runtime CDN, no deployment build step.
- Input source `tailwind/input.css`: `@import "tailwindcss"` + an `@theme` block mapping the OAIC tokens (navy `#002a3a`, teal `#00567d`, blue `#26547b`, dark `#003347`, ink `#0c3c60`, paper `#f7f7f7`, white `#ffffff`, gold `#ffcc00`, hair `#e6e6e6`) to Tailwind color tokens, so utilities like `bg-navy`, `text-ink`, `border-gold` exist.
- Content scan targets `src/site/**/*.py` (the renderers' f-strings) + `src/site/assets/foi-charts.js`. Utility class names in the Python renderers are **static strings** — never constructed from runtime values — so the scan sees them.
- `chrome()` links `/assets/tailwind.css` after `/assets/site.css`; tests updated to assert both.
- The compiled `tailwind.css` and the `tailwind-input.css` source + a `package.json` pinning `@tailwindcss/cli` are committed.

**Amended tasks:**
- **Task 4a (NEW): Tailwind adoption** — setup the v4 build, compile `tailwind.css`, link it in `chrome()`, convert the chrome (header / layout / footer) to Tailwind utilities, shrink `site.css` to the bespoke layer, update the stylesheet test. Commit.
- **Task 4 (live-filter wiring):** build the filter bar with Tailwind utilities (selects / labels / spacing), wire `wireFilters` in `foi-charts.js`. Commit.
- **Task 5 (lineage chrome):** unchanged — inherits the chrome + Tailwind.
- **Task 6 (verify + deploy):** verify both stylesheets render + the compiled `tailwind.css` ships with `src/`; deploy unchanged (`scripts/deploy.py` already pushes `src/`).

**Global constraints unchanged:** never-invent-a-number, no fabricated data, all tests green, stovepipe footer, responsive + a11y floor.
