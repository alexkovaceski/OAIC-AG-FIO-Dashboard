"""Task 2 tests: pages emit ECharts chartboxes + a window.__pageData blob.

The 12 pages stay data-backed (PURE frame -> HTML): every chart region now
carries a `.chartbox` mount point plus a per-page `window.__pageData` JSON blob
(the full foi_stats results for that page's figures + platform-derived filter
options). No fabricated figures: an uncomputable measure stays out of the blob
as an empty series, never a flat-zero line.
"""
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
    # Task 4: the filter bar (agency / type / fy selects) is deliberately scoped
    # to the 4 data pages in _FILTER_PAGES; the other chart pages render without
    # one (they now carry real FY series, but the live-filter scope is those 4).
    pages = _pages()
    data_pages = ["at-a-glance", "requests-received",
                  "key-agency-contributions-received", "requests-finalised"]
    for key in data_pages:
        html = pages[key]
        assert '<div class="filters' in html, \
            f"{key}: expected a filter bar on a data page"
        assert html.count("<select") >= 3, \
            f"{key}: expected agency/type/fy selects"
        # every select carries a data-filter dimension the JS reads
        for dim in ["agency", "type", "fy"]:
            assert f'data-filter="{dim}"' in html, \
                f"{key}: missing a data-filter=\"{dim}\" select"
    pages_without_filters = ["requests-decided", "key-agency-contributions-decided",
                             "decision-outcomes", "change-decision-outcomes",
                             "timeliness", "change-timeliness"]
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
    assert "__pageData.facts" in js, "wireFilters must filter the canonical facts"


def test_every_page_has_skip_link_and_main_landmark():
    # Task 3: a keyboard user can jump straight past the masthead + sidenav.
    for html in _pages().values():
        assert '<a class="skip-link" href="#main"' in html, "skip link missing"
        assert '<main id="main"' in html, "main landmark missing"


def test_top_nav_has_primary_aria_label():
    # Task 3: the top-level OAIC nav is the page's primary navigation landmark.
    for html in _pages().values():
        assert 'aria-label="Primary"' in html


def test_muted_token_passes_aa_on_white():
    # --muted must reach 4.5:1 on white for the small labels that use it.
    from pathlib import Path
    css = Path("src/site/assets/site.css").read_text(encoding="utf-8")
    m = re.search(r"--muted:\s*(#[0-9a-fA-F]{6})", css)
    assert m, "no --muted token"
    lum = _relative_luminance(m.group(1))
    ratio = (1.05) / (lum + 0.05)
    assert ratio >= 4.5, f"--muted {m.group(1)} is {ratio:.2f}:1 (needs >= 4.5:1)"


def test_no_outbound_oaic_links_or_branding():
    for key, html in _pages().items():
        assert "oaic.gov.au" not in html, f"{key}: outbound OAIC link remains"
        if key == "data-notes":
            assert "OAIC" in html  # verbatim corpus keeps the publisher's name
        else:
            assert "OAIC" not in html, f"{key}: OAIC name remains outside corpus"
        assert "© Commonwealth of Australia" not in html, f"{key}: AG copyright"


def test_masthead_is_foi_insights():
    for html in _pages().values():
        assert ">FOI Insights</a>" in html, "masthead missing FOI Insights"


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
