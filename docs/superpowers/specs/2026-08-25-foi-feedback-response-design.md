# FOI feedback response — design

**Date:** 2026-08-25
**Author:** Alex + Claude (brainstormed, approved section by section)
**Inputs:** `docs/feedback/2026-08-25-amna-foi-review.md` (Amna Saleem's review,
items A1–A7 / B1–B16), `docs/memories/2026-08-25-bluebird-foi-poc-handover.md`,
two verified triage workflows run 2026-08-25 (every finding below was
adversarially re-verified before it entered this spec).

## Goal

Address every item in Amna's review, then extend the POC with new
high-value reports for two audiences: the public and OAIC staff. The
internal (authenticated) surface — chat, reports, risk/forecasts — stays
gated; Amna and Alexia get named accounts and a guided tour instead of
public promotion. Sequencing: **fix first, deploy, then one point-by-point
reply** whose every claim is verifiable live. No hard external deadline.

## Evidence base (established before design)

- **A1 resolved by live measurement.** The OAIC Power BI report
  ("FOI at a glance", page 2/12, viewed 2026-08-25 in a real browser)
  headers **"Jul to Sep-25 (Q1)"** with filter
  "2025-26 (Fin Year) + Jul to Sep-25 (Q1) (Qtr)" and headline
  **12,359 FOI requests received**. The repo's Q1 labelling
  (`GOLDEN_Q1_FIGURES`) is correct; Amna's "Q3" reading was a misread of
  the file's Q1–Q3 coverage span. No rename sweep.
- **Dataset answer for the reply.** data.gov.au package
  `b0771c28-09cc-4c4e-9e61-9a96f6e3d040`
  (slug `freedom-of-information-statistics`); current file
  `agency-foi-data-2025-26-q1-to-q3-as-at-18-may-2026.xlsx`
  (159,858 bytes, HTTP 200, verified 2026-08-25). CKAN API now lives under
  `https://data.gov.au/data/api/3/...`; this network must force IPv4
  (`curl -4`) — the IPv6 route fails TLS deterministically.
- **34,418 vs 34,810 (A2):** both are published sub-totals in the same
  Total row — "received from applicant" (34,418, what we ingest, the basis
  Amna endorsed) + "on transfer" (392) = "Total requests received"
  (34,810). Our re-summed columns match the sheet's own totals exactly on
  every column we read.
- **Already shipped before her review:** x-row exclusion (A3, 0 of 48,536
  facts leak), trend-window decision (A5,
  `docs/decisions/2026-08-20-trend-window.md` — the five-year wording is
  OAIC's own inconsistency), no post-2018-19 quarterly source data (A6),
  decisions/outcomes/timeliness extraction (A7 literal reading, commit
  43fad97, live on decision-outcomes.html), legend legibility (B14 — not
  reproducible post `082bb73`+`c58a325`; her review landed 17 minutes
  after the cache-bust deploy; reply asks for a hard refresh).
- OAIC's page states their dashboard "will shortly undergo changes to
  improve presentation of nil data, filter behaviour, introduce tool tip
  displays, and update data" — context for the reply.

## Stage 1 — data & trust

**S1.1 Portfolio dimension (A4).** Ingest captures the portfolio banner
rows it currently discards: while iterating each sheet, remember the
last-seen banner text and stamp it on each agency fact as `portfolio`.
**Decision: per-(agency, FY) mapping** — each year's facts carry the
portfolio its own file assigned that year (historically faithful across
MoG moves, zero curation). Wiring: `portfolio` column in
`horizon.foi_facts` (migrate.sql, idempotent), through
`storage/facts.py` INSERT/SELECT (currently the column is absent and
`load_facts` hardcodes `""`), into `_filters_blob`. The `by_portfolio`
DSL op (`src/stats/dsl.py`) must fail loud — error or explicit
"unmapped" flag — when portfolio coverage is absent for the requested
slice, never a silent single-bucket answer.

**S1.2 Rename map (A4).** Extend `RENAME_MAP` (`src/ingest/mog.py`) with
the verified renames: Independent Hospital Pricing Authority →
Independent Health and Aged Care Pricing Authority; Asbestos Safety and
Eradication Agency → Asbestos and Silica Safety and Eradication Agency;
Department of Health and Aged Care → Department of Health, Disability and
Ageing; Net Zero Economy Agency → Net Zero Economy Authority.
**Decision (superseded 2026-08-25 during implementation): the 2021
courts merger keeps all entities distinct, with disclosure.** The
original decision (map both predecessors to the merged court) assumed a
single merged row; the source actually publishes Division 1 and
Division 2 as separate active entities from 2021-22, and OAIC's own
data-notes state merger-created entities are represented as new
entities. Predecessor courts and both divisions therefore stay separate,
and the topology is explained in the data-notes Platform reconciliation
section. Alex ruled "keep distinct + disclose" when the conflict
surfaced. Each entry gets a test asserting the old name
yields zero distinct agency keys.

**S1.3 Transfer channel (B5 data half) + totals note (A2).** New measure
`received_transfer` from columns 7–9 of Request numbers; `received`
stays applicant-only. One added data-notes sentence:
34,418 (applicant) + 392 (on transfer) = 34,810 (total requests
received), so the reconciliation question cannot recur. The channel
visual ships in Stage 2.

**S1.4 Provenance captions (B15).** `_kpi()` gains an optional source
line. Golden Q1 tiles: "Transcribed from the OAIC Power BI report,
Q1 2025-26 (Jul–Sep 2025); not derivable from the cumulative Q1–Q3
workbook." FY-derived charts: name the source workbook. Data comes from
what `_golden_q1_facts`/`derived=True` already knows — caption-only
change.

**S1.5 Lineage (B1).** Layer 1: validate the artifact id before the
bigint query (copy the `isdigit()` guard already proven in `app.py`'s
`/dashboards` route) so `/lineage/<page-key>` degrades honestly instead
of 500ing. Layer 2: **seed a real lineage row per static page at boot**
— source files, content hashes, figure keys, derivation summary — so
"View lineage for this dashboard" renders truthfully for all 12 pages,
not just AI-built ones.

**S1.6 Copy and cache hygiene.** Fix the stale How-to-use line claiming
"the filters become live in the interactive build" (they are live);
content-hash `?v=` for JS assets via the `_css_link` mechanism
generalised (`_asset_link`), closing the cache-bug class behind B14.
**Decision: drop `total` from the Type dropdown (B3)** — "All types"
already yields total-basis figures; this consciously reverses the
commented deliberate choice at `pages.py:154-156`.

**S1.7 Housekeeping.** `deploy.py --check` account probe → pilot01–05
(5/5); README's four `foi.fartkraft.ai` references → `foi.axoquant.com`;
handover doc corrected (exact dataset filename, IPv4 note);
`.gitignore` entry for `docs/memories/` (contains plaintext throwaway
passwords; `git add -A` must not sweep it); commit the orphaned
`docs/superpowers/plans/2026-08-23-foi-chat-reporting.md` (its spec
sibling is already committed; the feature shipped). **Decision: delete**
the never-tracked scratch `background/` and root `main.py`.

## Stage 2 — figure engine

**S2.1 Declarative figure specs.** Each figure in `stats/catalog.py`
gains a spec: `kind` (`trend` | `multi_trend` | `ratio_trend` | `top_n`
| `movers`), `measures`, optional `denominator`, bucket-awareness,
optional channel dimension, `default_fy` where relevant. Server renders
the default view and emits spec + a **scoped** facts slice per page —
replacing today's full-dataset 13MB `window.__pageData` blob
(48,536 rows on every page) with tens of KB.

**S2.2 Generic client rederivation.** One engine replaces the hardcoded
`TREND_MEASURES`/`TOP_N` paths in `foi-charts.js`:

- multi-series trends → filters work on decision-outcomes' 4-series
  chart (B12/B13);
- ratio recomputation (sum numerator / sum denominator) → the two
  "Change in…" pages become genuinely filterable (B16);
- top-N takes FY as a parameter (`active.fy || spec.default_fy`), never
  a hardcoded pin → B6/B7 dead-end eliminated;
- bucket-aware sums → personal/other selections chart instead of
  "no aggregate" (B2);
- channel dimension → Applicant vs On-Transfer grouped bars on
  Requests received (B5 visual half).

`_FILTER_PAGES` is replaced by per-page filter specs; all 12 pages get
Agency/Portfolio/Type/FY dropdowns where the figure can honour them and
none where it can't.

**S2.3 Presentation.**

- Top-20 charts go horizontal (category y-axis) with the left grid
  margin widened for full agency names (the naive axis swap clips
  labels) — fixes B9.
- **Decision (B8): footnote, not ghost bars** — ranked reporters only,
  plus "N agencies reported no data for FY x and are not ranked".
- Degenerate ranking guard: when an agency filter would rank one agency
  against nobody, the chart switches to that agency's own trend.
- **Decision (B4): pinned axis, except agency views** — y-axis pinned to
  the full unfiltered range for FY/Type changes; auto-rescales only for
  single-agency selection, with a caption noting the rescale.
- **Decision (B11): KPI tiles caption as national** — golden Q1 tiles
  stay static with "National total — agency filter applies to the charts
  below" (no per-agency Q1 data exists anywhere in the source).
- **Decision (B10): movers ship on both pages** — the movers stat is
  generalised (FY-pair parameterised, defaulting to the two most recent
  complete FYs, not hardcoded FY23/FY24) and rendered as a ranked
  table + bar on Change in decision outcomes;
  a timeliness-movers twin is added for Change in timeliness. Captions
  on both "Change" pages corrected to describe what is plotted.

**S2.4 Testing.** Server-side contract tests per figure spec (spec JSON,
scoped payload contents, default render); a guard test that no page
embeds facts beyond its spec'd slice; existing UI tests extended for the
new markup (filters present on all pages, horizontal top-20, captions).

## Stage 3 — new sheets, new reports, accounts, reply

**S3.1 Ingest the unread sheets (A7 wider reading — decision: all now).**
Extend `normalise_all()` with parsers for the remaining analytic sheets
in the six annual workbooks: Charges, Internal review, Section 48
(primary / response time / internal review), Practical refusal,
Exemptions, Disclosure Log, and the FOI/IPS cost & staffing sheets —
following the `_parse_pot_sheet` pattern, each with fixture-backed
tests. The 2025-26 partial file carries only 6 sheets; parsers must
tolerate absence. New measures become available to the engine and the
agentic layer.

**S3.2 New reports — build all four.**

- **Agency profiles (public):** one deep-linkable page per agency —
  volumes trend, outcome mix, timeliness vs national, portfolio
  context, rank; sparse-data agencies degrade honestly (show gaps, never
  invent). Generated from the engine's specs.
- **Year-in-review digest (public):** plain-language annual summary
  (national trend, movers, timeliness) with lineage.
- **Risk report cards (internal):** `/risk.html` extended with a per-
  agency card — classification, forecast, drivers; reuses
  `render_forecast_section`'s existing not-fitted fallback.
- **Backlog pressure watchlist (internal):** forecast-driven ranking of
  agencies whose projected request volume vs decided-capacity trend
  implies growing backlog, from what `src/risk` already computes.

**S3.3 Reviewer accounts.** Named accounts `amna.saleem` and
`alexia.hunter` (internal role) via the existing
`create_accounts(conn, accounts)` helper — pilot01–05 stay reserved for
the pilot cohort. Passwords are delivered by Alex out of band, never in
the reply and never in committed files.

**S3.4 The reply (drafted for Alex's review, sent by Alex, after
deploy).** Point-by-point table over A1–B16: fixed (live URL) /
already-shipped-before-review (live URL + decision doc) / decision made
(what and why). Plus: the dataset answer (exact resource URL); the B14
hard-refresh note; OAIC's own "dashboard changes coming" note; what the
new sheets unlock; the ranked menu framing for the four new reports now
live; internal-site tour (chat → reports → risk) with the named
accounts. Folds in the earlier drafted summary email (Alexia's asks).
Written in Alex's voice.

## Non-goals

- Pre-2019 quarterly CSVs (A6's optional extension): deferred — they
  cannot close the 2019-20-onward quarterly gap (OAIC publishes no
  quarterly detail for those years at all); the reply says so.
- Public promotion of forecasts/risk: internal only this round.
- A dedicated database for FOI accounts: unchanged, considered-but-
  unplanned.

## Error handling principles

Carried through every stage: missing data renders as an honest gap or
note, never an invented value ("Missing data is shown, not invented" is
already site copy); degenerate derivations (empty portfolio map,
one-agency rankings, unfitted forecasts) fail loud or fall back to an
explicit explanatory state, never a plausible-looking wrong chart.

## Delivery

Stages land as ordered commits on master via subagent-driven plan
execution (implementer + reviewer per task, whole-branch review at the
end), deployed with `python scripts/deploy.py` and verified live before
the reply goes out. Tests run per task; the slow ingest-fixture suite
(2–5 min) runs at stage boundaries.
