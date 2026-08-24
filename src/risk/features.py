"""features — no-leakage feature build from the canonical facts.

Every feature is a strict trailing statistic: warmup rows are NaN, a bar is
never its own feature (`.shift` / `pct_change`), and no lookahead
(`.shift(-N)`, bfill, full-series quantiles) is permitted. Labels (future
outcomes) are produced by the fit script from a time-split, never from data
the model saw.
"""
from __future__ import annotations
import pandas as pd


def build_forecast_series(facts, measure):
    rows = [f for f in facts if f["quarter"] is None
            and f["measure"] == measure and f["bucket"] == "total"]
    by = {}
    for f in rows:
        by[f["fy"]] = by.get(f["fy"], 0.0) + f["value"]
    cats = sorted({f["fy"] for f in facts if f["quarter"] is None})
    return {"fy": cats,
            "values": [round(by[y], 3) if y in by else None for y in cats]}


def build_agency_features(facts):
    rows = [
        {"agency": f["agency_name"], "fy": f["fy"], "measure": f["measure"],
         "value": float(f["value"])}
        for f in facts if f["quarter"] is None and f["bucket"] == "total"
    ]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    piv = df.pivot_table(index=["agency", "fy"], columns="measure",
                         values="value", aggfunc="sum").reset_index()
    groups = []
    for agency, grp in piv.groupby("agency"):
        grp = grp.sort_values("fy").reset_index(drop=True)
        r = pd.DataFrame({"agency": grp["agency"], "fy": grp["fy"]})
        for col in ("received", "decided", "within_statutory",
                    "granted_full", "granted_part", "refused", "withdrawn"):
            if col in grp:
                r[col] = grp[col]
        for col in ("received", "decided", "within_statutory"):
            if col in r:
                r[f"{col}_yoy"] = r[col].pct_change()
        groups.append(r)
    return pd.concat(groups, ignore_index=True) if groups else pd.DataFrame()
