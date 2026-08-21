"""lineage_viewer — the /lineage/{artifact_id} explainability page.

Renders the full lineage of one dashboard artifact: the request that built it,
the dataset snapshot it read (source files, hashes, window_mode), the
tool-call transcript, and the computed figures — with a link back to the
dashboard.

Testable without a live Postgres: callers may pass `data` as a dict shaped
like {artifact, dataset, ops, tool_calls}; when `conn` is given (and data is
not), the page reads from the horizon lineage tables. With neither, it renders
an honest degraded page — never a crash (best-effort, like the ledger).
"""
from __future__ import annotations
import html
import json

import psycopg2

from site.templates import chrome


def _s(data, key):
    """Data-source pick: an explicit dict wins; otherwise read from the DB via
    the connection (which may be None — every read is best-effort)."""
    if data is not None:
        return data.get(key) or None
    return None


def _load_artifact(artifact_id, conn):
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT artifact_type, artifact_key, user_id, dataset_id, "
                "request_text, spec_json, model, status "
                "FROM horizon.lineage_artifacts WHERE id = %s", (artifact_id,))
            row = cur.fetchone()
        if not row:
            return None
        return {"artifact_type": row[0], "artifact_key": row[1],
                "user_id": row[2], "dataset_id": row[3],
                "request_text": row[4], "spec_json": row[5],
                "model": row[6], "status": row[7]}
    except psycopg2.OperationalError:
        return None  # fail-open: an unreachable DB must not crash a page
    except psycopg2.Error:
        raise        # fail-loud: a schema/programming error must surface


def _load_dataset(dataset_id, conn):
    if conn is None or dataset_id is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT period_label, window_mode, source_files, normaliser_ver, "
                "canonical_hash, fact_count FROM horizon.foi_datasets "
                "WHERE id = %s", (dataset_id,))
            row = cur.fetchone()
        if not row:
            return None
        return {"period_label": row[0], "window_mode": row[1],
                "source_files": row[2], "normaliser_ver": row[3],
                "canonical_hash": row[4], "fact_count": row[5]}
    except psycopg2.OperationalError:
        return None  # fail-open: an unreachable DB must not crash a page
    except psycopg2.Error:
        raise        # fail-loud: a schema/programming error must surface


def _load_ops(artifact_id, conn):
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, kind, op, params, row_count, rows_hash, result_value "
                "FROM horizon.lineage_ops WHERE artifact_id = %s "
                "ORDER BY id", (artifact_id,))
            rows = cur.fetchall()
        return [{"id": r[0], "kind": r[1], "op": r[2], "params": r[3],
                 "row_count": r[4], "rows_hash": r[5], "result_value": r[6]}
                for r in rows]
    except psycopg2.OperationalError:
        return None  # fail-open: an unreachable DB must not crash a page
    except psycopg2.Error:
        raise        # fail-loud: a schema/programming error must surface


def _load_tool_calls(artifact_id, conn):
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT seq, tool, op, input_json, output_json "
                "FROM horizon.lineage_tool_calls WHERE artifact_id = %s "
                "ORDER BY seq", (artifact_id,))
            rows = cur.fetchall()
        return [{"seq": r[0], "tool": r[1], "op": r[2],
                 "input_json": r[3], "output_json": r[4]} for r in rows]
    except psycopg2.OperationalError:
        return None  # fail-open: an unreachable DB must not crash a page
    except psycopg2.Error:
        raise        # fail-loud: a schema/programming error must surface


def _pre(obj) -> str:
    """Render a Python object as a <pre> block (JSON for dicts/lists)."""
    if isinstance(obj, (dict, list)):
        return html.escape(json.dumps(obj, indent=2, default=str))
    return html.escape(str(obj))


def _section(title, body, empty_msg) -> str:
    if body is None:
        return (f'<section><h2>{html.escape(title)}</h2>'
                f'<p class="nodata">{empty_msg}</p></section>')
    return f'<section><h2>{html.escape(title)}</h2>{body}</section>'


def render_lineage_page(artifact_id, conn=None, *, data=None) -> str:
    """Render the lineage explainability page for one artifact.

    Parameters
    ----------
    artifact_id : int | str
        The lineage_artifacts.id (or its dashboard key, e.g. "at-a-glance").
    conn : conn, optional
        A psycopg2 connection; when given, the page reads the horizon lineage
        tables. Best-effort — a read error degrades, never crashes.
    data : dict, optional
        For tests / callers without a DB: {artifact, dataset, ops, tool_calls}.
        When provided, it takes precedence over `conn`.

    Returns the full HTML page.
    """
    artifact = _s(data, "artifact") or _load_artifact(artifact_id, conn)
    dataset_id = (artifact or {}).get("dataset_id")
    dataset = _s(data, "dataset") or _load_dataset(dataset_id, conn)
    ops = _s(data, "ops") or _load_ops(artifact_id, conn)
    tool_calls = _s(data, "tool_calls") or _load_tool_calls(artifact_id, conn)

    request = (artifact or {}).get("request_text")
    if isinstance(request, dict):
        request = json.dumps(request, default=str)
    model = (artifact or {}).get("model")
    status = (artifact or {}).get("status")

    request_html = (f'<pre id="request">{html.escape(str(request))}</pre>'
                    if request else
                    '<p class="nodata">No request recorded for this artifact.</p>')
    meta_html = ""
    if model or status:
        bits = [f"model: {html.escape(str(model))}" if model else "",
                f"status: {html.escape(str(status))}" if status else ""]
        meta_html = f'<p class="meta">{", ".join(b for b in bits if b)}</p>'

    if dataset:
        srcs = dataset.get("source_files") or []
        if isinstance(srcs, str):
            try:
                srcs = json.loads(srcs)
            except Exception:
                srcs = [srcs]
        src_lines = "\n".join(
            f"- {html.escape(str(s))}" for s in srcs)
        snapshot = (f'<pre id="snapshot">period_label: {html.escape(str(dataset.get("period_label", "")))}\n'
                    f'window_mode: {html.escape(str(dataset.get("window_mode", "")))}\n'
                    f'normaliser_ver: {html.escape(str(dataset.get("normaliser_ver", "")))}\n'
                    f'canonical_hash: {html.escape(str(dataset.get("canonical_hash", "")))}\n'
                    f'fact_count: {html.escape(str(dataset.get("fact_count", "")))}\n'
                    f'source files:\n{src_lines}</pre>')
    else:
        snapshot = ('<pre id="snapshot">source files, hashes, window_mode '
                    'unavailable</pre>')

    if ops is not None and ops:
        op_blocks = []
        for op in ops:
            val = op.get("result_value")
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    pass
            op_blocks.append(
                f'<div class="op"><strong>{html.escape(str(op.get("kind", "")))} '
                f'· {html.escape(str(op.get("op", "")))}</strong> '
                f'<span class="meta">rows: {html.escape(str(op.get("row_count", "")))} · '
                f'hash: {html.escape(str(op.get("rows_hash", "")))}</span>'
                f'<pre>{_pre(val)}</pre></div>')
        transcript = "\n".join(op_blocks)
    else:
        transcript = ('<p class="nodata">No computed figures recorded for this '
                      'artifact.</p>')

    if tool_calls is not None and tool_calls:
        call_blocks = []
        for c in tool_calls:
            call_blocks.append(
                f'<div class="call"><strong>{html.escape(str(c.get("seq", "")))} · '
                f'{html.escape(str(c.get("tool", "")))} · '
                f'{html.escape(str(c.get("op", "")))}</strong>'
                f'<pre class="callio">in:  {_pre(c.get("input_json"))}\n'
                f'out: {_pre(c.get("output_json"))}</pre></div>')
        tool_html = "\n".join(call_blocks)
    else:
        tool_html = ('<p class="nodata">No tool-call transcript recorded for '
                     'this artifact.</p>')

    body = f"""
    <h1>Lineage — {html.escape(str(artifact_id))}</h1>
    {meta_html}
    {_section("Request", request_html, "No request text available.")}
    {_section("Dataset snapshot", snapshot, "Dataset snapshot unavailable.")}
    {_section("Tool-call transcript", tool_html,
              "No tool calls recorded.")}
    {_section("Computed figures", transcript,
              "No computed figures recorded.")}
    <p><a href="/">← back to dashboard</a></p>"""
    return chrome(f"Lineage — {artifact_id}", body,
                  page_key="lineage")
