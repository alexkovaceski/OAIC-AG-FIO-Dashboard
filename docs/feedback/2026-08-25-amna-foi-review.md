# Feedback — Amna Saleem, 2026-08-25 17:22 Canberra (to Alex, cc Alexia)

Review of the FOI Power BI Dashboard vs the Bluebird AI solution (foi.axoquant.com).
Items numbered here for triage reference. Verbatim substance preserved; table
flattened.

## A. Data / reporting issues

- **A1 — Cumulative versus single-quarter reporting.** The file is cumulative.
  FY2025-26 Q1–Q3 = 34,418 requests received. The Power BI report displays
  12,359 for Q3, which appears to be the single-quarter value. Tools reading
  the file may incorrectly use the cumulative headline figure; single-quarter
  results cannot be reproduced from the file alone. Question (report page 2):
  which dataset is this sourced from on data.gov.au? Amna verified 34,418 is
  correctly reflected in the AI solution graph.
- **A2 — Total rows do not re-sum.** The sheet total (34,810) differs from the
  sum of agency rows (34,418) due to an extra transfer line. Recalculating
  totals from agency rows produces an incorrect result; published totals should
  be treated as the source of truth.
- **A3 — Notes rows mixed into data.** Rows prefixed with `x` appear within the
  table but should be treated as notes, not agencies. Automated processing may
  count note rows as agencies, creating phantom records. Amna verified the AI
  solution correctly excludes these rows.
- **A4 — Machinery of Government renames.** Agency names change over time
  (e.g. Human Services → Services Australia). Year-on-year comparisons require
  a curated mapping. Data mapping issue: portfolios do not currently group
  under their respective agency as in the FOI Power BI dashboard.
- **A5 — Trend axis differs from page text.** The report trend view shows
  Oct 2023–Sept 2025 while page text refers to a five-year view. A documented
  decision is needed on which interpretation is correct.
- **A6 — Quarterly data ends in 2018-19.** Quarterly files only extend to
  2018-19; annual files from 2019-20 onwards provide financial-year totals
  only. Recent-year quarterly trends cannot be sourced directly and would
  require reconstruction.
- **A7 — Decision timeliness measures available but not included.** Workbooks
  publish decision counts, outcomes and timeliness on dedicated sheets; the
  initial extraction only included request numbers. Decision-related reporting
  will be incomplete despite source data being available.

## B. AI solution comments/issues (bracketed = page/link name)

- **B1** — "View lineage for this dashboard" erroneous.
- **B2** — Visuals missing for "personal" and "other" Type of Information.
- **B3** — Type dropdown contains "total" and "All types", which is repetitive.
- **B4** — The y-axis intervals differ across fiscal years (FOI at a glance).
- **B5** — Visual option missing for how the requests were received, i.e.
  "Applicant" or "On Transfer" (Requests received).
- **B6** — No visuals for FY except "2024-25" (Key agency contributions).
- **B7** — Functionality for filtering/viewing top agencies missing. The AI
  solution does show a descending trend, but the x-axis is crowded and not
  entirely legible.
- **B8** — The visual does not show agencies with missing values, which could
  lead to trend interpretation challenges or perceived bias; it does show the
  max 20 agencies though.
- **B9** — Rotated labels are difficult to read compared to the horizontal bar
  chart in the PBI dashboard.
- **B10** — Missing change and comparison analysis.
- **B11** — Agency drop-down menu not working (Decisions: Requests Finalised).
- **B12** — Missing all filters (Decisions: Requests decided, Key Agency
  contributions).
- **B13** — Missing Portfolio or Agency filter, Type of information requested
  filter (Decision outcomes).
- **B14** — The legend color needs to change to white to be legible.
- **B15** — Where are the stats in the top boxes coming from? The stats are
  unclear from a source's perspective.
- **B16** — Static pages, with not enough options to manoeuvre, limiting
  insights compared to the FOI PBI Dashboard (Change in decision outcomes and
  Timeliness).
