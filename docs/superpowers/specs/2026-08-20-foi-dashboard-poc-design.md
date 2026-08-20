# Design — OAIC FOI statistics dashboard POC

**Date:** 2026-08-20
**Status:** Agreed design (awaiting implementation plan)
**Owner:** Alex

## 1. Purpose

A proof of concept that replaces the OAIC "Australian Government FOI statistics"
page plus its embedded Power BI report with a dashboard built on the horizon
platform. The POC:

- looks like the OAIC site (template taken from oaic.gov.au);
- replicates all 12 Power BI report pages;
- provides full agentic analysis and reporting (Approach C) — a natural-language
  dashboard/report builder wired in;
- records lineage for everything: data sourced, calculations applied, outcomes,
  and every dashboard-builder request;
- runs as a hosted no-auth demo URL.

## 2. Architecture (in one paragraph)

The normalising ingest resolves every data quirk once (MoG renames, `x`-prefixed
note rows, Total rows that do not re-sum, and the Q1–Q3-cumulative vs
single-quarter discrepancy) into canonical long-form facts. Those land in the
existing `horizon` Postgres as the durable source of truth (`foi_datasets`
snapshot pin + immutable `foi_facts`), and load into an in-memory frame at
startup for the agent path. The agent never touches SQL — it drives an
enum-constrained DSL (horizon's "model composes, platform computes" contract,
seeded by the dormant `dash_builder.py` tools), where every figure carries an
explicit `basis` field. Lineage is hybrid: a JSONL firehose for the raw
builder-request + tool-call event stream, and Postgres tables for the queryable
artifact→op→facts chain, with a lean `/lineage/{artifact_id}` viewer. The 12
Power BI pages are static file-based so they render even if every service behind
the chat path is down. Deploy is the existing horizon pattern: idc-1 +
Cloudflare tunnel + Worker, no auth.

### The question that started this: pgvector? Postgres?

**No vector store of any kind.** The FOI data is a categorical fact table
(agency × quarter × measure × bucket). Questions against it are exact-keyed
aggregations. Vector search returns the *adjacent row*, not the exact fact —
embed the rows and "requests received, Dept of Social Services, Q1" can pull the
Dept of Human Services (MoG predecessor) row or the wrong quarter. A
wrong-but-traceable number is the worst outcome for a government dashboard
because the provenance machinery vouches for it. The one job vectors might do
(bridging natural language → stat catalog) is already solved structurally by
horizon's enum-constrained spec schema.

Verified in the horizon code: nothing in the chat/report/dashboard path reads a
vector store today. Qdrant is write-side only (news/parliament ingest). So there
is no existing vector infra to reuse; it would be net-new machinery for a number
path that must not exist.

**Postgres wins — but for lineage, not data volume.** The dataset is ~2,800
rows, under 1 MB in memory. Postgres wins because lineage is the product: "every
number on this page traces to a logged query against a named dataset snapshot" is
the sentence an OAIC evaluator wants to hear. Lineage is a relational join
problem (artifact → op → facts → snapshot), and the `horizon` Postgres already
exists with an idempotent `migrate.sql` run on every app start — the lineage
tables are ~60 additive lines, zero migration risk.

### What the design explicitly rejects

- **Raw SQL for the agent.** A `SUM` over the cumulative column returns 34,418
  when the page shows single-quarter 12,359. The data quirks fail precisely under
  free SQL. The extension path is "add an op", not "give the agent SQL".
- **Vector embeddings of the stats.** Covered above; they answer this class worse.
- **YAGNI deferral of the Postgres lineage spine.** Postgres already exists; the
  lineage tables ship in v1.

## 3. Data layer

### 3.1 Sources

| Source | What it is | Use in the POC |
|---|---|---|
| `agency-foi-data-2025-26-q1-to-q3.xlsx` (as at 18 May 2026) | 6 sheets: Request numbers, Action on requests, Response times, Requests top 20, Determined top 20, Index | Single-quarter Q1 2025-26 headline (via derived differencing); Q1–Q3 cumulative series |
| Annual xlsx 2019-20 → 2024-25 | 21 sheets (Request numbers, Action, Response times, Charges, Internal review, Section 48, Exemptions, Disclosure Log…) | FY totals for the 5-year trend; agency-level top contributors |
| `foi-requests-costs-and-charges-1982-2024.csv` | Long-run FY requests/costs/charges | Long-run trend 1982-2024 |
| `foi-quarterly-returns-data-2015-16` → `2018-19` CSVs | Per-quarter data, pre-2019 | Historic quarterly depth (deferred) |

Dataset id on data.gov.au: `b0771c28-09cc-4c4e-9e61-9a96f6e3d040`.

Snapshot pinning: every ingested file is recorded with `{path, url, sha256, size,
downloaded_at}` in the `foi_datasets` row, and the as-at-18-May-2026 snapshot is
baked into the deploy — never a live fetch on demo day.

### 3.2 The trend-window decision (recorded)

The Power BI report shows a single selected quarter (Q1 2025-26) with a trend
axis that actually displays Oct-2023 → Sep-2025 (8 quarters ≈ 2 financial years),
not the "5 years" the OAIC page text claims. The current data.gov.au file is Q1–Q3
cumulative (34,418 received). Per-quarter files exist only through 2018-19;
annual xlsx files for 2019-20 → 2024-25 are FY-totals only.

Decision (Alex, 2026-08-20): **FY 5-year trend plus single-quarter Q1 headline.**

- Single-quarter Q1 2025-26 headline figures (requests received 12,359; finalised
  11,549; decided 7,344; within statutory 5,167; granted full 1,426 / part 3,968 /
  refused 1,950; withdrawn 3,955), sourced from the published Power BI figures as
  ground truth.
- Financial-year 5-year trend (FY2019-20 → FY2024-25, plus FY2025-26 Q1–Q3
  cumulative) from the published annual files.
- No per-quarter reconstruction for years without published quarterly data —
  synthesising quarters the sources do not contain is a leakage/credibility risk.

Recorded in `docs/decisions/2026-08-20-trend-window.md`.

### 3.3 Normalisation (the quirks, resolved once in the ingest)

1. **Total rows** → flagged `is_total=1`, never re-summed. Verified: the sheet's
   own Total row (34,810) ≠ sum of agency rows (34,418) because of an extra
   transfer line — the Total row is a trusted value, not computed.
2. **`x`-prefixed note rows** (e.g. "x Norfolk Island (external territory)",
   "xx changes") → stripped, excluded from agency facts.
3. **MoG renames** → a curated rename map from the "Data notes and disclaimer"
   corpus, applied at ingest. `agency_name` is resolved once at ingest and stored
   verbatim per snapshot; old snapshots keep old names.
4. **Quarter basis** → `window_mode` is a schema-enforced field on every fact and
   lineage row: `single_quarter | cumulative | fy`. The renderer prints the basis
   beside every figure.
5. **Personal/Other/Total** → long-form `bucket` column.

### 3.4 Canonical facts

- `foi_datasets` — one row per snapshot: `period_label`, `window_mode`,
  `source_files JSONB`, `normaliser_ver`, `canonical_hash` (sha256 over canonical
  fact rows), `fact_count`, `superseded_by`, `created_at`.
- `foi_facts` — long-form immutable rows: `agency_key`, `agency_name`
  (as-resolved-at-ingest), `fy`, `quarter`, `measure_group`, `measure`, `bucket`,
  `value`, `derived` (true for single-quarter differenced values), `row_hash`,
  `UNIQUE(dataset_id, agency_key, fy, quarter, measure_group, measure, bucket)`.

At startup the canonical facts load into an in-memory frame (~2,800 rows,
microseconds), with a boot-time golden check: assert the published Q1 2025-26
figures (above) against the loaded frame, abort loudly on mismatch.

Refresh invariant: re-download → INSERT new `foi_datasets` + `foi_facts`, never
UPDATE. If `canonical_hash` matches the prior snapshot, refresh is a no-op
(m4's sha256-identity pattern). Old artifacts keep their old `dataset_id`, so
old lineage stays exact.

## 4. Agentic analysis and reporting

### 4.1 The "never invent a number" contract, generalised

Horizon's proven mechanism: the model supplies only structure; the platform
computes every figure. The spec JSON schema is enum-constrained so the model
cannot emit an invalid figure key. Generalised to FOI:

- `foi_stats(frame, key)` catalog — every stat the POC can cite, computed from
  canonical facts (mirrors `computed_stats`). E.g. `requests_received_q1` →
  12,359, `within_statutory_pct_q1`, `top_contributors_fy24`,
  `refusal_rate_change_fy23_fy24`.
- `build_spec_schema(d)` — enum-constrained JSON schema (mirrors
  `build_spec_schema`).
- DSL ops over the FOI facts — the generalised dormant `dash_builder.py`
  `query_dataset` tools: `list_agencies`, `filter_agencies`, `summarize_agencies`,
  `trend` (5-year window), `compare_period` (same-period-previous-year),
  `top_contributors`, `by_portfolio`, `kpis`, `gaps`, plus AST-safe `compute`.
- **Citation pointers, never digits** — the model's prose/summary/stats carry
  `{c:<job>.<turn>.<call>.<field>}` markers, resolved by the renderer against the
  persisted tool-call transcript. Unknown key → fail loud. The agent cannot write
  a number into the output.

### 4.2 The agentic builder loop

Wired from the dormant `dash_builder.py`, FOI-flavoured. The critical fix: the
orphaned module discards its tool-call messages list and persists nothing. The
lineage requirement closes that gap:

1. **Per-turn transcript capture** — after every tool call, append one JSONL
   `tool_call` line (tool, op, args, result digest, seq) and write the
   `lineage_tool_calls` row, before rendering the page.
2. **Guardrails** — `dash_builder.py`'s scope, jailbreak, tool-sandbox, identity
   guardrails carry over; the FOI op set is read-only and enum-shaped.
3. **Fix a latent bug** — `_safe_math` returns `0.0` on division by zero, which
   would silently mint a "0% refusal rate" for a zero-denominator agency. Make it
   raise/None so a wrong rate cannot be computed.

### 4.3 Acceptance tests

Four questions the DSL must answer, plus the 12 Power BI pages as the coverage
bar, before wiring:

1. "Which agencies increased their refusal rate most between FY23 and FY24?" →
   `compare_period` + `refusal_rate` op.
2. "Correlate timeliness slippage with request volume." → `correlate` op.
3. "Which portfolios drive the increase in decisions made within statutory
   time?" → `by_portfolio` op. Portfolio grouping is derived from a **bundled
   agency→portfolio map** (an extension of the MoG rename table in the ingest),
   not an external MoG-directory dependency.
4. "Why does Home Affairs have ~35% of requests, citing the notes?" → `notes()` +
   corpus grounding.

System prompt: Data notes + disclaimer text verbatim (the definitional authority
for renames, quarterly-vs-FY basis, personal-info definition), sheet-to-page
mapping, output contract. Tool schema: measure-family tag per op
(`requests / finalisations / decisions / timeliness`) to block cross-family
conflation.

### 4.4 Report building

Reuses horizon's `report_build.py` + `charts.py` (styled .docx with embedded
charts), with the same citation-pointer constraint on prose numbers — report
figures trace through the same lineage ledger.

## 5. Site and 12-page replication

### 5.1 Site chrome

The POC takes the OAIC site template — masthead/nav/footer structure from
oaic.gov.au (logo block, top nav with expandable sections, breadcrumb, "On this
page" anchor list, feedback widget, footer with Acknowledgment of Country). It is
a static-HTML implementation of that visual language using OAIC design tokens,
not a copy of their CSS/JS. Shared `site.css` + nav injection, matching horizon's
`site/` pattern.

### 5.2 The 12 pages (static file-based)

Every KPI, trend point, and share traces through the platform-computed catalog or
the DSL. Basis is printed beside every figure. Charts: ECharts (vendored) for
interactive trend/top-contributor views; self-contained SVG for static pages.

| # | Power BI page | POC page |
|---|---|---|
| 1 | FOI at a glance | KPI tiles: requests received (12,359, +72% YoY, +5% QoQ), finalised (11,549), decided (7,344; 5,167 within statutory = 70%), granted full/part/refused shares (1,426 / 3,968 / 1,950), withdrawn (3,955). Filters: portfolio, type, FY/quarter. |
| 2 | Requests received (trend + top contributors) | Trend line (FY-level), top-contributors bar (Home Affairs ~35%). |
| 3 | Key agency contributions to requests received | Top-5 + contribution-to-change waterfall. |
| 4 | Requests finalised (trend) | Trend + decided/transferred/withdrawn stack. |
| 5 | Requests decided (trend + top contributors) | Trend + top contributors by type. |
| 6 | Key agency contributions to requests decided | Top-5 + contribution-to-change waterfall. |
| 7 | Decision outcomes (outcomes of decisions, trend) | Outcomes by quarter + % refused trend. |
| 8 | Change in decision outcomes (granted in full or part) | Change breakdown, agencies up/down. |
| 9 | Timeliness of decision-making (trend, within/after) | Within/after trend + % within trend. |
| 10 | Change in timeliness | Change breakdown, agencies up/down. |
| 11 | Data notes and disclaimer | The full text, verbatim, as a static page (also in the BM25 corpus). |
| 12 | How to use | Static explanatory page. |

### 5.3 Navigation

Top nav mirrors OAIC: Privacy / Freedom of information / Consumer Data Right /
Digital ID / Engage with us / About the OAIC, with the FOI statistics page in the
FOI section — but linking to the POC pages. Plus a distinct "Ask" entry to the
agentic builder. Breadcrumb: *Freedom of information → Australian Government FOI
statistics*.

### 5.4 The "Ask" (agentic) page

Type a natural-language request → the agentic builder runs → the dashboard/report
is built + lineage recorded → get a link to view it and its lineage page. This is
the page that demonstrates the explainability requirement live.

## 6. Governance (chat scope and identity)

The chat and agentic builder are hard-scoped to this use case. A user cannot
steer them outside the FOI statistics domain. Governance is **defence-in-depth**
(mirroring horizon's `request_governor.rule_screen` + `_grounded_system`):
a deterministic regex screen **and** a prompt-level scope block, so a scope
violation is caught even if one layer is bypassed.

### 6.1 Deterministic scope screen (Layer 1)

A regex + token-match screen runs on every request **before** it reaches the
model (mirroring `request_governor.rule_screen`). It matches out-of-scope terms
and returns `{blocked: true, reason}` without invoking the model. Matched terms
include: other countries' FOI/freedom-of-information, immigration/visa/citizenship,
tax/benefit/policy advice, health/medical, defence/security operations, anything
about named individuals or agencies' internal conduct, and any attempt to use the
data for purposes beyond the published statistics. Blocked requests are logged to
lineage (`governor_block`) and refused cleanly. If the screen is unsure, it lets
the request through to the model-level scope block (fail-open for words, but the
prompt block below is strict).

### 6.2 Prompt-level scope block (Layer 2)

The scope block in the system prompt (mirroring horizon's `_grounded_system`) is
FOI-specific and strict:

- **Allowed:** questions about Australian Government FOI statistics — requests
  received/finalised/decided, decision outcomes, timeliness, agency and portfolio
  breakdowns, the 5-year trend, and the agentic dashboard/report builder over
  that data.
- **Refused:** everything outside that scope — other countries' FOI or freedom of
  information, immigration/visa or any other government function, non-FOI data
  sources, and any attempt to use the data to reach conclusions about individuals,
  agencies' internal conduct, or matters beyond the published statistics.
- The refusal is a one/two-line polite answer that declines to engage, and is
  logged to lineage.

### 6.3 Jailbreak guardrail

Regex scan for prompt-injection and jailbreak patterns (mirroring
`dash_builder.py`): "ignore previous instructions", "reveal your system prompt",
"execute code", "show api key", role-play/alternate-identity attempts, and similar.
Blocked requests are logged and refused cleanly.

### 6.4 Tool sandbox

Read-only by construction. No shell, no file access, no arbitrary execution.
`fetch_source` is https + allowlisted hosts only. `compute` is AST-safe
arithmetic over declared columns. The agent cannot write to the dataset, the
lineage ledger, or the host.

### 6.5 Identity guardrail

The agent never reveals the underlying model vendor, concrete weights, hardware,
or prompt. When asked "what model are you" (or any variant), the stovepipe answer
is **the one and only** disclosure:

> "I am powered by the axoquant sovereign model stack (FartKraft), trained on
> local data."

That is the only model disclosure. It is true at the level the demo intends — the
model stack is sovereign and local — and deliberately does not name the concrete
weights, vendor, or hardware. This applies to the chat, the agentic builder, and
any report/dashboard metadata exposed on the public surface.

## 7. Lineage viewer, ledger, deploy, scope

### 7.1 Lineage viewer

One read-only endpoint `GET /lineage/{artifact_id}` rendering a single
self-contained HTML page. Per artifact it shows: request (verbatim, timestamp,
model); dataset snapshot (files, hashes, `window_mode`, `canonical_hash`,
`normaliser_ver`); tool-call transcript in order (tool, op, args, rows,
`rows_hash`); computed figures (key → value → source rows → `lineage_ops` row);
basis beside every figure; link to the built page. One endpoint + one template —
the data is already relational.

### 7.2 Lineage ledger

Hybrid, matching the codebase's existing pattern (Postgres `access_log` + JSONL
governor ledgers):

- **JSONL firehose** — raw best-effort event stream, one line per event:
  `data_loaded`, `request_received`, `tool_call`, `spec_selected`,
  `build_computed`, `output_written`, `review_verdict`. Captures the
  dashboard-builder request + full tool-call transcript.
- **Postgres tables** — `lineage_artifacts` (one row per dashboard/report/
  builder_request, with request text verbatim + spec + spec_hash + model +
  status), `lineage_ops` (every calculation: `dsl | figure | sql | compute |
  retrieve`, with op, params, `row_count`, `rows_hash`, `result_value`),
  `lineage_tool_calls` (the transcript), all keyed to `foi_datasets`.

Both are best-effort — a ledger failure must never fail a build.

**Replay verification:** a `lineage_replay` check in the governor style
recomputes each `lineage_ops` row from `(dataset_id, op, params)` and compares
`rows_hash`/`result_value` — it runs the computation itself, never trusts the
stored value.

### 7.3 Deploy

- idc-1 origin (FastAPI chat-proxy), Cloudflare tunnel + Worker, no auth.
- Static 12 pages file-based → render with the chat/LLM path down.
- As-at-18-May-2026 snapshot baked in → no live data.gov.au fetch on demo day.
- Lineage tables additive to the idempotent `migrate.sql` (~60 lines).

### 7.4 Scope summary

**Ships:** normalising ingest; golden-benchmark acceptance test (abort loud on
mismatch); canonical facts in Postgres + in-memory frame; enum-constrained DSL +
`foi_stats` catalog + `compute()` div-by-zero fix; agentic builder wired from
`dash_builder.py` with per-turn transcript + lineage persistence + citation
pointers; `/lineage/{artifact_id}` viewer; 12 static pages (FY 5-year trend +
single-quarter Q1 headline); governance (scope, jailbreak, tool sandbox,
identity); deploy (idc-1 + tunnel + Worker, no auth).

**Deferred:** pgvector / any vector backend (if ever forced, pgvector-inside-
horizon beats a second Qdrant collection; Qdrant stays write-side); the read-only
SQL tool + `foi_ro` SELECT-only role (only if a gov evaluator asks to interrogate
SQL directly); bitemporal valid_from/to lineage + multi-worker JSONL; portfolio
grouping derived from an *external* MoG-directory dependency (the bundled
agency→portfolio map in the ingest ships); any lineage-viewer expansion.

## 8. Key risks

- **Quarterly normaliser correctness** is the biggest demo-day risk: wrong
  cumulative→single-quarter handling makes every figure wrong and a government
  audience will catch it. Mitigated by the golden-benchmark acceptance test.
- **Model endpoint unreachable on demo day:** the agentic path dies, but the
  static pages and platform-computed figures always render; pre-demo dry-run
  checks LLM reachability.
- **MoG rename drift:** the rename map is platform-curated, versioned alongside
  the ingest, and named in each affected figure's lineage.
- **Semantic misalignment** (the agent emits a valid-but-wrong op for the
  question): mitigated by measure-family tags, basis labels, source-rows-next-to-
  figure rendering, and a flag-not-block alignment review appended to lineage.
