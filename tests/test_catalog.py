"""Regression tests for stats.catalog — the enum-constrained stat catalog.

The model may only cite keys in FIG_KEYS / STAT_KEYS; every figure is computed
from the canonical facts in the Frame, never hardcoded. foi_stats returns
{value, basis, source_rows, rows_hash} — rows_hash is the replay contract (a
sha256 over the canonical JSON of the exact source rows the stat consumed), so
storage.lineage.replay_verify can recompute-and-compare without trusting the
stored value.
"""
import sys; sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from storage.frame import Frame
from stats.catalog import foi_stats, FIG_KEYS, STAT_KEYS, hash_rows
from config import GOLDEN_Q1_FIGURES


def test_q1_headline_stats():
    f = Frame(normalise_all())
    assert foi_stats(f, "requests_received_q1")["value"] == GOLDEN_Q1_FIGURES["requests_received"]
    assert foi_stats(f, "within_statutory_pct_q1")["value"] == 70  # 5,167/7,344
    assert foi_stats(f, "granted_full_share_q1")["value"] == 19     # 1,426/7,344


def test_enum_constrained():
    # every key is a known key
    for k in list(FIG_KEYS) + list(STAT_KEYS):
        foi_stats(Frame(normalise_all()), k)  # must not raise


def test_unknown_key_raises():
    # the never-invent-a-number contract: an uncited key fails loud
    try:
        foi_stats(Frame(normalise_all()), "minted_number_123")
        assert False, "unknown key must raise"
    except KeyError:
        pass


def test_rows_hash_is_deterministic_sha256():
    # the replay contract: rows_hash is a deterministic sha256 over the source rows
    f = Frame(normalise_all())
    r1 = foi_stats(f, "requests_received_q1")
    r2 = foi_stats(f, "requests_received_q1")
    assert r1["rows_hash"] == r2["rows_hash"]
    assert len(r1["rows_hash"]) == 64
    assert all(c in "0123456789abcdef" for c in r1["rows_hash"])
    # the hash is over the exact source rows the stat consumed
    rows = f.filter(fy="2025-26", quarter=1, measure="received", bucket="total")
    assert r1["rows_hash"] == hash_rows(rows)
    assert r1["source_rows"] == len(rows) == 1
    assert r1["basis"] == "single_quarter"


def test_uncomputable_figures_are_empty_not_zero():
    # measures the annual files don't publish must NOT fabricate flat zero
    # lines — the figure returns an empty series, and the honest correlation
    # is None, never a number.
    f = Frame(normalise_all())
    for k in ["requests_decided_trend", "decision_outcomes_trend", "timeliness_trend",
              "refused_pct_trend", "granted_full_part_change", "timeliness_change",
              "decided_top20"]:
        fig = foi_stats(f, k)["value"]
        for s in fig["series"]:
            assert s["values"] == [], f"{k}: expected empty series, got {s['values']}"
    # timeliness_trend must not invent an after_statutory series
    tt = foi_stats(f, "timeliness_trend")["value"]
    assert all(s["name"] != "after_statutory" for s in tt["series"])
    assert foi_stats(f, "timeliness_slippage_corr")["value"] is None
