"""lineage — hybrid ledger: JSONL firehose + Postgres lineage tables.

Best-effort: a lineage failure must never fail a build (fail-open, like the
governor). The JSONL is the raw event stream; the Postgres tables are the
queryable mirror.

The record_* functions follow the Task 3 fail-open split: a transient DB error
(psycopg2.OperationalError) degrades to None / is swallowed, so the build never
fails on an unreachable DB; any other psycopg2.Error raises, so a schema or
programming error surfaces instead of being silently hidden.
"""
from __future__ import annotations
import json
import os
from pathlib import Path

import psycopg2

LINEAGE_EVENTS = ("data_loaded", "request_received", "tool_call", "spec_selected",
                  "build_computed", "output_written", "review_verdict")


class Ledger:
    """JSONL firehose — the raw best-effort event stream. append() never raises."""

    def __init__(self, ledger_path=None):
        self.path = Path(ledger_path or os.environ.get("FOI_LEDGER", "data/generated/lineage.jsonl"))
        self._f = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._f = open(self.path, "a", encoding="utf-8")
        except OSError:
            self._f = None  # fail-open: an unwritable ledger must never break a build

    def append(self, event: dict):
        if not isinstance(event, dict) or self._f is None:
            return
        try:
            self._f.write(json.dumps(event, default=str) + "\n")
        except Exception:
            pass  # never raise

    def flush(self):
        if self._f is not None:
            try:
                self._f.flush()
            except Exception:
                pass

    def close(self):
        if self._f is not None:
            try:
                self._f.close()
            except Exception:
                pass
            self._f = None


def record_artifact(conn, *, artifact_type, artifact_key, user_id, dataset_id,
                    request_text, spec_json, model, status) -> int | None:
    """Insert a lineage_artifacts row and return its id (RETURNING id).

    Best-effort: OperationalError -> None (the build must never fail on an
    unreachable DB); any other psycopg2.Error raises so it is not hidden."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO horizon.lineage_artifacts
                (artifact_type, artifact_key, user_id, dataset_id, request_text,
                 spec_json, model, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id
            """, (artifact_type, artifact_key, user_id, dataset_id, request_text,
                  json.dumps(spec_json), model, status))
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None
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


def record_op(conn, *, artifact_id, dataset_id, kind, op, params, row_count, rows_hash, result_value):
    """Insert a lineage_ops row. Best-effort, same split as record_artifact."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO horizon.lineage_ops
                (artifact_id, dataset_id, kind, op, params, row_count, rows_hash, result_value)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (artifact_id, dataset_id, kind, op, json.dumps(params), row_count,
                  rows_hash, json.dumps(result_value, default=str)))
            conn.commit()
    except psycopg2.OperationalError:
        try:
            conn.rollback()
        except Exception:
            pass
    except psycopg2.Error:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def record_tool_call(conn, *, artifact_id, seq, tool, op, input_json, output_json):
    """Insert a lineage_tool_calls row. Best-effort, same split as record_artifact."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO horizon.lineage_tool_calls
                (artifact_id, seq, tool, op, input_json, output_json)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (artifact_id, seq, tool, op, json.dumps(input_json), json.dumps(output_json)))
            conn.commit()
    except psycopg2.OperationalError:
        try:
            conn.rollback()
        except Exception:
            pass
    except psycopg2.Error:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def _replay_default_compute(op_row):
    """Default recompute for replay_verify: Task 5's foi_stats over the facts
    for the dataset_id. Lazy imports keep this module working before the catalog
    exists. Raises if the catalog is not built or the facts cannot be loaded;
    replay_verify catches that and fails open (returns False)."""
    from stats.catalog import foi_stats  # lazy — Task 5 builds stats.catalog
    from storage.facts import load_facts
    from storage.frame import Frame
    dataset_id = op_row["dataset_id"]
    facts = load_facts(dataset_id)
    if not facts:
        raise RuntimeError(f"no facts to replay for dataset {dataset_id}")
    result = foi_stats(Frame(facts), op_row["op"])
    return result.get("value"), result.get("rows_hash")


def replay_verify(conn, op_row, compute=None) -> bool:
    """Recompute an op from (dataset_id, op, params) and compare to the stored
    rows_hash. Never trusts the stored value.

    compute(op_row) -> (value, rows_hash); the default recomputes via Task 5's
    foi_stats (lazy import). On any recompute error, or when the stored hash is
    empty, replay fails open (returns False) — a lineage replay must never crash
    a build, and an unverifiable row must not pass.
    """
    compute = compute or _replay_default_compute
    try:
        _, rows_hash = compute(op_row)
        stored = op_row.get("rows_hash")
    except Exception:
        return False
    return bool(stored) and rows_hash == stored
