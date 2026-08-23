"""agentic.report — the reporting engine.

A natural-language request maps to a catalog stat (deterministic keyword
router), and the platform computes the figure. The model never writes a
digit: the router only selects a stat key; the number comes from the Frame.
This is the same "model emits structure, platform computes numbers"
discipline as the /ask builder. An unmappable request escalates to the email
redirect. Router order matters: more specific patterns (refusal rate, top
agencies by decided) come BEFORE the general ones (refus, decided) they would
otherwise shadow.
"""
from __future__ import annotations
import re

from stats.catalog import foi_stats
from agentic.guardrails import check_request, ScopeRefusal

_ESCALATION = ("That request is beyond what the site can compute. For a "
               "custom FOI report, email contact@bluebirdadvisory.com.au.")

_ROUTER: list[tuple[re.Pattern, str]] = [
    (re.compile(r"refusal rate", re.I), "refusal_rate_change_fy23_fy24"),
    (re.compile(r"within statutory|statutory", re.I), "within_statutory_pct_q1"),
    (re.compile(r"granted in full|full grant", re.I), "granted_full_share_q1"),
    (re.compile(r"granted in part|part grant", re.I), "granted_part_share_q1"),
    (re.compile(r"withdrawn", re.I), "withdrawn_q1"),
    (re.compile(r"top (?:20 )?agenc.*decid|decid.*top (?:20 )?agenc", re.I),
     "decided_top20"),
    (re.compile(r"top (?:20 )?agenc|agenc.*top|contribut", re.I), "received_top20"),
    (re.compile(r"received", re.I), "requests_received_q1"),
    (re.compile(r"finalis", re.I), "requests_finalised_q1"),
    (re.compile(r"refus", re.I), "refused_share_q1"),
    (re.compile(r"decided?|decision", re.I), "decided_q1"),
    (re.compile(r"timeliness|slippage", re.I), "timeliness_slippage_corr"),
]

_LABELS = {
    "requests_received_q1": "Requests received, Q1 2025-26",
    "requests_finalised_q1": "Requests finalised, Q1 2025-26",
    "decided_q1": "Requests decided, Q1 2025-26",
    "within_statutory_pct_q1": "Decisions within the statutory time period",
    "granted_full_share_q1": "Share of decisions granted in full",
    "granted_part_share_q1": "Share of decisions granted in part",
    "refused_share_q1": "Share of decisions refused",
    "withdrawn_q1": "Share of decisions withdrawn",
    "refusal_rate_change_fy23_fy24": "Refusal rate, FY23 vs FY24 top movers",
    "timeliness_slippage_corr": "Timeliness slippage correlation",
    "received_top20": "Top 20 agencies by requests received, FY 2024-25",
    "decided_top20": "Top 20 agencies by requests decided, FY 2024-25",
}


def build_report(request: str, frame) -> dict:
    try:
        check_request(request)
    except ScopeRefusal as exc:
        return {"request": request, "stat_key": None, "stat_label": None,
                "data": None, "basis": None, "dataset_registry": {},
                "model": "scope", "escalate": True, "error": f"{exc} {_ESCALATION}"}
    key = None
    for pattern, stat_key in _ROUTER:
        if pattern.search(request):
            key = stat_key
            break
    if key is None:
        return {"request": request, "stat_key": None, "stat_label": None,
                "data": None, "basis": None, "dataset_registry": {},
                "model": "no-match", "escalate": True, "error": _ESCALATION}
    stat = foi_stats(frame, key)
    return {"request": request, "stat_key": key,
            "stat_label": _LABELS.get(key, key.replace("_", " ")),
            "data": stat["value"], "basis": stat["basis"],
            "dataset_registry": {"source_rows": stat["source_rows"],
                                 "rows_hash": stat["rows_hash"]},
            "model": "deterministic router (figures from the platform frame, "
                     "not the LLM)", "escalate": False}
