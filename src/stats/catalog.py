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
)
# stat keys (KPI tiles) — the model may cite these
STAT_KEYS = (
    "requests_received_q1", "requests_finalised_q1", "decided_q1",
    "within_statutory_pct_q1", "granted_full_share_q1", "granted_part_share_q1",
    "refused_share_q1", "withdrawn_q1", "refusal_rate_change_fy23_fy24",
    "timeliness_slippage_corr",
)
FIG_CAPTIONS = {
    "requests_received_trend": "Requests received, FY trend",
    "requests_finalised_trend": "Requests finalised, FY trend",
    "requests_decided_trend": "Requests decided, FY trend",
    "received_top20": "Top 20 agencies by requests received",
    "decided_top20": "Top 20 agencies by requests decided",
    "decision_outcomes_trend": "Decision outcomes by FY",
    "timeliness_trend": "Timeliness of decision-making (within/after)",
    "refused_pct_trend": "Percentage of decisions refused",
    "granted_full_part_change": "Change in % granted in full or part",
    "timeliness_change": "Change in % within statutory time period",
}

# The latest complete financial year in the annual files. The 2025-26 file is
# a Q1-Q3 cumulative partial; top-N rankings default to the last full year.
# Update once per year when the new annual file lands. This is the ONLY place
# the year is written — specs and pages reference the constant.
LATEST_COMPLETE_FY = "2024-25"

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
}

# a fact row the stat consumed -> canonical JSON. NOTE: portfolio is excluded —
# the foi_facts table does not store it (load_facts returns portfolio=""), so a
# hash that included portfolio could never be reproduced from a DB reload, which
# would make the replay comparison always fail.
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

    Returns [] when the measure has no annual-FY rows at all — the annual files
    only publish received/finalised, so measures like decided/refused return an
    EMPTY series, never a fabricated flat zero line. Years missing within a
    present measure are None, not 0."""
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


def _refusal_rate_movers(frame, fy_a: str, fy_b: str) -> list[dict]:
    """Per-agency refusal rate (refused/decided) change between two FYs, top movers.

    Each agency's rate for both FYs is computed from its own bucket="total"
    rows; agencies without a decided total in either FY are skipped (no
    division by zero / no fabricated rate). Sorted by absolute change, largest
    first. The rate is the share of decisions refused (0-100), rounded to a
    tenth; the golden refused/decided totals only exist as single-quarter Q1
    2025-26 facts, so the FY series uses the published annual files' agency
    rows (both totals present -> a real, verifiable rate).
    """
    def rate(fy):
        rows = frame.filter(fy=fy, bucket="total")
        by = {}
        for f in rows:
            if f["measure"] in ("refused", "decided"):
                by.setdefault(f["agency_name"], {"refused": 0.0, "decided": 0.0})
                by[f["agency_name"]][f["measure"]] += f["value"]
        out = {}
        for name, m in by.items():
            if m["decided"] > 0:
                out[name] = 100.0 * m["refused"] / m["decided"]
        return out

    ra, rb = rate(fy_a), rate(fy_b)
    movers = []
    for name in ra:
        if name in rb:
            movers.append({"agency": name, "fy_a_rate": round(ra[name], 1),
                           "fy_b_rate": round(rb[name], 1),
                           "change": round(rb[name] - ra[name], 1)})
    movers.sort(key=lambda m: abs(m["change"]), reverse=True)
    return movers


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
        rows = frame.filter(measure=spec["measure"], bucket="total",
                            fy=spec["default_fy"])
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
        rows = frame.filter(fy="2023-24", bucket="total") \
            + frame.filter(fy="2022-23", bucket="total")
        return {"value": _refusal_rate_movers(frame, "2022-23", "2023-24"), "basis": "fy",
                "source_rows": len(rows), "rows_hash": hash_rows(rows)}
    if key == "timeliness_slippage_corr":
        # Pearson correlation between within-statutory FY counts and received FY
        # counts. The within-statutory series is empty (the measure only exists
        # as single-quarter Q1 facts), so the honest result is None — a
        # fabricated coefficient would be a made-up number. basis is "fy".
        return {"value": _pearson(_fy_series(frame, "within_statutory"),
                                  _fy_series(frame, "received")),
                "basis": "fy", "source_rows": 0, "rows_hash": hash_rows([])}
    if key in FIG_KEYS:
        rows = frame.facts
        return {"value": _figure(frame, key), "basis": "fy", "source_rows": len(rows),
                "rows_hash": hash_rows(rows)}
    raise KeyError(f"unknown stat key {key!r} — the model cannot cite this")
