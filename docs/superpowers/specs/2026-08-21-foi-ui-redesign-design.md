# Design — FOI Insights visual redesign (OAIC identity + interactive ECharts)

**Date:** 2026-08-21
**Status:** Agreed design (awaiting implementation plan)
**Owner:** Alex

## 1. Purpose

The FOI Insights dashboard POC (live at `foi.axoquant.com`) is functional but
visually flat ("completely crap — my 4-year-old George could have done a better
job"). This redesign makes it **sparkle** by adopting the real OAIC visual
identity (the POC is for the OAIC) and upgrading every chart to **interactive
ECharts** matching the Power BI dashboards it replaces (reference screenshots in
`background/`). The target is "11/10" on the user's scale.

The data, lineage, governance, and "never invent a number" contract are **not**
changed — only the presentation layer.

## 2. Design tokens (OAIC identity, extracted from the real OAIC stylesheet)

Extracted from `https://www.oaic.gov.au/__data/assets/git_bridge/0012/12063/main.css`:

| Token | Value | Role |
|---|---|---|
| `--navy` | `#002a3a` | Dark teal-navy header band (OAIC `.header-content` bg) |
| `--teal` | `#00567d` | Primary accent — links, active states, header rule |
| `--blue` | `#26547b` | Secondary blue — buttons, sub-accents |
| `--dark` | `#003347` | Darker navy for depth/footers |
| `--ink` | `#0c3c60` | Deep blue-black body text |
| `--paper` | `#f7f7f7` | Light grey page background |
| `--white` | `#ffffff` | Cards, surfaces |
| `--gold` | `#ffcc00` | Commonwealth gold accent |
| Type | Arial / Source Sans Pro | Sans-serif, government-legible |

**Signature:** the dark `#002a3a` header band with white logo + white nav (like
the real OAIC inverted header) and a single `#ffcc00` gold accent. This is the
unmistakable "Australian Government" identity the current white site lacks. The
header is the memorable element; everything else stays disciplined.

**Chart series palette** (sits on the teal/blue/gold base without clashing):
`#00567d` teal, `#26547b` blue, `#ffcc00` gold, `#eb6834` orange (refused/
negative), `#1baf7a` green (positive/within-statutory). Grid/hairlines `#e6e6e6`,
text `#0c3c60`.

## 3. Chrome — two-level navigation

### 3.1 Top OAIC nav (fixed, matches the real site)

The dark `#002a3a` header band with the six OAIC sections:
**Privacy / Freedom of information / Consumer Data Right / Digital ID /
Engage with us / About the OAIC.** "Freedom of information" is the active
section, accented with gold. These link to the real OAIC site's pages so the
portal reads as genuinely integrated. The FOI statistics page is where the
portal sits. A search icon sits in the header (non-functional or linking to the
site search — cosmetic in the POC).

### 3.2 Left vertical portal nav (horizon pattern)

A fixed `sidenav` column (216px, mirroring horizon's `site/index.html`
`.sidenav`) under the header + breadcrumb, listing the portal's pages vertically
with group labels:

- **Overview** — FOI at a glance
- **Requests** — Requests received · Key agency contributions (received) ·
  Requests finalised
- **Decisions** — Requests decided · Key agency contributions (decided) ·
  Decision outcomes · Change in decision outcomes
- **Timeliness** — Timeliness · Change in timeliness
- **Reference** — Data notes · How to use · API access

Each is a `navbtn` with the active page highlighted. On mobile it collapses to a
horizontal scroll bar (horizon's responsive behaviour).

### 3.3 Layout skeleton

```
┌──────────────────────────────────────────────────────────────┐
│ OAIC HEADER (#002a3a): [logo] Privacy · Freedom of info ·    │
│ Consumer Data Right · Digital ID · Engage · About  [search]  │
├──────────────────────────────────────────────────────────────┤
│ breadcrumb: Home › Freedom of information › FOI statistics    │
├──────────┬───────────────────────────────────────────────────┤
│  SIDE    │  (page content — KPI tiles + ECharts panels)       │
│  NAV     │                                                    │
│  (216px) │                                                    │
├──────────┴───────────────────────────────────────────────────┤
│ FOOTER: Acknowledgement of Country · © Commonwealth of        │
│ Australia · legal links · fartkraft sovereign stack          │
└──────────────────────────────────────────────────────────────┘
```

### 3.4 Footer

OAIC footer pattern: Acknowledgement of Country, © Commonwealth of Australia,
legal links (Site map / Copyright / Terms / Privacy / Accessibility), and the
fartkraft sovereign stack stovepipe (the only model disclosure, per the
governance spec).

## 4. Interactive ECharts panels + live filters

### 4.1 Chart system

- **ECharts 5.6.0 vendored** at `src/site/assets/echarts.min.js` (already
  downloaded into the worktree, ~1MB).
- Every panel is an ECharts instance rendered from the **same platform-computed
  figures** (`foi_stats` / the frame) the pages already use. The "never invent a
  number" contract holds — ECharts draws the data; it never generates a figure.
- Interactive by default: hover tooltips with exact values, data-zoom sliders on
  trends, legend toggles, animated load — matching the Power BI reference.

### 4.2 Per-page panels

| Page | ECharts panel(s) |
|---|---|
| FOI at a glance | 5 KPI tiles (big numbers, basis labels) + a small trend sparkline |
| Requests received | Interactive **line/area trend** (FY series, tooltips, data-zoom) + **top-contributors horizontal bar** (Home Affairs ~35%) |
| Key agency contributions | **Waterfall** showing contribution to change (increases/decreases) |
| Requests finalised | **Stacked bar/area** — decided / transferred / withdrawn by period |
| Requests decided | **Line trend** + **top-20 bar** by type (personal/other) |
| Decision outcomes | **Donut** (granted full / part / refused / withdrawn shares) + outcome trend |
| Change in decision outcomes | **Slope/change chart** — % granted full/part, agencies up vs down |
| Timeliness | **Stacked area** — within vs after statutory + **% within** line |
| Change in timeliness | **Change breakdown** — agencies up vs down |
| Data notes | Text (verbatim, styled) |
| How to use | Text + a small example chart |
| API access | Endpoint docs table |

Every chart carries the **basis label** (single_quarter / cumulative / fy) and
the **"No published data"** honesty placeholder where a measure isn't published —
never a fabricated flat zero.

### 4.3 Live filters

The Power BI filter surface becomes **live**: portfolio/agency · type
(personal/other) · FY/quarter dropdowns wired to the ECharts instances. A user
selects a filter and the charts re-render with the filtered platform-computed
data. This is the "interactive portal" upgrade that matches the reference.

Filter implementation: a small JS module (`foi-charts.js`) that (a) initia-
lises the ECharts instances from embedded `window.__pageData` (the pre-computed
figures + the long-form canonical facts needed for filtering), and (b) wires the
filter dropdowns to re-render the charts from the filtered data client-side.

**The "never invent a number" contract is preserved under filtering.** The
client-side filter may only **select and re-group facts the platform already
derived** (the canonical `facts` carry their values; filtering by FY/agency/type/
quarter just chooses a subset). It may **not** compute a new aggregate the
platform didn't derive — for example, re-summing a filtered slice into a total
that was never platform-computed is off-limits. Where a filter would need a new
aggregation (a slice the platform didn't pre-derive), the page either (a) shows
the underlying facts unchanged, or (b) the platform pre-derives that slice and
ships it in `__pageData`. Chart types (donut shares, % within) are computed from
facts the platform already derived, and the basis label is carried through every
filter state.

## 5. Files touched

- `src/site/assets/site.css` — full redesign to the OAIC tokens + chart styles.
- `src/site/assets/echarts.min.js` — vendored ECharts 5.6.0 (new).
- `src/site/assets/foi-charts.js` — chart init + filter wiring (new).
- `src/site/templates.py` — two-level nav (OAIC top nav + left sidenav) + footer.
- `src/site/pages.py` — pages emit ECharts containers + `window.__pageData`
  instead of inline SVG; the 12-page rendering stays pure frame → HTML.
- `scripts/deploy.py` — already pushes `src/`; no change needed (assets ship
  with src).

## 6. Not in scope (unchanged)

- The data/ingest/normalise layer, lineage, governance, the agentic `/ask`, the
  read-only API + throttling, Postgres schema. All 114 tests stay green.
- The `fartkraft.ai` DNS move (separate credentials task).
- The durable Postgres lineage on the live site (separate task).

## 7. Testing

- Existing 114 tests stay green (the data contract is untouched).
- New tests: pages render ECharts containers + `window.__pageData` (not inline
  SVG); the vendored ECharts asset is present; every chart container carries a
  basis label; no page renders a fabricated figure.
- Manual: the live filters re-render the charts; the top OAIC nav links out to
  the real OAIC pages; the left nav highlights the active page; responsive down
  to mobile.
