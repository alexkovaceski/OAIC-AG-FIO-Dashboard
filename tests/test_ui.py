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
