"""provenance — the curated registry, its parser, and the live figure layer.

The premise (spec S3.5): a reader asks where a number came from and gets the
dataset, the files, the hashes, the curation decisions, and for a named figure
the row basis behind it. No claim in that answer is invented at answer time.

Be exact about what that does and does not rule out, because "nothing here is
generated" is the easier sentence and it is not quite true. Every value in a
provenance answer is one of three things: curated text a human wrote into
`data/corpus/provenance/*.md`; a number measured from the frame at answer time;
or one of two human-authored strings this module supplies — the figure
`caption`, read from `stats.catalog.FIG_CAPTIONS`, and the `qualifier`, whose
sentences are written out in `_live_layer` below, assembled by `_qualifier`,
and whose only variable parts are the key, the basis, the measured scope, and
the name of the view taken from the payload's own `applies_to`. The qualifier
IS composed, from a fixed template, and it is composed on purpose: a row count
and a hash with no statement of what they describe is precisely the false claim
this feature exists to prevent. What no code path here does is author a NEW
claim about the data — a description, a caveat, or a number a human did not
write down or the frame did not produce.

Three files make up the registry, each a list of `## ` sections. A section opens
with a fenced key block the parser reads and continues as free prose a human
wrote:

    ## Agency FOI data 2024-25

    ```prov
    id: workbook-2024-25
    title: Agency FOI data 2024-25.xlsx
    url: https://data.gov.au/...
    sha256: 973a1ecd...
    covers: 2024-25
    ingested_as: data/sources/agency-foi-data-2024-25.xlsx
    ```

    Full financial year, July 2024 to June 2025. ...

No YAML: the block is `key: value` lines, one per line, keys lowercase with
underscores, values taken verbatim after the first colon (so a URL survives).
`covers`, `measures` and `buckets` split on commas. Anything after the closing
fence is the entry's prose.

FAIL LOUD, NOT DEGRADED. A missing file, a section with no key block, a
malformed key line, a missing required key or a duplicate id is a
`ProvenanceError`, and `_boot` calls `validate_registry` immediately after the
golden gate, so the service refuses to start rather than serving a page beside
provenance that has drifted. Stale provenance on a transparency site is worse
than none: it is a false claim with an official-looking hash next to it.

VALIDATED CONTENT ONLY. `load_registry` is the raw parse and enforces SHAPE
only. Content — a hash against the bytes on disk, a `covers` year against the
frame, a measure against the frame, a decision's `frame_check` — is checked by
`validate_registry`, which stashes the registry it accepted. `describe` serves
that stashed copy, so a registry edited after boot cannot be handed to a reader
wearing a validation it never passed. See `_validated_registry` for what
happens when `describe` runs before any validation has.

WHAT THE LIVE LAYER MAY AND MAY NOT SAY. There are four classes of key and they
do not share a caveat; the qualifier is chosen per class in `_live_layer`.

  CHART FIGURES A PAGE SHIPS (`_shipped_figure_keys`). Each chart page ships
  the whole `foi_stats` result for its figures into
  `window.__pageData.figures[key]`, including `source_rows` and `rows_hash`,
  while shipping facts for EVERY financial year (`pages._page_data_script`
  filters its fact blob by measure only, never by year); the chart engine then
  re-derives the chart in the browser for whatever filter the reader picks. So
  the hash that travels with a figure describes the DEFAULT view and not the
  one a filtered reader is looking at, and the qualifier says so. The layer
  does NOT attempt to recompute a basis for a client-side filter state: the
  server never sees that state, and a count derived from a state it cannot
  observe would be the same class of false claim in a new place.

  CHART FIGURES NO PAGE SHIPS. `FIG_KEYS` is not that set. Measured 2026-08-27,
  `refused_pct_trend`, `agency_contributions_received` and
  `agency_contributions_decided` are in no page's `PAGE_FIGURE_KEYS` and in no
  rendered page, so nothing re-derives them under a filter; they are reachable
  only through the `provenance` op in `stats.dsl`, which takes a key from the
  model. Handing them the chart caveat promised a filter control that does not
  exist — the same defect as promising one to a stat, in the direction that
  under-claims, which is why it survived a round that was looking for
  over-claims.

  Their sentence says only that no page SHIPS the figure, not that no page
  draws such a chart. Two of the three are spec-identical to a chart that is
  drawn: `agency_contributions_received` matches `received_top20` and
  `agency_contributions_decided` matches `decided_top20` on kind, measure, n,
  default_fy and `rows_hash`. Only `refused_pct_trend` is drawn nowhere, so the
  stronger sentence would have put a fresh false claim inside the fix for one.

  SERVER-RENDERED STATS. No stat key appears in `site.pages.PAGE_FIGURE_KEYS`,
  so no stat reaches `window.__pageData.figures` and `foi-charts.js` never
  touches one. The KPI tiles and the movers tables are server-rendered HTML
  over a fixed basis; the page says so itself (`pages._kpi_scope_note`). Giving
  them the chart caveat would offer a reader a filter path that does not exist,
  so they get a qualifier that says the filters do not reach them.

  TRANSCRIBED Q1 FIGURES. The eight single-quarter keys are the one place on
  this platform where a value was READ OFF the OAIC's published dashboard
  rather than computed from a workbook, and that — not a filter caveat — is the
  provenance fact a reader needs. Their qualifier points at the OAIC dashboard
  reference and the transcription decision, both of which travel in the same
  payload, and describes them as the answer renders them rather than by their
  registry ids, which the renderer never prints. It states what the boot check
  compares (this service's own recorded values) and what it does not (anything
  the OAIC publishes); see the comment on that branch for the measurement.

  They are recognised by their `single_quarter` basis rather than by a second
  list of eight key names to fall out of step with the first.
  `pages._source_for_basis` attaches `GOLDEN_SOURCE` to the same eight tiles,
  but NOT BY THE SAME RULE, and an earlier version of this docstring said it
  was. This module compares the basis ENUM (`stat["basis"] ==
  "single_quarter"`); that function tests for the substring "single quarter"
  inside a DISPLAY label produced by `pages._basis_label`, which maps the enum
  through `_BASIS_LABEL` to "basis: single quarter". They coincide because that
  is the only one of the three labels containing the substring — measured
  2026-08-27 they agree on all 25 catalog keys and on all three
  `config.WINDOW_MODES`. Nothing enforces the coincidence: reword the label and
  the citation beside the tile detaches from the qualifier in this file,
  silently. `tests/test_provenance.py` pins the two predicates against each
  other over the whole basis enum, which is what makes them one rule rather
  than two that happen to agree.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from config import CORPUS_DIR, PROJECT_ROOT
from stats.catalog import (FIG_CAPTIONS, FIG_KEYS, FIGURE_SPECS,
                           _figure_source_rows, foi_stats)


class ProvenanceError(RuntimeError):
    """The registry is missing, malformed, or no longer matches reality."""


# Module-level so a test (and an operator pointing at a staging corpus) can
# repoint it; every function below looks it up at call time.
_REGISTRY_DIR = CORPUS_DIR / "provenance"

# The registry `validate_registry` last ACCEPTED, and the only registry
# `describe` will serve. Set on success only. A test that needs to re-validate
# a repointed _REGISTRY_DIR resets this to None.
_VALIDATED: dict | None = None

_FILES = {"sources": "sources.md",
          "derivations": "derivations.md",
          "decisions": "decisions.md"}

# Keys every entry of a kind must carry. Shape rules that depend on another key
# (an ingested source needing a hash, a sheet derivation needing its measures)
# are applied in _check_entry_shape.
_REQUIRED_KEYS = {"sources": ("id", "title", "url"),
                  "derivations": ("id", "title", "kind"),
                  "decisions": ("id", "title", "date", "decision")}

# Comma-separated values the parser splits into lists.
_LIST_KEYS = frozenset({"covers", "measures", "buckets"})

_KEY_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

_DERIVATION_KINDS = ("sheet", "convention")

# foi_stats' basis tokens, spelled for a reader. "on a fy basis" is a database
# field printed at a member of the public; these are the same three values the
# site's own basis labels use. A basis with no entry falls through as itself
# rather than being dropped — an unspelled token is ugly, a missing one is a
# hole in the sentence.
_BASIS_PROSE = {"fy": "financial-year",
                "single_quarter": "single-quarter",
                "cumulative": "cumulative"}


# ------------------------------------------------------------- the parser ---

def _split_sections(text: str, path: Path) -> list[tuple[str, list[str]]]:
    """[(heading, body lines)] for every `## ` heading. A `## ` inside a fenced
    block is body text, not a heading — the fence state is tracked so a key
    block or a prose code sample cannot silently start a new entry."""
    sections: list[tuple[str, list[str]]] = []
    body: list[str] | None = None
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            body = []
            sections.append((line[3:].strip(), body))
            continue
        if body is not None:
            body.append(line)
    if in_fence:
        raise ProvenanceError(f"{path.name}: unclosed fenced block")
    return sections


def _parse_key_block(lines: list[str], heading: str, path: Path) -> tuple[dict, str]:
    """(keys, prose) for one section body. The FIRST fenced block is the key
    block; everything after its closing fence is prose."""
    start = next((i for i, l in enumerate(lines) if l.startswith("```")), None)
    if start is None:
        raise ProvenanceError(
            f"{path.name}: section {heading!r} has no key block — every entry "
            f"must open with a fenced `key: value` block")
    end = next((j for j in range(start + 1, len(lines))
                if lines[j].startswith("```")), None)
    if end is None:
        raise ProvenanceError(
            f"{path.name}: section {heading!r} has an unclosed key block")

    keys: dict = {}
    for raw in lines[start + 1:end]:
        if not raw.strip():
            continue
        key, sep, value = raw.partition(":")
        key = key.strip()
        if not sep or not _KEY_RE.match(key):
            raise ProvenanceError(
                f"{path.name}: section {heading!r}: malformed key line {raw!r} "
                f"— expected `key: value` with a lowercase key")
        if key in keys:
            raise ProvenanceError(
                f"{path.name}: section {heading!r}: duplicate key {key!r}")
        value = value.strip()
        if key in _LIST_KEYS:
            keys[key] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            keys[key] = value
    return keys, "\n".join(lines[end + 1:]).strip()


def _check_entry_shape(entry: dict, file_kind: str, path: Path) -> None:
    """Required keys, plus the shape rules one key imposes on another.

    `file_kind` is which registry file this entry came from (sources /
    derivations / decisions). It is NOT `entry["kind"]`, which is a derivation's
    own sheet-or-convention type."""
    missing = [k for k in _REQUIRED_KEYS[file_kind] if not entry.get(k)]
    if missing:
        raise ProvenanceError(
            f"{path.name}: entry {entry.get('id') or entry['heading']!r} is "
            f"missing required key(s) {missing}")
    if file_kind == "sources" and entry.get("ingested_as"):
        # an ingested file is the one thing validate_registry can check against
        # reality; without a hash and a year span the entry claims nothing
        # checkable
        if not _SHA256_RE.match(entry.get("sha256", "")):
            raise ProvenanceError(
                f"{path.name}: source {entry['id']!r} is ingested but carries "
                f"no valid sha256 (got {entry.get('sha256')!r})")
        if not entry.get("covers"):
            raise ProvenanceError(
                f"{path.name}: source {entry['id']!r} is ingested but does not "
                f"say which financial year(s) it covers")
    if file_kind == "derivations":
        if entry["kind"] not in _DERIVATION_KINDS:
            raise ProvenanceError(
                f"{path.name}: derivation {entry['id']!r} has kind "
                f"{entry['kind']!r}; expected one of {_DERIVATION_KINDS}")
        if entry["kind"] == "sheet":
            for required in ("sheet", "measures", "buckets"):
                if not entry.get(required):
                    raise ProvenanceError(
                        f"{path.name}: sheet derivation {entry['id']!r} is "
                        f"missing {required!r}")


def _parse_file(path: Path, file_kind: str) -> list[dict]:
    if not path.is_file():
        raise ProvenanceError(f"provenance registry file missing: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProvenanceError(
            f"provenance registry file unreadable: {path} ({exc})") from exc
    sections = _split_sections(text, path)
    if not sections:
        raise ProvenanceError(f"{path.name}: no `## ` entries — an empty "
                              f"registry file is a drift, not a default")
    entries = []
    seen: dict[str, str] = {}
    for heading, body in sections:
        keys, prose = _parse_key_block(body, heading, path)
        entry = dict(keys)
        entry["heading"] = heading
        entry["prose"] = prose
        _check_entry_shape(entry, file_kind, path)
        if entry["id"] in seen:
            raise ProvenanceError(
                f"{path.name}: duplicate id {entry['id']!r} (sections "
                f"{seen[entry['id']]!r} and {heading!r})")
        seen[entry["id"]] = heading
        entries.append(entry)
    return entries


def load_registry() -> dict:
    """The parsed curated registry: {"sources", "derivations", "decisions"},
    each a list of entries in file order. Raises ProvenanceError on a missing
    or malformed file.

    A SHAPE CHECK, NOT A CONTENT CHECK, and not what a reader is served. This
    function re-reads the files every call and enforces everything a single
    file can be judged on alone: required keys, sha256 format, duplicate ids,
    derivation kinds. It checks nothing against the world — not one hash
    against the bytes on disk, not one `covers` year or measure against the
    frame, not one `frame_check`. That is `validate_registry`, and `describe`
    serves only what `validate_registry` accepted.

    So there is no hot reload, and the earlier version of this docstring was
    wrong to advertise one. Editing these files under a running service does
    not put the edit in front of a reader as validated provenance; it takes a
    restart, because the restart is what re-validates. That is the point: an
    edit reaching readers without passing the content gate is the failure mode
    this whole module exists to prevent, and a typo corrected in the prose is
    not worth a path that would also serve a wrong hash.
    """
    return {file_kind: _parse_file(_REGISTRY_DIR / name, file_kind)
            for file_kind, name in _FILES.items()}


# ---------------------------------------------------------- the validator ---

def _check_sources(sources: list[dict], frame) -> None:
    frame_fys = {f["fy"] for f in frame.facts}
    covered: set[str] = set()
    for source in sources:
        relative = source.get("ingested_as")
        if not relative:
            # A reference source may still say which years it speaks to, but its
            # `covers` deliberately does NOT count towards coverage below: only a
            # file this repo actually reads can account for a fact in the frame,
            # and letting a reference cover a year would let a deleted workbook
            # entry pass unnoticed.
            continue
        stale = sorted(set(source["covers"]) - frame_fys)
        if stale:
            raise ProvenanceError(
                f"source {source['id']!r}: claims to cover financial year(s) "
                f"{stale} that the frame does not carry")
        covered.update(source["covers"])
        path = PROJECT_ROOT / relative
        if not path.is_file():
            raise ProvenanceError(
                f"source {source['id']!r}: registry claims ingested_as "
                f"{relative!r}, which is not a file at {path}")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != source["sha256"]:
            raise ProvenanceError(
                f"source {source['id']!r}: sha256 drift — the registry claims "
                f"{source['sha256']}, {relative} hashes to {digest}")
        if source.get("bytes"):
            try:
                claimed = int(source["bytes"])
            except ValueError:
                raise ProvenanceError(
                    f"source {source['id']!r}: bytes {source['bytes']!r} is not "
                    f"a number")
            if claimed != len(data):
                raise ProvenanceError(
                    f"source {source['id']!r}: byte count drift — the registry "
                    f"claims {claimed}, {relative} is {len(data)}")
    uncovered = sorted(frame_fys - covered)
    if uncovered:
        raise ProvenanceError(
            f"no ingested source covers financial year(s) {uncovered} — the "
            f"frame carries facts whose origin the registry does not state")


def _check_derivations(derivations: list[dict], frame) -> None:
    claimed_by: dict[str, str] = {}
    buckets: set[str] = set()
    for entry in derivations:
        if entry["kind"] != "sheet":
            continue
        for measure in entry["measures"]:
            if measure in claimed_by:
                raise ProvenanceError(
                    f"measure {measure!r} is derived by two entries "
                    f"({claimed_by[measure]!r} and {entry['id']!r}) — a measure "
                    f"has one origin")
            claimed_by[measure] = entry["id"]
        buckets.update(entry["buckets"])

    frame_measures = {f["measure"] for f in frame.facts}
    undocumented = sorted(frame_measures - set(claimed_by))
    if undocumented:
        raise ProvenanceError(
            f"no derivation explains measure(s) {undocumented} — the frame "
            f"publishes numbers the registry cannot account for")
    stale = sorted(set(claimed_by) - frame_measures)
    if stale:
        raise ProvenanceError(
            f"the registry derives measure(s) {stale} that the frame does not "
            f"carry — the registry describes an ingest that no longer runs")
    frame_buckets = {f["bucket"] for f in frame.facts}
    if buckets != frame_buckets:
        raise ProvenanceError(
            f"request-type drift — the registry derives buckets "
            f"{sorted(buckets)}, the frame carries {sorted(frame_buckets)}")


def _check_applicant_vs_total(entry: dict, frame) -> None:
    """Re-sum the applicant / on-transfer / total split the decision records.

    The whole point of the decision is that two published sub-totals both
    describe "requests received", so if the ingest ever silently switched
    columns the site's headline volume would move while the decision text still
    explained the old one."""
    required = ("check_fy", "check_applicant", "check_on_transfer", "check_total")
    missing = [k for k in required if not entry.get(k)]
    if missing:
        raise ProvenanceError(
            f"decision {entry['id']!r}: frame_check applicant_vs_total needs "
            f"{missing}")
    try:
        claimed = {k: int(entry[k]) for k in required[1:]}
    except ValueError:
        raise ProvenanceError(
            f"decision {entry['id']!r}: applicant_vs_total check values must be "
            f"whole numbers, got "
            f"{[entry[k] for k in required[1:]]}")
    fy = entry["check_fy"]

    def total_for(measure: str) -> int:
        return round(sum(f["value"] for f in frame.facts
                         if f["fy"] == fy and f["quarter"] is None
                         and f["measure"] == measure and f["bucket"] == "total"))

    for key, measure in (("check_applicant", "received"),
                         ("check_on_transfer", "received_transfer")):
        measured = total_for(measure)
        if claimed[key] != measured:
            raise ProvenanceError(
                f"decision {entry['id']!r}: claims {key} = {claimed[key]} for "
                f"{fy}, the frame sums {measure} to {measured}")
    if claimed["check_applicant"] + claimed["check_on_transfer"] != claimed["check_total"]:
        raise ProvenanceError(
            f"decision {entry['id']!r}: {claimed['check_applicant']} + "
            f"{claimed['check_on_transfer']} does not equal "
            f"{claimed['check_total']}")


_FRAME_CHECKS = {"applicant_vs_total": _check_applicant_vs_total}


def _check_decisions(decisions: list[dict], frame) -> None:
    for entry in decisions:
        name = entry.get("frame_check")
        if not name:
            continue
        check = _FRAME_CHECKS.get(name)
        if check is None:
            raise ProvenanceError(
                f"decision {entry['id']!r}: unknown frame_check {name!r} — "
                f"known checks are {sorted(_FRAME_CHECKS)}")
        check(entry, frame)


def validate_registry(frame) -> None:
    """Cross-check the curated registry against reality. Raises on any drift.
    On success, stashes the registry it accepted for `describe` to serve.

    WHAT IT CHECKS:
      - every source that claims `ingested_as` names a file that exists, and
        that file's sha256 (and byte count, where claimed) matches the registry
      - every financial year the frame carries is covered by some INGESTED
        source, and no ingested source claims a year the frame does not carry.
        A reference source's `covers` is documentation and does not count, so a
        deleted workbook entry cannot hide behind one.
      - every measure the frame carries is derived by exactly one derivation,
        and every derived measure is still in the frame; likewise the buckets
      - any `frame_check` a decision declares runs and agrees with the frame;
        an unrecognised check name is an error, never a skip

    WHAT IT DELIBERATELY DOES NOT CHECK:
      - that the registry lists every file `normalise_all` reads. The normaliser
        does not expose its file list, so this is checked indirectly: each
        workbook supplies exactly one financial year, so an unregistered new
        workbook fails the coverage check, and a removed workbook fails the
        `ingested_as` existence check.
      - the URLs. Boot must not depend on the network, and a government service
        that refused to start because data.gov.au was slow would be a worse
        failure than the one it prevents. The URLs were verified live when the
        entries were written and the date is recorded on each.
      - the eight golden Q1 figures. `Frame.golden_check` already gates them
        against `config.GOLDEN_Q1_FIGURES`; restating them here would create a
        second copy to drift.
      - the prose. It is curated text; a human wrote it and a human maintains
        it. What this function guarantees is that the numbers and file
        identities beside it are still true.
    """
    global _VALIDATED
    registry = load_registry()
    _check_sources(registry["sources"], frame)
    _check_derivations(registry["derivations"], frame)
    _check_decisions(registry["decisions"], frame)
    # Only on success, and only after every check: this is the copy describe()
    # serves, so a registry that failed anything above must not land here.
    _VALIDATED = registry


def _validated_registry(frame) -> dict:
    """The registry as `validate_registry` last accepted it — never a fresh
    parse. Returns a copy, so a caller mutating the payload cannot edit the
    validated original.

    BEFORE ANY VALIDATION HAS RUN, THIS VALIDATES ON DEMAND rather than raising.
    The choice is between two ways of not serving unvalidated content, and the
    third option — serving it — is not on the table. Raising would be the
    louder read, but `describe` is always handed a frame, which is the only
    thing `validate_registry` needs, so refusing to answer a question it has
    everything it needs to answer correctly buys no safety: the gate runs
    either way, and a drift raises ProvenanceError from here exactly as it does
    from boot. It also keeps every non-server caller honest — the DSL op, the
    chat report, a test holding a real frame — instead of making validation a
    thing only `server.app._boot` remembers to do.

    In the service this branch is dead: `_boot` validates before `_FRAME` is
    cached and before a route can be served, so by the time any request reaches
    `describe` the stash is already filled.

    THE LIMIT, STATED. The stash records that this registry CONTENT passed
    against a frame in this process; it does not record which frame. In the
    service there is one frame and boot validates it. A process that validated
    against one frame and then called `describe` with a different one would get
    the earlier verdict, which is why nothing here re-derives a frame of its
    own — the caller's frame and the validated frame are the same object by
    construction in `server.app`.
    """
    if _VALIDATED is None:
        validate_registry(frame)
    return {file_kind: list(entries) for file_kind, entries in _VALIDATED.items()}


# ------------------------------------------------------- the live figure ----

def _fy_phrase(financial_years: list[str]) -> str:
    """The financial-year span of a basis, in words — a RANGE only when the
    years really are contiguous.

    "2019-20 to 2025-26" asserts every year in between, and the old version
    asserted it from nothing but first-and-last of a set. `_figure_source_rows`
    documents the case that falsifies it: a figure's basis can carry a hole (an
    FY present only in non-total buckets, or only for non-reporting agencies, or
    a partial-measure ingest) while the chart's category axis still shows the
    year. Measured 2026-08-27 on the real frame, all thirteen figure bases run
    2019-20..2025-26 unbroken (or a single 2024-25 for the four top_n keys), so
    the list branch is inert today — which is when a guard is cheap to add.

    A year label the frame cannot supply as `YYYY-YY` falls to the list branch
    too: enumerating is never wrong, only longer.
    """
    if not financial_years:
        return "no financial year"
    if len(financial_years) == 1:
        return f"financial year {financial_years[0]}"
    starts = []
    for fy in financial_years:
        head = fy[:4]
        starts.append(int(head) if head.isdigit() else None)
    contiguous = all(a is not None and b is not None and b - a == 1
                     for a, b in zip(starts, starts[1:]))
    if contiguous:
        return f"financial years {financial_years[0]} to {financial_years[-1]}"
    return "financial years " + ", ".join(financial_years)


def _default_view_sentence(spec, financial_years: list[str],
                           buckets: list[str]) -> str:
    """The scope of a chart figure's basis, in words.

    "no portfolio filter", not "every portfolio": measured 2026-08-27, 85 of
    requests_received_trend's 2,022 basis rows carry no portfolio at all (2,295
    of the frame's 54,594 annual rows do, for the reason `portfolio-capture` in
    derivations.md records — each sheet's first banner sits above the row the
    parser starts from). "Every portfolio" would claim a completeness the rows
    do not have; what is true is that nothing was filtered out by portfolio.

    A top_n basis says what it is. `received_top20` consumes 303 rows and ranks
    303 agencies to draw 20 of them, so "every reporting agency" beside a chart
    captioned "Top 20" reads as a contradiction unless the sentence separates
    the ranking basis from what is drawn.
    """
    types = " and ".join(buckets) if buckets else "no request type"
    scope = (f"every reporting agency, no portfolio filter, request type "
             f"{types}, {_fy_phrase(financial_years)}")
    if spec and spec.get("kind") == "top_n":
        return (f"{scope} — the count and hash cover that whole ranking basis, "
                f"of which the chart draws the top {spec['n']}")
    return scope


_APPLIES_TO_PROSE = {"default_view": "the default view"}


def _shipped_figure_keys() -> frozenset:
    """The figure keys some page actually ships into `window.__pageData.figures`
    — the only keys a reader has a filter control for.

    NOT `FIG_KEYS`. Measured 2026-08-27, three of the thirteen catalog figure
    keys (`refused_pct_trend`, `agency_contributions_received`,
    `agency_contributions_decided`) are in no page's `PAGE_FIGURE_KEYS` and
    appear in no rendered page, so no filter re-derives them; they are reachable
    only through the model-driven `provenance` op in `stats.dsl`. Telling a
    reader of one of those answers that "any filter you set re-derives the chart
    in the browser" points at a control that does not exist — the same defect
    class as promising a filter to a server-rendered stat, in the opposite
    direction.

    Imported lazily and deliberately NOT cached. Lazily because `site.pages`
    only resolves as `site.*` once `site_shim.install()` has run (CPython
    freezes the stdlib `site`), and `import provenance` must not acquire that
    ordering constraint — `server.app` installs the shim first, but `stats.dsl`
    and `agentic.report` import this module too. Not cached because
    PAGE_FIGURE_KEYS is the single statement of what a page ships, and a stale
    copy taken at import time is exactly the drift this module exists to stop.
    """
    from site.pages import PAGE_FIGURE_KEYS
    return frozenset(k for keys in PAGE_FIGURE_KEYS.values() for k in keys)


def _qualifier(applies_to: str, template: str) -> str:
    """The ONLY constructor of a `qualifier`, and it cannot build one that does
    not name the view the count and hash describe.

    Structural, not incidental. Three classes of key need three different
    sentences, and before this the three happened to contain the words "default
    view" for three unrelated reasons — one said "the default view of <key>",
    another said "the page's default view", and a guard asserting the substring
    passed on all three by coincidence. Any rewording could have dropped the
    view from one class silently, and the guard would still have been green:
    the same shape of defect (a check passing for a reason other than the one
    it was written for) as the ones this feature exists to prevent.

    So the view is not written into any of the three sentences. Each passes a
    template with a `{view}` placeholder, this function refuses a template
    without one, and the words come from `applies_to` — the machine-readable
    field the same payload carries. The sentence a reader sees and the field a
    machine reads cannot disagree, because there is one source for both.

    Substitution is `replace`, not `format`, so that a brace anywhere else in a
    template is copied through as a brace rather than read as a field name.

    The earlier justification named "agency names" as the exposure, and that is
    wrong: no agency name reaches a template. Measured 2026-08-27, what
    `_live_layer` interpolates is the catalog key, the bucket names and
    financial-year labels taken off the figure's own source rows, `spec['n']`
    for a top_n, and — where `_BASIS_PROSE` has no entry — the raw basis token.
    Every one of those is fixed by code today (the normaliser writes the bucket
    and FY strings from literals, the keys and `n` are catalog constants), so
    there is no live path by which a published value carries a brace.

    It stays `replace` anyway, because the property worth having is about the
    NEXT template, not this one. Every template here is an f-string built over
    measured text; the day one of them interpolates something less controlled,
    `format` would turn a stray brace into a KeyError and a provenance answer
    into a 500, while `replace` degrades it to a literal brace a reader can see.
    A test holds this, because the swap is otherwise invisible: with `format`
    substituted in, every other test in the suite still passes.
    """
    view = _APPLIES_TO_PROSE.get(applies_to)
    if view is None:
        raise ProvenanceError(
            f"no wording for applies_to {applies_to!r} — a row count and a hash "
            f"that cannot say which view they describe must not be published")
    if "{view}" not in template:
        raise ProvenanceError(
            "refusing to build a qualifier that does not name the view it "
            "describes — that is the one thing a qualifier is for")
    return template.replace("{view}", view)


def _live_layer(frame, key: str) -> dict:
    """The measured basis behind one figure or stat, as the SERVER computed it.

    Raises KeyError for a key the catalog does not know (foi_stats owns that
    contract), so an unknown key can never come back as an empty-looking answer.

    `applies_to` is always "default_view". The QUALIFIER is not always the same
    sentence, because the four classes of key are not true of the same things —
    see the module docstring for the class split and the evidence behind it. In
    short: a chart a page ships really is re-derived in the browser under the
    reader's filter, so its basis has to be labelled as the default view; a
    figure NO page ships has no filter control at all, so it may not be offered
    one; a stat is server-rendered HTML the filters never touch, so promising a
    reader they can re-derive it is an invitation to a path that does not exist;
    and a transcribed Q1 figure's one load-bearing provenance fact is that it
    was read off the OAIC's dashboard rather than computed, which no filter
    caveat says.

    The MEASURED DETAIL and the SENTENCE split on different predicates, on
    purpose. Every catalog figure key gets the full measured `default_view`
    (years, buckets, measures, agency count) because `report._registry_rows`
    marks which workbooks feed the figure from those fields, and without them it
    falls back to an unmarked list of all seven — the over-claim it exists to
    prevent. Only the closing clause of the sentence dispatches on whether a
    page ships the key, because that is what decides whether a filter exists.

    What all four DO share is enforced rather than repeated: every one goes
    through `_qualifier`, which will not emit a sentence that does not name the
    view, and takes the wording of that view from this layer's own `applies_to`.
    Four sentences, one guarantee, and no way to reword a class out of it.
    """
    stat = foi_stats(frame, key)
    spec = FIGURE_SPECS.get(key)
    layer = {"key": key,
             "caption": FIG_CAPTIONS.get(key, ""),
             "kind": spec["kind"] if spec else "stat",
             "basis": stat["basis"],
             "source_rows": stat["source_rows"],
             "rows_hash": stat["rows_hash"],
             "applies_to": "default_view"}
    if key in FIG_KEYS:
        rows = _figure_source_rows(frame, key)
        financial_years = sorted({f["fy"] for f in rows})
        buckets = sorted({f["bucket"] for f in rows})
        layer["default_view"] = {
            "basis": stat["basis"],
            "financial_years": financial_years,
            "buckets": buckets,
            "measures": sorted({f["measure"] for f in rows}),
            # across the whole basis, not per year — a trend's basis spans seven
            # files, so this is the number of distinct names that appear in any
            # of them, not the number reporting in one year. Measured 2026-08-27:
            # 433 over the seven-year trends, 303 over the one-year top_n bases.
            # The reader sees this number in report._figure_rows as "across N
            # reporting agencies", so when it spans more than one year the
            # qualifier below says what N counts; a comment here does not reach
            # anyone reading the answer.
            "distinct_agencies": len({f["agency_name"] for f in rows}),
        }
        multi_year = "" if len(financial_years) < 2 else (
            " The agency count is the number of distinct agency names appearing "
            "anywhere in that basis, not the number reporting in any one year.")
        if key in _shipped_figure_keys():
            # A page ships this key into window.__pageData.figures, so the
            # reader really does have a filter that re-draws it client-side.
            filters = (" Any filter a reader sets re-derives the chart in the "
                       "browser from the same published facts, so this basis "
                       "describes {view} and not a filtered one.")
        else:
            # No page ships it, so there is no filter control to point at.
            #
            # The sentence claims only that, and deliberately does NOT say "this
            # chart is on no page of the site". Measured 2026-08-27,
            # agency_contributions_received is spec-identical to received_top20
            # and agency_contributions_decided to decided_top20 (same kind,
            # measure, n and default_fy; same rows_hash), and those two ARE
            # drawn, on key-agency-contributions-received and -decided. A reader
            # told "not on any page" who then finds what looks like the same
            # chart has been misled about a smaller thing than the one this
            # branch fixes. Only refused_pct_trend is drawn nowhere.
            filters = (" No page of this site ships this figure to a browser, "
                       "so no filter re-derives it; the basis above is the one "
                       "the server computed for this answer.")
        layer["qualifier"] = _qualifier(layer["applies_to"], (
            f"This row count and hash describe {{view}} of {key} as the server "
            f"computed it: "
            f"{_default_view_sentence(spec, financial_years, buckets)}."
            f"{multi_year}{filters}"))
    elif stat["basis"] == "single_quarter":
        # The transcribed Q1 2025-26 headline figures, recognised by the basis
        # ENUM so there is no second list of eight key names to drift.
        # pages._source_for_basis reaches the same eight tiles, but NOT by the
        # same rule — it matches a substring of a display label. See the module
        # docstring; a test pins the two predicates against each other.
        layer["default_view"] = {"basis": stat["basis"]}
        # "rests on values transcribed", not "is transcribed": measured
        # 2026-08-27, four of the eight keys ARE the published count (1 source
        # row) and four are one published count as a percentage of another (2
        # source rows, the only arithmetic being the division). Saying "this
        # figure is transcribed" would be false for those four, and the whole
        # point of this branch is to stop saying something weaker and less true
        # than the page already says.
        #
        # WHAT THE BOOT CHECK ACTUALLY COMPARES, because a reader will take the
        # sentence at face value. Frame.golden_check re-sums the frame's
        # fy=2025-26 / quarter=1 / bucket=total rows per measure and compares
        # each total to config.GOLDEN_Q1_FIGURES. Those rows are emitted FROM
        # GOLDEN_Q1_FIGURES by normalise._golden_q1_facts — one _fact per
        # constant, value = the constant — so both sides of the comparison are
        # the same eight numbers.
        #
        # It is a real gate, and worth stating truthfully rather than deleting.
        # It catches: a dropped or partial emission (the slice sums to 0);
        # fy/quarter/bucket stamping that moves a row out of the window it is
        # looked up in; a collision in _GOLDEN_MEASURE, where two golden keys
        # map to one measure and the slice doubles; any value transformation
        # between the constant and the fact; and contamination of the window by
        # some other ingest landing rows in fy=2025-26 quarter=1. It does NOT
        # catch a mistyped constant, because the constants are both sides. And
        # it compares nothing against anything the OAIC publishes: the boot path
        # makes no network call at all.
        #
        # An earlier wording here said "re-sums those rows against the published
        # figures" two sentences after naming the OAIC dashboard, which a
        # member of the public reads as a per-boot re-verification against the
        # OAIC. server/app.py had already caught and corrected that same
        # overstatement in its own docstring (see _boot, "the old wording here
        # ... overstated it"); this round reintroduced it in reader-facing
        # prose, on the eight keys the round existed to make honest.
        #
        # It cites no registry ids either. Measured 2026-08-27 across all 25
        # reader-visible rows of a decided_q1 answer, `oaic-dashboard` and
        # `golden-q1-transcription` appeared in exactly one row — this qualifier
        # itself. report._registry_rows prints titles, urls and dates, never
        # ids, so naming them told a reader to look for labels not on the page.
        # The entries are described by how they render instead, and not by
        # quoting their curated titles, which would put a second copy of curated
        # text here to drift from the registry.
        layer["qualifier"] = _qualifier(layer["applies_to"], (
            "This figure rests on values transcribed from the OAIC's own "
            "published FOI dashboard, not computed from the workbooks: the "
            "current workbook reports July to March cumulatively, so a single "
            "quarter cannot be recovered from it. Its row count says how many "
            "transcribed values it uses — one where the figure is a published "
            "count, two where it is one published count as a percentage of "
            "another. The transcription was read off the dashboard once, by a "
            "person. The OAIC dashboard is listed as a reference source below, "
            "and the decision to transcribe these eight figures sits among the "
            "curation decisions with the date it was made. Every start of this "
            "service re-sums those rows against the eight values written down "
            "in its own configuration and will not serve a page if they "
            "disagree, so a break in the transcription path stops the service "
            "rather than reaching a reader. That check is against this "
            "service's own record of what was transcribed, not against the "
            "OAIC: nothing here re-reads the dashboard. The tile is rendered by "
            "the server: the filters apply to the charts below it, so {view}, "
            "which is what this count and hash describe, is the only view of it "
            "there is."))
    else:
        layer["default_view"] = {"basis": stat["basis"]}
        layer["qualifier"] = _qualifier(layer["applies_to"], (
            f"This row count and hash describe {{view}} of {key} as the server "
            f"computed it, on a "
            f"{_BASIS_PROSE.get(stat['basis'], stat['basis'])} basis. The "
            f"server works this out and renders the result into the page as it "
            f"stands; the filters on a chart page re-derive the chart and not "
            f"this, so {{view}} is the only view of it there is."))
    return layer


def describe(frame, dataset=None, key=None) -> dict:
    """The layered provenance payload.

    Always: the curated registry, in full — sources, derivations, decisions.
    With `dataset`: the caller's measured `foi_datasets` snapshot, passed
    through unchanged (this module does not query the durable store; the caller
    that has a connection reads it and hands it over).
    With `key`: the live layer for that figure or stat, measured from this
    frame. An unknown key raises KeyError.

    The registry half comes from `_validated_registry`, never a fresh
    `load_registry`: a reader is served the content `validate_registry`
    accepted, not whatever is on disk at request time.
    """
    out = _validated_registry(frame)
    if dataset is not None:
        out["dataset"] = dataset
    if key is not None:
        out["figure"] = _live_layer(frame, key)
    return out
