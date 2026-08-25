"""pages — the 12 static Power BI pages, data-backed + basis-labelled.

Every number on a page is a platform-computed figure: render_all_pages computes
from the Frame via stats.catalog.foi_stats — no hardcoded figures, no model
numbers, no LLM, no DB. It is PURE frame → HTML.

Data honesty: a figure that cannot be computed (a measure the source files do
not publish) renders an honest "No published data for this measure" placeholder
— never a fabricated flat-zero line. A figure's missing year renders as '—',
never '0'. The basis label (single_quarter | cumulative | fy) rides beside every
figure.
"""
from __future__ import annotations
import html
import json
import re
from pathlib import Path

from stats.catalog import foi_stats, FIG_CAPTIONS
from site.templates import chrome

_CORPUS = Path(__file__).resolve().parent.parent.parent / "data" / "corpus"
_DATA_NOTES = _CORPUS / "data-notes.md"

# script tags every chart page loads, rendered before </body> by chrome()
_CHART_SCRIPTS = ('<script src="/assets/echarts.common.min.js"></script>\n'
                  '<script src="/assets/foi-charts.js"></script>')

# page_key -> the figure keys that page's chartboxes reference (the keys the
# page's window.__pageData blob ships). Pages without charts ship no figures.
PAGE_FIGURE_KEYS = {
    "at-a-glance": ["requests_received_trend"],
    "requests-received": ["requests_received_trend"],
    "key-agency-contributions-received": ["received_top20"],
    "requests-finalised": ["requests_finalised_trend"],
    "requests-decided": ["requests_decided_trend"],
    "key-agency-contributions-decided": ["decided_top20"],
    "decision-outcomes": ["decision_outcomes_trend"],
    "change-decision-outcomes": ["granted_full_part_change"],
    "timeliness": ["timeliness_trend"],
    "change-timeliness": ["timeliness_change"],
    "data-notes": [],
    "how-to-use": [],
    "api": [],
}

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


def _chart_container(chart_key, fig) -> str:
    """A mount point for an ECharts figure. The chart itself is rendered by
    foi-charts.js (Task 3) from window.__pageData.figures[chart_key].

    A figure with no published data keeps the honest server-rendered
    placeholder inside the same chartbox — so the page reads as "no data",
    not broken, even before any JS runs. The placeholder text matches the old
    inline `_chart` no-data copy verbatim."""
    inner = ""
    if not _figure_has_data(fig):
        inner = ('<div class="nodata">No published data for this measure. '
                 'The source files do not report this breakdown for the '
                 'financial years covered.</div>')
    return (f'<div class="chartbox" id="chart-{chart_key}" '
            f'data-figure="{chart_key}">{inner}</div>')


def _figure_has_data(fig) -> bool:
    series = fig.get("series") or []
    return any(s.get("values") for s in series)


def _filters_blob(frame) -> dict:
    """Platform-derived filter options, straight off the Frame — no new
    aggregates. Task 4 wires the real filter behaviour; this ships only what
    the source data itself distinguishes."""
    return {
        "agencies": sorted({f["agency_name"] for f in frame.facts}),
        "types": sorted({f["bucket"] for f in frame.facts}),
        "fys": sorted({f["fy"] for f in frame.facts}),
    }


# pages that carry a live filter bar. The four data pages all compute their
# figures from the facts, so a live filter can re-select them. The other chart
# pages (requests-decided / key-agency-contributions-decided / decision-outcomes
# / change-decision-outcomes / timeliness / change-timeliness) now render real
# FY series too, but the filter bar is deliberately scoped to these four pages —
# the rest render without one.
_FILTER_PAGES = frozenset({
    "at-a-glance",
    "requests-received",
    "key-agency-contributions-received",
    "requests-finalised",
})


def _filters_bar(frame, page_key) -> str:
    """The live-filter dropdowns (Agency / Type / FY) for the data pages. The
    selects carry data-filter="agency|type|fy" so foi-charts.js can read them;
    class names are static literals so Tailwind's content scan compiles them.
    Returns "" for pages outside _FILTER_PAGES — the filter bar is scoped to
    those four pages."""
    if page_key not in _FILTER_PAGES:
        return ""
    f = _filters_blob(frame)
    types = set(f["types"])

    def _select(label, filter_name, options, all_label):
        opts = [f'<option value="">{html.escape(all_label)}</option>']
        opts += [f'<option value="{html.escape(str(v))}">{html.escape(str(v))}</option>'
                 for v in options]
        return (f'<label class="flex items-center gap-2 text-sm text-ink-2" '
                f'for="filter-{filter_name}">{html.escape(label)}'
                f'<select data-filter="{filter_name}" id="filter-{filter_name}" '
                f'class="filter-select text-sm">{chr(10).join(opts)}</select></label>')

    agency = _select("Agency", "agency", f["agencies"], "All agencies")
    # the type options are the platform's own buckets; "total" is a valid
    # selection — it is the bucket every figure is derived from
    type_opts = [t for t in ("personal", "other", "total") if t in types]
    typ = _select("Type", "type", type_opts, "All types")
    fy = _select("FY", "fy", f["fys"], "All FYs")
    return (f'<div class="filters flex flex-wrap items-center gap-3" '
            f'role="group" aria-label="Filter the charts">{agency}{typ}{fy}</div>')


def _page_data_script(frame, page_key) -> str:
    """The window.__pageData blob for one page: the foi_stats results for the
    page's figure keys, the canonical long-form facts (frame.facts, verbatim),
    and the platform-derived filter options. PURE frame -> JSON — no fabricated
    figures, no new aggregates. The live filters select/re-group
    window.__pageData.facts only; they never sum into a total the platform did
    not derive.

    SECURITY: the JSON is escaped so a source value cannot break out of its
    <script> tag. json.dumps does NOT escape "</" (it serialises it verbatim),
    so the .replace("</", "<\\/") below is the ONLY guard against script-tag
    breakout. "--" is also escaped to \\u002d\\u002d so a source value cannot
    form an HTML comment boundary (<!-- / -->) inside the blob."""
    figures = {k: _stat(frame, k) for k in PAGE_FIGURE_KEYS.get(page_key, [])}
    blob = {"figures": figures, "facts": frame.facts, "filters": _filters_blob(frame)}
    safe = (json.dumps(blob).replace("</", "<\\/")
            .replace("--", "\\u002d\\u002d"))
    return f"<script>window.__pageData = {safe};</script>"


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
               f'aria-label="{html.escape(str(cat))}: {val_label}"></div>')
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


def _trend_section(title, fig, chart_key) -> str:
    basis = _basis_label({"basis": "fy"})
    return (f'<section class="figure-card"><h2>{html.escape(str(title))}</h2>'
            f'<p class="basis">{basis}</p>'
            f'{_chart_container(chart_key, fig)}</section>')


def _top20_section(title, fig, chart_key) -> str:
    basis = _basis_label({"basis": "fy"})
    return (f'<section class="figure-card"><h2>{html.escape(str(title))}</h2>'
            f'<p class="basis">{basis}</p>'
            f'{_chart_container(chart_key, fig)}</section>')


def _notes_section(title, fig, chart_key) -> str:
    """The figure card for a chart page. A note is emitted only when the
    figure's series are empty — the source files do not report the measure —
    so the empty chart reads as honest, not broken. A figure with data carries
    the chart itself, so no note is needed."""
    note = ""
    if not _figure_has_data(fig):
        note = ('<p class="note">No published data for this measure. '
                'The source files do not report this breakdown for the '
                'financial years covered.</p>')
    return (f'<section class="figure-card"><h2>{html.escape(str(title))}</h2>'
            f'<p class="basis">{_basis_label({"basis": "fy"})}</p>'
            f'{note}{_chart_container(chart_key, fig)}</section>')


def _lineage_panel(artifact) -> str:
    return (f'<p class="lineage"><a href="/lineage/{artifact}">'
            f'View lineage for this dashboard</a></p>')


# --- the 12 pages ------------------------------------------------------------


def _q1_total(frame, measure) -> str:
    """Raw single-quarter Q1 2025-26 total for a measure, computed from the
    canonical facts — the published figure rendered directly, never hardcoded."""
    rows = frame.filter(fy="2025-26", quarter=1, measure=measure, bucket="total")
    return _num(round(sum(f["value"] for f in rows), 0))


def _page_at_a_glance(frame) -> str:
    g = lambda k: _stat(frame, k)
    basis_sq = _basis_label(g("requests_received_q1"))
    share = lambda k: f"{g(k)['value']}% of decisions"
    kpis = ("<div class=\"kpis\">"
            + _kpi("Requests received", _q1_total(frame, "received"), basis_sq)
            + _kpi("Requests finalised", _q1_total(frame, "finalised"), basis_sq)
            + _kpi("Requests decided", _q1_total(frame, "decided"), basis_sq)
            + _kpi("Decided within statutory", _q1_total(frame, "within_statutory"),
                   basis_sq, title=share("within_statutory_pct_q1"))
            + _kpi("Granted in full", _q1_total(frame, "granted_full"), basis_sq,
                   title=share("granted_full_share_q1"))
            + _kpi("Granted in part", _q1_total(frame, "granted_part"), basis_sq,
                   title=share("granted_part_share_q1"))
            + _kpi("Refused", _q1_total(frame, "refused"), basis_sq,
                   title=share("refused_share_q1"))
            + _kpi("Withdrawn", _q1_total(frame, "withdrawn"), basis_sq)
            + "</div>")
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
    {_filters_bar(frame, "at-a-glance")}
    {_trend_section("Requests received, FY trend",
                    g('requests_received_trend')['value'],
                    "requests_received_trend")}
    {_lineage_panel("at-a-glance")}
    {_page_data_script(frame, "at-a-glance")}"""
    return chrome("FOI at a glance", body,
                  page_key="at-a-glance", scripts=_CHART_SCRIPTS)


def _page_requests_received(frame) -> str:
    fig = _stat(frame, "requests_received_trend")["value"]
    body = f"""
    <h1>Requests received</h1>
    <p class="intro">FOI requests received by Australian Government agencies and
    ministers, by financial year.</p>
    {_filters_bar(frame, "requests-received")}
    {_kpis(frame, ["requests_received_q1"])}
    {_trend_section(FIG_CAPTIONS["requests_received_trend"], fig,
                    "requests_received_trend")}
    {_lineage_panel("requests-received")}
    {_page_data_script(frame, "requests-received")}"""
    return chrome("Requests received", body,
                  page_key="requests-received", scripts=_CHART_SCRIPTS)


def _page_key_agency_contributions_received(frame) -> str:
    fig = _stat(frame, "received_top20")["value"]
    body = f"""
    <h1>Key agency contributions — requests received</h1>
    <p class="intro">Top 20 agencies by FOI requests received in FY2024-25
    (the latest complete financial year in the annual files).</p>
    {_filters_bar(frame, "key-agency-contributions-received")}
    {_top20_section(FIG_CAPTIONS["received_top20"], fig, "received_top20")}
    {_lineage_panel("key-agency-contributions-received")}
    {_page_data_script(frame, "key-agency-contributions-received")}"""
    return chrome("Key agency contributions — requests received",
                  body,
                  page_key="key-agency-contributions-received",
                  scripts=_CHART_SCRIPTS)


def _page_requests_finalised(frame) -> str:
    fig = _stat(frame, "requests_finalised_trend")["value"]
    body = f"""
    <h1>Requests finalised</h1>
    <p class="intro">FOI requests finalised by Australian Government agencies
    and ministers, by financial year.</p>
    {_filters_bar(frame, "requests-finalised")}
    {_kpis(frame, ["requests_finalised_q1"])}
    {_trend_section(FIG_CAPTIONS["requests_finalised_trend"], fig,
                    "requests_finalised_trend")}
    {_lineage_panel("requests-finalised")}
    {_page_data_script(frame, "requests-finalised")}"""
    return chrome("Requests finalised", body,
                  page_key="requests-finalised", scripts=_CHART_SCRIPTS)


def _page_requests_decided(frame) -> str:
    fig = _stat(frame, "requests_decided_trend")["value"]
    body = f"""
    <h1>Requests decided</h1>
    <p class="intro">FOI requests decided by Australian Government agencies and
    ministers, by financial year, alongside the latest published quarter.</p>
    {_kpis(frame, ["decided_q1"])}
    {_notes_section(FIG_CAPTIONS["requests_decided_trend"], fig,
                    "requests_decided_trend")}
    {_lineage_panel("requests-decided")}
    {_page_data_script(frame, "requests-decided")}"""
    return chrome("Requests decided", body,
                  page_key="requests-decided", scripts=_CHART_SCRIPTS)


def _page_key_agency_contributions_decided(frame) -> str:
    fig = _stat(frame, "decided_top20")["value"]
    body = f"""
    <h1>Key agency contributions — requests decided</h1>
    <p class="intro">Top 20 agencies by FOI requests decided in the latest
    complete financial year in the annual files.</p>
    {_top20_section(FIG_CAPTIONS["decided_top20"], fig, "decided_top20")}
    {_lineage_panel("key-agency-contributions-decided")}
    {_page_data_script(frame, "key-agency-contributions-decided")}"""
    return chrome("Key agency contributions — requests decided",
                  body,
                  page_key="key-agency-contributions-decided",
                  scripts=_CHART_SCRIPTS)


def _page_decision_outcomes(frame) -> str:
    fig = _stat(frame, "decision_outcomes_trend")["value"]
    body = f"""
    <h1>Decision outcomes</h1>
    <p class="intro">Outcomes of decisions on FOI requests: granted in full,
    granted in part, refused, and withdrawn, by financial year.</p>
    {_kpis(frame, ["granted_full_share_q1", "granted_part_share_q1",
                   "refused_share_q1", "withdrawn_q1"])}
    {_notes_section(FIG_CAPTIONS["decision_outcomes_trend"], fig,
                    "decision_outcomes_trend")}
    {_lineage_panel("decision-outcomes")}
    {_page_data_script(frame, "decision-outcomes")}"""
    return chrome("Decision outcomes", body,
                  page_key="decision-outcomes", scripts=_CHART_SCRIPTS)


def _page_change_decision_outcomes(frame) -> str:
    fig = _stat(frame, "granted_full_part_change")["value"]
    body = f"""
    <h1>Change in decision outcomes</h1>
    <p class="intro">Change in the percentage of decisions granted in full or
    in part, by financial year.</p>
    {_notes_section(FIG_CAPTIONS["granted_full_part_change"], fig,
                    "granted_full_part_change")}
    {_lineage_panel("change-decision-outcomes")}
    {_page_data_script(frame, "change-decision-outcomes")}"""
    return chrome("Change in decision outcomes", body,
                  page_key="change-decision-outcomes", scripts=_CHART_SCRIPTS)


def _page_timeliness(frame) -> str:
    fig = _stat(frame, "timeliness_trend")["value"]
    body = f"""
    <h1>Timeliness</h1>
    <p class="intro">Timeliness of decisions on FOI requests: the share of
    decisions made within the statutory time period, by financial year. Only
    the within-statutory measure is published in the source files; the
    after-statutory buckets are not ingested.</p>
    {_kpis(frame, ["within_statutory_pct_q1"])}
    {_notes_section(FIG_CAPTIONS["timeliness_trend"], fig, "timeliness_trend")}
    {_lineage_panel("timeliness")}
    {_page_data_script(frame, "timeliness")}"""
    return chrome("Timeliness", body,
                  page_key="timeliness", scripts=_CHART_SCRIPTS)


def _page_change_timeliness(frame) -> str:
    fig = _stat(frame, "timeliness_change")["value"]
    body = f"""
    <h1>Change in timeliness</h1>
    <p class="intro">Change in the percentage of decisions within the statutory
    time period, by financial year.</p>
    {_notes_section(FIG_CAPTIONS["timeliness_change"], fig, "timeliness_change")}
    {_lineage_panel("change-timeliness")}
    {_page_data_script(frame, "change-timeliness")}"""
    return chrome("Change in timeliness", body,
                  page_key="change-timeliness", scripts=_CHART_SCRIPTS)


def _page_data_notes() -> str:
    """Render data/corpus/data-notes.md VERBATIM — the definitional authority
    (Data notes + disclaimer) is never paraphrased."""
    try:
        notes = _DATA_NOTES.read_text(encoding="utf-8")
    except OSError:
        notes = ("# Data notes and disclaimer\n\n"
                 "The data notes document is missing from the corpus.")
    body = ("<h1>Data notes and disclaimer</h1>"
            '<p class="intro">These notes are reproduced verbatim from the '
            "source dataset (FOI statistics) on data.gov.au.</p>"
            f'<div class="notes">{_md(notes)}</div>')
    return chrome("Data notes and disclaimer", body,
                  page_key="data-notes")


def _page_how_to_use() -> str:
    body = """
    <h1>How to use</h1>
    <p class="intro">The 12 Bluebird FOI Insights pages are built from the source data
    published on data.gov.au (FOI statistics). Every figure is computed
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
    <p>Where the source files do not publish a measure (for example, the
    after-statutory timeliness buckets, or the transferred measures, which the
    dashboard does not render), the page shows
    <em>No published data for this measure</em> — a flat zero line would be a
    fabricated number. A year without a figure in a series renders as "—".</p>
    <h2>Filters</h2>
    <p>The filters row (portfolio / agency · type (personal/other) · FY or
    quarter) is the drill-down surface. In this static POC the pages render
    the full dataset; the filters become live in the interactive build.</p>
    <h2>Data notes</h2>
    <p>The <a href="/data-notes.html">Data notes and disclaimer</a> page carries
    the publisher's definitional notes verbatim.</p>
    """
    return chrome("How to use", body,
                  page_key="how-to-use")


def _page_api() -> str:
    body = """
    <h1>API access</h1>
    <p class="intro">Every figure and fact behind these visualisations is
    available as a read-only JSON API. The endpoints expose the <em>same
    platform-computed numbers the pages render</em> — nothing a model generated,
    only the canonical data sourced from data.gov.au (FOI statistics) plus
    the deterministic figures computed from it.</p>
    <h2>Endpoints</h2>
    <table class="apitable">
      <tr><th>Endpoint</th><th>What it returns</th></tr>
      <tr><td><code>GET /api/</code></td><td>Dataset info: snapshot, window
      modes, measures, figure/stat keys, source link, disclaimer.</td></tr>
      <tr><td><code>GET /api/figures</code></td><td>Every computed figure/stat
      with its <code>basis</code> label — the numbers behind the charts.</td></tr>
      <tr><td><code>GET /api/facts</code></td><td>The long-form canonical facts
      (agency × measure × bucket), filterable by <code>fy</code>,
      <code>measure</code>, <code>bucket</code>, <code>agency</code>,
      <code>quarter</code>, paged by <code>limit</code>/<code>offset</code>.</td></tr>
      <tr><td><code>GET /api/measures</code></td><td>The measure groups and the
      measures within each.</td></tr>
    </table>
    <h2>Examples</h2>
    <pre><code># all figures (with basis)
curl https://foi.axoquant.com/api/figures

# facts for a single measure
curl "https://foi.axoquant.com/api/facts?measure=received&fy=2024-25&bucket=total"

# dataset info
curl https://foi.axoquant.com/api/</code></pre>
    <h2>Throttling</h2>
    <p>The API is rate-limited per client IP (a fixed window) so a public,
    unauthenticated demo isn't overloaded. A <code>429</code> response carries a
    <code>Retry-After</code> header telling you when to try again. The limits
    are modest and tuned for demo traffic — this is not a production data
    service.</p>
    <h2>Source</h2>
    <p>The underlying data is the <a href="https://data.gov.au/data/dataset/freedom-of-information-statistics">
    FOI statistics dataset</a> on data.gov.au (dataset
    <code>b0771c28-09cc-4c4e-9e61-9a96f6e3d040</code>). See the
    <a href="/data-notes.html">Data notes and disclaimer</a> for how agencies,
    renames and personal information are handled.</p>
    <p class="lineage">Want to know where any figure came from? Every dashboard
    and report has a <a href="/lineage/local-1">lineage page</a> — the
    explainability trail is part of the demo.</p>
    """
    return chrome("API access", body,
                  page_key="api")


def _md(text: str) -> str:
    """Minimal markdown → HTML: escape, then wrap blank-line-separated
    paragraphs; keep headings, "- " bullet lists and *emphasis* readable.

    Everything is escaped before structure is added, so the emitted tags are
    the only markup — corpus content can never inject HTML.
    """
    esc = html.escape(text)
    esc = esc.replace("\xa0", " ")          # NBSP in the corpus → plain space
    esc = re.sub(r"\*([^*\n]+)\*", r"<em>\1</em>", esc)  # *emphasis* → <em>
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
        if all(ln.startswith("&lt;") for ln in block.splitlines()):  # <item> list
            items = "".join(
                f"<li>{ln[4:]}</li>" for ln in block.splitlines()
                if ln.startswith("&lt;"))
            blocks.append(f"<ul>{items}</ul>")
            continue
        if any(ln.lstrip().startswith("- ") for ln in block.splitlines()):
            # a "- " bullet list: each "- " line opens an item; wrapped
            # continuation lines fold into the current item
            items, cur = [], []
            for ln in block.splitlines():
                stripped = ln.strip()
                if stripped.startswith("- "):
                    if cur:
                        items.append(" ".join(cur))
                    cur = [stripped[2:]]
                elif cur:
                    cur.append(stripped)
            if cur:
                items.append(" ".join(cur))
            blocks.append("<ul>" + "".join(f"<li>{i}</li>" for i in items)
                          + "</ul>")
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
        "api": _page_api(),
    }
    return pages


def chat_page(user) -> str:
    """The gated chat page body. Rendered on demand (not in render_all_pages —
    only reachable behind a session)."""
    body = f"""
    <h1>Chat</h1>
    <p class="intro">Ask questions about Australian Government FOI statistics.
    Answers are grounded in the published data and the verbatim data notes;
    every figure carries a source. For anything the site can't answer, you'll
    be pointed to an email.</p>
    <div id="chat-log" class="chatlog" role="log" aria-live="polite"></div>
    <div class="chat-input">
      <input id="chat-in" type="text" placeholder="Ask about FOI statistics…" autocomplete="off">
      <button id="chat-send" type="button">Ask</button>
    </div>
    <p class="hint">Tip: try "how many requests were received?", "what share
    of decisions were refused?", "which agencies decide the most requests?".</p>
    """
    return chrome("Chat", body, page_key=None, user=user,
                  scripts='<script src="/assets/chat.js"></script>')


def reports_page(user) -> str:
    """The gated reports page body. Rendered on demand."""
    body = f"""
    <h1>Reports</h1>
    <p class="intro">Describe the FOI figure you want and this page returns the
    real number, computed from the published data. Custom or complex reports
    are handled by email.</p>
    <div class="report-input">
      <input id="report-in" type="text" placeholder="e.g. 'how many requests were received last quarter?'" autocomplete="off">
      <button id="report-send" type="button">Generate</button>
    </div>
    <div id="report-out" class="report-out" role="region" aria-live="polite"></div>
    <p class="hint">Try "top agencies for requests decided", "share of
    decisions refused", "timeliness within statutory".</p>
    """
    return chrome("Reports", body, page_key=None, user=user,
                  scripts='<script src="/assets/report.js"></script>')
