"""The provenance registry is a load-bearing document: a missing or drifted
entry must fail boot, not degrade a page (spec S3.5).

The premise the whole feature rests on is that nothing here is generated. Every
value a provenance answer carries is either curated text a human wrote into
`data/corpus/provenance/*.md`, or a number measured from the frame/dataset at
answer time. These tests hold both halves: the parser refuses a malformed or
incomplete registry, and `validate_registry` refuses a registry whose claims no
longer match the files on disk or the facts in the frame.
"""
import shutil
import sys

sys.path.insert(0, "src")

import pytest

from ingest.normalise import normalise_all, _fact
from storage.frame import Frame
import provenance


# ---------------------------------------------------------------- helpers ---

def _registry_copy(tmp_path):
    """A writable copy of the real registry, so a test can drift ONE claim and
    assert the validator catches it (rather than hand-rolling a fake registry
    that shares none of the real file's shape)."""
    dst = tmp_path / "provenance"
    shutil.copytree(provenance._REGISTRY_DIR, dst)
    return dst


_FACTS = None


def _real_frame():
    """The real frame, normalised once for the module. Every test that widens it
    does so by copying the list (`list(frame.facts) + [...]`), so the shared
    facts are never mutated."""
    global _FACTS
    if _FACTS is None:
        _FACTS = normalise_all()
    return Frame(_FACTS)


# ------------------------------------------------------------ the registry ---

def test_registry_loads_and_covers_every_ingested_workbook():
    reg = provenance.load_registry()
    ingested = {s["id"] for s in reg["sources"] if s.get("ingested_as")}
    # every workbook the normaliser reads must be registered
    assert len(ingested) >= 7, ingested


def test_registry_hashes_match_the_files_on_disk():
    # a registry that claims a hash it cannot reproduce is worse than none
    provenance.validate_registry(_real_frame())


def test_missing_registry_file_fails_loud(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", tmp_path)
    with pytest.raises(provenance.ProvenanceError):
        provenance.load_registry()


def test_every_entry_carries_its_required_keys():
    reg = provenance.load_registry()
    for s in reg["sources"]:
        assert s["id"] and s["title"] and s["url"]
        if s.get("ingested_as"):
            # an ingested file must be hash-pinned and FY-scoped, or
            # validate_registry has nothing to check it against
            assert len(s["sha256"]) == 64
            assert s["covers"]
    for d in reg["derivations"]:
        assert d["id"] and d["title"] and d["kind"] in ("sheet", "convention")
        if d["kind"] == "sheet":
            assert d["sheet"] and d["measures"] and d["buckets"]
    for d in reg["decisions"]:
        assert d["id"] and d["title"] and d["date"] and d["decision"]
        assert d["prose"], f"{d['id']}: a decision with no rationale is not a decision"


def test_registry_ids_are_unique_within_a_file():
    reg = provenance.load_registry()
    for kind, entries in reg.items():
        ids = [e["id"] for e in entries]
        assert len(ids) == len(set(ids)), f"{kind}: duplicate id"


def test_a_section_without_a_key_block_fails_loud(tmp_path, monkeypatch):
    d = _registry_copy(tmp_path)
    (d / "sources.md").write_text(
        "# Sources\n\n## A source with no key block\n\nJust prose.\n",
        encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError):
        provenance.load_registry()


def test_a_malformed_key_line_fails_loud(tmp_path, monkeypatch):
    d = _registry_copy(tmp_path)
    (d / "sources.md").write_text(
        "# Sources\n\n## Broken\n\n```prov\nid: broken\nthis line has no key\n```\n",
        encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError):
        provenance.load_registry()


def test_a_missing_required_key_fails_loud(tmp_path, monkeypatch):
    d = _registry_copy(tmp_path)
    (d / "decisions.md").write_text(
        "# Decisions\n\n## No date\n\n```prov\nid: x\ntitle: X\n"
        "decision: Something\n```\n\nProse.\n", encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError):
        provenance.load_registry()


# ----------------------------------------------------------- the validator ---

def test_a_drifted_workbook_hash_fails_validation(tmp_path, monkeypatch):
    d = _registry_copy(tmp_path)
    text = (d / "sources.md").read_text(encoding="utf-8")
    real = provenance.load_registry()["sources"]
    pinned = next(s["sha256"] for s in real if s.get("ingested_as"))
    (d / "sources.md").write_text(text.replace(pinned, "0" * 64), encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.validate_registry(_real_frame())
    assert "sha256" in str(exc.value)


def test_a_missing_workbook_fails_validation(tmp_path, monkeypatch):
    d = _registry_copy(tmp_path)
    text = (d / "sources.md").read_text(encoding="utf-8")
    real = provenance.load_registry()["sources"]
    path = next(s["ingested_as"] for s in real if s.get("ingested_as"))
    (d / "sources.md").write_text(
        text.replace(f"ingested_as: {path}", "ingested_as: data/sources/gone.xlsx"),
        encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError):
        provenance.validate_registry(_real_frame())


def test_a_financial_year_no_source_covers_fails_validation():
    # a new workbook ingested without a registry entry brings a new FY with it;
    # that is the drift the coverage check exists to catch
    frame = _real_frame()
    frame = Frame(list(frame.facts) + [
        _fact("A", "A", "2026-27", None, "requests", "received", "total", 1.0)])
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.validate_registry(frame)
    assert "2026-27" in str(exc.value)


def test_a_measure_with_no_derivation_fails_validation():
    frame = _real_frame()
    frame = Frame(list(frame.facts) + [
        _fact("A", "A", "2024-25", None, "requests", "charges_collected", "total", 1.0)])
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.validate_registry(frame)
    assert "charges_collected" in str(exc.value)


def test_an_unknown_frame_check_fails_loud(tmp_path, monkeypatch):
    d = _registry_copy(tmp_path)
    text = (d / "decisions.md").read_text(encoding="utf-8")
    assert "frame_check:" in text, "the registry should machine-check at least one decision"
    (d / "decisions.md").write_text(
        text.replace("frame_check:", "frame_check: not_a_real_check\nunused:", 1),
        encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.validate_registry(_real_frame())
    assert "not_a_real_check" in str(exc.value)


def test_a_decision_number_that_no_longer_matches_the_frame_fails_validation(
        tmp_path, monkeypatch):
    d = _registry_copy(tmp_path)
    text = (d / "decisions.md").read_text(encoding="utf-8")
    assert "check_applicant: 34418" in text
    (d / "decisions.md").write_text(
        text.replace("check_applicant: 34418", "check_applicant: 34419"),
        encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.validate_registry(_real_frame())
    assert "34419" in str(exc.value)


# -------------------------------------------------------------- describe() ---

def test_describe_without_a_key_returns_registry_only():
    out = provenance.describe(_real_frame())
    assert out["sources"] and out["decisions"] and out["derivations"]
    assert "figure" not in out
    assert "dataset" not in out


def test_describe_with_a_figure_key_adds_the_live_layer():
    frame = _real_frame()
    out = provenance.describe(frame, key="requests_received_trend")
    fig = out["figure"]
    assert fig["key"] == "requests_received_trend"
    assert fig["source_rows"] > 0
    assert len(fig["rows_hash"]) == 64
    # the live layer must agree with the catalog, not restate the registry
    from stats.catalog import foi_stats
    assert fig["rows_hash"] == foi_stats(frame, "requests_received_trend")["rows_hash"]


def test_describe_rejects_an_unknown_key():
    with pytest.raises(KeyError):
        provenance.describe(_real_frame(), key="not_a_real_key")


def test_the_live_layer_is_explicit_that_it_describes_the_default_view():
    """The page ships the whole foi_stats dict into window.__pageData while
    shipping facts for EVERY financial year, and the chart engine re-derives on
    the client for whatever filter the reader picks. So a row count and hash
    printed beside a filtered chart would be a false claim. The live layer has
    to say, in the payload, that it describes the DEFAULT view."""
    frame = _real_frame()
    fig = provenance.describe(frame, key="requests_received_trend")["figure"]
    assert fig["applies_to"] == "default_view"
    assert "default view" in fig["qualifier"].lower()
    assert "filter" in fig["qualifier"].lower()
    # and the default view is described in machine-readable form, measured from
    # the rows themselves — not a sentence a reader has to parse
    assert fig["default_view"]["financial_years"] == [
        "2019-20", "2020-21", "2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]
    assert fig["default_view"]["buckets"] == ["total"]


def test_the_live_layer_names_a_top_n_figures_ranking_year():
    # a top-N is drawn for ONE financial year; the client's FY filter redraws it
    # for a different one, so the year the basis covers has to be in the payload
    fig = provenance.describe(_real_frame(), key="received_top20")["figure"]
    assert fig["default_view"]["financial_years"] == ["2024-25"]
    assert fig["kind"] == "top_n"


def test_describe_with_a_stat_key_adds_the_live_layer():
    frame = _real_frame()
    out = provenance.describe(frame, key="requests_received_q1")
    from stats.catalog import foi_stats
    assert out["figure"]["basis"] == "single_quarter"
    assert out["figure"]["rows_hash"] == foi_stats(frame, "requests_received_q1")["rows_hash"]


def test_describe_passes_the_dataset_snapshot_through():
    snapshot = {"id": 7, "canonical_hash": "a" * 64, "fact_count": 54602}
    out = provenance.describe(_real_frame(), dataset=snapshot)
    assert out["dataset"] == snapshot


def test_describe_carries_no_generated_prose():
    """Nothing in a provenance answer may be authored at answer time: every
    prose string in the registry layer must appear verbatim in the curated
    markdown on disk."""
    out = provenance.describe(_real_frame(), key="requests_received_trend")
    files = "\n".join((provenance._REGISTRY_DIR / n).read_text(encoding="utf-8")
                      for n in ("sources.md", "derivations.md", "decisions.md"))
    for kind in ("sources", "derivations", "decisions"):
        for entry in out[kind]:
            assert entry["prose"] in files
            assert entry["title"] in files


# ------------------------------------------------------------------- boot ---

def test_boot_refuses_to_serve_on_a_missing_registry(tmp_path, monkeypatch):
    """A provenance drift is a boot failure, not a degraded page — the same
    discipline as the golden gate it runs behind."""
    import server.app as app_mod
    saved = (app_mod._FRAME, app_mod._PAGES)
    app_mod._FRAME, app_mod._PAGES = None, None
    try:
        monkeypatch.setattr(provenance, "_REGISTRY_DIR", tmp_path)
        with pytest.raises(provenance.ProvenanceError):
            app_mod.create_app()
        assert app_mod._FRAME is None, "a frame that failed validation must not be cached"
    finally:
        app_mod._FRAME, app_mod._PAGES = saved
