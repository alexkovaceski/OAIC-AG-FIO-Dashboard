"""server.dashboards — dashboard persistence + render validation, shared by the
request path and the background build worker.

Everything here is conn-and-frame pure: no app-state imports, so the worker
(server.worker) can use the same load/validate helpers the routes use without
a circular import. The figure-op recorder stays in server.app (its record_op
monkeypatch seam lives there); the worker reaches it through a lazy import.
"""
from __future__ import annotations
import json

import psycopg2

from agentic.render import render_dashboard_page


def load_dashboard(artifact_id, conn):
    """Load (spec, transcript) for an artifact from the live DB.

    The spec is the durable spec_json the builder produced; the transcript is
    the recorded lineage_tool_calls rebuilt as {seq, tool, result} entries so
    render_dashboard_page's citation resolver ({c:job.turn.call.field}) can
    resolve against it. (spec, transcript) is (None, []) when the DB is
    unreachable (fail-open) or the artifact has no durable spec — the caller
    renders the honest degraded page instead. A schema/programming error raises
    (fail-loud, like the lineage viewer).
    """
    if conn is None:
        return None, []
    # N1: the route passes the URL path segment as a string. A numeric string is
    # a real artifact id; a non-numeric one (the local-<hex> synthetic id when
    # /ask failed open) against a LIVE db would raise psycopg2.DataError
    # (non-Operational) on the `id = %s` compare and 500. Normalize the id and
    # degrade on anything non-numeric.
    if isinstance(artifact_id, int):
        pass
    elif isinstance(artifact_id, str) and artifact_id.isdigit():
        artifact_id = int(artifact_id)
    else:
        return None, []
    spec = None
    calls = []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT spec_json FROM horizon.lineage_artifacts WHERE id = %s",
                (artifact_id,))
            row = cur.fetchone()
            if row is not None:
                spec = row[0]
            cur.execute(
                "SELECT seq, tool, output_json FROM horizon.lineage_tool_calls "
                "WHERE artifact_id = %s ORDER BY seq", (artifact_id,))
            calls = cur.fetchall()
    except psycopg2.OperationalError:
        return None, []
    except psycopg2.Error:
        raise
    if spec is None:
        return None, []
    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except Exception:
            return None, []  # not a spec we can render — degrade, never crash
    transcript = []
    for seq, tool, out in calls:
        if isinstance(out, str):
            try:
                out = json.loads(out)
            except Exception:
                pass
        transcript.append({"seq": seq, "tool": tool, "result": out})
    return spec, transcript


def spec_renders(spec, conn, artifact_id, frame) -> bool:
    """Does a built spec actually render against the recorded transcript?

    The GET path degrades honestly when a stored spec cannot render, but the
    build path can do better: verify BEFORE the artifact is marked ready, so a
    model-output defect (an unresolvable {c:...} pointer, a hallucinated panel)
    flips the row to error and the caller falls back, instead of shipping a
    dashboard link that dies at read time. Best-effort: a verification failure
    of any other kind returns True — verification must never fail a build.
    """
    try:
        _, transcript = load_dashboard(artifact_id, conn)
        render_dashboard_page(spec, frame, artifact_id, transcript)
        return True
    except (SystemExit, KeyError, ValueError, TypeError):
        return False
    except Exception:
        return True
