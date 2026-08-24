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


class _StubPredictor:
    def __init__(self):
        self.forecast = [{"fy": "2021-22", "value": 110.0},
                         {"fy": "2022-23", "value": 120.0},
                         {"fy": "2023-24", "value": 130.0}]
    def predict(self, series):
        return self.forecast


class _StubTSP:
    @classmethod
    def load(cls, path):
        return _StubPredictor()


def test_fitted_forecast_renders_model_numbers_with_provenance(monkeypatch, tmp_path):
    from risk import forecast as fmod
    monkeypatch.setattr(fmod, "_get_predictor", lambda: _StubTSP)
    model_dir = tmp_path / "forecast"
    model_dir.mkdir()
    meta = {"model": "chronos", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc"}
    html = fmod.render_forecast_section(
        meta, str(model_dir),
        {"fy": ["2019-20", "2020-21"], "values": [10.0, 20.0]})
    assert "110.0" in html        # model-computed (stub) — not fabricated
    assert "chronos" in html      # provenance
    assert "2026-08-24" in html   # fitted-at provenance


class _StubClassifier:
    def __init__(self):
        self.tiers = [{"agency": "A", "tier": "medium", "prob": 0.62}]
    def predict(self, features):
        return self.tiers


class _StubTP:
    @classmethod
    def load(cls, path):
        return _StubClassifier()


def test_fitted_classify_renders_tiers_with_provenance(monkeypatch, tmp_path):
    from risk import classify as cmod
    monkeypatch.setattr(cmod, "_get_tabular", lambda: _StubTP)
    model_dir = tmp_path / "classify"
    model_dir.mkdir()
    meta = {"model": "tabpfn", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc"}
    html = cmod.render_classify_section(
        meta, str(model_dir), __import__("pandas").DataFrame(
            {"agency": ["A"], "fy": ["2020-21"], "received": [20.0]}))
    assert "medium" in html
    assert "tabpfn" in html
