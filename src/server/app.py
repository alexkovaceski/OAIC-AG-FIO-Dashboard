"""app — the Bluebird FOI Insights FastAPI service (no auth, hosted demo).

Routes:
  GET  /health                    {"status":"ok","model":"fartkraft sovereign stack"}
  GET  /                          at-a-glance page
  GET  /{page}.html               the 12 static pages (404 on unknown)
  GET  /assets/{file}             static assets (site.css, ...)
  POST /ask                       {request} -> {artifact_id, dashboard_url, lineage_url}
  GET  /lineage/{artifact_id}     lineage explainability page
  GET  /dashboards/{artifact_id}  the built dashboard page (rendered from spec_json + transcript)

Boot gate: create_app() builds the frame from normalise_all() and runs
frame.golden_check() — the data-integrity gate. A mismatch aborts loudly
(SystemExit) so the app never serves wrong data. The frame and the rendered
pages are built once and cached at module scope: re-normalising 7 xlsx files
per request would make every page load spend ~1.5s on IO the data cannot change
within a process. The boot also seeds the durable Postgres facts once
(storage.facts.ingest_facts, idempotent on canonical_hash) so foi_datasets holds
the snapshot that /ask's artifact rows reference by FK.

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

import asyncio  # noqa: E402
import html  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import urllib.parse  # noqa: E402

import psycopg2  # noqa: E402

logging.basicConfig(level=logging.WARNING,
                    format="%(levelname)s %(name)s %(message)s")
_LOGGER = logging.getLogger("foi-insights.server")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

import api  # noqa: E402
from config import STATIC_DIR  # noqa: E402
from ingest.normalise import normalise_all  # noqa: E402
from storage.frame import Frame  # noqa: E402
from storage.db import get_conn, ensure_schema  # noqa: E402
from storage.facts import ingest_facts  # noqa: E402
from storage.lineage import Ledger, record_artifact, record_op, update_artifact  # noqa: E402
from site.pages import render_all_pages  # noqa: E402
from site.lineage_viewer import render_lineage_page  # noqa: E402
from site.templates import chrome  # noqa: E402
from agentic.builder import build_spec  # noqa: E402
from agentic.guardrails import check_request, ScopeRefusal  # noqa: E402
from agentic.render import _stat_key, render_dashboard_page  # noqa: E402
from stats.catalog import foi_stats  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from storage import auth  # noqa: E402
from agentic.chat import chat as agentic_chat  # noqa: E402
from agentic.report import build_report  # noqa: E402
from site.pages import chat_page, reports_page  # noqa: E402
from risk.load import load_risk_artifacts, risk_page_html  # noqa: E402

# The golden boot check runs once at import; the frame and pages are immutable
# within a process, so they are cached at module scope rather than re-derived
# per request (normalise_all re-reads 7 xlsx files and render_all_pages
# recomputes every figure from the frame — both are pure frame/disk -> HTML).
_FRAME = None
_PAGES = None
# I2/C1: the foi_datasets id captured by the boot facts seed. record_artifact's
# NOT NULL FK references this row, so it is resolved here (never a hardcoded 1).
_DATASET_ID = None
# A module-scope ledger reused by every /ask: Ledger() opens a file handle, so
# a per-request ledger would leak one FD per request (reviewer I4).
_LEDGER = None
SESSION_SECRET = os.environ.get("FOI_SESSION_SECRET", "dev-insecure-secret")


def _session_secret_insecure() -> bool:
    """True when SESSION_SECRET is the public 'dev-insecure-secret' default.

    The default is a public constant in this repo, so a prod deploy that lacks
    FOI_SESSION_SECRET would mint sessions anyone could forge. Checked at boot
    (loud critical), per-login (refuse to mint) and per-session-validation
    (refuse to validate a cookie signed with the default), so the default never
    mints NOR accepts a valid cookie. Reads the module global at request time,
    so tests (and an operator reload) can swap the secret and the guard follows.
    """
    return SESSION_SECRET == "dev-insecure-secret"


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
    Once the frame passes, the durable Postgres facts are seeded (I2/C1).
    """
    global _FRAME, _PAGES
    if _FRAME is None:
        frame = Frame(normalise_all())
        frame.golden_check()
        _FRAME = frame
        _seed_facts(frame)  # I2/C1: seed the durable facts once at boot
    if _PAGES is None:
        _PAGES = render_all_pages(_FRAME)
    return _FRAME, _PAGES


def _seed_facts(frame) -> None:
    """Seed the durable Postgres facts (foi_datasets + foi_facts) once at boot.

    I2/C1: ingest_facts materialises the durable data spine and captures the
    real dataset_id that record_artifact's NOT NULL FK references — no more
    hardcoded 1, and no ForeignKeyViolation 500 against a live-but-unseeded
    Postgres. Idempotent on canonical_hash, so a re-boot over the same facts is
    a no-op.

    The seed is best-effort and FAIL-OPEN AT BOOT: the durable facts/lineage
    store is optional (Task 4) — an unreachable DB is skipped, and even a
    schema/programming error here must never refuse boot (it is logged loudly so
    an operator sees it). The fail-loud discipline is preserved where a live DB
    is expected: scripts/ingest.py exits 1 on a psycopg2.Error, and the /ask
    lazy seed (_dataset_id_for) re-raises a non-Operational psycopg2.Error.
    """
    global _DATASET_ID
    try:
        conn = get_conn()
    except RuntimeError:
        # fail-open: no live Postgres — the durable spine is simply absent; the
        # app still boots and /ask degrades to the synthetic-id path.
        _LOGGER.info("_seed_facts: Postgres unreachable; durable facts spine "
                     "skipped (fail-open)")
        return
    except Exception:
        _LOGGER.exception("_seed_facts: unexpected connect error; durable facts "
                          "spine skipped (fail-open)")
        return
    try:
        ensure_schema(conn)
        _DATASET_ID = ingest_facts(frame.facts, conn=conn)
    except Exception:
        _LOGGER.exception("_seed_facts: facts seed failed; durable spine "
                          "skipped (best-effort)")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _dataset_id_for(conn) -> int | None:
    """The seeded foi_datasets id for a live conn, seeding on demand.

    The boot seed normally captures it; this re-seeds when the DB was
    unreachable at boot but is reachable now. None on a transient DB error
    (fail-open, ingest_facts owns that split); a schema/programming error raises
    so it is not silently hidden.
    """
    global _DATASET_ID
    if _DATASET_ID is None:
        _DATASET_ID = ingest_facts(_FRAME.facts, conn=conn)
    return _DATASET_ID


def _record_figure_ops(conn, frame, artifact_id, dataset_id, spec) -> None:
    """I3: record a lineage_ops row for every figure/stat the spec resolves.

    kind='figure', op=the catalog key, params={}, and the platform's computed
    result_value + rows_hash (from foi_stats — never a model number), so the
    lineage viewer's "Computed figures" is populated and replay_verify can
    recompute-and-compare. Best-effort: record_op owns the fail-open split, so a
    transient DB error is swallowed; a schema/programming error raises.
    """
    if conn is None or artifact_id is None:
        return
    for panel in spec.get("panels", []):
        key = _stat_key(panel)
        if key is None:
            continue  # presentation-only (chart type) — nothing to replay
        stat = foi_stats(frame, key)
        record_op(conn, artifact_id=artifact_id, dataset_id=dataset_id,
                  kind="figure", op=key, params={},
                  row_count=stat.get("source_rows"),
                  rows_hash=stat.get("rows_hash"),
                  result_value=stat.get("value"))


def _load_dashboard(artifact_id, conn):
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


def _degraded_dashboard_page(artifact_id) -> str:
    """Honest fail-open page for a dashboard that cannot be rendered (unreachable
    DB, or no durable spec for the artifact). Never a 500, never a fabricated
    dashboard."""
    body = (
        f"<h1>Dashboard unavailable</h1>"
        f"<p>No durable dashboard could be found for artifact "
        f"{html.escape(str(artifact_id))} — the Postgres lineage store is "
        f"unreachable or the artifact has no recorded spec.</p>"
        f'<p><a href="/">← back to at-a-glance</a></p>')
    return chrome(f"Dashboard — {artifact_id}", body)


def _session_user(request: Request) -> dict | None:
    """The signed-cookie session payload, or None (tampered/expired/missing,
    or the session secret is the insecure default).

    Normalised to the same {"id", "username", "role"} shape _authenticate
    returns, so the gated routes can treat both identically (the signed
    payload's key is user_id — encode_session stores it under that name).
    Role defaults to "viewer" for legacy sessions minted before the role
    column existed (payload lacks the key)."""
    if _session_secret_insecure():
        # R2: with the public default secret in place, even a cookie signed with
        # that same default must NOT validate — an attacker who read this repo
        # can forge encode_session(..., "dev-insecure-secret"). Gate VALIDATION
        # too (the minting path already refuses), so every gated route treats
        # the request as anonymous.
        return None
    payload = auth.decode_session(request.cookies.get("foi_session"), SESSION_SECRET)
    if payload is None:
        return None
    return {"id": payload["user_id"], "username": payload["username"],
            "role": payload.get("role", "viewer")}


def _authenticate(username: str, password: str) -> dict | None:
    """Verify credentials against horizon.foi_chat_users. None on any failure
    (wrong password, unknown/inactive user, or unreachable DB — fail-open, the
    login just refuses)."""
    try:
        conn = get_conn()
    except Exception:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, pw_hash, is_active, role "
                        "FROM horizon.foi_chat_users WHERE username = %s",
                        (username,))
            row = cur.fetchone()
        if row is None or not row[3]:
            return None
        if not auth.verify_password(password, row[2]):
            return None
        return {"id": row[0], "username": row[1],
                "role": "internal" if row[4] == "internal" else "viewer"}
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _record_message(user_id, role: str, content: str) -> None:
    """Best-effort append to horizon.foi_chat_messages (the audit trail). Never
    breaks the response: any failure is logged and swallowed."""
    try:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO horizon.foi_chat_messages "
                    "(user_id, role, content) VALUES (%s,%s,%s)",
                    (user_id, role, content[:4000]))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        _LOGGER.warning("_record_message: message log write failed", exc_info=True)


def _login_page(error: str | None = None) -> str:
    err = f'<p class="form-error">{html.escape(error)}</p>' if error else ""
    body = f"""
    <h1>Log in</h1>
    <p class="intro">Sign in to use the Chat &amp; reports section.</p>
    {err}
    <form method="post" action="/login" class="login-form">
      <label for="username">Username</label>
      <input id="username" name="username" type="text" autocomplete="username" required>
      <label for="password">Password</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required>
      <button type="submit">Log in</button>
    </form>
    <p class="hint">Access is by invitation — contact bluebirdadvisory.com.au to
    request an account.</p>
    """
    return chrome("Log in", body)


def risk_not_authorized() -> str:
    return ("<h1>Not authorised</h1>"
            "<p>Your account does not have access to internal risk views.</p>")


class AskRequest(BaseModel):
    request: str


class ChatBody(BaseModel):
    question: str
    history: list[dict] | None = None


class ReportBody(BaseModel):
    request: str


def create_app():
    """Build the FastAPI app. The golden gate runs here; a data-integrity
    mismatch raises SystemExit, so the app cannot start on wrong data."""
    frame, pages = _boot()

    if _session_secret_insecure():
        _LOGGER.critical("FOI_SESSION_SECRET is missing or set to the insecure "
                         "default 'dev-insecure-secret'. Sessions are forgeable; "
                         "set FOI_SESSION_SECRET before deploying.")

    app = FastAPI(title="Bluebird FOI Insights")
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.state.frame = frame
    app.state.pages = pages

    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")

    # Starlette 1.6.0's StaticFiles takes no headers= kwarg, so the revalidation
    # cache header is applied here: every /assets/* response gets
    # Cache-Control: public, no-cache (never overwriting one that exists).
    @app.middleware("http")
    async def _asset_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/assets/"):
            response.headers.setdefault("Cache-Control", "public, no-cache")
        return response

    @app.get("/health")
    def health():
        return {"status": "ok", "model": "fartkraft sovereign stack"}

    # ---- read-only data API (throttled) ------------------------------------
    # Exposes the SAME platform-computed figures + canonical facts the
    # visualisations use. Every /api/* call is rate-limited per client IP so
    # the public no-auth demo doesn't get smashed.

    def _throttled(request):
        allowed, remaining, retry_after = api.check(api._client_ip(request))
        if not allowed:
            return JSONResponse(
                {"error": "rate limit exceeded",
                 "retry_after_seconds": round(retry_after, 1)},
                status_code=429,
                headers={"Retry-After": str(int(retry_after))})
        return None

    @app.get("/api/")
    def api_root(request: Request):
        b = _throttled(request)
        if b:
            return b
        return api.dataset_info(frame)

    @app.get("/api/figures")
    def api_figures(request: Request):
        b = _throttled(request)
        if b:
            return b
        return api.figures(frame)

    @app.get("/api/facts")
    def api_facts(request: Request, fy: str | None = None,
                  measure: str | None = None, bucket: str | None = None,
                  agency: str | None = None, quarter: int | None = None,
                  limit: int = 1000, offset: int = 0):
        b = _throttled(request)
        if b:
            return b
        return api.facts(frame, fy=fy, measure=measure, bucket=bucket,
                         agency=agency, quarter=quarter, limit=limit,
                         offset=offset)

    @app.get("/api/measures")
    def api_measures(request: Request):
        b = _throttled(request)
        if b:
            return b
        return api.measures(frame)

    @app.get("/")
    def index():
        return HTMLResponse(pages["at-a-glance"])

    @app.post("/login")
    async def login(request: Request):
        body = await request.body()
        data = dict(urllib.parse.parse_qsl(body.decode("utf-8", errors="replace"),
                                           keep_blank_values=True))
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        if _session_secret_insecure():
            # the default secret is public (forgeable) — refuse to mint a session
            return HTMLResponse(_login_page(
                "Sign-in is unavailable: the session secret is not configured."),
                status_code=503)
        user = _authenticate(username, password)
        if user is None:
            return HTMLResponse(_login_page("Invalid username or password"),
                                status_code=401)
        resp = RedirectResponse("/chat.html", status_code=303)
        resp.set_cookie("foi_session",
                        auth.encode_session(user["id"], user["username"],
                                            user.get("role", "viewer"),
                                            SESSION_SECRET),
                        httponly=True, samesite="lax", max_age=43_200)
        return resp

    @app.get("/logout")
    def logout():
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie("foi_session")
        return resp

    @app.get("/login")
    def login_page():
        return HTMLResponse(_login_page())

    @app.get("/chat.html")
    def chat_gated(request: Request):
        user = _session_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        return HTMLResponse(chat_page(user))

    @app.get("/reports.html")
    def reports_gated(request: Request):
        user = _session_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        return HTMLResponse(reports_page(user))

    @app.get("/risk.html")
    def risk_gated(request: Request):
        user = _session_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        if user.get("role") != "internal":
            return HTMLResponse(risk_not_authorized(), status_code=403)
        return HTMLResponse(risk_page_html(user, _FRAME,
                                           artifacts=load_risk_artifacts()))

    @app.post("/chat")
    async def chat_route(request: Request, req: ChatBody):
        user = _session_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        out = await agentic_chat(req.question, req.history)
        _record_message(user["id"], "user", req.question)
        _record_message(user["id"], "assistant", out.get("answer", ""))
        return out

    @app.post("/report")
    def report_route(request: Request, req: ReportBody):
        user = _session_user(request)
        if user is None:
            return RedirectResponse("/login", status_code=303)
        out = build_report(req.request, frame)
        _record_message(user["id"], "report", req.request)
        return out

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
        # exists (or None otherwise) — never a synthetic string. `conn` is the
        # conn handed to build_spec (None on any fail-open); `raw` is the actual
        # psycopg2 conn, always closed in the finally below.
        build_id = None
        dataset_id = None
        response_id = f"local-{len((req.request or '').encode('utf-8')):x}"
        conn = None
        raw = None
        try:
            try:
                raw = get_conn()
                ensure_schema(raw)
                # C1: the boot seed (or this lazy resolve) supplies the real
                # foi_datasets id, so record_artifact's NOT NULL FK resolves —
                # no more ForeignKeyViolation 500 on a live-but-unseeded DB.
                dataset_id = _dataset_id_for(raw)
            except (RuntimeError, psycopg2.OperationalError):
                # I2: fail-open — an unreachable DB (connect or schema) must not
                # kill /ask. No artifact row exists, so the builder gets
                # conn=None + build_id=None (its None-path skips tool-call
                # writes, never NULLing the NOT NULL FK) and the client gets a
                # deterministic synthetic id so the lineage URL stays stable.
                raw = None
            if raw is not None:
                # Task 6 carry-forward: the artifact row is PRE-CREATED
                # (record_artifact returns its real id) and that id is passed
                # into build_spec, so the builder's tool_calls key to THIS row —
                # never to a second artifact. The row (id, status="building")
                # must exist before any tool call is recorded:
                # lineage_tool_calls.artifact_id is a NOT NULL FK.
                if dataset_id is not None:
                    build_id = record_artifact(
                        raw, artifact_type="builder_request",
                        artifact_key=(req.request or "")[:40], user_id=None,
                        dataset_id=dataset_id, request_text=req.request,
                        spec_json={}, model="fartkraft", status="building")
                if build_id is not None:
                    conn = raw  # a real artifact row exists — the builder may write tool calls
                    response_id = build_id
                else:
                    # I1: the artifact INSERT failed open to None (or no dataset
                    # is seeded on this conn). No real row exists — give the
                    # builder the None-path. Never hand build_spec a synthetic
                    # string as a real artifact_id with a live conn: a recovered
                    # DB would make the builder's record_tool_call hit "invalid
                    # input syntax for type integer" (a non-Operational
                    # psycopg2.Error) and re-raise, aborting the build.
                    conn = None
            try:
                spec = await build_spec(
                    req.request, frame, _complete_fn, ledger, conn,
                    max_turns=6, artifact_id=build_id)
            except Exception as exc:
                # a genuine build error (not a refusal — those were screened
                # above): flip any real row to status="error" so it is not stuck
                # "building"
                if conn is not None and isinstance(build_id, int):
                    try:
                        update_artifact(conn, build_id, status="error")
                    except Exception:
                        pass  # best-effort: the error response always wins
                return {"error": str(exc), "artifact_id": response_id,
                        "dashboard_url": None, "lineage_url": None}
            if conn is not None and isinstance(build_id, int):
                update_artifact(conn, build_id, spec_json=spec, status="ready")
                # I3: per-figure lineage — record each computed figure as a
                # lineage_ops row (kind='figure', op=key, result + rows_hash) so
                # the viewer's "Computed figures" is populated and replay can
                # run. Best-effort inside record_op.
                _record_figure_ops(conn, frame, build_id, dataset_id, spec)
            # I4: point at the artifact's own dashboard, rendered from its
            # durable spec_json + transcript on GET /dashboards/{id} — not the
            # static at-a-glance page.
            return {"artifact_id": response_id,
                    "dashboard_url": f"/dashboards/{response_id}",
                    "lineage_url": f"/lineage/{response_id}"}
        finally:
            if raw is not None:
                try:
                    raw.close()
                except Exception:
                    pass

    @app.get("/lineage/{artifact_id}")
    def lineage(artifact_id: str):
        # Live Postgres wiring (Task 9/10): read the artifact/snapshot/ops/tool
        # calls from the horizon lineage tables so the explainability page shows
        # the REAL transcript recorded by build_spec. Best-effort — an unreachable
        # DB degrades to the honest "no live lineage" page (render_lineage_page
        # handles conn=None), so the page never 500s on a down DB.
        conn = None
        try:
            conn = get_conn()
        except (RuntimeError, psycopg2.OperationalError):
            conn = None
        return HTMLResponse(render_lineage_page(artifact_id, conn))

    @app.get("/dashboards/{artifact_id}")
    def dashboard(artifact_id: str):
        # I4: render the artifact's OWN dashboard from its durable spec_json and
        # recorded tool-call transcript — not the static at-a-glance page. The
        # conn is closed in the finally; a live-but-unreachable DB degrades to
        # the honest "unavailable" page (never a 500).
        conn = None
        try:
            try:
                conn = get_conn()
                spec, transcript = _load_dashboard(artifact_id, conn)
            except (RuntimeError, psycopg2.OperationalError):
                spec, transcript = None, []
            if spec is None:
                return HTMLResponse(_degraded_dashboard_page(artifact_id))
            return HTMLResponse(
                render_dashboard_page(spec, frame, artifact_id, transcript))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    return app


# The deterministic canned spec is the LOAD-BEARING fallback: on ANY failure —
# endpoint down, timeout, non-2xx, malformed body, or null/empty content — the
# demo must still return a valid spec, so /ask never dies.
_FALLBACK_SPEC = ('{"title": "FOI request summary", '
                  '"description": "Bluebird FOI Insights demo — deterministic completion '
                  '(live model unavailable).", "panels": []}')


async def _complete_fn(messages):
    """Call the axoquant-llm author endpoint with the messages.

    The identity stovepipe lives in build_spec (Task 6); this function only
    forwards the assembled messages and returns the model's raw text. The call
    goes through the axoquant-llm library (resolved by ROLE, not by URL — the
    author role maps to the front-door chat endpoint). The library is sync
    (stdlib urllib), so it runs in a worker thread. On ANY failure — including
    a model that answers with content=null (a tool-call payload or empty
    content, which raises no exception) — it returns _FALLBACK_SPEC so
    build_spec never receives a None it would crash on.
    """
    try:
        from axoquant_llm import chat

        def _call():
            resp = chat("author", messages, app="foi-insights/ask",
                        temperature=0.2, no_thinking=True)
            return resp.text

        text = await asyncio.to_thread(_call)
        if not text or not isinstance(text, str):
            # content=null (tool-call turn), "" or a malformed non-string is not
            # a usable spec — same failure class as an unreachable endpoint.
            # Guarded explicitly so it cannot slip past the fallback and crash
            # build_spec on None (or a non-string re.sub).
            _LOGGER.warning("_complete_fn: model returned empty/non-string "
                            "content (%r); using deterministic fallback", text)
            return _FALLBACK_SPEC
        return text
    except Exception:
        # deterministic fallback — the demo always returns a valid spec
        _LOGGER.warning("_complete_fn: LLM call failed; using deterministic "
                        "fallback", exc_info=True)
        return _FALLBACK_SPEC
