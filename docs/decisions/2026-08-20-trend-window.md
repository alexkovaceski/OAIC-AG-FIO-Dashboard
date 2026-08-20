# Decision — Trend window basis (2026-08-20)

**Status:** agreed by Alex (design phase).

## Decision

The FOI dashboard POC replicates the Power BI report using **option 2**:

- **Single-quarter Q1 2025-26 headline figures** (requests received 12,359; finalised
  11,549; decided 7,344; within statutory 5,167; granted in full 1,426 / part 3,968 /
  refused 1,950; withdrawn 3,955) as the headline numbers, sourced from the published
  Power BI figures as ground truth.
- **Financial-year 5-year trend** (FY2019-20 → FY2024-25, plus FY2025-26 Q1-Q3
  cumulative) from the published annual files for the trend views.
- **No per-quarter reconstruction** for years without published quarterly data.

## Why

The current data.gov.au file (`agency-foi-data-2025-26-q1-to-q3`) is Q1–Q3
cumulative (34,418 received). The Power BI report shows single-quarter Q1. Per-quarter
files exist on data.gov.au only through 2018-19; annual xlsx files for 2019-20 →
2024-25 are FY-totals only. Reconstructing individual quarters for 2019-20 onward would
require synthesising data the published sources do not contain — a leakage/credibility
risk for a government-facing demo.

## Reconciliation note (verified from the Power BI screenshots)

The Power BI report's trend views actually display **Oct-2023 → Sep-2025** (8
quarters ≈ 2 financial years), not the 5 years the OAIC page text claims. The POC
uses the published-data version of the claim: the **FY2019-20 → FY2024-25 annual
series** (6 financial years) plus the FY2025-26 Q1–Q3 cumulative file. This is
honest to the published files, matches the headline figures, and the lineage notes
the discrepancy where relevant.

## Consequences

- Single-quarter values for Q1 2025-26 are recorded with `basis=single_quarter` and
  marked `derived` where they are differenced from cumulative data.
- FY series are recorded with `basis=fy`.
- The lineage ledger records, for every figure, which basis and which source snapshot it
  came from.
- The `window_mode` field on every fact/lineage row is one of
  `single_quarter | cumulative | fy`, and the renderer prints the basis beside every figure.
