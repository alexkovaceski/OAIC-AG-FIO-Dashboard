# src/risk/classify.py — risk-tier section renderer (honest until fitted)
from __future__ import annotations


def _get_tabular():
    from autogluon.tabular import TabularPredictor
    return TabularPredictor


def _not_fitted(title):
    return (
        f"<section class=\"risk-section\"><h2>Risk tiers &mdash; {title}</h2>"
        "<p class=\"risk-absent\">Not yet fitted. Run "
        "<code>scripts/fit_risk_models.py</code>.</p></section>"
    )


def _tiers(result):
    """Normalise a predictor result to [{agency, tier, prob}]. List-of-dicts
    in tests; on idc-1 the fit script adapts the real predict output to this
    shape (or this helper learns a DataFrame of probabilities + label)."""
    return list(result)


def render_classify_section(meta, model_dir, features=None):
    """features is the build_agency_features DataFrame. Honest not-fitted when
    the artifact or features are absent (never fabricate tiers)."""
    if features is None:
        return _not_fitted("outcome mix")
    try:
        TP = _get_tabular()
        pred = TP.load(model_dir)
    except Exception:
        return _not_fitted("outcome mix")
    tiers = _tiers(pred.predict(features))  # Task 5 defines _tiers
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
