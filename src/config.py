"""Shared config + constants for the Bluebird FOI Insights POC."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_SOURCES_DIR = PROJECT_ROOT / "data" / "sources"
DATA_GENERATED_DIR = PROJECT_ROOT / "data" / "generated"
CORPUS_DIR = PROJECT_ROOT / "data" / "corpus"
STATIC_DIR = PROJECT_ROOT / "src" / "site" / "assets"

# data.gov.au dataset id for FOI statistics
OAIC_DATASET_ID = "b0771c28-09cc-4c4e-9e61-9a96f6e3d040"

# window_mode is a schema-enforced field on every fact/lineage row
WINDOW_MODES = ("single_quarter", "cumulative", "fy")

# The published Q1 2025-26 single-quarter figures (golden-benchmark acceptance).
GOLDEN_Q1_FIGURES = {
    "requests_received": 12359,
    "finalised": 11549,
    "decided": 7344,
    "within_statutory": 5167,
    "granted_full": 1426,
    "granted_part": 3968,
    "refused": 1950,
    "withdrawn": 3955,
}

# Postgres (idc-1 horizon DB; local dev override via env). No auth on the POC.
PG_DSN = os.environ.get("FOI_PG_DSN", "postgresql://algolotl:algolotl@localhost:5432/horizon")
