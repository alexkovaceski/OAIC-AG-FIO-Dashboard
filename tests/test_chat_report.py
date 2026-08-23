# tests/test_chat_report.py
import sys
sys.path.insert(0, "src")
from corpus import search_corpus, corpus_stats

def test_search_returns_documents():
    hits = search_corpus("requests received", top_n=5)
    assert hits and isinstance(hits[0], dict)
    assert {"title", "path", "snippet", "score"} <= hits[0].keys()
    assert hits[0]["score"] > 0

def test_search_grounds_on_catalog_descriptions():
    # a measure named in a request must surface the catalog description doc
    hits = search_corpus("granted in full", top_n=5)
    assert hits and any("granted in full" in h["title"].lower()
                        or h["path"] == "catalog:granted_full_share_q1"
                        for h in hits)

def test_corpus_stats():
    s = corpus_stats()
    assert s["docs"] >= 1
    assert s["tokens"] > 0

import asyncio
from agentic import chat as chat_mod

def test_chat_scope_refusal_escalates():
    # "immigration visa" trips _OUT_OF_SCOPE_RE BEFORE the model; the refusal
    # carries the email escalation path.
    out = asyncio.run(chat_mod.chat("immigration visa question", []))
    assert out["provider"] == "scope"
    assert out["escalate"] is True
    assert "contact@bluebirdadvisory.com.au" in out["answer"]

def test_chat_deterministic_fallback_on_model_failure(monkeypatch):
    async def _boom(*a, **k):
        raise RuntimeError("model unreachable")
    monkeypatch.setattr(chat_mod, "_complete", _boom)
    out = asyncio.run(chat_mod.chat("how many requests were received?", []))
    assert out["provider"] == "deterministic"
    assert out["escalate"] is False
    assert isinstance(out["citations"], list)
    assert out["answer"] and "contact@bluebirdadvisory.com.au" not in out["answer"]

def test_chat_sovereign_path_returns_model_text(monkeypatch):
    async def _hello(*a, **k):
        return "The Q1 2025-26 total is in the context. [catalog:requests_received_q1]"
    monkeypatch.setattr(chat_mod, "_complete", _hello)
    out = asyncio.run(chat_mod.chat("how many requests were received?", []))
    assert out["provider"] == "sovereign"
    assert out["escalate"] is False
    assert out["citations"]  # retrieved docs carried through

def test_report_routes_to_real_figure():
    from ingest.normalise import normalise_all
    from storage.frame import Frame
    from stats.catalog import foi_stats
    from agentic.report import build_report
    frame = Frame(normalise_all())
    out = build_report("How many requests were received last quarter?", frame)
    assert out["stat_key"] == "requests_received_q1"
    assert out["data"] == foi_stats(frame, "requests_received_q1")["value"]

def test_report_refused_if_out_of_scope():
    from ingest.normalise import normalise_all
    from storage.frame import Frame
    from agentic.report import build_report
    frame = Frame(normalise_all())
    out = build_report("crypto trading strategy", frame)
    assert out["stat_key"] is None
    assert out["escalate"] is True

def test_report_model_never_writes_digit():
    # the data value must equal the platform figure, not a model number
    from ingest.normalise import normalise_all
    from storage.frame import Frame
    from stats.catalog import foi_stats
    from agentic.report import build_report
    frame = Frame(normalise_all())
    out = build_report("top agencies for requests decided", frame)
    assert out["stat_key"] == "decided_top20"
    assert out["data"] == foi_stats(frame, "decided_top20")["value"]

def test_report_routes_timeliness_of_decisions_to_corr():
    # Reviewer: "timeliness of decisions" was misrouted to decided_q1 because
    # the `decided?|decision` pattern shadowed the later timeliness entry. The
    # reorder must send it to the timeliness_slippage_corr stat.
    from ingest.normalise import normalise_all
    from storage.frame import Frame
    from agentic.report import build_report
    frame = Frame(normalise_all())
    out = build_report("timeliness of decisions", frame)
    assert out["stat_key"] == "timeliness_slippage_corr"
    assert out["escalate"] is False

def test_report_unmappable_request_escalates():
    from ingest.normalise import normalise_all
    from storage.frame import Frame
    from agentic.report import build_report
    frame = Frame(normalise_all())
    out = build_report("build me a dashboard widget", frame)
    assert out["stat_key"] is None
    assert out["escalate"] is True
    assert "contact@bluebirdadvisory.com.au" in out["error"]
