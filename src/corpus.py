"""corpus — retrieval over the FOI corpus + catalog descriptions.

The chat is grounded: documents come from (a) data/corpus/*.md (verbatim)
and (b) a catalog-driven description of every stat/figure so a request that
names a measure resolves to the platform figure. Simple token/keyword
scoring (no external deps); every hit carries the source path so citations
always resolve.
"""
from __future__ import annotations
import math
import re
from collections import Counter
from pathlib import Path

from stats.catalog import FIG_CAPTIONS, STAT_KEYS, FIG_KEYS

_CORPUS = Path(__file__).resolve().parent.parent / "data" / "corpus"
_WORD = re.compile(r"[a-z0-9']+", re.I)

def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]

# A description of every catalog stat/figure, so retrieval can resolve a
# measure request to the platform figure it describes. Descriptive prose for
# retrieval only — never a figure.
_STAT_LABELS = {
    "requests_received_q1": "Requests received, single quarter",
    "requests_finalised_q1": "Requests finalised, single quarter",
    "decided_q1": "Requests decided, single quarter",
    "within_statutory_pct_q1": "Decisions within the statutory time period",
    "granted_full_share_q1": "Share of decisions granted in full",
    "granted_part_share_q1": "Share of decisions granted in part",
    "refused_share_q1": "Share of decisions refused",
    "withdrawn_q1": "Share of decisions withdrawn",
    "refusal_rate_change_fy23_fy24": "Refusal rate change, FY23 vs FY24, top agencies",
    "timeliness_slippage_corr": "Timeliness slippage correlation",
    "received_movers": "Agencies with growing requests received, year on year",
}

def _documents() -> list[dict]:
    docs = []
    for p in sorted(_CORPUS.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        title = ""
        for line in text.splitlines()[:5]:
            if line.startswith("#"):
                title = line.lstrip("#").strip()
                break
        docs.append({"title": title or p.stem,
                     "path": f"data/corpus/{p.name}",
                     "text": text, "tokens": Counter(_tokens(text))})
    for key in STAT_KEYS:
        label = _STAT_LABELS.get(key, key.replace("_", " "))
        docs.append({"title": label, "path": f"catalog:{key}",
                     "text": label, "tokens": Counter(_tokens(label))})
    for key in FIG_KEYS:
        label = FIG_CAPTIONS.get(key, key.replace("_", " "))
        docs.append({"title": label, "path": f"catalog:{key}",
                     "text": label, "tokens": Counter(_tokens(label))})
    return docs

_DOCS = _documents()

def search_corpus(query: str, top_n: int = 6) -> list[dict]:
    """Rank corpus+catalog documents by token overlap with the query
    (BM25-style log-ratio scoring, no deps)."""
    qt = _tokens(query)
    if not qt:
        return []
    n = len(_DOCS)
    df = Counter()
    for d in _DOCS:
        for t in set(d["tokens"]):
            df[t] += 1
    results = []
    for d in _DOCS:
        score = 0.0
        for t in qt:
            if t in d["tokens"]:
                score += math.log((n + 1) / (df[t] + 0.5))
        if score <= 0:
            continue
        snippet = d.get("text", "")[:200].replace("\n", " ").strip()
        results.append({"title": d["title"], "path": d["path"],
                        "snippet": snippet, "score": round(score, 4)})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_n]

def corpus_stats() -> dict:
    return {"docs": len(_DOCS), "tokens": sum(len(d["tokens"]) for d in _DOCS)}
