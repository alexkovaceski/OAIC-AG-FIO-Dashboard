# Derivations

How the workbooks in `sources.md` become the long-form facts every figure is
computed from. One section per sheet the normaliser actually reads, then the
conventions that apply across all of them.

The normaliser is `src/ingest/normalise.py`. It reads three of the 21 sheets in
a full-year workbook and three of the 6 in the current part-year workbook. Each
row it emits is a single number for one agency, one financial year, one measure
and one request type. Every figure on the site is built from those rows, and the
rows themselves are listable through the public API, so a reader can go from a
chart back to the numbers behind it without asking anyone.

The column positions and header text below were measured on 2026-08-26 across
all seven ingested workbooks. Where a position is stated, it was the same in all
seven.

## Sheet: Request numbers

```prov
id: sheet-request-numbers
title: Request numbers
kind: sheet
sheet: Request numbers
measures: received, received_transfer, finalised
buckets: personal, other, total
```

Three measures are read from fixed column positions (`MEASURE_COLS`). Counting
the agency name as column 0:

- columns 4, 5, 6 — "Requests received from applicant" — become `received`
- columns 7, 8, 9 — "Requests on transfer" — become `received_transfer`
- columns 16, 17, 18 — "Requests finalised" — become `finalised`

The three columns in each group are the personal, other and total request types
in that order.

This sheet is read by position, not by header text, so a workbook that reordered
its columns would be read wrongly rather than loudly. Two things stand against
that. All seven workbooks were checked and carry the same header at each of
those positions. And the `applicant-vs-total` decision in `decisions.md` pins
the current workbook's own published Total row: the platform re-sums `received`
and `received_transfer` from the facts at every boot and compares them to
34,418 and 392, so a reorder that swapped either column stops the service.

The boot gate on the Q1 figures does not help here, and it is worth being clear
about that. It compares the transcribed Q1 values against the facts the
normaliser emits for them, which catches a break in the transcription path; it
reads no workbook column.

The header spelling is not itself stable and cannot be relied on: five workbooks
label the request-type sub-header P, O and T, while the 2023-24 and 2025-26
files spell it Personal, Other and Total.

Columns not read from this sheet: the on-hand counts at the start and end of the
period, and the columns giving each agency's percentage share of all agencies'
requests. Nothing on the site needs the published share, and importing a rounded
percentage alongside the counts it is derived from would put two versions of the
same quantity in the frame.

## Sheet: Action on requests

```prov
id: sheet-action-on-requests
title: Action on requests
kind: sheet
sheet: Action on requests
measures: granted_full, granted_part, refused, withdrawn, decided
buckets: personal, other, total
```

This sheet is read by header rather than by position. The parser lowercases the
header row and takes the first column whose header starts with a known phrase,
then reads the following three columns as personal, other and total:

- "granted in full" — becomes `granted_full` (columns 1, 2, 3)
- "granted in part" — becomes `granted_part` (columns 5, 6, 7)
- "access refused" — becomes `refused` (columns 9, 10, 11)
- "withdrawn" — becomes `withdrawn` (columns 16, 17, 18)
- "total determined" — becomes `decided` (columns 19, 20, 21)

`decided` is the sheet's own "Total determined" column, not a sum of the four
outcome measures above it, so every rate the site publishes uses the
denominator the source publishes.

Columns not read: the "Transferred" group, and the three percentage columns
that follow the granted and refused groups.

## Sheet: Response times

```prov
id: sheet-response-times
title: Response times
kind: sheet
sheet: Response times
measures: within_statutory
buckets: personal, other, total
```

One measure, read by header in the same way:

- "response time within statutory time period" — becomes `within_statutory`
  (columns 4, 5, 6)

The sheet also publishes four bands of lateness (up to 30 days, 31 to 60, 61 to
90, over 90) and its own "Requests determined" column. None are read. Timeliness
on the site is therefore the share of decisions made within the statutory
period, with `decided` from the Action on requests sheet as the denominator.
A figure that showed how late the late decisions were would need those bands
ingested first.

## Convention: personal, other and total request types

```prov
id: bucket-convention
title: The P/O/T request-type buckets
kind: convention
buckets: personal, other, total
```

Every measure in every sheet is published three times over: for requests
involving personal information, for other requests, and for the total. The
normaliser keeps all three as separate rows under a `bucket` field, so a reader
can filter to one type without the platform having to re-derive anything.

`total` is the workbook's own total column, read directly. It is not computed as
personal plus other. Where a source rounds or corrects, the published total is
what the site shows.

Every figure the site draws by default reads the `total` bucket. The Type filter
on each chart page re-derives it for requests involving personal information, or
for other requests.

## Convention: portfolio, captured from banner rows

```prov
id: portfolio-capture
title: Portfolio, read from the sheet's section banners
kind: convention
```

The workbooks group agencies under portfolio banner rows: a row carrying the
portfolio name across every column and no numbers. The normaliser recognises a
banner as a row with no numeric cell after the first, remembers the name, and
stamps it on each agency row that follows until the next banner.

Portfolio is therefore recorded per agency and per year, as each year's own file
assigned it. An agency moved between portfolios by a Machinery of Government
change carries the portfolio it was reported under in that year, not its current
one.

One gap is worth stating plainly. Each sheet's first banner sits above the row
the parser starts reading from, so the agencies in the first portfolio on each
sheet carry no portfolio at all. Measured on 2026-08-26, that is 2,295 of the
54,602 fact rows, plus the 8 transcribed Q1 rows, which are national totals and
belong to no portfolio: 2,303 rows in total, a little over four per cent. Those
rows are complete and correct in every other respect and are counted in every
national figure. They are excluded only from a portfolio breakdown. The
`by_portfolio` operation discloses how many agencies in the requested slice
carry no portfolio, and refuses to answer at all when none of them does, rather
than collapsing an unmapped slice into a single plausible-looking bucket.

## Convention: normaliser version

```prov
id: normaliser-version
title: Normaliser version stamped on every stored dataset
kind: convention
normaliser_ver: 2026-08-21-data-gap-fill
```

Every batch of facts written to the durable store carries the normaliser version
that produced it (`storage.facts.NORMALISER_VER`) alongside a content hash over
the canonical fact rows. Two ingests of the same data by the same normaliser
produce the same hash and the second is a no-op; a change to the extraction
logic produces a new dataset row rather than overwriting the old one.

The current frame is 54,602 facts: 54,594 read from the seven workbooks, plus
the 8 transcribed Q1 2025-26 headline figures. Nine measures, three request
types, seven financial years.
