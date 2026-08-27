"""agentic.ask — the unified ask pipeline: one question in, one typed answer out.

One router in front of every engine, so the Chat and Reports split can collapse
into a single Ask surface. The answer kind is decided by the question, never
chosen by the reader:

  provenance  — curated lineage answer (registry, never the LLM)
  scope       — out-of-scope refusal + escalation
  dashboard   — a built, durable dashboard spec (the multi-turn builder)
  stat        — a platform-computed figure or table (router + granularity)
  note        — a deterministic explanation with no figure (e.g. quarterly data)
  narrative   — corpus-grounded prose from the sovereign LLM (the last resort)

Explicit build intent ("build a dashboard...", "compare X and Y") goes to the
builder BEFORE the stat router: the router would otherwise answer "build a
dashboard of requests received by agency" with the Q1 KPI number. A failed or
empty build falls through to the router (an instant figure is better than
nothing) and then to narrative.

Digit discipline is preserved per engine: stats and dashboards are
platform-computed (rows_hash + basis), narrative quotes only retrieved figures.
The builder is invoked through a `build` callback so this module stays free of
the server's conn/ledger plumbing; when no callback is given (or the build
fails), the question falls through the stat router to narrative instead of the
old "email us" escalation — an in-scope question should get an answer, not a
dead end.
"""
from __future__ import annotations
import re

from agentic.guardrails import check_request, ScopeRefusal

# Explicit dashboard intent. Compared against the original question before the
# router runs. "compare/versus/vs" counts as build intent: a two-agency
# comparison is a data job for the builder, not a prose question.
_WANTS_BUILD_RE = re.compile(
    r"\b(?:build|create|make|chart|graph|dashboard|plot|visuali[sz]e|panel|"
    r"report on|compare|versus|vs\.?)\b",
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

    if _WANTS_BUILD_RE.search(query or "") and build is not None:
        result = await build(query)
        if result.get("error") is None and result.get("dashboard_url"):
            return {"kind": "dashboard",
                    "dashboard_url": result["dashboard_url"],
                    "lineage_url": result["lineage_url"], "escalate": False}
        # the build failed or produced nothing: fall through to the router for
        # an instant figure rather than hiding the failure behind prose

    routed = build_report(query, frame)
    if routed.get("model") != "no-match":
        if routed.get("escalate"):
            # e.g. provenance-unavailable: the registry drifted since boot.
            return {"kind": "scope", "answer": routed.get("error") or "",
                    "citations": [], "escalate": True}
        kind = ("note" if (routed.get("note") and routed.get("data") is None)
                else "stat")
        return {**routed, "kind": kind}

    out = await agentic_chat(query, history, frame)
    return {**out, "kind": "narrative"}
