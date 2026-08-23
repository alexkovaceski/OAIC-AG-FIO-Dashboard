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
