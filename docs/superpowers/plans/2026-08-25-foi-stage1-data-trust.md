# FOI Stage 1 — Data & Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the data-correctness and trust fixes from the approved spec (`docs/superpowers/specs/2026-08-25-foi-feedback-response-design.md`, Stage 1): portfolio dimension, MoG renames, transfer channel, provenance captions, lineage repair, copy/cache hygiene, housekeeping.

**Architecture:** The site is statically pre-rendered at boot from a long-form facts list (`normalise_all()` → `Frame` → `render_all_pages`), with a Postgres mirror (`horizon.foi_facts`) seeded idempotently. Stage 1 enriches the facts (portfolio, transfer measure, renames), threads the new fields through storage/DSL/UI, and repairs the provenance surfaces (captions + lineage pages).

**Tech Stack:** Python 3.13, FastAPI/Starlette, psycopg2, openpyxl (via `ingest.xlsx.read_sheets`), pytest. No new dependencies.

## Global Constraints

- **Golden gate must keep passing:** boot runs a data-integrity check against `GOLDEN_Q1_FIGURES` (`src/config.py:18-27`); any change that alters Q1 2025-26 headline sums is a defect.
- **`bucket` stays in `('personal','other','total')`** — the DB CHECK (`migrate.sql:24`) and every consumer assume it. The transfer channel is a new *measure*, never a new bucket.
- **Missing data is shown, not invented** (site copy contract): degraded states must be explicit notes/errors, never fabricated values.
- **`site` module name collision:** never `python -c "import site.x"`. Tests import via the existing `conftest.py`/`src/site_shim.py`; ad-hoc scripts use `sys.path.insert(0, "src")`.
- **Test suite is slow (~2–5 min, ingests 7 xlsx at collection).** Run only the named test files per task (`python -m pytest tests/test_X.py -v`, timeout 300s); the full suite runs once at the end of the plan.
- **Measured values only in tests:** where this plan marks a value `MEASURE`, run the given discovery script and pin the printed value into the test. Never guess or copy from prose.
- **Commit after every task** with the repo's `type(scope): summary` style.
- **Do not deploy** during this plan; deployment happens at the stage boundary after the final review.

## File Structure

- `src/ingest/normalise.py` — banner-row portfolio capture, `received_transfer` measure (Tasks 1, 5)
- `src/ingest/mog.py` — RENAME_MAP additions, PORTFOLIO_MAP removal (Tasks 1, 4)
- `src/server/migrate.sql`, `src/storage/facts.py` — portfolio column end-to-end (Task 2)
- `src/stats/dsl.py` — `by_portfolio` fail-loud (Task 3)
- `src/site/pages.py` — platform notes, captions, type-option, how-to-use copy (Tasks 4, 6, 8)
- `src/site/templates.py` — `_asset_link` versioned script tags (Task 8)
- `src/site/assets/site.css` — `.source` caption style (Task 6)
- `src/site/lineage_viewer.py`, `src/server/app.py` — lineage key-resolution + boot seeding (Task 7)
- `scripts/deploy.py`, `README.md`, `.gitignore`, `docs/memories/…` — housekeeping (Task 9)
- Tests: `tests/test_normalise.py`, `tests/test_storage_facts.py` (new), `tests/test_dsl_portfolio.py` (new), `tests/test_ui.py`, `tests/test_lineage_static.py` (new), `tests/test_housekeeping.py` (new)

---

### Task 1: Portfolio capture in ingest

**Files:**
- Modify: `src/ingest/normalise.py` (whole file is 131 lines; key sites: `_fact` at 41-45, `_parse_pot_sheet` loop at 69-79, `_agency_facts` loop at 84-95, `_golden_q1_facts` at 104-112)
- Modify: `src/ingest/mog.py` (delete `PORTFOLIO_MAP` at line 9)
- Test: `tests/test_normalise.py`

**Interfaces:**
- Produces: every fact dict's `portfolio` key now carries the source file's own banner text for that agency+FY (empty string only for golden/derived facts). `_fact()` signature becomes `_fact(agency_key, agency_name, fy, quarter, group, measure, bucket, value, derived=False, portfolio="")`.
- Consumes: nothing from other tasks.

Background: each "Request numbers" / "Action on requests" / "Response times" sheet interleaves *portfolio banner rows* (all-text rows whose col 0 is the portfolio name, currently skipped by `_is_data_row`) with the agency rows belonging to that portfolio. Capturing the last-seen banner while iterating gives a per-(agency, FY) portfolio mapping straight from the source.

- [ ] **Step 1: Discovery — measure real banner→agency pairs**

Write and run this scratch script (do NOT commit it; put it in the session scratchpad):

```python
import sys; sys.path.insert(0, "src")
from config import DATA_SOURCES_DIR
from ingest.xlsx import read_sheets

for fn in ("agency-foi-data-2024-25.xlsx", "agency-foi-data-2025-26-q1-to-q3.xlsx"):
    rows = read_sheets(DATA_SOURCES_DIR / fn)["Request numbers"]
    banner = None
    pairs = []
    for r in rows[3:]:
        if not r[0]:
            continue
        name = str(r[0]).strip()
        if name.startswith("x") or name.lower() == "total":
            continue
        has_num = any(isinstance(c, (int, float)) for c in r[1:])
        if not has_num:
            banner = name
        elif banner and len(pairs) < 3:
            pairs.append((banner, name))
    print(fn, pairs)
```

Record the first (banner, agency) pair printed for EACH file — these are the `MEASURE` values for Step 2's test.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_normalise.py`)

```python
def test_portfolio_captured_from_banner_rows():
    # Stage 1 (spec S1.1): the banner rows are no longer discarded silently —
    # each agency fact carries the portfolio its own source file assigned it
    # that year (per-(agency, FY), no curated map).
    facts = normalise_all()
    real = [f for f in facts if not f["derived"]]
    with_portfolio = [f for f in real if f["portfolio"]]
    assert len(with_portfolio) / len(real) >= 0.95, \
        f"only {len(with_portfolio)}/{len(real)} facts carry a portfolio"
    # MEASURE: pin the two (banner, agency) pairs printed by the discovery
    # script — one per file — replacing the placeholders below before running.
    known = [
        ("2024-25", "<AGENCY-FROM-2024-25-PAIR>", "<BANNER-FROM-2024-25-PAIR>"),
        ("2025-26", "<AGENCY-FROM-2025-26-PAIR>", "<BANNER-FROM-2025-26-PAIR>"),
    ]
    for fy, agency, portfolio in known:
        rows = [f for f in real if f["fy"] == fy and f["agency_name"] == agency]
        assert rows, f"no facts for {agency} in {fy}"
        assert all(f["portfolio"] == portfolio for f in rows), \
            f"{agency} {fy}: got {sorted({f['portfolio'] for f in rows})}"


def test_portfolio_values_are_banners_not_agencies():
    # A portfolio value must never be an agency name: the set of portfolios and
    # the set of agencies are disjoint.
    facts = normalise_all()
    portfolios = {f["portfolio"] for f in facts if f["portfolio"]}
    agencies = {f["agency_name"] for f in facts}
    assert not (portfolios & agencies), sorted(portfolios & agencies)


def test_golden_facts_have_no_portfolio():
    facts = normalise_all()
    for f in facts:
        if f["derived"]:
            assert f["portfolio"] == ""
```

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `python -m pytest tests/test_normalise.py -v -k portfolio` (300s timeout)
Expected: `test_portfolio_captured_from_banner_rows` and `test_golden_facts_have_no_portfolio` FAIL (portfolio is currently always `""`). `test_portfolio_values_are_banners_not_agencies` may pass vacuously — that is fine.

- [ ] **Step 4: Implement banner capture**

In `src/ingest/mog.py`: delete the line `PORTFOLIO_MAP = {}` (line 9).

In `src/ingest/normalise.py`:

1. Change the import (line 6) to `from ingest.mog import normalise_agency`.
2. Replace `_fact` (lines 41-45) with:

```python
def _fact(agency_key, agency_name, fy, quarter, group, measure, bucket, value,
          derived=False, portfolio=""):
    return {"agency_key": agency_key, "agency_name": agency_name, "fy": fy,
            "quarter": quarter, "measure_group": group, "measure": measure,
            "bucket": bucket, "value": _num(value), "derived": derived,
            "portfolio": portfolio}
```

3. In `_parse_pot_sheet` (loop at lines 69-79), track the banner. Replace the loop body with:

```python
    portfolio = ""
    for r in rows[3:]:
        if not r[0]: continue
        name = str(r[0]).strip()
        if name.startswith("x") or name.startswith("xx"): continue
        if name.lower() == "total": continue  # Total row is a trusted value, not a fact
        if not _is_data_row(r):
            portfolio = name  # portfolio banner row: remember, don't emit
            continue
        key = normalise_agency(name)
        for measure, (pc, oc, tc) in offsets.items():
            facts.append(_fact(key, key, fy, quarter, group, measure, "personal", _num(r[pc]), portfolio=portfolio))
            facts.append(_fact(key, key, fy, quarter, group, measure, "other", _num(r[oc]), portfolio=portfolio))
            facts.append(_fact(key, key, fy, quarter, group, measure, "total", _num(r[tc]), portfolio=portfolio))
```

4. Apply the identical transformation to `_agency_facts` (loop at lines 84-95): initialise `portfolio = ""` before the loop, set it on the `not _is_data_row(r)` branch instead of `continue`-ing silently, and pass `portfolio=portfolio` in the three `_fact` calls.

(`_golden_q1_facts` needs no change: `_fact`'s default `portfolio=""` covers it.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_normalise.py -v` (300s timeout)
Expected: ALL tests in the file pass, including the pre-existing `test_portfolio_banner_rows_skipped` and `test_disr_renamed_to_most_recent_name` (banner rows must still not appear as agencies).

- [ ] **Step 6: Commit**

```bash
git add src/ingest/normalise.py src/ingest/mog.py tests/test_normalise.py
git commit -m "feat(ingest): capture portfolio from banner rows per (agency, FY)"
```

---

### Task 2: Portfolio through the database

**Files:**
- Modify: `src/server/migrate.sql` (foi_facts table, after line 29)
- Modify: `src/storage/facts.py` (INSERT at lines 76-84, SELECT at lines 108-120)
- Test: `tests/test_storage_facts.py` (new)

**Interfaces:**
- Consumes: fact dicts with a real `portfolio` value (Task 1).
- Produces: `horizon.foi_facts.portfolio` column; `load_facts()` rows carry the stored portfolio instead of hardcoded `""`.

Note: `_CANONICAL_KEYS` already includes `portfolio`, so `canonical_hash` changes when portfolios fill in — the idempotency gate correctly creates a fresh dataset on next ingest. No change needed there.

- [ ] **Step 1: Write the failing tests** (new file `tests/test_storage_facts.py`)

```python
"""storage.facts — portfolio must survive the DB roundtrip (spec S1.1)."""
import re
from pathlib import Path

from storage import facts as facts_mod


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def test_migrate_sql_adds_portfolio_column():
    sql = _read("src/server/migrate.sql")
    assert re.search(
        r"ALTER TABLE horizon\.foi_facts\s+ADD COLUMN IF NOT EXISTS portfolio TEXT NOT NULL DEFAULT ''",
        sql), "idempotent portfolio ALTER missing from migrate.sql"


def test_insert_includes_portfolio():
    src = _read("src/storage/facts.py")
    m = re.search(r"INSERT INTO horizon\.foi_facts.*?VALUES[^)]*\)", src, re.S)
    assert m and "portfolio" in m.group(0), "foi_facts INSERT must include portfolio"


def test_load_facts_selects_portfolio_not_hardcoded():
    src = _read("src/storage/facts.py")
    assert '"portfolio": ""' not in src, "load_facts still hardcodes portfolio=''"
    m = re.search(r"SELECT[^\"]*?derived, portfolio\s*\"", src) or \
        re.search(r"SELECT.*portfolio.*FROM horizon\.foi_facts", src, re.S)
    assert m, "load_facts SELECT must include the portfolio column"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_storage_facts.py -v`
Expected: all three FAIL.

- [ ] **Step 3: Implement**

`src/server/migrate.sql` — after the `idx_foi_facts_measure` index (line 30), add (mirroring the existing `role` ALTER pattern at lines 82-84):

```sql
-- Stage 1 (portfolio dimension): source-file portfolio per fact. Existing
-- rows default to ''; new ingests write the banner-row portfolio.
ALTER TABLE horizon.foi_facts
  ADD COLUMN IF NOT EXISTS portfolio TEXT NOT NULL DEFAULT '';
```

`src/storage/facts.py` — in `ingest_facts` (lines 76-84), extend the INSERT:

```python
                cur.execute(
                    "INSERT INTO horizon.foi_facts "
                    "(dataset_id, agency_key, agency_name, fy, quarter, "
                    " measure_group, measure, bucket, value, derived, portfolio, row_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (dataset_id, row["agency_key"], row["agency_name"], row["fy"],
                     row["quarter"], row["measure_group"], row["measure"],
                     row["bucket"], row["value"], bool(row["derived"]),
                     row.get("portfolio") or "",
                     hashlib.sha256(json.dumps(row, sort_keys=True).encode("utf-8")).hexdigest()))
```

In `load_facts` (lines 108-120), select and return it:

```python
            cur.execute(
                "SELECT agency_key, agency_name, fy, quarter, measure_group, "
                "measure, bucket, value, derived, portfolio "
                "FROM horizon.foi_facts WHERE dataset_id = %s "
                "ORDER BY agency_key, fy, quarter, measure_group, measure, bucket",
                (dataset_id,))
            rows = cur.fetchall()
        return [
            {"agency_key": r[0], "agency_name": r[1], "fy": r[2], "quarter": r[3],
             "measure_group": r[4], "measure": r[5], "bucket": r[6],
             "value": float(r[7]), "derived": bool(r[8]), "portfolio": r[9] or ""}
            for r in rows
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_storage_facts.py -v`
Expected: PASS (3/3).

- [ ] **Step 5: Commit**

```bash
git add src/server/migrate.sql src/storage/facts.py tests/test_storage_facts.py
git commit -m "feat(storage): persist and reload the portfolio dimension"
```

---

### Task 3: `by_portfolio` fails loud when unmapped

**Files:**
- Modify: `src/stats/dsl.py` (the `by_portfolio` branch, lines 122-133)
- Test: `tests/test_dsl_portfolio.py` (new)

**Interfaces:**
- Consumes: fact dicts with `portfolio` (Task 1). `Frame` is constructed as `Frame(list_of_fact_dicts)` (see `storage/frame.py`; facts are plain dicts).
- Produces: `query_dataset(frame, "by_portfolio", params)` returns `{"error": ...}` when no fact in the slice carries a portfolio, and reports partial coverage explicitly.

- [ ] **Step 1: Write the failing tests** (new file `tests/test_dsl_portfolio.py`)

```python
"""by_portfolio must never return a silently-degenerate single bucket."""
from stats.dsl import query_dataset
from storage.frame import Frame


def _fact(agency, fy, value, portfolio):
    return {"agency_key": agency, "agency_name": agency, "fy": fy,
            "quarter": None, "measure_group": "requests", "measure": "received",
            "bucket": "total", "value": float(value), "derived": False,
            "portfolio": portfolio}


def test_by_portfolio_errors_when_wholly_unmapped():
    frame = Frame([_fact("A", "2024-25", 10, ""), _fact("B", "2024-25", 20, "")])
    out = query_dataset(frame, "by_portfolio", {"fy": "2024-25"})
    assert "error" in out, out
    assert "portfolio" in out["error"].lower()


def test_by_portfolio_reports_partial_coverage():
    frame = Frame([_fact("A", "2024-25", 10, "Health"),
                   _fact("B", "2024-25", 20, "")])
    out = query_dataset(frame, "by_portfolio", {"fy": "2024-25"})
    assert out.get("portfolios") == [{"portfolio": "Health", "value": 10}]
    assert out.get("unmapped_agency_count") == 1


def test_by_portfolio_aggregates_mapped_facts():
    frame = Frame([_fact("A", "2024-25", 10, "Health"),
                   _fact("B", "2024-25", 20, "Health"),
                   _fact("C", "2024-25", 5, "Treasury")])
    out = query_dataset(frame, "by_portfolio", {"fy": "2024-25"})
    assert out["portfolios"] == [{"portfolio": "Health", "value": 30},
                                 {"portfolio": "Treasury", "value": 5}]
    assert out.get("unmapped_agency_count") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dsl_portfolio.py -v`
Expected: first two FAIL (current code returns one "Unmapped" bucket); third may pass.

- [ ] **Step 3: Implement** — replace the `by_portfolio` branch body (dsl.py lines 122-133):

```python
    if op == "by_portfolio":
        # the golden "Total" pseudo-agency is a total-level fact, not an agency
        rows = [f for f in frame.facts if f["agency_name"].lower() != "total"]
        if params.get("fy"): rows = [f for f in rows if f["fy"] == params["fy"]]
        if params.get("measure"): rows = [f for f in rows if f["measure"] == params["measure"]]
        if params.get("bucket"): rows = [f for f in rows if f["bucket"] == params["bucket"]]
        mapped = [f for f in rows if f.get("portfolio")]
        unmapped_agencies = {f["agency_name"] for f in rows if not f.get("portfolio")}
        if rows and not mapped:
            # fail-loud: an all-unmapped slice would otherwise collapse into one
            # plausible-looking "Unmapped" bucket (spec S1.1)
            return {"error": "portfolio mapping unavailable for this slice; "
                             "no fact carries a portfolio — re-ingest with the "
                             "banner-row capture normaliser"}
        aggs = {}
        for f in mapped:
            aggs.setdefault(f["portfolio"], 0.0)
            aggs[f["portfolio"]] += f["value"]
        return {"basis": params.get("window_mode", "fy"),
                "unmapped_agency_count": len(unmapped_agencies),
                "portfolios": [{"portfolio": p, "value": round(v)}
                               for p, v in sorted(aggs.items(), key=lambda kv: kv[1], reverse=True)]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dsl_portfolio.py -v`
Expected: PASS (3/3). Also run `python -m pytest tests/test_dsl.py -v` if that file exists (check with `ls tests/`) — pre-existing by_portfolio expectations may need their fixtures updated to carry portfolios; update fixtures, never weaken the new error contract.

- [ ] **Step 5: Commit**

```bash
git add src/stats/dsl.py tests/test_dsl_portfolio.py
git commit -m "fix(dsl): by_portfolio fails loud instead of one Unmapped bucket"
```

---

### Task 4: MoG renames, courts merger, platform reconciliation notes

**Files:**
- Modify: `src/ingest/mog.py` (RENAME_MAP, lines 2-8)
- Modify: `src/site/pages.py` (`_page_data_notes`, lines 454-467)
- Test: `tests/test_normalise.py`, `tests/test_ui.py`

**Interfaces:**
- Consumes: `normalise_agency()` (unchanged signature).
- Produces: six new RENAME_MAP entries; data-notes page gains a "Platform reconciliation notes" section after the verbatim corpus.

- [ ] **Step 1: Discovery — measure the merged courts series**

Scratch script (do not commit):

```python
import sys; sys.path.insert(0, "src")
from ingest.normalise import normalise_all
facts = normalise_all()
for name in ("Federal Circuit Court of Australia", "Family Court of Australia",
             "Federal Circuit and Family Court of Australia (Division 2)",
             "Federal Circuit and Family Court of Australia"):
    rows = [f for f in facts if f["agency_name"] == name
            and f["measure"] == "received" and f["bucket"] == "total"]
    by_fy = {}
    for f in rows: by_fy[f["fy"]] = by_fy.get(f["fy"], 0) + f["value"]
    print(name, {k: round(v) for k, v in sorted(by_fy.items())})
```

Record: (a) the EXACT post-merger agency name as it appears in the source (with or without "(Division 2)"), and (b) the per-FY sums for the two predecessor courts — the merged series' pre-2021-22 expected values are their sums.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_normalise.py`)

```python
def test_mog_renames_resolve_to_most_recent_name():
    # Stage 1 (spec S1.2): OAIC's convention — renamed agencies appear under
    # their most recent name for all periods.
    facts = normalise_all()
    agencies = {f["agency_name"] for f in facts}
    for old in ("Independent Hospital Pricing Authority",
                "Asbestos Safety and Eradication Agency",
                "Department of Health and Aged Care",
                "Net Zero Economy Agency",
                "Federal Circuit Court of Australia",
                "Family Court of Australia"):
        assert old not in agencies, f"old name not resolved: {old}"
    for new in ("Independent Health and Aged Care Pricing Authority",
                "Asbestos and Silica Safety and Eradication Agency",
                "Department of Health, Disability and Ageing",
                "Net Zero Economy Authority"):
        assert new in agencies, f"current name missing: {new}"


def test_courts_merger_aggregates_predecessors():
    # The 2021 merger: both predecessor courts map to the merged entity, so its
    # series is continuous. MEASURE: pin the merged name and the pre-merger FY
    # sums from the Task 4 discovery script before running.
    facts = normalise_all()
    merged = "<EXACT-MERGED-NAME-FROM-DISCOVERY>"
    rows = [f for f in facts if f["agency_name"] == merged
            and f["measure"] == "received" and f["bucket"] == "total"]
    by_fy = {}
    for f in rows: by_fy[f["fy"]] = by_fy.get(f["fy"], 0) + f["value"]
    expected_2019_20 = 0  # MEASURE: FCC 2019-20 + FamCourt 2019-20
    expected_2020_21 = 0  # MEASURE: FCC 2020-21 + FamCourt 2020-21
    assert round(by_fy.get("2019-20", -1)) == expected_2019_20, by_fy
    assert round(by_fy.get("2020-21", -1)) == expected_2020_21, by_fy
```

And append to `tests/test_ui.py`:

```python
def test_data_notes_platform_reconciliation_section():
    # A2 + S1.2 disclosure: the data-notes page explains the 34,810 vs 34,418
    # split and the courts-merger aggregation, in a clearly-separated platform
    # section (the corpus notes above it stay verbatim).
    page = _pages()["data-notes"]
    assert "Platform reconciliation notes" in page
    assert "34,418" in page and "34,810" in page and "392" in page
    assert "Federal Circuit and Family Court" in page
```

(`_pages()` is `tests/test_ui.py`'s existing module-level helper at line 25 — `render_all_pages(Frame(normalise_all()))`; every test in that file calls it directly, no fixtures.)

- [ ] **Step 3: Run to verify failures**

Run: `python -m pytest tests/test_normalise.py -k "mog or courts" -v` and `python -m pytest tests/test_ui.py -k reconciliation -v`
Expected: FAIL (names unmapped; section absent).

- [ ] **Step 4: Implement**

`src/ingest/mog.py` — extend RENAME_MAP (keep the DISR entry and comment; use the exact merged-court name from discovery):

```python
    # Stage 1 (2026-08-25 spec S1.2): further verified renames, same
    # most-recent-name convention as DISR.
    "Independent Hospital Pricing Authority": "Independent Health and Aged Care Pricing Authority",
    "Asbestos Safety and Eradication Agency": "Asbestos and Silica Safety and Eradication Agency",
    "Department of Health and Aged Care": "Department of Health, Disability and Ageing",
    "Net Zero Economy Agency": "Net Zero Economy Authority",
    # 2021 courts merger — both predecessors aggregate under the merged court
    # (disclosed on the data-notes page).
    "Federal Circuit Court of Australia": "<EXACT-MERGED-NAME-FROM-DISCOVERY>",
    "Family Court of Australia": "<EXACT-MERGED-NAME-FROM-DISCOVERY>",
```

`src/site/pages.py` — in `_page_data_notes` (lines 462-465), append a platform section after the verbatim notes div:

```python
    platform = (
        '<h2>Platform reconciliation notes</h2>'
        '<div class="notes"><p>These notes are Bluebird FOI Insights\' own, '
        'separate from the publisher\'s notes above.</p><ul>'
        '<li><strong>Requests received basis.</strong> The dashboard\'s '
        '"requests received" figures count requests received <em>from '
        'applicants</em> (34,418 for FY2025-26 Q1&ndash;Q3). The source '
        'workbook\'s "Total requests received" (34,810) additionally includes '
        '392 requests received on transfer from another agency; the transfer '
        'channel is ingested as its own measure.</li>'
        '<li><strong>2021 courts merger.</strong> The Federal Circuit Court of '
        'Australia and the Family Court of Australia merged in 2021; both '
        'predecessors\' figures are aggregated under the merged court '
        '(Federal Circuit and Family Court of Australia) for all periods, '
        'per the publisher\'s most-recent-name convention.</li>'
        '<li><strong>Agency renames.</strong> Renamed agencies appear under '
        'their most recent name for all periods (e.g. DISR, IHACPA, ASSEA, '
        'Health, Disability and Ageing, Net Zero Economy Authority).</li>'
        '</ul></div>')
    body = ("<h1>Data notes and disclaimer</h1>"
            '<p class="intro">These notes are reproduced verbatim from the '
            "source dataset (FOI statistics) on data.gov.au.</p>"
            f'<div class="notes">{_md(notes)}</div>'
            f'{platform}')
```

(Adjust the merged-court display name in the note if discovery shows it carries "(Division 2)".)

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_normalise.py tests/test_ui.py -v` (300s timeout)
Expected: ALL pass — including `test_disr_renamed_to_most_recent_name` (untouched) and `test_portfolio_values_are_banners_not_agencies`.

- [ ] **Step 6: Commit**

```bash
git add src/ingest/mog.py src/site/pages.py tests/test_normalise.py tests/test_ui.py
git commit -m "feat(ingest): verified MoG renames + courts merger, disclosed on data-notes"
```

---

### Task 5: `received_transfer` measure

**Files:**
- Modify: `src/ingest/normalise.py` (MEASURE_COLS, lines 36-39)
- Test: `tests/test_normalise.py`

**Interfaces:**
- Produces: facts with `measure == "received_transfer"` (P/O/T buckets, cols 7-9) for every Request numbers sheet. Stage 2's channel visual consumes this.

- [ ] **Step 1: Write the failing test** (append to `tests/test_normalise.py`)

```python
def test_received_transfer_measure_ingested():
    # B5 (spec S1.3): the on-transfer channel (cols 7-9) is a real measure.
    # FY2024-25 transfer total is 697 — the sheet's own Total row transfer
    # value (427 P + 270 O = 697 T), verified against the source 2026-08-25.
    facts = normalise_all()
    rows = [f for f in facts if f["measure"] == "received_transfer"
            and f["bucket"] == "total" and f["fy"] == "2024-25"]
    assert rows, "no received_transfer facts for 2024-25"
    assert round(sum(f["value"] for f in rows)) == 697
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_normalise.py -k transfer -v` (300s timeout)
Expected: FAIL (no such measure).

- [ ] **Step 3: Implement** — extend MEASURE_COLS (normalise.py lines 36-39):

```python
MEASURE_COLS = {
    "received": (4, 5, 6),            # from applicant: personal, other, total
    "received_transfer": (7, 8, 9),   # on transfer from another agency
    "finalised": (16, 17, 18),
}
```

- [ ] **Step 4: Run the full normalise + UI test files**

Run: `python -m pytest tests/test_normalise.py tests/test_ui.py tests/test_server.py -v` (300s timeout)
Expected: ALL pass. Watch specifically: the golden gate (boot integrity) must not change — `received_transfer` is a new measure and must not leak into `received` sums. If any figure/count test fails, the fix is wrong — do not adjust expected values of pre-existing tests.

- [ ] **Step 5: Commit**

```bash
git add src/ingest/normalise.py tests/test_normalise.py
git commit -m "feat(ingest): received_transfer measure from the on-transfer columns"
```

---

### Task 6: Provenance captions on KPI tiles and figure cards

**Files:**
- Modify: `src/site/pages.py` (`_kpi` at 207-212, `_kpis` at 215-231, `_trend_section`/`_top20_section` at 234-245, at-a-glance direct `_kpi` calls at 282-284 and any sibling calls in `_page_at_a_glance`)
- Modify: `src/site/assets/site.css` (new `.kpi .source` / `.figure-card .source` rule)
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: `_kpi(label, value_html, basis=None, title=None, source=None)`; `_trend_section(title, fig, chart_key, source=None)`, `_top20_section(title, fig, chart_key, source=None)`.

The rule: every stat whose basis is *single quarter* is a golden transcribed figure (only `quarter=1` facts exist and they are all `derived=True`), so single-quarter tiles get the fixed transcription caption automatically. FY figure cards name their source workbooks.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ui.py`, following the file's existing page-fixture convention)

```python
GOLDEN_SOURCE_SNIPPET = "Transcribed from the OAIC Power BI report, Q1 2025-26"

def test_single_quarter_kpis_carry_transcription_source():
    # B15 (spec S1.4): every basis-single-quarter tile says where the number
    # comes from — it is not derivable from the cumulative workbook.
    pages = _pages()
    for key in ("at-a-glance", "decision-outcomes", "timeliness"):
        assert GOLDEN_SOURCE_SNIPPET in pages[key], \
            f"{key} lacks the golden-source caption"

def test_fy_figure_cards_name_their_source():
    pages = _pages()
    assert "agency-foi-data-2024-25.xlsx" in pages["key-agency-contributions-received"]
    assert "data.gov.au FOI statistics workbooks" in pages["requests-received"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_ui.py -k source -v` (300s timeout)
Expected: FAIL.

- [ ] **Step 3: Implement**

`_kpi` (pages.py 207-212) becomes:

```python
def _kpi(label, value_html, basis=None, title=None, source=None) -> str:
    """A KPI tile: label, value, basis label, and provenance line when given."""
    basis_html = f'<span class="basis">{html.escape(str(basis))}</span>' if basis else ""
    title_html = f'<span class="tlabel">{html.escape(str(title))}</span>' if title else ""
    source_html = f'<span class="source">{html.escape(str(source))}</span>' if source else ""
    return (f'<div class="kpi">{title_html}<span class="label">{label}</span>'
            f'<span class="value">{value_html}</span>{basis_html}{source_html}</div>')
```

Add the module constant near the top of pages.py (after `_CHART_SCRIPTS`):

```python
# provenance caption for the transcribed golden Q1 figures (spec S1.4)
GOLDEN_SOURCE = ("Transcribed from the OAIC Power BI report, Q1 2025-26 "
                 "(Jul–Sep 2025); not derivable from the cumulative "
                 "Q1–Q3 workbook.")
```

In `_kpis` (215-231): after computing `basis = _basis_label(stat)`, add
`source = GOLDEN_SOURCE if (basis and "single quarter" in str(basis)) else None`
and pass `source=source` to `_kpi(...)`. In `_page_at_a_glance`, the direct
`_kpi(..., basis_sq)` calls (282-284 and siblings) get `source=GOLDEN_SOURCE`.

`_trend_section` / `_top20_section` (234-245) gain `source=None` param rendering
`<p class="source">…</p>` after the basis line; update the call sites:
trend pages pass `source="Source: data.gov.au FOI statistics workbooks, FY2019-20 – FY2025-26 (Q1–Q3 cumulative)"`, top-20 pages pass `source="Source: agency-foi-data-2024-25.xlsx"`. Locate every call site with `grep -n "_trend_section\|_top20_section" src/site/pages.py` and pass the appropriate string at each.

`src/site/assets/site.css` — add next to the existing `.kpi .basis` rule (find with `grep -n "\.basis" src/site/assets/site.css`):

```css
.kpi .source, .figure-card .source {
  display: block; font-size: 0.72rem; color: var(--muted); margin-top: 2px;
}
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_ui.py -v` (300s timeout)
Expected: ALL pass (the CSS content-hash test will pass automatically — the hash re-derives).

- [ ] **Step 5: Commit**

```bash
git add src/site/pages.py src/site/assets/site.css tests/test_ui.py
git commit -m "feat(site): provenance captions on golden KPI tiles and figure cards"
```

---

### Task 7: Lineage — key resolution and boot seeding for static pages

**Files:**
- Modify: `src/site/lineage_viewer.py` (`_load_artifact`, lines 30-49)
- Modify: `src/server/app.py` (`_seed_facts` region, lines 132-166; new `_seed_static_lineage` called from it)
- Test: `tests/test_lineage_static.py` (new)

**Interfaces:**
- Consumes: `record_artifact(conn, *, artifact_type, artifact_key, user_id, dataset_id, request_text, spec_json, model, status) -> int | None` and `record_op(conn, *, artifact_id, dataset_id, kind, op, params, row_count, rows_hash, result_value)` from `storage/lineage.py`; `PAGE_FIGURE_KEYS` from `site/pages.py`; `foi_stats` from `stats/catalog.py`.
- Produces: `/lineage/<page-key>` renders a real seeded lineage page (never 500); `_load_artifact` accepts non-numeric ids by resolving `artifact_key`.

- [ ] **Step 1: Write the failing tests** (new file `tests/test_lineage_static.py`)

```python
"""Lineage for static pages: key resolution (B1 fix) + boot seeding (S1.5)."""
import re
from pathlib import Path


class _Cursor:
    """Stub cursor recording SQL; returns canned rows per query shape."""
    def __init__(self, artifact_row=None, key_row=None):
        self.artifact_row = artifact_row
        self.key_row = key_row
        self.executed = []
    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        self._last = sql
    def fetchone(self):
        if "artifact_key = " in self._last or "artifact_key=" in self._last:
            return self.key_row
        return self.artifact_row
    def fetchall(self):
        return []
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Conn:
    def __init__(self, cursor): self._cur = cursor
    def cursor(self): return self._cur


def test_load_artifact_resolves_page_key_not_dataerror():
    # B1: a non-numeric id must resolve via artifact_key, never hit the bigint
    # id compare (which raises psycopg2.DataError -> 500 on the live site).
    from site.lineage_viewer import _load_artifact
    cur = _Cursor(key_row=(7,),
                  artifact_row=("static_page", "at-a-glance", None, 1,
                                "static render", "{}", "static-render", "rendered"))
    art = _load_artifact("at-a-glance", _Conn(cur))
    id_queries = [q for q, _ in cur.executed if "WHERE id = " in q]
    key_queries = [q for q, _ in cur.executed if "artifact_key" in q]
    assert key_queries, "non-numeric id must be resolved by artifact_key first"
    for q, params in cur.executed:
        if "WHERE id = " in q:
            assert all(not (isinstance(p, str) and not p.isdigit())
                       for p in (params or ())), "raw page-key hit the id compare"
    assert art is not None and art["artifact_key"] == "at-a-glance"


def test_load_artifact_unknown_key_degrades_to_none():
    from site.lineage_viewer import _load_artifact
    cur = _Cursor(key_row=None, artifact_row=None)
    assert _load_artifact("no-such-page", _Conn(cur)) is None


def test_boot_seeds_static_lineage():
    # app.py must define _seed_static_lineage and call it from the facts seed;
    # source-level contract check (a live-DB integration test needs Postgres).
    src = Path("src/server/app.py").read_text(encoding="utf-8")
    assert "_seed_static_lineage" in src
    assert re.search(r"artifact_type=.static_page.", src)
    assert src.index("_seed_static_lineage(") < len(src)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_lineage_static.py -v`
Expected: FAIL (resolver missing; seeding missing).

- [ ] **Step 3: Implement the resolver** — in `src/site/lineage_viewer.py`, replace `_load_artifact` (lines 30-49):

```python
def _load_artifact(artifact_id, conn):
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            # B1: the static pages link /lineage/<page-key>. A non-numeric id
            # against the BIGSERIAL id column raises psycopg2.DataError (a
            # non-Operational error -> 500). Resolve page keys via artifact_key
            # (latest row wins); only genuinely numeric ids hit the id compare.
            if not (isinstance(artifact_id, int)
                    or (isinstance(artifact_id, str) and artifact_id.isdigit())):
                cur.execute(
                    "SELECT id FROM horizon.lineage_artifacts "
                    "WHERE artifact_key = %s ORDER BY id DESC LIMIT 1",
                    (str(artifact_id),))
                row = cur.fetchone()
                if not row:
                    return None
                artifact_id = row[0]
            cur.execute(
                "SELECT artifact_type, artifact_key, user_id, dataset_id, "
                "request_text, spec_json, model, status "
                "FROM horizon.lineage_artifacts WHERE id = %s", (int(artifact_id),))
            row = cur.fetchone()
        if not row:
            return None
        return {"artifact_type": row[0], "artifact_key": row[1],
                "user_id": row[2], "dataset_id": row[3],
                "request_text": row[4], "spec_json": row[5],
                "model": row[6], "status": row[7]}
    except psycopg2.OperationalError:
        return None  # fail-open: an unreachable DB must not crash a page
    except psycopg2.Error:
        raise        # fail-loud: a schema/programming error must surface
```

Note: `_load_ops`/`_load_tool_calls` receive the ORIGINAL `artifact_id` from `render_lineage_page` (line 143-144) — they query `artifact_id = %s` against a BIGINT and would hit the same DataError for a page key. Fix inside `render_lineage_page`: after loading the artifact, resolve the numeric id once and pass it down. Change lines 140-144 to:

```python
    artifact = _s(data, "artifact") or _load_artifact(artifact_id, conn)
    resolved_id = artifact_id
    if artifact is not None and not (isinstance(artifact_id, int) or
                                     (isinstance(artifact_id, str) and str(artifact_id).isdigit())):
        resolved_id = _resolve_key_id(artifact_id, conn)
    dataset_id = (artifact or {}).get("dataset_id")
    dataset = _s(data, "dataset") or _load_dataset(dataset_id, conn)
    ops = _s(data, "ops") or (_load_ops(resolved_id, conn) if resolved_id is not None else None)
    tool_calls = _s(data, "tool_calls") or (_load_tool_calls(resolved_id, conn) if resolved_id is not None else None)
```

with the small helper added above `_load_artifact` (and reused by it to avoid duplicating the lookup):

```python
def _resolve_key_id(artifact_key, conn):
    """Latest lineage_artifacts.id for an artifact_key, or None."""
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM horizon.lineage_artifacts "
                "WHERE artifact_key = %s ORDER BY id DESC LIMIT 1",
                (str(artifact_key),))
            row = cur.fetchone()
        return row[0] if row else None
    except psycopg2.OperationalError:
        return None
    except psycopg2.Error:
        raise
```

(Refactor `_load_artifact`'s non-numeric branch to call `_resolve_key_id` instead of inlining the query.)

- [ ] **Step 4: Implement boot seeding** — in `src/server/app.py`, add after `_seed_facts` (line 166), and call it from `_seed_facts` right after `_DATASET_ID = ingest_facts(...)` succeeds (same try block, same conn):

```python
def _seed_static_lineage(conn, frame, dataset_id) -> None:
    """Seed one static_page lineage artifact per rendered page (spec S1.5), so
    'View lineage for this dashboard' is truthful for the static pages, not
    just AI-built ones. Idempotent per (artifact_key, dataset_id): a re-boot
    over the same dataset seeds nothing. Best-effort like the rest of lineage."""
    from site.pages import PAGE_FIGURE_KEYS
    from site.templates import SIDENAV_GROUPS
    page_keys = [key for _, items in SIDENAV_GROUPS for key, _ in items]
    for key in page_keys:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM horizon.lineage_artifacts "
                    "WHERE artifact_key = %s AND dataset_id = %s LIMIT 1",
                    (key, dataset_id))
                if cur.fetchone():
                    continue
            fig_keys = PAGE_FIGURE_KEYS.get(key, [])
            artifact_id = record_artifact(
                conn, artifact_type="static_page", artifact_key=key,
                user_id=None, dataset_id=dataset_id,
                request_text=(f"Static dashboard page '{key}': rendered at boot "
                              "from the normalised frame (no AI involved)."),
                spec_json={"page": key, "figures": fig_keys},
                model="static-render", status="rendered")
            if artifact_id is None:
                continue
            for fig_key in fig_keys:
                stat = foi_stats(frame, fig_key)
                record_op(conn, artifact_id=artifact_id, dataset_id=dataset_id,
                          kind="figure", op=fig_key, params={},
                          row_count=stat.get("source_rows"),
                          rows_hash=stat.get("rows_hash"),
                          result_value=stat.get("value"))
        except psycopg2.OperationalError:
            return  # fail-open: lineage must never block boot
```

(`foi_stats` is already imported in app.py — confirm with `grep -n "foi_stats" src/server/app.py`; add the import if not.) In `_seed_facts`, after the successful `_DATASET_ID = ingest_facts(frame.facts, conn=conn)` line, add:

```python
        if _DATASET_ID is not None:
            _seed_static_lineage(conn, frame, _DATASET_ID)
```

- [ ] **Step 5: Run the tests**

Run: `python -m pytest tests/test_lineage_static.py tests/test_server.py -v` (300s timeout)
Expected: ALL pass (test_server exercises boot without a DB — seeding must fail open when `get_conn` raises).

- [ ] **Step 6: Commit**

```bash
git add src/site/lineage_viewer.py src/server/app.py tests/test_lineage_static.py
git commit -m "fix(lineage): resolve page-key lineage links and seed static-page lineage at boot"
```

---

### Task 8: Copy fix, JS cache-busting, type-option cleanup

**Files:**
- Modify: `src/site/templates.py` (`_css_link` at 53-58 → generalised `_asset_link`; export it)
- Modify: `src/site/pages.py` (`_CHART_SCRIPTS` at 26-27, chat/report script tags at 649/668, type_opts at 154-157, how-to-use Filters paragraph at 492-495)
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: `templates._asset_link(name) -> str` emitting `<script src="/assets/<name>?v=<12-hex>"></script>` for `.js` (and the existing `_css_link` refactored to share the digest helper). Consumed by pages.py for all four script tags.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_ui.py`)

```python
def test_script_tags_carry_content_hash():
    # B14 residual (spec S1.6): JS gets the same ?v= content-hash the CSS got
    # in c58a325 — a behaviour change must never serve from a stale cache.
    page = _pages()["at-a-glance"]
    for name in ("echarts.common.min.js", "foi-charts.js"):
        assert re.search(rf'src="/assets/{re.escape(name)}\?v=[0-9a-f]{{12}}"', page), \
            f"{name} script tag is unversioned"

def test_type_dropdown_has_no_total_option():
    # B3 (decision 2026-08-25): 'All types' already yields total-basis figures;
    # a separate 'total' option reads as duplication.
    page = _pages()["requests-received"]
    assert '<option value="total">' not in page
    assert '<option value="">All types</option>' in page

def test_how_to_use_does_not_claim_filters_are_pending():
    page = _pages()["how-to-use"]
    assert "the filters become live in the interactive build" not in page
    assert "live on the chart pages" in page

def test_filters_blob_exposes_portfolios():
    # spec S1.1: the platform-derived filter options include the portfolio
    # dimension (the dropdown itself ships with the Stage-2 engine).
    page = _pages()["requests-received"]
    m = re.search(r"window\.__pageData = (.*?);</script>", page, re.S)
    assert m, "no __pageData blob"
    blob = json.loads(m.group(1).replace("<\\/", "</").replace("\\u002d\\u002d", "--"))
    portfolios = blob["filters"].get("portfolios")
    assert portfolios and len(portfolios) >= 10, portfolios
    assert all(p for p in portfolios)
```

(`re` is already imported at the top of test_ui.py; add `import json` beside it if not present.)

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_ui.py -k "script_tags or total_option or how_to_use" -v` (300s timeout)
Expected: FAIL (3/3).

- [ ] **Step 3: Implement**

`src/site/templates.py` — refactor lines 53-58 into a shared digest + two emitters:

```python
def _asset_digest(name: str) -> str:
    return hashlib.sha256((_ASSETS / name).read_bytes()).hexdigest()[:12]


def _css_link(rel: str, name: str) -> str:
    """A versioned stylesheet link: a ?v= content-hash suffix so a CSS change
    changes the URL and any browser holding the pre-fix cached sheet re-fetches
    (the site serves stylesheets with Cache-Control: public, max-age=14400)."""
    return f'<link rel="{rel}" href="/assets/{name}?v={_asset_digest(name)}">'


def _asset_link(name: str) -> str:
    """A versioned script tag — same content-hash contract as _css_link, so a
    JS behaviour change can never outlive a deploy in a browser cache."""
    return f'<script src="/assets/{name}?v={_asset_digest(name)}"></script>'
```

`src/site/pages.py`:
1. Import: extend line 20 to `from site.templates import chrome, _asset_link`.
2. Replace `_CHART_SCRIPTS` (lines 26-27):

```python
# script tags every chart page loads, rendered before </body> by chrome()
_CHART_SCRIPTS = (_asset_link("echarts.common.min.js") + "\n"
                  + _asset_link("foi-charts.js"))
```

3. Line 649: `scripts=_asset_link("chat.js")`; line 668: `scripts=_asset_link("report.js")`.
4. Type options (lines 154-157) become:

```python
    # personal/other are the drill-down buckets; the platform's total-basis
    # figures are what "All types" (no filter) already shows, so a separate
    # "total" option would duplicate it (B3, decision 2026-08-25).
    type_opts = [t for t in ("personal", "other") if t in types]
```

5. How-to-use Filters paragraph (lines 492-495) becomes:

```python
    <h2>Filters</h2>
    <p>The filters row (agency &middot; type (personal/other) &middot; FY) is
    live on the chart pages: selections re-derive the charts from the
    platform's own published facts. Where a selection has no published
    aggregate, the page says so instead of inventing one.</p>
```

6. `_filters_blob` (lines 108-116) gains the portfolio dimension (spec S1.1 —
   the data ships now; the dropdown itself is Stage-2 engine work):

```python
    return {
        "agencies": sorted({f["agency_name"] for f in frame.facts}),
        "types": sorted({f["bucket"] for f in frame.facts}),
        "fys": sorted({f["fy"] for f in frame.facts}),
        "portfolios": sorted({f["portfolio"] for f in frame.facts if f["portfolio"]}),
    }
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_ui.py -v` (300s timeout)
Expected: ALL pass, including the pre-existing `test_stylesheet_links_carry_content_hash`.

- [ ] **Step 5: Commit**

```bash
git add src/site/templates.py src/site/pages.py tests/test_ui.py
git commit -m "fix(site): version JS assets, drop duplicate total option, correct filters copy"
```

---

### Task 9: Housekeeping — probe, README, handover doc, gitignore, scratch

**Files:**
- Modify: `scripts/deploy.py` (_DB_PROBE at 60-74, --check consumer at 132-134)
- Modify: `README.md` (4 × `foi.fartkraft.ai`)
- Modify: `docs/memories/2026-08-25-bluebird-foi-poc-handover.md` (dataset filename + IPv4 note)
- Modify: `.gitignore`
- Delete: `background/` (directory), `main.py` (repo root) — both never tracked, verified scratch
- Commit (previously untracked): `docs/superpowers/plans/2026-08-23-foi-chat-reporting.md`
- Test: `tests/test_housekeeping.py` (new)

- [ ] **Step 1: Write the failing tests** (new file `tests/test_housekeeping.py`)

```python
"""Stage-1 housekeeping contracts (spec S1.7)."""
from pathlib import Path


def test_deploy_probe_checks_the_five_pilot_accounts():
    src = Path("scripts/deploy.py").read_text(encoding="utf-8")
    for name in ("pilot01.user", "pilot02.user", "pilot03.user",
                 "pilot04.user", "pilot05.user"):
        assert name in src, f"probe missing {name}"
    for old in ("foi.public", "foi.pilot", "foi.internal", "foi.officer"):
        assert old not in src, f"probe still references retired account {old}"
    assert "/5" in src and '"5"' in src, "probe denominator still /4"


def test_readme_advertises_the_live_hostname():
    src = Path("README.md").read_text(encoding="utf-8")
    assert "foi.fartkraft.ai" not in src
    assert "foi.axoquant.com" in src


def test_gitignore_covers_memories():
    src = Path(".gitignore").read_text(encoding="utf-8")
    assert "docs/memories/" in src


def test_scratch_files_are_gone():
    assert not Path("background").exists()
    assert not Path("main.py").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_housekeeping.py -v`
Expected: FAIL (4/4).

- [ ] **Step 3: Implement**

`scripts/deploy.py` — in `_DB_PROBE` (lines 68-70), the account query becomes:

```python
    '    cur.execute("SELECT count(*) FROM horizon.foi_chat_users "\n'
    '                "WHERE username IN (%s,%s,%s,%s,%s)",\n'
    '                ("pilot01.user", "pilot02.user", "pilot03.user", "pilot04.user", "pilot05.user"))\n'
```

and the consumer (lines 132-134) becomes:

```python
            f"if [ \"$n\" = \"5\" ]; then echo 'pilot accounts: seeded (5/5)'; else "
            f"echo 'pilot accounts: MISSING ('${{n:-none}}'/5; run "
            f"scripts/reset_pilot_users.py)'; fi"
```

(Note the remedy also changes: `reset_pilot_users.py`, which prints fresh passwords — `seed_pilot_users.py` alone cannot fix a partial state.)

`README.md`: replace every `foi.fartkraft.ai` with `foi.axoquant.com` (4 occurrences; verify with `grep -c "foi.fartkraft.ai" README.md` → 0 after).

`docs/memories/2026-08-25-bluebird-foi-poc-handover.md`: in the Open/pending data.gov.au bullet, change the filename to `agency-foi-data-2025-26-q1-to-q3-as-at-18-may-2026.xlsx` and replace the "unreachable from this network" sub-bullet with: "data.gov.au is reachable from this network only over IPv4 (`curl -4`); the CKAN API moved under `https://data.gov.au/data/api/3/...`. Confirmed live 2026-08-25."

`.gitignore` — append:

```
# session handover notes may carry throwaway credentials; never bulk-added
docs/memories/
```

Delete scratch (both verified never-tracked on 2026-08-25; `git log --all -- background/ main.py` is empty):

```bash
rm -rf background/ main.py
```

- [ ] **Step 4: Run the tests**

Run: `python -m pytest tests/test_housekeeping.py -v`
Expected: PASS (4/4).

- [ ] **Step 5: Commit (including the orphaned plan file)**

```bash
git add scripts/deploy.py README.md .gitignore tests/test_housekeeping.py docs/superpowers/plans/2026-08-23-foi-chat-reporting.md
git commit -m "chore: probe pilot01-05, live hostname in README, gitignore memories, adopt orphaned plan"
```

(`docs/memories/` is now gitignored so the handover-doc edit stays local by design — do not force-add it.)

---

### Task 10: Full-suite verification

**Files:** none modified.

- [ ] **Step 1: Run the complete test suite**

Run: `python -m pytest tests/ -v` with a 600s timeout (collection ingests 7 xlsx).
Expected: ALL tests pass. Any failure is a Stage-1 regression — fix it in the task that owns the file (return to that task's fix loop), never by weakening a test.

- [ ] **Step 2: Golden-gate boot check**

Run: `python -c "import sys; sys.path.insert(0, 'src')" && python -m pytest tests/test_server.py -v` (300s timeout) — the boot/golden-gate tests must pass with the enriched facts.

- [ ] **Step 3: No commit** (nothing changed); report suite results in the task report.
