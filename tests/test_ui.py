"""Task 2 tests: pages emit ECharts chartboxes + a window.__pageData blob.

The 12 pages stay data-backed (PURE frame -> HTML): every chart region now
carries a `.chartbox` mount point plus a per-page `window.__pageData` JSON blob
(the full foi_stats results for that page's figures + platform-derived filter
options). No fabricated figures: an uncomputable measure stays out of the blob
as an empty series, never a flat-zero line.
"""
import json
import re
import sys

sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from storage.frame import Frame
from site.pages import render_all_pages

PAGE_KEYS = [
    "at-a-glance", "requests-received", "key-agency-contributions-received",
    "requests-finalised", "requests-decided", "key-agency-contributions-decided",
    "decision-outcomes", "change-decision-outcomes", "timeliness",
    "change-timeliness", "data-notes", "how-to-use", "api",
]


def _pages():
    return render_all_pages(Frame(normalise_all()))


def _relative_luminance(hex6):
    """WCAG relative luminance of a #rrggbb (or rrggbb) colour on the sRGB curve."""
    import math
    hex6 = hex6.lstrip("#")
    vals = []
    for i in (0, 2, 4):
        c = int(hex6[i:i + 2], 16) / 255
        vals.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]


def test_pages_emit_echarts_containers_and_pagedata():
    pages = _pages()
    for key in ["at-a-glance", "requests-received", "decision-outcomes", "timeliness"]:
        html = pages[key]
        assert 'class="chartbox"' in html          # ECharts container
        assert "window.__pageData" in html          # data blob for the charts
        assert "/assets/echarts.common.min.js" in html  # ECharts loaded
        assert "/assets/foi-charts.js" in html      # init + filters


def test_no_fabricated_figures_in_pagedata():
    # a measure with no FY data must NOT appear as a flat-zero series
    import json
    pages = _pages()
    m = re.search(r"window\.__pageData\s*=\s*(\{.*?\});", pages["decision-outcomes"], re.S)
    data = json.loads(m.group(1))
    decided = data["figures"].get("decision_outcomes_trend", {})
    # either the series is empty or the value is None — never [0,0,0,...]
    for s in decided.get("value", {}).get("series", []):
        values = s.get("values")
        assert not values or values != [0] * len(values), "fabricated zeros"


def test_echarts_asset_present():
    from pathlib import Path
    assert Path("src/site/assets/echarts.common.min.js").exists()
    assert Path("src/site/assets/foi-charts.js").exists()


def test_echarts_uses_common_dist_not_full_bundle():
    # the full echarts bundle is ~1MB; the prebuilt common dist (bar/line/pie)
    # is all the chart system renders, at ~36% smaller. Guards a regression
    # back to the heavyweight bundle.
    from pathlib import Path
    common = Path("src/site/assets/echarts.common.min.js")
    assert common.exists(), "common dist not vendored"
    assert common.stat().st_size < 750_000, "common dist suspiciously large"
    assert not Path("src/site/assets/echarts.min.js").exists(), \
        "full bundle should have been removed"
    for key in ["at-a-glance", "requests-received", "decision-outcomes",
                "timeliness"]:
        assert "/assets/echarts.common.min.js" in _pages()[key]


def test_pagedata_blob_escapes_script_close():
    # the JSON blob must never break out of its <script> tag: any "</" in a
    # source value is escaped as "<\/", so "</script>" cannot inject HTML
    pages = _pages()
    for key in ["at-a-glance", "requests-received", "decision-outcomes",
                "timeliness"]:
        html = pages[key]
        m = re.search(r"<script>window\.__pageData\s*=\s*(\{.*?\});</script>",
                      html, re.S)
        assert m, f"{key}: expected a well-formed __pageData script"
        assert "</script>" not in m.group(1), f"{key}: blob breaks out of script tag"


def test_each_page_marks_exactly_its_own_sidenav_entry_active():
    # the sidenav marks exactly one entry active, and it is the page's own link
    pages = _pages()
    for key, html in pages.items():
        active = re.findall(r'class="navbtn active" href="([^"]+)"', html)
        assert active == [f"/{key}.html"], (
            f"{key}: expected exactly one active sidenav link to /{key}.html, "
            f"got {active}")


def test_pagedata_ships_facts_for_live_filters():
    # Task 3: the live-filter contract selects/re-groups window.__pageData.facts
    # (the canonical long-form rows) — never a new aggregate. The blob must ship
    # them verbatim alongside figures + filters.
    import json
    pages = _pages()
    for key in ["at-a-glance", "requests-received", "decision-outcomes",
                "timeliness"]:
        html = pages[key]
        m = re.search(r"<script>window\.__pageData\s*=\s*(\{.*?\});</script>",
                      html, re.S)
        assert m, f"{key}: expected a well-formed __pageData script"
        data = json.loads(m.group(1))
        assert "facts" in data, f"{key}: __pageData must ship the canonical facts"
        assert isinstance(data["facts"], list) and data["facts"], (
            f"{key}: facts must be a non-empty list")
        row = data["facts"][0]
        assert {"fy", "quarter", "measure", "bucket", "value"} <= row.keys(), (
            f"{key}: a fact row must carry fy/quarter/measure/bucket/value")


def test_filters_bar_present():
    # spec S2.2 (Stage 2 Task 3): the filter bar (agency / portfolio / type / fy
    # selects) ships on every chart page — Task 3 lifted the earlier 4-page
    # allowlist once _FILTER_PAGES became derived from PAGE_FIGURE_KEYS. Only
    # the reference pages (no chartable figure) render without one.
    pages = _pages()
    data_pages = ["at-a-glance", "requests-received",
                  "key-agency-contributions-received", "requests-finalised",
                  "requests-decided", "key-agency-contributions-decided",
                  "decision-outcomes", "change-decision-outcomes",
                  "timeliness", "change-timeliness"]
    for key in data_pages:
        html = pages[key]
        assert '<div class="filters' in html, \
            f"{key}: expected a filter bar on a chart page"
        assert html.count("<select") >= 4, \
            f"{key}: expected agency/portfolio/type/fy selects"
        # every select carries a data-filter dimension the JS reads
        for dim in ["agency", "portfolio", "type", "fy"]:
            assert f'data-filter="{dim}"' in html, \
                f"{key}: missing a data-filter=\"{dim}\" select"
    pages_without_filters = ["data-notes", "how-to-use", "api"]
    for key in pages_without_filters:
        assert '<div class="filters' not in pages[key], \
            f"{key}: a page outside the filter scope must not render a filter bar"
        assert "data-filter=" not in pages[key], \
            f"{key}: a page outside the filter scope must not render filter selects"
    # the old static placeholder is gone — no page carries it anymore
    for key, html in pages.items():
        assert "Filters: portfolio" not in html, \
            f"{key}: stray static filter placeholder remains"


def test_foi_charts_js_smoke():
    # static smoke test on the JS module (no browser): the file must declare
    # FoiCharts.init + FoiCharts.wireFilters, and must skip chartboxes that
    # already hold a server-rendered .nodata placeholder rather than init an
    # empty chart over them.
    from pathlib import Path
    js = Path("src/site/assets/foi-charts.js").read_text(encoding="utf-8")
    assert "FoiCharts" in js and "init" in js, "FoiCharts.init missing"
    assert re.search(r"FoiCharts\s*=\s*\{\s*init\s*:\s*init\s*,\s*wireFilters\s*:\s*wireFilters\s*\}", js), \
        "FoiCharts must expose init and wireFilters"
    assert "wireFilters" in js, "FoiCharts.wireFilters missing"
    assert re.search(r"querySelectorAll\(\"\.chartbox\"\)", js), \
        "init must mount every .chartbox"
    assert ".nodata" in js, "renderChart must skip server-rendered .nodata placeholders"
    # Task 4: wireFilters must read the selects and re-filter the facts — the
    # change binding and the honest no-derive fallback must be present
    assert "addEventListener(\"change\"" in js, "wireFilters must bind change handlers"
    assert "window.__pageData" in js, "engine must read window.__pageData"
    assert re.search(r"\bdata\.facts\b", js), \
        "engine must re-derive figures from the canonical facts slice"


def test_chat_js_smoke():
    from pathlib import Path
    js = Path("src/site/assets/chat.js").read_text(encoding="utf-8")
    assert '"/chat"' in js
    assert "chat-send" in js and "chat-in" in js
    assert "escalate" in js and "contact@bluebirdadvisory.com.au" in js
    assert "redirected" in js


def test_report_js_smoke():
    from pathlib import Path
    js = Path("src/site/assets/report.js").read_text(encoding="utf-8")
    assert '"/report"' in js
    assert "report-send" in js and "report-in" in js
    assert "escalate" in js and "contact@bluebirdadvisory.com.au" in js
    assert "redirected" in js


def test_every_page_has_skip_link_and_main_landmark():
    # Task 3: a keyboard user can jump straight past the masthead + sidenav.
    for html in _pages().values():
        assert '<a class="skip-link" href="#main"' in html, "skip link missing"
        assert '<main id="main"' in html, "main landmark missing"


def test_top_nav_has_primary_aria_label():
    # Task 3: the top-level OAIC nav is the page's primary navigation landmark.
    for html in _pages().values():
        assert 'aria-label="Primary"' in html


def _ratio_on_page(hex_color: str) -> float:
    # Contrast of `hex_color` against the Bluebird Horizon page background.
    # The reference site pins data-theme=light and renders light on every
    # machine (the dark tokens only apply under :root[data-theme=dark]), so AA
    # is asserted on the light page surface #ffffff.
    page_lum = _relative_luminance("#ffffff")
    color_lum = _relative_luminance(hex_color)
    lighter, darker = (color_lum, page_lum) if color_lum > page_lum else (page_lum, color_lum)
    return (lighter + 0.05) / (darker + 0.05)


def test_page_pins_light_theme():
    # horizon.axoquant.com forces data-theme="light" in the head before any CSS
    # so the site stays light even on dark-OS machines; the FOI site must
    # replicate that (the site.css dark block is gated on :root[data-theme=dark],
    # never a bare prefers-color-scheme match).
    for html in _pages().values():
        assert 'setAttribute("data-theme","light")' in html, "head must pin data-theme=light"


def test_stylesheet_links_carry_content_hash():
    # the CSS links must be versioned with a content hash (?v=<sha>), mirroring
    # horizon's horizon.css?v=2 — otherwise a browser holding the pre-fix cached
    # sheet keeps the old navy theme for the full Cache-Control window
    import hashlib
    from pathlib import Path
    assets = Path("src/site/assets")
    html = _pages()["at-a-glance"]
    for name in ("site.css", "tailwind.css"):
        digest = hashlib.sha256((assets / name).read_bytes()).hexdigest()[:12]
        assert f'/assets/{name}?v={digest}' in html, \
            f"{name} link must carry its content hash"
    assert re.search(r"href=\"/assets/(site|tailwind)\.css\"(?![?])", html) is None, \
        "an unversioned stylesheet link remains"


def test_sitecss_dark_is_opt_in_not_auto():
    # site.css must gate the dark variant exactly like the reference site:
    # only :root[data-theme=dark] or :root:not([data-theme=light]) under a dark
    # preference — never a bare prefers-color-scheme block flipping :root.
    from pathlib import Path
    css = Path("src/site/assets/site.css").read_text(encoding="utf-8")
    assert ":root[data-theme=dark]" in css
    assert ":root:not([data-theme=light])" in css
    # a bare media dark block that flips plain :root would be the old auto-dark
    m = re.search(r"@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root\s*\{", css)
    assert not m, "dark variant must not trigger on a bare :root"


def test_ink2_token_passes_aa_on_page():
    # --ink-2 carries the secondary text (intros, basis labels, hints) on the
    # light --page background; it must reach 4.5:1. --muted is a smaller
    # decorative label colour (the Horizon reference uses #7b8ca4 at 3.4:1 for
    # tiny group labels) and is not body text, so it is not held to AA.
    from pathlib import Path
    css = Path("src/site/assets/site.css").read_text(encoding="utf-8")
    m = re.search(r"--ink-2:\s*(#[0-9a-fA-F]{6})", css)
    assert m, "no --ink-2 token"
    ratio = _ratio_on_page(m.group(1))
    assert ratio >= 4.5, f"--ink-2 {m.group(1)} is {ratio:.2f}:1 on page (needs >= 4.5:1)"


def test_nodata_token_passes_aa_on_page():
    # --nodata is used for the "No published data" placeholder text on the light
    # page background; it must clear the same 4.5:1 AA bar as --ink-2.
    from pathlib import Path
    css = Path("src/site/assets/site.css").read_text(encoding="utf-8")
    m = re.search(r"--nodata:\s*(#[0-9a-fA-F]{6})", css)
    assert m, "no --nodata token"
    ratio = _ratio_on_page(m.group(1))
    assert ratio >= 4.5, f"--nodata {m.group(1)} is {ratio:.2f}:1 on page (needs >= 4.5:1)"


def test_tailwind_ink2_token_passes_aa_on_page():
    # tailwind.css is loaded on every page; its .text-ink-2 utility carries the
    # filter-label text on the light --page background. It must clear the same
    # 4.5:1 AA bar as site.css's --ink-2.
    from pathlib import Path
    css = Path("src/site/assets/tailwind.css").read_text(encoding="utf-8")
    m = re.search(r"--color-ink-2:\s*(#[0-9a-fA-F]{6})", css)
    assert m, "no --color-ink-2 token in tailwind.css"
    ratio = _ratio_on_page(m.group(1))
    assert ratio >= 4.5, f"--color-ink-2 {m.group(1)} is {ratio:.2f}:1 on page (needs >= 4.5:1)"


def test_no_outbound_oaic_links_or_branding():
    # S1.4 (spec 2026-08-25, B15) carved a narrow, deliberate exception: the
    # golden-Q1 provenance caption legitimately names its source ("Transcribed
    # from the OAIC Power BI report...") inside a .source citation — that is
    # sourcing, not branding. Strip .source spans/paragraphs before checking;
    # everywhere else (masthead, nav, footer, body copy) "OAIC" must still stay
    # out of the rebranded Bluebird product, and no outbound OAIC link or AG
    # copyright survives anywhere, source captions included.
    for key, html in _pages().items():
        assert "oaic.gov.au" not in html, f"{key}: outbound OAIC link remains"
        stripped = re.sub(r'<(span|p) class="source">.*?</\1>', "", html, flags=re.S)
        if key == "data-notes":
            assert "OAIC" in stripped  # verbatim corpus keeps the publisher's name
        else:
            assert "OAIC" not in stripped, \
                f"{key}: OAIC name remains outside corpus/provenance caption"
        assert "© Commonwealth of Australia" not in html, f"{key}: AG copyright"


def test_masthead_is_bluebird_foi_insights():
    for html in _pages().values():
        assert 'class="wordmark-name">Bluebird</span>' in html, "masthead missing Bluebird"
        assert 'class="wordmark-product">FOI INSIGHTS</span>' in html, "masthead missing FOI INSIGHTS"


def test_masthead_has_bluebird_logo():
    # the Horizon masthead carries the Bluebird mark (bb-logo.png) before the
    # wordmark; the FOI site must match.
    from pathlib import Path
    assert Path("src/site/assets/bb-logo.png").exists(), "bb-logo.png not vendored"
    for html in _pages().values():
        assert 'class="bb-mark" src="/assets/bb-logo.png"' in html, "masthead missing bb-mark logo"


def test_masthead_risk_link_only_for_internal():
    from site.templates import _user_nav
    assert "Risk" in _user_nav({"role": "internal", "username": "a"})
    assert "Risk" not in _user_nav({"role": "viewer", "username": "a"})
    assert "btn-login" in _user_nav(None)


def test_top_nav_links_are_all_internal():
    for html in _pages().values():
        nav = re.search(r'<nav[^>]*aria-label="Primary"[^>]*>(.*?)</nav>', html, re.S)
        assert nav, "primary nav not found"
        for href in re.findall(r'href="([^"]+)"', nav.group(1)):
            assert href.startswith("/"), f"external top-nav link: {href}"


def test_footer_has_in_site_links():
    html = _pages()["at-a-glance"]
    for link in ["/data-notes.html", "/how-to-use.html", "/api.html"]:
        assert link in html, f"footer missing in-site link {link}"


def test_chat_page_oaic_free_and_gated():
    from site.pages import chat_page
    html = chat_page({"username": "alice"})
    assert "oaic.gov.au" not in html and "OAIC" not in html
    assert 'id="chat-log"' in html and "chat.js" in html


def test_reports_page_oaic_free_and_gated():
    from site.pages import reports_page
    html = reports_page({"username": "alice"})
    assert "oaic.gov.au" not in html and "OAIC" not in html
    assert "report.js" in html


def test_seed_script_shape():
    import sys
    sys.path.insert(0, "scripts")
    from seed_chat_users import ACCOUNTS, main
    assert isinstance(ACCOUNTS, list) and len(ACCOUNTS) >= 1
    assert all({"username", "display_name"} <= set(a) for a in ACCOUNTS)
    assert callable(main)


def test_data_notes_platform_reconciliation_section():
    # A2 + S1.2 disclosure: the data-notes page explains the 34,810 vs 34,418
    # split and the courts-merger topology, in a clearly-separated platform
    # section (the corpus notes above it stay verbatim).
    page = _pages()["data-notes"]
    assert "Platform reconciliation notes" in page
    assert "34,418" in page and "34,810" in page and "392" in page
    assert "Federal Circuit and Family Court" in page


GOLDEN_SOURCE_SNIPPET = "Transcribed from the OAIC Power BI report, Q1 2025-26"


def test_single_quarter_kpis_carry_transcription_source():
    # B15 (spec S1.4): every basis-single-quarter tile says where the number
    # comes from — it is not derivable from the cumulative workbook.
    pages = _pages()
    for key in ("at-a-glance", "decision-outcomes", "timeliness"):
        assert GOLDEN_SOURCE_SNIPPET in pages[key], \
            f"{key} lacks the golden-source caption"


def test_fy_figure_cards_name_their_source():
    pages = _pages()
    assert "agency-foi-data-2024-25.xlsx" in pages["key-agency-contributions-received"]
    assert "data.gov.au FOI statistics workbooks" in pages["requests-received"]
    assert "data.gov.au FOI statistics workbooks" in pages["requests-decided"]
    assert "data.gov.au FOI statistics workbooks" in pages["timeliness"]


def test_pilot_seed_script_shape():
    # The pilot accounts are the five named pilot01.user..pilot05.user; the
    # reset script deletes the old accounts and re-seeds these five fresh.
    import sys
    sys.path.insert(0, "scripts")
    from seed_pilot_users import ACCOUNTS
    from reset_pilot_users import main as reset_main
    assert [a["username"] for a in ACCOUNTS] == [
        "pilot01.user", "pilot02.user", "pilot03.user",
        "pilot04.user", "pilot05.user"]
    assert all(a["role"] == "internal" for a in ACCOUNTS)
    assert callable(reset_main)


def test_script_tags_carry_content_hash():
    # B14 residual (spec S1.6): JS gets the same ?v= content-hash the CSS got
    # in c58a325 — a behaviour change must never serve from a stale cache.
    page = _pages()["at-a-glance"]
    for name in ("echarts.common.min.js", "foi-charts.js"):
        assert re.search(rf'src="/assets/{re.escape(name)}\?v=[0-9a-f]{{12}}"', page), \
            f"{name} script tag is unversioned"


def test_type_dropdown_has_no_total_option():
    # B3 (decision 2026-08-25): 'All types' already yields total-basis figures;
    # a separate 'total' option reads as duplication.
    page = _pages()["requests-received"]
    assert '<option value="total">' not in page
    assert '<option value="">All types</option>' in page


def test_how_to_use_does_not_claim_filters_are_pending():
    page = _pages()["how-to-use"]
    assert "the filters become live in the interactive build" not in page
    assert "live on the chart pages" in page


def test_filters_blob_exposes_portfolios():
    # spec S1.1: the platform-derived filter options include the portfolio
    # dimension (the dropdown itself ships with the Stage-2 engine).
    page = _pages()["requests-received"]
    m = re.search(r"window\.__pageData = (.*?);</script>", page, re.S)
    assert m, "no __pageData blob"
    # the blob escapes the script-close sequence and the HTML-comment sequence
    # (pages._page_data_script), and BOTH escapes are ordinary JSON — json.loads
    # reverses them itself. The manual replace() this test used to run was a
    # second, redundant unescape; every other blob test here just loads it.
    blob = json.loads(m.group(1))
    portfolios = blob["filters"].get("portfolios")
    assert portfolios and len(portfolios) >= 10, portfolios
    assert all(p for p in portfolios)


CHART_PAGES = ["at-a-glance", "requests-received",
               "key-agency-contributions-received", "requests-finalised",
               "requests-decided", "key-agency-contributions-decided",
               "decision-outcomes", "change-decision-outcomes",
               "timeliness", "change-timeliness"]


def test_every_chart_page_has_the_filter_bar():
    # B12/B13/B16 (spec S2.2): filters are page-spec-driven, not an allowlist
    pages = _pages()
    for key in CHART_PAGES:
        page = pages[key]
        assert 'class="filters' in page, f"{key} has no filter bar"
        for f in ("agency", "portfolio", "type", "fy"):
            assert f'data-filter="{f}"' in page, f"{key} missing {f} select"


def test_reference_pages_have_no_filter_bar():
    pages = _pages()
    for key in ("data-notes", "how-to-use", "api"):
        assert 'class="filters' not in pages[key]


def test_chart_pages_ship_specs_for_their_figures():
    pages = _pages()
    for key in CHART_PAGES:
        m = re.search(r"window\.__pageData = (.*?);</script>", pages[key], re.S)
        blob = json.loads(m.group(1))
        for fig_key in blob["figures"]:
            assert fig_key in blob["specs"], f"{key}: {fig_key} unspecced"


def test_change_pages_render_movers_tables():
    # B10 (spec S2.3): real change analysis, not just level series.
    # N6: the FY pair comes from the catalog constant, not from literals here —
    # bumping LATEST_COMPLETE_FY must not fail two test files at once.
    from stats.catalog import LATEST_COMPLETE_FY, _previous_complete_fy
    frame = Frame(normalise_all())
    fy_a, fy_b = _previous_complete_fy(frame), LATEST_COMPLETE_FY
    pages = render_all_pages(frame)
    cdo = pages["change-decision-outcomes"]
    assert 'class="movers"' in cdo and "Refusal-rate movers" in cdo
    assert fy_a in cdo and fy_b in cdo
    ct = pages["change-timeliness"]
    assert 'class="movers"' in ct and "Timeliness movers" in ct


def test_movers_tables_show_the_denominator_behind_every_rate():
    # C1: every one of the ten rendered refusal-rate rows had a `decided`
    # denominator of 1-5 and the page sold them as the agencies that "moved
    # most". The floor keeps them out; the denominator columns let a reader
    # check each remaining row without leaving the table.
    from stats.catalog import (LATEST_COMPLETE_FY, MOVERS_MIN_DENOMINATOR,
                               _previous_complete_fy, foi_stats)
    frame = Frame(normalise_all())
    fy_a, fy_b = _previous_complete_fy(frame), LATEST_COMPLETE_FY
    pages = render_all_pages(frame)
    for page_key, stat_key in (("change-decision-outcomes", "refusal_rate_movers"),
                               ("change-timeliness", "timeliness_movers")):
        page = pages[page_key]
        assert f"<th>{fy_a} decisions</th>" in page, page_key
        assert f"<th>{fy_b} decisions</th>" in page, page_key
        movers = foi_stats(frame, stat_key)["value"]["movers"][:10]
        for mover in movers:
            assert min(mover["fy_a_denominator"],
                       mover["fy_b_denominator"]) >= MOVERS_MIN_DENOMINATOR
            assert f"<td>{mover['fy_a_denominator']:,}</td>" in page or \
                   f"<td>{mover['fy_a_denominator']}</td>" in page, mover


def test_movers_change_column_is_percentage_points_not_per_cent():
    # N3: "+100.0%" for a move from 0.0% to 100.0% reads as a doubling. The
    # quantity is a DIFFERENCE of two percentages — percentage points.
    page = _pages()["change-decision-outcomes"]
    table = re.search(r'<table class="movers">.*?</table>', page, re.S).group(0)
    assert "<th>Change (pp)</th>" in table
    assert re.search(r"<td>[+-][\d.]+ pp</td>", table), \
        "the change cells must carry the pp unit"
    assert not re.search(r"<td>[+-][\d.]+%</td>", table), \
        "a percentage-point difference is being printed as a per cent"
    assert "percentage points" in page


def test_movers_footnote_discloses_the_floor_and_counts_the_rendered_rows():
    # C1 (the floor must be published, not silent) + N5 (the footnote said
    # "Top 10 of 7 agencies" above a 7-row table).
    from site.pages import _movers_section
    from stats.catalog import MOVERS_MIN_DENOMINATOR
    page = _pages()["change-decision-outcomes"]
    assert f"with at least {MOVERS_MIN_DENOMINATOR} decisions in both years" in page

    short = {"basis": "fy", "value": {
        "fy_a": "2000-01", "fy_b": "2001-02", "denominator": "decided",
        "min_denominator": MOVERS_MIN_DENOMINATOR,
        "movers": [{"agency": f"Agency {i}", "fy_a_rate": 10.0, "fy_b_rate": 20.0,
                    "change": 10.0, "fy_a_denominator": 40,
                    "fy_b_denominator": 50} for i in range(3)]}}
    html_out = _movers_section("Short movers", short)
    assert "Top 3 of 3 agencies" in html_out, html_out
    assert "Top 10 of" not in html_out


def test_movers_section_has_an_empty_state():
    # M1: an empty movers list rendered a header-only table above "Top 10 of 0
    # agencies". Everywhere else the site prints an explicit no-data note.
    from site.pages import _movers_section
    empty = {"basis": "fy", "value": {"fy_a": "2000-01", "fy_b": "2001-02",
                                      "denominator": "decided",
                                      "min_denominator": 30, "movers": []}}
    html_out = _movers_section("Empty movers", empty)
    assert '<table class="movers">' not in html_out
    assert '<p class="note">' in html_out
    assert "No agency has a computable rate" in html_out
    assert "Top 10 of 0" not in html_out


def test_agency_dropdown_excludes_the_total_pseudo_agency():
    # S2: every per-agency op filters "Total" out; the dropdown offered it as a
    # selectable agency, promising a slice the charts will never draw.
    frame = Frame(normalise_all())
    assert any(f["agency_name"].lower() == "total" for f in frame.facts), \
        "the golden national rows moved — retarget this guard"
    from site.pages import _filters_blob
    assert "Total" not in _filters_blob(frame)["agencies"]
    pages = render_all_pages(frame)
    for key in ("change-decision-outcomes", "requests-received"):
        assert '<option value="Total">' not in pages[key]


def test_change_page_captions_describe_what_is_plotted():
    # B10: the two "Change in..." figures plot LEVEL series; the caption must
    # say so, and the movers tables carry the actual change analysis
    pages = _pages()
    cdo = pages["change-decision-outcomes"]
    assert "% of decisions granted in full or part, by FY" in cdo
    assert "Change in % granted in full or part" not in cdo
    ct = pages["change-timeliness"]
    assert "% decided within statutory time, by FY" in ct
    assert "Change in % within statutory time period" not in ct


def test_requests_received_page_has_channel_visual():
    # B5 (spec S2.2): applicant vs on-transfer, from the Stage-1 measure
    page = _pages()["requests-received"]
    assert 'data-figure="received_channel_trend"' in page
    assert "on transfer" in page


def test_no_page_claims_the_transfer_channel_is_uncharted():
    # the channel visual landed, so the "not yet charted" copy is now false
    pages = _pages()
    for key, html in pages.items():
        assert "not yet charted" not in html, f"{key}: stale uncharted claim"
    assert "charted on the Requests received page" in pages["how-to-use"]
    assert "charted on the Requests received page" in pages["data-notes"]


def test_kpi_tiles_carry_national_scope_note():
    # B11 (decision 2026-08-25): tiles are static national figures; the note
    # says so instead of pretending the agency filter reaches them
    pages = _pages()
    for key in ("at-a-glance", "requests-received", "decision-outcomes"):
        assert "KPI tiles show national totals" in pages[key], key


def test_gated_page_scripts_carry_content_hash():
    # the gated pages are rendered on demand, so they never pass through
    # render_all_pages — their script tags need the same ?v= content hash the
    # static pages assert, or a behaviour change outlives a deploy in a cache
    from site.templates import _asset_link
    for name in ("chat.js", "report.js"):
        tag = _asset_link(name)
        assert re.search(rf'src="/assets/{re.escape(name)}\?v=[0-9a-f]{{12}}"', tag), \
            f"{name} script tag is unversioned"


def test_top_n_chartbox_is_already_the_tall_box_before_any_js_runs():
    # G: .chartbox is 320px and .chartbox.topn is 560px. The class was added by
    # foi-charts.js at mount time only, so every top-N page grew ~240px the
    # moment ECharts initialised. The spec kind is known server-side — emit the
    # class with the markup.
    pages = _pages()
    for key in ("key-agency-contributions-received",
                "key-agency-contributions-decided"):
        assert re.search(r'<div class="chartbox topn" id="chart-\w+"', pages[key]), \
            f"{key}: the ranking box must ship the taller class server-side"
    # a trend page keeps the plain box — the tall one would be 240px of padding
    for key in ("requests-received", "timeliness", "change-timeliness"):
        assert "chartbox topn" not in pages[key], \
            f"{key}: only a top_n figure gets the taller box"
    # and the JS must keep the toggle: a one-agency selection turns a ranking
    # into a trend and the box has to shrink back
    js = _charts_js()
    assert 'classList.remove("topn")' in js, \
        "the engine must still drop the class when the ranking becomes a trend"


def test_top_n_note_discloses_an_ignored_fy_selection():
    # J: on a top-N page, selecting an agency AND an FY silently dropped the FY
    # (the degenerate one-agency view plots every year). A select that visibly
    # ignores its input reads as broken — the composed note says so, exactly as
    # the one-year trend note does.
    js = _charts_js()
    assert "selection is not applied here" in js, \
        "an ignored FY selection must be disclosed"
    # and the disclosure must describe the series that is actually drawn:
    # trendSeries takes its categories from the FILTERED rows, so a small agency
    # spans fewer years than the frame (measured: "Aboriginal Benefit Account
    # Advisory Committee" renders 4 categories in a 7-FY frame). "every
    # published year" over-claimed.
    assert "the trend covers every year this agency has published" in js
    assert "the trend covers every published year" not in js, \
        "the note claims a span the one-agency trend does not have"


def test_dim_filter_docstring_matches_its_call_sites():
    # I: the docstring claimed top_n skips the agency dimension ("the
    # degenerate guard has already handled an agency selection"), but neither
    # top_n call site passes skip.agency — it was a supported-but-never-passed
    # parameter documented as if it were used.
    js = _charts_js()
    assert "skip.agency" not in js, \
        "an unused skip dimension is back"
    assert "degenerate guard has already handled an agency selection" not in js, \
        "the docstring still describes a skip no call site passes"
    calls = re.findall(r"dimFilter\(facts, active, \{([^}]*)\}\)", js)
    assert calls, "no dimFilter call sites found"
    for call in calls:
        assert "agency" not in call, \
            f"a call site passes an agency skip the docstring denies: {call}"


def test_default_chart_view_pins_the_same_kind_of_axis_a_filtered_view_does():
    # N: the unfiltered branch mounted with pinMax: null, so ECharts chose a
    # rounded top (7,000 for a 6,228 maximum) while every filtered view pins an
    # exact number — the axis jumped on the first selection and the file's own
    # comparability claim did not hold for the view a reader starts from.
    js = _charts_js()
    assert not re.search(r"horizontal:\s*isTopN,\s*pinMax:\s*null", js), \
        "the default view is unpinned again"
    assert re.search(r"horizontal:\s*isTopN,\s*pinMax:\s*baselineMax\[key\]", js), \
        "the default view must pin to its own maximum"


def test_kpi_scope_note_is_emitted_beside_the_tiles_not_pasted_per_page():
    # K: the note was pasted at six call sites, drifted out of position, and a
    # new KPI page would have shipped the tiles with no disclosure at all. The
    # function that renders the tiles emits it.
    from site.pages import _kpis, _kpi_scope_note
    frame = Frame(normalise_all())
    assert _kpi_scope_note() in _kpis(frame, ["requests_received_q1"]), \
        "_kpis must emit the scope note with its tiles"
    glued = '</div>' + _kpi_scope_note()
    for key, page in _pages().items():
        if 'class="kpis"' not in page:
            continue
        assert glued in page, \
            f"{key}: KPI tiles render without the note that scopes them"
        assert page.count("KPI tiles show national totals") == 1, \
            f"{key}: the scope note is duplicated"


def test_change_pages_survive_a_frame_without_an_fy_pair():
    # P: _previous_complete_fy raises KeyError for a frame whose annual years do
    # not straddle LATEST_COMPLETE_FY, and server.app._boot renders EVERY page
    # at boot — so one unformable FY pair would have failed the boot of all
    # thirteen pages, eleven of which have nothing to do with movers.
    # api.figures and the kpis op in stats.dsl already drop such a key rather
    # than take their payload down; the page path now degrades the same way,
    # with the house no-data note. Nothing is fabricated either way.
    import pytest
    from stats.catalog import LATEST_COMPLETE_FY, _previous_complete_fy
    # FY labels sort lexicographically, so no year literal is needed here
    frame = Frame([f for f in normalise_all() if f["fy"] >= LATEST_COMPLETE_FY])
    with pytest.raises(KeyError):
        _previous_complete_fy(frame)
    pages = render_all_pages(frame)                     # must not raise
    assert set(pages) == set(PAGE_KEYS), "a page dropped out of the render"
    for key in ("change-decision-outcomes", "change-timeliness"):
        assert "No movers ranking for this measure" in pages[key], key
        assert '<table class="movers">' not in pages[key], key
        assert "Top 10 of" not in pages[key], f"{key}: a ranking was invented"


def test_movers_note_does_not_explain_a_code_bug_as_a_data_limitation():
    # F3: the try wrapped the whole call, so a KeyError raised while BUILDING
    # the section (a malformed movers value dict — the real bug shape) was
    # converted into "the data in this snapshot does not cover two complete
    # financial years to compare". A code defect must not be published as a
    # data explanation. The try now covers the catalog lookup only.
    import pytest
    from site import pages as pages_mod
    frame = Frame(normalise_all())

    original = pages_mod._movers_section
    try:
        def exploding_section(title, stat, unit="%"):
            raise KeyError("fy_a")
        pages_mod._movers_section = exploding_section
        with pytest.raises(KeyError):
            pages_mod._movers_or_note(frame, "Refusal rate movers",
                                      "refusal_rate_movers")
    finally:
        pages_mod._movers_section = original

    # and the lookup KeyError still degrades to the honest note
    def missing_key(frame_arg, key):
        raise KeyError(key)
    original_stat = pages_mod._stat
    try:
        pages_mod._stat = missing_key
        out = pages_mod._movers_or_note(frame, "Refusal rate movers",
                                        "refusal_rate_movers")
    finally:
        pages_mod._stat = original_stat
    assert "No movers ranking for this measure" in out


def test_movers_table_says_the_filters_do_not_reach_it():
    # L: the change pages' filter bar re-derives the CHART; the movers table is
    # static server-rendered HTML. The tiles disclose that; the table sat under
    # the same filter bar saying nothing.
    pages = _pages()
    for key in ("change-decision-outcomes", "change-timeliness"):
        table = re.search(r'<table class="movers">.*?</section>', pages[key], re.S)
        assert table, f"{key}: no movers table"
        assert "The filters apply to the chart above" in table.group(0), key
        assert "does not change with a filter selection" in table.group(0), key


def test_foi_charts_js_has_no_hardcoded_fy_or_measure_maps():
    from pathlib import Path
    src = Path("src/site/assets/foi-charts.js").read_text(encoding="utf-8")
    assert "2024-25" not in src, "top-N year must come from the spec"
    assert "TREND_MEASURES" not in src and "TOP_N" not in src, \
        "legacy hardcoded maps must be gone"


# --- chart-engine contract (review round 2026-08-26) -------------------------
# There is no JS harness in this project by design, so these pin the engine's
# rendered text and the shape of each fix from the server side. Each names the
# defect it guards against.

def _charts_js():
    from pathlib import Path
    return Path("src/site/assets/foi-charts.js").read_text(encoding="utf-8")


def _site_css():
    from pathlib import Path
    return Path("src/site/assets/site.css").read_text(encoding="utf-8")


def _contrast(fg_hex, bg_hex) -> float:
    a, b = _relative_luminance(fg_hex), _relative_luminance(bg_hex)
    lighter, darker = (a, b) if a > b else (b, a)
    return (lighter + 0.05) / (darker + 0.05)


def test_chart_axis_pin_can_never_truncate_a_value():
    # C1: ECharts CLIPS a series at axis.max. Pinning the value axis to the
    # UNFILTERED baseline drew any larger filtered value at the baseline's
    # length (on decided_top20 the FY2019-20 leader was drawn at 42% of its
    # true bar). The pin must be the larger of the baseline and the selection's
    # own maximum, so the interval can grow but never crops.
    js = _charts_js()
    assert "seriesMax(out.fig)" in js, \
        "the pin must consider the selection's own maximum"
    assert re.search(r"Math\.max\(baselineMax\[key\]", js), \
        "the pin must be max(unfiltered baseline, this selection's maximum)"
    assert not re.search(r"pin\s*=\s*!active\.agency\s*&&\s*baselineMax\[key\]", js), \
        "the truncating baseline-only pin is back"


def test_top_n_footnote_makes_no_claim_about_missing_agencies():
    # C2 + I1: the old footnote read "N of 434 agencies reported no data for
    # FY x and are not ranked" — a compliance claim, published two clicks from
    # the landing page, that was false twice over. It divided a
    # portfolio-scoped numerator by the GLOBAL agency list (Portfolio=Treasury
    # rendered "400 of 434 ... reported no data" when those 400 simply sit in
    # other portfolios), and the agencies genuinely absent are overwhelmingly
    # abolished, renamed or not yet created rather than non-reporters.
    js = _charts_js()
    assert "reported no data" not in js, "the compliance claim is back"
    assert "are not ranked" not in js, "the compliance claim is back"
    assert "Ranked from the " in js, "the ranking pool must still be disclosed"
    assert "filters.agencies" not in js, \
        "the footnote must not count a universe the ranking never used"


def test_chart_engine_explains_a_single_year_selection():
    # I2: an FY filter APPLIES to a trend and a ratio, narrowing the category
    # axis to one point. That is a defensible choice — the filter visibly
    # responds — but the one-point view needs the same explanation the
    # one-agency ranking gets, and the dimFilter docstring must stop claiming
    # trends skip fy when both call sites apply it.
    js = _charts_js()
    assert "trends consume fy as a category axis" not in js, \
        "the docstring still contradicts its call sites"
    assert "single financial" in js, "a one-year selection must explain itself"
    assert "Clear the FY filter" in js


def test_ranking_gutter_is_responsive_and_keeps_every_label():
    # I3: grid.left was a fixed 230px. Under the 900px breakpoint a 390px
    # viewport leaves a ~294px chartbox, so 230 + 30 left ~34px of plot for a
    # 20-bar ranking. I4: the horizontal branch replaced axisLabel wholesale
    # and dropped interval:0, so ECharts thinned 20 agency names to about 10.
    js = _charts_js()
    assert "gridLeft" in js, "the ranking gutter must be derived from the width"
    assert re.search(r"grid:\s*\{\s*left:\s*230", js) is None, \
        "the ranking gutter is a fixed pixel value again"
    assert re.search(r"interval:\s*0[^}]*width:\s*labelWidth", js, re.S), \
        "the horizontal category axis must keep interval: 0"


def test_ranking_chartbox_is_tall_enough_for_its_labels():
    # I4: 20 bands drawn with interval:0 need more than the 320px default.
    css = _site_css()
    m = re.search(r"\.chartbox\.topn\s*\{[^}]*min-height:\s*(\d+)px", css, re.S)
    assert m, "no taller box for the horizontal rankings"
    assert int(m.group(1)) >= 500, \
        f"{m.group(1)}px leaves under 25px a band for 20 agency names"


def test_fignote_passes_aa_on_the_figure_card():
    # I5: .fignote carries every honesty caveat the engine emits — the ranking
    # pool, the axis disclaimers, the single-year explanation. At 0.78rem that
    # is body text and must clear 4.5:1 on the --surface the figure card
    # paints, not the 3.3:1 --muted gave it.
    css = _site_css()
    m = re.search(r"\.fignote\s*\{[^}]*color:\s*var\((--[a-z0-9-]+)\)", css, re.S)
    assert m, "no .fignote colour"
    token = m.group(1)
    fg = re.search(rf"{token}:\s*(#[0-9a-fA-F]{{6}})", css)
    bg = re.search(r"--surface:\s*(#[0-9a-fA-F]{6})", css)
    assert fg and bg, f"cannot resolve {token} / --surface"
    ratio = _contrast(fg.group(1), bg.group(1))
    assert ratio >= 4.5, \
        f".fignote {token} {fg.group(1)} is {ratio:.2f}:1 on the card surface"


def test_ranking_excludes_the_total_pseudo_agency_and_quarter_rows():
    # C3: the frame carries 8 golden Q1 rows under agency_name "Total" (a
    # NATIONAL single-quarter figure, not an agency). FY-parameterised ranking
    # newly reaches them: on FY2025-26 "Total" outranks every real agency
    # (received 12,359 vs Home Affairs 12,264) and puts one quarter's number on
    # a chart labelled "basis: financial year". An FY ranking sums annual rows
    # only, and ranks real agencies only.
    frame = Frame(normalise_all())
    golden = [f for f in frame.facts if f["agency_name"].lower() == "total"]
    assert golden, "the golden national rows moved — retarget this guard"
    assert all(f["quarter"] is not None for f in golden), \
        "a 'Total' row without a quarter would slip past the annual-rows guard"
    js = _charts_js()
    assert re.search(r'toLowerCase\(\)\s*!==\s*"total"', js), \
        "the ranking must exclude the 'Total' pseudo-agency"
    assert re.search(r"row\.quarter\s*!==\s*null", js), \
        "an FY ranking must sum annual rows only"
    assert "isReportingAgency(row.agency_name)" in js, \
        "the ranking must apply the whole reporting-agency predicate"


def test_client_and_server_agency_predicates_are_the_same_rule():
    # O: catalog.is_reporting_agency excludes the "Total" pseudo-agency AND
    # x-prefixed normaliser placeholder rows; the JS ranking guard excluded only
    # "total". Zero x-prefixed agency names in the frame today, so it is inert —
    # but the two engines are documented as mirrors, and an inert guard is
    # exactly the kind that is never noticed when it starts mattering.
    from stats.catalog import is_reporting_agency
    assert is_reporting_agency("Department of Home Affairs")
    assert not is_reporting_agency("Total") and not is_reporting_agency("total")
    assert not is_reporting_agency("xplaceholder")
    js = _charts_js()
    body = re.search(r"function isReportingAgency\(name\) \{(.*?)\n  \}", js, re.S)
    assert body, "the client twin of is_reporting_agency is missing"
    assert 'charAt(0) !== "x"' in body.group(1), \
        "the client predicate drops the x-prefixed half"
    # measured: the guard is inert on today's frame, which is why only a test
    # keeps the two halves together
    frame = Frame(normalise_all())
    assert not [f for f in frame.facts if f["agency_name"].startswith("x")], \
        "an x-prefixed agency row appeared — the client guard is now live"


def test_chart_engine_keeps_an_honest_placeholder_honest():
    # M2/M5: a figure with no published data still ships as a truthy OBJECT
    # ({categories: [...], series: [{values: []}]}), so an object-truthiness
    # test let mountChart paint a blank canvas over the server's honest
    # placeholder after one filter round-trip. Mirror _figure_has_data.
    js = _charts_js()
    assert "figHasData" in js, \
        "the engine must test for VALUES, not for object truthiness"
    assert not re.search(r"!fig\s*\|\|\s*!fig\.value", js), \
        "object truthiness is back"


def test_chart_engine_rounds_the_way_the_server_rounds():
    # M4: the client rounded half UP (Math.round(1000*x)/10) while the server
    # uses Python's half-to-even round(x, 1). Measured over every reachable
    # ratio selection (agency/portfolio x FY x bucket), 33 of 10,452 disagreed
    # by 0.1 — e.g. within_statutory 13/16 renders 81.2 on the page and 81.3 in
    # the chart. Same operand order, same rounding rule, or the two disagree.
    js = _charts_js()
    assert "Math.round(1000" not in js, "half-up ratio rounding is back"
    assert "roundTo(" in js and "down % 2 === 0" in js, \
        "the engine must round half to even, as Python's round() does"


def test_round_to_does_not_scale_by_ten_before_testing_for_a_tie():
    # H: the half-to-even test used to run AFTER multiplying by 10^dp, which
    # invents ties. 100*1009/2000 is held as 50.450000000000003 (Python rounds
    # it UP to 50.5) but x * 10 lands on exactly 504.5, so the tie test fired
    # and half-to-even gave 50.4. Measured over 2,003,000 num/den pairs
    # (den <= 2000): 402 diverged from Python's round(x, 1). The tie test must
    # scale by a power of TWO, which is exact and cannot invent a tie, and the
    # rounding itself goes through toFixed, which reads the double's exact
    # decimal value. Verified identical to Python over all 2,003,000 pairs at
    # dp=0 and dp=1 (sha256 over the packed doubles matched).
    js = _charts_js()
    body = re.search(r"function roundTo\(x, dp\) \{(.*?)\n  \}", js, re.S)
    assert body, "roundTo is gone"
    body = body.group(1)
    assert "Math.pow(2, dp + 1)" in body, \
        "the tie test must scale by a power of two, not by 10^dp"
    assert "toFixed(dp)" in body, \
        "the non-tie branch must round on the double's exact decimal value"
    assert not re.search(r"var scaled = x \* f", body), \
        "the pre-multiplied tie test is back"
    # and the true ties must still round half to EVEN — toFixed alone rounds
    # half AWAY from zero (6.25 -> 6.3 where Python gives 6.2), and 17 of the
    # 2,170 operand pairs reachable on today's frame sit exactly on such a tie
    assert "down % 2 === 0 ? down : down + 1" in body, \
        "an exact tie must still round half to even"
