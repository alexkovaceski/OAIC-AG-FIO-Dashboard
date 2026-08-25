"""facts — foi_datasets + foi_facts persistence and reload.

canonical_hash is the refresh idempotency gate: a sha256 over the canonical
fact rows, deterministic on fact content only (sorted JSON lines), so a re-run
of the same normaliser over the same data yields the same hash and the ingest
is a no-op.
"""
from __future__ import annotations
import hashlib
import json

import psycopg2

from storage.db import get_conn

# Fact dict keys that make up the canonical row (from normalise._fact).
_CANONICAL_KEYS = (
    "agency_key", "agency_name", "fy", "quarter", "measure_group", "measure",
    "bucket", "value", "derived", "portfolio",
)

NORMALISER_VER = "2026-08-21-data-gap-fill"


def canonical_hash(facts: list[dict]) -> str:
    """sha256 over canonical fact rows. Deterministic: sorts by the canonical
    JSON line, so order and float representation do not change the hash."""
    lines = []
    for f in facts:
        row = {k: f.get(k) for k in _CANONICAL_KEYS}
        # value is a float from _num; normalise to a canonical repr
        if "value" in row and isinstance(row["value"], float):
            row["value"] = round(row["value"], 9)
        lines.append(json.dumps(row, sort_keys=True))
    lines.sort()
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _dataset_exists(conn, h: str) -> int | None:
    """Return the id of the existing dataset with this canonical hash, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM horizon.foi_datasets WHERE canonical_hash = %s "
            "AND superseded_by IS NULL ORDER BY id DESC LIMIT 1", (h,))
        row = cur.fetchone()
    return row[0] if row else None


def ingest_facts(facts: list[dict], *, conn=None,
                 period_label: str = "FY2019-20..2025-26 Q1-Q3 + golden Q1",
                 window_mode: str = "single_quarter",
                 source_files: list[str] | None = None) -> int | None:
    """Persist facts as a new foi_datasets + foi_facts batch. Idempotent on
    canonical_hash: a re-run with the same facts returns the existing
    dataset_id without inserting rows. Returns None only on a transient DB
    error (best effort, fail-open); a schema or programming error raises so it
    is not silently hidden."""
    conn = conn or get_conn()
    h = canonical_hash(facts)
    try:
        existing = _dataset_exists(conn, h)
        if existing is not None:
            return existing
        srcs = source_files or ["(derived)", "data/sources/*.xlsx"]
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO horizon.foi_datasets "
                "(period_label, window_mode, source_files, normaliser_ver, "
                " canonical_hash, fact_count) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (period_label, window_mode, json.dumps(srcs), NORMALISER_VER, h,
                 len(facts)))
            dataset_id = cur.fetchone()[0]
            for f in facts:
                row = {k: f.get(k) for k in _CANONICAL_KEYS}
                cur.execute(
                    "INSERT INTO horizon.foi_facts "
                    "(dataset_id, agency_key, agency_name, fy, quarter, "
                    " measure_group, measure, bucket, value, derived, portfolio, row_hash) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (dataset_id, row["agency_key"], row["agency_name"], row["fy"],
                     row["quarter"], row["measure_group"], row["measure"],
                     row["bucket"], row["value"], bool(row["derived"]),
                     row.get("portfolio") or "",
                     hashlib.sha256(json.dumps(row, sort_keys=True).encode("utf-8")).hexdigest()))
        conn.commit()
        return dataset_id
    except psycopg2.OperationalError:
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    except psycopg2.Error:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def load_facts(dataset_id: int, *, conn=None) -> list[dict] | None:
    """Reload the long-form facts for a dataset as canonical dicts. Returns
    None only on a transient DB error (best effort); a schema or programming
    error raises so it is not silently hidden."""
    conn = conn or get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT agency_key, agency_name, fy, quarter, measure_group, "
                "measure, bucket, value, derived, portfolio "
                "FROM horizon.foi_facts WHERE dataset_id = %s "
                "ORDER BY agency_key, fy, quarter, measure_group, measure, bucket",
                (dataset_id,))
            rows = cur.fetchall()
        return [
            {"agency_key": r[0], "agency_name": r[1], "fy": r[2], "quarter": r[3],
             "measure_group": r[4], "measure": r[5], "bucket": r[6],
             "value": float(r[7]), "derived": bool(r[8]), "portfolio": r[9] or ""}
            for r in rows
        ]
    except psycopg2.OperationalError:
        return None
    except psycopg2.Error:
        raise
