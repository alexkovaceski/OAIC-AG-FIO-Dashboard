"""agentic.ask — the unified ask pipeline: one question in, one typed answer out.

One router in front of every engine, so the Chat and Reports split can collapse
into a single Ask surface. The answer kind is decided by the question, never
chosen by the reader:

  provenance  — curated lineage answer (registry, never the LLM)
  scope       — out-of-scope refusal + escalation
  stat        — a platform-computed figure or table (router + granularity)
  note        — a deterministic explanation with no figure (e.g. quarterly data)
  dashboard   — a built, durable dashboard spec (the multi-turn builder)
  narrative   — corpus-grounded prose from the sovereign LLM (the last resort)

Digit discipline is preserved per engine: stats and dashboards are
platform-computed (rows_hash + basis), narrative quotes only retrieved figures.
The builder is invoked through a `build` callback so this module stays free of
the server's conn/ledger plumbing; when no callback is given (or the build
fails), the question falls through to narrative instead of the old "email us"
escalation — an in-scope question should get an answer, not a dead end.
"""
from __future__ import annotations
import re

from agentic.guardrails import check_request, ScopeRefusal

# Explicit dashboard intent. The deterministic router runs first, so this only
# sees questions it could not map ("build a dashboard of requests by agency").
# Keeping it explicit means "explain how FOI decisions are classified" answers
# in prose immediately instead of spending six builder turns to fail.
_WANTS_BUILD_RE = re.compile(
    r"\b(?:build|create|make|chart|graph|dashboard|plot|visuali[sz]e|panel|"
    r"report on)\b",
    re.I)


async def ask(query: str, history: list[dict] | None, frame,
              build=None) -> dict:
    from agentic.chat import (_ESCALATION, _provenance_answer,
                              chat as agentic_chat)
    from agentic.report import build_report

    prov = _provenance_answer(query, frame)
    if prov is not None:
        return {**prov, "kind": "provenance"}

    try:
        check_request(query)
    except ScopeRefusal as exc:
        return {"kind": "scope", "answer": f"{exc} {_ESCALATION}",
                "citations": [], "escalate": True}

    routed = build_report(query, frame)
    if routed.get("model") != "no-match":
        if routed.get("escalate"):
            # e.g. provenance-unavailable: the registry drifted since boot.
            return {"kind": "scope", "answer": routed.get("error") or "",
                    "citations": [], "escalate": True}
        kind = ("note" if (routed.get("note") and routed.get("data") is None)
                else "stat")
        return {**routed, "kind": kind}

    # No deterministic figure: explicit dashboard intent -> builder; everything
    # else -> narrative. A failed/empty build also lands in narrative.
    if _WANTS_BUILD_RE.search(query or "") and build is not None:
        result = await build(query)
        if result.get("error") is None and result.get("dashboard_url"):
            return {"kind": "dashboard",
                    "dashboard_url": result["dashboard_url"],
                    "lineage_url": result["lineage_url"], "escalate": False}

    out = await agentic_chat(query, history, frame)
    return {**out, "kind": "narrative"}
