# FOI Stage 3a — Provenance Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the platform's provenance actually true per-figure, then build the data provenance library on top of it (spec S3.5): a curated OKF-style registry, a live lineage layer, and three surfaces — the gated chat, a read-only API, and a public page. A reviewer asks "where did this data come from?" and gets the dataset, the files, the hashes, the curation decisions, and — for a named figure — the row basis behind it.

**Architecture:** `stats/catalog.py` already derives every figure from a declarative `FIGURE_SPECS` entry. Task 1 uses that same spec to derive each figure's *source rows*, replacing the whole-frame hash that currently makes all 13 figure keys indistinguishable. `src/provenance.py` then parses a curated markdown registry at boot (fail-loud, like the golden gate) and composes it with live dataset/figure facts into one payload that the DSL op, the API route and the public page all render.

**Tech Stack:** Python 3.13, FastAPI/Starlette, psycopg2, pytest. No new dependencies.

## Global Constraints

- **`foi_stats`'s result contract is unchanged**: `{value, basis, source_rows, rows_hash}` for every key. Task 1 changes the VALUES of `source_rows`/`rows_hash` for the 13 figure keys, never the shape.
- **`hash_rows` and `_FACT_KEYS` are untouched.** The `portfolio` exclusion in `_FACT_KEYS` is load-bearing: it is what lets a hash survive a DB round-trip, because `load_facts` reads `portfolio` but pre-Stage-1 datasets stored `''`. Fix comments, never that code.
- **Replay drift is expected and accepted, once.** Changing a figure's hash basis means stored `lineage_ops.rows_hash` values for those keys stop matching. `replay_verify` fails CLOSED (returns False, never crashes), so old rows report unverified until re-recorded. This is the same trade accepted for the movers keys in Stage 2 and for `timeliness_slippage_corr`. Do not treat it as a regression; DO state it in the report.
- **Golden gate keeps passing** (boot integrity vs `GOLDEN_Q1_FIGURES`).
- **Provenance must fail loud.** A missing or malformed registry file is a boot failure, not a degraded page. Stale provenance is worse than none — that is the whole premise.
- **Never invent provenance.** Every value in a provenance answer is either curated text a human wrote, or a measured fact from the frame/dataset. No model-generated claims about sources.
- **`site` module name collision:** never `python -c "import site.x"`. Use `sys.path.insert(0, "src")` scratch scripts.
- **TEST EXECUTION:** this harness caps a FOREGROUND command at 600s; `test_ui`/`test_pages`/the full suite take 11–21 minutes. Run them as tracked BACKGROUND tasks and report exit codes. NEVER pipe pytest — a pipe swallows the exit code. pytest's "N passed" line does not survive redirection here; the exit code plus progress dots are the evidence. Do not run a gate while another agent is writing to the tree (gate runs read assets from the working tree; a concurrent save produces convincing false reds).
- **Commit after every task.** No deploy until the stage-boundary review.

## File Structure

- `src/stats/catalog.py` — `_figure_source_rows` + the FIG_KEYS hash branch (Task 1); registry-facing helpers (Task 3)
- `data/corpus/provenance/{sources,derivations,decisions}.md` — the curated registry (Task 3, new)
- `src/provenance.py` — registry parser + live-layer composer, boot-validated (Task 3, new)
- `src/stats/dsl.py` — the `provenance` op (Task 4)
- `src/agentic/report.py` — provenance intent routing (Task 4)
- `src/server/app.py` — `/api/provenance` + boot validation call (Task 5)
- `src/site/pages.py`, `src/site/templates.py` — the public page + its nav entry (Task 5)
- Carry-over fixes from Stage 2 (Task 2): `src/site/pages.py`, `src/site/assets/foi-charts.js`, `src/stats/dsl.py`
- Tests: `tests/test_catalog.py`, `tests/test_figure_specs.py`, `tests/test_provenance.py` (new), `tests/test_ui.py`, `tests/test_api.py`, `tests/test_dsl.py`

---

### Task 1: Per-figure source rows

**Files:**
- Modify: `src/stats/catalog.py` (add `_figure_source_rows`; the `if key in FIG_KEYS` branch at ~line 526)
- Test: `tests/test_figure_specs.py`

**Interfaces:**
- Produces: `catalog._figure_source_rows(frame, key) -> list[dict]` — the exact rows a figure's spec consumes. The 13 FIG_KEYS now return distinct, meaningful `source_rows`/`rows_hash`.
- Consumes: `FIGURE_SPECS` (Stage 2), `is_reporting_agency` (Stage 2).

The defect: `catalog.py:526-529` sets `rows = frame.facts` for EVERY figure key, so all 13 return the identical hash. Measured before this task: 1 distinct `rows_hash` across 13 keys. `replay_verify` cannot tell `requests_received_trend` from `decided_top20`, and any unrelated measure changing false-alarms all thirteen. `_movers_source_rows` (same file) already solves this shape for the movers keys — mirror it.

- [ ] **Step 1: Discovery — pin the current state**

Scratch script (session scratchpad, not committed):

```python
import sys; sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from storage.frame import Frame
from stats.catalog import FIG_KEYS, foi_stats
frame = Frame(normalise_all())
seen = {}
for k in FIG_KEYS:
    s = foi_stats(frame, k)
    seen.setdefault(s["rows_hash"], []).append(k)
    print(f"{k:35s} rows={s['source_rows']:6d} hash={s['rows_hash'][:12]}")
print("distinct hashes:", len(seen))
```

Record the output — "distinct hashes: 1" is the defect. You will assert the fixed counts in Step 2.

- [ ] **Step 2: Write the failing tests** (append to `tests/test_figure_specs.py`)

```python
def test_every_figure_hashes_only_the_rows_its_spec_consumes():
    # The whole-frame hash made all 13 figure keys indistinguishable: replay
    # could not tell requests_received_trend from decided_top20, and an
    # unrelated measure changing false-alarmed every one of them.
    frame = Frame(normalise_all())
    total = len(frame.facts)
    hashes = {}
    for key in FIG_KEYS:
        stat = foi_stats(frame, key)
        assert 0 < stat["source_rows"] < total, \
            f"{key}: source_rows {stat['source_rows']} is not a real subset of {total}"
        hashes.setdefault(stat["rows_hash"], []).append(key)
    # figures that consume genuinely different rows must hash differently
    collisions = {h: ks for h, ks in hashes.items() if len(ks) > 1}
    for h, keys in collisions.items():
        measures = {frozenset(_spec_measures_of(k)) for k in keys}
        assert len(measures) == 1, \
            f"keys with different measures share hash {h[:12]}: {keys}"


def _spec_measures_of(key):
    spec = FIGURE_SPECS[key]
    out = set(spec.get("measures", [])) | set(spec.get("numerators", []))
    if spec.get("denominator"):
        out.add(spec["denominator"])
    if spec.get("measure"):
        out.add(spec["measure"])
    return out


def test_figure_source_rows_are_annual_reporting_rows():
    # same discipline as _movers_source_rows: annual rows only (no golden
    # single-quarter rows), real reporting agencies only
    from stats.catalog import _figure_source_rows
    frame = Frame(normalise_all())
    for key in FIG_KEYS:
        for f in _figure_source_rows(frame, key):
            assert f["quarter"] is None, f"{key} hashes a quarter-carrying row"
            assert is_reporting_agency(f["agency_name"]), \
                f"{key} hashes a non-reporting agency: {f['agency_name']}"
```

Add `FIGURE_SPECS`, `_figure_source_rows` and `is_reporting_agency` to the file's imports.

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest tests/test_figure_specs.py -k "hashes_only or source_rows_are_annual" -v` (300s)
Expected: the first FAILS (13 keys share one whole-frame hash and `source_rows == total`); the second fails on import (`_figure_source_rows` does not exist).

- [ ] **Step 4: Implement.** Add next to `_movers_source_rows`:

```python
def _figure_source_rows(frame, key) -> list[dict]:
    """The exact fact rows a figure's spec consumes — the hash basis for that
    figure, mirroring _movers_source_rows.

    Every figure key used to hash `frame.facts` wholesale, so all 13 returned
    the IDENTICAL rows_hash: replay_verify could not distinguish
    requests_received_trend from decided_top20, and an unrelated measure
    changing false-alarmed all thirteen. The spec already declares exactly
    which measures a figure reads, so the basis derives from it.

    Discipline matches _movers_source_rows: annual rows only (the explicit
    `quarter is None` test, because Frame.filter(quarter=None) means "no
    quarter constraint"), bucket="total" (every spec's server derivation reads
    the total bucket), real reporting agencies only. A top_n additionally
    narrows to its ranking year.
    """
    spec = FIGURE_SPECS.get(key)
    if spec is None:
        return []
    measures = set(spec.get("measures", [])) | set(spec.get("numerators", []))
    if spec.get("denominator"):
        measures.add(spec["denominator"])
    if spec.get("measure"):
        measures.add(spec["measure"])
    rows = [f for f in frame.facts
            if f["quarter"] is None
            and f["bucket"] == "total"
            and f["measure"] in measures
            and is_reporting_agency(f["agency_name"])]
    if spec["kind"] == "top_n":
        rows = [f for f in rows if f["fy"] == spec["default_fy"]]
    return rows
```

Then replace the FIG_KEYS branch (`catalog.py:526-529`):

```python
    if key in FIG_KEYS:
        rows = _figure_source_rows(frame, key)
        return {"value": _figure(frame, key), "basis": "fy", "source_rows": len(rows),
                "rows_hash": hash_rows(rows)}
```

- [ ] **Step 5: Verify the fix measurably.** Re-run the Step 1 discovery script. Expected: `distinct hashes` is now well above 1, `source_rows` differs per figure, and the trend twins that genuinely read the same measure (e.g. `received_top20` vs `agency_contributions_received`) may legitimately still collide — the test allows exactly that case. Record the before/after table in your report.

- [ ] **Step 6: Run the tests**

Run: `python -m pytest tests/test_figure_specs.py tests/test_catalog.py tests/test_dsl.py -v` (600s, background task, report exit code)
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add src/stats/catalog.py tests/test_figure_specs.py
git commit -m "fix(stats): hash each figure's own source rows, not the whole frame"
```

---

### Task 2: Stage 2 carry-over sweep

**Files:**
- Modify: `src/site/pages.py`, `src/site/assets/foi-charts.js`, `src/stats/dsl.py`
- Test: `tests/test_ui.py`, `tests/test_dsl.py`

Six items carried from Stage 2's deploy caveats and routed follow-ups. All small; none changes a number a user reads except item C, which stops a note from misdescribing a chart.

- [ ] **Step 1: The items**

**A. `_WORKBOOK_SOURCE` does not follow `LATEST_COMPLETE_FY`.** `src/site/pages.py:42` hardcodes `"FY2019-20 – FY2025-26 (Q1–Q3 cumulative)"`. Correct today; wrong the year the constant advances (all eleven FY cards would keep calling the newest year cumulative and freeze the range endpoint). Derive it: the range start is the earliest annual FY in the frame, the end is the latest, and the "(Q1–Q3 cumulative)" qualifier applies only when the latest FY is a partial year (the `partial_fys` helper added in Stage 2 already answers that).

**B. The chart engine's header contract misdescribes its own exception.** `src/site/assets/foi-charts.js:24-25` says the part-year exception "auto-scales"; the code pins to the selection's own maximum, and the paragraph three lines above explains that auto-scaling was rejected precisely because ECharts picks a rounded top. One-word fix — but it is the contract the next reviewer reads.

**C. The part-year note is count-shaped and fires on ratio figures.** On `timeliness_change` / `granted_full_part_change` at a partial FY, the note says "These are part-year totals and are not comparable with a full-year figure" about a *rate* (71.1%), and warns that a part year "reads as a fall in FOI activity" — a mechanism that does not apply to a rate at all. Additionally, in 45 measured portfolio/type combinations the note claims the axis was rescaled *down* when it actually GREW. Fix: vary the wording by spec kind (a ratio's caveat is that the period is shorter and the denominator smaller, not that the total is partial), and only claim a rescale-down when the axis actually shrank.

**D. Lone-point trends lose their emphasis.** `figureOption` boosts `symbolSize` only when `cats.length === 1`, but since Stage 2's I2 fix the axis always carries every published FY, so a one-year agency draws a single default 4px dot with no connecting line and no note. 61 of 433 agencies are in this class. Fix: gate the emphasis on the non-null value count, and emit a note when a selection publishes fewer than two years.

**E. `.fignote:empty { display: none }` + `aria-live` is the classic skipped-live-region case.** A region hidden at mutation time is what screen readers most often miss, and the empty→text transition is exactly the first-filter case. Fix: use `visibility`/clip instead of `display:none`, or keep a non-breaking space.

**F. The `dsl.py` per-agency ops are inconsistent.** Only `list_agencies` applies both halves of the reporting-agency predicate; five ops apply only the "total" half. Measured impact today: 0 rows. It is a strict tightening (drops rows, never adds), so it cannot invent a figure. Align all six and add a synthetic-row test proving the x-prefixed exclusion works, since the real frame has none.

- [ ] **Step 2: Write tests first** where the item is server-testable (A, C, F). B/D/E are JS/CSS — hand-trace them and say so in the report.

For A:

```python
def test_workbook_source_follows_the_latest_complete_fy():
    # the caption must not freeze a year: it is derived from the frame
    import re
    from site import pages
    src = Path("src/site/pages.py").read_text(encoding="utf-8")
    assert not re.search(r'FY2019-20\s*[–-]\s*FY2025-26', src), \
        "the workbook caption hardcodes an FY range"
```

For F, a synthetic frame with an `x`-prefixed agency asserting each of the six ops excludes it.

- [ ] **Step 3: Implement A–F.**
- [ ] **Step 4:** Run `tests/test_ui.py tests/test_dsl.py tests/test_pages.py` (background, report exit codes); `node --check` on the JS.
- [ ] **Step 5: Commit**

```bash
git commit -m "fix(site): derive the workbook caption, honest part-year prose, aligned agency predicate"
```

---

### Task 3: The provenance registry and its parser

**Files:**
- Create: `data/corpus/provenance/sources.md`, `derivations.md`, `decisions.md`
- Create: `src/provenance.py`
- Test: `tests/test_provenance.py` (new)

**Interfaces:**
- Produces:
  - `provenance.load_registry() -> dict` — parsed curated registry. Raises `ProvenanceError` on a missing or malformed file.
  - `provenance.validate_registry(frame) -> None` — cross-checks the registry against reality; raises on drift. Called at boot.
  - `provenance.describe(frame, dataset=None, key=None) -> dict` — the layered payload: registry always, plus the live layer when `key` names a figure/stat.
- Consumes: `catalog.foi_stats`, `catalog._figure_source_rows`, `config.OAIC_DATASET_ID`, the frame.

The registry is CURATED PROSE plus machine-checkable facts. Humans write it; the parser validates it; nothing is generated.

- [ ] **Step 1: Write the registry files.**

`data/corpus/provenance/sources.md` — one `## ` section per source, each with a fenced `yaml`-ish key block the parser reads (`id`, `title`, `url`, `sha256`, `covers`, `ingested_as`) followed by free prose. Cover: the data.gov.au dataset page, each of the seven ingested workbooks (with the content hash the ingest computes today — MEASURE these, do not invent them), and the OAIC published dashboard behind the transcribed golden Q1 figures.

`derivations.md` — one section per sheet actually read (`Request numbers`, `Action on requests`, `Response times`), naming the columns each measure comes from, the P/O/T bucket convention, how portfolio is captured from banner rows, and the normaliser version.

`decisions.md` — one section per curation decision, each with `id`, `date`, `decision`, and prose: the courts-merger distinct-by-design ruling, the most-recent-name rename policy, the trend-window decision, applicant-vs-total basis (34,418 vs 34,810), the golden Q1 transcription, and the post-2018-19 quarterly gap.

Every factual claim must be one you can verify against the repo or the frame today.

- [ ] **Step 2: Write the failing tests** (`tests/test_provenance.py`)

```python
"""The provenance registry is a load-bearing document: a missing or drifted
entry must fail boot, not degrade a page (spec S3.5)."""
import pytest

from ingest.normalise import normalise_all
from storage.frame import Frame
import provenance


def test_registry_loads_and_covers_every_ingested_workbook():
    reg = provenance.load_registry()
    ingested = {s["id"] for s in reg["sources"] if s.get("ingested_as")}
    # every workbook the normaliser reads must be registered
    assert len(ingested) >= 7, ingested


def test_registry_hashes_match_the_files_on_disk():
    # a registry that claims a hash it cannot reproduce is worse than none
    provenance.validate_registry(Frame(normalise_all()))


def test_missing_registry_file_fails_loud(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", tmp_path)
    with pytest.raises(provenance.ProvenanceError):
        provenance.load_registry()


def test_describe_without_a_key_returns_registry_only():
    out = provenance.describe(Frame(normalise_all()))
    assert out["sources"] and out["decisions"] and out["derivations"]
    assert "figure" not in out


def test_describe_with_a_figure_key_adds_the_live_layer():
    frame = Frame(normalise_all())
    out = provenance.describe(frame, key="requests_received_trend")
    fig = out["figure"]
    assert fig["key"] == "requests_received_trend"
    assert fig["source_rows"] > 0
    assert len(fig["rows_hash"]) == 64
    # the live layer must agree with the catalog, not restate the registry
    from stats.catalog import foi_stats
    assert fig["rows_hash"] == foi_stats(frame, "requests_received_trend")["rows_hash"]


def test_describe_rejects_an_unknown_key():
    with pytest.raises(KeyError):
        provenance.describe(Frame(normalise_all()), key="not_a_real_key")
```

- [ ] **Step 3: Run to verify failure** — the module does not exist.

- [ ] **Step 4: Implement `src/provenance.py`.** A `ProvenanceError(RuntimeError)`; `_REGISTRY_DIR` pointing at the corpus dir; a small deterministic parser (sections by `## `, key blocks by fenced code, prose as the remainder — no YAML dependency); `load_registry()` raising on missing/malformed; `validate_registry(frame)` re-computing each workbook's sha256 and comparing, and asserting every FY the frame carries is `covers`-ed by some source; `describe(frame, dataset=None, key=None)` returning `{"sources", "derivations", "decisions", "dataset"?, "figure"?}`.

- [ ] **Step 5: Wire boot validation** — call `validate_registry(frame)` from `_boot()` in `src/server/app.py`, AFTER the golden gate, so a provenance drift refuses to serve. (This is the one app.py change in this task; the API route is Task 5.)

- [ ] **Step 6:** Run `tests/test_provenance.py tests/test_server.py` (background, exit codes).
- [ ] **Step 7: Commit**

```bash
git add data/corpus/provenance src/provenance.py src/server/app.py tests/test_provenance.py
git commit -m "feat(provenance): curated registry, boot-validated, with a live figure layer"
```

---

### Task 4: The `provenance` DSL op and chat routing

**Files:**
- Modify: `src/stats/dsl.py`, `src/agentic/report.py`
- Test: `tests/test_dsl.py`, `tests/test_chat_report.py`

**Interfaces:**
- Produces: `query_dataset(frame, "provenance", {"key": ...})` returning `provenance.describe(...)`; the op name appears in the unknown-op allowed list. Chat/report routing recognises provenance intent.

- [ ] **Step 1: Write the failing tests.** Include a REGRESSION test that the scope-refusal behaviour still holds — asking something outside the data must still refuse, not fall through to provenance.

```python
def test_provenance_op_returns_the_registry():
    out = query_dataset(Frame(normalise_all()), "provenance", {})
    assert out["sources"] and out["decisions"]

def test_provenance_op_with_a_key_adds_the_figure_layer():
    out = query_dataset(Frame(normalise_all()), "provenance",
                        {"key": "received_top20"})
    assert out["figure"]["key"] == "received_top20"

def test_provenance_op_unknown_key_errors_not_raises():
    out = query_dataset(Frame(normalise_all()), "provenance", {"key": "nope"})
    assert "error" in out  # the op returns an error dict; it must not 500

def test_unknown_op_message_lists_provenance():
    out = query_dataset(Frame(normalise_all()), "definitely_not_an_op", {})
    assert "provenance" in out["error"]
```

- [ ] **Step 2:** Verify failure.
- [ ] **Step 3: Implement.** The op catches `KeyError` from `describe` and returns `{"error": ...}` (consistent with the file's other ops). Add `provenance` to the allowed-ops string. In `report.py`, add a routing pattern for provenance intent (`where.*(from|come)|provenance|source of|lineage`) that returns the provenance block rather than a stat — placed BEFORE the generic patterns so it is not swallowed by `received`/`decided`.
- [ ] **Step 4:** Run `tests/test_dsl.py tests/test_chat_report.py tests/test_dsl_portfolio.py` (background, exit codes).
- [ ] **Step 5: Commit** `feat(dsl): provenance op + chat routing for "where did this come from"`

---

### Task 5: `/api/provenance` and the public page

**Files:**
- Modify: `src/server/app.py`, `src/site/pages.py`, `src/site/templates.py`
- Test: `tests/test_api.py`, `tests/test_ui.py`

- [ ] **Step 1: Write the failing tests.** The API route returns 200 with the registry and is rate-limited like its siblings; `provenance.html` renders in the Reference nav group, lists every source with its URL and hash, lists the decisions, and links each dashboard's lineage page.
- [ ] **Step 2:** Verify failure.
- [ ] **Step 3: Implement.** `GET /api/provenance` mirroring `/api/figures`'s throttle+shape. `_page_provenance(frame)` rendering the registry (escaped), added to `PAGE_FIGURE_KEYS` with `[]`, to `render_all_pages`, and to `SIDENAV_GROUPS`' Reference group. Update `/api/` index to list the new endpoint.
- [ ] **Step 4:** Run `tests/test_api.py tests/test_ui.py tests/test_pages.py tests/test_server.py` (background, exit codes).
- [ ] **Step 5: Commit** `feat(site): public provenance page + read-only /api/provenance`

---

### Task 6: Full-suite gate

**Files:** none modified.

- [ ] **Step 1:** `python -m pytest tests/ -q` as a tracked BACKGROUND task, UNPIPED, 1200s. Report the exit code and the dot count. Any failure: report precisely and STOP; the owning task's fix loop handles it.
- [ ] **Step 2:** Confirm the boot path with no DB and with a cold DB still works (`tests/test_server.py` covers the no-DB case; state which tests exercise it).
- [ ] **Step 3:** Re-run the Task 1 discovery script and put the final per-figure `source_rows`/`rows_hash` table in the report — it is the evidence that the provenance the library now publishes is real.
- [ ] **Step 4:** No commit. Report.
