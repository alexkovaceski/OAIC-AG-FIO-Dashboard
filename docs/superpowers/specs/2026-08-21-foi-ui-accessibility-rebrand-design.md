# Design — FOI Insights: load speed, WCAG stylesheet cleanup, FOI rebrand

**Date:** 2026-08-21
**Status:** Agreed design (awaiting implementation plan)
**Owner:** Alex

## 1. Purpose

Three follow-on improvements to the FOI Insights POC (`foi.axoquant.com`) after the
data-gap-fill deploy:

1. **Chart load speed** — pages are slow because every chart page ships the full
   1.03MB `echarts.min.js` with no compression and no cache headers.
2. **Stylesheet readability + WCAG** — `site.css` carries dead pre-ECharts code,
   several labels are ~11.5px, and `--muted: #6b7a86` fails WCAG AA contrast on
   white for the small text that uses it.
3. **Rebrand away from the OAIC identity** — the public site must not present as a
   government brand: no "OAIC" in the masthead, no links out to `oaic.gov.au`, no
   "© Commonwealth of Australia". It keeps the OAIC-derived *design language*
   (dark navy masthead, gold accent, two-level nav) so it stays in context for the
   style guide, but reads clearly as **FOI Insights**, separate from OAIC branding.

The data, lineage, governance, chart figures, and the "never invent a number"
contract are **not** changed — only the presentation layer and static-asset
delivery.

## 2. Rule that governs the rebrand

**OAIC appears nowhere on the public site except inside the verbatim data-notes
corpus.** The corpus text (`data/corpus/data-notes.md`) is the publisher's own
wording and is reproduced verbatim (unchanged, per decision). Every piece of
site-authored prose, navigation, footer, and chrome is OAIC-free.

## 3. Chart load — three deterministic changes

### 3.1 Swap the vendored ECharts bundle

- Replace `src/site/assets/echarts.min.js` (full bundle, 1,034,102 bytes) with
  **`echarts.common.min.js`** — ECharts' prebuilt "common" dist (bar + line + pie
  + grid + tooltip + legend + aria + canvas renderer).
- The chart system only ever renders **line** (`*_trend`, `*_change` keys) and
  **bar** (top-N / breakdown keys) — see `foi-charts.js figureOption()`. The
  common bundle covers both with no build step; no `dataZoom` or other full-bundle
  feature is used.
- **Source:** `https://cdn.jsdelivr.net/npm/echarts@5.6.1/dist/echarts.common.min.js`
  (pin `5.6.1` to match the current vendored version). Verify after download: the
  file is a JS file, is substantially smaller (~370KB), and a known symbol like
  `BarChart` is present.
- Size before / after: **1.03MB → ~370KB raw**, ~110KB when gzip-transferred.

### 3.2 Compress responses

- Add Starlette's `GZipMiddleware` to the FastAPI app (`gzip` for content over a
  minimum size, e.g. `minimum_size=1000`). This compresses the echarts bundle,
  every page's HTML, `window.__pageData`, the CSS, and the JSON API responses.

### 3.3 Cache headers on `/assets`

- Serve static assets with `Cache-Control: public, no-cache` so browsers
  revalidate against `Last-Modified` (cheap 304 on repeat visits, never stale
  after a deploy). StaticFiles already sends `Last-Modified`. Implement by passing
  `headers=` to the `StaticFiles` mount if the installed Starlette supports it,
  else a tiny `StaticFiles` subclass that adds the header.

## 4. Stylesheet cleanup (WCAG + readability)

### 4.1 Remove dead pre-ECharts CSS

`site.css` still carries the inline-SVG bar-chart system that ECharts replaced:
`.bar-row`, `.bar-row::after`, `.bar-end`, `.bar-end.none`, `.bval`, `.bcat`,
`.bseries`, `.chart-h`, `.chart-h-tall`. Confirm no template references them
(grep `site.css` class names in `src/site/`), then delete. Do not touch `.chartbox`
(the ECharts container) or `.nodata`.

### 4.2 WCAG AA contrast

- `--muted: #6b7a86` fails AA for small text on white (~3.9:1). Darken to a value
  that passes 4.5:1 on white — target **`#54626f`** (verify the ratio in the
  implementation task with a quick luminance check).
- `:focus-visible` currently uses the pale `--gold` 3px outline, which is weak on
  white (~1.6:1). Switch to `outline: 2px solid currentColor; outline-offset: 2px`
  so focus adapts to the background it sits on (white nav-link on navy, ink link on
  white both pass). Keep the gold active-nav underline (gold on navy is 13:1).

### 4.3 Bump tiny type

- `.kpi .tlabel`, `.kpi .basis`, `.sidenav .group` sit at `0.72rem` (~11.5px).
  Raise to `0.78rem`. Keep the 0.9rem–1rem ranges elsewhere.

### 4.4 WCAG structure

- **Skip link** (WCAG 2.4.1): a `a.skip-link` immediately inside `<body>`, visually
  hidden until focused, pointing at `<main id="main">`.
- **Landmark labels:** top nav gets `aria-label="Primary"`; the sidenav already has
  `aria-label="FOI statistics"` — two navs, two distinct labels.
- `html lang="en"` already present.

## 5. Rebrand — FOI Insights

### 5.1 Masthead

- Logo text "OAIC · FOI Insights" → **"FOI Insights"** (drop the OAIC prefix and
  the gold `·` rule).

### 5.2 Top nav

- Replace the six OAIC sections linking OUT to `oaic.gov.au` (Privacy / Freedom of
  information / Consumer Data Right / Digital ID / Engage with us / About the
  OAIC) with the FOI section's own five groups, each linking to its group's first
  page (all internal `/` links):
  **Overview · Requests · Decisions · Timeliness · Reference**.
- Active state = the group containing the current page (gold underline). Derive it
  from `SIDENAV_GROUPS` via a `page_key → group` lookup so the chrome stays a
  single source of truth.
- `chrome()` computes the active group from `page_key` itself (a `_group_for(page_key)`
  helper over `SIDENAV_GROUPS`); the `active_nav` parameter is removed and every call
  site drops its hardcoded `"Freedom of information"` argument.

### 5.3 Breadcrumb

- "Freedom of information › Australian Government freedom of information
  statistics" → **"FOI Insights › FOI statistics"**.

### 5.4 Footer

- Remove the outbound `Privacy` / `FOI` links to `oaic.gov.au` and the
  "© Commonwealth of Australia" line.
- Legal line becomes in-site links: **Data notes · How to use · API access**
  (`/data-notes.html`, `/how-to-use.html`, `/api.html`).
- Keep: Acknowledgement of Country, the fartkraft sovereign stack stovepipe
  (identity element).
- Attribution line → "FOI Insights — fartkraft sovereign stack · data from
  data.gov.au (FOI statistics)".

### 5.5 Prose (pages.py)

- `how-to-use` intro: "published on data.gov.au (OAIC FOI statistics)" →
  "(FOI statistics)".
- `how-to-use` data-notes line: "carries the OAIC's definitional notes verbatim"
  → "carries the publisher's definitional notes verbatim" (or "the source's").
- `api` intro + source line: "(OAIC FOI statistics)" → "(FOI statistics)"; the
  data.gov.au dataset link label "OAIC FOI statistics dataset" → "FOI statistics
  dataset" (link and dataset id unchanged).

### 5.6 Data notes page (verbatim, re-framed)

- Add a framing paragraph above the verbatim block, outside `.notes`:
  "These notes are reproduced verbatim from the source dataset (FOI statistics) on
  data.gov.au." The corpus itself is **untouched** — it keeps its "OAIC" mentions
  (that is the publisher's own wording, reproduced verbatim).
- `test_data_notes_renders_verbatim` (checks corpus phrases) continues to pass.

### 5.7 foi-charts.js

- Comment "OAIC brand palette" → "brand palette". The palette values are unchanged
  (the user keeps the style-guide context; only the OAIC name is dropped).

## 6. Files touched

- `src/site/assets/echarts.common.min.js` — vendored common bundle (new).
- `src/site/assets/echarts.min.js` — deleted (replaced).
- `src/site/assets/site.css` — dead-CSS removal, contrast + type fixes, skip-link
  + focus styles, comment header.
- `src/site/assets/tailwind.css` — unchanged.
- `src/site/assets/foi-charts.js` — palette comment only.
- `src/site/templates.py` — masthead, top nav, breadcrumb, footer, skip link,
  nav aria-labels, `main id`.
- `src/site/pages.py` — prose scrub (how-to-use, api), data-notes framing line,
  `_CHART_SCRIPTS` → common bundle, call-site `active_nav` changes.
- `src/server/app.py` — GZipMiddleware + `/assets` cache headers.
- `tests/test_ui.py` — update echarts bundle references; add rebrand + a11y tests.
- `tests/test_server.py` — add gzip + cache-control assertions.
- `tests/test_pages.py` — may extend the verbatim test with the framing line.

## 7. Testing

- All 126 existing tests stay green.
- Updated: `test_ui.py` echarts references (`echarts.min.js` → `echarts.common.min.js`).
- New rebrand tests:
  - No `oaic.gov.au` in any of the 12 rendered pages.
  - "OAIC" absent from every page **except** `data-notes` (which must still contain
    it — verbatim corpus preserved) and the framing line present.
  - Masthead contains "FOI Insights"; top-nav links all internal (`/`-relative).
- New a11y tests: every page has a skip link targeting `#main`; `<main id="main">`
  present; the two navs carry distinct `aria-label`s.
- New load tests: the loaded echarts asset is `echarts.common.min.js` and its size
  is < 500KB (guards a regression to the 1MB bundle).
- New server tests: a page and an asset respond `Content-Encoding: gzip` when
  requested with `Accept-Encoding: gzip`; `/assets` responses carry a
  `cache-control` header.
- Manual: local serve + visual check of masthead/nav/footer, skip-link tab focus,
  and a chart page loading gzip-transferred.

## 8. Not in scope

- Data / ingest / normalise / catalog / figures / API contract / lineage.
- The verbatim corpus text itself (kept byte-for-byte).
- The ECharts palette values and the navy/gold design language (kept, per the
  style-guide context requirement).
- Building a tree-shaken ECharts bundle (build step — not needed; the common dist
  is the no-build win).
