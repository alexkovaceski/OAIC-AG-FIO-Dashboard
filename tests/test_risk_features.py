import sys
sys.path.insert(0, "src")
import pandas as pd
from risk.features import (build_agency_features, build_agency_series,
                           build_forecast_series)


def _fact(agency, fy, value):
    return {"agency_key": agency.lower(), "agency_name": agency, "fy": fy,
            "quarter": None, "measure_group": "g", "measure": "received",
            "bucket": "total", "value": value, "derived": False}


def test_build_agency_series_keeps_agencies_reporting_recently():
    # "Current" keeps reporting through the latest years; "Old" stops in 2021-22
    # (an abolished pre-2022 name) — its 3-year forecast would land in the past.
    facts = [_fact("Current", fy, 10.0)
             for fy in ("2023-24", "2024-25", "2025-26")] + [
             _fact("Old", fy, 10.0)
             for fy in ("2019-20", "2020-21", "2021-22")]
    out = build_agency_series(facts, "received", min_last_fy="2024-25")
    assert list(out) == ["Current"]
    assert "Old" not in out


def test_build_agency_series_no_recency_filter_keeps_both():
    facts = [_fact("Current", fy, 10.0)
             for fy in ("2023-24", "2024-25", "2025-26")] + [
             _fact("Old", fy, 10.0)
             for fy in ("2019-20", "2020-21", "2021-22")]
    out = build_agency_series(facts, "received")
    assert set(out) == {"Current", "Old"}


def test_build_agency_series_min_history_still_applies():
    facts = [_fact("OneYear", "2025-26", 10.0)] + [
             _fact("Old", fy, 10.0)
             for fy in ("2019-20", "2020-21", "2021-22")]
    out = build_agency_series(facts, "received", min_history=3,
                              min_last_fy="2024-25")
    assert out == {}  # OneYear has too few points, Old is too stale


def test_features_have_trailing_warmup_nan():
    facts = [
        {"agency_key": "a", "agency_name": "A", "fy": "2019-20", "quarter": None,
         "measure_group": "g", "measure": "received", "bucket": "total", "value": 10.0,
         "derived": False},
        {"agency_key": "a", "agency_name": "A", "fy": "2020-21", "quarter": None,
         "measure_group": "g", "measure": "received", "bucket": "total", "value": 20.0,
         "derived": False},
    ]
    df = build_agency_features(facts)
    a2019 = df[(df.agency == "A") & (df.fy == "2019-20")].iloc[0]
    assert pd.isna(a2019["received_yoy"])  # no lookahead, no fill


def test_forecast_series_is_pure_annual_fy():
    facts = [
        {"agency_key": "a", "agency_name": "A", "fy": "2019-20", "quarter": None,
         "measure_group": "g", "measure": "received", "bucket": "total", "value": 10.0,
         "derived": False},
        {"agency_key": "a", "agency_name": "A", "fy": "2019-20", "quarter": 1,
         "measure_group": "g", "measure": "received", "bucket": "total", "value": 2.0,
         "derived": False},
        {"agency_key": "a", "agency_name": "A", "fy": "2020-21", "quarter": None,
         "measure_group": "g", "measure": "received", "bucket": "total", "value": 20.0,
         "derived": False},
    ]
    s = build_forecast_series(facts, "received")
    assert s["fy"] == ["2019-20", "2020-21"]
    assert s["values"] == [10.0, 20.0]  # quarter row excluded


def test_bucket_total_not_double_counted():
    facts = [
        {"agency_key": "a", "agency_name": "A", "fy": "2020-21", "quarter": None,
         "measure_group": "g", "measure": "received", "bucket": "personal", "value": 6.0,
         "derived": False},
        {"agency_key": "a", "agency_name": "A", "fy": "2020-21", "quarter": None,
         "measure_group": "g", "measure": "received", "bucket": "other", "value": 4.0,
         "derived": False},
        {"agency_key": "a", "agency_name": "A", "fy": "2020-21", "quarter": None,
         "measure_group": "g", "measure": "received", "bucket": "total", "value": 10.0,
         "derived": False},
    ]
    df = build_agency_features(facts)
    row = df[(df.agency == "A") & (df.fy == "2020-21")].iloc[0]
    assert row["received"] == 10.0  # not 20.0 (personal + other + total)


def test_empty_facts_return_empty_frame():
    df = build_agency_features([])
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_features_no_annual_rows_returns_empty_frame():
    facts = [
        {"agency_key": "a", "agency_name": "A", "fy": "2025-26", "quarter": 1,
         "measure_group": "g", "measure": "received", "bucket": "total",
         "value": 12359.0, "derived": True},
    ]
    df = build_agency_features(facts)
    assert df.empty
