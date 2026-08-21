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


def test_pages_emit_echarts_containers_and_pagedata():
    pages = _pages()
    for key in ["at-a-glance", "requests-received", "decision-outcomes", "timeliness"]:
        html = pages[key]
        assert 'class="chartbox"' in html          # ECharts container
        assert "window.__pageData" in html          # data blob for the charts
        assert "/assets/echarts.min.js" in html     # ECharts loaded
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
    assert Path("src/site/assets/echarts.min.js").exists()
    assert Path("src/site/assets/foi-charts.js").exists()


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
    # Task 4: the 4 data pages (their figures ARE computed from the facts) get
    # a live filter bar with three selects (agency / type / fy); the no-data
    # pages keep only the honest placeholder — a filter bar over an empty chart
    # would promise figures the source files don't publish.
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
    no_data_pages = ["requests-decided", "key-agency-contributions-decided",
                     "decision-outcomes", "change-decision-outcomes",
                     "timeliness", "change-timeliness"]
    for key in no_data_pages:
        assert '<div class="filters' not in pages[key], \
            f"{key}: a no-data page must not render a filter bar"
        assert "data-filter=" not in pages[key], \
            f"{key}: no-data page must not render filter selects"
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
