"""app — the FOI Insights FastAPI service (no auth, hosted demo).

Routes:
  GET  /health                    {"status":"ok","model":"fartkraft sovereign stack"}
  GET  /                          at-a-glance page
  GET  /{page}.html               the 12 static pages (404 on unknown)
  GET  /assets/{file}             static assets (site.css, ...)
  POST /ask                       {request} -> {artifact_id, dashboard_url, lineage_url}
  GET  /lineage/{artifact_id}     lineage explainability page

Boot gate: create_app() builds the frame from normalise_all() and runs
frame.golden_check() — the data-integrity gate. A mismatch aborts loudly
(SystemExit) so the app never serves wrong data. The frame and the rendered
pages are built once and cached at module scope: re-normalising 7 xlsx files
per request would make every page load spend ~1.5s on IO the data cannot change
within a process.

Lineage is best-effort by design (Task 4): a reachable Postgres records the
artifact and tool-call transcript; an unreachable one degrades the /ask reply
to a synthetic artifact id and the lineage page to an honest degraded render —
the build must never fail on a down DB, but it must also never pretend it wrote
something it did not. /ask pre-runs check_request before any artifact row is
created, so a scope refusal never leaves a stuck status="building" row.

CPython 3.13 freezes the stdlib `site` module, so src/site cannot be imported
as `site.*` without the shim. site_shim.install() MUST run before any
`from site... import ...` line below (and before `import server.app` in
scripts/serve.py).
"""
from __future__ import annotations

import site_shim  # noqa: E402
site_shim.install()  # noqa: E402

import os  # noqa: E402

import httpx  # noqa: E402
import psycopg2  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from config import STATIC_DIR  # noqa: E402
from ingest.normalise import normalise_all  # noqa: E402
from storage.frame import Frame  # noqa: E402
from storage.db import get_conn, ensure_schema  # noqa: E402
from storage.lineage import Ledger, record_artifact, update_artifact  # noqa: E402
from site.pages import render_all_pages  # noqa: E402
from site.lineage_viewer import render_lineage_page  # noqa: E402
from agentic.builder import build_spec  # noqa: E402
from agentic.guardrails import check_request, ScopeRefusal  # noqa: E402

# The golden boot check runs once at import; the frame and pages are immutable
# within a process, so they are cached at module scope rather than re-derived
# per request (normalise_all re-reads 7 xlsx files and render_all_pages
# recomputes every figure from the frame — both are pure frame/disk -> HTML).
_FRAME = None
_PAGES = None
# A module-scope ledger reused by every /ask: Ledger() opens a file handle, so
# a per-request ledger would leak one FD per request (reviewer I4).
_LEDGER = None


def _get_ledger() -> Ledger:
    global _LEDGER
    if _LEDGER is None:
        _LEDGER = Ledger()
    return _LEDGER


def _boot() -> tuple[Frame, dict[str, str]]:
    """Build the frame, run the golden data-integrity gate, render the pages.

    The golden check is the hard gate: a mismatch means the normaliser or the
    source data has drifted from the published Q1 2025-26 figures — the app must
    not serve wrong data, so it aborts loudly (SystemExit) instead of degrading.
    """
    global _FRAME, _PAGES
    if _FRAME is None:
        frame = Frame(normalise_all())
        frame.golden_check()
        _FRAME = frame
    if _PAGES is None:
        _PAGES = render_all_pages(_FRAME)
    return _FRAME, _PAGES


class AskRequest(BaseModel):
    request: str


def create_app():
    """Build the FastAPI app. The golden gate runs here; a data-integrity
    mismatch raises SystemExit, so the app cannot start on wrong data."""
    frame, pages = _boot()

    app = FastAPI(title="FOI Insights")
    app.state.frame = frame
    app.state.pages = pages

    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")

    @app.get("/health")
    def health():
        return {"status": "ok", "model": "fartkraft sovereign stack"}

    @app.get("/")
    def index():
        return HTMLResponse(pages["at-a-glance"])

    @app.get("/{page}.html")
    def page(page: str):
        if page in pages:
            return HTMLResponse(pages[page])
        return JSONResponse({"error": "not found"}, status_code=404)

    @app.post("/ask")
    async def ask(req: AskRequest):
        # I3: pre-run the scope guard BEFORE any artifact row is created, so a
        # refusal never leaves a stuck status="building" row behind. build_spec
        # runs it again for defence-in-depth; the route-level run is what
        # guarantees no row exists for a refused request.
        try:
            check_request(req.request)
        except ScopeRefusal as exc:
            return {"error": str(exc), "artifact_id": None,
                    "dashboard_url": None, "lineage_url": None}
        ledger = _get_ledger()
        # build_id is what build_spec receives; response_id is what the client
        # gets. build_id is a real int only when a lineage_artifacts row truly
        # exists (or None otherwise) — never a synthetic string.
        build_id = None
        response_id = f"local-{len((req.request or '').encode('utf-8')):x}"
        try:
            conn = get_conn()
            ensure_schema(conn)
        except (RuntimeError, psycopg2.OperationalError):
            # I2: fail-open — an unreachable DB (connect or schema) must not
            # kill /ask. No artifact row exists, so the builder gets
            # conn=None + build_id=None (its None-path skips tool-call writes,
            # never NULLing the NOT NULL FK) and the client gets a deterministic
            # synthetic id so the lineage URL stays stable.
            conn = None
        else:
            # Task 6 carry-forward: the artifact row is PRE-CREATED
            # (record_artifact returns its real id) and that id is passed into
            # build_spec, so the builder's tool_calls key to THIS row — never to
            # a second artifact. The row (id, status="building") must exist
            # before any tool call is recorded: lineage_tool_calls.artifact_id
            # is a NOT NULL FK.
            build_id = record_artifact(
                conn, artifact_type="builder_request",
                artifact_key=(req.request or "")[:40], user_id=None,
                dataset_id=1, request_text=req.request, spec_json={},
                model="fartkraft", status="building")
            if build_id is None:
                # I1: the artifact INSERT failed open to None even though the
                # conn is live. No real row exists — drop the conn and give the
                # builder the None-path. Never hand build_spec a synthetic
                # string as a real artifact_id with a live conn: a recovered DB
                # would make the builder's record_tool_call hit "invalid input
                # syntax for type integer" (a non-Operational psycopg2.Error)
                # and re-raise, aborting the build.
                conn = None
            response_id = (build_id if build_id is not None
                           else f"local-{len((req.request or '').encode('utf-8')):x}")
        try:
            spec = await build_spec(
                req.request, frame, _complete_fn, ledger, conn,
                max_turns=6, artifact_id=build_id)
        except Exception as exc:
            # a genuine build error (not a refusal — those were screened above):
            # flip any real row to status="error" so it is not stuck "building"
            if conn is not None and isinstance(build_id, int):
                try:
                    update_artifact(conn, build_id, status="error")
                except Exception:
                    pass  # best-effort: the error response always wins
            return {"error": str(exc), "artifact_id": response_id,
                    "dashboard_url": None, "lineage_url": None}
        if conn is not None and isinstance(build_id, int):
            update_artifact(conn, build_id, spec_json=spec, status="ready")
        return {"artifact_id": response_id,
                "dashboard_url": "/at-a-glance.html",
                "lineage_url": f"/lineage/{response_id}"}

    @app.get("/lineage/{artifact_id}")
    def lineage(artifact_id: str):
        # conn=None: the viewer degrades to an honest "no live lineage" page
        # (data dict + no conn -> no artifact/dataset/ops/tool_calls). A live
        # Postgres wiring is Task 9/10; the page must never 500 on a down DB.
        return HTMLResponse(render_lineage_page(artifact_id, None))

    return app


async def _complete_fn(messages):
    """Call the local model endpoint (idc-1, or FOI_LLM_URL) with the messages.

    The identity stovepipe lives in build_spec (Task 6); this function only
    forwards the assembled messages and returns the model's raw text. The
    deterministic canned spec is the LOAD-BEARING fallback: on ANY failure —
    endpoint down, timeout, non-2xx, malformed body, missing content field —
    the demo must still return a valid spec, so /ask never dies.
    """
    url = os.environ.get("FOI_LLM_URL", "http://idc-1:8012/v1/chat/completions")
    try:
        payload = {"model": os.environ.get("FOI_LLM_MODEL", "qwen3next-80b"),
                   "messages": messages, "temperature": 0.2}
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(url, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    except Exception:
        # deterministic fallback — the demo always returns a valid spec
        return ('{"title": "FOI request summary", '
                '"description": "FOI Insights demo — deterministic completion '
                '(live model unavailable).", "panels": []}')
