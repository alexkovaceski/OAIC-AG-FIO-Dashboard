"""load — risk artifact loading + risk page render (honest until fitted)."""
from __future__ import annotations
import html
import json
import os
from pathlib import Path

from risk.classify import render_classify_section
from risk.features import build_forecast_series
from risk.forecast import render_forecast_section
from site.templates import chrome, _asset_link

_RISK_DIR = (Path(__file__).resolve().parent.parent.parent
             / "data" / "generated" / "risk")


def load_risk_artifacts(path=None):
    base = Path(path) if path else _RISK_DIR
    meta = base / "risk_metadata.json"
    if not meta.exists():
        return None
    try:
        m = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    m["base"] = str(base)
    return m


def risk_page_html(user, frame, artifacts=None):
    if artifacts is None:
        body = (
            "<h1>Risk &amp; Forecast</h1>"
            '<p class="intro">Forward-looking views over the published FOI '
            "statistics.</p>"
            '<p class="risk-absent">Forecasts and risk ratings are not ready '
            "yet. They are generated when the source data is re-fitted.</p>"
        )
        return chrome("Risk & Forecast", body, page_key="risk", user=user)
    return _fitted_page(user, frame, artifacts)


def _plain_date(iso) -> str:
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(iso)).strftime("%d %B %Y")
    except (ValueError, TypeError):
        return str(iso or "unknown")


def _fitted_page(user, frame, artifacts):
    base = artifacts.get("base", "")
    forecast_dir = os.path.join(base, "forecast")
    classify_dir = os.path.join(base, "classify")
    series = (build_forecast_series(frame.facts, "received")
              if frame is not None else None)
    forecast_html, points = render_forecast_section(artifacts, forecast_dir,
                                                    series)
    classify_html, tiers = render_classify_section(artifacts, classify_dir)
    risk_data = {
        "forecast": {"historical": series, "points": points or []},
        "tiers": tiers or [],
    }
    # the JSON blob must never break out of its <script> tag (mirrors __pageData)
    blob = json.dumps(risk_data).replace("</", "<\\/")
    updated = _plain_date(artifacts.get("fitted_at"))
    body = (
        "<h1>Risk &amp; Forecast</h1>"
        '<p class="intro">Forward-looking views over the published FOI '
        "statistics &mdash; a forecast of request volume and a risk rating for "
        "each agency, explained in plain language.</p>"
        + forecast_html + classify_html
        + '<p class="provenance">Last updated '
        + html.escape(updated)
        + ". Forecasts and risk ratings refresh when the source data is "
          "re-fitted.</p>"
        + _technical_details(artifacts)
        + f"<script>window.__riskData = {blob};</script>"
    )
    scripts = _asset_link("echarts.common.min.js") + "\n" + _asset_link("risk.js")
    return chrome("Risk & Forecast", body, page_key="risk", user=user,
                  scripts=scripts)


def _technical_details(meta) -> str:
    """The model/hash provenance, tucked into a collapsed details block so it is
    available to a reviewer without crowding the reader-facing page."""
    return (
        '<details class="risk-details"><summary>Technical details</summary>'
        '<p class="provenance">Model: '
        + html.escape(str(meta.get("model", "?")))
        + "<br>Fitted: " + html.escape(str(meta.get("fitted_at", "?")))
        + "<br>Basis: " + html.escape(str(meta.get("basis", "?")))
        + "<br>Source rows: " + str(meta.get("source_rows", "?"))
        + "<br>Feature version: " + str(meta.get("feature_version", "?"))
        + "<br>Rows hash: " + html.escape(str(meta.get("rows_hash", "?")))
        + "</p></details>"
    )
