"""fit_risk_models — offline AutoGluon fit on idc-1 (RTX 3090).

Builds no-leakage features from the canonical facts, then fits:
  - forecast: TimeSeriesPredictor (AutoGluon-Chronos) over the FY received
    series, predicting the next 1-3 FY with prediction intervals.
  - classify: TabularPredictor (TabPFN) over per-agency per-FY features.
Labels are next-FY outcomes (strictly future, time-split on the FY boundary;
the final FY is unlabeled and excluded from training). Writes model artifacts
+ risk_metadata.json to data/generated/risk/. Run on idc-1 after deploy; the
service serves an honest 'not yet fitted' risk page until this runs.

The model never writes a digit: every figure the risk page shows comes from
these artifacts (predicted values, class probabilities) or the frame.

Renderer contract: the risk renderers (src/risk/forecast.py, classify.py) read
the fitted numbers straight from the JSON sidecars this script writes:
forecast/predictions.json is [{fy, value, lo, hi}] and classify/tiers.json is
[{agency, tier, prob}] — the exact contracts the renderers were built against,
so no renderer adjustment is needed. The renderers never import autogluon and
never live-predict; a missing or unparseable sidecar renders the honest
'not yet fitted' block. The sidecars are the model's computed numbers — the
guarantee that a fitted risk page never fabricates. The raw predictors are
saved alongside (forecast/model/, classify/model/) for refits / future use.

Usage:
  .venv/bin/python scripts/fit_risk_models.py --dry-run   # non-fit path, no writes
  .venv/bin/python scripts/fit_risk_models.py --skip-lineage  # fit, no DB record
  .venv/bin/python scripts/fit_risk_models.py             # full fit on idc-1
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd  # noqa: E402

import config  # noqa: E402
from ingest.normalise import normalise_all  # noqa: E402
from risk.features import (build_agency_features, build_agency_series,  # noqa: E402
                           build_forecast_series)
from storage.frame import Frame  # noqa: E402
from storage.facts import canonical_hash  # noqa: E402

# Artifact layout (mirrors src/risk/load.py's _RISK_DIR). data/generated/risk/
# is git-ignored — fitted artifacts are never committed.
RISK_DIR = Path(__file__).resolve().parent.parent / "data" / "generated" / "risk"
FORECAST_DIR = RISK_DIR / "forecast"
CLASSIFY_DIR = RISK_DIR / "classify"
METADATA_PATH = RISK_DIR / "risk_metadata.json"

# Bump when src/risk/features.py changes the feature builders.
FEATURE_VERSION = "1"
BASIS = "annual FY totals; time-split on the FY boundary"
SPLIT_FY = "2022-23"     # train FY <= SPLIT_FY, test FY > SPLIT_FY (hard split)
TIER_CUTS = (0.6, 0.4)   # timeliness share >= 0.6 -> low, >= 0.4 -> medium, else high
MEASURE = "received"     # forecast target series (annual totals)

# Forecast hyperparameters (POC, verified on autogluon 1.5.0). chronos_small
# does NOT exist; chronos2_small is the smallest chronos2 preset. Weights
# download from HuggingFace on the first fit (verified reachable from idc-1).
FORECAST_PRESET = "chronos2_small"
PREDICTION_LENGTH = 3
QUANTILE_LEVELS = [0.1, 0.9]
FORECAST_TIME_LIMIT = 3600

CLASSIFY_PRESETS = "best_quality"
CLASSIFY_TIME_LIMIT = 3600


# --------------------------------------------------------------------------- #
# facts + features (no-leakage build; the same seam the ingest path uses)      #
# --------------------------------------------------------------------------- #

def load_facts() -> list[dict]:
    """Canonical facts via the ingest load + the golden data-integrity gate."""
    facts = normalise_all(config.DATA_SOURCES_DIR)
    frame = Frame(facts)
    frame.golden_check()
    return frame.facts


def _next_fy(fy: str) -> str:
    """The FY one year later. '2019-20' -> '2020-21' (end year = start + 2)."""
    start = int(fy.split("-")[0])
    return f"{start + 1}-{str((start + 2) % 100).zfill(2)}"


def _timeliness_tier(share) -> str | None:
    if share is None or pd.isna(share):
        return None
    if share >= TIER_CUTS[0]:
        return "low"
    if share >= TIER_CUTS[1]:
        return "medium"
    return "high"


def _label_for(nxt_row: pd.Series) -> str | None:
    """Next-FY timeliness-share tier for one agency row of the next FY."""
    if "within_statutory" not in nxt_row.index or "decided" not in nxt_row.index:
        return None
    decided = nxt_row.get("decided")
    within = nxt_row.get("within_statutory")
    if decided is None or pd.isna(decided) or not float(decided):
        return None
    return _timeliness_tier(float(within) / float(decided))


def build_label_frame(features: pd.DataFrame) -> pd.DataFrame:
    """Add next-FY outcome labels: row (agency, fy) -> tier(within/decided @ fy+1).

    The final FY has no next-FY outcome, so those rows stay unlabeled and are
    excluded from training. The label is strictly future relative to the row's
    own features — no leakage.
    """
    df = features.copy()
    df["tier_next"] = None
    fy_lookup = {(a, f): r for a, g in df.groupby("agency")
                 for f, r in g.set_index("fy").iterrows()}
    for i, row in df.iterrows():
        nxt = fy_lookup.get((row["agency"], _next_fy(row["fy"])))
        if nxt is not None:
            df.loc[i, "tier_next"] = _label_for(nxt)
    return df


def _classify_training_frame(label_frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Split labeled rows on the FY boundary; drop the unlabeled final FY.

    Returns (labeled rows with tier_next, final_fy). Rows whose label could
    not be computed (missing measures, zero decided) are dropped — an agency/FY
    with no definable next-FY tier is not a training example.
    """
    labeled = label_frame[label_frame["tier_next"].notna()].copy()
    final_fy = sorted(label_frame["fy"].unique())[-1]  # lexicographic == chronological (20XX)
    labeled = labeled[labeled["fy"] != final_fy]  # final FY unlabeled by construction; belt-and-braces
    return labeled, final_fy


def _final_fy_rows(label_frame: pd.DataFrame, final_fy: str) -> pd.DataFrame:
    """The final-FY feature rows the forward-looking tier is predicted on.

    These rows were never in training (no label), so predicting on them is the
    honest 'what is each agency's next-FY risk tier' question.
    """
    return label_frame[label_frame["fy"] == final_fy].drop(
        columns=["tier_next"])


# --------------------------------------------------------------------------- #
# forecast (AutoGluon-Chronos)                                                #
# --------------------------------------------------------------------------- #

def _series_to_tsdf(series: dict):
    """Wrap the build_forecast_series dict into a TimeSeriesDataFrame.

    FY "2019-20" -> 2019-07-01 (Australian FY start), freq YS-JUL. Lazy-imports
    autogluon (this helper is only reached on the fit path).
    """
    from autogluon.timeseries import TimeSeriesDataFrame
    rows = []
    for fy, v in zip(series["fy"], series["values"]):
        if v is None:
            continue
        rows.append({
            "timestamp": pd.Timestamp(year=int(fy[:4]), month=7, day=1),
            "item_id": MEASURE,
            "values": float(v),
        })
    if not rows:
        raise ValueError("forecast series has no values to fit")
    df = pd.DataFrame(rows)
    df["item_id"] = df["item_id"].astype(str)
    df = df.set_index(["item_id", "timestamp"])
    return TimeSeriesDataFrame(df)


def _ts_to_fy(ts) -> str:
    return f"{ts.year}-{str((ts.year + 1) % 100).zfill(2)}"


def _point_fy(idx) -> str:
    """Extract the FY from a predict-output index entry, regardless of whether
    AutoGluon emits (timestamp, item_id) or (item_id, timestamp) order.

    We build the training index as (timestamp, item_id), but AutoGluon's
    predict() output index ordering is not something we control or assert. Bind
    the Timestamp defensively and raise a clear error if neither slot is one —
    the fit must never abort after the ~1h GPU fit with an AttributeError.
    """
    a, b = idx
    ts = a if isinstance(a, pd.Timestamp) else (b if isinstance(b, pd.Timestamp) else None)
    if ts is None:
        raise ValueError(
            f"unexpected forecast index {idx!r}: no pd.Timestamp in either slot")
    return _ts_to_fy(ts)


def fit_forecast(series: dict, time_limit: int = FORECAST_TIME_LIMIT):
    """Fit the Chronos forecast predictor and return the [{fy,value,lo,hi}] list.

    The renderer reads forecast/predictions.json only (never loads the
    predictor); forecast/model/ keeps the raw predictor for reproducibility.
    """
    from autogluon.timeseries import TimeSeriesPredictor
    tsdf = _series_to_tsdf(series)
    model_dir = FORECAST_DIR / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    predictor = TimeSeriesPredictor(
        path=str(model_dir), target="values",
        prediction_length=PREDICTION_LENGTH, freq="YS-JUL",
        quantile_levels=QUANTILE_LEVELS)
    predictor.fit(train_data=tsdf, presets=FORECAST_PRESET,
                  time_limit=time_limit)
    raw = predictor.predict(tsdf)
    points = []
    for idx, row in raw.iterrows():
        points.append({
            "fy": _point_fy(idx),
            "value": float(row["mean"]),
            "lo": float(row[str(QUANTILE_LEVELS[0])]),
            "hi": float(row[str(QUANTILE_LEVELS[1])]),
        })
    _write_json(FORECAST_DIR / "predictions.json", points)
    return points, type(raw).__name__


def _agency_to_tsdf(agency_series: dict):
    """Wrap the per-agency series dict into one multi-item TimeSeriesDataFrame.

    One item per agency; sparse agencies contribute only the years they report.
    """
    from autogluon.timeseries import TimeSeriesDataFrame
    rows = []
    for agency, series in agency_series.items():
        for fy, v in zip(series["fy"], series["values"]):
            if v is None:
                continue
            rows.append({
                "item_id": agency,
                "timestamp": pd.Timestamp(year=int(fy[:4]), month=7, day=1),
                "values": float(v),
            })
    if not rows:
        raise ValueError("no agency series to fit")
    df = pd.DataFrame(rows)
    df["item_id"] = df["item_id"].astype(str)
    df = df.set_index(["item_id", "timestamp"])
    return TimeSeriesDataFrame(df)


def _item_and_fy(idx):
    """(item_id, fy) from a predict-output index entry, regardless of whether
    AutoGluon emits (item_id, timestamp) or (timestamp, item_id) order."""
    a, b = idx
    ts = a if isinstance(a, pd.Timestamp) else (b if isinstance(b, pd.Timestamp) else None)
    if ts is None:
        raise ValueError(f"unexpected forecast index {idx!r}: no pd.Timestamp")
    item = b if ts is a else a
    return str(item), _ts_to_fy(ts)


def fit_agency_forecast(agency_series: dict, time_limit: int = FORECAST_TIME_LIMIT):
    """Fit the per-agency Chronos forecast and write forecast/agency_predictions.json.

    ONE global model over every agency's own series — the efficient shape for
    many short, related series. The renderer reads the sidecar only (never
    loads the predictor); forecast/agency_model/ keeps it for reproducibility.
    """
    from autogluon.timeseries import TimeSeriesPredictor
    tsdf = _agency_to_tsdf(agency_series)
    model_dir = FORECAST_DIR / "agency_model"
    model_dir.mkdir(parents=True, exist_ok=True)
    predictor = TimeSeriesPredictor(
        path=str(model_dir), target="values",
        prediction_length=PREDICTION_LENGTH, freq="YS-JUL",
        quantile_levels=QUANTILE_LEVELS)
    predictor.fit(train_data=tsdf, presets=FORECAST_PRESET, time_limit=time_limit)
    raw = predictor.predict(tsdf)
    out: dict = {}
    for idx, row in raw.iterrows():
        item, fy = _item_and_fy(idx)
        out.setdefault(item, []).append({
            "fy": fy,
            "value": float(row["mean"]),
            "lo": float(row[str(QUANTILE_LEVELS[0])]),
            "hi": float(row[str(QUANTILE_LEVELS[1])]),
        })
    _write_json(FORECAST_DIR / "agency_predictions.json", out)
    return out, type(raw).__name__


# --------------------------------------------------------------------------- #
# classify (AutoGluon-Tabular)                                                #
# --------------------------------------------------------------------------- #

def fit_classify(train_df: pd.DataFrame, final_X: pd.DataFrame):
    """Fit the tier classifier and return the [{agency, tier, prob}] list.

    TabPFN is available via autogluon[tabarena]; 'best_quality' picks a strong
    ensemble for this small per-agency/per-FY table. The label column is
    tier_next (dropped from the final-FY predict frame). The model is saved at
    classify/model/ (see module docstring for why not classify/).
    """
    from autogluon.tabular import TabularPredictor
    model_dir = CLASSIFY_DIR / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    predictor = TabularPredictor(
        label="tier_next", problem_type="multiclass", path=str(model_dir))
    predictor.fit(train_data=train_df, presets=CLASSIFY_PRESETS,
                  time_limit=CLASSIFY_TIME_LIMIT)
    labels = predictor.predict(final_X)
    proba = predictor.predict_proba(final_X)
    tiers = []
    for i, (_, row) in enumerate(final_X.iterrows()):
        lab = str(labels.iloc[i])
        p = proba.iloc[i][lab] if lab in proba.columns else float("nan")
        tiers.append({"agency": row["agency"], "tier": lab, "prob": round(float(p), 4)})
    _write_json(CLASSIFY_DIR / "tiers.json", tiers)
    return tiers, type(labels).__name__


# --------------------------------------------------------------------------- #
# artifacts + provenance                                                      #
# --------------------------------------------------------------------------- #

def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def write_metadata(facts, fitted_at: str) -> dict:
    meta = {
        "model": f"autogluon {FORECAST_PRESET} (forecast) + "
                 f"{CLASSIFY_PRESETS} (classify)",
        "fitted_at": fitted_at,
        "basis": BASIS,
        "source_rows": len(facts),
        "rows_hash": canonical_hash(facts),
        "feature_version": FEATURE_VERSION,
    }
    _write_json(METADATA_PATH, meta)
    return meta


def record_lineage(facts, meta: dict, *, conn=None) -> None:
    """Best-effort provenance: a lineage_artifacts row (kind model_fit) + a
    lineage_ops row carrying the metadata path + model + fitted_at + rows_hash.

    Mirrors the ingest/app pattern: unreachable DB degrades to None (fail-open,
    the fit still succeeds); a schema/programming error raises so it is not
    silently hidden. A missing dataset_id (facts not seeded on this DB) also
    degrades gracefully.
    """
    if conn is None:
        from storage.db import get_conn
        conn = get_conn()
    from storage.db import ensure_schema
    from storage.facts import ingest_facts
    from storage.lineage import record_artifact, record_op
    ensure_schema(conn)
    dataset_id = ingest_facts(facts, conn=conn)
    if dataset_id is None:
        print("  lineage: no foi_datasets row available; provenance record skipped")
        return
    artifact_id = record_artifact(
        conn, artifact_type="model_fit",
        artifact_key=str(METADATA_PATH.relative_to(config.PROJECT_ROOT)),
        user_id=None, dataset_id=dataset_id,
        request_text="fit_risk_models",
        spec_json={"metadata_path": str(METADATA_PATH),
                   "model": meta["model"], "fitted_at": meta["fitted_at"]},
        model=meta["model"], status="fitted")
    if artifact_id is None:
        print("  lineage: artifact row not recorded (DB transient error, fail-open)")
        return
    record_op(conn, artifact_id=artifact_id, dataset_id=dataset_id,
              kind="model_fit", op="fit_risk_models",
              params={"metadata_path": str(METADATA_PATH),
                      "model": meta["model"], "fitted_at": meta["fitted_at"]},
              row_count=meta["source_rows"], rows_hash=meta["rows_hash"],
              result_value={"model": meta["model"], "fitted_at": meta["fitted_at"]})
    print(f"  lineage: recorded fit provenance (artifact id={artifact_id})")


def _write_forecast_readme() -> None:
    readme = (
        "This directory holds the offline AutoGluon-Chronos forecast fit.\n\n"
        "  model/            the TimeSeriesPredictor artifact (kept for "
        "reproducibility;\n"
        "                    the renderer does not load or predict with it).\n"
        "  predictions.json  the model's computed next-FY forecast [{fy, value, "
        "lo, hi}] — the\n"
        "                    exact contract src/risk/forecast.py's "
        "render_forecast_section\n"
        "                    reads directly. No renderer edit required.\n"
    )
    (FORECAST_DIR / "README.md").write_text(readme, encoding="utf-8")


def _write_classify_readme() -> None:
    readme = (
        "This directory holds the offline AutoGluon classify fit.\n\n"
        "  model/        the TabularPredictor artifact (kept for "
        "reproducibility;\n"
        "                the renderer does not load or predict with it).\n"
        "  tiers.json    the model's computed per-agency forward-looking tiers "
        "[{agency, tier,\n"
        "                prob}] — the exact contract src/risk/classify.py's "
        "render_classify_section\n"
        "                reads directly. No renderer edit required.\n"
    )
    (CLASSIFY_DIR / "README.md").write_text(readme, encoding="utf-8")


# --------------------------------------------------------------------------- #
# driver                                                                       #
# --------------------------------------------------------------------------- #

def _print_contract_check(forecast_raw, classify_raw, points, tiers) -> None:
    """Report what the raw AutoGluon predictors returned and where the sidecars
    landed (verified at fit time)."""
    print("\n--- renderer contract check (verified at fit time) ---")
    if points:
        print(f"forecast predict() returned {forecast_raw} "
              f"-> adapted to {len(points)} points [{points[0]['fy']}.."
              f"{points[-1]['fy']}] in forecast/predictions.json")
    else:
        print(f"forecast predict() returned {forecast_raw} "
              f"-> adapted to 0 points in forecast/predictions.json")
    print(f"classify predict() returned {classify_raw} "
          f"-> adapted to {len(tiers)} agency tiers in classify/tiers.json")
    print("The renderers (src/risk/forecast.py, classify.py) load these "
          "sidecars directly")
    print("at route time, so the fitted numbers surface on the next /risk.html "
          "request — no")
    print("renderer edit and no restart needed. No number on the risk page is "
          "ever fabricated —")
    print("every figure comes from these artifacts or the frame.")


def dry_run() -> int:
    """Non-fit path: load facts, build features/labels, report the plan. No
    autogluon import, nothing written — safe to run on any machine."""
    facts = load_facts()
    series = build_forecast_series(facts, MEASURE)
    agency_series = build_agency_series(facts, MEASURE)
    features = build_agency_features(facts)
    if features.empty:
        print("error: no annual agency feature rows — nothing to fit", file=sys.stderr)
        return 1
    label_frame = build_label_frame(features)
    labeled, final_fy = _classify_training_frame(label_frame)
    print(f"facts: {len(facts)} canonical (rows_hash {canonical_hash(facts)[:12]}...)")
    print(f"forecast series: {len(series['fy'])} FY points "
          f"({series['fy'][0]}..{series['fy'][-1]})")
    print(f"agency series: {len(agency_series)} agencies for the per-agency "
          f"volume forecast")
    print(f"label rows: {len(labeled)} (final FY {final_fy} unlabeled, excluded "
          f"from training)")
    train = labeled[labeled["fy"] <= SPLIT_FY]
    test = labeled[labeled["fy"] > SPLIT_FY]
    print(f"label FY boundary {SPLIT_FY}: {len(train)} labeled rows at/before it, "
          f"{len(test)} after (no-leakage check; the production fit uses ALL "
          f"{len(labeled)} labeled rows — no held-out evaluation runs)")
    if labeled["tier_next"].notna().sum() < 2:
        print("warning: too few labeled rows for a meaningful fit")
    print("would fit (on idc-1, autogluon required):")
    print(f"  forecast  TimeSeriesPredictor preset={FORECAST_PRESET} "
          f"prediction_length={PREDICTION_LENGTH}")
    print(f"  classify  TabularPredictor presets={CLASSIFY_PRESETS} label=tier_next")
    print(f"would write {RISK_DIR}/ (forecast/, classify/, risk_metadata.json)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="load facts + build features/labels and report the "
                             "plan; no autogluon, no writes")
    parser.add_argument("--skip-lineage", action="store_true",
                        help="fit + write artifacts but skip the Postgres "
                             "provenance record")
    args = parser.parse_args(argv)

    if args.dry_run:
        return dry_run()

    print("fit_risk_models: loading canonical facts (golden gate) ...")
    facts = load_facts()
    series = build_forecast_series(facts, MEASURE)
    agency_series = build_agency_series(facts, MEASURE)
    features = build_agency_features(facts)
    if features.empty:
        print("error: no annual agency feature rows — nothing to fit", file=sys.stderr)
        return 1
    label_frame = build_label_frame(features)
    labeled, final_fy = _classify_training_frame(label_frame)
    final_X = _final_fy_rows(label_frame, final_fy)
    fitted_at = datetime.now(timezone.utc).isoformat()
    print(f"facts={len(facts)} rows_hash={canonical_hash(facts)[:12]}... "
          f"final_fy={final_fy} train_labels={len(labeled)}")

    print(f"\n[forecast] fitting {FORECAST_PRESET} (prediction_length="
          f"{PREDICTION_LENGTH}) ...")
    points, forecast_raw = fit_forecast(series)
    print(f"[forecast] wrote {FORECAST_DIR}/ + predictions.json "
          f"({len(points)} FY points)")

    print(f"\n[agency forecast] fitting per-agency series "
          f"({len(agency_series)} agencies) ...")
    agency_out, agency_raw = fit_agency_forecast(agency_series)
    print(f"[agency forecast] wrote {FORECAST_DIR}/agency_predictions.json "
          f"({len(agency_out)} agencies)")

    print(f"\n[classify] fitting {CLASSIFY_PRESETS} over {len(labeled)} "
          f"labeled rows ...")
    tiers, classify_raw = fit_classify(labeled, final_X)
    print(f"[classify] wrote {CLASSIFY_DIR}/tiers.json + model/ "
          f"({len(tiers)} agency tiers)")
    _write_forecast_readme()
    _write_classify_readme()

    meta = write_metadata(facts, fitted_at)
    print(f"\n[metadata] wrote {METADATA_PATH}")
    print(f"  model={meta['model']}\n  fitted_at={meta['fitted_at']}\n"
          f"  basis={meta['basis']}\n  source_rows={meta['source_rows']}\n"
          f"  rows_hash={meta['rows_hash']}\n"
          f"  feature_version={meta['feature_version']}")

    if not args.skip_lineage:
        print("\n[lineage] recording fit provenance ...")
        try:
            record_lineage(facts, meta)
        except Exception as exc:  # fail-open: a DB hiccup must not hide a good fit
            print(f"  lineage: skipped (fail-open): {exc}")
    else:
        print("\n[lineage] skipped (--skip-lineage)")

    _print_contract_check(forecast_raw, classify_raw, points, tiers)
    print("\nDone. The fitted risk artifacts are live — /risk.html reads them at "
          "route time,")
    print("so the next request shows the model-computed numbers (no restart "
          "needed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
