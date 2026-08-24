# src/risk/forecast.py — forecast section renderer (honest until fitted)
from __future__ import annotations
import json
import os


def _not_fitted(title):
    return (
        f"<section class=\"risk-section\"><h2>Forecast &mdash; {title}</h2>"
        "<p class=\"risk-absent\">Not yet fitted. Run "
        "<code>scripts/fit_risk_models.py</code>.</p></section>"
    )


def _load_points(path):
    """Load the [{fy, value, lo, hi}] sidecar, or None when absent, unreadable
    or malformed — never a 500, never a fabricated number."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return None
        out = []
        for row in data:
            if not isinstance(row, dict):
                return None
            out.append({"fy": row["fy"], "value": float(row["value"]),
                        "lo": float(row["lo"]), "hi": float(row["hi"])})
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return None


def render_forecast_section(meta, model_dir, series=None):
    """Render the fitted forecast from the predictions.json sidecar.

    The fit script (scripts/fit_risk_models.py) runs prediction at fit time and
    writes [{fy, value, lo, hi}] to os.path.join(model_dir, "predictions.json").
    This renderer never imports autogluon and never live-predicts: a missing or
    unparseable sidecar renders the honest not-fitted block. `series` is kept
    for signature compatibility (load.py passes it) but no longer drives the
    render.
    """
    points = _load_points(os.path.join(model_dir, "predictions.json"))
    if points is None:
        return _not_fitted("request volume")
    rows = "".join(
        f"<tr><td>{p['fy']}</td><td>{p['value']}</td></tr>" for p in points)
    return (
        "<section class=\"risk-section\"><h2>Forecast &mdash; request volume</h2>"
        f"<p class=\"provenance\">model {meta.get('model')} &middot; fitted "
        f"{meta.get('fitted_at')} &middot; basis {meta.get('basis')} &middot; "
        f"rows {meta.get('source_rows')} &middot; hash {meta.get('rows_hash')}</p>"
        f"<table><thead><tr><th>FY</th><th>forecast</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )
