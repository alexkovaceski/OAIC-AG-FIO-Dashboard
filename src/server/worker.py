"""server.worker — the background build queue: the vitalrecord-style theatre.

Builds are claimed oldest-first from the queued artifact rows, run attempt by
attempt (tool calls cleared per attempt so citation pointers resolve against
that attempt's own transcript), and end in one of three terminal states the Ask
page renders:

  ready     — a dashboard that actually renders against its transcript
  fallback  — every attempt failed; result_json carries the deterministic
              router answer for the same question (never prose that cannot
              quote figures)
  error     — failed, and no deterministic answer exists either

The queue IS the DB, so a restart loses nothing: stuck 'building' rows are
flipped to error at boot (mark_interrupted) and 'queued' rows are claimed
again. One job runs at a time — the queue serialises the LLM load, which is
also what keeps the model backend healthy while users wait in the theatre.
"""
from __future__ import annotations
import asyncio
import logging

from agentic.builder import build_spec
from agentic.report import build_report
from server.dashboards import spec_renders
from storage.lineage import (append_progress, claim_next_job, reset_attempt,
                             set_job_result, update_artifact)

_LOGGER = logging.getLogger("foi-insights.worker")

POLL_SECONDS = 2.0
MAX_ATTEMPTS = 2


def _fallback_result(request_text: str, frame) -> dict | None:
    """The deterministic answer for a failed build, or None when the router has
    nothing for the question either (the job then ends plain error)."""
    out = build_report(request_text, frame)
    if out.get("escalate") or out.get("model") == "no-match":
        return None
    if out.get("data") is None and not out.get("note"):
        return None
    return {"stat_key": out.get("stat_key"), "stat_label": out.get("stat_label"),
            "data": out.get("data"), "basis": out.get("basis"),
            "note": out.get("note"),
            "dataset_registry": out.get("dataset_registry"),
            "kind": ("note" if (out.get("note") and out.get("data") is None)
                     else "stat")}


async def run_job(frame, conn, job, complete_fn, ledger,
                  max_attempts: int = MAX_ATTEMPTS) -> str:
    """Run one claimed job to a terminal state. Returns the terminal status."""
    aid = job["id"]
    dataset_id = job.get("dataset_id")
    request_text = job["request_text"]

    def progress(step, detail):
        try:
            append_progress(conn, aid, step, detail)
        except Exception:
            pass

    for attempt in range(1, max_attempts + 1):
        # a fresh transcript per attempt: citation pointers are per-run and
        # sequence numbers restart, so stale calls would misresolve
        reset_attempt(conn, aid)
        progress("building", f"attempt {attempt} of {max_attempts}")
        prompt = (request_text if attempt == 1
                  else request_text + " — return ONLY the JSON spec with "
                         "panels, using the tools for real data; do not explain.")
        try:
            spec = await build_spec(prompt, frame, complete_fn, ledger, conn,
                                    max_turns=6, artifact_id=aid,
                                    progress=progress)
        except Exception as exc:
            progress("failed", f"attempt {attempt} raised: {exc}")
            continue
        panels = spec.get("panels") if isinstance(spec, dict) else []
        if not panels:
            progress("retry", f"attempt {attempt} produced no panels")
            continue
        update_artifact(conn, aid, spec_json=spec, status="ready")
        if spec_renders(spec, conn, aid, frame):
            # the figure-op recorder lives in server.app (its record_op
            # monkeypatch seam); import lazily to avoid the cycle
            from server import app as _app
            _app._record_figure_ops(conn, frame, aid, dataset_id, spec)
            set_job_result(conn, aid, status="ready", result=None,
                           step="ready", detail="dashboard built")
            return "ready"
        progress("failed", f"attempt {attempt} produced an unrenderable spec")

    fallback = _fallback_result(request_text, frame)
    if fallback is not None:
        set_job_result(conn, aid, status="error", result=fallback,
                       step="fallback",
                       detail="dashboard build failed; the computed figure "
                              "is shown instead")
        return "fallback"
    set_job_result(conn, aid, status="error", result=None,
                   step="failed",
                   detail="no renderable dashboard and no computed figure")
    return "error"


async def run_due_jobs(frame, get_conn, complete_fn, ledger,
                       poll_seconds: float = POLL_SECONDS) -> None:
    """The queue loop: claim the oldest queued job, run it, repeat. A transient
    DB error just skips a cycle; jobs stay queued in the table. Never exits."""
    while True:
        try:
            conn = get_conn()
            if conn is not None:
                try:
                    job = claim_next_job(conn)
                    if job is not None:
                        await run_job(frame, conn, job, complete_fn, ledger)
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
        except Exception:
            _LOGGER.warning("worker loop error", exc_info=True)
        await asyncio.sleep(poll_seconds)
