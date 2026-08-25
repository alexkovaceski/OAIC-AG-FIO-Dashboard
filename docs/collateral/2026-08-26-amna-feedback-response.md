# Response to your FOI dashboard review

Amna, thanks for the review. It was thorough and most of it was right.
This document goes through every item: what has changed on the live site
since, what was already in place, and what is still in build. Everything
marked "live" is on https://foi.axoquant.com now and you can re-check it
directly. One request up front: do a hard refresh (Ctrl+Shift+R) before
re-reviewing. Your session on the 25th overlapped a styling deploy by
minutes, and at least one thing you saw (the illegible legend) was a
stale cached stylesheet we have since made impossible to serve again.

## Where the data comes from

Every figure on the site is computed from the published source data:

- Dataset: **Freedom of Information statistics** on data.gov.au:
  https://data.gov.au/data/dataset/freedom-of-information-statistics
- Files used: the six annual workbooks `agency-foi-data-2019-20.xlsx`
  through `agency-foi-data-2024-25.xlsx`, plus the current-year file
  `agency-foi-data-2025-26-q1-to-q3-as-at-18-may-2026.xlsx` (direct
  download: https://data.gov.au/data/dataset/b0771c28-09cc-4c4e-9e61-9a96f6e3d040/resource/0438fe31-540c-47cd-8923-826fa13b30c2/download/agency-foi-data-2025-26-q1-to-q3-as-at-18-may-2026.xlsx)
- The eight single-quarter headline figures (12,359 requests received,
  etc.) are transcribed from the OAIC's published dashboard on
  https://www.oaic.gov.au/freedom-of-information/australian-government-freedom-of-information-statistics
  because the cumulative Q1-Q3 file cannot produce a single quarter.
  Every tile that uses them now says so on the tile itself.

This answers your page-2 question directly: the report and our site draw
on the same dataset above. We verified against the live Power BI report
that 12,359 is Q1 2025-26 (July to September 2025), shown under its
"Jul to Sep-25 (Q1)" header. The "Q3" reading appears to have come from
the file's Q1-Q3 coverage label.

## Your data findings (A items)

| Item | Status |
|---|---|
| Cumulative vs single-quarter | Resolved. 34,418 is the cumulative applicant figure and matches our chart, as you verified. 12,359 is Q1, verified against the live report as above. Tiles carry the source caption. |
| Totals do not re-sum (34,810 vs 34,418) | Explained and disclosed, live. Both are published sub-totals: 34,418 received from applicants plus 392 received on transfer equals 34,810. The reconciliation is on the Data notes page, and the on-transfer channel is now ingested as its own measure. Our extraction re-sums exactly against the sheet's own totals on every column we read. |
| Notes rows prefixed with x | Confirmed working, as you found. Measured: zero of ~55,000 extracted facts come from x-prefixed rows. |
| Machinery of Government renames | Fixed, live. The rename map now covers DISR plus four further verified renames, applied to the most-recent-name convention the publisher documents. The 2021 courts merger is deliberately kept as distinct entities because the source itself publishes Division 1 and Division 2 separately and treats merger-created bodies as new entities; the Data notes page explains this. Portfolio data is now captured from the workbooks' own portfolio rows and stored per agency per year; the portfolio filter ships with the next deploy. |
| Trend axis vs five-year text | This inconsistency is in the source page itself: the OAIC page text says five years while its trend view shows eight quarters. We documented the decision on 20 August and use the published annual series (FY2019-20 to FY2025-26). |
| Quarterly data ends 2018-19 | Source constraint, agreed. No quarterly detail is published for 2019-20 onward, so we show annual figures honestly rather than reconstructing quarters that do not exist. |
| Decision timeliness measures | Decision counts, outcomes and timeliness were extracted and live before your review (see the Decision outcomes and Timeliness pages). The remaining workbook sheets (Exemptions, Charges, Internal review, Section 48, costs) are scheduled next. |

## Your site findings (B items)

Fixed and live now:

- **View lineage** links work on every page and open the real provenance
  record: source files, content hashes, computed figures (was a server
  error, your B1).
- **Stat provenance** (B15): every headline tile and figure card names
  its source, down to the workbook.
- **Type dropdown duplication** (B3): the redundant "total" option is
  removed; "All types" gives the published totals.
- **Legend legibility** (B14): not reproducible after the styling fix
  deployed the same day; stylesheets and scripts are now content-hash
  versioned so a stale cache cannot recur. Please hard refresh.

In build now, one deploy away (the chart engine rework):

- Filters on every chart page including Decisions and Timeliness, plus a
  Portfolio filter (B12, B13, B16).
- Personal/other selections will chart instead of showing the
  no-aggregate note (B2).
- The top-20 pages' year selector will actually rank the selected year
  (B6, B7), bars go horizontal with readable agency names (B9), and a
  footnote states how many agencies reported no data for that year (B8).
- Consistent y-axis scales when switching year or type (B4).
- A received-by-channel chart, applicant vs on transfer (B5; the data
  itself is already ingested and in the API).
- Change and comparison analysis: top-mover tables for refusal rate and
  timeliness on the two Change pages (B10), with the page captions
  corrected to describe what is plotted.
- KPI tiles labelled as national totals so the agency filter's scope is
  explicit (B11; the charts already respond to the filter, the tiles
  never did, and that read as broken).

Scheduled after that:

- Ingesting the remaining workbook sheets listed above.
- Per-agency profile pages and a year-in-review summary.
- Internal analyst tools (natural-language chat over the same facts,
  narrative reports, per-agency risk and forecast views). We will set
  you and Alexia up with accounts so you can review those directly;
  login details will come separately, not in email.

Happy to walk through any of it. The fastest way to re-review is to pick
any number on the site and follow it: tile caption, then the lineage
link, then the Data notes page.

Alex
