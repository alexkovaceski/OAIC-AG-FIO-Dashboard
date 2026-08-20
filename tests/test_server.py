"""Regression tests for the Task 8 FastAPI server (server.app).

The whole suite must run WITHOUT a live Postgres: /ask fails open to a synthetic
artifact id when the DB is unreachable (lineage must never fail a build), and
/lineage/{id} renders a degraded page with conn=None. The golden boot check
runs on create_app() — any test failing here means the data/normaliser
integrity gate is wrong.
"""
import sys

sys.path.insert(0, "src")
from fastapi.testclient import TestClient
from server.app import create_app


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


def test_ask_returns_artifact_and_urls():
    # the deterministic _complete_fn returns a canned spec, so /ask works
    # end-to-end without a live model or a live DB (fail-open to a synthetic id)
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
