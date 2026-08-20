"""pages — the 12 static Power BI pages, data-backed + basis-labelled.

Every number on a page is a platform-computed figure: render_all_pages computes
from the Frame via stats.catalog.foi_stats — no hardcoded figures, no model
numbers, no LLM, no DB. It is PURE frame → HTML.

Data honesty: a figure that cannot be computed (e.g. the decided/outcome/
timeliness FY series, which the annual files do not publish) renders an honest
"No published data for this measure" placeholder — never a fabricated flat-zero
line. A figure's missing year renders as '—', never '0'. The basis label
(single_quarter | cumulative | fy) rides beside every figure.
"""
from __future__ import annotations
import html
import re
from pathlib import Path

from stats.catalog import foi_stats, FIG_CAPTIONS
from site.templates import chrome

_CORPUS = Path(__file__).resolve().parent.parent.parent / "data" / "corpus"
_DATA_NOTES = _CORPUS / "data-notes.md"

# series colours (validated categorical palette, slots 1-4 — see site.css)
_BAR_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")

# human-readable KPI labels for the STAT_KEYS (the catalog keys are enum
# identifiers, not prose — the page shows a proper label)
_STAT_LABELS = {
    "requests_received_q1": "Requests received",
    "requests_finalised_q1": "Requests finalised",
    "decided_q1": "Requests decided",
    "within_statutory_pct_q1": "Decided within statutory",
    "granted_full_share_q1": "Granted in full",
    "granted_part_share_q1": "Granted in part",
    "refused_share_q1": "Refused",
    "withdrawn_q1": "Withdrawn",
    "refusal_rate_change_fy23_fy24": "Refusal rate, top movers",
    "timeliness_slippage_corr": "Timeliness slippage correlation",
}

# human-readable basis labels — printed beside every figure
_BASIS_LABEL = {
    "single_quarter": "basis: single quarter",
    "cumulative": "basis: cumulative",
    "fy": "basis: financial year",
}

def _stat(frame, key):
    """foi_stats with a guarded accessor — a missing key is a programming error
    (the model can only cite catalog keys), not a silently missing figure."""
    return foi_stats(frame, key)


def _basis_label(stat):
    return _BASIS_LABEL.get(stat.get("basis", ""), stat.get("basis", ""))


def _num(value) -> str:
    """Format a scalar as a human-readable number (1,235.0 -> '1,235')."""
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _series_label(fig, series):
    """A series gets its name only when the figure carries more than one series
    (a single-series line names itself in the caption)."""
    if len(fig.get("series", [])) > 1:
        return html.escape(str(series.get("name", "")))
    return ""


def _chart(fig, height="chart-h") -> str:
    """Render a figure as an inline HTML/CSS bar chart. A missing year is '—'
    (never 0); an empty series shows an honest no-data placeholder instead of a
    fabricated flat-zero line."""
    series = fig.get("series") or []
    if not series or not any(s.get("values") for s in series):
        return ('<div class="nodata">No published data for this measure. '
                'The source files do not report this breakdown for the '
                'financial years covered.</div>')
    cats = fig.get("categories") or []
    # scale bars to the largest value in the figure, not to a fixed cap — so a
    # 42,759 bar reads taller than a 33,630 bar, and a 1,426 bar is clearly
    # smaller than a 3,968 bar
    data_max = max((v for s in series for v in (s.get("values") or [])
                    if v is not None), default=None)
    row_idx = 0
    cells = []
    for i, s in enumerate(series):
        name = _series_label(fig, s)
        values = s.get("values") or []
        for j, v in enumerate(values):
            cells.append(_bar(cats[j] if j < len(cats) else "", name, v,
                              _BAR_COLOURS[i % len(_BAR_COLOURS)], row_idx,
                              data_max))
            row_idx += 1
    return f'<div class="chart {height}">{chr(10).join(cells)}</div>'


def _bar(cat, name, v, colour, row_idx, data_max=None):
    """One bar (data-end, value label, category label). A None year is '—', never
    0; a zero value (a genuine published 0, not a missing figure) renders '0'.
    Bars are scaled to the figure's largest value (data_max), so proportions
    reflect the data."""
    if v is None:
        val_label = "—"
        height_pct = 0
        bar = '<div class="bar-end none" aria-label="no data"></div>'
        tip = f"{cat}: no data"
    else:
        val_label = _num(v)
        # 100px = the largest value in the figure; smaller values are shorter
        height_pct = (100 * float(v) / data_max) if data_max else 0
        bar = (f'<div class="bar-end" style="height:{height_pct:.0f}px" '
               f'aria-label="{cat}: {val_label}"></div>')
        tip = f"{cat}: {val_label}"
    return (f'<div class="bar-row" data-row="{row_idx}" title="{html.escape(tip)}">'
            f'{bar}<span class="bval">{val_label}</span>'
            f'<span class="bcat">{html.escape(str(cat))}</span>'
            f'{("<span class=\"bseries\">" + name + "</span>") if name else ""}'
            f'</div>')


def _kpi(label, value_html, basis=None, title=None) -> str:
    """A KPI tile: label, value, and the basis label when one is available."""
    basis_html = f'<span class="basis">{html.escape(str(basis))}</span>' if basis else ""
    title_html = f'<span class="tlabel">{html.escape(str(title))}</span>' if title else ""
    return (f'<div class="kpi">{title_html}<span class="label">{label}</span>'
            f'<span class="value">{value_html}</span>{basis_html}</div>')


def _kpis(frame, keys) -> str:
    cells = []
    for key in keys:
        stat = _stat(frame, key)
        value = stat.get("value")
        if value is None:
            value_html = "No published data"
            basis = None
        elif isinstance(value, (int, float)):
            value_html = _num(value)
            basis = _basis_label(stat)
        else:
            value_html = html.escape(str(value))
            basis = _basis_label(stat)
        cells.append(_kpi(_STAT_LABELS.get(key, key.replace("_", " ")),
                          value_html, basis))
    return f'<div class="kpis">{chr(10).join(cells)}</div>'


def _trend_section(title, fig) -> str:
    basis = _basis_label({"basis": "fy"})
    return (f'<section class="figure-card"><h2>{html.escape(str(title))}</h2>'
            f'<p class="basis">{basis}</p>{_chart(fig)}</section>')


def _top20_section(title, fig) -> str:
    basis = _basis_label({"basis": "fy"})
    return (f'<section class="figure-card"><h2>{html.escape(str(title))}</h2>'
            f'<p class="basis">{basis}</p>{_chart(fig, height="chart-h-tall")}'
            f'</section>')


def _notes_section(title, fig) -> str:
    """A dedicated note under a chart when the figure's series are empty (the
    annual files do not publish the measure) — states WHY there is no data,
    so the empty chart reads as honest, not broken."""
    return (f'<section class="figure-card"><h2>{html.escape(str(title))}</h2>'
            f'<p class="note">No published data for this measure. The annual '
            f'FOI files report only requests received and finalised per '
            f'financial year; this breakdown is not published on a yearly '
            f'basis.</p>{_chart(fig)}</section>')


def _lineage_panel(artifact) -> str:
    return (f'<p class="lineage"><a href="/lineage/{artifact}">'
            f'View lineage for this dashboard</a></p>')


# --- the 12 pages ------------------------------------------------------------


def _page_at_a_glance(frame) -> str:
    g = lambda k: _stat(frame, k)
    kpis = _kpis(frame, [
        "requests_received_q1", "requests_finalised_q1", "decided_q1",
        "within_statutory_pct_q1", "granted_full_share_q1",
        "granted_part_share_q1", "refused_share_q1", "withdrawn_q1",
    ])
    kpis += ("<div class=\"kpis\">"
             + _kpi("Granted full / part / refused (share of decisions)",
                    f"{g('granted_full_share_q1')['value']}/{g('granted_part_share_q1')['value']}/{g('refused_share_q1')['value']}%",
                    _basis_label(g('granted_full_share_q1')))
             + "</div>")
    body = f"""
    <h1>FOI at a glance</h1>
    <p class="intro">Freedom of Information (FOI) activity by Australian
    Government agencies and ministers — latest published quarter (Q1
    2025-26). All figures are computed from the source data.</p>
    {kpis}
    <div class="filters">Filters: portfolio / agency · type (personal/other) · FY or quarter</div>
    <section class="figure-card"><h2>Requests received, FY trend</h2>
    <p class="basis">basis: financial year</p>
    {_chart(g('requests_received_trend')['value'])}</section>
    {_lineage_panel("at-a-glance")}"""
    return chrome("FOI at a glance", "Freedom of information", body)


def _page_requests_received(frame) -> str:
    fig = _stat(frame, "requests_received_trend")["value"]
    body = f"""
    <h1>Requests received</h1>
    <p class="intro">FOI requests received by Australian Government agencies and
    ministers, by financial year.</p>
    {_kpis(frame, ["requests_received_q1"])}
    {_trend_section(FIG_CAPTIONS["requests_received_trend"], fig)}
    {_lineage_panel("requests-received")}"""
    return chrome("Requests received", "Freedom of information", body)


def _page_key_agency_contributions_received(frame) -> str:
    fig = _stat(frame, "received_top20")["value"]
    body = f"""
    <h1>Key agency contributions — requests received</h1>
    <p class="intro">Top 20 agencies by FOI requests received in FY2024-25
    (the latest complete financial year in the annual files).</p>
    {_top20_section(FIG_CAPTIONS["received_top20"], fig)}
    {_lineage_panel("key-agency-contributions-received")}"""
    return chrome("Key agency contributions — requests received",
                  "Freedom of information", body)


def _page_requests_finalised(frame) -> str:
    fig = _stat(frame, "requests_finalised_trend")["value"]
    body = f"""
    <h1>Requests finalised</h1>
    <p class="intro">FOI requests finalised by Australian Government agencies
    and ministers, by financial year.</p>
    {_kpis(frame, ["requests_finalised_q1"])}
    {_trend_section(FIG_CAPTIONS["requests_finalised_trend"], fig)}
    {_lineage_panel("requests-finalised")}"""
    return chrome("Requests finalised", "Freedom of information", body)


def _page_requests_decided(frame) -> str:
    fig = _stat(frame, "requests_decided_trend")["value"]
    body = f"""
    <h1>Requests decided</h1>
    <p class="intro">FOI requests decided by Australian Government agencies and
    ministers. The annual files do not publish decisions by financial year, so
    this page reports the latest published quarter.</p>
    {_kpis(frame, ["decided_q1"])}
    {_notes_section(FIG_CAPTIONS["requests_decided_trend"], fig)}
    {_lineage_panel("requests-decided")}"""
    return chrome("Requests decided", "Freedom of information", body)


def _page_key_agency_contributions_decided(frame) -> str:
    fig = _stat(frame, "decided_top20")["value"]
    body = f"""
    <h1>Key agency contributions — requests decided</h1>
    <p class="intro">Top 20 agencies by FOI requests decided in FY2024-25.
    Decisions by financial year are not published in the annual files, so this
    figure is empty until the source data reports them.</p>
    {_top20_section(FIG_CAPTIONS["decided_top20"], fig)}
    {_lineage_panel("key-agency-contributions-decided")}"""
    return chrome("Key agency contributions — requests decided",
                  "Freedom of information", body)


def _page_decision_outcomes(frame) -> str:
    fig = _stat(frame, "decision_outcomes_trend")["value"]
    body = f"""
    <h1>Decision outcomes</h1>
    <p class="intro">Outcomes of decisions on FOI requests: granted in full,
    granted in part, refused, and withdrawn. The annual files report only
    requests received and finalised by financial year, so outcome series are
    not published on a yearly basis.</p>
    {_kpis(frame, ["granted_full_share_q1", "granted_part_share_q1",
                   "refused_share_q1", "withdrawn_q1"])}
    {_notes_section(FIG_CAPTIONS["decision_outcomes_trend"], fig)}
    {_lineage_panel("decision-outcomes")}"""
    return chrome("Decision outcomes", "Freedom of information", body)


def _page_change_decision_outcomes(frame) -> str:
    fig = _stat(frame, "granted_full_part_change")["value"]
    body = f"""
    <h1>Change in decision outcomes</h1>
    <p class="intro">Change in the percentage of decisions granted in full or
    in part, by financial year.</p>
    {_notes_section(FIG_CAPTIONS["granted_full_part_change"], fig)}
    {_lineage_panel("change-decision-outcomes")}"""
    return chrome("Change in decision outcomes", "Freedom of information", body)


def _page_timeliness(frame) -> str:
    fig = _stat(frame, "timeliness_trend")["value"]
    body = f"""
    <h1>Timeliness</h1>
    <p class="intro">Timeliness of decisions on FOI requests: within or after
    the statutory time period. Only the within-statutory measure is published,
    and not on a financial-year basis in the annual files.</p>
    {_kpis(frame, ["within_statutory_pct_q1"])}
    {_notes_section(FIG_CAPTIONS["timeliness_trend"], fig)}
    {_lineage_panel("timeliness")}"""
    return chrome("Timeliness", "Freedom of information", body)


def _page_change_timeliness(frame) -> str:
    fig = _stat(frame, "timeliness_change")["value"]
    body = f"""
    <h1>Change in timeliness</h1>
    <p class="intro">Change in the percentage of decisions within the statutory
    time period, by financial year.</p>
    {_notes_section(FIG_CAPTIONS["timeliness_change"], fig)}
    {_lineage_panel("change-timeliness")}"""
    return chrome("Change in timeliness", "Freedom of information", body)


def _page_data_notes() -> str:
    """Render data/corpus/data-notes.md VERBATIM — the definitional authority
    (Data notes + disclaimer) is never paraphrased."""
    try:
        notes = _DATA_NOTES.read_text(encoding="utf-8")
    except OSError:
        notes = ("# Data notes and disclaimer\n\n"
                 "The data notes document is missing from the corpus.")
    body = ("<h1>Data notes and disclaimer</h1>"
            f'<div class="notes">{_md(notes)}</div>')
    return chrome("Data notes and disclaimer", "Freedom of information", body)


def _page_how_to_use() -> str:
    body = """
    <h1>How to use</h1>
    <p class="intro">The 12 FOI Insights pages are built from the source data
    published on data.gov.au (OAIC FOI statistics). Every figure is computed
    from that data by the platform — no figure is typed in by hand — and every
    figure carries a basis label so you can tell what window it covers.</p>
    <h2>Reading the basis labels</h2>
    <ul>
      <li><strong>basis: single quarter</strong> — a figure for one published
      quarter (the current snapshot is Q1 2025-26).</li>
      <li><strong>basis: cumulative</strong> — a figure for a cumulative
      quarter window (e.g. Q1-Q3 within a financial year).</li>
      <li><strong>basis: financial year</strong> — a figure for a complete
      financial year (July-June).</li>
    </ul>
    <h2>Missing data is shown, not invented</h2>
    <p>Where the source files do not publish a measure (for example, decisions
    or decision outcomes by financial year), the page shows
    <em>No published data for this measure</em> — a flat zero line would be a
    fabricated number. A year without a figure in a series renders as "—".</p>
    <h2>Filters</h2>
    <p>The filters row (portfolio / agency · type (personal/other) · FY or
    quarter) is the drill-down surface. In this static POC the pages render
    the full dataset; the filters become live in the interactive build.</p>
    <h2>Data notes</h2>
    <p>The <a href="/data-notes.html">Data notes and disclaimer</a> page carries
    the OAIC's definitional notes verbatim.</p>
    """
    return chrome("How to use", "Freedom of information", body)


def _md(text: str) -> str:
    """Minimal markdown → HTML: escape, then wrap blank-line-separated
    paragraphs; keep headings and simple lists readable."""
    esc = html.escape(text)
    esc = esc.replace("\xa0", " ")          # NBSP in the corpus → plain space
    blocks = []
    for raw in re.split(r"\n\s*\n", esc):
        block = raw.strip()
        if not block:
            continue
        if block.startswith("&gt;"):            # a blockquote line
            blocks.append(f"<blockquote>{block[4:]}</blockquote>")
            continue
        if block.startswith("# "):              # h1
            blocks.append(f"<h1>{block[2:]}</h1>")
            continue
        if block.startswith("## "):             # h2
            blocks.append(f"<h2>{block[3:]}</h2>")
            continue
        if all(ln.startswith("&lt;") for ln in block.splitlines()):  # list
            items = "".join(
                f"<li>{ln[4:]}</li>" for ln in block.splitlines()
                if ln.startswith("&lt;"))
            blocks.append(f"<ul>{items}</ul>")
            continue
        # paragraphs: hard breaks ("  \n") become <br>; soft line breaks
        # (single newline, the corpus's hard-wrapped source lines) collapse to
        # a space — content stays verbatim, only line-wrapping normalises
        segs = [s.replace("\n", " ").strip() for s in re.split(r"  \n", block)]
        blocks.append("<p>" + "<br>".join(s for s in segs if s) + "</p>")
    return "\n".join(blocks)


def render_all_pages(frame) -> dict[str, str]:
    """Render the 12 static pages from the Frame. PURE frame → HTML: no LLM,
    no DB. Returns {page-name: full-HTML-document}."""
    pages = {
        "at-a-glance": _page_at_a_glance(frame),
        "requests-received": _page_requests_received(frame),
        "key-agency-contributions-received": _page_key_agency_contributions_received(frame),
        "requests-finalised": _page_requests_finalised(frame),
        "requests-decided": _page_requests_decided(frame),
        "key-agency-contributions-decided": _page_key_agency_contributions_decided(frame),
        "decision-outcomes": _page_decision_outcomes(frame),
        "change-decision-outcomes": _page_change_decision_outcomes(frame),
        "timeliness": _page_timeliness(frame),
        "change-timeliness": _page_change_timeliness(frame),
        "data-notes": _page_data_notes(),
        "how-to-use": _page_how_to_use(),
    }
    return pages
