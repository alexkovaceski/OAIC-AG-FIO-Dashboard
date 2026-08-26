"""provenance — the curated registry, its parser, and the live figure layer.

The premise (spec S3.5): a reader asks where a number came from and gets the
dataset, the files, the hashes, the curation decisions, and for a named figure
the row basis behind it. Nothing in that answer is generated. Every value is
either curated text a human wrote into `data/corpus/provenance/*.md`, or a
number measured from the frame at answer time.

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

WHAT THE LIVE LAYER MAY AND MAY NOT SAY. Each chart page ships the whole
`foi_stats` result for its figures into `window.__pageData.figures[key]`,
including `source_rows` and `rows_hash`, while shipping facts for EVERY
financial year; the chart engine then re-derives the chart in the browser for
whatever filter the reader picks. So the hash that travels with a figure
describes the DEFAULT view and not the one a filtered reader is looking at.
`_live_layer` therefore labels its basis explicitly (`applies_to:
"default_view"`) and carries a `qualifier` sentence saying so, plus a
`default_view` block measured from the basis rows themselves rather than
asserted. It does NOT attempt to recompute a basis for a client-side filter
state: the server never sees that state, and a count derived from a state it
cannot observe would be the same class of false claim in a new place.
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

    Not cached. The three files are small, and re-reading them means an operator
    who corrects a typo sees it without a restart. The gate that matters —
    validate_registry — runs at boot.
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
    registry = load_registry()
    _check_sources(registry["sources"], frame)
    _check_derivations(registry["derivations"], frame)
    _check_decisions(registry["decisions"], frame)


# ------------------------------------------------------- the live figure ----

def _default_view_sentence(financial_years: list[str], buckets: list[str]) -> str:
    if len(financial_years) == 1:
        years = f"financial year {financial_years[0]}"
    elif financial_years:
        years = f"financial years {financial_years[0]} to {financial_years[-1]}"
    else:
        years = "no financial year"
    types = " and ".join(buckets) if buckets else "no request type"
    return (f"every reporting agency, every portfolio, request type {types}, "
            f"{years}")


def _live_layer(frame, key: str) -> dict:
    """The measured basis behind one figure or stat, as the SERVER computed it.

    Raises KeyError for a key the catalog does not know (foi_stats owns that
    contract), so an unknown key can never come back as an empty-looking answer.

    `applies_to` is always "default_view" and `qualifier` says so in words. See
    the module docstring: the chart engine re-derives on the client for the
    reader's filter selection, and this basis does not describe that view.
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
            # of them, not the number reporting in one year
            "distinct_agencies": len({f["agency_name"] for f in rows}),
        }
        layer["qualifier"] = (
            f"This row count and hash describe the default view of {key} as the "
            f"server computed it: "
            f"{_default_view_sentence(financial_years, buckets)}. Any filter a "
            f"reader sets re-derives the chart in the browser from the same "
            f"published facts, so this basis describes the default view and not "
            f"a filtered one.")
    else:
        layer["default_view"] = {"basis": stat["basis"]}
        layer["qualifier"] = (
            f"This row count and hash describe {key} as the server computed it "
            f"for the default, unfiltered view, on a {stat['basis']} basis. Any "
            f"filter a reader sets re-derives what is drawn from the same "
            f"published facts, so this basis describes the default view and not "
            f"a filtered one.")
    return layer


def describe(frame, dataset=None, key=None) -> dict:
    """The layered provenance payload.

    Always: the curated registry, in full — sources, derivations, decisions.
    With `dataset`: the caller's measured `foi_datasets` snapshot, passed
    through unchanged (this module does not query the durable store; the caller
    that has a connection reads it and hands it over).
    With `key`: the live layer for that figure or stat, measured from this
    frame. An unknown key raises KeyError.
    """
    out = load_registry()
    if dataset is not None:
        out["dataset"] = dataset
    if key is not None:
        out["figure"] = _live_layer(frame, key)
    return out
