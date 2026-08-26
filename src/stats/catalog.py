"""foi_stats — the enum-constrained stat catalog. The model may only cite these keys.

Every figure is computed from the canonical facts in the Frame; no model numbers.
Each result carries:
  value      — the number / series / list the renderer prints
  basis      — single_quarter | cumulative | fy (printed beside every figure)
  source_rows— how many fact rows the stat consumed
  rows_hash  — sha256 over the canonical JSON of the exact source rows, so
               storage.lineage.replay_verify can recompute-and-compare without
               trusting the stored value.
"""
from __future__ import annotations
import hashlib
import json

# figure keys (chartable) — the model may reference these in a spec
FIG_KEYS = (
    "requests_received_trend", "requests_finalised_trend", "requests_decided_trend",
    "decided_top20", "received_top20", "decision_outcomes_trend",
    "timeliness_trend", "refused_pct_trend", "granted_full_part_change",
    "timeliness_change", "agency_contributions_received", "agency_contributions_decided",
    "received_channel_trend",
)
# stat keys (KPI tiles) — the model may cite these
STAT_KEYS = (
    "requests_received_q1", "requests_finalised_q1", "decided_q1",
    "within_statutory_pct_q1", "granted_full_share_q1", "granted_part_share_q1",
    "refused_share_q1", "withdrawn_q1", "refusal_rate_change_fy23_fy24",
    "timeliness_slippage_corr", "refusal_rate_movers", "timeliness_movers",
)
FIG_CAPTIONS = {
    "requests_received_trend": "Requests received, FY trend",
    "requests_finalised_trend": "Requests finalised, FY trend",
    "requests_decided_trend": "Requests decided, FY trend",
    "received_top20": "Top 20 agencies by requests received",
    "decided_top20": "Top 20 agencies by requests decided",
    "decision_outcomes_trend": "Decision outcomes by FY",
    "timeliness_trend": "Timeliness of decision-making (within statutory)",
    "refused_pct_trend": "Percentage of decisions refused",
    # the two "change" figures plot a LEVEL series (a ratio per FY), not a
    # first difference — the caption says what is actually drawn (B10). The
    # change analysis itself is the movers table beside each chart.
    "granted_full_part_change": "% of decisions granted in full or part, by FY",
    "timeliness_change": "% decided within statutory time, by FY",
    "received_channel_trend": "Requests received by channel (applicant vs on transfer)",
}

# The latest complete financial year in the annual files. The 2025-26 file is
# a Q1-Q3 cumulative partial; top-N rankings default to the last full year.
# Update once per year when the new annual file lands. This is the ONLY place
# the year is written — specs and pages reference the constant.
LATEST_COMPLETE_FY = "2024-25"

# What a PART-year annual file covers, and what that window means in months.
# The site is allowed to say "financial year" only about a complete July-June
# year (site/pages.py defines that label on the How to use page), so a figure
# drawn for a part year has to say which months it actually covers. Two short
# strings rather than one because the basis label wants the window and the
# prose wants the months; nesting them read as "(Q1-Q3 cumulative (July to
# March))".
PARTIAL_FY_COVERAGE = "Q1–Q3 cumulative"
PARTIAL_FY_MONTHS = "July to March"


def partial_fys(frame) -> list[str]:
    """The annual financial years in this frame that are NOT complete years.

    DERIVED, not listed. LATEST_COMPLETE_FY names the latest year whose file
    covers a whole July-June year, so every annual category AFTER it is by
    definition a part-year release — no second year literal to fall out of step
    with the first. FY labels sort lexicographically in chronological order (the
    property _previous_complete_fy, _figure and _fy_series already rely on), so
    "later than" is a string comparison.

    Measured 2026-08-26 on the real frame: annual categories 2019-20..2025-26
    against LATEST_COMPLETE_FY 2024-25 returns exactly ['2025-26'] — the Q1-Q3
    cumulative workbook, and nothing else.

    Quarter-carrying rows are excluded for the same reason _fy_series excludes
    them: this is about which ANNUAL files are partial, and the golden Q1 rows
    are a separate single-quarter basis that never joins an FY series.
    """
    return sorted(fy for fy in {f["fy"] for f in frame.facts
                                if f["quarter"] is None}
                  if fy > LATEST_COMPLETE_FY)

# Movers floor: an agency needs at least this many denominator events (decided
# requests) in BOTH compared years before its rate change is ranked. Without a
# floor the top-10s are pure sampling noise — measured on the real frame
# 2026-08-26, all ten rendered refusal-rate rows had denominators of 1-5
# ("Asbestos and Silica Safety and Eradication Agency 0.0% -> 100.0%" is one
# refused request out of two decisions), and 65 of the 182 agencies with a
# computable rate decided fewer than 5 requests in a year. At 30, 53 agencies
# qualify — ample for a top 10 — and the table shows movement a reader can act
# on (Office of the eSafety Commissioner +32.7pp on 69 -> 457 decisions).
MOVERS_MIN_DENOMINATOR = 30

# FIGURE_SPECS — the declarative engine (spec S2.1). Each chartable figure is
# declared once; the server's generic _figure and the client's rederivation
# both interpret the same vocabulary:
#   trend       — one measure summed per FY (annual rows, bucket-scoped)
#   multi_trend — several measures, one series each
#   ratio_trend — 100 * sum(numerators) / sum(denominator) per FY, 1dp
#   top_n       — agencies ranked by one measure for one FY (default_fy unless
#                 the client's FY filter overrides it)
FIGURE_SPECS = {
    "requests_received_trend":  {"kind": "trend", "measures": ["received"]},
    "requests_finalised_trend": {"kind": "trend", "measures": ["finalised"]},
    "requests_decided_trend":   {"kind": "trend", "measures": ["decided"]},
    "decision_outcomes_trend":  {"kind": "multi_trend",
                                 "measures": ["granted_full", "granted_part",
                                              "refused", "withdrawn"]},
    "timeliness_trend":         {"kind": "trend", "measures": ["within_statutory"]},
    "refused_pct_trend":        {"kind": "ratio_trend", "numerators": ["refused"],
                                 "denominator": "decided", "name": "refused_pct"},
    "granted_full_part_change": {"kind": "ratio_trend",
                                 "numerators": ["granted_full", "granted_part"],
                                 "denominator": "decided",
                                 "name": "granted_full_or_part_pct"},
    "timeliness_change":        {"kind": "ratio_trend",
                                 "numerators": ["within_statutory"],
                                 "denominator": "decided",
                                 "name": "within_statutory_pct"},
    "received_top20":           {"kind": "top_n", "measure": "received", "n": 20,
                                 "default_fy": LATEST_COMPLETE_FY},
    "decided_top20":            {"kind": "top_n", "measure": "decided", "n": 20,
                                 "default_fy": LATEST_COMPLETE_FY},
    "agency_contributions_received": {"kind": "top_n", "measure": "received",
                                      "n": 20, "default_fy": LATEST_COMPLETE_FY},
    "agency_contributions_decided":  {"kind": "top_n", "measure": "decided",
                                      "n": 20, "default_fy": LATEST_COMPLETE_FY},
    # B5: how requests arrived — direct from an applicant vs on transfer from
    # another agency. Both measures are ingested by Stage 1, so the generic
    # multi_trend renderer draws this with no new engine code.
    "received_channel_trend":   {"kind": "multi_trend",
                                 "measures": ["received", "received_transfer"]},
}

# a fact row the stat consumed -> canonical JSON. portfolio is EXCLUDED on
# purpose and must stay excluded: pre-Stage-1 datasets were stored with
# portfolio='' and their lineage rows_hash values were computed without it, so
# including it would make replay_verify fail for every dataset ingested before
# 2026-08-25. The DB stores portfolio (storage/facts.py) — this hash simply
# does not consume it.
_FACT_KEYS = (
    "agency_key", "agency_name", "fy", "quarter", "measure_group", "measure",
    "bucket", "value", "derived",
)


def hash_rows(rows: list[dict]) -> str:
    """sha256 over the canonical JSON of source rows (order-independent). The
    replay contract: deterministic on fact content, so replay_verify can compare
    a recomputed hash against the stored lineage_ops.rows_hash."""
    lines = []
    for f in rows:
        row = {k: f.get(k) for k in _FACT_KEYS}
        if isinstance(row.get("value"), float):
            row["value"] = round(row["value"], 9)
        lines.append(json.dumps(row, sort_keys=True))
    lines.sort()
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def is_reporting_agency(agency_name: str) -> bool:
    """True for a real reporting body. It excludes exactly two things: the
    golden "Total" pseudo-agency (a national total-level fact, not an agency)
    and x-prefixed names (the normaliser's placeholder rows). The per-agency
    figures in this module apply it — the top-N ranking in _figure and the
    movers row selector (M3, S1).

    stats.dsl now applies THIS predicate, not a divergent copy. It used to: five
    of the six per-agency ops there open-coded only the first half
    (`agency_name.lower() != "total"`), so filter_agencies, summarize_agencies,
    trend, compare_period and by_portfolio kept x-prefixed rows that
    list_agencies and this module dropped. Commit 600d93f aligned them.
    Re-measured 2026-08-27 against dsl.py: all six ops call is_reporting_agency,
    and the only remaining `!= "total"` in that file is inside the comment
    explaining the history. The alignment moved 0 rows — ingest.normalise drops
    x-prefixed rows, so none of the frame's 54,602 facts can exercise the second
    half — and it is a strict tightening, which can only drop rows, never invent
    one. The synthetic-frame test in tests/test_dsl.py is what exercises the
    x-prefixed half, because the real frame cannot.

    What it IS the twin of: foi-charts.js's isReportingAgency, which applies
    both halves exactly as written here. Those two must stay identical, because
    the client re-derives on screen the same rankings this module publishes.

    PUBLIC because site.pages needs it for the agency dropdown — it was
    imported across a module boundary as a private name."""
    return agency_name.lower() != "total" and not agency_name.startswith("x")


def _q1_value(frame, measure):
    q1 = frame.filter(fy="2025-26", quarter=1, measure=measure, bucket="total")
    return round(sum(f["value"] for f in q1), 0)


def _single_quarter_rows(frame, measure):
    """The exact source rows a single-quarter Q1 figure consumed (hash basis)."""
    return frame.filter(fy="2025-26", quarter=1, measure=measure, bucket="total")


def _fy_series(frame, measure):
    """FY totals for a measure from the annual files (quarter is None, bucket=total).

    NOTE: Frame.filter(quarter=None) means "no quarter constraint" (it only
    filters when quarter is not None), so the annual-FY rows are selected by the
    explicit `f["quarter"] is None` test, not by frame.filter.

    Returns [] when the measure has no annual-FY rows at all — an absent measure
    yields an EMPTY series, never a fabricated flat zero line. Years missing
    within a present measure are None, not 0."""
    rows = [f for f in frame.facts if f["quarter"] is None
            and f["measure"] == measure and f["bucket"] == "total"]
    if not rows:
        return []
    by = {}
    for f in rows:
        by.setdefault(f["fy"], 0.0)
        by[f["fy"]] += f["value"]
    cats = sorted({f["fy"] for f in frame.facts if f["quarter"] is None})
    return [round(by[y]) if y in by else None for y in cats]


def _fy_series_source_rows(frame, measures) -> list[dict]:
    """The annual fact rows an FY-series stat reads: quarter is None,
    bucket="total", one of `measures`, real reporting agencies only.

    This is the hash basis for a stat computed from _fy_series output, so
    source_rows/rows_hash describe rows the stat actually consumed rather than a
    sentinel (the same discipline _movers_source_rows applies).

    One honest caveat: _fy_series itself applies NO agency predicate, so this
    row set is the reporting-agency SUBSET of what the series sums. On the
    current frame the two are the same rows — measured 2026-08-26, no annual row
    carries a non-reporting agency name, and the correlation's basis is 4044
    rows with sha256 65aa3bd3... whether the predicate is applied or not.

    WHICH WAY IT FAILS: silent PASS, not false alarm. If an annual "Total" row
    ever lands, _fy_series would sum it — moving the computed value — while this
    basis excluded it, leaving rows_hash unchanged, so replay_verify would tick
    green over a stat whose value had moved. That would be a bug in _fy_series
    (the top-N path in _figure already excludes it), and the divergence is worth
    surfacing rather than papering over by hashing rows a per-agency figure
    would refuse.
    """
    return [f for f in frame.facts
            if f["quarter"] is None and f["bucket"] == "total"
            and f["measure"] in measures
            and is_reporting_agency(f["agency_name"])]


def _pearson(a, b):
    n = len(a)
    if n != len(b) or n < 2:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return round(cov / (va * vb) ** 0.5, 3)


def _previous_complete_fy(frame):
    """The FY immediately before LATEST_COMPLETE_FY among the annual categories.

    Raises KeyError when LATEST_COMPLETE_FY is absent from the frame, or when it
    is the EARLIEST annual category: `cats[i - 1]` would then wrap to `cats[-1]`
    — the NEWEST year — and silently invert every FY-pair comparison (measured
    on a frame trimmed to ['2024-25', '2025-26']: the old code returned 2025-26
    as the "previous complete FY", flipping the sign of every change with no
    exception raised).

    KeyError (not ValueError) is deliberate: api.figures and the kpis op in
    stats.dsl both treat KeyError as "a key this frame cannot compute stays
    absent", so a frame the constant does not fit drops the two movers keys
    instead of 500-ing the whole /api/figures payload.
    """
    annual_fys = sorted({f["fy"] for f in frame.facts if f["quarter"] is None})
    if LATEST_COMPLETE_FY not in annual_fys:
        raise KeyError(f"LATEST_COMPLETE_FY {LATEST_COMPLETE_FY!r} has no annual "
                       f"rows in this frame ({annual_fys!r}) — no FY pair")
    i = annual_fys.index(LATEST_COMPLETE_FY)
    if i == 0:
        raise KeyError(f"no financial year precedes {LATEST_COMPLETE_FY!r} in this "
                       f"frame ({annual_fys!r}) — no FY pair")
    return annual_fys[i - 1]


def _movers_source_rows(frame, num_measure, den_measure, fy_a, fy_b) -> list[dict]:
    """The exact fact rows a rate-movers computation reads: the two FYs, the two
    measures, bucket="total", ANNUAL rows only, real reporting agencies only.

    This is both the input to _rate_movers and the hash basis of the stat, so
    `source_rows` / `rows_hash` describe what the stat actually consumed (I2).
    Hashing every bucket="total" row of both years instead (5247 rows, of which
    only 1166 are read) made refusal_rate_movers and timeliness_movers return
    the IDENTICAL hash despite computing different values — replay could not
    tell them apart, and an unrelated measure changing false-alarmed both.

    quarter: Frame.filter(quarter=None) means "no quarter constraint" (see
    _fy_series), so the annual rows are selected by the explicit
    `f["quarter"] is None` test. Without it the golden single-quarter rows would
    join the FY sums the moment LATEST_COMPLETE_FY reaches the partial year (I4).
    """
    return [f for f in frame.facts
            if f["fy"] in (fy_a, fy_b) and f["quarter"] is None
            and f["bucket"] == "total"
            and f["measure"] in (num_measure, den_measure)
            and is_reporting_agency(f["agency_name"])]


def _rate_movers(frame, num_measure, den_measure, fy_a, fy_b,
                 min_denominator: float = 0) -> list[dict]:
    """Per-agency rate (num/den) change between two FYs — the generalised form
    of the refusal-rate movers.

    Each agency's rate for both FYs is computed from its own annual
    bucket="total" rows, so both totals are published figures and the rate is
    verifiable. Rates are shares (0-100) rounded to a tenth; `change` is their
    difference and is therefore in PERCENTAGE POINTS, not percent (N3 — the
    renderer must not print it with a "%"). Each row carries the two
    denominators so a reader can judge the row without leaving the table.

    min_denominator is the floor the denominator must clear in BOTH years for
    the agency to be ranked at all. An agency that decided two requests can move
    from 0% to 100% on one decision; at min_denominator=0 those rows monopolise
    every top 10 (see MOVERS_MIN_DENOMINATOR). 0 means "any positive
    denominator" — the legacy refusal_rate_change_fy23_fy24 key keeps that,
    since agentic/report.py ships its list verbatim.

    The list is sorted by absolute change, largest first. Callers take the head
    — the full list is returned so the count of qualifying agencies can be
    disclosed."""
    totals = {}
    for f in _movers_source_rows(frame, num_measure, den_measure, fy_a, fy_b):
        agency_measures = totals.setdefault(
            (f["fy"], f["agency_name"]), {num_measure: 0.0, den_measure: 0.0})
        agency_measures[f["measure"]] += f["value"]

    def rates_by_agency(fy):
        """agency -> (rate, denominator) for the agencies that clear the floor."""
        return {agency: (100.0 * measures[num_measure] / measures[den_measure],
                         measures[den_measure])
                for (row_fy, agency), measures in totals.items()
                if row_fy == fy and measures[den_measure] > 0
                and measures[den_measure] >= min_denominator}

    rates_a, rates_b = rates_by_agency(fy_a), rates_by_agency(fy_b)
    movers = []
    for agency, (rate_a, denominator_a) in rates_a.items():
        if agency not in rates_b:
            continue
        rate_b, denominator_b = rates_b[agency]
        movers.append({"agency": agency,
                       "fy_a_rate": round(rate_a, 1),
                       "fy_b_rate": round(rate_b, 1),
                       "change": round(rate_b - rate_a, 1),
                       "fy_a_denominator": round(denominator_a),
                       "fy_b_denominator": round(denominator_b)})
    movers.sort(key=lambda mover: abs(mover["change"]), reverse=True)
    return movers


def _refusal_rate_movers(frame, fy_a: str, fy_b: str) -> list[dict]:
    """Per-agency refusal rate (refused/decided) change between two FYs, top
    movers. Kept as a named wrapper because the legacy
    `refusal_rate_change_fy23_fy24` stat key routes through it with its fixed
    FY pair and must keep returning the bare LIST (agentic/report.py renders
    stat["value"] directly). No denominator floor here — see _rate_movers."""
    return _rate_movers(frame, "refused", "decided", fy_a, fy_b)


def _movers_stat(frame, num_measure, den_measure,
                 min_denominator: float = MOVERS_MIN_DENOMINATOR) -> dict:
    """The standard result contract for an FY-pair movers stat: the two latest
    complete FYs, the denominator floor that was applied (so the renderer can
    disclose it), their movers, and the exact source rows both years consumed
    (so replay_verify can recompute the hash)."""
    fy_a, fy_b = _previous_complete_fy(frame), LATEST_COMPLETE_FY
    rows = _movers_source_rows(frame, num_measure, den_measure, fy_a, fy_b)
    return {"value": {"fy_a": fy_a, "fy_b": fy_b,
                      "denominator": den_measure,
                      "min_denominator": min_denominator,
                      "movers": _rate_movers(frame, num_measure, den_measure,
                                             fy_a, fy_b, min_denominator)},
            "basis": "fy", "source_rows": len(rows), "rows_hash": hash_rows(rows)}


def _figure_source_rows(frame, key) -> list[dict]:
    """The exact fact rows a figure's spec consumes — the hash basis for that
    figure, mirroring _movers_source_rows.

    Every figure key used to hash `frame.facts` wholesale, so all 13 returned
    the IDENTICAL rows_hash: replay_verify could not distinguish
    requests_received_trend from decided_top20, and an unrelated measure
    changing false-alarmed all thirteen. The spec already declares exactly
    which measures a figure reads, so the basis derives from it.

    Discipline matches _movers_source_rows: annual rows only (the explicit
    `quarter is None` test, because Frame.filter(quarter=None) means "no
    quarter constraint"), bucket="total" (every spec's server derivation reads
    the total bucket), real reporting agencies only. A top_n additionally
    narrows to its ranking year — without that narrowing a seven-year trend and
    a one-year top-20 over the same measure would hash identically.

    is_reporting_agency is defence-in-depth here, not an active filter: measured
    2026-08-26, all 8 non-reporting rows in the 54,602-fact frame are the golden
    "Total" pseudo-agency carrying quarter=1, so `quarter is None` already
    excludes every one of them and dropping the predicate moves no row. It earns
    its place by matching what _figure's top_n path applies, so the basis cannot
    drift from the ranking if an annual "Total" row ever lands.

    Same honest caveat as _fy_series_source_rows: the trend kinds route through
    _fy_series, which applies NO agency predicate, so for those this basis is
    the reporting-agency SUBSET of what the series sums. Measured 2026-08-26 on
    the real frame the two are the same rows — no annual row carries a
    non-reporting agency name, and every figure's basis is byte-identical with
    the predicate applied or removed. The top_n kinds have no such gap; _figure
    applies the identical predicate there.

    SECOND CAVEAT — the category axis is outside this basis, and it fails SILENT
    PASS. _figure builds `cats` from the annual FY set of the WHOLE frame (any
    measure, any bucket, any agency), so an FY that no row in this basis carries
    still adds a category and a trailing None to the figure's series: the value
    moves while rows_hash does not, and replay_verify ticks green over a changed
    figure. That is worse than a false alarm — a false alarm is visible.

    THE BLAST RADIUS IS EIGHT FIGURES, NOT ONE. Re-measured 2026-08-27 by
    injecting a single annual `withdrawn` row in a new FY 2026-27: 9 of the 13
    figure keys changed VALUE, and 8 of those 9 kept their rows_hash — every
    trend, multi_trend and ratio_trend key except decision_outcomes_trend, which
    reads `withdrawn` and so took the injected row into its own basis (its hash
    moved too, correctly). requests_received_trend is the representative case:
    categories gained '2026-27', the series gained a trailing None, source_rows
    stayed 2022 and rows_hash stayed 3b698fc46826. The three top_n keys are
    unaffected — they narrow to one FY.

    AND ONE HARD FAILURE ON THE SAME TRIGGER. That same injected row makes
    timeliness_slippage_corr raise, not drift: `TypeError: unsupported operand
    type(s) for +: 'int' and 'NoneType'`, because _pearson sums its inputs with
    no None guard and _fy_series now hands it a series with a hole. So the
    category-axis gap is not purely a silent-pass class; it takes a stat key
    down with it.

    It is inert on the real frame because the annual/total/reporting table is
    complete — all 9 measures x 7 FYs are populated (2,022 rows per measure), so
    a new annual file enters every figure's basis at once and no FY can exist
    outside one. It becomes reachable the moment that stops holding: a
    partial-measure ingest, an FY present only in non-total buckets, or an FY
    carried only by non-reporting agencies.

    REMEDIATION IS NOT ONE FUNCTION. _figure is where the axis is consumed, but
    _fy_series (same file) derives an IDENTICAL whole-frame axis of its own to
    position its values on. Narrowing only _figure would leave every trend
    series longer than its own category list, and ratio_trend indexing that
    longer series positionally against the shorter list — which lines up only
    while the narrowed axis is a leading prefix of the full one, and attributes
    values to the wrong year the moment a year goes missing from the middle. The
    two have to be narrowed together, and _pearson needs the None guard above in
    the same change. All of it is a behaviour change needing its own review —
    this docstring records the gap rather than closing it quietly.
    """
    spec = FIGURE_SPECS.get(key)
    if spec is None:
        return []
    measures = set(spec.get("measures", [])) | set(spec.get("numerators", []))
    if spec.get("denominator"):
        measures.add(spec["denominator"])
    if spec.get("measure"):
        measures.add(spec["measure"])
    rows = [f for f in frame.facts
            if f["quarter"] is None
            and f["bucket"] == "total"
            and f["measure"] in measures
            and is_reporting_agency(f["agency_name"])]
    if spec["kind"] == "top_n":
        rows = [f for f in rows if f["fy"] == spec["default_fy"]]
    return rows


def _figure(frame, key):
    """A chartable figure: {categories, series}, computed by interpreting the
    figure's FIGURE_SPECS entry. The FY trends read the annual files
    (quarter=None, bucket=total); the top-N reads one FY's agency rows. The
    single-quarter Q1 2025-26 headline stays on the separate *_q1 stats, never
    blended into the FY series (per the trend-window decision). A measure with
    no annual rows yields an empty/None-holed series, never a fabricated line.
    """
    spec = FIGURE_SPECS.get(key)
    if spec is None:
        return {"categories": [], "series": []}
    cats = sorted({f["fy"] for f in frame.facts if f["quarter"] is None})

    if spec["kind"] in ("trend", "multi_trend"):
        return {"categories": cats, "series": [
            {"name": m, "values": _fy_series(frame, m)} for m in spec["measures"]]}

    if spec["kind"] == "ratio_trend":
        nums = [_fy_series(frame, m) for m in spec["numerators"]]
        den = _fy_series(frame, spec["denominator"])
        if not den or any(not s for s in nums):
            # legacy zip semantics: an empty operand series truncates the
            # whole ratio to [] — and [] is what _figure_has_data needs to
            # show the honest no-data note instead of an all-null ghost line
            return {"categories": cats, "series": [{"name": spec["name"], "values": []}]}
        values = []
        for i in range(len(cats)):
            parts = [s[i] if i < len(s) else None for s in nums]
            d = den[i] if i < len(den) else None
            if any(p is None for p in parts) or not d:
                values.append(None)
            else:
                values.append(round(100 * sum(parts) / d, 1))
        return {"categories": cats, "series": [{"name": spec["name"], "values": values}]}

    if spec["kind"] == "top_n":
        # ANNUAL rows only, real reporting agencies only (S1). frame.filter
        # applies no quarter constraint, so a single-quarter row and the golden
        # "Total" pseudo-agency would both enter the ranking — and "Total" would
        # out-rank every real agency — the moment default_fy reaches the partial
        # year. The client-side engine applies the same two guards.
        rows = [f for f in frame.facts
                if f["fy"] == spec["default_fy"] and f["quarter"] is None
                and f["measure"] == spec["measure"] and f["bucket"] == "total"
                and is_reporting_agency(f["agency_name"])]
        aggs = {}
        for f in rows:
            aggs.setdefault(f["agency_name"], 0.0)
            aggs[f["agency_name"]] += f["value"]
        top = sorted(aggs.items(), key=lambda kv: kv[1], reverse=True)[:spec["n"]]
        return {"categories": [a for a, _ in top],
                "series": [{"name": spec["measure"],
                            "values": [round(v) for _, v in top]}]}

    return {"categories": [], "series": []}


def foi_stats(frame, key) -> dict:
    """Compute one stat from the canonical facts. Returns {value, basis, source_rows, rows_hash}."""
    if key == "requests_received_q1":
        rows = _single_quarter_rows(frame, "received")
        return {"value": _q1_value(frame, "received"), "basis": "single_quarter",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "requests_finalised_q1":
        rows = _single_quarter_rows(frame, "finalised")
        return {"value": _q1_value(frame, "finalised"), "basis": "single_quarter",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "decided_q1":
        rows = _single_quarter_rows(frame, "decided")
        return {"value": _q1_value(frame, "decided"), "basis": "single_quarter",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "within_statutory_pct_q1":
        rows = _single_quarter_rows(frame, "within_statutory") + _single_quarter_rows(frame, "decided")
        within = _q1_value(frame, "within_statutory"); decided = _q1_value(frame, "decided")
        return {"value": round(100 * within / decided), "basis": "single_quarter",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "granted_full_share_q1":
        rows = _single_quarter_rows(frame, "granted_full") + _single_quarter_rows(frame, "decided")
        v = _q1_value(frame, "granted_full"); d = _q1_value(frame, "decided")
        return {"value": round(100 * v / d), "basis": "single_quarter",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "granted_part_share_q1":
        rows = _single_quarter_rows(frame, "granted_part") + _single_quarter_rows(frame, "decided")
        v = _q1_value(frame, "granted_part"); d = _q1_value(frame, "decided")
        return {"value": round(100 * v / d), "basis": "single_quarter",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "refused_share_q1":
        rows = _single_quarter_rows(frame, "refused") + _single_quarter_rows(frame, "decided")
        v = _q1_value(frame, "refused"); d = _q1_value(frame, "decided")
        return {"value": round(100 * v / d), "basis": "single_quarter",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "withdrawn_q1":
        rows = _single_quarter_rows(frame, "withdrawn")
        return {"value": _q1_value(frame, "withdrawn"), "basis": "single_quarter",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "refusal_rate_change_fy23_fy24":
        # compare_period: refusal share FY23 vs FY24, per agency (top movers)
        rows = _movers_source_rows(frame, "refused", "decided", "2022-23", "2023-24")
        # NOTE: value stays a BARE LIST — agentic/report.py routes "refusal
        # rate" here and renders stat["value"] directly. The FY-pair dict shape
        # belongs to the newer refusal_rate_movers key, and so does the
        # denominator floor: this key keeps min_denominator=0.
        return {"value": _refusal_rate_movers(frame, "2022-23", "2023-24"), "basis": "fy",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "refusal_rate_movers":
        return _movers_stat(frame, "refused", "decided")
    if key == "timeliness_movers":
        return _movers_stat(frame, "within_statutory", "decided")
    if key == "timeliness_slippage_corr":
        # Pearson correlation between the within-statutory FY series and the
        # received FY series, both computed by _fy_series over the annual files.
        # Both measures have annual rows (the annual files publish decisions,
        # outcomes and timeliness since 43fad97), so this is a real coefficient:
        # 0.538 over the seven FYs in the current frame. _pearson returns None
        # only for a degenerate pair — fewer than two points, mismatched
        # lengths, or zero variance in either series — never a fabricated
        # number. basis is "fy".
        #
        # source_rows/rows_hash used to be the empty-row sentinel (0 /
        # hash_rows([])) left over from when this stat returned None. That was
        # a false provenance claim published beside a real number (the router in
        # agentic.report ships both fields to the user as dataset_registry), and
        # it was WORSE than no check: the sentinel string is truthy, so
        # replay_verify's `bool(stored) and rows_hash == stored` compared the
        # sentinel to itself and returned a green tick over nothing. Now it
        # names the 4044 annual rows it consumes (measured 2026-08-26; sha256
        # 65aa3bd3578c51e75cb208f6bf6834d656564c10cacbea395754a24f947d9ebe).
        #
        # Accepted cost: lineage_ops rows recorded BEFORE this change carry the
        # sentinel and will now fail replay. That is the correct outcome — they
        # were recorded with no row basis — and it is the precedent the three
        # movers keys set in this same stage. replay_verify fails closed
        # (returns False, never raises), and this key is not in
        # PAGE_FIGURE_KEYS, so only AI-built dashboard panels via
        # server.app._record_figure_ops ever wrote it.
        rows = _fy_series_source_rows(frame, ("within_statutory", "received"))
        return {"value": _pearson(_fy_series(frame, "within_statutory"),
                                  _fy_series(frame, "received")),
                "basis": "fy", "source_rows": len(rows),
                "rows_hash": hash_rows(rows)}
    if key in FIG_KEYS:
        rows = _figure_source_rows(frame, key)
        return {"value": _figure(frame, key), "basis": "fy", "source_rows": len(rows),
                "rows_hash": hash_rows(rows)}
    raise KeyError(f"unknown stat key {key!r} — the model cannot cite this")
