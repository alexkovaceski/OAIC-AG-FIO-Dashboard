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
being asked about, so the answer carries that figure's measured basis.

WHAT THE ROUTE MAY ANSWER IS BOUNDED BY WHAT THIS PLATFORM CAN CITE, not by a
list of words that sound in-scope. See _provenance_subject for the rule and for
the two earlier attempts it replaces.

Nothing in a provenance answer is generated. Every value is either curated text
a human wrote into data/corpus/provenance/*.md or a number measured from the
frame — see provenance.describe.
"""
from __future__ import annotations
import re

from provenance import ProvenanceError, describe
from stats.catalog import (FIG_CAPTIONS, FIG_KEYS, FIGURE_SPECS, STAT_KEYS,
                           foi_stats)
from agentic.guardrails import check_request, ScopeRefusal, _FOI_TERMS

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
_ROUTER: list[tuple[re.Pattern, str]] = [
    # FIRST: a question about a figure, not a request for one (see the module
    # docstring). Intent only — the SUBJECT is bounded by _provenance_subject,
    # which build_report consults before this entry may win.
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
    # NOT "FY23 vs FY24". Measured 2026-08-26 on the real frame, the stat
    # compares _previous_complete_fy(frame) = 2023-24 with LATEST_COMPLETE_FY =
    # 2024-25, so the old label named two years the figure does not use — and the
    # provenance route publishes this string as a heading ("Where <label> comes
    # from"), which turns a stale caption into a provenance claim. No years are
    # written here in their place: LATEST_COMPLETE_FY advances once a year and a
    # year literal in a label is the same defect again, one release later. The
    # years the figure actually used travel in its own value (fy_a / fy_b), and
    # site/pages.py already calls this table "Refusal rate, top movers".
    # `refusal_rate_change_fy23_fy24` is the catalog's own KEY and is not renamed
    # here; that is stats/catalog.py's to decide.
    "refusal_rate_change_fy23_fy24": "Refusal rate, top movers",
    "timeliness_slippage_corr": "Timeliness slippage correlation",
    "received_top20": "Top 20 agencies by requests received, FY 2024-25",
    "decided_top20": "Top 20 agencies by requests decided, FY 2024-25",
}


# --------------------------------------------- the bounded-subject gate ------
#
# THE RULE, in one paragraph. A provenance question is answered only when the
# platform can actually cite the thing it names. Two conditions, both required.
# (1) CLOSED VOCABULARY: every content word of the request — everything left
# after the provenance framing and ordinary function words are removed — must
# come from this platform's own vocabulary (_VOCABULARY below: the catalog's
# stat and figure keys, its captions, this router's labels, the measures and
# buckets in the frame, guardrails._FOI_TERMS, and a short list of shape nouns
# like "chart" and "figure"). Numbers must be a quantifier after "top" or a
# financial year the frame carries. One unknown word and the route declines.
# (2) A CITABLE SUBJECT: either the second pass over _ROUTER[1:] resolves a
# figure key — which, given (1), can only have matched platform vocabulary
# rather than a foreign word that happened to contain it — or the request names
# this platform's subject explicitly (_PLATFORM_SUBJECT_RE: "the FOI data", "the
# Australian Government FOI statistics", "this dashboard's data"). Neither means
# escalate; the fall-through to the whole-platform lineage is gone.
#
# WHY THIS IS NOT A THIRD WORD LIST. The two attempts this replaces both asked
# "does the request contain AT LEAST ONE word from list L?" — an existential
# test over an unbounded universe of subjects, which is why every list lost.
# Attempt 1 admitted `data`/`chart`/`total`; 7 of 12 off-topic phrasings came
# back as full FOI lineage. Attempt 2 narrowed L to FOI domain nouns and closed
# those 12, and then 29 more leaked, because a share PORTFOLIO, a travel AGENCY,
# pull REQUESTS and GRANTED liquor licences are ordinary English. The test here
# is UNIVERSAL, not existential: EVERY content word must be in the vocabulary.
# That inverts the failure mode. A word missing from the vocabulary can only
# cause an escalation, never an answer; a word wrongly added only admits requests
# in which every OTHER word is also this platform's. The set being screened is
# the request, which is finite, instead of the set of possible subjects, which is
# not.
#
# WHAT IT COSTS, STATED. A genuine question that uses a word the platform does
# not publish escalates to the email path — "where did last year's FOI data come
# from?" ("last"), "where did the Home Affairs FOI request numbers come from?"
# does answer ("home affairs" is in _FOI_TERMS) but a question naming an agency
# the vocabulary does not carry does not. That is the deliberate direction: this
# route's failure mode must be silence, not a table of seven Australian
# workbooks and seven sha256 hashes under a heading about somebody's share
# portfolio.

# Words that carry no subject: the provenance framing itself plus ordinary
# function words, all stripped before the vocabulary check. A word may be added
# here ONLY if it can never be what a question is ABOUT — that is the whole test.
# It is why "data", "chart" and "figure" are not here (they are shape nouns, and
# a shape noun is still checked), and why "last", "next", "current", "recent" and
# "future" are in neither this set nor the vocabulary: a question about a year
# this platform does not publish must not be answered as though it were about
# one it does.
_FRAME_WORDS = frozenset("""
a an the this that these those there here
where what which who whom whose when why how
is are was were be been being am do does did done
come comes came coming get gets got go goes went
from of for in on at to by with about into over under out up off
and or but nor so than then if as
i me my mine we us our ours you your yours they them their it its
he she his her him
has have had having can could would should will shall may might must
know knows knew tell tells told show shows showed say says said
give gives gave please just even also still ever
actually really exactly originally
provenance lineage origin origins source sources sourced sourcing
originate originates originated derive derives derived
calculate calculates calculated compile compiles compiled
based behind underlying used using
""".split())

# Domain-NEUTRAL nouns. These are the words attempt 1 was destroyed by, and they
# are safe here for a structural reason: under a universal test a shape noun
# admits nothing on its own. "where did the tourism data come from?" still fails
# on "tourism". What they buy is that a reader may say "chart", "figure" or
# "spreadsheet" about a figure this platform really does hold.
_SHAPE_WORDS = frozenset("""
data dataset datasets database
figure figures number numbers stat stats statistic statistics
chart charts graph graphs plot plots table tables tile tiles kpi kpis
series count counts total totals sum sums percentage percentages percent
share shares rate rates proportion proportions value values
workbook workbooks spreadsheet spreadsheets sheet sheets file files
column columns row rows record records field fields
page pages site dashboard platform service report reports
corpus registry breakdown summary
""".split())

# This platform's own subject, in the words a reader would use for it. "q1" and
# no other quarter: the eight transcribed headline figures are Q1 2025-26 and the
# workbooks report July-to-March cumulatively, so "the Q2 requests received
# figures" is a question about a quarter this platform cannot produce, and
# answering it with the Q1 figure's lineage is the false claim in a new place.
_PLATFORM_WORDS = frozenset("""
foi freedom information australian australia government commonwealth oaic
q1 applicant applicants transfer transferred transfers channel channels
""".split())

_LETTERS_RE = re.compile(r"[a-z]+")


def _derived_vocabulary() -> frozenset:
    """The platform's vocabulary, READ OFF the platform rather than written down.

    Catalog keys, chart captions, this router's own labels, the figure specs'
    measure names and guardrails' in-scope terms. Deriving it is what stops it
    drifting into a hand-maintained third word list: a new stat key or caption
    brings its own words, and nothing here has to be remembered.

    Digits are dropped (`[a-z]+`), so "received_top20" contributes "received"
    and "top" but not "20" — numbers are governed by their own rule in
    _out_of_vocabulary, which is where a year can be checked against coverage.
    """
    words: set[str] = set()
    for key in STAT_KEYS + FIG_KEYS:
        words.update(_LETTERS_RE.findall(key))
    for text in list(FIG_CAPTIONS.values()) + list(_LABELS.values()) + list(_FOI_TERMS):
        words.update(_LETTERS_RE.findall(text.lower()))
    for spec in FIGURE_SPECS.values():
        for field in ("measures", "numerators"):
            for measure in spec.get(field, ()):
                words.update(_LETTERS_RE.findall(measure))
        for field in ("measure", "denominator", "name"):
            if spec.get(field):
                words.update(_LETTERS_RE.findall(spec[field]))
    return frozenset(words)


_VOCABULARY = _derived_vocabulary() | _SHAPE_WORDS | _PLATFORM_WORDS

# Deixis is deliberately in NEITHER set. Named so a test can hold it there: the
# cheap way to "fix" an escalation on "where did last year's FOI data come from?"
# is to drop "last" into _FRAME_WORDS, and that silently re-opens the
# out-of-coverage class ("next year's FOI requests data") the gate was built to
# close.
_NEVER_ADMITTED = frozenset("""
last next previous prior current latest recent future upcoming coming
today yesterday tomorrow now soon
""".split())

# The whole-platform subject, enumerated. Not a bare noun: each alternative
# names THIS platform — its FOI subject, the OAIC, or the site itself. The
# closed-vocabulary check has already removed any foreign modifier by the time
# this runs ("the Irish FOI request data" never gets here), so this pattern's job
# is only to insist the reader named the platform's subject at all rather than
# some in-vocabulary phrase like "the top rate data".
_PLATFORM_SUBJECT_RE = re.compile(
    r"\b(?:(?:australian government|australian|commonwealth|oaic|agency|agencies)"
    r"\s+)?(?:foi|freedom of information)\s+"
    r"(?:requests?\s+|agency\s+|agencies\s+)?"
    r"(?:data|datasets?|statistics|stats|figures?|numbers?|corpus|records?"
    r"|series|dashboards?)\b"
    r"|\b(?:this|the)\s+(?:site|dashboard|platform|service)(?:'s)?\s+"
    r"(?:data|datasets?|statistics|stats|figures?|numbers?)\b"
    r"|\b(?:the\s+)?(?:oaic|australian government)(?:'s)?\s+"
    r"(?:data|datasets?|statistics|stats|figures?|numbers?)\b",
    re.I)

_FY_TOKEN_RE = re.compile(r"\b(?:19|20)\d{2}-\d{2}\b")
_WORD_RE = re.compile(r"[a-z0-9]+")
_POSSESSIVE_RE = re.compile(r"['’]s\b")


def _frame_vocabulary(frame) -> tuple[frozenset, frozenset, frozenset]:
    """(financial-year labels, bare years, measure/bucket words) from the frame.

    One pass over the facts. The years are what bounds a numeric token: 2024 and
    2024-25 are things this platform publishes, 1995 and 2005 are not, and a
    lineage answer about a year the frame does not carry is a claim about data
    that is not here.
    """
    fy_labels: set[str] = set()
    words: set[str] = set()
    for fact in frame.facts:
        fy_labels.add(fact["fy"])
        words.add(fact["measure"])
        words.add(fact["bucket"])
    years: set[str] = set()
    for label in fy_labels:
        head, _, tail = label.partition("-")
        if head.isdigit():
            years.add(head)
            if len(tail) == 2 and tail.isdigit():
                years.add(head[:2] + tail)
    tokens: set[str] = set()
    for word in words:
        tokens.update(_LETTERS_RE.findall(str(word).lower()))
    return frozenset(fy_labels), frozenset(years), frozenset(tokens)


def _known_word(word: str, extra: frozenset) -> bool:
    """Vocabulary membership, allowing the plural and participle a reader writes.

    One suffix, one lookup: "agencies" -> "agency", "decisions" -> "decision",
    "requesting" -> "request". It deliberately does not stem twice, so "ratings"
    reaches "rating" and stops rather than reaching "rat" — the credit-rating
    leak turned on exactly that word.
    """
    if word in _VOCABULARY or word in extra:
        return True
    for suffix, replacement in (("ies", "y"), ("es", ""), ("s", ""),
                                ("ed", ""), ("ing", "")):
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            stem = word[:-len(suffix)] + replacement
            if stem in _VOCABULARY or stem in extra:
                return True
    return False


def _out_of_vocabulary(request: str, frame) -> list[str]:
    """Every content word in `request` this platform does not publish.

    Empty means the request is written wholly in the platform's own vocabulary.
    Returned as a list rather than a bool so a caller — and a test — can say
    WHICH word declined the route.
    """
    fy_labels, years, frame_words = _frame_vocabulary(frame)
    text = _POSSESSIVE_RE.sub(" ", request.lower())
    stray = [fy for fy in _FY_TOKEN_RE.findall(text) if fy not in fy_labels]
    previous = ""
    for word in _WORD_RE.findall(_FY_TOKEN_RE.sub(" ", text)):
        if word in _FRAME_WORDS:
            previous = word
            continue
        if word.isdigit():
            # a quantifier ("top 20") or a year the frame carries; nothing else
            if not (previous == "top" or word in years):
                stray.append(word)
        elif not _known_word(word, frame_words):
            stray.append(word)
        previous = word
    return stray


def _provenance_subject(request: str, frame) -> tuple[bool, str | None]:
    """(answer it?, which figure) for a request carrying provenance wording.

    (False, None) means this platform cannot cite what the request names, and
    build_report keeps looking down the router — so the request gets whatever
    the ordinary stat patterns make of it, or the escalation, but never lineage.
    """
    if _out_of_vocabulary(request, frame):
        return False, None
    figure_key = next((k for p, k in _ROUTER[1:] if p.search(request)), None)
    if figure_key is not None:
        return True, figure_key
    if _PLATFORM_SUBJECT_RE.search(request):
        return True, None
    return False, None


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

    THE TRANSCRIBED Q1 FIGURES ARE MARKED FROM THEIR BASIS INSTEAD. All eight
    keys in config.GOLDEN_Q1_FIGURES are stats, so their live layer carries no
    year breakdown to mark sources with — and the site's eight most prominent
    numbers were each rendering a flat, unmarked list of every workbook and every
    sha256 under a heading like "Where Share of decisions withdrawn comes from".
    `withdrawn_q1` is one fact row, and it did not come from any of them. Their
    `single_quarter` basis says something stronger than "unknown": a
    single-quarter figure was read off the OAIC's published dashboard, because
    the current workbook reports July to March cumulatively and no quarter can be
    recovered from it. It marks the sheet derivations for the same reason it
    marks the workbooks, and leaves the convention derivations alone, which are
    true of a transcribed fact as of any other.

    WHAT THIS FUNCTION'S TEST ACTUALLY IS, because a previous version of this
    docstring claimed more. It compares the measured basis ENUM for exact
    equality: `view.get("basis") == "single_quarter"`. `provenance._live_layer`
    tests the same raw token the same way (inside an `elif` after `key in
    FIG_KEYS`). `site.pages._source_for_basis` does NOT: it tests for the
    substring "single quarter" — with a space — inside a DISPLAY label. The three
    agree on all 25 catalog keys today by coincidence, not by construction:
    `provenance._BASIS_PROSE` already spells the same concept "single-quarter"
    with a hyphen, and `"single quarter" in "basis: single-quarter"` is False, so
    a one-character edit to that label would drop the transcription notice from
    the eight KPI tiles while the rows below stayed marked. They belong as one
    predicate in stats.catalog taking the raw token; that is not this commit's
    to do, and until it is, this docstring says what this check tests and no
    more.

    THE LIMIT, STATED. A stat with an `fy` or `cumulative` basis still gets the
    flat list, because there is nothing measured to mark it with. That is right
    for the two movers keys and timeliness_slippage_corr, whose bases really do
    span every annual workbook, and it over-states refusal_rate_change_fy23_fy24,
    which reads two of them. Marking that one honestly needs a year breakdown in
    the live layer, which is provenance._live_layer's to add, not this
    function's — it must stay a consumer of measured fields.
    """
    years = set(view.get("financial_years") or ()) if view else set()
    measures = set(view.get("measures") or ()) if view else set()
    transcribed = bool(view) and view.get("basis") == "single_quarter"
    # The marker is a `part` cell, and `part` is the narrow column in
    # site/assets/report.js's table. The version this replaces was
    # " (not this figure — transcribed, see below)" repeated on ten of the
    # roughly twenty-five rows of a KPI answer: at 42 characters it was the
    # widest cell on the page and it squeezed the `detail` column, which is the
    # one carrying the URLs and the sha256 hashes a reader came for. The
    # explanation is said ONCE, as its own row, and each row keeps only the mark.
    # Nothing is dropped — the pointer row below says everything the long label
    # did — and the widest `part` cell is now "Scope of that row count and hash",
    # which was already there. The cheaper fix is here rather than in report.js.
    not_this_figure = " (not this figure)"
    rows: list[dict] = []
    if transcribed:
        rows.append({"part": "Reading the marks below", "detail":
                     "This figure was transcribed from the OAIC's published "
                     "dashboard, so nothing marked '(not this figure)' below fed "
                     "it: not one of the workbooks and not one of the sheets. "
                     "The dashboard itself is listed as a Reference, and the "
                     "decision to transcribe these figures is among the curation "
                     "decisions, both further down this table."})
    for source in registry["sources"]:
        if not source.get("ingested_as"):
            rows.append({"part": "Reference", "detail":
                         f"{source['title']} — {source['url']}"})
            continue
        part = "Source file"
        if transcribed:
            part += not_this_figure
        elif years:
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
            # A transcribed figure came through no sheet at all, so "the 'Action
            # on requests' sheet supplies ... withdrawn" under the heading "Where
            # Share of decisions withdrawn comes from" is the same false claim by
            # juxtaposition as the workbook list above. Only SHEET derivations
            # are marked: the convention entries (the P/O/T buckets, the
            # normaliser version) apply to every fact including a transcribed
            # one, so marking them would be the false claim in reverse.
            if transcribed:
                part += not_this_figure
            elif measures:
                part += (" (this figure)" if measures & set(entry["measures"])
                         else " (other measures)")
        else:
            detail = entry["title"]
        rows.append({"part": part, "detail": detail})
    for entry in registry["decisions"]:
        rows.append({"part": "Curation decision",
                     "detail": f"{entry['title']} (recorded {entry['date']})"})
    return rows


def _fact_rows_phrase(n: int) -> str:
    """"1 published fact row", not "1 published fact rows". Four of the eight
    transcribed Q1 figures ARE one row, so the ungrammatical string was on the
    site's most prominent numbers rather than in a rare branch."""
    return f"{n} published fact row" + ("" if n == 1 else "s")


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
            f"{_fact_rows_phrase(figure['source_rows'])}: "
            f"{', '.join(view['measures'])} for request type "
            f"{', '.join(view['buckets'])}, financial year {years}, across "
            f"{view['distinct_agencies']} reporting agencies")
    else:
        count_detail = (f"{_fact_rows_phrase(figure['source_rows'])} on a "
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


class _UnknownFigure(LookupError):
    """`describe` rejected the figure key the router resolved.

    A NAMED signal so build_report can catch exactly that and nothing else. The
    version this replaces wrapped the whole `_provenance_report` call in
    `except KeyError` and rendered "This site could not work out the basis behind
    'withdrawn_q1'" — naming a figure it had not diagnosed. A KeyError from the
    registry rendering below would have been reported as a fault in whichever
    figure the router happened to pick, and on a whole-platform question, where
    `key` is None, the reader was told the site "could not work out the basis
    behind None".
    """


def _provenance_report(request: str, frame, key: str | None) -> dict:
    # NO `except KeyError: payload = describe(frame)` HERE. That fallback turned
    # any KeyError raised anywhere inside describe — the catalog's "unknown stat
    # key" signal and a genuine one alike — into the whole-platform answer, with
    # nothing in front of the reader saying the figure they named was not found.
    # A reader who asked about one figure and got seven workbooks under "Where
    # this data comes from" is the same false claim by juxtaposition this route's
    # subject gate exists to prevent. `key` comes from _ROUTER's own stat keys so
    # the signal is unreachable today; if one ever arrives, build_report turns it
    # into an explicit refusal rather than a plausible-looking answer.
    #
    # The catch is HERE and it is one line wide, so only a KeyError raised while
    # resolving a NAMED figure can be reported as one. Everything below — the
    # registry rendering, the qualifier constructor — raises on out, because a
    # KeyError there is a code fault, and a code fault dressed as a polite
    # "we could not work out that figure" is a bug that reaches nobody who can
    # fix it. `ProvenanceError` keeps its own handler: registry drift is an
    # operational state an operator can cause, not a fault.
    if key is None:
        payload = describe(frame)
    else:
        try:
            payload = describe(frame, key=key)
        except KeyError as exc:
            raise _UnknownFigure(key) from exc
    figure = payload.get("figure")
    if figure is not None:
        # nothing catches _qualified_basis' ValueError: a figure layer that
        # arrived without its qualifier must fail loud, not fall back to a
        # generic answer that would look like it worked
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
    # Only meaningful once `key == _PROVENANCE`: which figure the reader is
    # asking about, or None for the platform as a whole. It is resolved by
    # _provenance_subject rather than by a second pass down here, because
    # deciding WHETHER to answer and deciding WHAT the answer is about are the
    # same question — the subject gate admits a request only when it can name
    # the thing being cited, so the key it found IS the key this route needs.
    # The pass it replaces recomputed `next((k for p, k in _ROUTER[1:] ...))`,
    # the identical expression, a few lines further down.
    figure_key = None
    for pattern, stat_key in _ROUTER:
        if not pattern.search(request):
            continue
        if stat_key == _PROVENANCE:
            # Provenance wording about something this platform cannot cite
            # ("where did the share portfolio data come from") is a refusal,
            # not a request for a statistic. `break`, not `continue`: falling
            # through to the stat router would answer "where did the train
            # timeliness data come from?" with the timeliness correlation — the
            # same coincidental keyword hit this subject gate exists to prevent,
            # one hop down. Escalation (key stays None) is the only honest
            # answer. See _provenance_subject: every content word must be this
            # platform's, and the request must resolve a figure or name the
            # platform itself.
            answerable, figure_key = _provenance_subject(request, frame)
            if not answerable:
                figure_key = None
                break
        key = stat_key
        break
    if key is None:
        return {"request": request, "stat_key": None, "stat_label": None,
                "data": None, "basis": None, "dataset_registry": {},
                "model": "no-match", "escalate": True, "error": _ESCALATION}
    if key == _PROVENANCE:
        # `figure_key` came from _provenance_subject above — the same
        # _ROUTER[1:] scan, run once, at the point where its result decided the
        # route may answer at all.
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
        except _UnknownFigure as exc:
            # the catalog's "unknown stat key" signal, reaching here through
            # describe. figure_key came from _ROUTER, so this is unreachable
            # today; it is handled explicitly because the alternative (falling
            # back to the whole-platform lineage) answers a question the reader
            # did not ask under a heading that looks like the one they did.
            #
            # `_UnknownFigure`, NOT `KeyError`. _provenance_report re-raises the
            # KeyError as _UnknownFigure precisely so a KeyError from the
            # registry rendering below it stays a crash instead of being
            # reported to a reader as a fault in whichever figure the router
            # picked. `_UnknownFigure` subclasses LookupError, which is
            # KeyError's PARENT, not KeyError — so `except KeyError` here would
            # have caught nothing and let the named signal escape as a 500.
            return {"request": request, "stat_key": None, "stat_label": None,
                    "data": None, "basis": None, "dataset_registry": {},
                    "model": "provenance-unavailable", "escalate": True,
                    "error": f"This site could not work out the basis behind "
                             f"{figure_key!r}, so it will not say where that "
                             f"figure came from ({exc.__cause__!r}). "
                             f"{_ESCALATION}"}
    stat = foi_stats(frame, key)
    return {"request": request, "stat_key": key,
            "stat_label": _LABELS.get(key, key.replace("_", " ")),
            "data": stat["value"], "basis": stat["basis"],
            "dataset_registry": {"source_rows": stat["source_rows"],
                                 "rows_hash": stat["rows_hash"]},
            "model": "deterministic router (figures from the platform frame, "
                     "not the LLM)", "escalate": False}
