# src/risk/classify.py — risk-tier section renderer (end-user language)
from __future__ import annotations
import html
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


def summary(rows: list[dict]) -> str:
    """A one-sentence plain-English reading of the risk tiers.

    Rows carry `tier` plus a measured `share` (timeliness). Elevated agencies
    are ordered by severity then by lowest timeliness share, not by the
    (nearly uniform) classifier confidence.
    """
    if not rows:
        return ""
    counts = Counter(t["tier"] for t in rows)
    total = len(rows)
    low = counts.get("low", 0)
    elevated = counts.get("medium", 0) + counts.get("high", 0)
    el = sorted([t for t in rows if t["tier"] != "low"],
                key=lambda t: (t["tier"] != "high",
                               t.get("share") if t.get("share") is not None else 1.0))
    names = ", ".join(t["agency"] for t in el[:5])
    return (f"{low} of {total} agencies are rated <strong>low risk</strong>. "
            f"{elevated} show elevated risk"
            + (f", led by {names}" if names else "") + ".")


def _share_cell(share) -> str:
    return "&mdash;" if share is None else f"{share:.0%}"


def render_classify_section(meta, model_dir, benchmark=None) -> tuple[str, list | None]:
    """Render the agency risk-rating section.

    The fit script writes [{agency, tier, prob}] to classify/tiers.json. This
    renderer never imports autogluon and never live-predicts: a missing or
    unparseable sidecar renders the honest not-fitted block. `benchmark` (from
    load.py) carries each agency's measured timeliness share, which is what
    actually distinguishes agencies — the classifier's confidence is nearly
    uniform (93-96% "low") and is NOT shown. The distribution chart, ranking
    and the per-agency detail are drawn client-side by risk.js.
    """
    tiers = load_tiers(os.path.join(model_dir, "tiers.json"))
    if tiers is None:
        return _not_fitted("Agency risk rating"), None
    tier_by = {t["agency"]: t["tier"] for t in tiers}
    rows = benchmark or []
    for r in rows:
        r["tier"] = tier_by.get(r["agency"], "low")
    rows.sort(key=lambda r: (r.get("share") is None,
                             r.get("share") if r.get("share") is not None else 0))
    body = "".join(
        f'<tr data-name="{r["agency"].lower()}" data-agency="{html.escape(r["agency"])}">'
        f'<td>{html.escape(r["agency"])}</td>'
        f'<td>{_share_cell(r.get("share"))}</td>'
        f'<td><span class="tier tier-{r["tier"]}">'
        f'{_TIER_LABEL.get(r["tier"], r["tier"])}</span></td></tr>' for r in rows)
    section = (
        '<section class="risk-section"><h2>Agency risk rating</h2>'
        f'<p class="risk-summary">{summary(rows)}</p>'
        '<p class="hint">Agencies are ranked by the share of decisions made '
        'within the statutory period this year &mdash; the lower the share, the '
        'higher the risk. The rating column is the expectation for next year. '
        'Select an agency to see its trend.</p>'
        '<div class="chartbox chartbox-sm" id="tier-chart" role="img" '
        'aria-label="Timeliness distribution chart"></div>'
        '<div class="risk-search"><input id="risk-search-in" type="search" '
        'placeholder="Search agencies…" autocomplete="off" '
        'aria-label="Search agencies"></div>'
        '<table class="report-table" id="risk-table"><thead><tr>'
        '<th>Agency</th><th>Within statutory</th><th>Rating</th></tr></thead>'
        f'<tbody>{body}</tbody></table>'
        '<div id="agency-detail" class="agency-detail" role="region" '
        'aria-live="polite"></div></section>'
    )
    return section, tiers
