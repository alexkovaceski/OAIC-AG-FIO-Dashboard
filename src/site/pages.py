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

from stats.catalog import (foi_stats, FIG_CAPTIONS, FIGURE_SPECS,
                           is_reporting_agency, partial_fys,
                           LATEST_COMPLETE_FY, PARTIAL_FY_COVERAGE,
                           PARTIAL_FY_MONTHS)
from site.templates import chrome, _asset_link

_CORPUS = Path(__file__).resolve().parent.parent.parent / "data" / "corpus"
_DATA_NOTES = _CORPUS / "data-notes.md"

# script tags every chart page loads, rendered before </body> by chrome()
_CHART_SCRIPTS = (_asset_link("echarts.common.min.js") + "\n"
                  + _asset_link("foi-charts.js"))

# provenance caption for the transcribed golden Q1 figures (spec S1.4)
GOLDEN_SOURCE = ("Transcribed from the OAIC Power BI report, Q1 2025-26 "
                 "(Jul–Sep 2025); not derivable from the cumulative "
                 "Q1–Q3 workbook.")


def _workbook_source(frame) -> str:
    """Provenance caption for every FY figure: the whole annual workbook family,
    not one year's file. It was pasted at nine call sites and the two top-N
    pages named a SINGLE file instead ("agency-foi-data-2024-25.xlsx") — true of
    the default ranking and false the moment the FY filter selects another year,
    which the same chart supports. One definition, eleven FY cards.

    DERIVED from the frame, not written down. The constant this replaced read
    "FY2019-20 – FY2025-26 (Q1–Q3 cumulative)": correct on today's frame and
    wrong the year LATEST_COMPLETE_FY advances, because all eleven cards would
    go on calling the newest annual file a Q1–Q3 cumulative and would freeze the
    range endpoint at 2025-26 while the frame moved past it. The range runs from
    the earliest ANNUAL financial year in the frame to the latest, and the
    cumulative qualifier rides only while stats.catalog.partial_fys still calls
    that latest year partial — the same derivation the part-year disclosure and
    the How to use definition already use.

    Quarter-carrying rows are excluded for the reason partial_fys excludes them:
    the golden Q1 facts are a separate single-quarter basis with its own
    provenance caption (GOLDEN_SOURCE), and they never join an FY series.

    Measured 2026-08-26 on the real frame: annual years 2019-20..2025-26 with
    partial_fys() == ['2025-26'] reproduce the retired constant byte for byte.
    """
    annual = sorted({f["fy"] for f in frame.facts if f["quarter"] is None})
    stem = "Source: data.gov.au FOI statistics workbooks"
    if not annual:
        return stem
    span = (f"FY{annual[0]}" if annual[0] == annual[-1]
            else f"FY{annual[0]} – FY{annual[-1]}")
    qualifier = (f" ({PARTIAL_FY_COVERAGE})"
                 if annual[-1] in partial_fys(frame) else "")
    return f"{stem}, {span}{qualifier}"


# page_key -> the figure keys that page's chartboxes reference (the keys the
# page's window.__pageData blob ships). Pages without charts ship no figures.
PAGE_FIGURE_KEYS = {
    "at-a-glance": ["requests_received_trend"],
    "requests-received": ["requests_received_trend", "received_channel_trend"],
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
    "provenance": [],
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
    "refusal_rate_movers": "Refusal-rate movers",
    "timeliness_movers": "Timeliness movers",
}

# human-readable basis labels — printed beside every figure
_BASIS_LABEL = {
    "single_quarter": "basis: single quarter",
    "cumulative": "basis: cumulative",
    "fy": "basis: financial year",
}

# The basis label a PART financial year is allowed to carry. "basis: financial
# year" is defined on the How to use page as "a figure for a COMPLETE financial
# year (July-June)", so it may not ride beside a figure drawn from a part-year
# file. This label is display-only: it never enters foi_stats, whose `basis`
# stays one of config.WINDOW_MODES.
PARTIAL_FY_BASIS = f"basis: part financial year ({PARTIAL_FY_COVERAGE})"


def _partial_fy_blob(frame) -> dict:
    """Per-FY disclosure for every financial year this frame publishes without
    a complete July-June file. Shipped in window.__pageData so the chart engine
    can say which year it is drawing and under what basis, WITHOUT naming a year
    in JavaScript: stats.catalog.partial_fys derives the set from
    LATEST_COMPLETE_FY, and the prose lives here where it is escaped once and
    testable from the server side.

    Eight strings per year, because the engine has to say the true one:

      basis        — replaces the figure card's "basis: financial year" line
      count_note   — what the year covers, for a figure that plots COUNTS
      ratio_note   — the same, for a figure that plots a RATE
      axis_note_count_lowered / _raised / _unchanged
      axis_note_ratio_lowered / _raised / _unchanged
                   — why the axis is pinned to the selection's own maximum
                     instead of the full-year baseline: one sentence per
                     (figure kind x direction the pin moved). See the axis
                     contract in foi-charts.js.

    Why the note comes in two shapes. One count-shaped sentence used to fire on
    every figure kind, including the two ratio pages: it told a reader looking
    at 71.1% that "these are part-year TOTALS", and warned that a part year
    "reads as a fall in FOI activity" — a mechanism that belongs to a count and
    does not apply to a rate at all. A rate's real caveat is that it is computed
    over a shorter period and a smaller denominator, so a handful of decisions
    can move it in a way a full year would damp.

    Why the AXIS note is a 2x3 matrix and not a 1x3 one. The part-year exception
    pins the axis to the SELECTION's own maximum rather than holding the
    unfiltered baseline, and that pin can move either way — so the first split
    is the direction. Splitting on direction ALONE still left the count-shaped
    rationale firing on rates: the lowered sentence says a part year "reads as a
    fall in FOI activity that the data does not show", and re-measured
    2026-08-27 over all 495 publishing part-year selections, 55 of the 90 on the
    two ratio pages lowered their axis and drew that sentence — including the
    DEFAULT part-year view of change-decision-outcomes (baseline 85.0, axis
    73.0), one dropdown click from how the page loads. It is false twice on a
    rate: a grant rate is not "FOI activity", and 73.0% against the earlier
    years' 85.0% is exactly what the data shows. A rate's honest axis caveat is
    about comparability of HEIGHTS between two differently scaled charts, not
    about activity falling.

    Measured 2026-08-27 across the eleven shipped figures, FY2025-26, every
    portfolio x type selection that publishes a figure (495 of 858): counts
    405 lowered / 0 raised / 0 unchanged; rates 55 lowered / 34 raised /
    1 unchanged. The three count sentences are unchanged from the single set
    they replaced, so no count-shaped figure's note moved.

    Measured 2026-08-26: returns one entry, 2025-26.
    """
    out = {}
    for fy in partial_fys(frame):
        covers = (f"FY {fy} is not a complete financial year: the published "
                  f"file covers {PARTIAL_FY_COVERAGE} ({PARTIAL_FY_MONTHS}), "
                  f"not the full July–June year.")
        out[fy] = {
            "basis": PARTIAL_FY_BASIS,
            "count_note": (f"{covers} These are part-year totals and are not "
                           f"comparable with a full-year figure."),
            "ratio_note": (f"{covers} This rate is measured over that shorter "
                           f"period and a smaller denominator, so it is not "
                           f"comparable with a full-year rate."),
            "axis_note_count_lowered": ("Axis rescaled down to this part-year "
                                        "selection: a part year drawn against "
                                        "the full-year axis reads as a fall in "
                                        "FOI activity that the data does not "
                                        "show."),
            "axis_note_count_raised": ("Axis set to this part-year selection's "
                                       "own maximum, which sits above the "
                                       "unfiltered one: the interval grew to "
                                       "fit the selection rather than being "
                                       "reduced to it."),
            "axis_note_count_unchanged": ("Axis set to this part-year "
                                          "selection's own maximum rather than "
                                          "held at the unfiltered one: a part "
                                          "year and a full year are not like "
                                          "windows to compare across."),
            "axis_note_ratio_lowered": ("Axis rescaled down to this part-year "
                                        "selection: the top of the axis is "
                                        "this selection's own highest rate, so "
                                        "heights on this chart are not "
                                        "comparable with the unfiltered one. "
                                        "The rates themselves are unaffected "
                                        "by the rescale; read them from the "
                                        "axis labels."),
            "axis_note_ratio_raised": ("Axis set to this part-year selection's "
                                       "own maximum, which sits above the "
                                       "unfiltered one: this selection reaches "
                                       "a higher rate than any year on the "
                                       "unfiltered chart, so the interval grew "
                                       "to fit it."),
            "axis_note_ratio_unchanged": ("Axis set to this part-year "
                                          "selection's own maximum rather than "
                                          "held at the unfiltered one: a "
                                          "part-year rate and a full-year rate "
                                          "are measured over different windows "
                                          "and are not read off a shared "
                                          "scale."),
        }
    return out


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
    inline `_chart` no-data copy verbatim.

    A top_n figure ships the `topn` class from HERE, derived from its spec
    kind, because that class carries the taller box (.chartbox.topn is 560px
    against the 320px default). foi-charts.js also adds it at mount time, and
    adding it only there meant every top-N page grew 240px the moment ECharts
    initialised. The JS toggle still runs: classList.add on a class the server
    already wrote is a no-op, and the JS still REMOVES it when the same box
    falls back to a one-agency trend or an honest placeholder — which is why a
    figure with no data keeps the plain box here too.

    The empty `.fignote` after the box is a PERSISTENT live region, not a
    placeholder: foi-charts.js writes every honesty caveat it emits into this
    element (the ranking pool, the part-year disclosure, the axis
    disclaimers). Created and destroyed per render — which is what the engine
    used to do — the note is a new node each time and a screen reader announces
    nothing, so a filter selection silently changed the caveat under the chart.
    A container that exists before the text lands is the same pattern the chat
    log and the report output already use (role/aria-live on a server-rendered
    div). It renders as nothing while empty: site.css clips `.fignote:empty` out
    of flow — clipped rather than `display: none`, because a live region that is
    display:none at the moment it is mutated is the one screen readers skip, and
    the empty→text transition is the first filter selection of the session."""
    inner = ""
    has_data = _figure_has_data(fig)
    if not has_data:
        inner = ('<div class="nodata">No published data for this measure. '
                 'The source files do not report this breakdown for the '
                 'financial years covered.</div>')
    is_top_n = FIGURE_SPECS.get(chart_key, {}).get("kind") == "top_n"
    css_class = "chartbox topn" if (is_top_n and has_data) else "chartbox"
    return (f'<div class="{css_class}" id="chart-{chart_key}" '
            f'data-figure="{chart_key}">{inner}</div>'
            f'<p class="fignote" id="fignote-{chart_key}" aria-live="polite"></p>')


def _figure_has_data(fig) -> bool:
    series = fig.get("series") or []
    return any(s.get("values") for s in series)


def _filters_blob(frame) -> dict:
    """Platform-derived filter options, straight off the Frame — no new
    aggregates. Task 4 wires the real filter behaviour; this ships only what
    the source data itself distinguishes.

    The Agency list excludes the golden "Total" pseudo-agency (S2): it is a
    national total-level fact, not an agency, and every per-agency op in
    stats.dsl and stats.catalog filters it out — so offering it as a selectable
    agency promised a slice the charts will never draw."""
    return {
        "agencies": sorted({f["agency_name"] for f in frame.facts
                            if is_reporting_agency(f["agency_name"])}),
        "types": sorted({f["bucket"] for f in frame.facts}),
        "fys": sorted({f["fy"] for f in frame.facts}),
        "portfolios": sorted({f["portfolio"] for f in frame.facts if f["portfolio"]}),
    }


# every page with a chartable figure carries the live filter bar; the engine
# (foi-charts.js) applies each dimension only where the figure kind can honour
# it and shows the honest note where it cannot (spec S2.2)
_FILTER_PAGES = frozenset(k for k, figs in PAGE_FIGURE_KEYS.items() if figs)


def _filters_bar(frame, page_key) -> str:
    """The live-filter dropdowns (Agency / Portfolio / Type / FY) for every
    chart page. The selects carry data-filter="agency|portfolio|type|fy" so
    foi-charts.js can read them; class names are static literals so
    Tailwind's content scan compiles them. Returns "" for pages outside
    _FILTER_PAGES — pages with no chartable figure render without one."""
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
    portfolio = _select("Portfolio", "portfolio", f["portfolios"], "All portfolios")
    # personal/other are the drill-down buckets; the platform's total-basis
    # figures are what "All types" (no filter) already shows, so a separate
    # "total" option would duplicate it (B3, decision 2026-08-25).
    type_opts = [t for t in ("personal", "other") if t in types]
    typ = _select("Type", "type", type_opts, "All types")
    fy = _select("FY", "fy", f["fys"], "All FYs")
    return (f'<div class="filters flex flex-wrap items-center gap-3" '
            f'role="group" aria-label="Filter the charts">{agency}{portfolio}{typ}{fy}</div>')


def _page_spec_measures(page_key) -> set:
    """Every fact measure the page's figure specs consume (trend measures,
    ratio numerators + denominator, top-N measure)."""
    out = set()
    for fig_key in PAGE_FIGURE_KEYS.get(page_key, []):
        spec = FIGURE_SPECS.get(fig_key, {})
        out.update(spec.get("measures", []))
        out.update(spec.get("numerators", []))
        if spec.get("denominator"):
            out.add(spec["denominator"])
        if spec.get("measure"):
            out.add(spec["measure"])
    return out


def _page_data_script(frame, page_key) -> str:
    """The window.__pageData blob for one page: the foi_stats results for the
    page's figure keys, the page's FIGURE_SPECS subset (spec S2.1 — the
    declarative vocabulary the client engine interprets), the canonical
    long-form facts scoped to the measures those specs consume, and the
    platform-derived filter options (GLOBAL — derived from the full frame, so
    the dropdowns always list every agency/portfolio/type/FY regardless of
    which measures the page ships), and the part-year disclosure for every FY
    the source files do not publish in full (_partial_fy_blob — derived from
    the frame, so the client never carries a year literal). PURE frame -> JSON
    — no fabricated figures, no new aggregates. The live filters select/re-group
    window.__pageData.facts only; they never sum into a total the platform did
    not derive.

    SECURITY: the JSON is escaped so a source value cannot break out of its
    <script> tag. json.dumps does NOT escape "</" (it serialises it verbatim),
    so the .replace("</", "<\\/") below is the ONLY guard against script-tag
    breakout. "--" is also escaped to \\u002d\\u002d so a source value cannot
    form an HTML comment boundary (<!-- / -->) inside the blob."""
    figures = {k: _stat(frame, k) for k in PAGE_FIGURE_KEYS.get(page_key, [])}
    specs = {k: FIGURE_SPECS[k] for k in PAGE_FIGURE_KEYS.get(page_key, [])
             if k in FIGURE_SPECS}
    measures = _page_spec_measures(page_key)
    facts = [f for f in frame.facts if f["measure"] in measures]
    blob = {"figures": figures, "specs": specs, "facts": facts,
            "filters": _filters_blob(frame),
            "partial_fys": _partial_fy_blob(frame)}
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


def _kpi(label, value_html, basis=None, title=None, source=None) -> str:
    """A KPI tile: label, value, basis label, and provenance line when given."""
    basis_html = f'<span class="basis">{html.escape(str(basis))}</span>' if basis else ""
    title_html = f'<span class="tlabel">{html.escape(str(title))}</span>' if title else ""
    source_html = f'<span class="source">{html.escape(str(source))}</span>' if source else ""
    return (f'<div class="kpi">{title_html}<span class="label">{label}</span>'
            f'<span class="value">{value_html}</span>{basis_html}{source_html}</div>')


def _source_for_basis(basis) -> str | None:
    """The provenance caption a basis implies. Every single-quarter figure on
    the site is a transcribed golden Q1 number (S1.4) — it is not derivable
    from the cumulative workbook, so every tile carrying that basis carries the
    same citation. One definition, every use: _kpis derives it per tile and
    _page_at_a_glance derives it once for its whole block."""
    return GOLDEN_SOURCE if (basis and "single quarter" in str(basis)) else None


def _kpi_block(cells: str) -> str:
    """A KPI block: the tiles, then the scope note that describes them.

    The guarantee is about this function, not about the pages: tiles emitted
    THROUGH _kpi_block always carry the disclosure that the filters do not reach
    them, and the note lives here rather than pasted at each call site so it
    cannot drift out of position. It is NOT true that a page cannot render tiles
    without it — _page_at_a_glance hand-builds its first `.kpis` div and only
    its second block comes through here, so that page's single note sits under
    both. A new tile block should route through this function rather than repeat
    that loophole."""
    return f'<div class="kpis">{cells}</div>{_kpi_scope_note()}'


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
                          value_html, basis, source=_source_for_basis(basis)))
    return _kpi_block(chr(10).join(cells))


def _provenance_link(chart_key: str) -> str:
    """The per-figure "where did this come from?" affordance. The page already
    knows which figure is on screen, so the reader's provenance question arrives
    with the figure key attached — the guardrail is never widened, the question
    is just made precise (it names the figure the reader is looking at). Links
    to the public provenance page for that figure."""
    return (f'<a class="provenance-link" '
            f'href="/provenance.html?key={html.escape(chart_key)}">'
            f'Where did this come from?</a>')


def _trend_section(title, fig, chart_key, source=None) -> str:
    basis = _basis_label({"basis": "fy"})
    source_html = f'<p class="source">{html.escape(str(source))}</p>' if source else ""
    return (f'<section class="figure-card"><h2>{html.escape(str(title))}</h2>'
            f'<p class="basis">{basis}</p>{source_html}'
            f'{_provenance_link(chart_key)}'
            f'{_chart_container(chart_key, fig)}</section>')


def _top20_section(title, fig, chart_key, source=None) -> str:
    basis = _basis_label({"basis": "fy"})
    source_html = f'<p class="source">{html.escape(str(source))}</p>' if source else ""
    return (f'<section class="figure-card"><h2>{html.escape(str(title))}</h2>'
            f'<p class="basis">{basis}</p>{source_html}'
            f'{_provenance_link(chart_key)}'
            f'{_chart_container(chart_key, fig)}</section>')


def _notes_section(title, fig, chart_key, source=None) -> str:
    """The figure card for a chart page. A note is emitted only when the
    figure's series are empty — the source files do not report the measure —
    so the empty chart reads as honest, not broken. A figure with data carries
    the chart itself, so no note is needed."""
    note = ""
    if not _figure_has_data(fig):
        note = ('<p class="note">No published data for this measure. '
                'The source files do not report this breakdown for the '
                'financial years covered.</p>')
    source_html = f'<p class="source">{html.escape(str(source))}</p>' if source else ""
    return (f'<section class="figure-card"><h2>{html.escape(str(title))}</h2>'
            f'<p class="basis">{_basis_label({"basis": "fy"})}</p>{source_html}'
            f'{_provenance_link(chart_key)}'
            f'{note}{_chart_container(chart_key, fig)}</section>')


# the plural noun for a movers denominator measure — the footnote says what the
# floor counts ("at least 30 decisions"), so the reader knows what qualified an
# agency for the ranking
_MOVERS_DENOMINATOR_NOUN = {"decided": "decisions", "finalised": "finalisations",
                            "received": "requests received"}

MOVERS_TOP_N = 10

# The filter bar on a change page re-derives the CHARTS from the page's fact
# slice; the movers table is server-rendered HTML and a selection cannot reach
# it. Say so beside the table, exactly as the KPI tiles say it beside the tiles
# — a table sitting under a filter bar that cannot move it reads as broken.
_MOVERS_SCOPE_NOTE = ("The filters apply to the chart above; this ranking is "
                      "drawn from every qualifying agency nationally and does "
                      "not change with a filter selection.")


def _movers_section(title, stat, unit="%") -> str:
    """A ranked movers table: agency, rate and denominator in each FY, and the
    change between them. Top 10 by absolute change; the denominator floor and
    the count of qualifying agencies are both disclosed.

    This is the real change analysis (B10) — the chart beside it plots the
    national level series, which is a different question.

    Units (N3): fy_a_rate/fy_b_rate are percentages and carry `unit`; `change`
    is their DIFFERENCE and is therefore in percentage POINTS. Printing it as
    "+100.0%" read as a doubling, so it is labelled and suffixed "pp".

    Denominators (C1): each row shows the two denominator counts, so a reader
    can judge the row without leaving the table — a rate that moved 100 points
    on two decisions is visibly different from one that moved 30 points on 457.

    Scope: this table is server-rendered from the whole frame and the filter bar
    never touches it — foi-charts.js re-derives the chartboxes and nothing else.
    The tiles got that disclosure in B11; the table says the same thing in its
    footnote rather than sitting silently under a filter bar that cannot move
    it.
    """
    value = stat["value"]
    rows = value["movers"][:MOVERS_TOP_N]
    floor = value.get("min_denominator") or 0
    noun = _MOVERS_DENOMINATOR_NOUN.get(value.get("denominator"),
                                        f'{value.get("denominator", "source")} rows')
    head = (f'<section class="figure-card"><h2>{html.escape(title)}</h2>'
            f'<p class="basis">{_basis_label(stat)}</p>')
    if not rows:
        # the house no-data pattern (see _notes_section) — a header-only table
        # above "Top 10 of 0 agencies" reads as broken, not as honest (M1)
        floor_clause = (f' with at least {floor} {html.escape(noun)}'
                        if floor else '')
        return (head + '<p class="note">No agency has a computable rate in both '
                f'{html.escape(value["fy_a"])} and {html.escape(value["fy_b"])}'
                f'{floor_clause}, so there is no movers ranking for this '
                'measure.</p></section>')
    head += (f'<table class="movers"><thead><tr><th>Agency</th>'
             f'<th>{html.escape(value["fy_a"])} rate</th>'
             f'<th>{html.escape(value["fy_a"])} {html.escape(noun)}</th>'
             f'<th>{html.escape(value["fy_b"])} rate</th>'
             f'<th>{html.escape(value["fy_b"])} {html.escape(noun)}</th>'
             f'<th>Change (pp)</th></tr></thead><tbody>')
    body = "".join(
        f'<tr><td>{html.escape(mover["agency"])}</td>'
        f'<td>{mover["fy_a_rate"]}{unit}</td>'
        f'<td>{_num(mover["fy_a_denominator"])}</td>'
        f'<td>{mover["fy_b_rate"]}{unit}</td>'
        f'<td>{_num(mover["fy_b_denominator"])}</td>'
        f'<td>{"+" if mover["change"] > 0 else ""}{mover["change"]} pp</td></tr>'
        for mover in rows)
    qualified = (f'agencies with at least {floor} {noun} in both years' if floor
                 else 'agencies with a computable rate in both years')
    foot = (f'</tbody></table><p class="fignote">Top {len(rows)} of '
            f'{len(value["movers"])} {html.escape(qualified)}. Change is in '
            f'percentage points (the difference between the two rates), not '
            f'per cent. {_MOVERS_SCOPE_NOTE}</p></section>')
    return head + body + foot


def _movers_or_note(frame, title, stat_key) -> str:
    """The movers section, or the house no-data note when this frame cannot
    form the FY pair the stat needs.

    stats.catalog._previous_complete_fy raises KeyError for a frame whose
    annual years do not straddle LATEST_COMPLETE_FY (it refuses to wrap to the
    newest year and invert every comparison). api.figures and the kpis op in
    stats.dsl both drop such a key rather than take their payload down; this
    page path did not, and server.app._boot renders EVERY page at boot — so one
    unformable FY pair would have failed the boot of all thirteen pages, eleven
    of which have nothing to do with movers.

    Degrading rather than failing loud is deliberate, and it is not the golden
    gate's territory: that gate aborts because a figure would be WRONG. Here no
    figure is produced at all, and the page says so in the same words every
    other unpublishable figure on the site uses. Nothing is fabricated.

    The try covers the CATALOG LOOKUP only, and the section is built outside it.
    Wrapping the whole call meant any KeyError raised while composing the HTML —
    a movers value dict missing "fy_a", say — was rendered to the reader as "the
    data in this snapshot does not cover two complete financial years", which is
    a code defect dressed up as a data limitation. A build error now propagates.

    What the except still cannot do is tell the catalog's declared "this frame
    cannot compute this key" signal from a genuine KeyError raised inside
    foi_stats — the same limitation api.figures carries. A mis-typed key here
    would render the note instead of raising; the two literal keys below are
    covered by test_change_pages_render_movers_tables.
    """
    try:
        stat = _stat(frame, stat_key)
    except KeyError:
        return (f'<section class="figure-card"><h2>{html.escape(title)}</h2>'
                '<p class="note">No movers ranking for this measure: the data '
                'in this snapshot does not cover two complete financial years '
                'to compare.</p></section>')
    return _movers_section(title, stat)


def _kpi_scope_note() -> str:
    """B11 (decision 2026-08-25): the golden Q1 tiles are national figures with
    no per-agency breakdown in any source, so the agency filter cannot reach
    them. Say so rather than let the tiles look unresponsive.

    Call it through _kpi_block, not from a page body: pasted at six call sites
    it drifted out of position and a new KPI page would have shipped without
    it."""
    return ('<p class="fignote">KPI tiles show national totals for the '
            'published quarter; the filters apply to the charts below.</p>')


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
    # every tile in this block is a single-quarter golden figure (basis_sq), so
    # the provenance follows from the basis exactly as it does in _kpis — one
    # definition here, nine tiles below
    src_sq = _source_for_basis(basis_sq)
    share = lambda k: f"{g(k)['value']}% of decisions"
    kpis = ("<div class=\"kpis\">"
            + _kpi("Requests received", _q1_total(frame, "received"), basis_sq,
                   source=src_sq)
            + _kpi("Requests finalised", _q1_total(frame, "finalised"), basis_sq,
                   source=src_sq)
            + _kpi("Requests decided", _q1_total(frame, "decided"), basis_sq,
                   source=src_sq)
            + _kpi("Decided within statutory", _q1_total(frame, "within_statutory"),
                   basis_sq, title=share("within_statutory_pct_q1"),
                   source=src_sq)
            + _kpi("Granted in full", _q1_total(frame, "granted_full"), basis_sq,
                   title=share("granted_full_share_q1"), source=src_sq)
            + _kpi("Granted in part", _q1_total(frame, "granted_part"), basis_sq,
                   title=share("granted_part_share_q1"), source=src_sq)
            + _kpi("Refused", _q1_total(frame, "refused"), basis_sq,
                   title=share("refused_share_q1"), source=src_sq)
            + _kpi("Withdrawn", _q1_total(frame, "withdrawn"), basis_sq,
                   source=src_sq)
            + "</div>")
    # the second block closes the tiles, so it is the one that carries the scope
    # note — _kpi_block emits both together
    kpis += _kpi_block(
        _kpi("Granted full / part / refused (share of decisions)",
             f"{g('granted_full_share_q1')['value']}/{g('granted_part_share_q1')['value']}/{g('refused_share_q1')['value']}%",
             _basis_label(g('granted_full_share_q1')), source=src_sq))
    body = f"""
    <h1>FOI at a glance</h1>
    <p class="intro">Freedom of Information (FOI) activity by Australian
    Government agencies and ministers — latest published quarter (Q1
    2025-26). All figures are computed from the source data.</p>
    {kpis}
    {_filters_bar(frame, "at-a-glance")}
    {_trend_section("Requests received, FY trend",
                    g('requests_received_trend')['value'],
                    "requests_received_trend",
                    source=_workbook_source(frame))}
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
                    "requests_received_trend",
                    source=_workbook_source(frame))}
    {_trend_section(FIG_CAPTIONS["received_channel_trend"],
                    _stat(frame, "received_channel_trend")["value"],
                    "received_channel_trend",
                    source=_workbook_source(frame))}
    {_lineage_panel("requests-received")}
    {_page_data_script(frame, "requests-received")}"""
    return chrome("Requests received", body,
                  page_key="requests-received", scripts=_CHART_SCRIPTS)


def _page_key_agency_contributions_received(frame) -> str:
    fig = _stat(frame, "received_top20")["value"]
    body = f"""
    <h1>Key agency contributions — requests received</h1>
    <p class="intro">Top 20 agencies by FOI requests received. This page opens
    on FY{LATEST_COMPLETE_FY}, the latest complete financial year in the annual
    files; the FY filter re-ranks the chart for any published year, and the
    note under the chart always names the year it ranked and what that year's
    file covers.</p>
    {_filters_bar(frame, "key-agency-contributions-received")}
    {_top20_section(FIG_CAPTIONS["received_top20"], fig, "received_top20",
                    source=_workbook_source(frame))}
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
                    "requests_finalised_trend",
                    source=_workbook_source(frame))}
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
    {_filters_bar(frame, "requests-decided")}
    {_kpis(frame, ["decided_q1"])}
    {_notes_section(FIG_CAPTIONS["requests_decided_trend"], fig,
                    "requests_decided_trend",
                    source=_workbook_source(frame))}
    {_lineage_panel("requests-decided")}
    {_page_data_script(frame, "requests-decided")}"""
    return chrome("Requests decided", body,
                  page_key="requests-decided", scripts=_CHART_SCRIPTS)


def _page_key_agency_contributions_decided(frame) -> str:
    fig = _stat(frame, "decided_top20")["value"]
    body = f"""
    <h1>Key agency contributions — requests decided</h1>
    <p class="intro">Top 20 agencies by FOI requests decided. This page opens
    on FY{LATEST_COMPLETE_FY}, the latest complete financial year in the annual
    files; the FY filter re-ranks the chart for any published year, and the
    note under the chart always names the year it ranked and what that year's
    file covers.</p>
    {_filters_bar(frame, "key-agency-contributions-decided")}
    {_top20_section(FIG_CAPTIONS["decided_top20"], fig, "decided_top20",
                    source=_workbook_source(frame))}
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
    {_filters_bar(frame, "decision-outcomes")}
    {_kpis(frame, ["granted_full_share_q1", "granted_part_share_q1",
                   "refused_share_q1", "withdrawn_q1"])}
    {_notes_section(FIG_CAPTIONS["decision_outcomes_trend"], fig,
                    "decision_outcomes_trend",
                    source=_workbook_source(frame))}
    {_lineage_panel("decision-outcomes")}
    {_page_data_script(frame, "decision-outcomes")}"""
    return chrome("Decision outcomes", body,
                  page_key="decision-outcomes", scripts=_CHART_SCRIPTS)


def _page_change_decision_outcomes(frame) -> str:
    fig = _stat(frame, "granted_full_part_change")["value"]
    body = f"""
    <h1>Change in decision outcomes</h1>
    <p class="intro">The national share of decisions granted in full or in part
    for each financial year, and the agencies whose refusal rate moved most
    between the two latest complete years. Only agencies that decided enough
    requests for a rate to mean anything are ranked; the note under the table
    gives the threshold and the number of agencies that met it.</p>
    {_filters_bar(frame, "change-decision-outcomes")}
    {_notes_section(FIG_CAPTIONS["granted_full_part_change"], fig,
                    "granted_full_part_change",
                    source=_workbook_source(frame))}
    {_movers_or_note(frame, "Refusal-rate movers", "refusal_rate_movers")}
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
    {_filters_bar(frame, "timeliness")}
    {_kpis(frame, ["within_statutory_pct_q1"])}
    {_notes_section(FIG_CAPTIONS["timeliness_trend"], fig, "timeliness_trend",
                    source=_workbook_source(frame))}
    {_lineage_panel("timeliness")}
    {_page_data_script(frame, "timeliness")}"""
    return chrome("Timeliness", body,
                  page_key="timeliness", scripts=_CHART_SCRIPTS)


def _page_change_timeliness(frame) -> str:
    fig = _stat(frame, "timeliness_change")["value"]
    body = f"""
    <h1>Change in timeliness</h1>
    <p class="intro">The national share of decisions made within the statutory
    time period for each financial year, and the agencies whose within-statutory
    rate moved most between the two latest complete years. Only agencies that
    decided enough requests for a rate to mean anything are ranked; the note
    under the table gives the threshold and the number of agencies that met
    it.</p>
    {_filters_bar(frame, "change-timeliness")}
    {_notes_section(FIG_CAPTIONS["timeliness_change"], fig, "timeliness_change",
                    source=_workbook_source(frame))}
    {_movers_or_note(frame, "Timeliness movers", "timeliness_movers")}
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
    platform = (
        '<h2>Platform reconciliation notes</h2>'
        '<div class="notes"><p>These notes are Bluebird FOI Insights\' own, '
        'separate from the publisher\'s notes above.</p><ul>'
        '<li><strong>Requests received basis.</strong> The dashboard\'s '
        '"requests received" figures count requests received <em>from '
        'applicants</em> (34,418 for FY2025-26 Q1&ndash;Q3). The source '
        'workbook\'s "Total requests received" (34,810) additionally includes '
        '392 requests received on transfer from another agency; the transfer '
        'channel is ingested as its own measure and charted on the Requests '
        'received page.</li>'
        '<li><strong>Agency renames.</strong> Renamed agencies appear under '
        'their most recent name for all periods (e.g. DISR, IHACPA, ASSEA, '
        'Health, Disability and Ageing, Net Zero Economy Authority).</li>'
        '<li><strong>2021 courts merger.</strong> The Federal Circuit Court of '
        'Australia and the Family Court of Australia merged in 2021 into the '
        'Federal Circuit and Family Court of Australia. The source data reports '
        'this as two separate, still-active divisions (Division 1 and Division '
        '2) with no single combined row, and does not indicate which '
        'predecessor court maps to which division. The dashboard keeps all '
        'four as distinct series (the two predecessor courts to 2020-21, the '
        'two divisions from 2021-22) by design, rather than merging them — '
        'this matches the publisher\'s own convention of representing '
        'merger-created bodies as new entities.</li>'
        '</ul></div>')
    body = ("<h1>Data notes and disclaimer</h1>"
            '<p class="intro">These notes are reproduced verbatim from the '
            "source dataset (FOI statistics) on data.gov.au.</p>"
            f'<div class="notes">{_md(notes)}</div>'
            f'{platform}')
    return chrome("Data notes and disclaimer", body,
                  page_key="data-notes")


def _page_how_to_use(frame) -> str:
    # the part-year years are derived from the frame (stats.catalog.partial_fys),
    # so this definition can never name a year the snapshot has since completed
    partial = ", ".join(f"FY{fy}" for fy in partial_fys(frame))
    partial_clause = (f"In the current snapshot that is {partial}, published as "
                      f"{PARTIAL_FY_COVERAGE} ({PARTIAL_FY_MONTHS})."
                      if partial else
                      "The current snapshot publishes every financial year in "
                      "full.")
    body = f"""
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
      <li><strong>{html.escape(PARTIAL_FY_BASIS)}</strong> — a figure for a
      financial year the source files have not yet published in full.
      {html.escape(partial_clause)} A part-year total is not comparable with a
      full year, and a chart drawn for one says so in the note beneath it and
      rescales its axis rather than drawing part of a year against a full
      year's scale.</li>
    </ul>
    <h2>Missing data is shown, not invented</h2>
    <p>Where the source files do not publish a measure (for example, the
    after-statutory timeliness buckets), the page shows
    <em>No published data for this measure</em> — a flat zero line would be a
    fabricated number. A year without a figure in a series renders as "—". The
    on-transfer request channel is published, ingested as its own measure and
    charted on the Requests received page.</p>
    <h2>Filters</h2>
    <p>The filters row (agency &middot; portfolio &middot; type
    (personal/other) &middot; FY) is live on the chart pages: selections
    re-derive the charts from the platform's own published facts. Where a
    selection has no published aggregate, the page says so instead of inventing
    one. Selecting a financial year re-ranks the agency charts for that year and
    the note beneath the chart names the year it ranked; if that year is a part
    year, the basis label beside the chart changes with it.</p>
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
      <tr><td><code>GET /api/provenance</code></td><td>The curated provenance
      registry (source files, hashes, derivations, curation decisions); add
      <code>?key=</code> for one figure's live row basis.</td></tr>
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


def _page_provenance(frame, key=None) -> str:
    """The public data-provenance page, in end-user language.

    The reader sees: a one-line statement of where the data comes from, the
    source dataset and the workbooks (by name and period, no hashes), and the
    plain-language curation decisions. The hashes and sheet mappings are tucked
    into a collapsed "Technical details" block so the page reads like an answer,
    not a registry dump. The honest marking ("this figure"/"other years") is
    preserved in the technical block via agentic.report._registry_rows.
    """
    import provenance as prov
    from agentic.report import _registry_rows, _figure_label
    unknown_key = None
    try:
        payload = prov.describe(frame, key=key)
    except KeyError:
        payload = prov.describe(frame)
        unknown_key = key
    figure = payload.get("figure")

    figure_html = ""
    if figure is not None:
        view = figure.get("default_view") or {}
        rows = figure.get("source_rows")
        bits = []
        if view.get("measures"):
            bits.append("the measures " + ", ".join(view["measures"]))
        if view.get("financial_years"):
            bits.append("financial year " + ", ".join(view["financial_years"]))
        if view.get("distinct_agencies"):
            bits.append(f"across {view['distinct_agencies']} reporting agencies")
        what = (" (" + "; ".join(bits) + ")") if bits else ""
        figure_html = (
            f'<h2>Where {html.escape(_figure_label(figure))} comes from</h2>'
            f'<p>This figure is computed from <strong>{rows:,} published fact '
            f'rows</strong>{what}.</p>'
            f'<p class="hint">{html.escape(str(figure.get("qualifier") or ""))}</p>'
        )

    sources = payload.get("sources") or []
    refs = [s for s in sources if not s.get("ingested_as")]
    files = [s for s in sources if s.get("ingested_as")]
    source_html = ""
    if refs or files:
        lis = []
        for s in refs:
            lis.append(f'<li>{html.escape(s.get("title") or "")} &mdash; '
                       f'<a href="{html.escape(s.get("url") or "#")}">'
                       f'{html.escape(s.get("url") or "")}</a></li>')
        for s in files:
            covers = ", ".join(s.get("covers") or [])
            lis.append(f'<li>{html.escape(s.get("title") or "")}'
                       f' <span class="meta">(covers {html.escape(covers)})</span></li>')
        source_html = '<h2>The sources</h2><ul>' + "".join(lis) + "</ul>"

    decisions = payload.get("decisions") or []
    dec_html = ""
    if decisions:
        decs = "".join(f'<li>{html.escape(d.get("title") or "")}</li>'
                       for d in decisions)
        dec_html = '<h2>How we handle the data</h2><ul>' + decs + "</ul>"

    tech_rows = _registry_rows(payload,
                               figure.get("default_view") if figure else None)
    tech_table = "".join(
        f'<tr><th>{html.escape(r["part"])}</th>'
        f'<td>{html.escape(r["detail"])}</td></tr>' for r in tech_rows)
    tech = ('<details class="risk-details"><summary>Technical details '
            '(hashes and sheet mappings)</summary>'
            f'<table class="apitable provenance">{tech_table}</table></details>')

    unknown = (f'<p class="note">No figure named '
               f'<code>{html.escape(str(unknown_key))}</code> is published on '
               f'this site, so the source information below is shown without a '
               f'figure basis.</p>' if unknown_key is not None else "")

    body = (
        '<h1>Where our data comes from</h1>'
        f'{unknown}'
        '<p class="intro">Every figure on this site is computed from the '
        'Australian Government&rsquo;s published freedom-of-information (FOI) '
        'statistics &mdash; no number is typed in by hand.</p>'
        + figure_html + source_html + dec_html + tech
    )
    return chrome("Data provenance", body, page_key="provenance")


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
        "how-to-use": _page_how_to_use(frame),
        "api": _page_api(),
        "provenance": _page_provenance(frame),
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
    return chrome("Chat", body, page_key="chat", user=user,
                  scripts=_asset_link("chat.js"))


def _fmt_when(ts) -> str:
    """A report row's created_at, as a short reader-facing date+time. TIMESTAMPTZ
    comes back as a tz-aware datetime from psycopg2; a missing/unparseable value
    degrades to '—' rather than crashing the list."""
    if not ts:
        return "—"
    try:
        return ts.strftime("%d %b %Y %H:%M")
    except Exception:
        return str(ts)


_REPORT_STATUS_LABEL = {"building": "Building…", "ready": "Ready",
                        "error": "Failed"}
_REPORT_STATUS_CLASS = {"building": "status-building", "ready": "status-ready",
                        "error": "status-error"}


def _report_row(a: dict) -> str:
    """One row of the "Your reports" table. A report is openable only when it is
    genuinely built (status "ready" AND at least one panel); a ready-but-empty row
    is a pre-guard failed build and is shown as Failed with no Open link."""
    status = a.get("status") or ""
    panels = a.get("panel_count") or 0
    if status == "ready" and panels == 0:
        status = "error"  # ready-but-empty is a failed build, never "Open"-able
    label = _REPORT_STATUS_LABEL.get(status, status or "Unknown")
    cls = _REPORT_STATUS_CLASS.get(status, "status-unknown")
    openable = status == "ready"
    action = (f'<a class="nav-link" href="/dashboards/{a["id"]}">Open</a>'
              if openable else '<span class="meta">—</span>')
    return (f'<tr data-id="{a["id"]}">'
            f'<td class="report-req">{html.escape(a.get("request_text") or "")}</td>'
            f'<td><span class="status-badge {cls}">{html.escape(label)}</span></td>'
            f'<td class="report-when">{html.escape(_fmt_when(a.get("created_at")))}</td>'
            f'<td class="report-actions">{action} '
            f'<button class="report-delete" type="button" data-id="{a["id"]}">'
            f'Delete</button></td></tr>')


def reports_page(user, artifacts=None) -> str:
    """The gated reports page body. Rendered on demand."""
    artifacts = artifacts or []
    if artifacts:
        rows = "".join(_report_row(a) for a in artifacts)
        table = ('<table class="report-table reports-index">'
                 '<thead><tr><th>Report</th><th>Status</th><th>Created</th>'
                 '<th class="actions">Actions</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table>')
    else:
        table = ('<p class="nodata">No reports yet. Describe a figure above '
                 'and it will be built here.</p>')
    body = f"""
    <h1>Reports</h1>
    <p class="intro">Describe the FOI figure you want and this page returns the
    real number, computed from the published data. Anything it cannot map to a
    fixed figure is built into a dashboard and stored below.</p>
    <div class="report-input">
      <input id="report-in" type="text" placeholder="e.g. 'how many requests were received last quarter?'" autocomplete="off">
      <button id="report-send" type="button">Generate</button>
    </div>
    <div id="report-out" class="report-out" role="region" aria-live="polite"></div>
    <p class="hint">Try "top agencies for requests decided", "share of
    decisions refused", "timeliness within statutory".</p>
    <h2>Your reports</h2>
    {table}
    <p class="hint">Open a built report, or delete any report you no longer
    want.</p>
    """
    return chrome("Reports", body, page_key="reports", user=user,
                  scripts=_asset_link("report.js"))


def ask_page(user, artifacts=None) -> str:
    """The unified Ask page: one input, one thread for every answer kind, and
    the user's report job board beneath. Chat and Reports redirect here; the
    router (agentic.ask) decides whether a question comes back as a figure, a
    table, an explanation, prose, or a built dashboard."""
    artifacts = artifacts or []
    if artifacts:
        rows = "".join(_report_row(a) for a in artifacts)
        board = ('<table class="report-table reports-index">'
                 '<thead><tr><th>Report</th><th>Status</th><th>Created</th>'
                 '<th class="actions">Actions</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table>')
    else:
        board = ('<p class="nodata">No reports yet. Say "build a dashboard…" '
                 'and it will be built here.</p>')
    body = f"""
    <h1>Ask</h1>
    <p class="intro">Ask anything about the published FOI statistics. The
    answer comes back as a figure, a table, an explanation, or &mdash; for
    &ldquo;build a dashboard&rdquo; requests &mdash; a live dashboard.</p>
    <div class="report-input">
      <input id="ask-in" type="text" placeholder="e.g. 'how many requests were received last quarter?'" autocomplete="off">
      <button id="ask-send" type="button">Ask</button>
    </div>
    <div id="ask-log" class="chatlog" role="log" aria-live="polite"></div>
    <p class="hint">Try "top agencies for requests decided", "which agencies
    are growing requests?", "where does the decision outcomes data come
    from?", or "build a dashboard of requests by agency".</p>
    <h2>Your reports</h2>
    <div id="ask-reports">{board}</div>
    <p class="hint">Open a built report, or delete any report you no longer
    want.</p>
    """
    return chrome("Ask", body, page_key="ask", user=user,
                  scripts=_asset_link("ask.js"))
