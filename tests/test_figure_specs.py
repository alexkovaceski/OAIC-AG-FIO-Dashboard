"""FIGURE_SPECS — the declarative engine contract (spec S2.1).

The generic _figure must reproduce the legacy per-key outputs exactly;
these tests pin the spec vocabulary and the output-identity property.
"""
import sys; sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from storage.frame import Frame
from stats import catalog
from stats.catalog import FIG_KEYS, FIGURE_SPECS, LATEST_COMPLETE_FY, foi_stats


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


def test_top_n_spec_takes_fy_parameter():
    # the server default uses LATEST_COMPLETE_FY; the spec carries it so the
    # client can override with the FY filter (B6/B7 fix)
    for key in ("received_top20", "decided_top20"):
        assert FIGURE_SPECS[key]["default_fy"] == LATEST_COMPLETE_FY
        assert FIGURE_SPECS[key]["n"] == 20


def test_movers_stats_default_to_latest_complete_pair():
    frame = Frame(normalise_all())
    out = foi_stats(frame, "refusal_rate_movers")
    assert out["basis"] == "fy"
    assert out["value"]["fy_a"] == "2023-24" and out["value"]["fy_b"] == "2024-25"
    assert out["value"]["movers"], "no movers computed"
    top = out["value"]["movers"][0]
    assert set(top) == {"agency", "fy_a_rate", "fy_b_rate", "change"}

    t = foi_stats(frame, "timeliness_movers")
    assert t["value"]["movers"], "no timeliness movers"


def test_legacy_movers_key_still_works():
    # src/agentic/report.py routes "refusal rate" to this key and renders
    # stat["value"] directly — it must stay a bare LIST, not the new dict
    frame = Frame(normalise_all())
    out = foi_stats(frame, "refusal_rate_change_fy23_fy24")
    assert out["value"], "legacy key must keep returning movers"
    assert isinstance(out["value"], list), "legacy key must stay a bare list"
    assert set(out["value"][0]) == {"agency", "fy_a_rate", "fy_b_rate", "change"}


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
