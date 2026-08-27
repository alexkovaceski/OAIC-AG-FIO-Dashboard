# src/risk/classify.py — risk-tier section renderer (end-user language)
from __future__ import annotations
import json
import os
from collections import Counter

_TIER_LABEL = {"low": "Low risk", "medium": "Medium risk", "high": "High risk"}


def _not_fitted(title):
    return (
        f"<section class=\"risk-section\"><h2>{title}</h2>"
        "<p class=\"risk-absent\">Risk ratings are not ready yet. They are "
        "generated when the source data is re-fitted.</p></section>"
    )


def load_tiers(path) -> list[dict] | None:
    """Load the [{agency, tier, prob}] sidecar, or None when absent, unreadable
    or malformed — never a 500, never a fabricated tier."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return None
        out = []
        for row in data:
            if not isinstance(row, dict):
                return None
            out.append({"agency": row["agency"], "tier": row["tier"],
                        "prob": float(row["prob"])})
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return None


def summary(tiers: list[dict]) -> str:
    """A one-sentence plain-English reading of the risk tiers."""
    if not tiers:
        return ""
    counts = Counter(t["tier"] for t in tiers)
    total = len(tiers)
    low = counts.get("low", 0)
    elevated = counts.get("medium", 0) + counts.get("high", 0)
    el = sorted([t for t in tiers if t["tier"] != "low"],
                key=lambda t: (t["tier"] != "high", -t["prob"]))
    names = ", ".join(t["agency"] for t in el[:5])
    return (f"{low} of {total} agencies are rated <strong>low risk</strong>. "
            f"{elevated} show elevated risk"
            + (f", led by {names}" if names else "") + ".")


def render_classify_section(meta, model_dir, features=None) -> tuple[str, list | None]:
    """Render the agency risk-rating section.

    The fit script writes [{agency, tier, prob}] to classify/tiers.json. This
    renderer never imports autogluon and never live-predicts: a missing or
    unparseable sidecar renders the honest not-fitted block. The distribution
    chart and the searchable table are drawn client-side by risk.js from
    window.__riskData; the model names stay out of the reader-facing page.
    """
    tiers = load_tiers(os.path.join(model_dir, "tiers.json"))
    if tiers is None:
        return _not_fitted("Agency risk rating"), None
    ordered = sorted(tiers,
                     key=lambda t: (t["tier"] != "high", t["tier"] != "medium",
                                    -t["prob"]))
    rows = "".join(
        f'<tr data-name="{t["agency"].lower()}"><td>{t["agency"]}</td>'
        f'<td><span class="tier tier-{t["tier"]}">{_TIER_LABEL.get(t["tier"], t["tier"])}</span></td>'
        f'<td>{t["prob"]:.0%}</td></tr>' for t in ordered)
    html = (
        '<section class="risk-section"><h2>Agency risk rating</h2>'
        f'<p class="risk-summary">{summary(tiers)}</p>'
        '<p class="hint">Each agency is rated on how likely it is to meet the '
        'statutory timeframe for deciding requests next year &mdash; a '
        '&ldquo;High risk&rdquo; rating means a lower share of decisions is '
        'expected within the statutory period.</p>'
        '<div class="chartbox chartbox-sm" id="tier-chart" role="img" '
        'aria-label="Risk tier distribution chart"></div>'
        '<div class="risk-search"><input id="risk-search-in" type="search" '
        'placeholder="Search agencies…" autocomplete="off" '
        'aria-label="Search agencies"></div>'
        '<table class="report-table" id="risk-table"><thead><tr>'
        '<th>Agency</th><th>Rating</th><th>Confidence</th></tr></thead>'
        f'<tbody>{rows}</tbody></table></section>'
    )
    return html, tiers
