# Curation decisions

Points where the published data admitted more than one honest reading, and what
was decided. Each entry records the decision, the date it was made, and where
the full reasoning is written down. None of them is a judgement about the data's
quality: agencies own their own FOI data and the OAIC publishes what agencies
report.

Where a decision rests on a number, that number is checked against the current
frame at every boot. A decision whose arithmetic no longer holds stops the
service.

## Courts merger: all four entities kept distinct

```prov
id: courts-merger-distinct
title: The 2021 courts merger is reported as new entities, not a rename
date: 2026-08-25
decision: Keep the two predecessor courts and both post-merger divisions as four separate agencies, and disclose it.
source: docs/superpowers/specs/2026-08-25-foi-feedback-response-design.md
```

The design assumed the Federal Circuit Court of Australia and the Family Court
of Australia would aggregate under a single merged name from 2021-22. The
source does something else: it reports the merged court as two entities,
Federal Circuit and Family Court of Australia (Division 1) and (Division 2),
each with its own continuous series from 2021-22 onward.

Nothing in the published data pins one predecessor to one division. Both
predecessors sat in the Attorney-General's portfolio and both divisions begin
cleanly in the same year, so neither portfolio nor timing can distinguish a
one-to-one mapping from a summed one. Mapping both predecessors onto one
division would attribute the other division's history to the wrong body.

All four are therefore kept distinct. This follows the OAIC's own stated
convention that agencies created by Machinery of Government changes which
combine responsibilities are represented as new entities. A reader comparing
court FOI volumes across the merger has to add the series up themselves, and the
data notes page says so. The alternative was a single line that looked
continuous and was not.

## Renamed agencies appear under their most recent name

```prov
id: most-recent-name
title: Renamed agencies are reported under their current name for all years
date: 2026-08-25
decision: Map a superseded agency name to its current name where responsibilities were materially unchanged.
source: src/ingest/mog.py
```

This follows the OAIC's own convention, stated in its data notes: agencies that
changed name but materially kept the same responsibilities are represented under
their most recent name, including for periods when the former name applied.

Five renames are applied:

- Department of Industry, Science, Energy and Resources becomes Department of
  Industry, Science and Resources
- Independent Hospital Pricing Authority becomes Independent Health and Aged
  Care Pricing Authority
- Asbestos Safety and Eradication Agency becomes Asbestos and Silica Safety and
  Eradication Agency
- Department of Health and Aged Care becomes Department of Health, Disability
  and Ageing
- Net Zero Economy Agency becomes Net Zero Economy Authority

Each pair was checked for a clean cutover before being added, and re-checked
against the raw sheets on 2026-08-26: for all five, the new name starts
reporting in the financial year immediately after the old name stops, with no
year in which both appear and no year in which neither does. A test asserts that
none of the superseded names survives into the frame.

The rule is deliberately narrow. It covers renames only. Where responsibilities
were combined or materially changed, the new body is a new entity, which is what
the courts entry above turns on.

## Trend window: financial years, not reconstructed quarters

```prov
id: trend-window
title: Trends are drawn on published financial years; quarters are not reconstructed
date: 2026-08-20
decision: Plot FY2019-20 to FY2024-25 plus the FY2025-26 part year, and never synthesise a quarter.
source: docs/decisions/2026-08-20-trend-window.md
```

The annual workbooks publish financial-year totals only. The current workbook is
cumulative across three quarters. Rebuilding individual quarters for 2019-20
onward would mean generating numbers no published source contains, so it is not
done.

Trend charts therefore run across the seven financial years the files publish,
with the most recent one marked as a part year. The single-quarter Q1 2025-26
headline figures sit on their own tiles with their own basis label and are never
blended into a financial-year series.

One inconsistency is worth naming. The OAIC page describes a five-year trend
while its own dashboard's trend views display eight quarters, from October 2023
to September 2025. This platform uses the published-file version of that claim,
which is the seven-year annual series, and says which years each chart covers
rather than relying on a label.

## Requests received: applicant basis, not total received

```prov
id: applicant-vs-total
title: "Requests received" means received from an applicant
date: 2026-08-25
decision: Report requests received from an applicant as the headline received figure, and carry requests on transfer as a separate measure.
source: docs/superpowers/specs/2026-08-25-foi-feedback-response-design.md
frame_check: applicant_vs_total
check_fy: 2025-26
check_applicant: 34418
check_on_transfer: 392
check_total: 34810
```

The Request numbers sheet publishes two totals that both describe requests
received, and picking the wrong one shifts every volume figure on the site.

For 2025-26 across the first three quarters: 34,418 requests were received from
applicants, a further 392 arrived on transfer from another agency, and the
sheet's own total requests received is 34,810. The two sub-totals and the total
are all published; they are not in conflict.

The site reports the applicant figure as "requests received", because a request
transferred between agencies has already been counted once where it was made,
and adding transfers to a national total counts the same request twice.
Transfers are kept as their own measure, `received_transfer`, and the requests
received page charts the two channels side by side so the difference is visible
rather than buried.

The three numbers above are re-summed from the frame at every boot and compared
against this entry. If the ingest or the source ever moves one of them, the
service stops.

## Q1 2025-26 headline figures are transcribed

```prov
id: golden-q1-transcription
title: The eight Q1 2025-26 headline figures come from the OAIC dashboard
date: 2026-08-20
decision: Transcribe the published single-quarter Q1 figures, mark them derived, and gate every boot on them.
source: src/config.py
```

The current workbook is cumulative across Q1 to Q3, so a single quarter cannot
be recovered from it by subtraction. The eight headline figures for Q1 2025-26
are therefore transcribed from the OAIC's published dashboard: requests
received, finalised, decided, decided within the statutory period, granted in
full, granted in part, refused, and withdrawn.

They are the only transcribed numbers on the platform. They are marked as
derived in the fact store, carry a single-quarter basis label wherever they are
shown, and never enter a financial-year series.

The transcription was read off the OAIC dashboard in a browser and the reading
is recorded in `docs/superpowers/specs/2026-08-25-foi-feedback-response-design.md`:
page 2 of the report, filtered to 2025-26 and the July-to-September quarter,
headline 12,359 requests received. That reading is the one thing on this
platform a machine cannot re-check, which is why the eight values are pinned in
code and gated at boot rather than left in a document.

They are also the boot gate. At every start the service re-sums the single
quarter slice of the normalised facts, measure by measure, and compares it to
the transcribed values; a mismatch exits rather than serving a headline that no
longer reconciles with what the OAIC published.

What that gate does and does not cover is worth stating. It catches a break in
the transcription path and anything that contaminates the single-quarter slice,
such as a future quarterly ingest landing rows in the same window. It reads no
workbook column, so it is not what protects the annual figures. Those are
covered by the `applicant-vs-total` check in this file and by the source hashes
in `sources.md`.

## No quarterly detail after 2018-19

```prov
id: quarterly-gap-post-2018-19
title: Quarterly data exists only up to 2018-19, and cannot be used to fill the gap
date: 2026-08-25
decision: Disclose the gap; do not backfill quarters from the pre-2019 files.
source: docs/superpowers/specs/2026-08-25-foi-feedback-response-design.md
```

Quarterly returns are published on data.gov.au for 2011-12 through 2018-19. From
2019-20 onward the dataset publishes annual workbooks only, so there is no
quarterly detail to read for any year this platform covers.

Ingesting the pre-2019 quarterly files would not close that gap. They stop
before the first year in the frame, so they can add earlier history but cannot
put a single quarter into 2019-20 or later. The one exception is the current
part year, where the OAIC's dashboard publishes a Q1 figure the workbook does
not; that is the transcription covered above.

The gap is stated on the site rather than papered over. A reader who wants
quarter-level movement in a recent year needs a source that does not currently
exist.
