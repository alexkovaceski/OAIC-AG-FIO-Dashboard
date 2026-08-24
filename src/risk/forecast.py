# src/risk/forecast.py — forecast section renderer (honest until fitted)
from __future__ import annotations


def _get_predictor():
    # lazy: autogluon is only imported when the forecast artifact is present
    from autogluon.timeseries import TimeSeriesPredictor
    return TimeSeriesPredictor


def _not_fitted(title):
    return (
        f"<section class=\"risk-section\"><h2>Forecast &mdash; {title}</h2>"
        "<p class=\"risk-absent\">Not yet fitted. Run "
        "<code>scripts/fit_risk_models.py</code>.</p></section>"
    )


def render_forecast_section(meta, model_dir, series=None):
    """Series is the build_forecast_series dict. When the model artifact or
    series is absent, render the honest not-fitted block (never fabricate)."""
    if series is None:
        return _not_fitted("request volume")
    try:
        TSP = _get_predictor()
        pred = TSP.load(model_dir)
    except Exception:
        return _not_fitted("request volume")
    points = _points(pred.predict(series))  # Task 5 defines _points
    rows = "".join(
        f"<tr><td>{p['fy']}</td><td>{p['value']:.0f}</td></tr>" for p in points)
    return (
        "<section class=\"risk-section\"><h2>Forecast &mdash; request volume</h2>"
        f"<p class=\"provenance\">model {meta.get('model')} &middot; fitted "
        f"{meta.get('fitted_at')} &middot; basis {meta.get('basis')} &middot; "
        f"rows {meta.get('source_rows')} &middot; hash {meta.get('rows_hash')}</p>"
        f"<table><thead><tr><th>FY</th><th>forecast</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )
