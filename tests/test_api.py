"""Tests for the read-only data API + rate limiter (src/api.py + /api routes).

The API exposes the SAME platform-computed figures and canonical facts the
visualisations use. It is throttled per client IP so the public no-auth demo
isn't overloaded. All tests run without a live DB.
"""
import sys

sys.path.insert(0, "src")
from fastapi.testclient import TestClient
import api
from ingest.normalise import normalise_all
from storage.frame import Frame
from server.app import create_app


def _frame():
    return Frame(normalise_all())


def test_dataset_info_reports_snapshot():
    info = api.dataset_info(_frame())
    assert info["dataset_id"] == "b0771c28-09cc-4c4e-9e61-9a96f6e3d040"
    assert "received" in info["measures"]
    assert "single_quarter" in info["window_modes"]
    assert info["fact_count"] > 1000


def test_figures_carry_basis_and_real_value():
    figs = api.figures(_frame())
    # the golden Q1 received figure is platform-computed, basis labelled
    assert figs["requests_received_q1"]["value"] == 12359
    assert figs["requests_received_q1"]["basis"] == "single_quarter"


def test_facts_filter_and_page():
    out = api.facts(_frame(), measure="received", bucket="total", fy="2024-25")
    assert out["total"] > 0
    assert all(f["measure"] == "received" for f in out["facts"])
    assert all(f["bucket"] == "total" for f in out["facts"])
    assert all(f["fy"] == "2024-25" for f in out["facts"])
    # paging
    p1 = api.facts(_frame(), limit=10)
    p2 = api.facts(_frame(), limit=10, offset=10)
    assert len(p1["facts"]) == 10 and len(p2["facts"]) == 10
    assert p1["facts"][0] != p2["facts"][0]


def test_measures_groups():
    m = api.measures(_frame())
    assert "requests" in m
    assert "received" in m["requests"]


def test_provenance_api_returns_the_registry():
    out = api.provenance(_frame())
    assert out["sources"] and out["decisions"] and out["derivations"]


def test_provenance_api_with_a_key_adds_the_figure_layer():
    out = api.provenance(_frame(), key="received_top20")
    assert out["figure"]["key"] == "received_top20"
    assert out["figure"]["source_rows"] > 0
    assert len(out["figure"]["rows_hash"]) == 64


def test_provenance_api_unknown_key_errors_not_raises():
    out = api.provenance(_frame(), key="nope")
    assert "error" in out
    assert "sources" not in out


def test_provenance_endpoint_via_testclient():
    c = TestClient(create_app())
    r = c.get("/api/provenance")
    assert r.status_code == 200
    assert r.json()["sources"]
    with_key = c.get("/api/provenance?key=received_top20").json()
    assert with_key["figure"]["key"] == "received_top20"


def test_api_endpoints_via_testclient():
    c = TestClient(create_app())
    assert c.get("/api/").status_code == 200
    figs = c.get("/api/figures").json()
    assert figs["requests_received_q1"]["value"] == 12359
    facts = c.get("/api/facts?measure=received&bucket=total&fy=2024-25").json()
    assert facts["total"] > 0
    assert c.get("/api/measures").status_code == 200


def test_rate_limiter_throttles():
    # with a tight limit, excess requests get 429 + Retry-After
    old_limit, old_window = api.RATE_LIMIT, api.RATE_WINDOW
    api.RATE_LIMIT, api.RATE_WINDOW = 3, 60
    api._buckets.clear()
    try:
        c = TestClient(create_app())
        ok = [c.get("/api/") for _ in range(3)]
        assert all(r.status_code == 200 for r in ok)
        blocked = c.get("/api/")
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
        assert "rate limit exceeded" in blocked.text
    finally:
        api.RATE_LIMIT, api.RATE_WINDOW = old_limit, old_window
        api._buckets.clear()


def test_api_page_is_served():
    c = TestClient(create_app())
    r = c.get("/api.html")
    assert r.status_code == 200
    assert "API access" in r.text
    assert "/api/figures" in r.text
    assert "rate-limited" in r.text.lower()
    assert "fartkraft" in r.text.lower()
