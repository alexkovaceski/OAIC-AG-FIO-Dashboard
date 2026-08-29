"""Regression tests for the Task 8 FastAPI server (server.app).

The whole suite must run WITHOUT a live Postgres: /ask fails open to a synthetic
artifact id when the DB is unreachable (lineage must never fail a build), and
/lineage/{id} renders a degraded page with conn=None. The golden boot check
runs on create_app() — any test failing here means the data/normaliser
integrity gate is wrong.

Also covers the final-review wiring: boot seeds the durable facts (I2/C1),
/ask against a seeded DB returns a real artifact + its own dashboard URL (C1,
I4) and records per-figure lineage_ops (I3), /dashboards/{id} serves the built
spec, and the per-request psycopg2 conn is closed.
"""
import asyncio
import json
import sys
import types

import httpx
import pytest

sys.path.insert(0, "src")
from fastapi.testclient import TestClient
from server.app import create_app
import server.app as app_mod


async def _fake_complete(messages):
    # hermetic replacement for the real _complete_fn: no network, immediate spec
    # (non-empty panels, so the empty-spec guard does not treat it as a failure)
    return ('{"title": "FOI request summary", '
            '"description": "test", '
            '"panels": [{"figure": "kpi", "stat": "requests_received_q1"}]}')


def test_health():
    c = TestClient(create_app())
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["model"] == "axoquant sovereign stack"


def test_static_pages_render():
    c = TestClient(create_app())
    for page in ["at-a-glance", "requests-received", "data-notes"]:
        r = c.get(f"/{page}.html")
        assert r.status_code == 200
        assert "axoquant" in r.text.lower()


def test_ask_returns_artifact_and_urls(monkeypatch):
    # hermetic end-to-end /ask: the fake complete_fn returns the canned spec, so
    # the route works without a live model or a live DB (fail-open to a synthetic id)
    monkeypatch.setattr(app_mod, "_complete_fn", _fake_complete)
    c = TestClient(create_app())
    r = c.post("/ask", json={"request": "show me requests received by agency"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("artifact_id")
    # I4: the built dashboard is served on its own route, not the static
    # at-a-glance page.
    assert body["dashboard_url"] == f"/dashboards/{body['artifact_id']}"
    assert body["lineage_url"] == f"/lineage/{body['artifact_id']}"


def test_lineage_page_renders(monkeypatch):
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.get("/lineage/abc123")
    assert r.status_code == 200
    assert "axoquant" in r.text.lower()


def test_lineage_route_requires_session():
    c = TestClient(create_app())
    r = c.get("/lineage/42", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers.get("location", "")


def test_lineage_route_forbidden_for_foreign_owner(monkeypatch):
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    monkeypatch.setattr(app_mod, "get_conn", lambda: object())
    monkeypatch.setattr(app_mod, "may_access_artifact", lambda c, aid, uid: False)
    r = c.get("/lineage/42")
    assert r.status_code == 403
    assert "not yours" in r.text


def test_lineage_route_reads_live_db_when_available(monkeypatch):
    # Task 11: /lineage must attempt a live Postgres read so the REAL transcript
    # recorded by build_spec renders on demo day — a hardcoded conn=None would
    # always show the degraded "no live lineage" page even with the DB up.
    captured = {}
    sentinel_conn = object()
    monkeypatch.setattr(app_mod, "get_conn", lambda: sentinel_conn)
    monkeypatch.setattr(app_mod, "may_access_artifact", lambda c, aid, uid: True)
    monkeypatch.setattr(
        app_mod, "render_lineage_page",
        lambda artifact_id, conn: captured.update(artifact_id=artifact_id,
                                                  conn=conn)
        or "<!doctype html><p>ok</p>")
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.get("/lineage/42")
    assert r.status_code == 200
    assert captured["artifact_id"] == "42"
    assert captured["conn"] is sentinel_conn  # the live conn reached the viewer


def test_lineage_route_degrades_when_db_down(monkeypatch):
    # an unreachable DB (get_conn raises RuntimeError) must still render the
    # honest degraded page — never a 500. (The session still gates first.)
    def raise_conn():
        raise RuntimeError("no db")

    monkeypatch.setattr(app_mod, "get_conn", raise_conn)
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.get("/lineage/42")
    assert r.status_code == 200
    assert "axoquant" in r.text.lower()


def test_unknown_page_is_404():
    c = TestClient(create_app())
    r = c.get("/not-a-real-page.html")
    assert r.status_code == 404


def test_ask_record_artifact_fails_open_passes_none_not_string(monkeypatch):
    # Reviewer I1: record_artifact fails open to None even though the conn is
    # live. The route must NOT hand build_spec a synthetic string as a real
    # artifact_id (a recovered DB would make record_tool_call raise a
    # non-Operational "invalid input syntax for integer" error and abort the
    # build). It drops the conn and passes artifact_id=None instead.
    # _DATASET_ID is set to simulate a boot-seeded DB (C1: the FK id resolves).
    captured = {}

    async def fake_build_spec(text, frame, complete_fn, ledger, conn,
                              max_turns=6, artifact_id=None):
        captured["conn"] = conn
        captured["artifact_id"] = artifact_id
        return {"title": "FOI request summary", "panels": []}

    monkeypatch.setattr(app_mod, "_DATASET_ID", 1)  # boot already seeded the facts
    monkeypatch.setattr(app_mod, "get_conn", lambda: object())
    monkeypatch.setattr(app_mod, "ensure_schema", lambda conn: None)
    monkeypatch.setattr(app_mod, "record_artifact", lambda *a, **k: None)
    monkeypatch.setattr(app_mod, "build_spec", fake_build_spec)
    c = TestClient(create_app())
    r = c.post("/ask", json={"request": "show me requests received by agency"})
    assert r.status_code == 200
    body = r.json()
    assert body["artifact_id"].startswith("local-")
    assert captured["artifact_id"] is None  # never a string id into the builder
    assert captured["conn"] is None         # conn dropped with it (None-path)


def test_ask_scope_refusal_rejected_before_artifact(monkeypatch):
    # Reviewer I3: a refused request is screened BEFORE any artifact row is
    # created, so no stuck status="building" row is left behind.
    calls = []
    monkeypatch.setattr(
        app_mod, "record_artifact", lambda *a, **k: calls.append(1) or 42)
    c = TestClient(create_app())
    r = c.post("/ask", json={"request": "crypto trading strategy"})
    assert r.status_code == 200
    body = r.json()
    assert body["error"]
    assert body["artifact_id"] is None
    assert calls == []  # no artifact row was created for a refusal


def test_boot_seeds_facts_once(monkeypatch):
    # I2/C1: the boot path calls ingest_facts so foi_datasets/foi_facts
    # materialise, and captures the real dataset_id record_artifact's FK needs.
    # Reset the module cache and patch the DB to a live conn.
    saved = (app_mod._FRAME, app_mod._PAGES, app_mod._DATASET_ID, app_mod._LEDGER)
    app_mod._FRAME, app_mod._PAGES, app_mod._DATASET_ID, app_mod._LEDGER = None, None, None, None
    captured = {}
    conn = types.SimpleNamespace(close=lambda: None)
    try:
        def fake_ingest_facts(facts, *, conn=None):
            captured["facts"] = facts
            captured["conn"] = conn
            return 7

        monkeypatch.setattr(app_mod, "get_conn", lambda: conn)
        monkeypatch.setattr(app_mod, "ensure_schema", lambda c: None)
        monkeypatch.setattr(app_mod, "ingest_facts", fake_ingest_facts)
        app_mod.create_app()
        assert captured.get("conn") is conn
        assert captured.get("facts") is app_mod._FRAME.facts  # the canonical facts
        assert app_mod._DATASET_ID == 7                        # boot captured the id
    finally:
        app_mod._FRAME, app_mod._PAGES, app_mod._DATASET_ID, app_mod._LEDGER = saved


def test_ask_with_seeded_db_does_not_500_and_uses_real_dataset_id(monkeypatch):
    # C1: /ask against a live, SEEDED Postgres must not 500 on record_artifact's
    # ForeignKeyViolation. The seeded foi_datasets id threads into record_artifact
    # (never a hardcoded 1). Also asserts the built dashboard URL (I4), the
    # per-figure lineage_ops row (I3), and that the conn is closed.
    closed = []
    conn = types.SimpleNamespace(close=lambda: closed.append(1))
    recorded = {}
    ops = []

    def fake_record_artifact(*a, **k):
        recorded["dataset_id"] = k["dataset_id"]
        return 42

    def fake_record_op(*a, **k):
        ops.append(k)
        return None

    async def fake_build_spec(text, frame, complete_fn, ledger, conn,
                              max_turns=6, artifact_id=None):
        return {"title": "Seeded", "panels": [
            {"figure": "kpi", "stat": "requests_received_q1"}]}

    monkeypatch.setattr(app_mod, "_DATASET_ID", 7)  # the boot-seeded foi_datasets id
    monkeypatch.setattr(app_mod, "get_conn", lambda: conn)
    monkeypatch.setattr(app_mod, "ensure_schema", lambda c: None)
    monkeypatch.setattr(app_mod, "record_artifact", fake_record_artifact)
    monkeypatch.setattr(app_mod, "update_artifact", lambda *a, **k: None)
    monkeypatch.setattr(app_mod, "record_op", fake_record_op)
    monkeypatch.setattr(app_mod, "build_spec", fake_build_spec)
    c = TestClient(create_app())
    r = c.post("/ask", json={"request": "top agencies by requests received Q1 2025-26"})
    assert r.status_code == 200
    body = r.json()
    assert body["artifact_id"] == 42
    assert body["dashboard_url"] == "/dashboards/42"   # the artifact's own dashboard
    assert body["lineage_url"] == "/lineage/42"
    assert recorded["dataset_id"] == 7                 # the seeded id, not a hardcoded 1
    assert closed == [1]                               # the per-request conn was closed
    # I3: record_op ran for the panel's stat key with the platform value
    assert len(ops) == 1
    assert ops[0]["kind"] == "figure"
    assert ops[0]["op"] == "requests_received_q1"
    assert ops[0]["artifact_id"] == 42
    assert ops[0]["dataset_id"] == 7
    assert ops[0]["result_value"] == 12359             # golden Q1 requests received
    assert ops[0]["rows_hash"]                         # replay-comparable hash


def test_record_figure_ops_writes_lineage_ops_per_stat_panel(monkeypatch):
    # I3: every stat-keyed panel records a lineage_ops row (kind='figure'); a
    # presentation-only panel (chart type, no catalog key) is skipped.
    captured = []
    monkeypatch.setattr(app_mod, "record_op",
                        lambda *a, **k: captured.append(k) or None)
    spec = {"panels": [
        {"figure": "kpi", "stat": "requests_received_q1"},
        {"figure": "bar"},                # presentation-only — no lineage_ops row
        {"figure": "received_top20"},
    ]}
    app_mod._record_figure_ops(object(), app_mod._FRAME, 42, 7, spec)
    assert [k["op"] for k in captured] == ["requests_received_q1", "received_top20"]
    for k in captured:
        assert k["kind"] == "figure"
        assert k["artifact_id"] == 42
        assert k["dataset_id"] == 7
        assert k["rows_hash"]             # replay_verify can recompute-and-compare


def test_load_dashboard_reconstructs_spec_and_transcript():
    # I4: _load_dashboard parses the durable spec_json and rebuilds the tool-call
    # transcript (seq/tool/result) for the citation resolver.
    spec = {"title": "T", "panels": []}
    calls = [(1, "query_dataset", json.dumps({"top": [{"agency": "A", "value": 5}]}))]

    class _Cursor:
        def __init__(self):
            self._n = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self._n += 1

        def fetchone(self):
            return (json.dumps(spec),)

        def fetchall(self):
            return calls

    class _Conn:
        def cursor(self):
            return _Cursor()

    s, t = app_mod._load_dashboard(42, _Conn())
    assert s == spec
    assert t == [{"seq": 1, "tool": "query_dataset",
                  "result": {"top": [{"agency": "A", "value": 5}]}}]


def test_dashboard_route_serves_built_spec(monkeypatch):
    # I4: a built dashboard is served at /dashboards/{id}, rendered from the
    # artifact's durable spec_json + recorded transcript (not the static
    # at-a-glance page). The per-request conn is closed.
    spec = {"title": "Seeded dashboard", "panels": [
        {"figure": "bar", "stat": "requests_received_q1"}]}
    calls = [(1, "query_dataset", json.dumps({"top": [{"agency": "Home Affairs"}]}))]

    class _Cursor:
        def __init__(self):
            self._n = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self._n += 1

        def fetchone(self):
            return (json.dumps(spec),)

        def fetchall(self):
            return calls

    class _Conn:
        def __init__(self):
            self._cursor = _Cursor()
            self.closed = False

        def cursor(self):
            return self._cursor

        def close(self):
            self.closed = True

    conn = _Conn()
    monkeypatch.setattr(app_mod, "get_conn", lambda: conn)
    monkeypatch.setattr(app_mod, "may_access_artifact", lambda c, aid, uid: True)
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.get("/dashboards/42")
    assert r.status_code == 200
    assert "Seeded dashboard" in r.text
    assert "12,359" in r.text            # the golden Q1 requests received, platform-computed
    assert conn.closed                   # the per-request conn was closed


def test_dashboard_route_requires_session():
    # a report URL is private: no session, no page
    c = TestClient(create_app())
    r = c.get("/dashboards/42", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers.get("location", "")


def test_dashboard_route_forbidden_for_foreign_owner(monkeypatch):
    # a signed-in user cannot open another user's report, even with the URL
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    monkeypatch.setattr(app_mod, "get_conn", lambda: object())
    monkeypatch.setattr(app_mod, "may_access_artifact", lambda c, aid, uid: False)
    r = c.get("/dashboards/42")
    assert r.status_code == 403
    assert "not yours" in r.text


def test_dashboard_route_degrades_when_db_down(monkeypatch):
    # I4 fail-open: an unreachable DB renders the honest "unavailable" page,
    # never a 500. (The session still gates first.)
    def raise_conn():
        raise RuntimeError("no db")

    monkeypatch.setattr(app_mod, "get_conn", raise_conn)
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.get("/dashboards/42")
    assert r.status_code == 200
    assert "Dashboard unavailable" in r.text


def test_dashboard_route_degrades_on_synthetic_nonint_id(monkeypatch):
    # N1: a non-numeric id (the local-<hex> synthetic id when /ask failed open)
    # against a LIVE db must degrade, never 500 (the id = %s compare would raise
    # psycopg2.DataError, not OperationalError).
    monkeypatch.setattr(app_mod, "get_conn", lambda: object())  # a live conn
    monkeypatch.setattr(app_mod, "may_access_artifact", lambda c, aid, uid: True)
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.get("/dashboards/local-2c")
    assert r.status_code == 200
    assert "Dashboard unavailable" in r.text


def test_dashboard_route_degrades_when_spec_cannot_render(monkeypatch):
    # A stored spec with an unresolvable citation pointer must degrade to the
    # honest page instead of SystemExit-ing the whole service (the fail-loud
    # renderer used to take the site down on one bad model output).
    spec = {"title": "Broken", "panels": [
        {"figure": "kpi", "stat": "{c:0.0.0.total}"}]}

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return (json.dumps(spec),)

        def fetchall(self):
            return []

    class _Conn:
        def cursor(self):
            return _Cursor()

        def close(self):
            pass

    monkeypatch.setattr(app_mod, "get_conn", lambda: _Conn())
    monkeypatch.setattr(app_mod, "may_access_artifact", lambda c, aid, uid: True)
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.get("/dashboards/42")
    assert r.status_code == 200
    assert "This report cannot be rendered" in r.text


def test_spec_renders_false_for_unresolvable_citation():
    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return (json.dumps({"panels": []}),)

        def fetchall(self):
            return []

    class _Conn:
        def cursor(self):
            return _Cursor()

    bad = {"panels": [{"figure": "kpi", "stat": "{c:0.0.0.total}"}]}
    assert app_mod._spec_renders(bad, _Conn(), 42, app_mod._FRAME) is False
    good = {"panels": [{"figure": "kpi", "stat": "requests_received_q1"}]}
    assert app_mod._spec_renders(good, _Conn(), 42, app_mod._FRAME) is True


def test_build_flips_unrenderable_spec_to_error(monkeypatch):
    # A built spec that cannot render is flipped to status="error" and the
    # caller gets an error (so the ask pipeline falls back), never a ready
    # dashboard link that dies at read time.
    async def fake_build_spec(*a, **k):
        return {"title": "Broken", "panels": [
            {"figure": "kpi", "stat": "{c:0.0.0.total}"}]}

    statuses = []
    conn = types.SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(app_mod, "_DATASET_ID", 7)
    monkeypatch.setattr(app_mod, "get_conn", lambda: conn)
    monkeypatch.setattr(app_mod, "ensure_schema", lambda c: None)
    monkeypatch.setattr(app_mod, "record_artifact", lambda *a, **k: 42)
    monkeypatch.setattr(app_mod, "build_spec", fake_build_spec)
    monkeypatch.setattr(app_mod, "_spec_renders", lambda spec, c, aid, f: False)
    monkeypatch.setattr(app_mod, "update_artifact",
                        lambda c, aid, **k: statuses.append(k.get("status")))
    monkeypatch.setattr(app_mod, "_record_figure_ops", lambda *a, **k: None)
    out = asyncio.run(app_mod._build_dashboard(app_mod._FRAME, "build x"))
    assert out["error"] is not None
    assert out["dashboard_url"] is None
    assert statuses[-1] == "error"


def test_ask_empty_spec_returns_error_not_broken_link(monkeypatch):
    # A builder that returns no panels must not be presented as "built": the
    # route returns an error (so /report escalates and /ask reports the failure)
    # instead of a dashboard_url to a blank /dashboards/{id} page.
    async def empty_build_spec(text, frame, complete_fn, ledger, conn,
                               max_turns=6, artifact_id=None):
        return {"panels": []}

    monkeypatch.setattr(app_mod, "build_spec", empty_build_spec)
    c = TestClient(create_app())
    r = c.post("/ask", json={"request": "breakup of foi requests by compliance"})
    assert r.status_code == 200
    body = r.json()
    assert body["error"]
    assert body["dashboard_url"] is None


def test_dashboard_route_serves_empty_spec_as_empty_page(monkeypatch):
    # A ready-but-empty artifact (panels == []) must render the honest "no
    # content" page, not a blank "FOI dashboard" that reads as a broken link.
    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return (json.dumps({"panels": []}),)

        def fetchall(self):
            return []

    class _Conn:
        def __init__(self):
            self.closed = False

        def cursor(self):
            return _Cursor()

        def close(self):
            self.closed = True

    conn = _Conn()
    monkeypatch.setattr(app_mod, "get_conn", lambda: conn)
    monkeypatch.setattr(app_mod, "may_access_artifact", lambda c, aid, uid: True)
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.get("/dashboards/42")
    assert r.status_code == 200
    assert "This report has no content" in r.text
    assert conn.closed


def test_delete_report_route(monkeypatch):
    # Deleting a report is gated on a session, routes through delete_artifact on
    # the live conn, and is scoped to the caller's user id.
    from storage import auth
    import server.app as app_mod
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    token = auth.encode_session(1, "alice", "viewer", app_mod.SESSION_SECRET)

    deleted = {}
    sentinel_conn = object()

    def fake_delete_artifact(conn, artifact_id, user_id=None):
        deleted["conn"] = conn
        deleted["artifact_id"] = artifact_id
        deleted["user_id"] = user_id
        return True

    monkeypatch.setattr(app_mod, "get_conn", lambda: sentinel_conn)
    monkeypatch.setattr(app_mod, "delete_artifact", fake_delete_artifact)
    c = TestClient(create_app())
    c.cookies.set("foi_session", token)
    r = c.post("/dashboards/42/delete")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}
    assert deleted["artifact_id"] == 42
    assert deleted["user_id"] == 1
    assert deleted["conn"] is sentinel_conn


def test_delete_report_route_requires_session():
    c = TestClient(create_app())
    r = c.post("/dashboards/42/delete", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers.get("location", "")


def test_complete_fn_falls_back_when_llm_unreachable(monkeypatch):
    # Task 9 load-bearing requirement: on ANY failure (endpoint down, timeout,
    # non-2xx, bad body) _complete_fn returns the deterministic canned spec so
    # the demo never dies. _complete_fn routes through axoquant_llm.chat — mock
    # it to raise (the endpoint-down case) and assert the fallback.
    import axoquant_llm
    monkeypatch.setattr(axoquant_llm, "chat", _raising_chat)
    out = asyncio.run(app_mod._complete_fn([{"role": "user", "content": "x"}]))
    spec = json.loads(out)
    assert spec["title"] == "FOI request summary"
    assert "panels" in spec


def _raising_chat(*a, **k):
    raise RuntimeError("endpoint unreachable")


@pytest.mark.parametrize("bad_content", [None, "", {"nested": "not-a-string"}])
def test_complete_fn_returns_fallback_on_bad_content(monkeypatch, bad_content):
    # IMPORTANT reviewer finding: a model answering with a tool-call payload or
    # empty content returns content=null (NO exception), so the raw access does
    # not trip the except path. That null must NOT escape _complete_fn —
    # build_spec would call _parse_tool_calls(None) and crash with AttributeError.
    import axoquant_llm

    def _null_chat(*a, **k):
        class _R:
            text = bad_content
        return _R()

    monkeypatch.setattr(axoquant_llm, "chat", _null_chat)
    out = asyncio.run(app_mod._complete_fn([{"role": "user", "content": "x"}]))
    spec = json.loads(out)
    assert spec["title"] == "FOI request summary"
    assert "panels" in spec


def test_complete_fn_passes_through_model_text(monkeypatch):
    # when the endpoint answers, _complete_fn returns the raw model text
    import axoquant_llm

    def _hello_chat(role, messages, app, **kw):
        class _R:
            text = "hello"
        return _R()

    monkeypatch.setattr(axoquant_llm, "chat", _hello_chat)
    msgs = [{"role": "user", "content": "build a dashboard"}]
    out = asyncio.run(app_mod._complete_fn(msgs))
    assert out == "hello"


def test_complete_fn_returns_fallback_on_truncated(monkeypatch):
    # finish_reason="length" means the model hit its token budget mid-spec: the
    # text is a cut-off (unparseable) JSON spec. axoquant_llm marks this with
    # Response.truncated; _complete_fn must treat it as a failure, never ship a
    # half dashboard.
    import axoquant_llm

    def _truncated_chat(*a, **k):
        class _R:
            text = '{"title": "half a dashboard'
            truncated = True
        return _R()

    monkeypatch.setattr(axoquant_llm, "chat", _truncated_chat)
    out = asyncio.run(app_mod._complete_fn([{"role": "user", "content": "x"}]))
    spec = json.loads(out)
    assert spec["title"] == "FOI request summary"
    assert "panels" in spec


def test_golden_gate_aborts_on_bad_data(monkeypatch):
    # Reviewer (c): the boot data-integrity gate must abort loudly (SystemExit)
    # when the normaliser emits data that fails the golden check — the app must
    # never serve wrong data. Reset the module cache and patch normalise_all to
    # produce a frame that cannot pass golden_check.
    saved_frame, saved_pages = app_mod._FRAME, app_mod._PAGES
    app_mod._FRAME, app_mod._PAGES = None, None
    try:
        monkeypatch.setattr(app_mod, "normalise_all", lambda: [])
        with pytest.raises(SystemExit):
            app_mod.create_app()
    finally:
        app_mod._FRAME, app_mod._PAGES = saved_frame, saved_pages


def test_gzip_compresses_pages_and_assets():
    c = TestClient(create_app())
    for path in ["/at-a-glance.html", "/assets/site.css"]:
        r = c.get(path, headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200
        assert r.headers.get("content-encoding") == "gzip"


def test_assets_carry_revalidation_cache_header():
    c = TestClient(create_app())
    r = c.get("/assets/site.css")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, no-cache"


def test_gated_pages_redirect_when_anonymous():
    c = TestClient(create_app())
    for path in ["/ask.html"]:
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303
        assert "/login" in r.headers.get("location", "")

def test_legacy_pages_redirect_to_ask():
    # Chat and Reports collapsed into the Ask page; the old URLs stay alive.
    c = TestClient(create_app())
    for path in ["/chat.html", "/reports.html"]:
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers.get("location") == "/ask.html"

def test_gated_page_serves_with_valid_session(monkeypatch):
    from storage import auth
    import server.app as app_mod
    # a real secret is required to VALIDATE a session: with the forgeable default
    # in place the gated routes now treat every cookie as anonymous (303 -> login)
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    token = auth.encode_session(1, "alice", "viewer", app_mod.SESSION_SECRET)
    c = TestClient(create_app())
    c.cookies.set("foi_session", token)
    r = c.get("/ask.html")
    assert r.status_code == 200
    assert 'id="ask-log"' in r.text

def test_session_user_defaults_role_to_viewer(monkeypatch):
    # Task 1: a session minted before the role column existed (payload lacks
    # the key) must normalise to "viewer" — never KeyError, never internal.
    from starlette.requests import Request
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    monkeypatch.setattr(app_mod.auth, "decode_session",
                        lambda token, secret: {"user_id": 1, "username": "alice"})
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [],
             "query_string": b"", "cookies": {"foi_session": "legacy"}}
    user = app_mod._session_user(Request(scope))
    assert user == {"id": 1, "username": "alice", "role": "viewer"}

def test_gated_page_rejects_cookie_minted_with_default_secret(monkeypatch):
    # Reviewer R2: with the public default secret in place, a VALIDLY-SIGNED
    # cookie (minted with the same default) must be rejected on every gated
    # route — an attacker who read this repo can forge encode_session(1,"alice",
    # "dev-insecure-secret") and the default must not validate it.
    from storage import auth
    import server.app as app_mod
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "dev-insecure-secret")
    token = auth.encode_session(1, "alice", "viewer", "dev-insecure-secret")
    c = TestClient(create_app())
    c.cookies.set("foi_session", token)
    r = c.get("/ask.html", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers.get("location", "")

def test_chat_route_requires_session():
    c = TestClient(create_app())
    r = c.post("/chat", json={"question": "how many requests?"},
               follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers.get("location", "")

def test_report_route_requires_session():
    c = TestClient(create_app())
    r = c.post("/report", json={"request": "requests received"},
               follow_redirects=False)
    assert r.status_code == 303

def test_report_route_threads_user_id_into_the_builder(monkeypatch):
    # "My reports" is per-user: when the deterministic router cannot map a query,
    # /report hands the session user's id to _build_dashboard so the artifact row
    # is owned by the caller (and listed only on their reports page).
    import server.app as app_mod
    from storage import auth
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    token = auth.encode_session(1, "alice", "viewer", app_mod.SESSION_SECRET)

    captured = {}

    async def fake_build(frame, request_text, user_id=None):
        captured["user_id"] = user_id
        return {"artifact_id": 1, "dashboard_url": "/dashboards/1",
                "lineage_url": "/lineage/1", "error": None}

    monkeypatch.setattr(app_mod, "build_report",
                        lambda request, frame: {"model": "no-match",
                                                "escalate": True, "error": "x"})
    monkeypatch.setattr(app_mod, "_build_dashboard", fake_build)
    monkeypatch.setattr(app_mod, "_record_message", lambda *a, **k: None)
    c = TestClient(create_app())
    c.cookies.set("foi_session", token)
    r = c.post("/report", json={"request": "top 5 agencies by requests"})
    assert r.status_code == 200
    assert r.json()["built"] is True
    assert captured["user_id"] == 1

def test_login_sets_session_cookie(monkeypatch):
    import server.app as app_mod
    monkeypatch.setattr(app_mod, "_authenticate",
                        lambda u, p: {"id": 1, "username": "alice"})
    # a real secret is required to mint a session: with the forgeable default in
    # place the route now refuses (503) instead of signing a cookie
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    c = TestClient(create_app())
    r = c.post("/login", data={"username": "alice", "password": "x"},
               follow_redirects=False)
    assert r.status_code == 303
    assert r.headers.get("location") == "/ask.html"
    assert "foi_session" in r.cookies

def test_login_wrong_password_rejected(monkeypatch):
    import server.app as app_mod
    monkeypatch.setattr(app_mod, "_authenticate", lambda u, p: None)
    # a real secret so the request reaches the credential check (not the 503 guard)
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    c = TestClient(create_app())
    r = c.post("/login", data={"username": "alice", "password": "bad"},
               follow_redirects=False)
    assert r.status_code == 401

def test_login_refused_when_session_secret_is_default(monkeypatch):
    # Reviewer (Important): with the public default secret in place, POST /login
    # must refuse to mint a session (503) — the default is forgeable by anyone
    # who has read this repo, so it must never sign a valid cookie.
    import server.app as app_mod
    monkeypatch.setattr(app_mod, "_authenticate",
                        lambda u, p: {"id": 1, "username": "alice"})
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "dev-insecure-secret")
    c = TestClient(create_app())
    r = c.post("/login", data={"username": "alice", "password": "x"},
               follow_redirects=False)
    assert r.status_code == 503
    assert "foi_session" not in r.cookies

def test_logout_clears_session():
    from storage import auth
    import server.app as app_mod
    c = TestClient(create_app())
    c.cookies.set("foi_session", auth.encode_session(1, "alice", "viewer", app_mod.SESSION_SECRET))
    r = c.get("/logout", follow_redirects=False)
    assert r.status_code == 303
    # The session cookie must be CLEARED, not re-sent with a fresh value. The
    # original brief assertion ("foi_session=" not in set-cookie) was impossible:
    # Starlette 1.6.0's delete_cookie renders the clearing Set-Cookie as
    # `foi_session=""; ...; Max-Age=0; ...` — any Set-Cookie that clears the
    # `foi_session` cookie must name the key. Assert the clearing attributes
    # instead (empty value via Max-Age=0), and that no new token is minted.
    set_cookie = r.headers.get("set-cookie", "")
    assert "foi_session" in set_cookie
    assert "Max-Age=0" in set_cookie

def test_chat_route_returns_grounded_answer(monkeypatch):
    import server.app as app_mod
    from storage import auth
    # a real secret is required to VALIDATE a session: with the forgeable default
    # in place the gated routes treat every cookie as anonymous (303 -> login)
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    token = auth.encode_session(1, "alice", "viewer", app_mod.SESSION_SECRET)
    captured = {}

    async def fake_chat(query, history=None, frame=None):
        captured["query"] = query
        return {"answer": "12,359 requests were received in Q1 2025-26.",
                "citations": ["catalog:requests_received_q1"],
                "provider": "deterministic", "escalate": False}

    # IMPORTANT: app.py imports `chat` BY VALUE (`from agentic.chat import
    # chat as agentic_chat`), so patching agentic.chat.chat does NOT change
    # what the route calls. Patch the app module's own `agentic_chat` binding.
    monkeypatch.setattr(app_mod, "agentic_chat", fake_chat)
    c = TestClient(create_app())
    c.cookies.set("foi_session", token)
    r = c.post("/chat", json={"question": "how many requests were received?"})
    assert r.status_code == 200
    body = r.json()
    assert captured["query"] == "how many requests were received?"
    assert body["citations"] == ["catalog:requests_received_q1"]


def _ask_session(monkeypatch, c):
    from storage import auth
    import server.app as app_mod
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    token = auth.encode_session(1, "alice", "viewer", app_mod.SESSION_SECRET)
    c.cookies.set("foi_session", token)
    return app_mod


def test_ask_question_routes_stat_kind(monkeypatch):
    # The unified ask endpoint: a stat-shaped question comes back as kind "stat"
    # with the platform-computed figure (same contract the reports page had).
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.post("/ask-question",
               json={"question": "how many requests were received last quarter?"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "stat"
    assert body["stat_key"] == "requests_received_q1"
    assert body["data"] == 12359
    assert body["dataset_registry"]["rows_hash"]


def test_ask_question_routes_note_kind_for_quarterly(monkeypatch):
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.post("/ask-question",
               json={"question": "show requests received by month"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "note"
    assert "annual" in body["note"]
    assert body["escalate"] is False


def test_ask_question_routes_provenance_kind(monkeypatch):
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    r = c.post("/ask-question", json={"question": "where does the data come from?"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "provenance"
    assert "Where this data comes from" in body["answer"]


def test_ask_question_falls_back_to_narrative(monkeypatch):
    # An in-scope question the router cannot map and that has no build intent
    # answers in grounded prose (never the old "email us" escalation). The ask
    # pipeline imports chat lazily, so patch agentic.chat.chat itself.
    import agentic.chat as chat_mod
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)

    async def fake_chat(query, history=None, frame=None):
        return {"answer": "The dataset holds agency-level FOI statistics.",
                "citations": ["data/corpus/data-notes.md"],
                "provider": "sovereign", "escalate": False}

    monkeypatch.setattr(chat_mod, "chat", fake_chat)
    r = c.post("/ask-question",
               json={"question": "what does the FOI dataset contain?"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "narrative"
    assert body["escalate"] is False
    assert "agency-level" in body["answer"]


def test_ask_question_builds_dashboard_on_explicit_intent(monkeypatch):
    # "build a dashboard…" goes to the builder; the returned kind carries the
    # durable dashboard link, and the build is stamped with the caller's id.
    import server.app as app_mod
    c = TestClient(create_app())
    app_mod = _ask_session(monkeypatch, c)
    captured = {}

    async def fake_build(frame, request_text, user_id=None):
        captured["user_id"] = user_id
        return {"artifact_id": 42, "dashboard_url": "/dashboards/42",
                "lineage_url": "/lineage/42", "error": None}

    monkeypatch.setattr(app_mod, "_build_dashboard", fake_build)
    monkeypatch.setattr(app_mod, "_record_message", lambda *a, **k: None)
    r = c.post("/ask-question",
               json={"question": "build a dashboard of requests by agency"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "dashboard"
    assert body["dashboard_url"] == "/dashboards/42"
    assert captured["user_id"] == 1


def test_ask_question_compare_is_deterministic(monkeypatch):
    # a named-agency comparison answers deterministically off the frame (the
    # agency table), never through the LLM builder and never as prose that
    # cannot quote figures
    import server.app as app_mod
    c = TestClient(create_app())
    app_mod = _ask_session(monkeypatch, c)
    monkeypatch.setattr(app_mod, "_record_message", lambda *a, **k: None)
    r = c.post("/ask-question",
               json={"question": "compare Home Affairs and Services Australia"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "stat"
    assert body["stat_key"] == "agency_compare"
    assert "Department of Home Affairs" in body["data"]["compare"]["agencies"]


def test_ask_question_failed_build_falls_back_to_the_router(monkeypatch):
    # build intent that produces nothing falls through to the stat router: an
    # instant figure beats hiding the failure behind prose
    import server.app as app_mod
    c = TestClient(create_app())
    app_mod = _ask_session(monkeypatch, c)

    async def fake_build(frame, request_text, user_id=None):
        return {"artifact_id": 9, "dashboard_url": None,
                "lineage_url": None, "error": "could not build"}

    monkeypatch.setattr(app_mod, "_build_dashboard", fake_build)
    monkeypatch.setattr(app_mod, "_record_message", lambda *a, **k: None)
    r = c.post("/ask-question",
               json={"question": "build a dashboard of requests received by agency"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "stat"
    assert body["stat_key"] == "received_top20"


def test_ask_question_requires_session():
    c = TestClient(create_app())
    r = c.post("/ask-question", json={"question": "how many requests?"},
               follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers.get("location", "")


def test_ask_question_queues_build_when_worker_enabled(monkeypatch):
    # With the worker on (FOI_WORKER=1), build intent returns kind "queued"
    # immediately: the page then polls /dashboards/{id}/status for the theatre.
    import server.app as app_mod
    c = TestClient(create_app())
    app_mod = _ask_session(monkeypatch, c)
    monkeypatch.setattr(app_mod, "WORKER_ENABLED", True)
    captured = {}

    def fake_enqueue(frame, request_text, user_id=None):
        captured["user_id"] = user_id
        captured["request_text"] = request_text
        return {"queued": True, "job_id": 5, "dashboard_url": "/dashboards/5",
                "lineage_url": "/lineage/5", "error": None}

    monkeypatch.setattr(app_mod, "_enqueue_dashboard", fake_enqueue)
    monkeypatch.setattr(app_mod, "_record_message", lambda *a, **k: None)
    r = c.post("/ask-question",
               json={"question": "build a dashboard of requests by agency"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "queued"
    assert body["job_id"] == 5
    assert body["dashboard_url"] == "/dashboards/5"
    assert captured["user_id"] == 1


def test_dashboard_status_endpoint(monkeypatch):
    import server.app as app_mod
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params=None):
            pass

        def fetchone(self):
            return ("building",
                    [{"step": "queued", "detail": "waiting for the builder"},
                     {"step": "building", "detail": "turn 1 of 6"}], {})

    class _Conn:
        def cursor(self):
            return _Cursor()

        def close(self):
            pass

    monkeypatch.setattr(app_mod, "get_conn", lambda: _Conn())
    monkeypatch.setattr(app_mod, "may_access_artifact", lambda c, aid, uid: True)
    r = c.get("/dashboards/42/status")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "building"
    assert body["progress"][-1]["detail"] == "turn 1 of 6"
    assert body["dashboard_url"] == "/dashboards/42"


def test_dashboard_status_requires_session():
    c = TestClient(create_app())
    r = c.get("/dashboards/42/status", follow_redirects=False)
    assert r.status_code == 303


def test_dashboard_status_forbidden_for_foreign_owner(monkeypatch):
    c = TestClient(create_app())
    _ask_session(monkeypatch, c)
    monkeypatch.setattr(app_mod, "get_conn", lambda: object())
    monkeypatch.setattr(app_mod, "may_access_artifact", lambda c, aid, uid: False)
    r = c.get("/dashboards/42/status")
    assert r.status_code == 403


def test_dashboard_retry_endpoint(monkeypatch):
    import server.app as app_mod
    c = TestClient(create_app())
    app_mod = _ask_session(monkeypatch, c)
    captured = {}

    def fake_requeue(conn, artifact_id, user_id=None):
        captured["user_id"] = user_id
        captured["id"] = artifact_id
        return True

    monkeypatch.setattr(app_mod, "get_conn", lambda: object())
    monkeypatch.setattr(app_mod, "requeue_job", fake_requeue)
    r = c.post("/dashboards/42/retry")
    assert r.status_code == 200
    assert r.json() == {"queued": True}
    assert captured == {"user_id": 1, "id": 42}

def test_risk_page_internal_renders(monkeypatch):
    from storage import auth
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    token = auth.encode_session(1, "alice", "internal", app_mod.SESSION_SECRET)
    c = TestClient(create_app())
    c.cookies.set("foi_session", token)
    r = c.get("/risk.html")
    assert r.status_code == 200
    assert "Risk &amp; Forecast" in r.text


def test_risk_page_viewer_renders(monkeypatch):
    # the risk/forecast views are now a signed-in section, not internal-only
    from storage import auth
    monkeypatch.setattr(app_mod, "SESSION_SECRET", "test-secret-0123456789abcdef")
    token = auth.encode_session(1, "alice", "viewer", app_mod.SESSION_SECRET)
    c = TestClient(create_app())
    c.cookies.set("foi_session", token)
    r = c.get("/risk.html", follow_redirects=False)
    assert r.status_code == 200
    assert "Risk &amp; Forecast" in r.text


def test_risk_page_anonymous_redirects():
    c = TestClient(create_app())
    r = c.get("/risk.html", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers.get("location", "")
