import sys
sys.path.insert(0, "src")
import pandas as pd
from risk.features import build_agency_features, build_forecast_series


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
