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


def test_published_measures_render_real_series():
    # the annual files now publish decided/outcomes/timeliness, so these figures
    # render real data — never flat zeros, never a fabricated line
    f = Frame(normalise_all())
    for k in ["requests_decided_trend", "decision_outcomes_trend", "timeliness_trend",
              "refused_pct_trend", "granted_full_part_change", "timeliness_change",
              "decided_top20"]:
        fig = foi_stats(f, k)["value"]
        assert fig["series"], f"{k}: expected a real series"
        for s in fig["series"]:
            assert any(v is not None for v in s["values"]), f"{k}: all None (fabricated)"
    # timeliness_trend must not invent an after_statutory series
    tt = foi_stats(f, "timeliness_trend")["value"]
    assert all(s["name"] != "after_statutory" for s in tt["series"])
    # the within-statutory correlation is a real coefficient over published
    # series — not a fabricated number, not a forced None
    corr = foi_stats(f, "timeliness_slippage_corr")["value"]
    assert corr is not None and -1 <= corr <= 1


def test_received_movers_are_volume_growth_between_two_fys():
    # the count-shaped sibling of the rate movers: per-agency change in requests
    # received between the two latest complete FYs, growth first, both years'
    # counts carried, and the exact source rows hashed for replay.
    f = Frame(normalise_all())
    stat = foi_stats(f, "received_movers")
    value = stat["value"]
    assert value["fy_a"] == "2023-24" and value["fy_b"] == "2024-25"
    assert stat["basis"] == "fy"
    assert stat["source_rows"] and len(stat["rows_hash"]) == 64
    movers = value["movers"]
    assert movers, "expected per-agency movers"
    first = movers[0]
    assert set(first) == {"agency", "fy_a_value", "fy_b_value", "change"}
    assert first["change"] == first["fy_b_value"] - first["fy_a_value"]
    # growth first: sorted by change descending
    changes = [m["change"] for m in movers]
    assert changes == sorted(changes, reverse=True)
    # Home Affairs is the biggest published grower in this frame
    home = next(m for m in movers if m["agency"] == "Department of Home Affairs")
    assert home["change"] > 0


def test_empty_row_hash_is_not_a_replay_pass():
    # hash_rows([]) is a truthy 64-char string, so replay_verify's old
    # `bool(stored) and rows_hash == stored` compared the sentinel to a
    # recomputed copy of itself and returned True — a green tick over a figure
    # with no row basis. An empty row set is UNVERIFIABLE, not verified.
    from storage import lineage
    sentinel = hash_rows([])
    assert lineage.EMPTY_ROWS_HASH == sentinel
    assert bool(sentinel), "the sentinel is truthy — that is the whole trap"

    row = {"dataset_id": 1, "op": "timeliness_slippage_corr", "params": {},
           "result_value": 0.538, "rows_hash": sentinel}
    assert lineage.replay_verify(
        None, row, compute=lambda op_row: (0.538, sentinel)) is False

    # a real row basis still verifies, and a mismatch still fails
    real = hash_rows([{"agency_key": "a", "agency_name": "A", "fy": "2024-25",
                       "quarter": None, "measure_group": "g", "measure": "m",
                       "bucket": "total", "value": 1.0, "derived": False}])
    good = dict(row, rows_hash=real)
    assert lineage.replay_verify(
        None, good, compute=lambda op_row: (0.538, real)) is True
    assert lineage.replay_verify(
        None, good, compute=lambda op_row: (0.538, sentinel)) is False
