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

from stats.dsl import resolve_citations
from stats.catalog import FIG_CAPTIONS, FIG_KEYS, STAT_KEYS, foi_stats


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
