"""Regression tests for the Task 7 static site (site.pages + site.lineage_viewer).

The 12 pages are data-backed: every figure renders via stats.catalog.foi_stats
(platform-computed), each KPI carries its basis label, and uncomputable figures
show an honest no-data placeholder — never a fabricated flat-zero line.
render_all_pages is PURE frame → HTML (no LLM, no DB). The lineage viewer is
testable without a live Postgres (accepts a dict, or degrades with conn=None).
"""
import sys

sys.path.insert(0, "src")
from ingest.normalise import normalise_all
from storage.frame import Frame
from site.pages import _bar, _md, render_all_pages
from site.lineage_viewer import render_lineage_page

PAGE_KEYS = [
    "at-a-glance", "requests-received", "key-agency-contributions-received",
    "requests-finalised", "requests-decided", "key-agency-contributions-decided",
    "decision-outcomes", "change-decision-outcomes", "timeliness",
    "change-timeliness", "data-notes", "how-to-use", "api",
]


def _pages():
    return render_all_pages(Frame(normalise_all()))


def test_all_12_pages_render():
    pages = _pages()
    assert set(pages) == set(PAGE_KEYS)          # exactly the 12 pages, no more
    for name, html in pages.items():
        assert "<!doctype html>" in html.lower()
        assert "fartkraft" in html.lower()        # identity stovepipe on every page
        assert "/assets/site.css" in html         # bespoke component stylesheet linked
        assert "/assets/tailwind.css" in html     # Tailwind utility stylesheet linked
        assert "Traditional Custodians" in html   # Acknowledgement of Country footer


def test_no_model_numbers_in_pages():
    # the golden Q1 headline renders with a human-readable basis label
    atag = _pages()["at-a-glance"]
    assert "12,359" in atag and "single quarter" in atag.lower()


def test_at_a_glance_shows_all_published_q1_figures():
    # spec page 1: the at-a-glance KPI tiles carry every published Q1 figure as
    # a raw value (5,167 within statutory; 1,426 full / 3,968 part / 1,950
    # refused) alongside the share-of-decisions percentage, with basis labels —
    # a share alone ("70%") is not the published figure.
    atag = _pages()["at-a-glance"]
    for fig in ["12,359", "11,549", "7,344", "5,167", "1,426", "3,968",
                "1,950", "3,955"]:
        assert fig in atag, f"at-a-glance missing published Q1 figure {fig}"
    assert atag.lower().count("basis: single quarter") >= 8  # one per KPI tile


def test_every_kpi_carries_a_basis_label():
    # constraint: basis printed beside every figure (single quarter / cumulative / fy)
    for name in ["at-a-glance", "requests-received", "requests-finalised",
                 "requests-decided", "decision-outcomes", "timeliness"]:
        assert "basis: " in _pages()[name], name


def test_uncomputable_figures_show_nodata_not_zero():
    # the annual files do not publish decided/outcome/timeliness FY series, so
    # those pages must show an honest placeholder — never "0 every year"
    for name in ["requests-decided", "decision-outcomes", "change-decision-outcomes",
                 "timeliness", "change-timeliness"]:
        assert "No published data" in _pages()[name], \
            f"{name}: expected honest no-data placeholder"


def test_nodata_pages_never_render_a_zero_value_label():
    # a fabricated flat zero would render as a "0" value label on a bar — the
    # no-data pages must not contain any rendered zero
    for name in ["requests-decided", "decision-outcomes", "timeliness"]:
        html = _pages()[name]
        assert ">0<" not in html.replace(" ", ""), name


def test_data_notes_renders_verbatim():
    html = _pages()["data-notes"]
    for phrase in ["Freedom of Information Act 1982", "1300 363 992",
                   "reliability and quality of the data",
                   "We acknowledge the Traditional Custodians"]:
        assert phrase in html


def test_requests_received_page_has_the_real_trend():
    # the one trend the annual files DO publish renders with its data, and the
    # FY labels come from the frame, not a hardcoded list
    html = _pages()["requests-received"]
    assert "Requests received, FY trend" in html
    assert "2019-20" in html and "2024-25" in html


# --- lineage viewer: testable without a live Postgres -----------------------


def test_lineage_viewer_renders_from_dict_without_db():
    data = {
        "artifact": {"id": 7, "artifact_key": "at-a-glance",
                     "request_text": "show me the Q1 headline figures",
                     "model": "claude", "status": "ok", "dataset_id": 1},
        "dataset": {"period_label": "FY2019-20..2025-26 Q1-Q3 + golden Q1",
                    "window_mode": "single_quarter",
                    "source_files": ["data/sources/agency-foi-data-2019-20.xlsx"],
                    "canonical_hash": "abc123"},
        "ops": [{"id": 1, "kind": "figure", "op": "requests_received_q1",
                 "params": {}, "row_count": 1, "rows_hash": "h1",
                 "result_value": 12359}],
        "tool_calls": [{"seq": 1, "tool": "query_dataset", "op": "filter_agencies",
                        "input_json": {"measure": "received", "top_n": 1},
                        "output_json": {"top": [{"agency": "Department of Home Affairs"}]}}],
    }
    html = render_lineage_page(7, None, data=data)
    assert "fartkraft" in html.lower()
    assert "show me the Q1 headline figures" in html   # request text
    assert "single_quarter" in html                    # dataset window_mode
    assert "agency-foi-data-2019-20.xlsx" in html      # source files
    assert "requests_received_q1" in html              # computed figures
    assert "filter_agencies" in html                   # tool-call transcript
    assert "back to dashboard" in html                 # link back


def test_lineage_viewer_degrades_without_db_and_data():
    # no conn, no data dict -> an honest degraded page, never a crash
    html = render_lineage_page("at-a-glance", None)
    assert "<!doctype html>" in html.lower()
    assert "fartkraft" in html.lower()
    assert "unavailable" in html.lower()


# --- review-fix regressions: XSS escaping, _bar aria-label, _md lists/emphasis


def test_lineage_title_escapes_xss():
    # Task 8 routes /lineage/{artifact_id} from the URL; an unescaped path
    # segment must not become reflected XSS in <title> (the body <h1> escapes,
    # the title must too)
    html = render_lineage_page("<script>alert(1)</script>", None)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<title>Lineage — &lt;script&gt;alert(1)&lt;/script&gt;</title>" in html


def test_bar_aria_label_escapes_category():
    # the aria-label must escape cat exactly like the sibling title attribute
    html = _bar('<img src=x onerror=alert(1)>', "name", 100, "#2a78d6", 0, 100)
    assert 'aria-label="&lt;img src=x onerror=alert(1)&gt;: 100"' in html
    assert 'aria-label="<img src=x onerror=alert(1)>: 100"' not in html


def test_md_renders_bullet_list_as_ul():
    # a "- " bullet block renders as <ul><li>, with wrapped continuation lines
    # joined into the item, and *emphasis* as <em>
    html = _md("- first item\n- second *emphasised* item\n  wrapped continuation")
    assert "<ul>" in html
    assert "<li>first item</li>" in html
    assert ("<li>second <em>emphasised</em> item wrapped continuation</li>"
            in html)
    # no run-on <p> carrying literal "- " prefixes
    assert "- first item" not in html


def test_data_notes_renders_bullets_and_emphasis():
    # the corpus data-notes.md list and FOI Act emphasis render as real markup
    html = _pages()["data-notes"]
    assert "<em>Freedom of Information Act 1982</em>" in html
    assert "*Freedom of Information Act 1982*" not in html
    assert "<ul>" in html
    assert "- the number of Freedom" not in html
