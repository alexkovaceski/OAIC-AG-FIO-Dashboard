"""Frame — the in-memory fact frame the agent path reads. Read-only + golden-checked."""
from config import GOLDEN_Q1_FIGURES

class Frame:
    def __init__(self, facts: list[dict]):
        self.facts = facts

    def filter(self, *, fy=None, quarter=None, measure=None, bucket=None, agency=None):
        out = self.facts
        if fy is not None: out = [f for f in out if f["fy"] == fy]
        if quarter is not None: out = [f for f in out if f["quarter"] == quarter]
        if measure is not None: out = [f for f in out if f["measure"] == measure]
        if bucket is not None: out = [f for f in out if f["bucket"] == bucket]
        if agency is not None: out = [f for f in out if f["agency_name"] == agency]
        return out

    def summarize(self, facts=None, measure="received", bucket="total"):
        # `facts or self.facts` would silently fall back to the whole frame on
        # an empty filtered list — a wrong number produced without an error.
        if facts is None:
            facts = self.facts
        return round(sum(f["value"] for f in facts if f["measure"] == measure and f["bucket"] == bucket), 0)

    def golden_check(self):
        # the normaliser emits golden Q1 facts with translated measure names
        # (ingest.normalise._GOLDEN_MEASURE), e.g. "received" for the
        # "requests_received" golden key — match on the fact measure, not the key.
        from ingest.normalise import _GOLDEN_MEASURE
        for key, expected in GOLDEN_Q1_FIGURES.items():
            # single-quarter Q1: derived rows for FY2025-26 quarter=1
            q1 = [f for f in self.facts if f["fy"] == "2025-26" and f["quarter"] == 1 and f["measure"] == _GOLDEN_MEASURE[key] and f["bucket"] == "total"]
            got = round(sum(f["value"] for f in q1), 0)
            if got != expected:
                raise SystemExit(f"GOLDEN CHECK FAILED: {key} = {got}, expected {expected} - data or normaliser is wrong")
