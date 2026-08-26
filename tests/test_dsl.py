"""Regression tests for stats.dsl — the enum-constrained DSL ops.

Covers the four acceptance-test questions (compare_period refusal movers,
correlate timeliness/volume, by_portfolio, top contributor is Home Affairs)
plus the div-by-zero fix and the review-found regressions (no phantom Total
agency, basis on kpis, change_pct None on a zero base, compute_safe error
containment, citation fail-loud).
"""
import sys; sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from storage.frame import Frame
from stats.catalog import foi_stats, STAT_KEYS
from stats.dsl import query_dataset, compute_safe, resolve_citations


def test_acceptance_q1_refusal_movers():
    f = Frame(normalise_all())
    r = query_dataset(f, "compare_period", {"measure": "refused", "fy_a": "2022-23", "fy_b": "2023-24"})
    assert "change" in r and "value_a" in r
    # refused now has annual-FY facts read from the published Total row; the
    # change is real published data, never a fabricated rate off a zero base
    assert r["value_a"] == 4797 and r["value_b"] == 5223
    assert r["change"] == 426 and r["change_pct"] == 9


def test_compare_period_received_real_change():
    f = Frame(normalise_all())
    r = query_dataset(f, "compare_period", {"measure": "received", "fy_a": "2023-24", "fy_b": "2024-25"})
    assert r["value_a"] == 34153 and r["value_b"] == 42759
    assert r["change"] == 8606
    assert r["change_pct"] == 25  # round(100 * 8606 / 34153)


def test_acceptance_q2_correlate_timeliness_volume():
    f = Frame(normalise_all())
    # within_statutory now has annual-FY facts, so the trend is a real published
    # series; the correlation is a real coefficient over that series, never a
    # fabricated number and never a forced None.
    within = query_dataset(f, "trend", {"measure": "within_statutory"})["values"]
    recv = query_dataset(f, "trend", {"measure": "received"})["values"]
    assert within and any(v > 0 for v in within)  # real published series
    assert recv and any(v > 0 for v in recv)      # received is a real series
    assert foi_stats(f, "timeliness_slippage_corr")["value"] is not None  # real correlation


def test_acceptance_q3_portfolio():
    f = Frame(normalise_all())
    r = query_dataset(f, "by_portfolio", {"measure": "within_statutory", "fy": "2024-25"})
    assert "portfolios" in r


def test_acceptance_q4_home_affairs():
    f = Frame(normalise_all())
    r = query_dataset(f, "filter_agencies", {"measure": "received", "top_n": 1})
    assert r["top"][0]["agency"] == "Department of Home Affairs"


def test_no_phantom_total_agency():
    f = Frame(normalise_all())
    ag = query_dataset(f, "list_agencies", {})
    assert "Total" not in ag["agencies"]
    r = query_dataset(f, "filter_agencies", {"measure": "received", "top_n": 5})
    assert all(a["agency"] != "Total" for a in r["top"])
    s = query_dataset(f, "summarize_agencies", {"measure": "received"})
    assert "count" in s and "total" in s


def test_trend_no_fabrication_and_no_golden_total():
    f = Frame(normalise_all())
    # within_statutory now has annual-FY facts; the series is the published
    # Total-row values, never zeros and never the golden grand total
    within = query_dataset(f, "trend", {"measure": "within_statutory"})
    assert within["values"] == [23085, 20663, 17798, 15723, 15754, 18296, 16047]
    assert within["years"] == ["2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
    # received is a real series; the 2025-26 point is the per-agency cumulative
    # total (34,418), NOT 46,777 — the golden "Total" grand total must not leak in
    received = query_dataset(f, "trend", {"measure": "received"})["values"]
    assert received[-1] == 34418


def test_compare_period_excludes_total():
    f = Frame(normalise_all())
    r = query_dataset(f, "compare_period", {"measure": "received", "fy_a": "2024-25", "fy_b": "2025-26"})
    # 2025-26 value_b is the per-agency cumulative total (34,418), not the
    # double-counted 46,777 that would include the golden grand total
    assert r["value_a"] == 42759 and r["value_b"] == 34418
    assert r["change"] == -8341 and r["change_pct"] == -20


def test_by_portfolio_excludes_total():
    f = Frame(normalise_all())
    r = query_dataset(f, "by_portfolio", {"measure": "received", "fy": "2025-26", "bucket": "total"})
    # portfolio data comes from banner-row capture (Tasks 1-2); some agencies are mapped,
    # some are not. The result excludes the golden "Total" pseudo-agency grand total
    # (46,777), counting only per-agency facts and summing mapped values only.
    # Measured as of this test write: 14 portfolios, 11 unmapped agencies, mapped_sum=34303.
    assert len(r["portfolios"]) == 14
    assert r.get("unmapped_agency_count") == 11
    mapped_sum = sum(p["value"] for p in r["portfolios"])
    assert mapped_sum == 34303


def test_kpis_op_carries_basis():
    # SCALAR-ONLY (review I3, 2026-08-26). A KPI is one number. The ranked
    # movers TABLES took the payload to 42.6KB while agentic/builder.py
    # truncates the model-facing tool result at 4000 chars — the model saw none
    # of them, and the 167-row legacy refusal_rate_change_fy23_fy24 list (key 9
    # of 12) ate the whole truncation budget before timeliness_slippage_corr
    # was reached. Every excluded key is still reachable via foi_stats and
    # GET /api/figures. The shape of the keys that remain is unchanged.
    f = Frame(normalise_all())
    r = query_dataset(f, "kpis", {})
    scalar_keys = {k for k in STAT_KEYS
                   if not isinstance(foi_stats(f, k)["value"], (list, dict))}
    assert set(r) == scalar_keys
    assert set(r) < set(STAT_KEYS), "nothing was excluded — the op is unchanged"
    assert "refusal_rate_movers" not in r and "timeliness_movers" not in r
    assert "timeliness_slippage_corr" in r, \
        "the scalar the tables used to crowd out must survive"
    for k, v in r.items():
        assert isinstance(v, dict) and "value" in v and "basis" in v
        assert not isinstance(v["value"], (list, dict))


def test_kpis_op_payload_stays_small_enough_for_the_model_to_see():
    # I3: builder.py truncates the tool result at 4000 chars. A kpis payload
    # bigger than that is cost the model provably cannot read.
    import json
    f = Frame(normalise_all())
    blob = json.dumps(query_dataset(f, "kpis", {}))
    assert len(blob) < 4000, f"{len(blob)} chars — truncated before the model sees it"


def test_div_by_zero_raises():
    r = compute_safe("a / b", {"a": 5, "b": 0})
    assert "error" in r and "division by zero" in r["error"]


def test_compute_safe_valid():
    r = compute_safe("a * 2 + b", {"a": 3, "b": 1})
    assert r["value"] == 7.0
    assert "error" not in r


def test_compute_safe_unsupported_operator_is_error():
    r = compute_safe("a // b", {"a": 5, "b": 2})
    assert "error" in r and "unsupported operator" in r["error"]


def test_compute_safe_overflow_is_error():
    r = compute_safe("a ** b", {"a": 10, "b": 1000})
    assert "error" in r


def test_resolve_citations_known_and_fail_loud():
    transcript = [{"seq": 1, "tool": "query_dataset",
                   "result": {"top": [{"agency": "Department of Home Affairs", "value": 203256}]}}]
    spec = {"panels": [{"title": "{c:0.1.0.top[0].agency}"}]}
    resolved = resolve_citations(spec, transcript)
    assert resolved["panels"][0]["title"] == "Department of Home Affairs"

    # an unknown pointer must FAIL LOUD, never print a guess
    try:
        resolve_citations({"panels": [{"title": "{c:0.9.0.top[0].agency}"}]}, transcript)
        assert False, "should have failed loud"
    except SystemExit as e:
        assert "FAIL LOUD" in str(e)

    # a non-numeric turn must fail loud too (previously leaked ValueError)
    try:
        resolve_citations({"panels": [{"title": "{c:0.xx.0.top}"}]}, transcript)
        assert False, "should have failed loud"
    except SystemExit as e:
        assert "FAIL LOUD" in str(e)


# --- Stage 3a carry-over sweep, item F ---------------------------------------

def _synthetic_agency_frame():
    """A frame carrying one real agency, the golden "Total" pseudo-agency and an
    x-prefixed placeholder row, in two financial years.

    SYNTHETIC on purpose: the real frame cannot exercise the x-prefixed half of
    the predicate at all — measured 2026-08-26, 0 of its 54,602 facts carry an
    x-prefixed agency name, because ingest.normalise drops those rows. That is
    why the divergence between stats.catalog.is_reporting_agency and the dsl ops
    survived unnoticed, and it is why a real-frame assertion cannot guard the
    alignment.
    """
    def row(agency, fy, value, portfolio="Attorney-General's"):
        return {"agency_key": agency.lower().replace(" ", "-"),
                "agency_name": agency, "fy": fy, "quarter": None,
                "measure_group": "requests", "measure": "received",
                "bucket": "total", "value": float(value), "derived": False,
                "portfolio": portfolio}
    return Frame([
        row("Agency A", "2023-24", 100), row("Agency A", "2024-25", 120),
        row("Total", "2023-24", 100), row("Total", "2024-25", 120),
        row("xPlaceholder", "2023-24", 7), row("xPlaceholder", "2024-25", 9),
    ])


def test_every_per_agency_op_applies_both_halves_of_the_agency_predicate():
    # F: only list_agencies applied both halves of is_reporting_agency;
    # filter_agencies, summarize_agencies, trend, compare_period and
    # by_portfolio dropped the "Total" pseudo-agency and KEPT x-prefixed
    # placeholder rows. The divergence moved 0 rows on the real frame (no
    # x-prefixed facts survive ingest), so the exposure was one ingest change
    # away rather than structurally impossible. All six now apply the same
    # predicate the catalog and the chart engine apply.
    from stats.catalog import is_reporting_agency
    f = _synthetic_agency_frame()
    assert not is_reporting_agency("xPlaceholder")
    assert not is_reporting_agency("Total")
    assert is_reporting_agency("Agency A")

    ag = query_dataset(f, "list_agencies", {})
    assert ag["agencies"] == ["Agency A"], ag

    top = query_dataset(f, "filter_agencies", {"measure": "received"})
    assert [t["agency"] for t in top["top"]] == ["Agency A"], top
    assert top["count"] == 1

    # 100 + 120 from Agency A alone; 236 would mean the placeholder was summed
    s = query_dataset(f, "summarize_agencies", {"measure": "received"})
    assert s["total"] == 220 and s["count"] == 2, s

    tr = query_dataset(f, "trend", {"measure": "received"})
    assert tr["years"] == ["2023-24", "2024-25"]
    assert tr["values"] == [100, 120], tr

    cp = query_dataset(f, "compare_period",
                       {"measure": "received", "fy_a": "2023-24", "fy_b": "2024-25"})
    assert cp["value_a"] == 100 and cp["value_b"] == 120, cp

    bp = query_dataset(f, "by_portfolio", {"measure": "received"})
    assert bp["portfolios"] == [{"portfolio": "Attorney-General's", "value": 220}], bp

    # top_contributors delegates to filter_agencies, so it is covered too
    tc = query_dataset(f, "top_contributors", {"measure": "received"})
    assert [t["agency"] for t in tc["top"]] == ["Agency A"], tc


def test_dsl_agency_predicate_is_single_sourced():
    # F: six ops open-coded `agency_name.lower() != "total"`. One definition —
    # stats.catalog.is_reporting_agency — or they drift again.
    import ast
    from pathlib import Path
    # the CODE, comments stripped — the module comment quotes the predicate it
    # replaced, which is the record of what went wrong
    code = ast.unparse(ast.parse(
        Path("src/stats/dsl.py").read_text(encoding="utf-8")))
    applied = code.count("is_reporting_agency(f['agency_name'])")
    assert applied == 6, \
        f"{applied} of the 6 per-agency ops apply the shared predicate"
    assert "!= 'total'" not in code, "an open-coded half-predicate is back"
    assert ".startswith('x')" not in code, "an open-coded half-predicate is back"
