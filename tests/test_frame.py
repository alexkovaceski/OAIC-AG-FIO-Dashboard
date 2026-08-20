from pathlib import Path
import sys; sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from storage.frame import Frame
from config import GOLDEN_Q1_FIGURES

def test_golden_check_passes():
    facts = normalise_all()
    f = Frame(facts)
    f.golden_check()  # should not raise

def test_golden_check_aborts_on_mismatch():
    facts = normalise_all()
    q1 = [f for f in facts if f["fy"] == "2025-26" and f["quarter"] == 1]
    q1[0]["value"] = 999  # corrupt a golden Q1 fact
    f = Frame(facts)
    try:
        f.golden_check()
        assert False, "should have raised"
    except SystemExit:
        pass  # abort loudly on mismatch

def test_summarize_empty_filter_returns_zero():
    facts = normalise_all()
    f = Frame(facts)
    # an empty filtered list must not fall back to the whole frame
    assert f.summarize(f.filter(fy="2099")) == 0
    assert f.summarize(f.filter(fy="2025-26", quarter=99)) == 0
