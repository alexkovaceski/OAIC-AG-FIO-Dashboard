# FOI Stage 2 — Figure Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded figure/filter machinery with a declarative, spec-driven engine (spec S2 of `docs/superpowers/specs/2026-08-25-foi-feedback-response-design.md`): figures declared once server-side, one generic client rederivation, scoped page payloads, filters on every chart page, corrected presentation (horizontal top-20, pinned axes, missing-agency footnotes, movers analysis).

**Architecture:** `stats/catalog.py` gains `FIGURE_SPECS` (kind + measures per figure) and a generic `_figure()` that interprets them, producing byte-identical outputs for all existing keys (the existing pinned tests are the regression net). `site/pages.py` ships each page's spec map plus a facts slice scoped to the measures its figures consume. `foi-charts.js` is rewritten around one spec-driven rederivation engine that applies filter dimensions per figure kind. Movers become first-class catalog stats rendered as tables on the two "Change" pages.

**Tech Stack:** Python 3.13 server-side, vanilla ES5-style JS + ECharts client-side (matching the existing file), pytest. No new dependencies, no JS build step, no JS test harness (see Testing philosophy).

## Global Constraints

- **Output-identity for existing figure keys:** the generic `_figure()` must produce exactly the same `{categories, series}` values the per-key branches produce today. The pinned tests (`test_disr_renamed_to_most_recent_name` FY sums, `test_dsl.py` 14/11/34303 pins, decision-series non-empty checks) are the net; never adjust a pinned expectation.
- **Golden gate keeps passing** (boot integrity vs `GOLDEN_Q1_FIGURES`).
- **`foi_stats` result contract unchanged:** `{value, basis, source_rows, rows_hash}`; `hash_rows`/`_FACT_KEYS` and lineage/replay behaviour untouched (the portfolio exclusion in `_FACT_KEYS` is load-bearing for replay of pre-Stage-1 datasets — rewrite its stale comment in Task 6, never the code).
- **Published figures only:** every client rederivation sums published fact rows; unpublishable selections show the honest note, never an invented aggregate.
- **`LATEST_COMPLETE_FY` is the single source of the top-N default year** — no other `"2024-25"` literal may remain in catalog.py, pages.py, or foi-charts.js when Stage 2 completes.
- **Backward compatibility for AI-built dashboards:** `/dashboards/{id}` pages load the same foi-charts.js; `figureOption` must keep a key-suffix fallback for figure keys that have no spec.
- **Testing philosophy:** there is no JS unit harness. Server-side pytest pins the emitted specs, scoped payload contents, and `__pageData` contract; JS behaviour is verified by task review of the complete file plus the mandatory post-deploy interactive browser sweep (Task 8). Do not add a node-based test runner.
- **`site` module name collision:** never `python -c "import site.x"`; scripts use `sys.path.insert(0, "src")`.
- **Suite speed:** run only named test files per task (300s timeout; test_ui ~6 min — 600s); full suite once at Task 8. Foreground runs only — never background a pytest run.
- **Commit after every task**; no deploy until the stage-boundary review completes.

## File Structure

- `src/stats/catalog.py` — FIGURE_SPECS, LATEST_COMPLETE_FY, generic `_figure`, movers generalisation (Tasks 1, 5, 6)
- `src/site/pages.py` — spec emission + scoped payloads, filters everywhere, portfolio dropdown, movers sections, caption consolidation (Tasks 2, 3, 5, 6)
- `src/site/assets/foi-charts.js` — complete rewrite (Task 4)
- `src/site/assets/site.css` — `.fignote` + movers-table styles (Tasks 4, 5)
- `src/server/app.py` — /lineage conn close (Task 7)
- `src/site/lineage_viewer.py` — single-resolve refactor (Task 7)
- `scripts/deploy.py` — information_schema schema predicate (Task 6)
- Tests: `tests/test_figure_specs.py` (new), `tests/test_payload_scope.py` (new), `tests/test_ui.py`, `tests/test_normalise.py` (unchanged, regression net), `tests/test_lineage_static.py`

---

### Task 1: FIGURE_SPECS and the generic server figure

**Files:**
- Modify: `src/stats/catalog.py` (add FIGURE_SPECS + LATEST_COMPLETE_FY after FIG_CAPTIONS ~line 41; replace `_figure` lines 148-217)
- Test: `tests/test_figure_specs.py` (new)

**Interfaces:**
- Produces: `catalog.FIGURE_SPECS: dict[str, dict]` — every FIG_KEYS entry has a spec; `catalog.LATEST_COMPLETE_FY = "2024-25"`. Spec vocabulary (consumed verbatim by Tasks 2-4):
  - `{"kind": "trend", "measures": [m]}` — single-measure FY line
  - `{"kind": "multi_trend", "measures": [m1..mn]}` — n-series FY line
  - `{"kind": "ratio_trend", "numerators": [..], "denominator": m, "name": s}` — 100*sum(nums)/sum(den) per FY, 1dp
  - `{"kind": "top_n", "measure": m, "n": 20, "default_fy": LATEST_COMPLETE_FY}` — ranked agencies
- Consumes: nothing new.

- [ ] **Step 1: Write the failing tests** (new file `tests/test_figure_specs.py`)

```python
"""FIGURE_SPECS — the declarative engine contract (spec S2.1).

The generic _figure must reproduce the legacy per-key outputs exactly;
these tests pin the spec vocabulary and the output-identity property.
"""
from ingest.normalise import normalise_all
from storage.frame import Frame
from stats import catalog
from stats.catalog import FIG_KEYS, FIGURE_SPECS, LATEST_COMPLETE_FY, foi_stats


def test_every_fig_key_has_a_spec():
    for key in FIG_KEYS:
        assert key in FIGURE_SPECS, f"no spec for {key}"
        assert FIGURE_SPECS[key]["kind"] in ("trend", "multi_trend",
                                             "ratio_trend", "top_n"), key


def test_latest_complete_fy_is_single_sourced():
    assert LATEST_COMPLETE_FY == "2024-25"
    import inspect
    src = inspect.getsource(catalog)
    # the only "2024-25" literal in catalog.py is the constant's own definition
    assert src.count('"2024-25"') == 1, \
        "top-N years must reference LATEST_COMPLETE_FY, not literals"


def test_generic_figure_reproduces_legacy_outputs():
    # Output-identity: computed via the spec engine, pinned against values the
    # legacy branches produced (measured on the real frame, 2026-08-26).
    frame = Frame(normalise_all())
    fig = foi_stats(frame, "requests_received_trend")["value"]
    assert fig["categories"][0] == "2019-20" and fig["categories"][-1] == "2025-26"
    assert fig["series"][0]["name"] == "received"
    # MEASURE: pin the full values list printed by the discovery script before
    # running (it is the exact legacy output; the engine must match it).
    assert fig["series"][0]["values"] == "<MEASURE-RECEIVED-TREND-VALUES>"

    outcomes = foi_stats(frame, "decision_outcomes_trend")["value"]
    assert [s["name"] for s in outcomes["series"]] == [
        "granted_full", "granted_part", "refused", "withdrawn"]

    ratio = foi_stats(frame, "granted_full_part_change")["value"]
    assert ratio["series"][0]["name"] == "granted_full_or_part_pct"
    assert ratio["series"][0]["values"] == "<MEASURE-GFP-CHANGE-VALUES>"

    top = foi_stats(frame, "received_top20")["value"]
    assert len(top["categories"]) == 20
    assert top["categories"][0] == "<MEASURE-TOP-AGENCY>"
    assert top["series"][0]["values"][0] == "<MEASURE-TOP-VALUE>"


def test_top_n_spec_takes_fy_parameter():
    # the server default uses LATEST_COMPLETE_FY; the spec carries it so the
    # client can override with the FY filter (B6/B7 fix)
    for key in ("received_top20", "decided_top20"):
        assert FIGURE_SPECS[key]["default_fy"] == LATEST_COMPLETE_FY
        assert FIGURE_SPECS[key]["n"] == 20
```

- [ ] **Step 2: Discovery — pin the legacy outputs.** Scratch script (session scratchpad, not committed):

```python
import sys; sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from storage.frame import Frame
from stats.catalog import foi_stats
frame = Frame(normalise_all())
for key in ("requests_received_trend", "granted_full_part_change", "received_top20"):
    print(key, foi_stats(frame, key)["value"])
```

Run BEFORE changing catalog.py — the printed values are the legacy outputs. Pin the four MEASURE placeholders. Then run the new test file: everything except `test_every_fig_key_has_a_spec` / `test_latest_complete_fy_is_single_sourced` / `test_top_n_spec_takes_fy_parameter` should PASS against the legacy code (they pin current behaviour); those three FAIL (no specs yet). That split is the point: the pins are the safety net for Step 3.

- [ ] **Step 3: Implement.** In `src/stats/catalog.py`, after FIG_CAPTIONS add:

```python
# The latest complete financial year in the annual files. The 2025-26 file is
# a Q1-Q3 cumulative partial; top-N rankings default to the last full year.
# Update once per year when the new annual file lands. This is the ONLY place
# the year is written — specs and pages reference the constant.
LATEST_COMPLETE_FY = "2024-25"

# FIGURE_SPECS — the declarative engine (spec S2.1). Each chartable figure is
# declared once; the server's generic _figure and the client's rederivation
# both interpret the same vocabulary:
#   trend       — one measure summed per FY (annual rows, bucket-scoped)
#   multi_trend — several measures, one series each
#   ratio_trend — 100 * sum(numerators) / sum(denominator) per FY, 1dp
#   top_n       — agencies ranked by one measure for one FY (default_fy unless
#                 the client's FY filter overrides it)
FIGURE_SPECS = {
    "requests_received_trend":  {"kind": "trend", "measures": ["received"]},
    "requests_finalised_trend": {"kind": "trend", "measures": ["finalised"]},
    "requests_decided_trend":   {"kind": "trend", "measures": ["decided"]},
    "decision_outcomes_trend":  {"kind": "multi_trend",
                                 "measures": ["granted_full", "granted_part",
                                              "refused", "withdrawn"]},
    "timeliness_trend":         {"kind": "trend", "measures": ["within_statutory"]},
    "refused_pct_trend":        {"kind": "ratio_trend", "numerators": ["refused"],
                                 "denominator": "decided", "name": "refused_pct"},
    "granted_full_part_change": {"kind": "ratio_trend",
                                 "numerators": ["granted_full", "granted_part"],
                                 "denominator": "decided",
                                 "name": "granted_full_or_part_pct"},
    "timeliness_change":        {"kind": "ratio_trend",
                                 "numerators": ["within_statutory"],
                                 "denominator": "decided",
                                 "name": "within_statutory_pct"},
    "received_top20":           {"kind": "top_n", "measure": "received", "n": 20,
                                 "default_fy": LATEST_COMPLETE_FY},
    "decided_top20":            {"kind": "top_n", "measure": "decided", "n": 20,
                                 "default_fy": LATEST_COMPLETE_FY},
    "agency_contributions_received": {"kind": "top_n", "measure": "received",
                                      "n": 20, "default_fy": LATEST_COMPLETE_FY},
    "agency_contributions_decided":  {"kind": "top_n", "measure": "decided",
                                      "n": 20, "default_fy": LATEST_COMPLETE_FY},
}
```

Replace the `_figure` body (keep the docstring, updating its stale claims — see Task 6 for the full sweep; here just make it describe the spec engine):

```python
def _figure(frame, key):
    """A chartable figure: {categories, series}, computed by interpreting the
    figure's FIGURE_SPECS entry. The FY trends read the annual files
    (quarter=None, bucket=total); the top-N reads one FY's agency rows. The
    single-quarter Q1 2025-26 headline stays on the separate *_q1 stats, never
    blended into the FY series (per the trend-window decision). A measure with
    no annual rows yields an empty/None-holed series, never a fabricated line.
    """
    spec = FIGURE_SPECS.get(key)
    if spec is None:
        return {"categories": [], "series": []}
    cats = sorted({f["fy"] for f in frame.facts if f["quarter"] is None})

    if spec["kind"] in ("trend", "multi_trend"):
        return {"categories": cats, "series": [
            {"name": m, "values": _fy_series(frame, m)} for m in spec["measures"]]}

    if spec["kind"] == "ratio_trend":
        nums = [_fy_series(frame, m) for m in spec["numerators"]]
        den = _fy_series(frame, spec["denominator"])
        values = []
        for i in range(len(cats)):
            parts = [s[i] if i < len(s) else None for s in nums]
            d = den[i] if i < len(den) else None
            if any(p is None for p in parts) or not d:
                values.append(None)
            else:
                values.append(round(100 * sum(parts) / d, 1))
        return {"categories": cats, "series": [{"name": spec["name"], "values": values}]}

    if spec["kind"] == "top_n":
        rows = frame.filter(measure=spec["measure"], bucket="total",
                            fy=spec["default_fy"])
        aggs = {}
        for f in rows:
            aggs.setdefault(f["agency_name"], 0.0)
            aggs[f["agency_name"]] += f["value"]
        top = sorted(aggs.items(), key=lambda kv: kv[1], reverse=True)[:spec["n"]]
        return {"categories": [a for a, _ in top],
                "series": [{"name": spec["measure"],
                            "values": [round(v) for _, v in top]}]}

    return {"categories": [], "series": []}
```

Delete the now-dead per-key branches (the whole legacy if-chain) and the `agency_contributions_*` aliases (their specs handle them). `_fy_series` note: the legacy `granted_full_part_change` required BOTH numerators non-None (`a is not None and b is not None`) — the generic `any(p is None ...)` reproduces that exactly. The legacy ratio series were zip-based over possibly-empty lists; the generic indexes defensively (`i < len(s)`) which is equivalent for equal-length or empty series. Empty `_fy_series` (no rows) yields `[]`, so every ratio value becomes None-guarded — matching legacy zip-over-empty behaviour (empty series → empty zip → all values absent → but legacy returned a values list from zip which would be []… CHECK in Step 4: `timeliness_change` on the real frame has non-empty series today, and the empty-measure case is covered by `_notes_section`'s no-data path; if the identity test surfaces a []-vs-[None,...] shape difference for any key, match the LEGACY shape and note it in the report).

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_figure_specs.py tests/test_normalise.py -v` (300s timeout)
Expected: ALL pass — the pinned legacy values must reproduce through the engine. Then `python -m pytest tests/test_dsl.py tests/test_dsl_portfolio.py -v` (fast) — untouched, must stay green.

- [ ] **Step 5: Commit**

```bash
git add src/stats/catalog.py tests/test_figure_specs.py
git commit -m "feat(stats): declarative FIGURE_SPECS + generic figure engine"
```

---

### Task 2: Scoped page payloads

**Files:**
- Modify: `src/site/pages.py` (`_page_data_script`, currently ~lines 163-180)
- Test: `tests/test_payload_scope.py` (new)

**Interfaces:**
- Produces: `window.__pageData` gains `"specs"` (the page's FIGURE_SPECS subset) and its `"facts"` become the slice scoped to the page's spec-consumed measures. `"filters"` stays GLOBAL (derived from the full frame) so dropdowns list every agency/portfolio/FY.
- Consumes: `FIGURE_SPECS` (Task 1).

- [ ] **Step 1: Write the failing tests** (new file `tests/test_payload_scope.py`)

```python
"""Scoped __pageData payloads (spec S2.1): each page ships only the facts its
figures consume, plus the specs the client engine interprets."""
import json
import re

from ingest.normalise import normalise_all
from storage.frame import Frame
from site.pages import render_all_pages, PAGE_FIGURE_KEYS
from stats.catalog import FIGURE_SPECS


def _blob(page_html):
    m = re.search(r"window\.__pageData = (.*?);</script>", page_html, re.S)
    assert m, "no __pageData"
    return json.loads(m.group(1))


def _spec_measures(page_key):
    out = set()
    for fig_key in PAGE_FIGURE_KEYS[page_key]:
        spec = FIGURE_SPECS[fig_key]
        out.update(spec.get("measures", []))
        out.update(spec.get("numerators", []))
        if spec.get("denominator"):
            out.add(spec["denominator"])
        if spec.get("measure"):
            out.add(spec["measure"])
    return out


def test_pages_ship_only_their_spec_measures():
    pages = render_all_pages(Frame(normalise_all()))
    for key in ("at-a-glance", "requests-received", "decision-outcomes",
                "key-agency-contributions-received", "change-timeliness"):
        blob = _blob(pages[key])
        allowed = _spec_measures(key)
        shipped = {f["measure"] for f in blob["facts"]}
        assert shipped <= allowed, f"{key}: foreign measures {shipped - allowed}"
        assert blob["facts"], f"{key}: empty facts slice"


def test_pages_ship_their_specs():
    pages = render_all_pages(Frame(normalise_all()))
    blob = _blob(pages["key-agency-contributions-received"])
    assert blob["specs"]["received_top20"]["kind"] == "top_n"
    assert blob["specs"]["received_top20"]["default_fy"] == "2024-25"


def test_filters_blob_stays_global():
    pages = render_all_pages(Frame(normalise_all()))
    blob = _blob(pages["at-a-glance"])  # ships only 'received' facts
    # dropdown options must still cover the whole platform
    assert len(blob["filters"]["agencies"]) > 250
    assert len(blob["filters"]["portfolios"]) >= 10
    assert "2019-20" in blob["filters"]["fys"]


def test_payload_shrinks():
    pages = render_all_pages(Frame(normalise_all()))
    at_a_glance = _blob(pages["at-a-glance"])
    # at-a-glance consumes one measure; the slice must be well under a fifth
    # of the ~54.6k-fact full frame
    assert len(at_a_glance["facts"]) < 12000, len(at_a_glance["facts"])
```

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest tests/test_payload_scope.py -v` (300s timeout)
Expected: all FAIL (facts are the full frame; no specs key).

- [ ] **Step 3: Implement.** Replace `_page_data_script`'s blob construction:

```python
def _page_spec_measures(page_key) -> set:
    """Every fact measure the page's figure specs consume (trend measures,
    ratio numerators + denominator, top-N measure)."""
    out = set()
    for fig_key in PAGE_FIGURE_KEYS.get(page_key, []):
        spec = FIGURE_SPECS.get(fig_key, {})
        out.update(spec.get("measures", []))
        out.update(spec.get("numerators", []))
        if spec.get("denominator"):
            out.add(spec["denominator"])
        if spec.get("measure"):
            out.add(spec["measure"])
    return out
```

and inside `_page_data_script` (docstring updated to describe the scoping; the SECURITY escaping paragraph and the `.replace` guards stay exactly as they are):

```python
    figures = {k: _stat(frame, k) for k in PAGE_FIGURE_KEYS.get(page_key, [])}
    specs = {k: FIGURE_SPECS[k] for k in PAGE_FIGURE_KEYS.get(page_key, [])
             if k in FIGURE_SPECS}
    measures = _page_spec_measures(page_key)
    facts = [f for f in frame.facts if f["measure"] in measures]
    blob = {"figures": figures, "specs": specs, "facts": facts,
            "filters": _filters_blob(frame)}
```

Import `FIGURE_SPECS` beside the existing `foi_stats, FIG_CAPTIONS` import.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_payload_scope.py tests/test_ui.py -v` (600s timeout)
Expected: new file passes; in test_ui, `test_filters_blob_exposes_portfolios` and the `__pageData` tests must still pass (they parse the blob, not its size). If any pre-existing test asserted full-frame facts length, treat that as a contract update this task owns: update it to the scoped contract and say so in the report.

- [ ] **Step 5: Commit**

```bash
git add src/site/pages.py tests/test_payload_scope.py tests/test_ui.py
git commit -m "feat(site): scope __pageData facts to each page's spec measures"
```

---

### Task 3: Filters on every chart page + Portfolio dropdown

**Files:**
- Modify: `src/site/pages.py` (`_FILTER_PAGES` ~125-130, `_filters_bar` ~133-160, the five pages currently without a bar: requests-decided, key-agency-contributions-decided, decision-outcomes, change-decision-outcomes, timeliness, change-timeliness)
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: all TEN chart pages render the filter bar with FOUR selects: `data-filter="agency|portfolio|type|fy"`. Task 4's engine reads `active.portfolio`.
- Consumes: `_filters_blob()["portfolios"]` (Stage 1).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ui.py`)

```python
CHART_PAGES = ["at-a-glance", "requests-received",
               "key-agency-contributions-received", "requests-finalised",
               "requests-decided", "key-agency-contributions-decided",
               "decision-outcomes", "change-decision-outcomes",
               "timeliness", "change-timeliness"]

def test_every_chart_page_has_the_filter_bar():
    # B12/B13/B16 (spec S2.2): filters are page-spec-driven, not an allowlist
    pages = _pages()
    for key in CHART_PAGES:
        page = pages[key]
        assert 'class="filters' in page, f"{key} has no filter bar"
        for f in ("agency", "portfolio", "type", "fy"):
            assert f'data-filter="{f}"' in page, f"{key} missing {f} select"

def test_reference_pages_have_no_filter_bar():
    pages = _pages()
    for key in ("data-notes", "how-to-use", "api"):
        assert 'class="filters' not in pages[key]
```

- [ ] **Step 2: Run to verify failures**

Run: `python -m pytest tests/test_ui.py -k "filter_bar" -v` (600s timeout)
Expected: FAIL (six pages lack the bar; no portfolio select anywhere).

- [ ] **Step 3: Implement.**

1. Replace `_FILTER_PAGES` with the chart-page set and update its comment (the bar ships wherever a page has figures):

```python
# every page with a chartable figure carries the live filter bar; the engine
# (foi-charts.js) applies each dimension only where the figure kind can honour
# it and shows the honest note where it cannot (spec S2.2)
_FILTER_PAGES = frozenset(k for k, figs in PAGE_FIGURE_KEYS.items() if figs)
```

2. In `_filters_bar`, add the Portfolio select between Agency and Type:

```python
    portfolio = _select("Portfolio", "portfolio", f["portfolios"], "All portfolios")
```

and include it in the returned bar: `{agency}{portfolio}{typ}{fy}`.

3. The six pages that previously had no `_filters_bar(...)` call get one, placed exactly where the four existing pages put it (after the intro/KPIs, before the figure section) — pattern-match `_page_requests_received`.

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_ui.py -v` (600s timeout)
Expected: ALL pass (including the new pair and the pre-existing filter tests).

- [ ] **Step 5: Commit**

```bash
git add src/site/pages.py tests/test_ui.py
git commit -m "feat(site): filter bar on every chart page + portfolio dimension"
```

---

### Task 4: The client engine — complete foi-charts.js rewrite

**Files:**
- Replace: `src/site/assets/foi-charts.js` (full file below)
- Modify: `src/site/assets/site.css` (`.fignote` rule)
- Test: `tests/test_ui.py` (contract assertions only — see Testing philosophy)

**Interfaces:**
- Consumes: `__pageData.specs` (Task 2), four filter selects (Task 3), `__pageData.filters.agencies` (footnote universe).
- Produces: spec-driven rederivation honouring B2 (bucket-aware), B4 (pinned axis except agency views), B6/B7 (FY-parameterised top-N), B8 (missing-agency footnote), B9 (horizontal top-N), B16 (ratio rederivation), degenerate-agency fallback (top-N + agency filter → that agency's own trend).

Behavioural contract the reviewer must trace (each maps to a feedback item):

1. Type filter `personal`/`other` on a trend now REDERIVES with that bucket (B2) — no more dead-end note; the note remains only for selections with genuinely no rows.
2. FY filter on a top-N page ranks THAT year (B6/B7); no FY filter → `spec.default_fy`.
3. Agency filter on a top-N figure switches to that agency's FY trend for the spec's measure, with a fignote saying so (approved degenerate-guard design).
4. Ratio figures recompute from numerator/denominator sums under any dimension combination (B16).
5. Axis: with any filter active EXCEPT agency, the value axis pins to the unfiltered baseline max (B4); with an agency filter it auto-scales and the fignote says "Axis rescaled for the selected agency."
6. top_n renders horizontal (category y-axis, inverse so rank 1 sits on top, left grid 230px, truncated labels) (B9).
7. top_n emits a fignote: "N of M agencies reported no data for FY x and are not ranked" computed from the GLOBAL agencies universe minus agencies with rows for (measure, fy) in the page slice (B8).
8. Keys without a spec fall back to the legacy suffix heuristic (AI-built dashboard pages).

- [ ] **Step 1: Add the contract tests** (append to `tests/test_ui.py` — these pin the server side of the JS contract)

```python
def test_chart_pages_ship_specs_for_their_figures():
    pages = _pages()
    for key in CHART_PAGES:
        m = re.search(r"window\.__pageData = (.*?);</script>", pages[key], re.S)
        blob = json.loads(m.group(1))
        for fig_key in blob["figures"]:
            assert fig_key in blob["specs"], f"{key}: {fig_key} unspecced"

def test_foi_charts_js_has_no_hardcoded_fy_or_measure_maps():
    src = Path("src/site/assets/foi-charts.js").read_text(encoding="utf-8")
    assert "2024-25" not in src, "top-N year must come from the spec"
    assert "TREND_MEASURES" not in src and "TOP_N" not in src, \
        "legacy hardcoded maps must be gone"
```

(`Path` import exists or add `from pathlib import Path` at top.) Run `-k "specs_for_their or hardcoded_fy"`: first passes already after Task 2 (fine — it pins the contract Task 4 relies on), second FAILS until the rewrite lands.

- [ ] **Step 2: Replace `src/site/assets/foi-charts.js` with the complete file:**

```javascript
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
```

- [ ] **Step 3: Add the `.fignote` style** to `src/site/assets/site.css`, beside the `.source` rule:

```css
.fignote {
  font-size: 0.78rem; color: var(--muted); margin: 6px 0 0;
}
```

- [ ] **Step 4: Trace the eight contract behaviours by hand** against the new file (the reviewer will re-trace them; your report lists each behaviour with the function/line implementing it). Then run: `python -m pytest tests/test_ui.py -v` (600s timeout) — all pass, including the two Step-1 contract tests.

- [ ] **Step 5: Commit**

```bash
git add src/site/assets/foi-charts.js src/site/assets/site.css tests/test_ui.py
git commit -m "feat(site): spec-driven chart engine - bucket/FY/portfolio filters, horizontal top-N, pinned axes"
```

---

### Task 5: Movers analysis on the two Change pages

**Files:**
- Modify: `src/stats/catalog.py` (generalise `_refusal_rate_movers` callers; new stat keys)
- Modify: `src/site/pages.py` (`_movers_section` helper; the two change pages; caption corrections)
- Modify: `src/site/assets/site.css` (movers table styles)
- Test: `tests/test_ui.py`, `tests/test_figure_specs.py`

**Interfaces:**
- Produces: STAT_KEYS gains `"refusal_rate_movers"` and `"timeliness_movers"` (FY-pair defaulting to the two latest complete FYs); `foi_stats` returns their mover lists with the standard result contract. `pages._movers_section(title, stat, fy_a, fy_b)` renders a top-10 table. The legacy `refusal_rate_change_fy23_fy24` key stays (agentic `report.py` routes to it) and now delegates to the generalised movers with its fixed pair.
- Consumes: `LATEST_COMPLETE_FY` (Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_figure_specs.py`:

```python
def test_movers_stats_default_to_latest_complete_pair():
    frame = Frame(normalise_all())
    out = foi_stats(frame, "refusal_rate_movers")
    assert out["basis"] == "fy"
    assert out["value"]["fy_a"] == "2023-24" and out["value"]["fy_b"] == "2024-25"
    assert out["value"]["movers"], "no movers computed"
    top = out["value"]["movers"][0]
    assert set(top) == {"agency", "fy_a_rate", "fy_b_rate", "change"}

    t = foi_stats(frame, "timeliness_movers")
    assert t["value"]["movers"], "no timeliness movers"

def test_legacy_movers_key_still_works():
    frame = Frame(normalise_all())
    out = foi_stats(frame, "refusal_rate_change_fy23_fy24")
    assert out["value"], "legacy key must keep returning movers"
```

Append to `tests/test_ui.py`:

```python
def test_change_pages_render_movers_tables():
    # B10 (spec S2.3): real change analysis, not just level series
    pages = _pages()
    cdo = pages["change-decision-outcomes"]
    assert 'class="movers"' in cdo and "Refusal-rate movers" in cdo
    assert "2023-24" in cdo and "2024-25" in cdo
    ct = pages["change-timeliness"]
    assert 'class="movers"' in ct and "Timeliness movers" in ct

def test_change_page_captions_describe_what_is_plotted():
    pages = _pages()
    assert "Change in % granted in full or part" not in pages["change-decision-outcomes"] \
        or "% of decisions granted in full or part, by FY" in pages["change-decision-outcomes"]
```

(The caption test's final shape: FIG_CAPTIONS for the two change figures become "% of decisions granted in full or part, by FY" and "% decided within statutory time, by FY" — level series described as levels; the movers tables carry the "change" analysis. Adjust the assertion to the exact new caption strings you set.)

- [ ] **Step 2: Run to verify failures** (`python -m pytest tests/test_figure_specs.py -k movers tests/test_ui.py -k "movers or captions_describe" -v`, 600s) — FAIL.

- [ ] **Step 3: Implement.**

`catalog.py` — a generalised rate-movers helper and the two stats:

```python
def _previous_complete_fy(frame):
    """The FY before LATEST_COMPLETE_FY among the annual categories."""
    cats = sorted({f["fy"] for f in frame.facts if f["quarter"] is None})
    i = cats.index(LATEST_COMPLETE_FY)
    return cats[i - 1]


def _rate_movers(frame, num_measure, den_measure, fy_a, fy_b):
    """Per-agency rate (num/den) change between two FYs — the generalised form
    of the refusal-rate movers. Agencies without a positive denominator in
    either FY are skipped (no fabricated rate)."""
    def rate(fy):
        rows = frame.filter(fy=fy, bucket="total")
        by = {}
        for f in rows:
            if f["measure"] in (num_measure, den_measure):
                by.setdefault(f["agency_name"], {num_measure: 0.0, den_measure: 0.0})
                by[f["agency_name"]][f["measure"]] += f["value"]
        return {name: 100.0 * m[num_measure] / m[den_measure]
                for name, m in by.items() if m[den_measure] > 0}
    ra, rb = rate(fy_a), rate(fy_b)
    movers = [{"agency": n, "fy_a_rate": round(ra[n], 1),
               "fy_b_rate": round(rb[n], 1), "change": round(rb[n] - ra[n], 1)}
              for n in ra if n in rb]
    movers.sort(key=lambda m: abs(m["change"]), reverse=True)
    return movers
```

Refactor `_refusal_rate_movers(frame, fy_a, fy_b)` to `return _rate_movers(frame, "refused", "decided", fy_a, fy_b)` (keeping its name for the legacy key's call site). Add to `foi_stats`:

```python
    if key == "refusal_rate_movers":
        fy_a, fy_b = _previous_complete_fy(frame), LATEST_COMPLETE_FY
        rows = frame.filter(fy=fy_a, bucket="total") + frame.filter(fy=fy_b, bucket="total")
        return {"value": {"fy_a": fy_a, "fy_b": fy_b,
                          "movers": _rate_movers(frame, "refused", "decided", fy_a, fy_b)},
                "basis": "fy", "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "timeliness_movers":
        fy_a, fy_b = _previous_complete_fy(frame), LATEST_COMPLETE_FY
        rows = frame.filter(fy=fy_a, bucket="total") + frame.filter(fy=fy_b, bucket="total")
        return {"value": {"fy_a": fy_a, "fy_b": fy_b,
                          "movers": _rate_movers(frame, "within_statutory", "decided", fy_a, fy_b)},
                "basis": "fy", "source_rows": len(rows), "rows_hash": hash_rows(rows)}
```

Add both keys to `STAT_KEYS`. Update FIG_CAPTIONS for the two change figures to level-series descriptions (exact strings you assert in the test).

`pages.py` — the table helper (top 10 by |change|, counts disclosed):

```python
def _movers_section(title, stat, unit="%") -> str:
    """A ranked movers table: agency, rate in each FY, change. Top 10 by
    absolute change; the count of qualifying agencies is disclosed."""
    v = stat["value"]
    rows = v["movers"][:10]
    head = (f'<section class="figure-card"><h2>{html.escape(title)}</h2>'
            f'<p class="basis">{_basis_label(stat)}</p>'
            f'<table class="movers"><thead><tr><th>Agency</th>'
            f'<th>{html.escape(v["fy_a"])}</th><th>{html.escape(v["fy_b"])}</th>'
            f'<th>Change</th></tr></thead><tbody>')
    body = "".join(
        f'<tr><td>{html.escape(m["agency"])}</td>'
        f'<td>{m["fy_a_rate"]}{unit}</td><td>{m["fy_b_rate"]}{unit}</td>'
        f'<td>{"+" if m["change"] > 0 else ""}{m["change"]}{unit}</td></tr>'
        for m in rows)
    foot = (f'</tbody></table><p class="fignote">Top 10 of {len(v["movers"])} '
            f'agencies with a computable rate in both years.</p></section>')
    return head + body + foot
```

Render `_movers_section("Refusal-rate movers", _stat(frame, "refusal_rate_movers"))` on change-decision-outcomes after the figure card, and `_movers_section("Timeliness movers", _stat(frame, "timeliness_movers"))` on change-timeliness. Update both pages' intro copy to say the page shows the level series plus the biggest movers between the two latest complete years. `site.css`: a plain `.movers` table rule (full width, hairline row borders, right-aligned numeric cells) beside the existing table styles if any, else after `.fignote`.

**Also in this task — the B5 channel visual (spec S2.2's remaining half).** Add the received-channel figure end to end:

1. `catalog.py`: `"received_channel_trend"` appended to FIG_KEYS, with
   `FIGURE_SPECS["received_channel_trend"] = {"kind": "multi_trend", "measures": ["received", "received_transfer"]}` and
   `FIG_CAPTIONS["received_channel_trend"] = "Requests received by channel (applicant vs on transfer)"`.
   The generic engine renders it with zero new code.
2. `pages.py`: `PAGE_FIGURE_KEYS["requests-received"]` gains `"received_channel_trend"`, and `_page_requests_received` renders a second `_trend_section(FIG_CAPTIONS["received_channel_trend"], _stat(frame, "received_channel_trend")["value"], "received_channel_trend", source=...)` after the main trend (same workbooks source string).
3. Test (append to `tests/test_ui.py`):

```python
def test_requests_received_page_has_channel_visual():
    # B5 (spec S2.2): applicant vs on-transfer, from the Stage-1 measure
    page = _pages()["requests-received"]
    assert 'data-figure="received_channel_trend"' in page
    assert "on transfer" in page
```

The data-notes/how-to-use copy claiming the channel is "not yet charted" becomes false when this lands — update BOTH sentences in the same commit (data-notes platform bullet: "...ingested as its own measure and charted on the Requests received page."; how-to-use: same clause), and extend the existing reconciliation/how-to-use tests only if their assertions break.

- [ ] **Step 4: Run the tests** (`python -m pytest tests/test_figure_specs.py tests/test_ui.py -v`, 600s) — ALL pass. Also `python -m pytest tests/test_server.py -v` (movers keys are STAT_KEYS members; the `kpis` DSL op iterates STAT_KEYS — verify it tolerates dict-valued stats or exclude movers from that op; if `query_dataset(op="kpis")` breaks, scope it to scalar stats and say so in the report).

- [ ] **Step 5: Commit**

```bash
git add src/stats/catalog.py src/site/pages.py src/site/assets/site.css tests/test_figure_specs.py tests/test_ui.py
git commit -m "feat(stats): generalised FY-pair movers rendered on both change pages"
```

---

### Task 6: Consolidation and stale-record sweep

**Files:**
- Modify: `src/stats/catalog.py` (comments/docstrings only), `src/site/pages.py` (at-a-glance caption derivation), `scripts/deploy.py` (schema predicate), `tests/test_ui.py` (hygiene items)
- Test: existing files

Six precise items, no behaviour changes except the probe:

- [ ] **Step 1:** `catalog.py` `_FACT_KEYS` comment (lines 43-46) — replace with:

```python
# a fact row the stat consumed -> canonical JSON. portfolio is EXCLUDED on
# purpose and must stay excluded: pre-Stage-1 datasets were stored with
# portfolio='' and their lineage rows_hash values were computed without it, so
# including it would make replay_verify fail for every dataset ingested before
# 2026-08-25. The DB stores portfolio (storage/facts.py) — this hash simply
# does not consume it.
```

- [ ] **Step 2:** `_fy_series` docstring: delete the stale "the annual files only publish received/finalised" sentence (they publish decisions/outcomes/timeliness since commit 43fad97); keep the None-vs-empty contract text. `timeliness_slippage_corr` branch comment: it now computes a real coefficient (within_statutory has an annual series); rewrite the comment to say the correlation is computed over the FY series and returns None only when a series is degenerate. `FIG_CAPTIONS["timeliness_trend"]` "(within/after)" becomes "(within statutory)".

- [ ] **Step 3:** `_page_at_a_glance`: replace the nine hardcoded `source=GOLDEN_SOURCE` arguments with derivation from the basis, mirroring `_kpis`: compute once `src_sq = GOLDEN_SOURCE` next to `basis_sq` and pass `source=src_sq` — then the latent copy-paste gap is documented where the value is defined, with a one-line comment: `# every tile in this block is a single-quarter golden figure (basis_sq)`. (This closes the Task-6 deferred minor at its root: one definition, nine uses.)

- [ ] **Step 3b (B11 decision — KPI tiles caption as national):** in `pages.py`, every page that renders both `_kpis(...)` (or the at-a-glance KPI blocks) AND the filter bar gets one static line directly under its last kpis div:

```python
    <p class="fignote">KPI tiles show national totals for the published quarter;
    the filters apply to the charts below.</p>
```

Emit it from a tiny helper `_kpi_scope_note()` returning that string, called on the chart pages that have KPI tiles (at-a-glance, requests-received, requests-finalised, requests-decided, decision-outcomes, timeliness). Test (append to `tests/test_ui.py`):

```python
def test_kpi_tiles_carry_national_scope_note():
    # B11 (decision 2026-08-25): tiles are static national figures; the note
    # says so instead of pretending the agency filter reaches them
    pages = _pages()
    for key in ("at-a-glance", "requests-received", "decision-outcomes"):
        assert "KPI tiles show national totals" in pages[key], key
```

- [ ] **Step 4:** `scripts/deploy.py` `_DB_PROBE`: both information_schema queries gain a schema predicate — `WHERE table_schema=%s AND table_name=%s AND column_name=%s` with params `("horizon", "foi_chat_users", "role")` and `("horizon", "foi_facts", "portfolio")`. No single quotes; keep line count/order (probe still prints 3 lines).

- [ ] **Step 5:** test hygiene in `tests/test_ui.py`: `test_filters_blob_exposes_portfolios` drops the redundant manual unescape (plain `json.loads(m.group(1))` like the file's other blob tests); add versioned-src assertions for the gated pages' scripts:

```python
def test_gated_page_scripts_carry_content_hash():
    from site.templates import _asset_link
    for name in ("chat.js", "report.js"):
        tag = _asset_link(name)
        assert re.search(rf'src="/assets/{re.escape(name)}\?v=[0-9a-f]{{12}}"', tag)
```

- [ ] **Step 6:** Run `python -m pytest tests/test_ui.py tests/test_housekeeping.py tests/test_figure_specs.py -v` (600s) — all pass (the probe test from Stage 1 greps strings that survive the predicate change; if its regex breaks, update the TEST to the new probe text — the five account names, "(5/5)", and "portfolio column:" contracts all still hold).

- [ ] **Step 7: Commit**

```bash
git add src/stats/catalog.py src/site/pages.py scripts/deploy.py tests/test_ui.py
git commit -m "chore: stale-record sweep, schema-qualified probe, caption consolidation"
```

---

### Task 7: Lineage hygiene

**Files:**
- Modify: `src/server/app.py` (the `/lineage/{artifact_id}` route), `src/site/lineage_viewer.py` (`render_lineage_page`)
- Test: `tests/test_lineage_static.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_lineage_static.py`)

```python
def test_lineage_route_closes_its_connection():
    src = Path("src/server/app.py").read_text(encoding="utf-8")
    m = re.search(r'@app\.get\("/lineage/\{artifact_id\}"\)(.*?)@app\.get',
                  src, re.S)
    assert m and "finally" in m.group(1) and "conn.close()" in m.group(1), \
        "/lineage must close its conn like /dashboards does"
```

(`Path`/`re` imports exist in this file.)

- [ ] **Step 2:** Run `-k closes_its_connection` — FAIL.

- [ ] **Step 3: Implement.** The `/lineage` route wraps its body in try/finally closing `conn` (mirror the `/dashboards` route's structure in the same file exactly). In `lineage_viewer.py`, eliminate the double resolution: `_load_artifact` returns the resolved numeric id alongside the artifact — change its return to `(artifact_dict | None, resolved_id | None)` and update `render_lineage_page` to unpack it instead of calling `_resolve_key_id` a second time. Update the two stub-cursor tests' unpacking accordingly (their SQL-capture assertions stay identical — the contract they pin is unchanged).

- [ ] **Step 4:** Run `python -m pytest tests/test_lineage_static.py tests/test_server.py -v` (300s) — all pass.

- [ ] **Step 5: Commit**

```bash
git add src/server/app.py src/site/lineage_viewer.py tests/test_lineage_static.py
git commit -m "fix(lineage): close route conn, resolve page key once"
```

---

### Task 8: Full-suite gate, payload measurement, live verification checklist

**Files:** none modified (report only).

- [ ] **Step 1:** Full suite, foreground, unpiped: `python -m pytest tests/ -q` (900s timeout). ALL pass; any failure routes to the owning task's fix loop.

- [ ] **Step 2:** Measure the payload win. Scratch script printing per-page `len(_page_data_script(frame, key))` for all 13 pages, before/after comparison against the ~13.1MB Stage-1 baseline (the baseline is in the Stage-1 triage record: 13,100,108 bytes on requests-finalised). Report the table; no pass/fail threshold beyond `tests/test_payload_scope.py`'s pins.

- [ ] **Step 3:** Record in the report the POST-DEPLOY browser checklist the controller executes live (not this task): FY filter on key-agency-contributions-received shows FY2023-24's top-20 (B6/B7 dead); type=personal on requests-received renders a chart (B2 dead); decision-outcomes shows 4 filterable series (B12/B13 dead); change pages rederive + movers tables render (B10/B16 dead); top-20 horizontal with readable names (B9); footnote counts (B8); axis pinned under FY switch, rescaled note under agency (B4); no console errors.
