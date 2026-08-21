# FOI Data Gap Fill — decisions, outcomes & timeliness

> **Status:** Approved design. Implementation plan to follow.

## Problem

Six dashboard chart pages render the honest "No published data" placeholder because the ingest
only reads the "Request numbers" sheet (received / finalised). The source workbooks already
publish the missing measures — decisions, decision outcomes, and timeliness — on dedicated
sheets, but those sheets are never read:

- **"Action on requests"** — Granted in Full, Granted in Part, Access refused, Transferred,
  Withdrawn, Total determined (each with Personal / Other / Total / % columns).
- **"Response times"** — Requests determined, Response time within statutory, and response-time
  buckets (each P / O / T).

The figure catalog (`src/stats/catalog.py`) already defines all six figures from facts:
`requests_decided_trend`, `decided_top20`, `decision_outcomes_trend`, `granted_full_part_change`,
`timeliness_trend`, `timeliness_change`. The pages are empty only because the facts for
`decided`, `granted_full`, `granted_part`, `refused`, `withdrawn`, `within_statutory` do not exist.

## Goal

Extract those measures per-agency per-FY from the published sheets so all six figures render
real data. Every new fact is a direct read from a published source cell — the "never invent a
number" contract is preserved (no sums into a total the platform did not publish; `decided` is
read from the sheet's own Total determined column, not computed from outcome components).

## Data extraction

**Sheets and measures** (all buckets P / O / T, `quarter=None`, `measure_group="requests"`,
`derived=False`, same `_fact` shape as received/finalised):

| Source sheet | Measures | Notes |
|---|---|---|
| "Action on requests" | `decided`, `granted_full`, `granted_part`, `refused`, `withdrawn` | `decided` = Total determined (read from the sheet column, never summed). |
| "Response times" | `within_statutory` | Response time within statutory (P/O/T). |

**decided source:** read only from "Action on requests". The "Response times" sheet also carries
a "Requests determined" total; ingesting both would double-count decided in the FY series.

**Header-driven parsing:** each sheet has a two-row header — row 0 measure-group name, row 1 the
P / O / T / % run. The parser matches the measure-group header text (e.g. "Granted in Full",
"Total determined", "Response time within") and reads the P / O / T columns at that offset. This
is robust to the "Response time within" vs "Response time within statutory" text variance across
years. Verified stable across 2019-20 .. 2024-25.

**Skipped:** Transferred and the response-time bucket columns (up to 30 / 31-60 / 61-90 / over
90). No figure or stat consumes them (YAGNI).

**Data-model details:**

- Annual files (2019-20 .. 2024-25) -> `quarter=None`, `fy` = the year.
- 2025-26 file (Q1-Q3 cumulative) -> treated as `quarter=None`, `fy="2025-26"`, exactly as
  received/finalised already are. Golden Q1 constants stay `quarter=1`, untouched.
- Missing measure in a year -> no rows for that FY -> `_fy_series` yields None (honest blank),
  never a fabricated zero. The catalog already handles this.
- The "Total" agency row is skipped, same as `_agency_facts`.

## Catalog / pages

No changes needed. `_figure` already computes all six figures from the facts; the pages light up
automatically once the facts exist.

## Tests

- New: `normalise` emits `decided` / `granted_full` / `granted_part` / `refused` / `withdrawn` /
  `within_statutory` per FY.
- New: `_fy_series` for each new measure is non-empty across 2019-20 .. 2025-26.
- New: the six figures are no longer empty.
- New: cross-sheet integrity — Total decided (from "Action on requests") equals the sum of
  outcome components (`granted_full + granted_part + refused + withdrawn`), per FY.
- Existing: all 122 stay green. The no-fabricated-figures contract test still holds (every value
  is a real published number).

## Scope

- Modify: `src/ingest/normalise.py` (+ a small header-driven sheet-parser helper).
- No UI, no catalog, no deploy changes.
- After implementation: full suite, local serve check on the six pages, then deploy.

## Out of scope

- Response-time bucket breakdowns (no figure consumes them).
- Changing `timeliness_trend` to a percentage-of-decisions view (a one-line catalog change if
  wanted later).
