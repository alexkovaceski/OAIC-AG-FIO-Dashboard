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


# Measured on the published frame (2026-08-26): 54,602 facts across 9 measures,
# 6,067 facts for every measure but received_transfer (6,066). A page ships one
# such slice per measure its figure specs consume, so the honest per-page bound
# scales with the page's measure count — a two-measure page legitimately ships
# twice what a one-measure page does. 7,000 leaves ~15% headroom for the frame
# growing a quarter or two without the guard crying wolf.
MAX_FACTS_PER_MEASURE = 7000


def test_payload_shrinks():
    """Every chart page's payload is bounded, and bounded by what that page
    actually needs. Two bounds, because neither alone is sufficient:

    1. Per-measure — catches a page widening its slice beyond the measures its
       specs consume (or a measure's slice ballooning).
    2. Absolute (half the frame) — catches the original regression this guard
       exists for: a page declaring so many measures that it ships the whole
       frame again. A purely per-measure bound would wave that through, since
       9 measures x 7,000 exceeds the entire 54.6k-fact frame.

    Pages with no figures must ship no blob at all — zero is the only correct
    payload for a page that renders no chart.
    """
    frame = Frame(normalise_all())
    pages = render_all_pages(frame)
    total_facts = len(frame.facts)

    for key, fig_keys in PAGE_FIGURE_KEYS.items():
        if not fig_keys:
            assert "window.__pageData" not in pages[key], (
                f"{key}: no figures, so it must ship no __pageData blob")
            continue

        shipped = len(_blob(pages[key])["facts"])
        n_measures = len(_spec_measures(key))
        assert n_measures, f"{key}: charted page with no spec measures"

        per_measure_bound = MAX_FACTS_PER_MEASURE * n_measures
        assert shipped <= per_measure_bound, (
            f"{key}: ships {shipped} facts for {n_measures} measure(s); "
            f"bound is {per_measure_bound}")
        assert shipped <= total_facts // 2, (
            f"{key}: ships {shipped} of {total_facts} facts — more than half "
            f"the frame is not a scoped payload")
