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


def build_agency_series(facts, measure, min_history=3, min_last_fy=None):
    """Per-agency annual series — {agency: {"fy": [...], "values": [...]}}.

    The per-agency volume forecast fits ONE global Chronos model over every
    agency's own series, so each agency gets its own next-FY forecast instead of
    sharing the single total. Missing years are None (sparse agencies simply
    contribute fewer points to the multi-series frame).

    `min_history` drops agencies with too few annual points to forecast — the
    frame contains many renamed/merged entities that report for only 1-2 years
    under an old name, and a forecast on a 1-point series is a flat past-year
    artefact, not a forecast.

    `min_last_fy` drops agencies whose LAST reported year is older than that FY.
    An agency abolished or renamed in the July 2022 restructure ends its series
    in 2021-22 or earlier, so its 3-year "forecast" lands entirely in years
    already past (2022-23..2024-25) — not a forecast, an artefact of the series
    stopping. The fit script passes the second-latest annual FY so every
    retained forecast starts in the current published FY or later.
    """
    rows = [f for f in facts if f["quarter"] is None
            and f["measure"] == measure and f["bucket"] == "total"]
    by_agency = {}
    for f in rows:
        by_agency.setdefault(f["agency_name"], {})[f["fy"]] = f["value"]
    cats = sorted({f["fy"] for f in facts if f["quarter"] is None})
    out = {}
    for a, fyvals in by_agency.items():
        values = [fyvals.get(y) for y in cats]
        present = [y for y, v in zip(cats, values) if v is not None]
        if len(present) < min_history:
            continue
        if min_last_fy and (not present or present[-1] < min_last_fy):
            continue
        out[a] = {"fy": cats, "values": values}
    return out


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
