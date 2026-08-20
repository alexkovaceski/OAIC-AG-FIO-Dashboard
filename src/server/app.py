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
something it did not.

CPython 3.13 freezes the stdlib `site` module, so src/site cannot be imported
as `site.*` without the shim. site_shim.install() MUST run before any
`from site... import ...` line below (and before `import server.app` in
scripts/serve.py).
"""
from __future__ import annotations

import site_shim  # noqa: E402
site_shim.install()  # noqa: E402

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

# The golden boot check runs once at import; the frame and pages are immutable
# within a process, so they are cached at module scope rather than re-derived
# per request (normalise_all re-reads 7 xlsx files and render_all_pages
# recomputes every figure from the frame — both are pure frame/disk -> HTML).
_FRAME = None
_PAGES = None


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
        # Task 6 carry-forward: the artifact row is PRE-CREATED (record_artifact
        # returns its real id) and that id is passed into build_spec, so the
        # builder's tool_calls key to THIS row — never to a second artifact.
        # The artifact row (id, status="building") must exist before any tool call
        # is recorded: lineage_tool_calls.artifact_id is a NOT NULL FK.
        ledger = Ledger()
        try:
            conn = get_conn()
            ensure_schema(conn)
        except RuntimeError:
            # fail-open: an unreachable DB must not kill /ask. No artifact row
            # exists, so the builder gets artifact_id=None (it then skips tool
            # calls — never writes NULL into the NOT NULL FK) and we synthesize
            # a deterministic id so the client still gets a stable lineage URL.
            conn = None
            artifact_id = f"local-{len((req.request or '').encode('utf-8')):x}"
        else:
            artifact_id = record_artifact(
                conn, artifact_type="builder_request",
                artifact_key=(req.request or "")[:40], user_id=None,
                dataset_id=1, request_text=req.request, spec_json={},
                model="fartkraft", status="building")
            if artifact_id is None:
                # the artifact INSERT itself failed open to None (I1) — keep the
                # build going, but the lineage page can only be the degraded one.
                artifact_id = f"local-{len((req.request or '').encode('utf-8')):x}"
        try:
            spec = await build_spec(
                req.request, frame, _complete_fn, ledger, conn,
                max_turns=6, artifact_id=artifact_id)
        except Exception as exc:
            return {"error": str(exc), "artifact_id": artifact_id,
                    "dashboard_url": None, "lineage_url": None}
        if conn is not None and isinstance(artifact_id, int):
            update_artifact(conn, artifact_id,
                            spec_json=spec, status="ready")
        return {"artifact_id": artifact_id,
                "dashboard_url": "/at-a-glance.html",
                "lineage_url": f"/lineage/{artifact_id}"}

    @app.get("/lineage/{artifact_id}")
    def lineage(artifact_id: str):
        # conn=None: the viewer degrades to an honest "no live lineage" page
        # (data dict + no conn -> no artifact/dataset/ops/tool_calls). A live
        # Postgres wiring is Task 9/10; the page must never 500 on a down DB.
        return HTMLResponse(render_lineage_page(artifact_id, None))

    return app


async def _complete_fn(messages):
    """Deterministic completion for the POC demo (Task 9 wires the real LLM).

    Returns a canned spec immediately, so /ask works end-to-end without a live
    model. Kept async because build_spec awaits it (inspect.iscoroutinefunction).
    """
    return ('{"title": "FOI request summary", '
            '"description": "Deterministic POC completion — Task 9 wires the '
            'live model.", "panels": []}')
