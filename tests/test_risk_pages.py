import json
import sys
sys.path.insert(0, "src")
from risk.load import load_risk_artifacts, risk_page_html


def test_model_absent_state_renders_honest():
    html = risk_page_html({"username": "alice", "role": "internal"},
                          None, artifacts=None)
    assert "not ready yet" in html
    assert "12359" not in html  # never a fabricated figure


def test_artifacts_present_but_models_missing_renders_not_fitted(tmp_path):
    meta = {"model": "chronos", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc",
            "feature_version": "1", "base": str(tmp_path)}
    html = risk_page_html({"username": "alice", "role": "internal"},
                          None, artifacts=meta)
    assert "not ready yet" in html              # both sections honest
    assert "Technical details" in html          # model tucked into a collapsed block
    assert "chronos" in html                    # still present for a reviewer
    assert "2026-08-24" in html
    assert "12359" not in html


def test_load_artifacts_returns_none_when_absent(tmp_path):
    assert load_risk_artifacts(str(tmp_path / "missing")) is None


def test_model_absent_path_never_imports_autogluon():
    risk_page_html({"role": "internal"}, None, artifacts=None)
    assert "autogluon" not in sys.modules


def test_fitted_forecast_renders_model_numbers(tmp_path):
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
    html, points = fmod.render_forecast_section(
        meta, str(model_dir),
        {"fy": ["2019-20", "2020-21"], "values": [10.0, 20.0]})
    assert points is not None and len(points) == 3
    assert "2021-22" in html                    # the sidecar FY renders
    assert "forecast" in html.lower()           # plain-English summary
    assert "chronos" not in html                # model name hidden from the section
    assert "12359" not in html


def test_fitted_classify_renders_tiers(tmp_path):
    from risk import classify as cmod
    model_dir = tmp_path / "classify"
    model_dir.mkdir()
    (model_dir / "tiers.json").write_text(json.dumps([
        {"agency": "A", "tier": "medium", "prob": 0.62},
    ]), encoding="utf-8")
    meta = {"model": "tabpfn", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc"}
    html, tiers = cmod.render_classify_section(
        meta, str(model_dir),
        __import__("pandas").DataFrame({"agency": ["A"], "fy": ["2020-21"],
                                        "received": [20.0]}))
    assert tiers is not None and len(tiers) == 1
    assert "Medium risk" in html                # end-user tier label
    assert "62%" in html
    assert "tabpfn" not in html                 # model name hidden
    assert "12359" not in html


def test_missing_or_malformed_sidecar_renders_not_fitted(tmp_path):
    from risk import classify as cmod
    from risk import forecast as fmod
    meta = {"model": "chronos", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc"}
    fdir = tmp_path / "forecast-missing"
    fdir.mkdir()
    cdir = tmp_path / "classify-missing"
    cdir.mkdir()
    fhtml, _ = fmod.render_forecast_section(meta, str(fdir), {})
    chtml, _ = cmod.render_classify_section(meta, str(cdir), None)
    assert "not ready yet" in fhtml
    assert "not ready yet" in chtml
    assert "12359" not in fhtml and "12359" not in chtml
    # malformed sidecar (not a list / not valid JSON) -> honest not-fitted
    fdir2 = tmp_path / "forecast-malformed"
    fdir2.mkdir()
    (fdir2 / "predictions.json").write_text(json.dumps({"oops": True}),
                                            encoding="utf-8")
    cdir2 = tmp_path / "classify-malformed"
    cdir2.mkdir()
    (cdir2 / "tiers.json").write_text("not json", encoding="utf-8")
    f2, _ = fmod.render_forecast_section(meta, str(fdir2), {})
    c2, _ = cmod.render_classify_section(meta, str(cdir2), None)
    assert "not ready yet" in f2 and "not ready yet" in c2


def test_classify_sidecar_with_non_numeric_prob_renders_not_fitted(tmp_path):
    from risk import classify as cmod
    meta = {"model": "tabpfn", "fitted_at": "2026-08-24T00:00:00Z",
            "basis": "fy", "source_rows": 100, "rows_hash": "abc"}
    cdir = tmp_path / "classify"
    cdir.mkdir()
    (cdir / "tiers.json").write_text(json.dumps([
        {"agency": "A", "tier": "medium", "prob": "high"},
    ]), encoding="utf-8")
    html, _ = cmod.render_classify_section(meta, str(cdir), None)
    assert "not ready yet" in html
    assert "12359" not in html
