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
    pointer is still recognisable (resolve_citations replaces it with a value).

    `source` is accepted as an alias the model sometimes emits for the figure
    key; it is held to the same enum discipline as `figure`."""
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
    src = p.get("source")
    if src is not None and src not in FIG_KEYS and src not in STAT_KEYS \
            and not (isinstance(src, str) and _CIT_RE.match(src)):
        raise SystemExit(
            f"FAIL LOUD: panel source {src!r} is not a FIG_KEY, STAT_KEY or "
            "{{c:...}} pointer — the model invented a number (never write a digit)")


def _stat_key(p: dict) -> str | None:
    """The catalog key a panel cites, if any. A 'figure' value that is a chart
    type (bar/hbar/line/...) is presentation, not a figure source. `source` is
    accepted as an alias the model sometimes emits for the figure key."""
    for field in ("stat", "figure", "source"):
        key = p.get(field)
        if key in STAT_KEYS or key in FIG_KEYS:
            return key
    return None


def _num(v):
    if isinstance(v, float) and v.is_integer():
        return f"{int(v):,}"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _cell(v) -> str:
    return "—" if v is None else _num(v)


def _fmt(value) -> str:
    """Conservative value rendering: None is never 0, and a figure's missing
    year is '—' not '0' — never mint a number.

    Chart-shaped values ({categories, series}) render as a table with one row
    per category and one column per series, so a top-N figure shows the AGENCY
    NAMES beside their numbers instead of a bare comma list. A movers value
    (rate or volume) renders agency rows with both years and the change. Any
    other dict renders as a key/value table; a bare list of dicts renders the
    shared keys as columns. Nothing is ever dumped as one long JSON line.
    """
    if value is None:
        return "no data"
    if isinstance(value, (int, float)):
        return _num(value)
    if isinstance(value, dict) and "categories" in value and "series" in value:
        cats = value.get("categories") or []
        series = [s for s in value.get("series") or [] if isinstance(s, dict)]
        head = "<tr><th></th>" + "".join(
            f"<th>{html.escape(str(s.get('name') or 'value'))}</th>"
            for s in series) + "</tr>"
        rows = []
        for i, cat in enumerate(cats):
            cells = ""
            for s in series:
                vals = s.get("values") or []
                cells += "<td>" + _cell(vals[i] if i < len(vals) else None) + "</td>"
            rows.append(f"<tr><th>{html.escape(str(cat))}</th>{cells}</tr>")
        return ('<table class="dash-table"><thead>' + head + "</thead><tbody>"
                + "".join(rows) + "</tbody></table>")
    if isinstance(value, dict) and isinstance(value.get("movers"), list):
        movers = value["movers"][:10]
        volume = bool(movers) and "fy_a_value" in movers[0]
        fy_a = html.escape(str(value.get("fy_a") or "fy_a"))
        fy_b = html.escape(str(value.get("fy_b") or "fy_b"))
        head = f"<tr><th>Agency</th><th>{fy_a}</th><th>{fy_b}</th><th>Change</th></tr>"
        rows = []
        for m in movers:
            if not isinstance(m, dict):
                continue
            a = html.escape(str(m.get("agency") or ""))
            if volume:
                rows.append(
                    f"<tr><th>{a}</th><td>{_cell(m.get('fy_a_value'))}</td>"
                    f"<td>{_cell(m.get('fy_b_value'))}</td>"
                    f"<td>{_cell(m.get('change'))}</td></tr>")
            else:
                rows.append(
                    f"<tr><th>{a}</th><td>{_cell(m.get('fy_a_rate'))}</td>"
                    f"<td>{_cell(m.get('fy_b_rate'))}</td>"
                    f"<td>{_cell(m.get('change'))}</td></tr>")
        foot = ""
        if len(value["movers"]) > len(movers):
            foot = (f'<p class="dash-note">Top {len(movers)} of '
                    f'{len(value["movers"])} agencies.</p>')
        return ('<table class="dash-table"><thead>' + head + "</thead><tbody>"
                + "".join(rows) + "</tbody></table>" + foot)
    if isinstance(value, list) and value and all(isinstance(x, dict)
                                                 for x in value[:10]):
        rows = value[:10]
        keys = sorted({k for r in rows for k in r})
        head = "<tr>" + "".join(f"<th>{html.escape(k)}</th>" for k in keys) + "</tr>"
        body = "".join(
            "<tr>" + "".join(
                "<td>" + ("" if r.get(k) is None
                          else html.escape(_num(r[k]) if isinstance(r[k], (int, float))
                                           else str(r[k]))) + "</td>"
                for k in keys) + "</tr>"
            for r in rows)
        return ('<table class="dash-table"><thead>' + head + "</thead><tbody>"
                + body + "</tbody></table>")
    if isinstance(value, dict):
        rows = "".join(
            f"<tr><th>{html.escape(str(k))}</th>"
            f"<td>{html.escape(json.dumps(v, default=str)[:200])}</td></tr>"
            for k, v in sorted(value.items()))
        return f'<table class="dash-table"><tbody>{rows}</tbody></table>'
    return html.escape(json.dumps(value, default=str))


# A small self-contained stylesheet for the dashboard page: it is a bare HTML
# document (not the site chrome), so it carries its own presentable panel and
# table styling instead of depending on site.css or the tailwind build.
_DASH_CSS = (
    "<style>"
    "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;"
    "color:#0f1e33;background:#f6f8fb;max-width:64rem;margin:0 auto;"
    "padding:2rem 1.5rem 3rem;}"
    "h1{font-size:1.6rem;margin:0 0 1.2rem;}"
    "h3{margin:0 0 0.4rem;font-size:1.05rem;}"
    ".panel{background:#fff;border:1px solid #e4eaf2;border-radius:12px;"
    "padding:1rem 1.25rem;margin:0 0 1rem;box-shadow:0 1px 3px rgba(15,30,51,.06);}"
    ".value{font-variant-numeric:tabular-nums;}"
    ".basis{display:inline-block;margin-top:0.5rem;color:#4a5a72;font-size:.8rem;}"
    ".dash-table{width:100%;border-collapse:collapse;margin-top:.6rem;"
    "font-size:.9rem;}"
    ".dash-table th,.dash-table td{border-bottom:1px solid #e4eaf2;"
    "padding:.4rem .6rem;text-align:right;}"
    ".dash-table th:first-child,.dash-table td:first-child,.dash-table thead th{"
    "text-align:left;}"
    ".dash-table thead th{color:#4a5a72;font-weight:600;font-size:.8rem;"
    "text-transform:uppercase;letter-spacing:.02em;}"
    ".dash-note{color:#4a5a72;font-size:.8rem;margin:.4rem 0 0;}"
    "footer{color:#4a5a72;font-size:.8rem;margin-top:2rem;}"
    "a{color:#0787d9;}"
    "</style>"
)


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
    footer = "<footer>Bluebird FOI Insights — Australian Government FOI statistics</footer>"
    if artifact_id is not None:
        footer = (f'<footer><a href="/lineage/{int(artifact_id)}">'
                  "View lineage transcript</a> — Bluebird FOI Insights — "
                  "Australian Government FOI statistics</footer>")
    title = html.escape(str(s.get("title", "FOI dashboard")))
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{title}</title>{_DASH_CSS}</head>"
        f"<body><h1>{title}</h1>{body}{footer}</body></html>"
    )
