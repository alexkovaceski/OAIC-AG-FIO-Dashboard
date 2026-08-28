# FOI Insights: public user guide

FOI Insights presents Australian Government freedom-of-information (FOI) statistics. Every figure is computed from the published source files. No number is typed by hand.

The site covers the financial years 2019-20 to 2025-26. The 2025-26 file is a part year: it reports July 2025 to March 2026 (Q1 to Q3), published by the OAIC on 18 May 2026. Earlier years are complete July to June years.

Eight headline figures for Q1 2025-26 were read from the OAIC's published dashboard. The workbook reports that year cumulatively, so a single quarter cannot be recovered from it. Everything else is computed from the workbooks.

## The pages

### Overview

- FOI at a glance: the eight Q1 2025-26 headline figures, plus the requests received trend by year. The filters do not reach the headline tiles; they are national totals, and the page says so.

### Requests

- Requests received: national totals by year, with the channel split (requests from applicants, and requests received on transfer from another agency).
- Key agency contributions: the 20 agencies with the most requests received.
- Requests finalised: national totals by year.

### Decisions

- Requests decided: national totals by year.
- Key agency contributions: the 20 agencies with the most decisions.
- Decision outcomes: granted in full, granted in part, refused and withdrawn, by year.
- Change in decision outcomes: the national grant share by year, plus the agencies whose refusal rate moved most between the two latest complete years.

### Timeliness

- Timeliness: the share of decisions made within the statutory period, by year.
- Change in timeliness: the national share by year, plus the agencies whose within-statutory rate moved most between the two latest complete years.

### Reference

- Data notes and disclaimer: the publisher's notes, reproduced word for word, plus this site's own reconciliation notes.
- How to use: the basis labels and the filter behaviour explained.
- API access: a read-only JSON API behind the charts (dataset info, figures, facts and measures).
- Data provenance: where the data comes from, file by file, with the checks the site runs.

## Reading a figure

Each figure card carries a basis label, which names the window the figure covers:

- single quarter: one published quarter (Q1 2025-26)
- cumulative: a quarter window added up (for example Q1 to Q3)
- financial year: a complete July to June year
- part financial year: a year the source has not published in full

A part-year figure is a part-year total. It is not comparable with a full-year figure, and the site says so beside each one.

Each figure card also links to its provenance: which files fed it, with the hashes, and the decisions made when the data was prepared.

## Missing data

Where the source files do not publish a measure, the page says "No published data for this measure". It does not draw a zero. A missing year reads as a dash, never as a zero.

## Filters

The chart pages carry four filters: agency, portfolio, type (personal or other) and financial year. A selection re-draws the chart in the browser from the published facts. Where a selection has no published figure, the page says so instead of inventing one. The headline tiles are national totals and never change with a filter.

## Where the data comes from

The source is the OAIC's FOI statistics dataset on data.gov.au. The site reads seven agency workbooks: one complete year for each of 2019-20 to 2024-25, and the 2025-26 Q1 to Q3 file. The Data provenance page lists each file with its hash and the curation decisions.

## Getting help

The Data notes page carries the publisher's notes and this site's reconciliation notes. For anything else, write to contact@bluebirdadvisory.com.au.
