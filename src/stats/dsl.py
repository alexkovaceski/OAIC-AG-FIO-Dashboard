"""dsl — the enum-constrained DSL the agent drives. Platform computes every figure.

Read-only ops over the Frame plus AST-safe compute. The agent never touches SQL
and never writes a digit: it issues ops with enum-constrained params and cites
recorded tool-call results via {c:job.turn.call.field} pointers.
"""
from __future__ import annotations
import ast
import operator as _op
import re

from stats.catalog import foi_stats, STAT_KEYS

# citation pointer {c:<job>.<turn>.<call>.<field>} -> a value recorded in the
# transcript of a query_dataset call (see resolve_citations). The field path
# supports bracket indices, e.g. top[0].agency.
CITATION_PATTERN = re.compile(r"\{c:([\w.\[\]]+)\}")
# tokenises a field-path segment like "top[0]" into keys ("top") and indices (0)
_FIELD_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


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
            if type(n.op) not in ops:
                raise ValueError(f"unsupported operator {type(n.op).__name__}")
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
    # Exception (not just ValueError): an unsupported operator (KeyError), an
    # overflowing power (OverflowError) or a bad operand must all surface as an
    # error dict — compute never raises, never mints a wrong number.
    try:
        return {"expression": expr, "value": round(_safe_math(expr, env), 2)}
    except Exception as exc:
        return {"expression": expr, "error": str(exc)}


def query_dataset(frame, op: str, params: dict) -> dict:
    """Read-only DSL ops over the FOI frame. Basis is a field of every result."""
    op = (op or "").strip().lower()
    basis = params.get("window_mode", "fy")
    if op == "list_agencies":
        return {"basis": basis, "agencies": sorted({f["agency_name"] for f in frame.facts
                if not f["agency_name"].startswith("x") and f["agency_name"].lower() != "total"})}
    if op == "filter_agencies":
        # {fy?, measure?, bucket?, top_n?} — the golden "Total" pseudo-agency is
        # a total-level fact, not an agency, so it is excluded from per-agency ops
        rows = [f for f in frame.facts if f["agency_name"].lower() != "total"]
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
        rows = [f for f in frame.facts if f["agency_name"].lower() != "total"]
        if params.get("measure"): rows = [f for f in rows if f["measure"] == params["measure"]]
        if params.get("bucket"): rows = [f for f in rows if f["bucket"] == params["bucket"]]
        return {"basis": basis, "count": len(rows), "total": round(sum(f["value"] for f in rows))}
    if op == "trend":
        # 5-year FY trend from the annual files (quarter is None). A measure
        # with no annual-FY rows (e.g. within_statutory, which only exists as
        # single-quarter Q1 facts) returns an EMPTY series, never a fabricated
        # flat zero line. The golden "Total" pseudo-agency is excluded.
        rows = [f for f in frame.facts if f["quarter"] is None
                and f["measure"] == params.get("measure", "received")
                and f["bucket"] == "total" and f["agency_name"].lower() != "total"]
        if not rows:
            return {"basis": "fy", "years": [], "values": []}
        by = {}
        for f in rows:
            by.setdefault(f["fy"], 0.0)
            by[f["fy"]] += f["value"]
        cats = sorted({f["fy"] for f in frame.facts if f["quarter"] is None})
        return {"basis": "fy", "years": cats,
                "values": [round(by[y]) if y in by else None for y in cats]}
    if op == "compare_period":
        # same-period-previous-year change in a measure
        m = params.get("measure", "received")
        a, b = params.get("fy_a"), params.get("fy_b")
        def tot(fy):
            return sum(f["value"] for f in frame.facts
                       if f["fy"] == fy and f["measure"] == m and f["bucket"] == "total"
                       and f["agency_name"].lower() != "total")  # no golden grand totals
        va, vb = tot(a), tot(b)
        return {"basis": "fy", "fy_a": a, "fy_b": b, "value_a": round(va), "value_b": round(vb),
                "change": round(vb - va),
                "change_pct": round(100 * (vb - va) / va) if va else None}
    if op == "top_contributors":
        return query_dataset(frame, "filter_agencies", params)
    if op == "by_portfolio":
        # the golden "Total" pseudo-agency is a total-level fact, not an agency
        rows = [f for f in frame.facts if f["agency_name"].lower() != "total"]
        if params.get("fy"): rows = [f for f in rows if f["fy"] == params["fy"]]
        if params.get("measure"): rows = [f for f in rows if f["measure"] == params["measure"]]
        if params.get("bucket"): rows = [f for f in rows if f["bucket"] == params["bucket"]]
        mapped = [f for f in rows if f.get("portfolio")]
        unmapped_agencies = {f["agency_name"] for f in rows if not f.get("portfolio")}
        if rows and not mapped:
            # fail-loud: an all-unmapped slice would otherwise collapse into one
            # plausible-looking "Unmapped" bucket (spec S1.1)
            return {"error": "portfolio mapping unavailable for this slice; "
                             "no fact carries a portfolio — re-ingest with the "
                             "banner-row capture normaliser"}
        aggs = {}
        for f in mapped:
            aggs.setdefault(f["portfolio"], 0.0)
            aggs[f["portfolio"]] += f["value"]
        return {"basis": params.get("window_mode", "fy"),
                "unmapped_agency_count": len(unmapped_agencies),
                "portfolios": [{"portfolio": p, "value": round(v)}
                               for p, v in sorted(aggs.items(), key=lambda kv: kv[1], reverse=True)]}
    if op == "kpis":
        # every KPI tile carries its basis — basis is a field of the output.
        #
        # SCALAR-ONLY (I3). A KPI is one number. The ranked movers TABLES
        # (list/dict values) ballooned this payload 17.6KB -> 56.3KB while
        # agentic/builder.py truncates the model-facing tool result at 4000
        # chars — so the model saw none of them, and the legacy
        # refusal_rate_change_fy23_fy24 list (167 rows, ~19KB, key 9 of 12) ate
        # the truncation budget before timeliness_slippage_corr was even
        # reached. Every excluded key stays reachable via foi_stats directly and
        # via GET /api/figures, which carries all of them; the shape of the keys
        # that remain is unchanged ({value, basis}).
        #
        # foi_stats is called ONCE per key — the old comprehension called it
        # twice, so each movers stat (which hashes thousands of rows) was
        # computed four times per kpis call.
        out = {}
        for key in STAT_KEYS:
            try:
                stat = foi_stats(frame, key)
            except KeyError:
                # the catalog's declared "this frame cannot compute this key"
                # signal — the key stays absent, nothing is fabricated. Note
                # what this does NOT guarantee: a genuine KeyError raised inside
                # a stat is indistinguishable from the signal and would drop the
                # key just as quietly. Every other exception type still
                # propagates. Same limitation as api.figures.
                continue
            if isinstance(stat["value"], (list, dict)):
                continue
            out[key] = {"value": stat["value"], "basis": stat["basis"]}
        return out
    if op == "gaps":
        return {"error": "gaps op not applicable to FOI stats — use trend/compare_period/top_contributors"}
    if op == "classes":
        return {"classes": sorted({f["measure_group"] for f in frame.facts})}
    return {"error": f"unknown op {op!r}; allowed: list_agencies, filter_agencies, summarize_agencies, trend, compare_period, top_contributors, by_portfolio, kpis, classes, compute"}


def resolve_citations(spec: dict, transcript: list[dict]) -> dict:
    """Replace {c:job.turn.call.field} pointers with recorded tool-call values.

    transcript entries carry the query_dataset result under 'result'; the
    pointer matches by turn (parts[1]) and walks the field path (parts[3:])
    over that result, supporting bracket indices (top[0].agency). An unknown or
    malformed pointer FAILS LOUD (SystemExit) — never a guessed number.
    """
    def _lookup(path: str):
        parts = path.split(".")
        if len(parts) < 4:
            raise KeyError(f"citation {path}: malformed pointer (need job.turn.call.field)")
        try:
            seq = int(parts[1])
        except ValueError:
            raise KeyError(f"citation {path}: turn is not a number") from None
        for ev in transcript:
            if ev.get("seq") == seq and ev.get("tool") == "query_dataset":
                cur = ev.get("result")
                if not isinstance(cur, (dict, list)):
                    raise KeyError(f"citation {path}: no recorded result")
                # skip the call number (parts[2]); walk the field path parts[3:]
                # over the recorded result, tokenising bracket indices
                for p in parts[3:]:
                    if p.isdigit():
                        idx = int(p)
                        if not isinstance(cur, list) or idx >= len(cur):
                            raise KeyError(f"citation {path}: index {idx} out of range")
                        cur = cur[idx]
                        continue
                    for tok in _FIELD_TOKEN.finditer(p):
                        if tok.group(1) is not None:
                            key = tok.group(1)
                            if not isinstance(cur, dict) or key not in cur:
                                raise KeyError(f"citation {path}: unknown field {key}")
                            cur = cur[key]
                        else:
                            idx = int(tok.group(2))
                            if not isinstance(cur, list) or idx >= len(cur):
                                raise KeyError(f"citation {path}: index {idx} out of range")
                            cur = cur[idx]
                return cur
        raise KeyError(f"citation {path}: unknown transcript entry")

    def _sub(m):
        # str(), not json.dumps(): the substitution happens INSIDE a JSON string
        # literal, so a bare scalar is correct (json.dumps would double-quote).
        return str(_lookup(m.group(1)))

    def _walk(node):
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        if isinstance(node, str):
            try:
                return CITATION_PATTERN.sub(_sub, node)
            except KeyError as e:
                raise SystemExit(f"FAIL LOUD: {e} — a figure could not be resolved") from e
        return node

    return _walk(spec)
