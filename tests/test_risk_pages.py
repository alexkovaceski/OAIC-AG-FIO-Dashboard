import sys
sys.path.insert(0, "src")
from risk.load import load_risk_artifacts, risk_page_html


def test_model_absent_state_renders_honest():
    html = risk_page_html({"username": "alice", "role": "internal"},
                          None, artifacts=None)
    assert "not yet fitted" in html
    assert "fit_risk_models" in html
    assert "12359" not in html  # never a fabricated figure


def test_artifacts_present_but_models_missing_renders_not_fitted(tmp_path):
    meta = {"model": "chronos", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc",
            "feature_version": "1", "base": str(tmp_path)}
    html = risk_page_html({"username": "alice", "role": "internal"},
                          None, artifacts=meta)
    assert "Not yet fitted" in html          # both sections honest
    assert "chronos" in html                 # provenance footer
    assert "2026-08-24" in html              # fitted-at provenance
    assert "12359" not in html


def test_load_artifacts_returns_none_when_absent(tmp_path):
    assert load_risk_artifacts(str(tmp_path / "missing")) is None


def test_model_absent_path_never_imports_autogluon():
    import sys
    risk_page_html({"role": "internal"}, None, artifacts=None)
    assert "autogluon" not in sys.modules
