"""normalise — resolve every data quirk once, emit long-form facts."""
from __future__ import annotations
from pathlib import Path
from config import DATA_SOURCES_DIR, GOLDEN_Q1_FIGURES
from ingest.xlsx import read_sheets
from ingest.mog import normalise_agency, PORTFOLIO_MAP

def _num(v):
    if v is None: return 0
    if isinstance(v, (int, float)): return float(v)
    try: return float(str(v).strip().replace(",", ""))
    except: return 0

# column layout (current file): 0 Agency, 1-3 OnHand(P,O,T), 4-6 RecvApplicant(P,O,T),
# 7-9 Transfer(P,O,T), 10-12 TotalReceived(P,O,T), 13-15 %share, 16-18 Finalised(P,O,T),
# 19 onhand31mar, 20-21 onhand30jun
MEASURE_COLS = {
    "received": (4, 5, 6),    # personal, other, total
    "finalised": (16, 17, 18),
}

def _fact(agency_key, agency_name, fy, quarter, group, measure, bucket, value, derived=False):
    return {"agency_key": agency_key, "agency_name": agency_name, "fy": fy,
            "quarter": quarter, "measure_group": group, "measure": measure,
            "bucket": bucket, "value": _num(value), "derived": derived,
            "portfolio": PORTFOLIO_MAP.get(agency_name, "")}

def _agency_facts(sheet_rows, fy, quarter, measure_group):
    facts = []
    for r in sheet_rows[3:]:  # skip header + repeated-name rows
        if not r[0]: continue
        name = str(r[0]).strip()
        if name.startswith("x") or name.startswith("xx"): continue
        if name.lower() == "total": continue  # Total row is a trusted value, not a fact
        key = normalise_agency(name)
        for measure, (pc, oc, tc) in MEASURE_COLS.items():
            facts.append(_fact(key, name, fy, quarter, measure_group, measure, "personal", _num(r[pc])))
            facts.append(_fact(key, name, fy, quarter, measure_group, measure, "other", _num(r[oc])))
            facts.append(_fact(key, name, fy, quarter, measure_group, measure, "total", _num(r[tc])))
    return facts

# map golden Q1 constants to fact measures (all bucket=total, quarter=1)
_GOLDEN_MEASURE = {
    "requests_received": "received", "finalised": "finalised", "decided": "decided",
    "within_statutory": "within_statutory", "granted_full": "granted_full",
    "granted_part": "granted_part", "refused": "refused", "withdrawn": "withdrawn",
}

def _golden_q1_facts() -> list[dict]:
    """Q1 2025-26 single-quarter headline figures from the published Power BI
    values (golden ground truth). Marked derived=True because they are not
    recoverable by differencing the Q1-Q3 cumulative file."""
    out = []
    for key, val in GOLDEN_Q1_FIGURES.items():
        out.append(_fact("_all", "Total", "2025-26", 1, "requests",
                         _GOLDEN_MEASURE[key], "total", val, derived=True))
    return out

def normalise_all(source_dir: Path = DATA_SOURCES_DIR) -> list[dict]:
    facts = []
    # annual files: FY totals, quarter=None
    for year, fn in [("2019-20","agency-foi-data-2019-20.xlsx"), ("2020-21","agency-foi-data-2020-21.xlsx"),
                     ("2021-22","agency-foi-data-2021-22.xlsx"), ("2022-23","agency-foi-data-2022-23.xlsx"),
                     ("2023-24","agency-foi-data-2023-24.xlsx"), ("2024-25","agency-foi-data-2024-25.xlsx")]:
        sheets = read_sheets(source_dir / fn)
        facts += _agency_facts(sheets["Request numbers"], year, None, "requests")
    # current file: Q1-Q3 cumulative (quarter=None, cumulative window)
    cur = read_sheets(source_dir / "agency-foi-data-2025-26-q1-to-q3.xlsx")
    facts += _agency_facts(cur["Request numbers"], "2025-26", None, "requests")
    # single-quarter Q1 2025-26 headline: published golden figures, marked derived
    facts += _golden_q1_facts()
    return facts
