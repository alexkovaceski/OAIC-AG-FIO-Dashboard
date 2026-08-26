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
    blob = json.loads(m.group(1).replace("<\\/", "</").replace("\\u002d\\u002d", "--"))
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


def test_foi_charts_js_has_no_hardcoded_fy_or_measure_maps():
    from pathlib import Path
    src = Path("src/site/assets/foi-charts.js").read_text(encoding="utf-8")
    assert "2024-25" not in src, "top-N year must come from the spec"
    assert "TREND_MEASURES" not in src and "TOP_N" not in src, \
        "legacy hardcoded maps must be gone"
