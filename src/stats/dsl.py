"""dsl — the enum-constrained DSL the agent drives. Platform computes every figure.

Read-only ops over the Frame plus AST-safe compute. The agent never touches SQL
and never writes a digit: it issues ops with enum-constrained params and cites
recorded tool-call results via {c:job.turn.call.field} pointers.
"""
from __future__ import annotations
import ast
import json
import operator as _op
import re

from stats.catalog import foi_stats, STAT_KEYS

# citation pointer {c:<job>.<turn>.<call>.<field>} -> a value recorded in the
# transcript of a query_dataset call (see resolve_citations).
CITATION_PATTERN = re.compile(r"\{c:([\w.]+)\}")


def _safe_math(expr: str, env: dict) -> float:
    """AST-safe arithmetic over env (named columns + numbers). Div-by-zero RAISES."""
    expr = (expr or "").strip()
    if not expr:
        raise ValueError("empty expression")

    def node_eval(n):
        if isinstance(n, ast.Expression):
            return node_eval(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in env:
                return env[n.id]
            raise ValueError(f"unknown column {n.id}")
        if isinstance(n, ast.BinOp):
            ops = {ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
                   ast.Div: _op.truediv, ast.Pow: _op.pow}
            a, b = node_eval(n.left), node_eval(n.right)
            if isinstance(n.op, ast.Div) and b == 0:
                raise ValueError("division by zero — cannot mint a wrong rate")
            return ops[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -node_eval(n.operand)
        raise ValueError("unsupported expression element")

    try:
        return float(node_eval(ast.parse(expr, mode="eval").body))
    except ValueError:
        raise


def compute_safe(expr: str, env: dict) -> dict:
    try:
        return {"expression": expr, "value": round(_safe_math(expr, env), 2)}
    except ValueError as exc:
        return {"expression": expr, "error": str(exc)}


def query_dataset(frame, op: str, params: dict) -> dict:
    """Read-only DSL ops over the FOI frame. Basis is a field of every result."""
    op = (op or "").strip().lower()
    basis = params.get("window_mode", "fy")
    if op == "list_agencies":
        return {"basis": basis, "agencies": sorted({f["agency_name"] for f in frame.facts if not f["agency_name"].startswith("x")})}
    if op == "filter_agencies":
        # {fy?, measure?, bucket?, top_n?}
        rows = frame.facts
        if params.get("fy"): rows = [f for f in rows if f["fy"] == params["fy"]]
        if params.get("measure"): rows = [f for f in rows if f["measure"] == params["measure"]]
        if params.get("bucket"): rows = [f for f in rows if f["bucket"] == params["bucket"]]
        aggs = {}
        for f in rows:
            aggs.setdefault(f["agency_name"], 0.0)
            aggs[f["agency_name"]] += f["value"]
        top = sorted(aggs.items(), key=lambda kv: kv[1], reverse=True)[:int(params.get("top_n", 20))]
        return {"basis": basis, "count": len(aggs), "top": [{"agency": a, "value": round(v)} for a, v in top]}
    if op == "summarize_agencies":
        rows = frame.facts
        if params.get("measure"): rows = [f for f in rows if f["measure"] == params["measure"]]
        if params.get("bucket"): rows = [f for f in rows if f["bucket"] == params["bucket"]]
        return {"basis": basis, "count": len(rows), "total": round(sum(f["value"] for f in rows))}
    if op == "trend":
        # 5-year FY trend
        cats = sorted({f["fy"] for f in frame.facts if f["quarter"] is None})
        rows = [f for f in frame.facts if f["quarter"] is None and f["measure"] == params.get("measure", "received") and f["bucket"] == "total"]
        by = {}
        for f in rows:
            by.setdefault(f["fy"], 0.0)
            by[f["fy"]] += f["value"]
        return {"basis": "fy", "years": cats, "values": [round(by.get(y, 0)) for y in cats]}
    if op == "compare_period":
        # same-period-previous-year change in a measure
        m = params.get("measure", "received")
        a, b = params.get("fy_a"), params.get("fy_b")
        def tot(fy):
            return sum(f["value"] for f in frame.facts if f["fy"] == fy and f["measure"] == m and f["bucket"] == "total")
        va, vb = tot(a), tot(b)
        return {"basis": "fy", "fy_a": a, "fy_b": b, "value_a": round(va), "value_b": round(vb),
                "change": round(vb - va), "change_pct": round(100 * (vb - va) / va) if va else 0}
    if op == "top_contributors":
        return query_dataset(frame, "filter_agencies", params)
    if op == "by_portfolio":
        rows = frame.facts
        if params.get("fy"): rows = [f for f in rows if f["fy"] == params["fy"]]
        if params.get("measure"): rows = [f for f in rows if f["measure"] == params["measure"]]
        if params.get("bucket"): rows = [f for f in rows if f["bucket"] == params["bucket"]]
        aggs = {}
        for f in rows:
            p = f.get("portfolio") or "Unmapped"
            aggs.setdefault(p, 0.0)
            aggs[p] += f["value"]
        return {"basis": params.get("window_mode", "fy"), "portfolios": [{"portfolio": p, "value": round(v)} for p, v in sorted(aggs.items(), key=lambda kv: kv[1], reverse=True)]}
    if op == "kpis":
        return {k: foi_stats(frame, k)["value"] for k in STAT_KEYS}
    if op == "gaps":
        return {"error": "gaps op not applicable to FOI stats — use trend/compare_period/top_contributors"}
    if op == "classes":
        return {"classes": sorted({f["measure_group"] for f in frame.facts})}
    return {"error": f"unknown op {op!r}; allowed: list_agencies, filter_agencies, summarize_agencies, trend, compare_period, top_contributors, by_portfolio, kpis, classes, compute"}


def resolve_citations(spec: dict, transcript: list[dict]) -> dict:
    """Replace {c:job.turn.call.field} pointers with recorded tool-call values.

    transcript entries carry the query_dataset result under 'result'; the
    pointer walks .result.<field-path>. An unknown pointer FAILS LOUD (SystemExit)
    — never a guessed number.
    """
    def _lookup(path: str):
        parts = path.split(".")
        if len(parts) < 2:
            raise KeyError(f"citation {path}: malformed pointer")
        seq = int(parts[1])
        for ev in transcript:
            if ev.get("seq") == seq and ev.get("tool") == "query_dataset":
                cur = ev.get("result")
                for p in parts[2:]:
                    if p.isdigit():
                        cur = cur[int(p)]
                    else:
                        if not isinstance(cur, dict) or p not in cur:
                            raise KeyError(f"citation {path}: unknown field {p}")
                        cur = cur[p]
                return cur
        raise KeyError(f"citation {path}: unknown transcript entry")

    text = json.dumps(spec)

    def _sub(m):
        return json.dumps(_lookup(m.group(1)))

    try:
        text = CITATION_PATTERN.sub(_sub, text)
    except KeyError as e:
        raise SystemExit(f"FAIL LOUD: {e} — a figure could not be resolved") from e
    return json.loads(text)
