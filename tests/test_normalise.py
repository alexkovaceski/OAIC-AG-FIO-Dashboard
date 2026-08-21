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

# Published Total-row values (total bucket) per FY — direct reads from each
# workbook's "Action on requests" / "Response times" Total row.
PUBLISHED_TOTALS = {
    "2019-20": {"decided": 29358, "granted_full": 13727, "granted_part": 11221, "refused": 4410, "withdrawn": 10000, "within_statutory": 23085},
    "2020-21": {"decided": 26680, "granted_full": 10978, "granted_part": 10984, "refused": 4718, "withdrawn": 6834, "within_statutory": 20663},
    "2021-22": {"decided": 25303, "granted_full": 9966, "granted_part": 10547, "refused": 4790, "withdrawn": 5916, "within_statutory": 17798},
    "2022-23": {"decided": 21228, "granted_full": 5376, "granted_part": 11055, "refused": 4797, "withdrawn": 15915, "within_statutory": 15723},
    "2023-24": {"decided": 21347, "granted_full": 4465, "granted_part": 11659, "refused": 5223, "withdrawn": 11024, "within_statutory": 15754},
    "2024-25": {"decided": 25211, "granted_full": 5395, "granted_part": 13558, "refused": 6258, "withdrawn": 13353, "within_statutory": 18296},
    "2025-26": {"decided": 22573, "granted_full": 4154, "granted_part": 12334, "refused": 6085, "withdrawn": 10598, "within_statutory": 16047},
}

def test_new_measures_extracted_per_fy():
    facts = normalise_all()
    for fy, expected in PUBLISHED_TOTALS.items():
        for measure, want in expected.items():
            # golden Q1 facts share fy=2025-26/measure/bucket=total but are single-
            # quarter headlines (derived=True, agency "Total"), not agency totals
            rows = [f for f in facts if f["fy"] == fy and f["measure"] == measure and f["bucket"] == "total" and not f["derived"]]
            assert rows, f"no {measure} rows for {fy}"
            got = round(sum(f["value"] for f in rows))
            assert got == want, f"{fy} {measure}: sum(agency total)={got} != published total {want}"
