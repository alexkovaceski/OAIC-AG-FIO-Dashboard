# src/risk/forecast.py — forecast section renderer (end-user language)
from __future__ import annotations
import json
import os


def _not_fitted(title):
    return (
        f"<section class=\"risk-section\"><h2>{title}</h2>"
        "<p class=\"risk-absent\">Forecasts are not ready yet. They are "
        "generated when the source data is re-fitted.</p></section>"
    )


def load_points(path) -> list[dict] | None:
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


def summary(points: list[dict]) -> str:
    """A one-sentence plain-English reading of the forecast."""
    if not points:
        return ""
    avg = round(sum(p["value"] for p in points) / len(points))
    first, last = points[0]["value"], points[-1]["value"]
    if last > first * 1.05:
        trend = "grow"
    elif last < first * 0.95:
        trend = "fall"
    else:
        trend = "hold roughly steady"
    span = f"{points[0]['fy']} to {points[-1]['fy']}"
    return (f"Request volume is forecast to <strong>{trend}</strong>, averaging "
            f"about <strong>{avg:,}</strong> requests a year over {span}.")


def render_forecast_section(meta, model_dir, series=None) -> tuple[str, list | None]:
    """Render the request-volume forecast section.

    The fit script writes [{fy, value, lo, hi}] to forecast/predictions.json.
    This renderer never imports autogluon and never live-predicts: a missing or
    unparseable sidecar renders the honest not-fitted block. The chart itself is
    drawn client-side by risk.js from window.__riskData (historical series +
    forecast points), so the model names and technical details stay out of the
    reader-facing page.
    """
    points = load_points(os.path.join(model_dir, "predictions.json"))
    if points is None:
        return _not_fitted("Request volume forecast"), None
    rows = "".join(
        f"<tr><td>{p['fy']}</td><td>{p['value']:,.0f}</td>"
        f"<td>{p['lo']:,.0f} &ndash; {p['hi']:,.0f}</td></tr>" for p in points)
    html = (
        '<section class="risk-section"><h2>Request volume forecast</h2>'
        f'<p class="risk-summary">{summary(points)}</p>'
        '<div class="chartbox" id="forecast-chart" role="img" '
        'aria-label="Request volume forecast chart"></div>'
        '<details class="risk-details"><summary>Forecast numbers</summary>'
        '<table class="report-table"><thead><tr><th>Financial year</th>'
        '<th>Forecast</th><th>Range</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></details></section>'
    )
    return html, points
