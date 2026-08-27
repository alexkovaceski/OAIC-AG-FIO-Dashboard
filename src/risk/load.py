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


def _agency_benchmark(frame):
    """Per-agency latest-FY timeliness share, for a discriminative ranking.

    The classifier's confidence score is not what distinguishes agencies (nearly
    everyone is 93-96% "low"). What actually varies is each agency's timeliness
    — the share of decisions made within the statutory period. Rank on that.
    Returns [{agency, share, decided, received}], share = within/decided (None
    when undecidable).
    """
    rows = [f for f in frame.facts if f["quarter"] is None
            and f["bucket"] == "total"]
    fys = sorted({f["fy"] for f in rows})
    latest = fys[-1] if fys else None
    within, decided, received = {}, {}, {}
    for f in rows:
        if f["fy"] != latest:
            continue
        if f["measure"] == "within_statutory":
            within[f["agency_name"]] = f["value"]
        elif f["measure"] == "decided":
            decided[f["agency_name"]] = f["value"]
        elif f["measure"] == "received":
            received[f["agency_name"]] = f["value"]
    out = []
    for agency, d in decided.items():
        w = within.get(agency, 0)
        out.append({"agency": agency,
                    "share": (round(w / d, 3) if d else None),
                    "decided": d, "received": received.get(agency)})
    return out


def _agency_trend(frame, agencies):
    """Per-agency FY-by-FY timeliness share + volume, for the detail panel."""
    rows = [f for f in frame.facts if f["quarter"] is None
            and f["bucket"] == "total"]
    by_agency = {}
    for f in rows:
        if f["agency_name"] not in agencies:
            continue
        by_agency.setdefault(f["agency_name"], {}).setdefault(
            f["fy"], {})[f["measure"]] = f["value"]
    out = {}
    for agency, fys in by_agency.items():
        trend = []
        for fy in sorted(fys):
            w = fys[fy].get("within_statutory", 0)
            d = fys[fy].get("decided", 0)
            trend.append({"fy": fy, "share": (round(w / d, 3) if d else None),
                          "received": fys[fy].get("received"), "decided": d})
        out[agency] = trend
    return out


def _load_agency_forecast(path):
    """Load the {agency: [{fy, value, lo, hi}]} sidecar, or {} when absent."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _agency_forecast_table(agency_forecast, top=10) -> str:
    """The forecast section's drill-down into agencies: the largest ten by their
    latest forecast year, each row clickable to the same per-agency detail the
    risk table uses. Empty when the sidecar is absent."""
    if not agency_forecast:
        return ""
    rows = []
    for agency, pts in agency_forecast.items():
        if pts:
            last = pts[-1]
            rows.append((agency, last["fy"], float(last["value"])))
    rows.sort(key=lambda r: r[2], reverse=True)
    rows = rows[:top]
    if not rows:
        return ""
    body = "".join(
        f'<tr class="agency-fc-row" data-agency="{html.escape(a)}" '
        f'tabindex="0" role="button" aria-label="View {html.escape(a)}">'
        f'<td>{html.escape(a)}</td><td>{html.escape(fy)}</td>'
        f'<td>{value:,.0f}</td></tr>'
        for a, fy, value in rows)
    return (
        '<details class="risk-details" open><summary>Forecast by agency '
        '(top 10)</summary>'
        '<p class="hint">Forecast requests received in the final forecast year, '
        'largest first. Click a row to see that agency&rsquo;s detail.</p>'
        '<table class="report-table risk-table" id="agency-fc-table">'
        '<thead><tr><th>Agency</th><th>FY</th><th>Forecast</th></tr></thead>'
        f'<tbody>{body}</tbody></table></details>'
    )


def _fitted_page(user, frame, artifacts):
    base = artifacts.get("base", "")
    forecast_dir = os.path.join(base, "forecast")
    classify_dir = os.path.join(base, "classify")
    series = (build_forecast_series(frame.facts, "received")
              if frame is not None else None)
    forecast_html, points = render_forecast_section(artifacts, forecast_dir,
                                                    series)
    agency_fc = _load_agency_forecast(
        os.path.join(forecast_dir, "agency_predictions.json"))
    benchmark = (_agency_benchmark(frame) if frame is not None else [])
    classify_html, tiers = render_classify_section(artifacts, classify_dir,
                                                   benchmark)
    risk_data = {
        "forecast": {"historical": series, "points": points or []},
        "tiers": tiers or [],
        "benchmark": benchmark,
        "trend": (_agency_trend(frame, {b["agency"] for b in benchmark})
                  if frame is not None else {}),
        "agency_forecast": agency_fc,
    }
    # the JSON blob must never break out of its <script> tag (mirrors __pageData)
    blob = json.dumps(risk_data).replace("</", "<\\/")
    updated = _plain_date(artifacts.get("fitted_at"))
    body = (
        "<h1>Risk &amp; Forecast</h1>"
        '<p class="intro">Forward-looking views over the published FOI '
        "statistics &mdash; a forecast of request volume and a risk rating for "
        "each agency, explained in plain language.</p>"
        + forecast_html + _agency_forecast_table(agency_fc) + classify_html
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
