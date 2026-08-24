"""load — risk artifact loading + risk page render (honest until fitted)."""
from __future__ import annotations
import json
import os
from pathlib import Path

from risk.classify import render_classify_section
from risk.features import build_agency_features, build_forecast_series
from risk.forecast import render_forecast_section
from site.templates import chrome

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
            "<h1>Risk insights</h1>"
            "<p class=\"intro\">Internal risk views over the published FOI "
            "statistics.</p>"
            "<p class=\"risk-absent\">Risk models are not yet fitted. Run "
            "<code>scripts/fit_risk_models.py</code> on idc-1 to train the "
            "forecast and classification models; this page will then show "
            "model-computed forecasts and risk tiers.</p>"
        )
        return chrome("Risk insights", body, page_key="risk", user=user)
    return _fitted_page(user, frame, artifacts)


def _fitted_page(user, frame, artifacts):
    base = artifacts.get("base", "")
    forecast_dir = os.path.join(base, "forecast")
    classify_dir = os.path.join(base, "classify")
    if frame is not None:
        series = build_forecast_series(frame.facts, "received")
        features = build_agency_features(frame.facts)
    else:
        series = features = None
    body = (
        "<h1>Risk insights</h1>"
        "<p class=\"intro\">Internal risk views over the published FOI "
        "statistics.</p>"
        + render_forecast_section(artifacts, forecast_dir, series)
        + render_classify_section(artifacts, classify_dir, features)
        + _provenance_footer(artifacts)
    )
    return chrome("Risk insights", body, page_key="risk", user=user)


def _provenance_footer(meta):
    return (
        "<p class=\"provenance\">risk model " + str(meta.get("model", "?"))
        + " &middot; fitted " + str(meta.get("fitted_at", "?"))
        + " &middot; basis " + str(meta.get("basis", "?"))
        + " &middot; source rows " + str(meta.get("source_rows", "?"))
        + " &middot; feature version " + str(meta.get("feature_version", "?"))
        + " &middot; rows hash " + str(meta.get("rows_hash", "?")) + "</p>"
    )
