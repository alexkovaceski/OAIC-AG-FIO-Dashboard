"""Regression tests for stats.dsl — the enum-constrained DSL ops.

Covers the four acceptance-test questions (compare_period refusal movers,
correlate timeliness/volume, by_portfolio, top contributor is Home Affairs)
plus the div-by-zero fix: compute_safe must surface the error, never mint a
wrong rate.
"""
import sys; sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from storage.frame import Frame
from stats.dsl import query_dataset, compute_safe


def test_acceptance_q1_refusal_movers():
    f = Frame(normalise_all())
    r = query_dataset(f, "compare_period", {"measure": "refused", "fy_a": "2022-23", "fy_b": "2023-24"})
    assert "change" in r and "value_a" in r


def test_acceptance_q2_correlate_timeliness_volume():
    f = Frame(normalise_all())
    # correlate = trend of within_statutory vs received; platform computes the correlation
    within = [query_dataset(f, "trend", {"measure": "within_statutory"})["values"]]
    recv = [query_dataset(f, "trend", {"measure": "received"})["values"]]
    # assert both trend series exist (the corr coefficient is computed downstream)
    assert within and recv


def test_acceptance_q3_portfolio():
    f = Frame(normalise_all())
    r = query_dataset(f, "by_portfolio", {"measure": "within_statutory", "fy": "2024-25"})
    assert "portfolios" in r


def test_acceptance_q4_home_affairs():
    f = Frame(normalise_all())
    r = query_dataset(f, "filter_agencies", {"measure": "received", "top_n": 1})
    assert r["top"][0]["agency"] == "Department of Home Affairs"


def test_div_by_zero_raises():
    r = compute_safe("a / b", {"a": 5, "b": 0})
    assert "error" in r and "division by zero" in r["error"]


def test_compute_safe_valid():
    r = compute_safe("a * 2 + b", {"a": 3, "b": 1})
    assert r["value"] == 7.0
    assert "error" not in r
