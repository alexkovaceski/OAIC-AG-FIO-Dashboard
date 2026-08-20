"""db — Postgres connection + idempotent schema (migrate.sql).

No live Postgres is required to import this module or run the test suite:
get_conn() only raises when it is actually called without a reachable DB.
"""
from __future__ import annotations
from pathlib import Path

import psycopg2

from config import PG_DSN

MIGRATE_SQL = Path(__file__).resolve().parent.parent / "server" / "migrate.sql"


def get_conn():
    """Return a psycopg2 connection to the horizon DB (PG_DSN).

    Raises a clear error if the DB is unreachable — callers in the tests never
    call this, so the suite runs without a live Postgres.
    """
    try:
        return psycopg2.connect(PG_DSN)
    except psycopg2.Error as exc:
        raise RuntimeError(
            f"cannot connect to Postgres ({PG_DSN!r}); is the horizon DB up? "
            f"Set FOI_PG_DSN to override. {exc}"
        ) from exc


def ensure_schema(conn=None):
    """Run migrate.sql (idempotent: CREATE IF NOT EXISTS). Returns the conn used."""
    own = conn is None
    conn = conn or get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(MIGRATE_SQL.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        if own:
            conn.close()
    return conn
