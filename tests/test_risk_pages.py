import json
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


def test_fitted_forecast_renders_model_numbers_with_provenance(tmp_path):
    from risk import forecast as fmod
    model_dir = tmp_path / "forecast"
    model_dir.mkdir()
    (model_dir / "predictions.json").write_text(json.dumps([
        {"fy": "2021-22", "value": 110.0, "lo": 90.0, "hi": 130.0},
        {"fy": "2022-23", "value": 120.0, "lo": 95.0, "hi": 145.0},
        {"fy": "2023-24", "value": 130.0, "lo": 100.0, "hi": 160.0},
    ]), encoding="utf-8")
    meta = {"model": "chronos", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc"}
    html = fmod.render_forecast_section(
        meta, str(model_dir),
        {"fy": ["2019-20", "2020-21"], "values": [10.0, 20.0]})
    assert "110.0" in html        # model-computed (stub sidecar) — not fabricated
    assert "2021-22" in html      # the sidecar FY renders
    assert "chronos" in html      # provenance
    assert "2026-08-24" in html   # fitted-at provenance
    assert "12359" not in html


def test_fitted_classify_renders_tiers_with_provenance(tmp_path):
    from risk import classify as cmod
    model_dir = tmp_path / "classify"
    model_dir.mkdir()
    (model_dir / "tiers.json").write_text(json.dumps([
        {"agency": "A", "tier": "medium", "prob": 0.62},
    ]), encoding="utf-8")
    meta = {"model": "tabpfn", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc"}
    html = cmod.render_classify_section(
        meta, str(model_dir), __import__("pandas").DataFrame(
            {"agency": ["A"], "fy": ["2020-21"], "received": [20.0]}))
    assert "medium" in html
    assert "62%" in html
    assert "tabpfn" in html
    assert "12359" not in html


def test_missing_or_malformed_sidecar_renders_not_fitted(tmp_path):
    from risk import classify as cmod
    from risk import forecast as fmod
    meta = {"model": "chronos", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc"}
    # no sidecar at all -> honest not-fitted
    fdir = tmp_path / "forecast-missing"
    fdir.mkdir()
    cdir = tmp_path / "classify-missing"
    cdir.mkdir()
    assert "Not yet fitted" in fmod.render_forecast_section(meta, str(fdir), {})
    assert "Not yet fitted" in cmod.render_classify_section(meta, str(cdir), None)
    assert "12359" not in fmod.render_forecast_section(meta, str(fdir), {})
    assert "12359" not in cmod.render_classify_section(meta, str(cdir), None)
    # malformed sidecar (not a list / not valid JSON) -> honest not-fitted
    fdir2 = tmp_path / "forecast-malformed"
    fdir2.mkdir()
    (fdir2 / "predictions.json").write_text(json.dumps({"oops": True}),
                                            encoding="utf-8")
    cdir2 = tmp_path / "classify-malformed"
    cdir2.mkdir()
    (cdir2 / "tiers.json").write_text("not json", encoding="utf-8")
    assert "Not yet fitted" in fmod.render_forecast_section(meta, str(fdir2), {})
    assert "Not yet fitted" in cmod.render_classify_section(meta, str(cdir2), None)
    assert "12359" not in fmod.render_forecast_section(meta, str(fdir2), {})
    assert "12359" not in cmod.render_classify_section(meta, str(cdir2), None)
