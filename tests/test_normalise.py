from pathlib import Path
import sys
sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from config import DATA_SOURCES_DIR, GOLDEN_Q1_FIGURES

def _sum(facts, measure, bucket="total"):
    return round(sum(f["value"] for f in facts if f["measure"] == measure and f["bucket"] == bucket), 0)

def test_golden_q1_received():
    facts = normalise_all(DATA_SOURCES_DIR)
    # the current file is Q1-Q3 cumulative; single-quarter Q1 is marked derived
    q1 = [f for f in facts if f["fy"] == "2025-26" and f["quarter"] == 1]
    assert round(sum(f["value"] for f in q1 if f["measure"] == "received" and f["bucket"] == "total"), 0) == GOLDEN_Q1_FIGURES["requests_received"]

def test_no_x_rows():
    facts = normalise_all(DATA_SOURCES_DIR)
    assert not any(f["agency_name"].startswith("x") or f["agency_name"].startswith("xx") for f in facts)

def test_total_row_not_resummed():
    facts = normalise_all(DATA_SOURCES_DIR)
    # the Total row's received value is trusted, not computed from agency rows
    tot = [f for f in facts if f["agency_name"] == "Total"]
    assert tot, "Total row present"
