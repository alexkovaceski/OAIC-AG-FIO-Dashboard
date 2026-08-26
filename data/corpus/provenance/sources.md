# Sources

Every number this platform publishes traces back to one of the sources below.
Each section opens with a key block the parser reads (`src/provenance.py`) and
then explains, in plain terms, what the source is and what it is used for.

A source that carries `ingested_as` is a file held in this repository and read
by the normaliser at boot. Its `sha256` is checked against the bytes on disk
every time the service starts: if the file changes and the registry does not,
the service refuses to start. A source without `ingested_as` is a reference,
not an input.

The hashes, byte counts and financial-year coverage recorded here were measured
on 2026-08-26 by reading the files in `data/sources/` and the facts the
normaliser derives from them. They were not copied from any document.

## data.gov.au — Freedom of information statistics

```prov
id: dataset-page
title: Freedom of information statistics (data.gov.au dataset)
url: https://data.gov.au/data/dataset/freedom-of-information-statistics
package_id: b0771c28-09cc-4c4e-9e61-9a96f6e3d040
verified: 2026-08-26
```

The dataset page every workbook below is published on. It is maintained by the
Office of the Australian Information Commissioner (OAIC) and carried 37
resources when it was last read, on 2026-08-26, through the CKAN
`package_show` API.

The dataset is the whole published history of Australian Government FOI
statistics, going back to 2011-12. This platform ingests the seven most recent
agency workbooks, which is what the seven entries below pin. The rest of the
dataset — the pre-2019 quarterly and annual CSVs, the reporting guides, and the
long-run costs and charges series — is not read. See the
`quarterly-gap-post-2018-19` entry in `decisions.md` for why the quarterly files
cannot close the gap they look like they close.

One more file than the seven sits in `data/sources/`:
`foi-requests-costs-and-charges-1982-2024.csv`, a long-run national cost series
from the same dataset page. It is not registered here because it is not read.
Nothing on the site is computed from it, and it is a different unit of analysis
from the agency-level facts, so merging it into this frame would not be an
improvement. If it is ever wanted, it belongs to its own figure with its own
entry above.

## Agency FOI data 2019-20

```prov
id: workbook-2019-20
title: Agency FOI data - 2019-20 (Excel).xlsx
url: https://data.gov.au/data/dataset/b0771c28-09cc-4c4e-9e61-9a96f6e3d040/resource/bb44fbf0-031f-4ed9-a152-0d59eae80deb/download/agency-foi-data-2019-20-excel.xlsx
sha256: a4331ed2d8a84f90c13b10c333b96b5c5a1865803439c8e3e356960035b79d82
bytes: 422928
covers: 2019-20
ingested_as: data/sources/agency-foi-data-2019-20.xlsx
published: 2020-11-19
verified: 2026-08-26
```

Full financial year, July 2019 to June 2020. The workbook holds 21 sheets; the
normaliser reads three of them and derives 8,019 facts.

## Agency FOI data 2020-21

```prov
id: workbook-2020-21
title: Agency FOI data 2020-21.xlsx
url: https://data.gov.au/data/dataset/b0771c28-09cc-4c4e-9e61-9a96f6e3d040/resource/10814129-d618-4c6c-80d8-576aab3fdc4b/download/agency-foi-data-2020-21.xlsx
sha256: d76e1cb2b1921db3ed591160355b181a4ca2f59c23aa664d1fe7fbc5fce2f6a1
bytes: 394587
covers: 2020-21
ingested_as: data/sources/agency-foi-data-2020-21.xlsx
published: 2021-10-26
verified: 2026-08-26
```

Full financial year, July 2020 to June 2021. 21 sheets, three read, 7,587 facts.

This is the one resource for which data.gov.au publishes its own content hash
(an MD5, `887306f8e5b3fb53f8563d7454d5bbe5`). The copy in this repository
reproduces it exactly, which pins the local file to the published one byte for
byte rather than by size alone. For the other six workbooks data.gov.au
publishes no hash, so the correspondence rests on the byte count, which matches
the published `size` field for all seven.

## Agency FOI data 2021-22

```prov
id: workbook-2021-22
title: Agency FOI data 2021-22.xlsx
url: https://data.gov.au/data/dataset/b0771c28-09cc-4c4e-9e61-9a96f6e3d040/resource/2ca9a822-040b-4d47-92a4-55868a3358a7/download/agency-foi-data-2021-22.xlsx
sha256: 9b70e7ee6867d52845b98ebbec353b342e19f45f30522880da50a1b81c01a26c
bytes: 427885
covers: 2021-22
ingested_as: data/sources/agency-foi-data-2021-22.xlsx
published: 2022-11-02
verified: 2026-08-26
```

Full financial year, July 2021 to June 2022. 21 sheets, three read, 7,749 facts.
This is the first year in which the Federal Circuit and Family Court of
Australia reports as two divisions; see `courts-merger-distinct` in
`decisions.md`.

## Agency FOI data 2022-23

```prov
id: workbook-2022-23
title: Agency FOI data 2022-23.xlsx
url: https://data.gov.au/data/dataset/b0771c28-09cc-4c4e-9e61-9a96f6e3d040/resource/6f7292d7-3f12-49b9-8ee5-c7ebea18cb6d/download/agency-foi-data-2022-23.xlsx
sha256: 598dd62fa245ce1930cde31b96c8df47baa0c76250becd4d9cb17ed8bccb4935
bytes: 407205
covers: 2022-23
ingested_as: data/sources/agency-foi-data-2022-23.xlsx
published: 2024-06-18
verified: 2026-08-26
```

Full financial year, July 2022 to June 2023. 21 sheets, three read, 7,452 facts.

## Agency FOI data 2023-24

```prov
id: workbook-2023-24
title: Agency FOI data 2023-24.xlsx
url: https://data.gov.au/data/dataset/b0771c28-09cc-4c4e-9e61-9a96f6e3d040/resource/52b58c68-6d9c-4a78-8ba8-0bec492b11bb/download/agency-foi-data-2023-24.xlsx
sha256: b933826c0a2d80f0fcf57f186f2b994d9a14dac9289012a5363be4ca2f8c073d
bytes: 422168
covers: 2023-24
ingested_as: data/sources/agency-foi-data-2023-24.xlsx
published: 2024-11-18
verified: 2026-08-26
```

Full financial year, July 2023 to June 2024. 21 sheets, three read, 7,560 facts.

## Agency FOI data 2024-25

```prov
id: workbook-2024-25
title: Agency FOI data 2024-25.xlsx
url: https://data.gov.au/data/dataset/b0771c28-09cc-4c4e-9e61-9a96f6e3d040/resource/f372d955-c5a4-4c60-b2ab-f252092f8978/download/agency-foi-data-202425.xlsx
sha256: 973a1ecd2722b981e90ac04e3e99036ae73db9e6fa2452066b7c53d1ced94563
bytes: 453165
covers: 2024-25
ingested_as: data/sources/agency-foi-data-2024-25.xlsx
published: 2025-11-06
verified: 2026-08-26
```

Full financial year, July 2024 to June 2025. 21 sheets, three read, 8,181 facts.

This is the most recent complete year on the dataset page, so it is the year the
site ranks agencies on by default. `stats.catalog.LATEST_COMPLETE_FY` names it
in one place and every top-20 figure reads that constant.

## Agency FOI data 2025-26, Q1 to Q3

```prov
id: workbook-2025-26-q1-q3
title: Agency FOI data 2025-26 - Q1 to Q3 as at 18 May 2026
url: https://data.gov.au/data/dataset/b0771c28-09cc-4c4e-9e61-9a96f6e3d040/resource/0438fe31-540c-47cd-8923-826fa13b30c2/download/agency-foi-data-2025-26-q1-to-q3-as-at-18-may-2026.xlsx
sha256: 0ca28e57f061bfeb2f5a6e789078f3d824b6f59e3b8d4fc900ab432fcaa00bc3
bytes: 159858
covers: 2025-26
ingested_as: data/sources/agency-foi-data-2025-26-q1-to-q3.xlsx
published: 2026-05-28
verified: 2026-08-26
```

A part year: July 2025 to March 2026, reported cumulatively rather than quarter
by quarter. It carries 6 sheets rather than the 21 in a full-year workbook; the
three the normaliser reads are all present, and it yields 8,046 facts.

Because it is not a complete July-to-June year, figures drawn from it are
labelled as part-year on the site and never carry the "financial year" basis
label. Its totals are lower than a full year's for that reason alone, which is
what the part-year note beside each chart exists to say.

## OAIC published FOI dashboard

```prov
id: oaic-dashboard
title: Australian Government Freedom of Information statistics (OAIC)
url: https://www.oaic.gov.au/freedom-of-information/australian-government-freedom-of-information-statistics
covers: 2025-26
verified: 2026-08-26
```

The OAIC's own published dashboard. It is the source of the eight single-quarter
Q1 2025-26 headline figures the site shows, which are transcribed from it rather
than derived from any workbook. The Q1-to-Q3 workbook above is cumulative, so
the individual first quarter cannot be recovered from it by subtraction.

Those eight figures are pinned in `src/config.py` as `GOLDEN_Q1_FIGURES` and are
checked against the normalised facts at every boot. A mismatch stops the service
rather than degrading a page. See `golden-q1-transcription` in `decisions.md`.

Nothing else on this platform is transcribed. Every other number is computed
from the workbooks above.
