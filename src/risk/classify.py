# src/risk/classify.py — risk-tier section renderer (honest until fitted)
from __future__ import annotations
import json
import os


def _not_fitted(title):
    return (
        f"<section class=\"risk-section\"><h2>Risk tiers &mdash; {title}</h2>"
        "<p class=\"risk-absent\">Not yet fitted. Run "
        "<code>scripts/fit_risk_models.py</code>.</p></section>"
    )


def _load_tiers(path):
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
                        "prob": row["prob"]})
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return None


def render_classify_section(meta, model_dir, features=None):
    """Render the fitted tiers from the tiers.json sidecar.

    The fit script (scripts/fit_risk_models.py) writes [{agency, tier, prob}]
    to os.path.join(model_dir, "tiers.json"). This renderer never imports
    autogluon and never live-predicts: a missing or unparseable sidecar renders
    the honest not-fitted block. `features` is kept for signature compatibility
    (load.py passes it) but no longer drives the render.
    """
    tiers = _load_tiers(os.path.join(model_dir, "tiers.json"))
    if tiers is None:
        return _not_fitted("outcome mix")
    rows = "".join(
        f"<tr><td>{t['agency']}</td><td>{t['tier']}</td>"
        f"<td>{t['prob']:.0%}</td></tr>" for t in tiers)
    return (
        "<section class=\"risk-section\"><h2>Risk tiers &mdash; outcome mix</h2>"
        f"<p class=\"provenance\">model {meta.get('model')} &middot; fitted "
        f"{meta.get('fitted_at')} &middot; basis {meta.get('basis')} &middot; "
        f"rows {meta.get('source_rows')} &middot; hash {meta.get('rows_hash')}</p>"
        f"<table><thead><tr><th>Agency</th><th>Tier</th><th>P</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></section>"
    )
