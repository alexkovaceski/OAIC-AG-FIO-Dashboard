"""Scoped __pageData payloads (spec S2.1): each page ships only the facts its
figures consume, plus the specs the client engine interprets."""
import json
import re

from ingest.normalise import normalise_all
from storage.frame import Frame
from site.pages import render_all_pages, PAGE_FIGURE_KEYS
from stats.catalog import FIGURE_SPECS


def _blob(page_html):
    m = re.search(r"window\.__pageData = (.*?);</script>", page_html, re.S)
    assert m, "no __pageData"
    return json.loads(m.group(1))


def _spec_measures(page_key):
    out = set()
    for fig_key in PAGE_FIGURE_KEYS[page_key]:
        spec = FIGURE_SPECS[fig_key]
        out.update(spec.get("measures", []))
        out.update(spec.get("numerators", []))
        if spec.get("denominator"):
            out.add(spec["denominator"])
        if spec.get("measure"):
            out.add(spec["measure"])
    return out


def test_pages_ship_only_their_spec_measures():
    pages = render_all_pages(Frame(normalise_all()))
    for key in ("at-a-glance", "requests-received", "decision-outcomes",
                "key-agency-contributions-received", "change-timeliness"):
        blob = _blob(pages[key])
        allowed = _spec_measures(key)
        shipped = {f["measure"] for f in blob["facts"]}
        assert shipped <= allowed, f"{key}: foreign measures {shipped - allowed}"
        assert blob["facts"], f"{key}: empty facts slice"


def test_pages_ship_their_specs():
    pages = render_all_pages(Frame(normalise_all()))
    blob = _blob(pages["key-agency-contributions-received"])
    assert blob["specs"]["received_top20"]["kind"] == "top_n"
    assert blob["specs"]["received_top20"]["default_fy"] == "2024-25"


def test_filters_blob_stays_global():
    pages = render_all_pages(Frame(normalise_all()))
    blob = _blob(pages["at-a-glance"])  # ships only 'received' facts
    # dropdown options must still cover the whole platform
    assert len(blob["filters"]["agencies"]) > 250
    assert len(blob["filters"]["portfolios"]) >= 10
    assert "2019-20" in blob["filters"]["fys"]


def test_payload_shrinks():
    pages = render_all_pages(Frame(normalise_all()))
    at_a_glance = _blob(pages["at-a-glance"])
    # at-a-glance consumes one measure; the slice must be well under a fifth
    # of the ~54.6k-fact full frame
    assert len(at_a_glance["facts"]) < 12000, len(at_a_glance["facts"])
