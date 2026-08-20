"""ingest — CLI entry point for the FOI ingest pipeline.

Runs the normalising loader and seeds the durable Postgres facts
(horizon.foi_datasets + foi_facts) via storage.facts.ingest_facts — idempotent
on canonical_hash, so a re-run over the same data is a no-op. Best-effort and
fail-open like the server boot: an unreachable Postgres reports and exits 0
(the demo still serves the in-memory frame), while a schema or programming error
exits 1 so it surfaces.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg2  # noqa: E402

import config  # noqa: E402
from ingest.normalise import normalise_all  # noqa: E402
from storage.frame import Frame  # noqa: E402
from storage.db import get_conn, ensure_schema  # noqa: E402
from storage.facts import ingest_facts  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    facts = normalise_all(config.DATA_SOURCES_DIR)
    frame = Frame(facts)
    frame.golden_check()  # the same data-integrity gate the server boot runs
    print(f"ingest: {len(facts)} canonical facts from {config.DATA_SOURCES_DIR}")
    try:
        conn = get_conn()
    except RuntimeError as exc:
        print(f"ingest: Postgres unreachable — facts NOT persisted (fail-open). {exc}")
        return 0
    try:
        ensure_schema(conn)
        dataset_id = ingest_facts(facts, conn=conn)
        if dataset_id is None:
            print("ingest: facts already present (idempotent no-op) or DB error.")
        else:
            print(f"ingest: persisted facts as foi_datasets id={dataset_id}")
        return 0
    except psycopg2.Error as exc:
        print(f"ingest: FATAL — schema/programming error persisting facts: {exc}")
        return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
