"""Regression tests for the Task 8 FastAPI server (server.app).

The whole suite must run WITHOUT a live Postgres: /ask fails open to a synthetic
artifact id when the DB is unreachable (lineage must never fail a build), and
/lineage/{id} renders a degraded page with conn=None. The golden boot check
runs on create_app() — any test failing here means the data/normaliser
integrity gate is wrong.
"""
import asyncio
import json
import sys

import httpx
import pytest

sys.path.insert(0, "src")
from fastapi.testclient import TestClient
from server.app import create_app
import server.app as app_mod


async def _fake_complete(messages):
    # hermetic replacement for the real _complete_fn: no network, immediate spec
    return ('{"title": "FOI request summary", '
            '"description": "test", "panels": []}')


def test_health():
    c = TestClient(create_app())
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["model"] == "fartkraft sovereign stack"


def test_static_pages_render():
    c = TestClient(create_app())
    for page in ["at-a-glance", "requests-received", "data-notes"]:
        r = c.get(f"/{page}.html")
        assert r.status_code == 200
        assert "fartkraft" in r.text.lower()


def test_ask_returns_artifact_and_urls(monkeypatch):
    # hermetic end-to-end /ask: the fake complete_fn returns the canned spec, so
    # the route works without a live model or a live DB (fail-open to a synthetic id)
    monkeypatch.setattr(app_mod, "_complete_fn", _fake_complete)
    c = TestClient(create_app())
    r = c.post("/ask", json={"request": "show me requests received by agency"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("artifact_id")
    assert body["dashboard_url"] == "/at-a-glance.html"
    assert body["lineage_url"] == f"/lineage/{body['artifact_id']}"


def test_lineage_page_renders():
    c = TestClient(create_app())
    r = c.get("/lineage/abc123")
    assert r.status_code == 200
    assert "fartkraft" in r.text.lower()


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
    captured = {}

    async def fake_build_spec(text, frame, complete_fn, ledger, conn,
                              max_turns=6, artifact_id=None):
        captured["conn"] = conn
        captured["artifact_id"] = artifact_id
        return {"title": "FOI request summary", "panels": []}

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


def test_complete_fn_falls_back_when_llm_unreachable(monkeypatch):
    # Task 9 load-bearing requirement: on ANY failure (endpoint down, timeout,
    # non-2xx, bad body) _complete_fn returns the deterministic canned spec so
    # the demo never dies. Point FOI_LLM_URL at an unreachable port and assert
    # the fallback — no network is actually required (connect is refused).
    monkeypatch.setenv("FOI_LLM_URL", "http://127.0.0.1:1/v1/chat/completions")
    out = asyncio.run(app_mod._complete_fn([{"role": "user", "content": "x"}]))
    spec = json.loads(out)
    assert spec["title"] == "FOI request summary"
    assert "panels" in spec


def test_complete_fn_passes_through_model_text(monkeypatch):
    # when the endpoint answers, _complete_fn returns the raw model text; the
    # messages it received are forwarded verbatim in the payload
    captured = {}

    async def fake_post(self, url, json=None):
        # AsyncClient.post is a coroutine — the fake must be awaitable too, and
        # raise_for_status() needs the request set on the response
        captured["url"] = url
        captured["payload"] = json
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello"}}]},
            request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    msgs = [{"role": "user", "content": "build a dashboard"}]
    out = asyncio.run(app_mod._complete_fn(msgs))
    assert out == "hello"
    assert captured["payload"]["messages"] == msgs
    assert captured["payload"]["model"] == "qwen3next-80b"
    assert captured["payload"]["temperature"] == 0.2
    assert captured["url"] == "http://idc-1:8012/v1/chat/completions"


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
