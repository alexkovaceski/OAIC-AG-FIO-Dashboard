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
    # refused has no FY facts, so the base is 0 — change_pct must be None,
    # never a fabricated "no change" of 0
    assert r["value_a"] == 0 and r["value_b"] == 0
    assert r["change_pct"] is None


def test_compare_period_received_real_change():
    f = Frame(normalise_all())
    r = query_dataset(f, "compare_period", {"measure": "received", "fy_a": "2023-24", "fy_b": "2024-25"})
    assert r["value_a"] == 34153 and r["value_b"] == 42759
    assert r["change"] == 8606
    assert r["change_pct"] == 25  # round(100 * 8606 / 34153)


def test_acceptance_q2_correlate_timeliness_volume():
    f = Frame(normalise_all())
    # within_statutory only exists as single-quarter Q1 facts — no FY series, so
    # the honest correlation is None, never a fabricated coefficient.
    within = query_dataset(f, "trend", {"measure": "within_statutory"})["values"]
    recv = query_dataset(f, "trend", {"measure": "received"})["values"]
    assert len(within) == len(recv) >= 6          # the FY windows line up
    assert all(v == 0 for v in within)            # honest zero line (no FY facts)
    assert recv and any(v > 0 for v in recv)      # received is a real series
    assert foi_stats(f, "timeliness_slippage_corr")["value"] is None  # no fabrication


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


def test_kpis_op_carries_basis():
    f = Frame(normalise_all())
    r = query_dataset(f, "kpis", {})
    assert set(r) == set(STAT_KEYS)
    for k, v in r.items():
        assert isinstance(v, dict) and "value" in v and "basis" in v


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
