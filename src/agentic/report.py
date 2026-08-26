"""agentic.report — the reporting engine.

A natural-language request maps to a catalog stat (deterministic keyword
router), and the platform computes the figure. The model never writes a
digit: the router only selects a stat key; the number comes from the Frame.
This is the same "model emits structure, platform computes numbers"
discipline as the /ask builder. An unmappable request escalates to the email
redirect. Router order matters: more specific patterns (refusal rate, top
agencies by decided) come BEFORE the general ones (refus, decided) they would
otherwise shadow.

PROVENANCE IS THE FIRST ROUTE. "Where did this data come from" is a question
ABOUT a figure, not a request for one, so its pattern sits at index 0 of
_ROUTER. Every other entry would otherwise shadow it: "where does the
timeliness data come from" matches `timeliness|slippage` and would have come
back as the slippage correlation, and "where did the top 20 agencies chart come
from" would have come back as the chart. Once provenance matches, the remaining
router entries are re-run over the same request to work out WHICH figure is
being asked about, so the answer carries that figure's measured basis; no match
there means the reader is asking about the data as a whole and gets the
registry alone.

Nothing in a provenance answer is generated. Every value is either curated text
a human wrote into data/corpus/provenance/*.md or a number measured from the
frame — see provenance.describe.
"""
from __future__ import annotations
import re

from provenance import ProvenanceError, describe
from stats.catalog import foi_stats
from agentic.guardrails import check_request, ScopeRefusal

_ESCALATION = ("That request is beyond what the site can compute. For a "
               "custom FOI report, email contact@bluebirdadvisory.com.au.")

# The sentinel _ROUTER entry for "this is a question about where a figure came
# from". Not a stat key: it selects the provenance answer, and the figure it is
# about is resolved by a second pass over the stat patterns below it.
_PROVENANCE = "provenance"

# Provenance INTENT. Deliberately narrower than a bare `where.*from`: "where
# were the most requests received from?" is a question about agencies, so the
# phrase has to be "come/comes/came from" (or an explicit provenance word) to
# select this route.
_PROVENANCE_RE = re.compile(
    r"provenance|lineage|"
    r"where\b.*\b(?:come|comes|came)\s+from\b|"
    r"where\b.*\b(?:sourced|originate[sd]?)\b|"
    r"source of|sources? for|"
    r"which (?:file|workbook|spreadsheet|sheet|source)|"
    r"how do (?:you|we) know|"
    r"how (?:was|were|is|are)\b.*\b(?:derived|calculated|compiled)\b",
    re.I)
# ...and a SUBJECT the site actually holds. Provenance wording is ordinary
# English ("where did the pyramids come from"), so intent alone is not enough to
# claim a question is about this platform's data. This mirrors the positive
# in-scope signal guardrails.check_request applies, one layer further in: the
# scope screen is what refuses an out-of-scope request, and this is what stops
# an in-scope-sounding one from being answered with FOI lineage it never asked
# for.
_PROVENANCE_SUBJECT_RE = re.compile(
    r"\b(?:data|dataset|datasets|figure|figures|number|numbers|stat|stats|"
    r"statistic|statistics|chart|charts|graph|graphs|series|count|counts|"
    r"total|totals|percentage|share|rate|workbook|spreadsheet|file|files|"
    r"source|sources|foi|freedom of information|request|requests|received|"
    r"finalis\w*|decided|decision|decisions|refus\w*|granted|withdrawn|"
    r"timeliness|statutory|agency|agencies|portfolio|portfolios)\b", re.I)

_ROUTER: list[tuple[re.Pattern, str]] = [
    # FIRST: a question about a figure, not a request for one (see the module
    # docstring). Gated by _PROVENANCE_SUBJECT_RE in build_report.
    (_PROVENANCE_RE, _PROVENANCE),
    (re.compile(r"refusal rate", re.I), "refusal_rate_change_fy23_fy24"),
    (re.compile(r"within statutory|statutory", re.I), "within_statutory_pct_q1"),
    (re.compile(r"granted in full|full grant", re.I), "granted_full_share_q1"),
    (re.compile(r"granted in part|part grant", re.I), "granted_part_share_q1"),
    (re.compile(r"withdrawn", re.I), "withdrawn_q1"),
    (re.compile(r"top (?:20 )?agenc.*decid|decid.*top (?:20 )?agenc", re.I),
     "decided_top20"),
    (re.compile(r"top (?:20 )?agenc|agenc.*top|contribut", re.I), "received_top20"),
    (re.compile(r"received", re.I), "requests_received_q1"),
    (re.compile(r"finalis", re.I), "requests_finalised_q1"),
    (re.compile(r"refus", re.I), "refused_share_q1"),
    (re.compile(r"timeliness|slippage", re.I), "timeliness_slippage_corr"),
    (re.compile(r"decided?|decision", re.I), "decided_q1"),
]

_LABELS = {
    "requests_received_q1": "Requests received, Q1 2025-26",
    "requests_finalised_q1": "Requests finalised, Q1 2025-26",
    "decided_q1": "Requests decided, Q1 2025-26",
    "within_statutory_pct_q1": "Decisions within the statutory time period",
    "granted_full_share_q1": "Share of decisions granted in full",
    "granted_part_share_q1": "Share of decisions granted in part",
    "refused_share_q1": "Share of decisions refused",
    "withdrawn_q1": "Share of decisions withdrawn",
    "refusal_rate_change_fy23_fy24": "Refusal rate, FY23 vs FY24 top movers",
    "timeliness_slippage_corr": "Timeliness slippage correlation",
    "received_top20": "Top 20 agencies by requests received, FY 2024-25",
    "decided_top20": "Top 20 agencies by requests decided, FY 2024-25",
}


# ------------------------------------------------------- provenance answer ---

def _qualified_basis(count_detail: str, source_rows, rows_hash,
                     qualifier: str) -> tuple[list[dict], dict]:
    """(reader-visible rows, dataset_registry) for a provenance answer's basis.

    THE ONLY constructor of a provenance dataset_registry that carries
    source_rows / rows_hash, and it refuses to build one without a qualifier.

    Why the refusal is the point: each chart page ships facts for EVERY
    financial year and the chart engine re-derives in the browser for whatever
    filter the reader picked, so a row count and a hash the server computed
    describe the DEFAULT view and not necessarily the one on screen. A count and
    a hash with no statement of which view they describe is a false claim
    wearing an official-looking hash — on the one feature whose whole job is
    being trustworthy.

    Returning the rows and the registry TOGETHER is the structural half of the
    guarantee: a caller cannot obtain the count and the hash without also
    obtaining the sentence that says what they describe, and the rows are what
    site/assets/report.js prints. The test half is
    test_provenance_answer_never_quotes_a_row_count_without_the_qualifier.
    """
    if not (qualifier or "").strip():
        raise ValueError(
            "refusing to publish source_rows/rows_hash with no qualifier — a "
            "row count and a hash must say which view they describe")
    rows = [{"part": "What it is drawn from", "detail": count_detail}]
    if rows_hash:
        rows.append({"part": "Row hash", "detail": rows_hash})
    rows.append({"part": "Scope of that row count and hash", "detail": qualifier})
    return rows, {"source_rows": source_rows, "rows_hash": rows_hash,
                  "qualifier": qualifier}


def _figure_label(figure: dict) -> str:
    """What to call a figure in front of a reader. FIG_CAPTIONS covers the
    charts; a KPI stat has no caption, so fall back to the router's own label
    before the bare key — "Where timeliness_slippage_corr comes from" is a
    heading written for a database, not for a reader."""
    return (figure["caption"]
            or _LABELS.get(figure["key"], figure["key"].replace("_", " ")))


def _registry_rows(registry: dict, view: dict | None = None) -> list[dict]:
    """The curated registry as reader-visible rows. Every `detail` below is
    curated text read out of data/corpus/provenance/*.md — the composition is
    punctuation, never a claim.

    `view` is a figure's measured default_view, when the reader asked about one.
    Without it every source and derivation is listed flat. With it, each is
    marked according to whether it actually feeds THAT figure: the platform
    ingests seven workbooks, and a top-N chart drawn on one financial year is
    fed by one of them. An unmarked list of seven files under the heading "where
    this chart comes from" reads as a claim that the chart used all seven.

    The marking is measured, not asserted: `covers` and `measures` are curated
    keys that validate_registry already cross-checks against the frame, and
    financial_years / measures in `view` come from the figure's own source rows.
    A stat whose live layer carries no year or measure breakdown gets the flat
    list, because there is nothing measured to mark it with.
    """
    years = set(view.get("financial_years") or ()) if view else set()
    measures = set(view.get("measures") or ()) if view else set()
    rows: list[dict] = []
    for source in registry["sources"]:
        if not source.get("ingested_as"):
            rows.append({"part": "Reference", "detail":
                         f"{source['title']} — {source['url']}"})
            continue
        part = "Source file"
        if years:
            part += (" (this figure)" if years & set(source["covers"])
                     else " (other years)")
        rows.append({"part": part, "detail":
                     f"{source['title']} — covers "
                     f"{', '.join(source['covers'])}; read from "
                     f"{source['ingested_as']}; sha256 {source['sha256']}; "
                     f"{source['url']}"})
    for entry in registry["derivations"]:
        part = "Derivation"
        if entry["kind"] == "sheet":
            detail = (f"{entry['title']} — the '{entry['sheet']}' sheet supplies "
                      f"{', '.join(entry['measures'])}")
            if measures:
                part += (" (this figure)" if measures & set(entry["measures"])
                         else " (other measures)")
        else:
            detail = entry["title"]
        rows.append({"part": part, "detail": detail})
    for entry in registry["decisions"]:
        rows.append({"part": "Curation decision",
                     "detail": f"{entry['title']} (recorded {entry['date']})"})
    return rows


def _figure_rows(figure: dict) -> tuple[list[dict], dict]:
    """The measured basis behind one named figure, as rows + dataset_registry."""
    view = figure["default_view"]
    shape = "statistic" if figure["kind"] == "stat" else f"{figure['kind']} chart"
    head = [{"part": "Figure", "detail":
             f"{_figure_label(figure)} ({figure['key']}) — a {shape} on a "
             f"{figure['basis']} basis"}]
    if "financial_years" in view:
        years = ", ".join(view["financial_years"])
        count_detail = (
            f"{figure['source_rows']} published fact rows: "
            f"{', '.join(view['measures'])} for request type "
            f"{', '.join(view['buckets'])}, financial year {years}, across "
            f"{view['distinct_agencies']} reporting agencies")
    else:
        count_detail = (f"{figure['source_rows']} published fact rows on a "
                        f"{view['basis']} basis")
    basis_rows, registry = _qualified_basis(
        count_detail, figure["source_rows"], figure["rows_hash"],
        figure["qualifier"])
    return head + basis_rows, registry


def _frame_rows(frame, registry: dict) -> tuple[list[dict], dict]:
    """The whole-frame basis, for a reader asking about the data in general.

    There is no single figure here, so there is no single figure's hash — and
    saying so is the qualifier. The per-workbook sha256s the reader actually
    wants are in the source rows beneath.

    The workbook count is counted off the registry rather than written down: a
    hardcoded "seven" is a claim that goes stale the day an eighth workbook is
    ingested, which is the exact failure this feature exists to prevent.
    """
    facts = len(frame.facts)
    workbooks = sum(1 for s in registry["sources"] if s.get("ingested_as"))
    return _qualified_basis(
        f"{facts:,} normalised fact rows, read from the source files below",
        facts, None,
        f"That count is every published fact this platform holds, across all "
        f"{workbooks} workbooks — it is not the basis of any one chart. A "
        f"chart's own row count and hash come with that chart, and describe "
        f"the default "
        "view of it: the pages ship facts for every financial year and re-derive "
        "in the browser when a reader sets a filter, so the server never "
        "computes a filtered basis. Ask about a named figure to get its.")


def _provenance_report(request: str, frame, key: str | None) -> dict:
    try:
        payload = describe(frame, key=key)
    except KeyError:
        # the catalog's "this frame cannot compute that key" signal — answer
        # about the data as a whole rather than 500 on the lineage question
        payload = describe(frame)
    figure = payload.get("figure")
    if figure is not None:
        # deliberately OUTSIDE the try above: a figure layer that arrived
        # without its qualifier must fail loud, not fall back to a generic
        # answer that would look like it worked
        rows, dataset_registry = _figure_rows(figure)
        label = f"Where {_figure_label(figure)} comes from"
        basis = figure["basis"]
        view = figure["default_view"]
    else:
        rows, dataset_registry = _frame_rows(frame, payload)
        label = "Where this data comes from"
        basis = None
        view = None
    return {"request": request, "stat_key": _PROVENANCE, "stat_label": label,
            "data": rows + _registry_rows(payload, view), "basis": basis,
            "dataset_registry": dataset_registry,
            # the whole layered payload, for a caller that wants the prose and
            # the key blocks rather than the reader-visible summary
            "provenance": payload,
            "model": "curated provenance registry + the platform frame (no "
                     "generated text)", "escalate": False}


# ------------------------------------------------------------ the router -----

def build_report(request: str, frame) -> dict:
    try:
        check_request(request)
    except ScopeRefusal as exc:
        return {"request": request, "stat_key": None, "stat_label": None,
                "data": None, "basis": None, "dataset_registry": {},
                "model": "scope", "escalate": True, "error": f"{exc} {_ESCALATION}"}
    key = None
    for pattern, stat_key in _ROUTER:
        if not pattern.search(request):
            continue
        if stat_key == _PROVENANCE and not _PROVENANCE_SUBJECT_RE.search(request):
            # provenance wording about something this platform does not hold
            # ("where do the top tourists come from") is not a provenance
            # question — keep looking, and escalate if nothing else matches
            continue
        key = stat_key
        break
    if key is None:
        return {"request": request, "stat_key": None, "stat_label": None,
                "data": None, "basis": None, "dataset_registry": {},
                "model": "no-match", "escalate": True, "error": _ESCALATION}
    if key == _PROVENANCE:
        # second pass over the stat patterns: which figure is the reader asking
        # about? None of them matching means "the data" as a whole.
        figure_key = next((k for p, k in _ROUTER[1:] if p.search(request)), None)
        try:
            return _provenance_report(request, frame, figure_key)
        except ProvenanceError as exc:
            # the registry drifted or became unreadable since boot validated it.
            # Refuse the lineage question outright — a partial answer beside a
            # broken registry is exactly the false claim this feature exists to
            # avoid.
            return {"request": request, "stat_key": None, "stat_label": None,
                    "data": None, "basis": None, "dataset_registry": {},
                    "model": "provenance-unavailable", "escalate": True,
                    "error": f"The provenance registry could not be read, so "
                             f"this site will not answer where its data came "
                             f"from ({exc}). {_ESCALATION}"}
    stat = foi_stats(frame, key)
    return {"request": request, "stat_key": key,
            "stat_label": _LABELS.get(key, key.replace("_", " ")),
            "data": stat["value"], "basis": stat["basis"],
            "dataset_registry": {"source_rows": stat["source_rows"],
                                 "rows_hash": stat["rows_hash"]},
            "model": "deterministic router (figures from the platform frame, "
                     "not the LLM)", "escalate": False}
