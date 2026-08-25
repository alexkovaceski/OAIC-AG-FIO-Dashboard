# Bluebird FOI Insights: product overview

*For new users. Two pages. Everything here is live at https://foi.axoquant.com.*

## What it is

FOI Insights is Bluebird's rebuild of the Australian Government FOI
statistics dashboard. It takes the same published data the OAIC uses
(the FOI statistics dataset on data.gov.au) and turns it into a public
dashboard plus a set of analyst tools behind a login. Every number on
every page is computed from the published workbooks, and every page can
show you exactly how.

The design position is simple: published figures only, provenance on
everything, and where the source has a gap the page says so instead of
inventing a number.

## The data underneath

Seven source workbooks: annual files for FY2019-20 through FY2024-25,
plus the FY2025-26 Q1-Q3 cumulative file. From these we extract request
volumes (received from applicants, received on transfer, finalised),
decision outcomes (granted in full, in part, refused, withdrawn,
decided), and statutory timeliness, each split by personal, other and
total information types. Agencies carry their portfolio as assigned in
each year's file, and renamed agencies are reconciled to their current
names using the publisher's own convention. The eight single-quarter
headline figures (Q1 2025-26) are transcribed from the OAIC's published
report and labelled as such, because the cumulative file cannot produce
them.

The Data notes page reproduces the publisher's definitional notes
verbatim, then adds our own reconciliation notes: why 34,418 and 34,810
are both correct totals for requests received, and how the 2021 courts
restructure is handled.

## The public site

Thirteen pages, no login needed:

- FOI at a glance: the headline quarter figures and the request trend.
- Requests received, finalised and decided, with financial-year trends.
- Key agency contributions: top-20 agencies by volume.
- Decision outcomes, timeliness, and change-over-time views.
- Data notes, How to use, and API access.

The chart pages carry a live filter row (agency, information type,
financial year). Selections re-derive the charts from the published
facts in your browser. If a selection has no published aggregate, the
chart says so.

Two things worth showing anyone new:

1. Source captions. Every headline tile and figure card names where its
   number comes from, down to the workbook.
2. The lineage link. "View lineage for this dashboard" at the foot of
   each page opens the full provenance record: source files, content
   hashes, and the computed figures behind that page.

There is also a read-only API (/api) exposing the same computed figures
and canonical facts the pages use, rate-limited, no key needed.

## The analyst surface (login required)

Three tools sit behind the login, for internal users:

- Chat: ask questions in plain English ("which agencies drove the rise
  in refusals?"). Answers are computed from the facts through a fixed
  set of operations, and each answer records its lineage. The assistant
  refuses questions outside the data rather than guessing.
- Reports: request a narrative report ("summarise refusal trends for
  the top agencies") and get a written analysis built from the same
  computed figures, with the figures cited.
- Risk: per-agency risk classification and request-volume forecasts,
  fitted offline and served with an honest not-fitted fallback when a
  model is unavailable.

Accounts are issued individually (username plus a generated password).
Ask Alex for one.

## How to get started

1. Open https://foi.axoquant.com and walk the pages top to bottom. Ten
   minutes covers it.
2. Pick any number and follow it: caption, then lineage link, then the
   Data notes page. That round trip is the product's core claim.
3. Log in and ask the chat something you already know the answer to.
   Check its lineage.
4. If you need the data itself, hit /api/figures and /api/facts.

## Current limits

The source publishes annual totals only from FY2019-20 onward, so
recent quarterly trends do not exist anywhere and are not shown here.
The on-transfer request channel is ingested and disclosed but not yet
charted. Portfolio filtering and per-agency profile pages are in build
now, along with deeper extractions (exemptions, charges, review
outcomes) and further report types.

Questions to Alex.
