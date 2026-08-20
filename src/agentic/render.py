"""render — turn a spec into a self-contained HTML dashboard page.

Citation pointers {c:<job>.<turn>.<call>.<field>} resolve against the recorded
transcript via the CANONICAL resolver in stats.dsl (imported here, never
duplicated); an unknown key FAILS LOUD (SystemExit) — never a guessed number.

Every printed number is computed by the platform from the frame via foi_stats
(the agent never writes a digit), and every figure carries its basis label
(single_quarter | cumulative | fy). A compare_period zero-base result is never
read as "no requests decided" — the renderer computes the real value from the
frame, it does not copy transcript results into the page.
"""
from __future__ import annotations
import html
import json
import re

from stats.dsl import resolve_citations
from stats.catalog import FIG_CAPTIONS, FIG_KEYS, STAT_KEYS, foi_stats

# a panel's "figure" is either a FIG_KEYS source OR a chart type (presentation)
_CHART_TYPES = ("bar", "hbar", "line", "area", "pie", "table", "kpi")
# a full {c:job.turn.call.field} citation pointer (the sanctioned way to reference
# a number — resolve_citations replaces it with the recorded value)
_CIT_RE = re.compile(r"^\{c:[\w.\[\]]+\}$")


def _check_no_hallucinated_number(p: dict) -> None:
    """M4: the model is forbidden from writing digits. A panel's stat/figure must
    be an enum key, a chart type (figure only), or a {c:...} citation pointer. A
    value that is none of those (e.g. a literal "12345") is a hallucinated number
    and FAILS LOUD — never rendered. Runs on the ORIGINAL spec so a citation
    pointer is still recognisable (resolve_citations replaces it with a value)."""
    stat = p.get("stat")
    if stat is not None and stat not in STAT_KEYS \
            and not (isinstance(stat, str) and _CIT_RE.match(stat)):
        raise SystemExit(
            f"FAIL LOUD: panel stat {stat!r} is not a STAT_KEY or {{c:...}} pointer "
            "— the model invented a number (never write a digit)")
    fig = p.get("figure")
    if fig is not None and fig not in FIG_KEYS and fig not in _CHART_TYPES \
            and not (isinstance(fig, str) and _CIT_RE.match(fig)):
        raise SystemExit(
            f"FAIL LOUD: panel figure {fig!r} is not a chart type, FIG_KEY or "
            "{{c:...}} pointer — the model invented a number (never write a digit)")


def _stat_key(p: dict) -> str | None:
    """The catalog key a panel cites, if any. A 'figure' value that is a chart
    type (bar/hbar/line/...) is presentation, not a figure source."""
    key = p.get("stat") or p.get("figure")
    if key in STAT_KEYS or key in FIG_KEYS:
        return key
    return None


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _fmt(value) -> str:
    """Conservative value rendering: None is never 0, and a figure's missing
    year is '—' not '0' — never mint a number."""
    if value is None:
        return "no data"
    if isinstance(value, (int, float)):
        return _num(value)
    if isinstance(value, dict) and "categories" in value and "series" in value:
        rows = []
        for s in value["series"]:
            vals = ", ".join(
                "—" if v is None else _num(v) for v in s.get("values", []))
            rows.append(f"{html.escape(str(s.get('name', '')))}: {vals}")
        return "<br>".join(rows)
    return html.escape(json.dumps(value, default=str))


def render_dashboard_page(spec, frame, artifact_id, transcript) -> str:
    """Self-contained HTML page for a built dashboard spec.

    Unknown citation pointers FAIL LOUD (SystemExit from resolve_citations).
    Panel numbers are computed from the frame; basis labels ride beside them.
    artifact_id renders a lineage link when one exists.
    """
    for p in spec.get("panels", []):
        _check_no_hallucinated_number(p)
    s = resolve_citations(spec, transcript)
    panels = []
    for i, p in enumerate(s.get("panels", [])):
        title = p.get("title") or FIG_CAPTIONS.get(p.get("figure", ""), f"Panel {i + 1}")
        value_html = "&nbsp;"
        basis = p.get("basis")
        key = _stat_key(p)
        if key is not None:
            stat = foi_stats(frame, key)
            value_html = _fmt(stat.get("value"))
            basis = stat.get("basis") or basis
        basis_html = (f'<span class="basis">{html.escape(str(basis))}</span>'
                      if basis else "")
        panels.append(
            f'<section class="panel"><h3>{html.escape(str(title))}</h3>'
            f'<div class="value">{value_html}</div>{basis_html}'
            f'<div id="c{i}" class="chart"></div></section>')
    body = "\n".join(panels)
    footer = "<footer>FOI Insights — Australian Government FOI statistics</footer>"
    if artifact_id is not None:
        footer = (f'<footer><a href="/lineage/{int(artifact_id)}">'
                  "View lineage transcript</a> — FOI Insights — "
                  "Australian Government FOI statistics</footer>")
    title = html.escape(str(s.get("title", "FOI dashboard")))
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{title}</title></head>"
        f"<body><h1>{title}</h1>{body}{footer}</body></html>"
    )
