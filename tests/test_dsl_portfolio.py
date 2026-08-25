"""by_portfolio must never return a silently-degenerate single bucket."""
from stats.dsl import query_dataset
from storage.frame import Frame


def _fact(agency, fy, value, portfolio):
    return {"agency_key": agency, "agency_name": agency, "fy": fy,
            "quarter": None, "measure_group": "requests", "measure": "received",
            "bucket": "total", "value": float(value), "derived": False,
            "portfolio": portfolio}


def test_by_portfolio_errors_when_wholly_unmapped():
    frame = Frame([_fact("A", "2024-25", 10, ""), _fact("B", "2024-25", 20, "")])
    out = query_dataset(frame, "by_portfolio", {"fy": "2024-25"})
    assert "error" in out, out
    assert "portfolio" in out["error"].lower()


def test_by_portfolio_reports_partial_coverage():
    frame = Frame([_fact("A", "2024-25", 10, "Health"),
                   _fact("B", "2024-25", 20, "")])
    out = query_dataset(frame, "by_portfolio", {"fy": "2024-25"})
    assert out.get("portfolios") == [{"portfolio": "Health", "value": 10}]
    assert out.get("unmapped_agency_count") == 1


def test_by_portfolio_aggregates_mapped_facts():
    frame = Frame([_fact("A", "2024-25", 10, "Health"),
                   _fact("B", "2024-25", 20, "Health"),
                   _fact("C", "2024-25", 5, "Treasury")])
    out = query_dataset(frame, "by_portfolio", {"fy": "2024-25"})
    assert out["portfolios"] == [{"portfolio": "Health", "value": 30},
                                 {"portfolio": "Treasury", "value": 5}]
    assert out.get("unmapped_agency_count") == 0


def test_by_portfolio_excludes_golden_total():
    """Regression: the golden 'Total' pseudo-agency must be filtered out,
    even when it carries a portfolio. This test verifies the exclusion filter
    (agency_name.lower() != "total") works, not the unmapped-split fallback."""
    frame = Frame([_fact("A", "2024-25", 10, "Health"),
                   # golden Total with a portfolio should be excluded
                   _fact("Total", "2024-25", 1000, "Health"),
                   _fact("B", "2024-25", 20, "Treasury")])
    out = query_dataset(frame, "by_portfolio", {"fy": "2024-25"})
    # Golden Total (1000) must not be included in Health's sum; results sorted by value desc
    assert out["portfolios"] == [{"portfolio": "Treasury", "value": 20},
                                 {"portfolio": "Health", "value": 10}]
    assert out.get("unmapped_agency_count") == 0
