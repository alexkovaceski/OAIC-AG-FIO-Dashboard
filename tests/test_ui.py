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
    "change-timeliness", "data-notes", "how-to-use", "api", "provenance",
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
    pages_without_filters = ["data-notes", "how-to-use", "api", "provenance"]
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
        if key == "provenance":
            # the provenance page's whole job is to cite where the data came from,
            # including the OAIC dashboard the golden Q1 figures were transcribed
            # from — sourcing, not branding, the same rationale as the .source
            # caption exemption. The AG-copyright check below still applies.
            assert "© Commonwealth of Australia" not in html, f"{key}: AG copyright"
            continue
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
    for key in ("key-agency-contributions-received", "requests-received",
                "requests-decided", "timeliness"):
        assert "data.gov.au FOI statistics workbooks" in pages[key], key


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
    for key in ("data-notes", "how-to-use", "api", "provenance"):
        assert 'class="filters' not in pages[key]


def test_provenance_page_lists_sources_and_decisions():
    # the public provenance page is the one surface that needs no login and no
    # FOI noun: it lists every ingested source with its hash, the derivations
    # and the curation decisions, straight off the validated registry.
    html = _pages()["provenance"]
    assert "Data provenance" in html
    assert "agency-foi-data-2024-25.xlsx" in html
    assert "sha256" in html
    assert "Curation decision" in html
    assert "data.gov.au" in html


def test_figure_cards_link_their_own_provenance():
    # the figure-key affordance: a chart card's "where did this come from?"
    # arrives with the key attached, so the guardrail is never widened.
    html = _pages()["requests-received"]
    assert 'href="/provenance.html?key=requests_received_trend"' in html


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
    # and the disclosure must describe the series that is actually drawn. It
    # used to read "every year this agency has published data for", because
    # trendSeries built its categories from the FILTERED rows and a small agency
    # therefore spanned fewer years than the frame — "Aboriginal Benefit Account
    # Advisory Committee" rendered a 4-category axis in a 7-FY frame, and the
    # wording was accurate about a chart that was itself wrong. The category
    # contract (final fix wave, 2026-08-26) made the axis the full published one
    # with a gap where the agency has no row, so the note now claims the whole
    # span — correctly — and names the gap. Measured after: the same agency
    # renders 7 categories, values [0,0,0,0,null,null,null].
    assert "the trend spans every published financial year" in js
    assert "drawn as a gap" in js, \
        "an axis with holes must say what the holes are"
    assert "covers every year this agency has published" not in js, \
        "the note under-claims the span the trend now draws"


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


# --- final fix wave (whole-branch review 2026-08-26) --------------------------
# C1 (part-year honesty), I2 (category axis), I4 (baseline), I5 (a11y),
# I6 (render-failure recovery). The JS behaviours are pinned from the source
# text — there is no JS harness in this project by design — and every claim
# these guard was measured against the real frame before the fix.

def _chart_page_data(page_key):
    """The window.__pageData blob for one page, decoded."""
    html = _pages()[page_key]
    m = re.search(r"window\.__pageData\s*=\s*(\{.*?\});", html, re.S)
    assert m, f"{page_key}: no __pageData"
    return json.loads(m.group(1).replace("<\\/", "</")
                      .replace("\\u002d\\u002d", "--"))


def test_page_data_ships_the_part_year_disclosure():
    # C1: selecting FY2025-26 re-ranks a top-N from the Q1-Q3 CUMULATIVE file —
    # nine months of activity — under a card that said "basis: financial year",
    # which How to use defines as a COMPLETE July-June year. The engine cannot
    # name the year itself (it carries no year literals), so the server ships
    # the derived set and the prose with it.
    from stats.catalog import LATEST_COMPLETE_FY
    for page_key in ("key-agency-contributions-received",
                     "key-agency-contributions-decided",
                     "requests-received", "change-timeliness"):
        blob = _chart_page_data(page_key)
        partial = blob["partial_fys"]
        assert list(partial) == ["2025-26"], f"{page_key}: {list(partial)}"
        entry = partial["2025-26"]
        assert entry["basis"] != "basis: financial year", \
            "a part year must not be published under the complete-year label"
        assert "part financial year" in entry["basis"]
        assert "Q1–Q3 cumulative" in entry["basis"]
        # the note names the year and says what the file actually covers. It
        # comes in a count and a ratio wording since the Stage 3a sweep (item
        # C) — the key set itself is pinned by
        # test_part_year_note_says_what_kind_of_figure_it_is_qualifying
        for note in (entry["count_note"], entry["ratio_note"]):
            assert "2025-26" in note and "July" in note
            assert "not a complete financial year" in note
            assert "not comparable" in note
        # and the axis notes explain the rescale rather than leaving the reader
        # to compare nine months against a full-year interval
        assert all("scale" in entry[k] or "Axis" in entry[k]
                   for k in entry if k.startswith("axis_note_"))
        assert len([k for k in entry if k.startswith("axis_note_")]) == 6, \
            "one axis sentence per (figure kind x direction the pin moved)"
        assert LATEST_COMPLETE_FY not in partial, \
            "the latest COMPLETE year must never be flagged as partial"


def test_top_n_pages_assert_no_year_the_fy_filter_can_change():
    # C1: both Key agency contributions pages sat under a live FY filter while
    # the intro said "in FY2024-25" and the caption named a single workbook
    # ("agency-foi-data-2024-25.xlsx"). One click on the FY select made both
    # false. They now describe the DEFAULT view and point at the note, and the
    # caption names the workbook family every FY selection draws from.
    pages = _pages()
    for key in ("key-agency-contributions-received",
                "key-agency-contributions-decided"):
        page = pages[key]
        assert "agency-foi-data-2024-25.xlsx" not in page, \
            f"{key}: the caption names one year's file under an FY filter"
        assert "data.gov.au FOI statistics workbooks" in page, key
        intro = re.search(r'<p class="intro">(.*?)</p>', page, re.S).group(1)
        assert "This page opens" in intro, f"{key}: intro asserts a fixed year"
        assert "FY filter re-ranks" in intro, key
        assert "note under the chart" in intro, key


def test_how_to_use_defines_the_part_year_basis():
    # C1: the basis vocabulary is defined in one place and a label the charts
    # can emit must be defined there too — otherwise "basis: part financial
    # year" appears on a card with nothing telling the reader what it means.
    from site.pages import PARTIAL_FY_BASIS
    page = _pages()["how-to-use"]
    assert "a figure for a complete" in page, \
        "the complete-financial-year definition is the one this contrasts with"
    assert PARTIAL_FY_BASIS in page, "the part-year label is undefined"
    assert "have not yet published in full" in page
    assert "FY2025-26" in page, "the definition must name the part year in force"


def test_chart_cards_ship_a_persistent_live_note():
    # I5: .fignote carries every honesty caveat the engine emits, and the
    # engine used to CREATE and REMOVE the element per render. A brand-new node
    # is not a live-region update, so a filter selection silently swapped the
    # sentence under the chart. The container is server-rendered, empty, and
    # announced — the same pattern the chat log and the report output use.
    from site.pages import PAGE_FIGURE_KEYS
    pages = _pages()
    boxes = 0
    for page_key, figs in PAGE_FIGURE_KEYS.items():
        for fig_key in figs:
            boxes += 1
            page = pages[page_key]
            note = (f'<p class="fignote" id="fignote-{fig_key}" '
                    f'aria-live="polite"></p>')
            assert note in page, \
                f"{page_key}/{fig_key}: no persistent live note for this figure"
            # and it sits AFTER the box it describes
            assert page.index(note) > page.index(f'data-figure="{fig_key}"'), \
                f"{page_key}/{fig_key}: the note precedes its chartbox"
    assert boxes == 11, f"chartbox count moved ({boxes}) — retarget this guard"
    css = _site_css()
    # an empty note must occupy no space — WITHOUT leaving the accessibility
    # tree, which display:none would do (item E; the rule itself is pinned by
    # test_empty_fignote_stays_in_the_accessibility_tree)
    assert re.search(r"\.fignote:empty\s*\{[^}]*clip-path", css), \
        "an empty note must occupy no space"


def test_chart_engine_qualifies_a_part_year_selection():
    # C1, client half: the ranking, the basis line and the axis all have to
    # agree that a part year is a part year. Measured on the real frame before
    # the fix: FY2025-26 on received_top20 drew its 12,264 leader against the
    # FY2024-25 pin of 17,120 — 71.6% of the axis — under "basis: financial
    # year", which reads as a collapse in FOI activity that did not happen.
    js = _charts_js()
    assert "partial_fys" in js, "the engine must read the derived part-year set"
    assert "function partialFy(" in js and "function setBasis(" in js
    assert "partial.basis" in js, "the basis label must vary for a part year"
    # the note and the axis sentence are chosen per render since item C —
    # by spec kind, and by whether the axis actually shrank
    assert "partYearNote(partial, spec)" in js
    assert "partYearAxisNote(partial," in js
    assert re.search(r"else if \(partial\) pin = own", js), \
        "a part-year selection must rescale to its own maximum, not the pin"
    assert "out.fyIgnored" in js, \
        "the one-agency view ignores the FY filter and must not claim a part year"
    # the prose lives on the server; the engine still names no year
    assert "2025-26" not in js


def test_chart_engine_takes_its_categories_from_the_unfiltered_figure():
    # I2: trendSeries built the category axis from the FILTERED rows, so a year
    # the selection had no row for vanished instead of becoming a gap — and
    # with smooth:true the remaining points rendered evenly spaced and joined,
    # asserting a continuity the data does not carry. Measured 2026-08-26: 230
    # of the 433 agencies with annual rows do not span all seven FYs, and
    # "Aboriginal Benefit Account Advisory Committee" drew a 4-category axis in
    # a 7-FY frame.
    js = _charts_js()
    assert "function fyAxis(" in js and "function trendCats(" in js
    assert re.search(r"function trendSeries\(facts, measure, bucket, cats\)", js), \
        "the categories must be an INPUT to trendSeries, not an output"
    assert "cats.indexOf(row.fy) === -1" not in js, \
        "the axis is being rebuilt from the filtered rows again"
    assert "fig.value.categories.slice()" in js, \
        "a trend's axis must come from the unfiltered figure"
    # the server's own promise this mirrors
    from site import pages as pages_mod
    assert re.search(r"missing year renders as '—',\s+never '0'", pages_mod.__doc__), \
        "the server-side contract this client fix mirrors has moved"


def test_chart_engine_computes_the_baseline_whatever_the_filter_state():
    # I4: baselineMax was assigned only inside the `if (!hasFilters)` branch.
    # The filter selects carry no autocomplete="off" and nothing resets them, so
    # a soft reload restores the reader's selections while module state starts
    # empty. `baselineMax[key] || 0` then collapsed the pin to the selection's
    # own maximum (measured: FY2022-23 on received_top20 drew against 12,993
    # instead of the 17,120 baseline, so two selections were no longer
    # comparable) AND the same falsy value short-circuited the disclaimer, so
    # "Axis extended past the unfiltered maximum" was suppressed in exactly the
    # case where the axis was being rescaled (FY2019-20, own max 17,294).
    js = _charts_js()
    assert "function ensureBaseline(" in js
    assert re.search(r"var hasFilters = [^\n]*\n\s*ensureBaseline\(key\);", js), \
        "the baseline must be computed before the filtered/unfiltered branch"
    body = re.search(r"if \(!hasFilters\) \{(.*?)\n      \}", js, re.S)
    assert body and "baselineMax[key] =" not in body.group(1), \
        "the baseline is assigned inside the unfiltered branch again"


def test_chart_engine_names_itself_to_assistive_tech():
    # I5: ECharts OVERWRITES the aria-label the page sets — with aria.enabled
    # and no aria.label.description it falls through to its own generated
    # string, so every chart announced "This is a chart with type bar" instead
    # of its <h2>. Its generated string also enumerates only
    # aria.label.data.maxCount points (default 10), half of a top-20, with no
    # table fallback on the page. Verified against the bundled ECharts 5.6.1.
    js = _charts_js()
    assert "function ariaDescription(" in js
    assert re.search(r"description:\s*ariaDescription\(label, figValue\)", js), \
        "ECharts must be given the intended label, or it invents one"
    assert '"no data"' in js, \
        "a missing year must reach assistive tech as 'no data', not as nothing"
    # the bundled build is the one this was verified against
    from pathlib import Path
    bundle = Path("src/site/assets/echarts.common.min.js").read_text(
        encoding="utf-8", errors="ignore")
    assert 'a.get("description")' in bundle, \
        "the bundled ECharts no longer honours aria.label.description"
    assert 'setAttribute("role","img")' in bundle, \
        "the bundled ECharts no longer stamps role=img — recheck noData"


def test_no_data_placeholder_is_reachable_by_a_screen_reader():
    # I5: ECharts stamps role="img" + aria-label on the CONTAINER and dispose()
    # leaves both behind, so when noData replaced a chart with the honest "No
    # published aggregate..." text, a screen reader still saw an image with the
    # old label and never reached the text. The site's central honesty
    # mechanism was unavailable to exactly the readers least able to work
    # around it.
    js = _charts_js()
    body = re.search(r"function noData\(el, key, text\) \{(.*?)\n  \}", js, re.S)
    assert body, "noData is gone"
    body = body.group(1)
    assert 'el.removeAttribute("role")' in body, "role=img survives dispose"
    assert 'el.removeAttribute("aria-label")' in body, \
        "the disposed chart's label would mask the placeholder text"
    assert 'el.setAttribute("aria-live", "polite")' in body
    assert re.search(r'aria-live".*?el\.innerHTML', body, re.S), \
        "the live region must exist before the text lands"
    # and a mounted chart must not stay a live region, or every filter change
    # announces the whole enumerated series again
    mount = re.search(r"function mountChart\(el, key, figValue, opts\) \{(.*?)\n  \}",
                      js, re.S)
    assert 'el.removeAttribute("aria-live")' in mount.group(1)


def test_chart_engine_recovers_from_a_render_failure():
    # I6: setNote runs AFTER mountChart, which has already cleared innerHTML. A
    # throw inside setOption left the PREVIOUS render's caveat ("Ranked from
    # the 303 agencies with published FY 2024-25 data for this measure") over
    # an empty box, describing a chart that is no longer there.
    js = _charts_js()
    catch = re.search(r"\} catch \(err\) \{(.*?)\n    \}", js, re.S)
    assert catch, "the render guard is gone"
    catch = catch.group(1)
    assert "noData(el, key, RENDER_FAILED_TEXT)" in catch, \
        "a failed render must clear the stale note and say what happened"
    assert "RENDER_FAILED_TEXT" in js and "could not be drawn" in js
    # and it must NOT claim the publisher does not report the measure
    assert "noData(el, key, NO_DATA_TEXT)" not in catch, \
        "a render failure is not a data-availability claim"


# --- Stage 3a carry-over sweep (Stage 2 deploy caveats A-F) ------------------
# Six loose ends, all prose / presentation / predicate hygiene: no figure VALUE
# moves. A (the workbook caption), C (part-year prose) and F (the dsl agency
# predicate, in tests/test_dsl.py) are server-testable; B, D and E are JS/CSS
# and are pinned from the source text, the way every other engine guard here is.

def _synthetic_annual_frame(years):
    """A Frame carrying one annual fact per year in `years` — enough for the
    caption derivation, which reads only fy and quarter."""
    from storage.frame import Frame
    row = {"agency_key": "a", "agency_name": "Agency A", "quarter": None,
           "measure_group": "requests", "measure": "received", "bucket": "total",
           "value": 10.0, "derived": False, "portfolio": ""}
    return Frame([dict(row, fy=fy) for fy in years])


def test_workbook_caption_is_derived_from_the_frame_not_written_down():
    # A: _WORKBOOK_SOURCE hardcoded "FY2019-20 – FY2025-26 (Q1–Q3 cumulative)"
    # and rode eleven FY cards. Correct on today's frame and wrong the year
    # LATEST_COMPLETE_FY advances: every card would keep calling the newest
    # annual file a Q1–Q3 cumulative and would freeze the range endpoint at
    # 2025-26. The caption is now derived from the frame's own annual years.
    import ast
    from pathlib import Path
    from stats.catalog import LATEST_COMPLETE_FY, PARTIAL_FY_COVERAGE
    from site.pages import _workbook_source
    # no EMITTABLE string literal in pages.py may carry an FY range. Docstrings
    # are exempt because _workbook_source's own docstring quotes the constant it
    # replaced, which is the record of what went wrong; comments never reach a
    # page at all, and ast drops them.
    tree = ast.parse(Path("src/site/pages.py").read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))
    emitted = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and id(n) not in docstrings]
    hardcoded = [s for s in emitted if re.search(r"FY\d{4}-\d{2}\s*[–-]\s*FY", s)]
    assert not hardcoded, f"the workbook caption hardcodes an FY range: {hardcoded}"

    # on the real frame it reproduces the retired constant byte for byte
    frame = Frame(normalise_all())
    assert _workbook_source(frame) == (
        "Source: data.gov.au FOI statistics workbooks, "
        "FY2019-20 – FY2025-26 (Q1–Q3 cumulative)")

    # a frame that ENDS at the latest complete year carries no cumulative
    # qualifier — which is exactly what the constant could never do
    complete = _synthetic_annual_frame(["2019-20", LATEST_COMPLETE_FY])
    assert _workbook_source(complete) == (
        "Source: data.gov.au FOI statistics workbooks, "
        f"FY2019-20 – FY{LATEST_COMPLETE_FY}")
    assert PARTIAL_FY_COVERAGE not in _workbook_source(complete)

    # and the endpoint FOLLOWS the frame: a later annual file moves it, and
    # stays qualified while partial_fys still calls that year partial
    later = _synthetic_annual_frame(["2019-20", LATEST_COMPLETE_FY, "2999-00"])
    assert _workbook_source(later) == (
        "Source: data.gov.au FOI statistics workbooks, "
        f"FY2019-20 – FY2999-00 ({PARTIAL_FY_COVERAGE})")

    # a single-year frame must not print a range from a year to itself
    one = _synthetic_annual_frame([LATEST_COMPLETE_FY])
    assert _workbook_source(one) == (
        f"Source: data.gov.au FOI statistics workbooks, FY{LATEST_COMPLETE_FY}")


def test_workbook_caption_rides_every_fy_card():
    # A, wiring: the derived caption must reach the same cards the constant did
    from site.pages import _workbook_source
    frame = Frame(normalise_all())
    caption = _workbook_source(frame)
    pages = _pages()
    carrying = [k for k, html in pages.items() if caption in html]
    # ten of the twelve pages carry at least one FY card (data-notes, how-to-use
    # and api carry none; at-a-glance carries one)
    assert len(carrying) == 10, carrying
    total = sum(html.count(caption) for html in pages.values())
    assert total == 11, f"the caption rides {total} cards, not 11"


def test_part_year_note_says_what_kind_of_figure_it_is_qualifying():
    # C: the single part-year note was COUNT-shaped ("These are part-year totals
    # and are not comparable with a full-year figure") and fired on the two
    # ratio pages, where the figure is a RATE — 71.1% is not a partial total,
    # and a rate does not "read as a fall in FOI activity" because the period
    # is short. The prose now varies by spec kind.
    for page_key in ("key-agency-contributions-received", "requests-received",
                     "change-timeliness", "change-decision-outcomes"):
        entry = _chart_page_data(page_key)["partial_fys"]["2025-26"]
        assert set(entry) == {
            "basis", "count_note", "ratio_note",
            "axis_note_count_lowered", "axis_note_count_raised",
            "axis_note_count_unchanged",
            "axis_note_ratio_lowered", "axis_note_ratio_raised",
            "axis_note_ratio_unchanged"}, entry
        # both notes still name the year and say what the file actually covers
        for note in (entry["count_note"], entry["ratio_note"]):
            assert "2025-26" in note and "July" in note
            assert "not a complete financial year" in note
            assert "not comparable" in note
        # the COUNT note keeps the totals wording
        assert "part-year totals" in entry["count_note"]
        # the RATIO note must not call a rate a total, and must give a rate's
        # real caveat: a shorter period over a smaller denominator
        assert "total" not in entry["ratio_note"].lower(), entry["ratio_note"]
        assert "denominator" in entry["ratio_note"]
        assert "rate" in entry["ratio_note"]


def _js_axis_note_dispatch():
    """(is_ratio, direction) -> the __pageData key, READ OUT of the shipped JS.

    There is no JS runtime here, so the test below cannot call
    partYearAxisNote. What it CAN refuse to do is hand-write the table it is
    checking. This parses the three return statements out of the real function
    body and drives the harness off them, so swapping the ratio and count
    branches in foi-charts.js swaps this table with them and the enumeration
    below fails on real data instead of quietly passing.

    The direction each branch belongs to is fixed by the guards, which are
    asserted here verbatim: the first return sits under the null/equal guard
    (unchanged), the second under `pin < baseline` (lowered), the third is the
    fallthrough (raised). Change a guard and these regexes stop matching.
    """
    js = _charts_js()
    body = re.search(r"function partYearAxisNote\(partial, spec, baseline, pin\)"
                     r" \{(.*?)\n  \}", js, re.S)
    assert body, "partYearAxisNote no longer takes (partial, spec, baseline, pin)"
    body = body.group(1)
    assert "var ratio = isRatioFigure(spec);" in body, \
        "the kind must come from the one shared predicate, not a second copy"
    assert re.search(r"if \(baseline === null \|\| baseline === undefined \|\|\s*"
                     r"pin === null \|\| pin === undefined \|\| pin === baseline\)",
                     body), "the unchanged guard is gone"
    assert re.search(r"if \(pin < baseline\) \{", body), \
        "the direction must come from a measured comparison, not the spec kind"
    pairs = re.findall(r"return ratio \? partial\.(\w+)\s*:\s*partial\.(\w+);", body)
    assert len(pairs) == 3, pairs
    table = {}
    for direction, (ratio_key, count_key) in zip(
            ("unchanged", "lowered", "raised"), pairs):
        table[(True, direction)] = ratio_key
        table[(False, direction)] = count_key
    return table


def _axis_direction(baseline, pin):
    """The JS guard, transliterated. Its shape is pinned by regex above, so
    this cannot drift from the engine without _js_axis_note_dispatch failing."""
    if baseline is None or pin is None or pin == baseline:
        return "unchanged"
    return "lowered" if pin < baseline else "raised"


def _series_max(fig_value):
    vals = [v for s in fig_value.get("series", [])
            for v in s.get("values", []) if v is not None]
    return max(vals) if vals else None


def _part_year_rate(facts, spec, fy, bucket, portfolio=None):
    """The rate a ratio figure draws for one part-year selection, off the same
    fact slice the client re-derives from: sum(numerators) / sum(denominator)
    over that year's ANNUAL rows, rounded the way the server rounds."""
    numerator = denominator = 0.0
    for f in facts:
        if f["quarter"] is not None or f["fy"] != fy or f["bucket"] != bucket:
            continue
        if portfolio and f.get("portfolio") != portfolio:
            continue
        if f["measure"] in spec["numerators"]:
            numerator += f["value"]
        elif f["measure"] == spec["denominator"]:
            denominator += f["value"]
    return round(100 * numerator / denominator, 1) if denominator else None


def test_part_year_axis_note_fits_the_figure_kind_and_what_the_axis_did():
    # C (round 2): the part-year exception pins the axis to the SELECTION's own
    # maximum. Dispatching that note on DIRECTION alone fixed half the defect:
    # the lowered sentence explains the shrink with a count's mechanism ("reads
    # as a fall in FOI activity that the data does not show"), and re-measured
    # 2026-08-27 over all 495 publishing part-year selections, 55 of the 90 on
    # the two ratio pages lowered their axis and drew it — including the DEFAULT
    # part-year view of change-decision-outcomes, where the reader sees a 73.0%
    # grant rate against an 85.0% baseline and is told the data shows no fall.
    # It is false twice there: a grant rate is not FOI activity, and the fall it
    # denies is what the rate shows. So the note dispatches on kind x direction.
    table = _js_axis_note_dispatch()
    from stats.catalog import FIGURE_SPECS
    pages = _pages()

    def blob(page_key):
        m = re.search(r"window\.__pageData\s*=\s*(\{.*?\});", pages[page_key], re.S)
        return json.loads(m.group(1).replace("<\\/", "</")
                          .replace("\\u002d\\u002d", "--"))

    outcomes, timeliness, received = (blob("change-decision-outcomes"),
                                      blob("change-timeliness"),
                                      blob("requests-received"))
    entry = timeliness["partial_fys"]["2025-26"]
    assert entry == outcomes["partial_fys"]["2025-26"], \
        "the disclosure must be the same prose on every page"
    fy = "2025-26"

    # four cases measured off the REAL frame, one per reachable (kind,
    # direction) cell — baseline from the server's own unfiltered figure, pin
    # from the selection the client would re-derive.
    cases = []
    grant = FIGURE_SPECS["granted_full_part_change"]
    grant_fig = outcomes["figures"]["granted_full_part_change"]["value"]
    cases.append(("granted_full_part_change, no filter", True,
                  _series_max(grant_fig),
                  _part_year_rate(outcomes["facts"], grant, fy, "total")))
    late = FIGURE_SPECS["timeliness_change"]
    late_fig = timeliness["figures"]["timeliness_change"]["value"]
    late_baseline = _series_max(late_fig)
    cases.append(("timeliness_change, type=other", True, late_baseline,
                  _part_year_rate(timeliness["facts"], late, fy, "other")))
    cases.append(("timeliness_change, Defence + type=other", True, late_baseline,
                  _part_year_rate(timeliness["facts"], late, fy, "other",
                                  portfolio="Defence")))
    received_fig = received["figures"]["requests_received_trend"]["value"]
    received_pin = received_fig["series"][0]["values"][
        received_fig["categories"].index(fy)]
    cases.append(("requests_received_trend, no filter", False,
                  _series_max(received_fig), received_pin))
    # and the cells the enumerated real-frame cases above do not reach: the two
    # count-shaped cells (0 of the 405 count-shaped selections raised or held
    # the axis) and the one ratio selection whose axis is unchanged (1 of the 90
    # ratio selections) — driven with constructed numbers so the sentence each
    # cell would print is still checked
    cases.append(("count, axis grew (synthetic)", False, 100.0, 140.0))
    cases.append(("count, axis held (synthetic)", False, 100.0, 100.0))
    cases.append(("ratio, axis held (synthetic)", True, 100.0, 100.0))

    seen = set()
    for label, is_ratio, baseline, pin in cases:
        assert baseline is not None and pin is not None, label
        direction = _axis_direction(baseline, pin)
        note = entry[table[(is_ratio, direction)]]
        seen.add((is_ratio, direction))
        where = f"{label} (baseline {baseline}, pin {pin}, {direction})"
        if direction == "lowered":
            assert "rescaled down" in note.lower(), where
        else:
            assert "rescaled down" not in note.lower(), where
        if direction == "raised":
            assert "above" in note.lower() or "higher" in note.lower(), where
        if is_ratio:
            # a rate is not FOI activity and is not a total, whatever the axis
            # did. This is the assertion the previous version got backwards.
            assert "fall in FOI activity" not in note, where
            assert "activity" not in note.lower(), where
            assert "total" not in note.lower(), where
            assert "rate" in note.lower(), where
        elif direction == "lowered":
            # the count rationale belongs HERE, and only here
            assert "fall in FOI activity" in note, where

    # the real frame must actually exercise the discrimination, not just the
    # synthetic tail: a rate that lowered, a rate that grew and a count that
    # lowered all have to appear above; the unchanged-rate cell (1 of 90, not
    # enumerated above) is driven synthetically and asserted too
    for expected in ((True, "lowered"), (True, "raised"), (False, "lowered"),
                     (True, "unchanged")):
        assert expected in seen, f"{expected} was never reached"
    # and the two lowered sentences must differ, or the dispatch bought nothing
    assert entry[table[(True, "lowered")]] != entry[table[(False, "lowered")]]

    js = _charts_js()
    assert "partYearAxisNote(partial, spec, baselineMax[key], pin)" in js, \
        "the render path must pass the spec, or the kind can never reach it"
    assert "partial.axis_note;" not in js, "the single axis claim is back"
    assert "function partYearNote(" in js, "the kind caveat is gone"
    # the ONE predicate both part-year sentences route through, pinned to its
    # body (a loose substring match would pass even after the predicate is
    # neutered to `return true`, because rederiveFigure also writes
    # `spec.kind === "ratio_trend"`)
    isr = re.search(r"function isRatioFigure\(spec\) \{(.*?)\n  \}", js, re.S)
    assert isr, "isRatioFigure is gone"
    assert "spec.kind === \"ratio_trend\"" in isr.group(1), \
        "isRatioFigure must test spec.kind, not hardcode true/false"


def test_chart_axis_pin_is_applied_on_a_null_test_not_a_truthy_one():
    # a selection whose maximum is exactly 0 is a real pin, and `if (opts.pinMax)`
    # would drop it and auto-scale while the note beside the chart claimed a pin.
    # No such selection exists today (measured 2026-08-27: 0 of the 495
    # publishing part-year selections have a zero maximum, the smallest is 5),
    # which is why a truthy test could sit here unnoticed.
    js = _charts_js()
    assert not re.search(r"if \(opts\.pinMax\) valAxis\.max", js), \
        "a zero maximum is a pin, not an absent one"
    assert re.search(r"if \(opts\.pinMax !== null && opts\.pinMax !== undefined\)",
                     js), "the pin must be applied on an explicit null test"


def test_lone_point_trend_keeps_its_emphasis_and_says_it_is_alone():
    # D: figureOption boosted symbolSize only when cats.length === 1, but since
    # the I2 axis fix the axis always carries EVERY published FY — so an agency
    # that published one year drew a single default 4px dot, no connecting line
    # (nulls break smooth) and no note (oneFyNote needs active.fy).
    # Measured 2026-08-26: 61 of the 433 agencies with annual rows publish
    # exactly one financial year.
    js = _charts_js()
    opt = re.search(r"function figureOption\(key, fig, opts, width\) \{(.*?)\n  \}",
                    js, re.S)
    assert opt, "figureOption is gone"
    opt = opt.group(1)
    assert "cats.length === 1) opt.symbolSize" not in opt, \
        "the emphasis is still gated on the axis length, not the data"
    assert re.search(r"countPublished\(s\.values\) === 1", opt), \
        "a lone NON-NULL point is what needs the bigger symbol"
    assert "function countPublished(" in js
    # and the reader has to be told the series is one point on a full axis
    assert "function lonePointNote(" in js
    assert js.count("lonePointNote(") >= 4, \
        "every trend path must be able to emit the lone-point note"


def test_empty_fignote_stays_in_the_accessibility_tree():
    # E: `.fignote:empty { display: none }` on an aria-live region is the
    # classic skipped-live-region case — a region that is display:none at the
    # moment it is mutated is what screen readers most often miss, and the
    # empty -> text transition is the FIRST filter of the session, which is
    # when the honesty caveats first appear. It must occupy no space without
    # leaving the accessibility tree.
    css = _site_css()
    rule = re.search(r"\.fignote:empty\s*\{([^}]*)\}", css)
    assert rule, "the empty-note rule is gone"
    body = rule.group(1)
    assert not re.search(r"display:\s*none", body), \
        "display:none removes the live region a screen reader must observe"
    assert not re.search(r"visibility:\s*hidden", body), \
        "visibility:hidden removes it from the accessibility tree too"
    assert "clip-path" in body and "position: absolute" in body, \
        "the clip pattern is what hides it without unmounting it"
    assert re.search(r"height:\s*1px", body) and re.search(r"width:\s*1px", body)


def test_axis_contract_header_describes_the_part_year_exception_it_implements():
    # B: the header said the part-year exception "auto-scales" three lines after
    # explaining that auto-scaling was REJECTED (ECharts picks a rounded top —
    # 7,000 for a 6,228 maximum). The code pins to the selection's own maximum.
    js = _charts_js()
    header = js[:js.index("(function ()")]
    contract = re.search(r"Axis contract:(.*?)\n \*\n", header, re.S).group(1)
    # unwrap the comment so the assertions do not depend on where lines break
    contract = " ".join(contract.replace("\n *", " ").split())
    assert "exceptions auto-scale" not in contract, \
        "the header still calls the part-year pin an auto-scale"
    assert re.search(r"PART-year selection, which is pinned to the "
                     r"SELECTION'S OWN maximum", contract), \
        "the part-year exception pins to the selection's own maximum"
    # and the header must say the pin moves both ways, since the note now does
    assert "either way" in " ".join(header.split()).lower()
    # and the code it describes is unchanged
    assert re.search(r"else if \(partial\) pin = own", js)
