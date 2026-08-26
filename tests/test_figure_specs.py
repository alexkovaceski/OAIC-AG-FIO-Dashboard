"""FIGURE_SPECS — the declarative engine contract (spec S2.1).

The generic _figure must reproduce the legacy per-key outputs exactly;
these tests pin the spec vocabulary and the output-identity property.
"""
import sys; sys.path.insert(0, "src")
import json

import pytest

import api
from ingest.normalise import normalise_all
from storage.frame import Frame
from stats import catalog
from stats.catalog import (FIG_KEYS, FIGURE_SPECS, LATEST_COMPLETE_FY,
                           MOVERS_MIN_DENOMINATOR, STAT_KEYS, foi_stats,
                           hash_rows, is_reporting_agency, partial_fys,
                           _figure_source_rows, _fy_series_source_rows,
                           _movers_source_rows, _previous_complete_fy)


def test_every_fig_key_has_a_spec():
    for key in FIG_KEYS:
        assert key in FIGURE_SPECS, f"no spec for {key}"
        assert FIGURE_SPECS[key]["kind"] in ("trend", "multi_trend",
                                             "ratio_trend", "top_n"), key


def test_latest_complete_fy_is_single_sourced():
    assert LATEST_COMPLETE_FY == "2024-25"
    import inspect
    src = inspect.getsource(catalog)
    # the only "2024-25" literal in catalog.py is the constant's own definition
    assert src.count('"2024-25"') == 1, \
        "top-N years must reference LATEST_COMPLETE_FY, not literals"


def test_partial_fys_are_derived_not_listed():
    # C1: the FY filter re-ranks a top-N for ANY published year, including
    # 2025-26 — whose annual file is a Q1-Q3 cumulative partial. Every
    # disclosure the pages and the chart engine make about that comes from
    # here, and it must be derived from LATEST_COMPLETE_FY rather than named,
    # or the site carries two year literals that can drift apart.
    frame = Frame(normalise_all())
    annual = sorted({f["fy"] for f in frame.facts if f["quarter"] is None})
    assert partial_fys(frame) == ["2025-26"], partial_fys(frame)
    assert all(fy > LATEST_COMPLETE_FY for fy in partial_fys(frame))
    assert LATEST_COMPLETE_FY in annual and LATEST_COMPLETE_FY not in partial_fys(frame)

    row = {"agency_key": "a", "agency_name": "Agency A", "quarter": None,
           "measure_group": "requests", "measure": "received", "bucket": "total",
           "value": 10.0, "derived": False, "portfolio": ""}
    # a frame that ends at the latest complete year has no part year at all
    complete_only = Frame([dict(row, fy=LATEST_COMPLETE_FY)])
    assert partial_fys(complete_only) == []
    # and the next annual file to land is a part year until the constant moves
    with_next = Frame([dict(row, fy=LATEST_COMPLETE_FY), dict(row, fy="2999-00")])
    assert partial_fys(with_next) == ["2999-00"]
    # a quarter-carrying row is a separate basis and never makes an FY partial
    quarters = Frame([dict(row, fy=LATEST_COMPLETE_FY),
                      dict(row, fy="2999-00", quarter=1)])
    assert partial_fys(quarters) == []


def test_generic_figure_reproduces_legacy_outputs():
    # Output-identity: computed via the spec engine, pinned against values the
    # legacy branches produced (measured on the real frame, 2026-08-26).
    frame = Frame(normalise_all())
    fig = foi_stats(frame, "requests_received_trend")["value"]
    assert fig["categories"][0] == "2019-20" and fig["categories"][-1] == "2025-26"
    assert fig["series"][0]["name"] == "received"
    # MEASURE: pin the full values list printed by the discovery script before
    # running (it is the exact legacy output; the engine must match it).
    assert fig["series"][0]["values"] == [40691, 34345, 33820, 33630, 34153, 42759, 34418]

    outcomes = foi_stats(frame, "decision_outcomes_trend")["value"]
    assert [s["name"] for s in outcomes["series"]] == [
        "granted_full", "granted_part", "refused", "withdrawn"]

    ratio = foi_stats(frame, "granted_full_part_change")["value"]
    assert ratio["series"][0]["name"] == "granted_full_or_part_pct"
    assert ratio["series"][0]["values"] == [85.0, 82.3, 81.1, 77.4, 75.5, 75.2, 73.0]

    top = foi_stats(frame, "received_top20")["value"]
    assert len(top["categories"]) == 20
    assert top["categories"][0] == "Department of Home Affairs"
    assert top["series"][0]["values"][0] == 17120


def test_timeliness_caption_and_correlation_describe_what_is_published():
    # Stale-record sweep: the annual files have published decisions, outcomes
    # and timeliness since 43fad97. The caption still promised a within/after
    # split that is not ingested, and the correlation's comment still claimed a
    # degenerate None it no longer returns.
    from stats.catalog import FIG_CAPTIONS
    assert FIG_CAPTIONS["timeliness_trend"] == \
        "Timeliness of decision-making (within statutory)"
    frame = Frame(normalise_all())
    within = catalog._fy_series(frame, "within_statutory")
    assert within and all(v is not None for v in within), \
        "within_statutory has an annual series — the caption/comment must agree"
    corr = foi_stats(frame, "timeliness_slippage_corr")
    assert corr["value"] is not None and -1 <= corr["value"] <= 1, \
        "the correlation is a real coefficient over two published FY series"


def test_correlation_publishes_the_rows_it_actually_consumed():
    # F1: the stat computed a real 0.538 and reported source_rows=0 with
    # rows_hash=hash_rows([]) — a false provenance claim shipped to the user by
    # agentic/report.py as dataset_registry, and a sentinel that made
    # replay_verify compare itself to itself and return a green tick.
    frame = Frame(normalise_all())
    corr = foi_stats(frame, "timeliness_slippage_corr")
    empty_sentinel = hash_rows([])
    assert corr["source_rows"] > 0, "a computed correlation consumed no rows"
    assert corr["rows_hash"] != empty_sentinel, \
        "the hash is the empty-row sentinel — nothing to replay against"
    # and the basis is the exact rows: annual, bucket=total, both correlated
    # measures, real reporting agencies only
    expected = _fy_series_source_rows(frame, ("within_statutory", "received"))
    assert corr["source_rows"] == len(expected)
    assert corr["rows_hash"] == hash_rows(expected)
    for row in expected:
        assert row["quarter"] is None and row["bucket"] == "total"
        assert row["measure"] in ("within_statutory", "received")
        assert catalog.is_reporting_agency(row["agency_name"])


def test_no_stat_hashes_an_empty_row_set_while_computing_a_value():
    # the general form of F1: a {value, basis, source_rows, rows_hash} result
    # that carries a real value must carry a real row basis. hash_rows([]) is
    # truthy, so a sentinel here is worse than a missing hash.
    frame = Frame(normalise_all())
    empty_sentinel = hash_rows([])
    for key in list(FIG_KEYS) + list(STAT_KEYS):
        stat = foi_stats(frame, key)
        if stat["value"] is None:
            continue
        assert stat["source_rows"] > 0, f"{key}: real value, zero source rows"
        assert stat["rows_hash"] != empty_sentinel, \
            f"{key}: real value, empty-row hash sentinel"


def test_top_n_spec_takes_fy_parameter():
    # the server default uses LATEST_COMPLETE_FY; the spec carries it so the
    # client can override with the FY filter (B6/B7 fix)
    for key in ("received_top20", "decided_top20"):
        assert FIGURE_SPECS[key]["default_fy"] == LATEST_COMPLETE_FY
        assert FIGURE_SPECS[key]["n"] == 20


MOVER_ROW_KEYS = {"agency", "fy_a_rate", "fy_b_rate", "change",
                  "fy_a_denominator", "fy_b_denominator"}


def test_movers_stats_default_to_latest_complete_pair():
    # the FY pair comes from the single-sourced constant, never from literals
    # here — bumping LATEST_COMPLETE_FY must not break this file (N6)
    frame = Frame(normalise_all())
    out = foi_stats(frame, "refusal_rate_movers")
    assert out["basis"] == "fy"
    assert out["value"]["fy_a"] == _previous_complete_fy(frame)
    assert out["value"]["fy_b"] == LATEST_COMPLETE_FY
    assert out["value"]["movers"], "no movers computed"
    top = out["value"]["movers"][0]
    assert set(top) == MOVER_ROW_KEYS

    t = foi_stats(frame, "timeliness_movers")
    assert t["value"]["movers"], "no timeliness movers"


def test_movers_floor_excludes_small_denominator_agencies():
    # C1: the page-facing movers ranked pure sampling noise. Measured on the
    # real frame before the floor, all ten rendered refusal-rate rows had a
    # `decided` denominator of 1-5 and the largest denominator anywhere in
    # either table was 20 ("Asbestos and Silica Safety and Eradication Agency
    # 0.0% -> 100.0%" was one refused request out of two decisions).
    frame = Frame(normalise_all())
    assert MOVERS_MIN_DENOMINATOR >= 30, "the floor is the whole point"
    for key in ("refusal_rate_movers", "timeliness_movers"):
        value = foi_stats(frame, key)["value"]
        assert value["min_denominator"] == MOVERS_MIN_DENOMINATOR
        assert value["denominator"] == "decided"
        assert len(value["movers"]) >= 10, \
            f"{key}: the floor left too few agencies for a top 10"
        for mover in value["movers"]:
            assert mover["fy_a_denominator"] >= MOVERS_MIN_DENOMINATOR, mover
            assert mover["fy_b_denominator"] >= MOVERS_MIN_DENOMINATOR, mover

    # and the floor genuinely bites: the unfloored list is much longer
    unfloored = catalog._rate_movers(frame, "refused", "decided",
                                     _previous_complete_fy(frame),
                                     LATEST_COMPLETE_FY)
    floored = foi_stats(frame, "refusal_rate_movers")["value"]["movers"]
    assert len(unfloored) > len(floored) * 2, \
        f"{len(unfloored)} unfloored vs {len(floored)} floored — floor is inert"


def test_movers_stats_hash_only_the_rows_they_read():
    # I2: the stat hashed every bucket="total" row of both FYs (5247) when it
    # read only the two measures (1166), so both stats returned the IDENTICAL
    # rows_hash despite computing different values — replay could not tell them
    # apart and an unrelated measure changing false-alarmed both.
    frame = Frame(normalise_all())
    refusal = foi_stats(frame, "refusal_rate_movers")
    timeliness = foi_stats(frame, "timeliness_movers")
    assert refusal["rows_hash"] != timeliness["rows_hash"], \
        "two stats over different measures must not share a hash"

    every_total_row = len(frame.filter(fy=_previous_complete_fy(frame), bucket="total")) \
        + len(frame.filter(fy=LATEST_COMPLETE_FY, bucket="total"))
    assert refusal["source_rows"] < every_total_row, \
        "source_rows still counts rows the stat never read"
    expected = _movers_source_rows(frame, "refused", "decided",
                                   _previous_complete_fy(frame), LATEST_COMPLETE_FY)
    assert refusal["source_rows"] == len(expected)
    assert refusal["rows_hash"] == catalog.hash_rows(expected)


def test_movers_source_rows_are_annual_real_agency_rows_only():
    # I4 + M3: frame.filter applies NO quarter constraint, and _rate_movers
    # excluded neither the golden "Total" pseudo-agency nor x-prefixed rows.
    # Inert only while LATEST_COMPLETE_FY predates the golden rows.
    frame = Frame(normalise_all())
    rows = _movers_source_rows(frame, "refused", "decided",
                               _previous_complete_fy(frame), LATEST_COMPLETE_FY)
    assert rows
    assert all(f["quarter"] is None for f in rows), "a quarter row entered an FY sum"
    assert all(f["bucket"] == "total" for f in rows)
    assert all(f["measure"] in ("refused", "decided") for f in rows)
    assert all(f["agency_name"].lower() != "total" for f in rows)

    # a synthetic frame that actually carries both traps
    annual = {"agency_key": "a", "agency_name": "Agency A", "fy": LATEST_COMPLETE_FY,
              "quarter": None, "measure_group": "decisions", "measure": "decided",
              "bucket": "total", "value": 10.0, "derived": False, "portfolio": ""}
    trapped = Frame([
        annual,
        dict(annual, agency_name="Total", agency_key="total"),
        dict(annual, agency_key="q", quarter=1, value=99.0),
        dict(annual, agency_key="xplaceholder", agency_name="xplaceholder"),
    ])
    kept = _movers_source_rows(trapped, "refused", "decided",
                               "2000-01", LATEST_COMPLETE_FY)
    assert [f["agency_name"] for f in kept] == ["Agency A"]


def test_previous_complete_fy_raises_instead_of_wrapping():
    # I1: cats.index() returns 0 when LATEST_COMPLETE_FY is the FIRST category,
    # so cats[i - 1] wrapped to cats[-1] — the NEWEST year — and every change
    # silently flipped sign. Measured on a frame trimmed to the two latest FYs,
    # the old code returned the newer year as the "previous complete FY".
    row = {"agency_key": "a", "agency_name": "Agency A", "quarter": None,
           "measure_group": "decisions", "measure": "decided", "bucket": "total",
           "value": 10.0, "derived": False, "portfolio": ""}
    first_of_the_frame = Frame([dict(row, fy=LATEST_COMPLETE_FY),
                                dict(row, fy="2999-00")])
    with pytest.raises(KeyError):
        _previous_complete_fy(first_of_the_frame)

    absent = Frame([dict(row, fy="2999-00")])
    with pytest.raises(KeyError):
        _previous_complete_fy(absent)

    # and the stats surface the same KeyError rather than an inverted answer
    for key in ("refusal_rate_movers", "timeliness_movers"):
        with pytest.raises(KeyError):
            foi_stats(first_of_the_frame, key)


def test_api_figures_survives_a_frame_without_an_fy_pair():
    # I1's blast radius: api.figures catches only KeyError, and dsl's kpis op
    # caught nothing. A stat that cannot form its FY pair must drop out, never
    # take the whole /api/figures payload down with it.
    # the real frame trimmed so LATEST_COMPLETE_FY is its EARLIEST annual year
    # (FY labels sort lexicographically, so no year literal is needed here)
    frame = Frame([f for f in normalise_all() if f["fy"] >= LATEST_COMPLETE_FY])
    with pytest.raises(KeyError):
        _previous_complete_fy(frame)
    out = api.figures(frame)                       # must not raise
    assert "refusal_rate_movers" not in out and "timeliness_movers" not in out
    assert "requests_received_trend" in out, "one bad key took the payload down"

    from stats.dsl import query_dataset
    kpis = query_dataset(frame, "kpis", {})        # must not raise either
    assert isinstance(kpis, dict)


def test_legacy_movers_key_still_works():
    # src/agentic/report.py routes "refusal rate" to this key and renders
    # stat["value"] directly — it must stay a bare LIST, not the new dict, and
    # it must keep min_denominator=0 (its rows are what the AI report ships).
    frame = Frame(normalise_all())
    out = foi_stats(frame, "refusal_rate_change_fy23_fy24")
    assert out["value"], "legacy key must keep returning movers"
    assert isinstance(out["value"], list), "legacy key must stay a bare list"
    assert set(out["value"][0]) == MOVER_ROW_KEYS
    # no floor here: small-denominator agencies are still ranked, and now the
    # denominator columns make that visible rather than hiding it
    assert min(m["fy_a_denominator"] for m in out["value"]) < MOVERS_MIN_DENOMINATOR


def test_top_n_ranks_annual_rows_of_real_agencies_only():
    # S1 (server twin of the client-side C3 fix): frame.filter applies no
    # quarter constraint and the golden "Total" pseudo-agency is not an agency.
    # Inert only while LATEST_COMPLETE_FY predates the golden rows.
    annual = {"agency_key": "a", "agency_name": "Agency A",
              "fy": FIGURE_SPECS["received_top20"]["default_fy"], "quarter": None,
              "measure_group": "requests", "measure": "received", "bucket": "total",
              "value": 10.0, "derived": False, "portfolio": ""}
    frame = Frame([
        annual,
        dict(annual, agency_key="total", agency_name="Total", value=9999.0),
        dict(annual, agency_key="q", quarter=1, value=5000.0),
        dict(annual, agency_key="xplaceholder", agency_name="xplaceholder"),
    ])
    fig = foi_stats(frame, "received_top20")["value"]
    assert fig["categories"] == ["Agency A"], fig["categories"]
    assert fig["series"][0]["values"] == [10], "a quarter row entered an FY total"

    # and the real frame's ranking is unchanged by the guards
    real = foi_stats(Frame(normalise_all()), "received_top20")["value"]
    assert real["categories"][0] == "Department of Home Affairs"
    assert real["series"][0]["values"][0] == 17120


def test_received_channel_trend_is_spec_driven():
    # B5 (spec S2.2): the Stage-1 received_transfer measure gets a figure with
    # zero new engine code — a plain multi_trend spec
    assert "received_channel_trend" in FIG_KEYS
    spec = FIGURE_SPECS["received_channel_trend"]
    assert spec["kind"] == "multi_trend"
    assert spec["measures"] == ["received", "received_transfer"]
    fig = foi_stats(Frame(normalise_all()), "received_channel_trend")["value"]
    assert [s["name"] for s in fig["series"]] == ["received", "received_transfer"]
    for s in fig["series"]:
        assert any(v is not None for v in s["values"]), "channel series is all None"


def test_ratio_trend_with_empty_operand_yields_empty_values():
    # legacy zip shape: an absent measure truncates the ratio to [], which is
    # what keeps _figure_has_data honest (a [None,...] list would ghost-render)
    facts = [{"agency_key": "A", "agency_name": "A", "fy": "2023-24",
              "quarter": None, "measure_group": "requests", "measure": "decided",
              "bucket": "total", "value": 10.0, "derived": False, "portfolio": ""}]
    frame = Frame(facts)
    # numerator 'refused' has zero rows in this frame
    fig = foi_stats(frame, "refused_pct_trend")["value"]
    assert fig["series"][0]["values"] == []


def test_every_figure_hashes_only_the_rows_its_spec_consumes():
    # The whole-frame hash made all 13 figure keys indistinguishable: replay
    # could not tell requests_received_trend from decided_top20, and an
    # unrelated measure changing false-alarmed every one of them.
    frame = Frame(normalise_all())
    total = len(frame.facts)
    hashes = {}
    for key in FIG_KEYS:
        stat = foi_stats(frame, key)
        assert 0 < stat["source_rows"] < total, \
            f"{key}: source_rows {stat['source_rows']} is not a real subset of {total}"
        hashes.setdefault(stat["rows_hash"], []).append(key)
    # Figures that consume genuinely different rows must hash differently. The
    # ONLY collision this permits is a byte-identical spec published under two
    # keys (received_top20/agency_contributions_received and the decided pair —
    # same measure, same n, same default FY, different page and caption).
    #
    # Comparing MEASURE SETS here instead would permit the regression this test
    # exists to catch: requests_decided_trend, decided_top20 and
    # agency_contributions_decided all declare the measure set {decided}, so
    # dropping the top_n FY narrowing in _figure_source_rows collapses 11
    # distinct hashes to 9 — a seven-year trend hashing identically to a
    # one-year top-20 ranking — and a measure-set check still passes.
    collisions = {h: ks for h, ks in hashes.items() if len(ks) > 1}
    for h, keys in collisions.items():
        specs = {json.dumps(FIGURE_SPECS[k], sort_keys=True) for k in keys}
        assert len(specs) == 1, \
            f"keys with different specs share hash {h[:12]}: {keys}"


def test_figure_source_rows_are_annual_reporting_rows():
    # same discipline as _movers_source_rows: annual rows only (no golden
    # single-quarter rows), the total bucket only (both server derivations read
    # it, so a bucket row entering the basis would hash rows no figure sums),
    # real reporting agencies only
    frame = Frame(normalise_all())
    for key in FIG_KEYS:
        for f in _figure_source_rows(frame, key):
            assert f["quarter"] is None, f"{key} hashes a quarter-carrying row"
            assert f["bucket"] == "total", \
                f"{key} hashes a non-total bucket row: {f['bucket']}"
            assert is_reporting_agency(f["agency_name"]), \
                f"{key} hashes a non-reporting agency: {f['agency_name']}"
