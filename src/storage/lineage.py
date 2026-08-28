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
import hashlib
import json
import os
from pathlib import Path

import psycopg2

LINEAGE_EVENTS = ("data_loaded", "request_received", "tool_call", "spec_selected",
                  "build_computed", "output_written", "review_verdict")

# stats.catalog.hash_rows([]) — sha256 over an EMPTY row set. Computed here, not
# imported, so this module keeps working before the catalog is built (see
# _replay_default_compute). A stored op carrying this hash has no verifiable row
# basis, and comparing it to a recomputed copy of itself is a green tick over
# nothing — replay_verify treats it as UNVERIFIABLE, not as a pass.
EMPTY_ROWS_HASH = hashlib.sha256(b"").hexdigest()


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
            self._f.flush()
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


def update_artifact(conn, artifact_id, *, spec_json=None, status=None):
    """Update a lineage_artifacts row (spec_json / status). No-op when nothing
    to set. Best-effort, same split as record_artifact: OperationalError ->
    swallowed (the build must never fail on an unreachable DB); any other
    psycopg2.Error raises so a schema/programming error is not hidden."""
    fields, values = [], []
    if spec_json is not None:
        fields.append("spec_json = %s")
        values.append(json.dumps(spec_json))
    if status is not None:
        fields.append("status = %s")
        values.append(status)
    if not fields:
        return
    values.append(artifact_id)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE horizon.lineage_artifacts SET "
                + ", ".join(fields) + " WHERE id = %s",
                tuple(values))
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


def list_artifacts(conn, *, limit=12, artifact_type="builder_request",
                   user_id=None) -> list[dict]:
    """Recent artifacts of a type, newest first — the user's built reports.

    `user_id` scopes the list to one user's reports ("My reports"); None lists
    every artifact of the type (the pre-scoping behaviour, kept for callers
    without a user).

    Best-effort: OperationalError -> [] (an unreachable DB must not break the
    reports page); any other psycopg2.Error raises so a schema/programming error
    is not hidden. Ordered by id DESC (id is monotonic, so this is newest-first).

    `panel_count` lets the reports page tell a genuinely built report (ready with
    panels) from a ready-but-empty one (a failed build that was wrongly stored
    empty before the empty-spec guard existed), and `created_at` puts a time on
    each row.
    """
    try:
        with conn.cursor() as cur:
            if user_id is not None:
                cur.execute("""
                    SELECT id, request_text, status, created_at,
                           COALESCE(jsonb_array_length(spec_json->'panels'), 0),
                           progress_json
                    FROM horizon.lineage_artifacts
                    WHERE artifact_type = %s AND user_id = %s
                    ORDER BY id DESC LIMIT %s
                """, (artifact_type, user_id, limit))
            else:
                cur.execute("""
                    SELECT id, request_text, status, created_at,
                           COALESCE(jsonb_array_length(spec_json->'panels'), 0),
                           progress_json
                    FROM horizon.lineage_artifacts
                    WHERE artifact_type = %s
                    ORDER BY id DESC LIMIT %s
                """, (artifact_type, limit))
            return [{"id": r[0], "request_text": r[1] or "",
                     "status": r[2] or "", "created_at": r[3],
                     "panel_count": int(r[4] or 0),
                     "progress": r[5] or []} for r in cur.fetchall()]
    except psycopg2.OperationalError:
        return []


def delete_artifact(conn, artifact_id, user_id=None) -> bool:
    """Delete an artifact and its dependent lineage rows (tool calls + ops).

    `user_id` scopes the delete to the caller's own reports: with it set, a row
    owned by someone else (or unowned legacy rows) is left alone and the call
    returns False. None deletes regardless of ownership (the pre-scoping
    behaviour).

    A DELETE is a user-initiated state change, not a background write, so it does
    NOT fail open like the record_* writes: a DB error raises here so the caller
    can tell the reader the delete did not happen, rather than a row silently
    surviving. Returns True when the artifact row was deleted, False when there
    was nothing to delete (absent id, or not the caller's row).
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM horizon.lineage_tool_calls WHERE artifact_id = %s",
                    (artifact_id,))
        cur.execute("DELETE FROM horizon.lineage_ops WHERE artifact_id = %s",
                    (artifact_id,))
        if user_id is None:
            cur.execute("DELETE FROM horizon.lineage_artifacts WHERE id = %s",
                        (artifact_id,))
        else:
            cur.execute(
                "DELETE FROM horizon.lineage_artifacts "
                "WHERE id = %s AND (user_id = %s OR user_id IS NULL)",
                (artifact_id, user_id))
        deleted = cur.rowcount
    conn.commit()
    return deleted > 0


# ----------------------------------------------- the build queue (theatre) ----

def append_progress(conn, artifact_id, step: str, detail: str) -> None:
    """Append one theatre step to an artifact's progress list. Best-effort like
    the other writes: the build must never fail because a progress tick did."""
    from datetime import datetime, timezone
    row = json.dumps([{"step": step, "detail": detail,
                       "at": datetime.now(timezone.utc).isoformat()}])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE horizon.lineage_artifacts "
                "SET progress_json = progress_json || %s::jsonb WHERE id = %s",
                (row, artifact_id))
            conn.commit()
    except psycopg2.Error:
        try:
            conn.rollback()
        except Exception:
            pass


def claim_next_job(conn) -> dict | None:
    """The oldest queued builder job, flipped to building. Returns {id,
    request_text, user_id, dataset_id} or None when the queue is empty. A single
    worker process runs, so select-then-update is safe; the update re-checks
    status so a crash between the two cannot double-run."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, request_text, user_id, dataset_id FROM "
                "horizon.lineage_artifacts "
                "WHERE artifact_type = 'builder_request' AND status = 'queued' "
                "ORDER BY id LIMIT 1")
            row = cur.fetchone()
            if row is None:
                return None
            aid, request_text, user_id, dataset_id = row
            cur.execute(
                "UPDATE horizon.lineage_artifacts SET status = 'building' "
                "WHERE id = %s AND status = 'queued'", (aid,))
            if cur.rowcount != 1:
                return None
            conn.commit()
            return {"id": aid, "request_text": request_text or "",
                    "user_id": user_id, "dataset_id": dataset_id}
    except psycopg2.OperationalError:
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def requeue_job(conn, artifact_id, user_id=None) -> bool:
    """Put a finished (or failed) job back on the queue, e.g. the Ask page's
    'try again'. Scoped to the caller like delete_artifact. Returns True when a
    row was re-queued."""
    try:
        with conn.cursor() as cur:
            if user_id is None:
                cur.execute(
                    "UPDATE horizon.lineage_artifacts SET status = 'queued' "
                    "WHERE id = %s AND artifact_type = 'builder_request' "
                    "AND status IN ('error', 'ready')", (artifact_id,))
            else:
                cur.execute(
                    "UPDATE horizon.lineage_artifacts SET status = 'queued' "
                    "WHERE id = %s AND artifact_type = 'builder_request' "
                    "AND status IN ('error', 'ready') "
                    "AND (user_id = %s OR user_id IS NULL)",
                    (artifact_id, user_id))
            updated = cur.rowcount
        conn.commit()
        return updated > 0
    except psycopg2.OperationalError:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def reset_attempt(conn, artifact_id) -> None:
    """Clear a job's recorded tool calls so a retry starts its own transcript
    with sequence numbers from 1 (citation pointers resolve per attempt)."""
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM horizon.lineage_tool_calls "
                        "WHERE artifact_id = %s", (artifact_id,))
            conn.commit()
    except psycopg2.OperationalError:
        try:
            conn.rollback()
        except Exception:
            pass


def mark_interrupted(conn) -> None:
    """Boot recovery: a 'building' row orphaned by a restart can never finish.
    Flip every stuck row to error with an honest step."""
    from datetime import datetime, timezone
    row = json.dumps([{"step": "failed", "detail": "interrupted by a restart",
                       "at": datetime.now(timezone.utc).isoformat()}])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE horizon.lineage_artifacts "
                "SET status = 'error', progress_json = progress_json || %s::jsonb "
                "WHERE artifact_type = 'builder_request' AND status = 'building'",
                (row,))
            conn.commit()
    except psycopg2.OperationalError:
        try:
            conn.rollback()
        except Exception:
            pass


def set_job_result(conn, artifact_id, *, status: str, result: dict | None,
                   step: str, detail: str) -> None:
    """Terminal write for a job: status, the fallback answer when there is one,
    and the closing theatre step. Best-effort."""
    from datetime import datetime, timezone
    row = json.dumps([{"step": step, "detail": detail,
                       "at": datetime.now(timezone.utc).isoformat()}])
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE horizon.lineage_artifacts SET status = %s, "
                "result_json = %s::jsonb, "
                "progress_json = progress_json || %s::jsonb WHERE id = %s",
                (status, json.dumps(result or {}), row, artifact_id))
            conn.commit()
    except psycopg2.OperationalError:
        try:
            conn.rollback()
        except Exception:
            pass


def get_job_status(conn, artifact_id) -> dict | None:
    """The theatre payload for one job: status, step list, fallback result."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, progress_json, result_json FROM "
                "horizon.lineage_artifacts WHERE id = %s "
                "AND artifact_type = 'builder_request'", (artifact_id,))
            row = cur.fetchone()
        if row is None:
            return None
        return {"status": row[0] or "", "progress": row[1] or [],
                "result": row[2] or {}}
    except psycopg2.OperationalError:
        return None


def may_access_artifact(conn, artifact_id, user_id) -> bool | None:
    """May this signed-in user view the artifact behind /dashboards or
    /lineage? True = yes, False = someone else's report, None = no such row.

    Builder reports are private to their owner. Every other artifact kind
    (static_page, model_fit) is platform data, and a legacy builder row with no
    owner is an orphan any signed-in user may see. Fails open on a transient DB
    error: the caller's route still requires a session, and the page degrades
    honestly when the store is unreachable.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, artifact_type FROM horizon.lineage_artifacts "
                "WHERE id = %s", (artifact_id,))
            row = cur.fetchone()
    except psycopg2.OperationalError:
        return True
    if row is None:
        return None
    owner, atype = row[0], row[1]
    if atype != "builder_request" or owner is None:
        return True
    return owner == user_id


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
    foi_stats (lazy import). On any recompute error, when the stored hash is
    empty, or when it is EMPTY_ROWS_HASH, replay fails closed (returns False) —
    a lineage replay must never crash a build, and an unverifiable row must not
    pass.

    The EMPTY_ROWS_HASH guard is the one that was missing: a stat that recorded
    hash_rows([]) stored a truthy 64-char string, so both sides of the compare
    were the same sentinel and the row passed with no row basis behind it.
    """
    compute = compute or _replay_default_compute
    try:
        _, rows_hash = compute(op_row)
        stored = op_row.get("rows_hash")
    except Exception:
        return False
    if not stored or stored == EMPTY_ROWS_HASH:
        return False
    return rows_hash == stored
