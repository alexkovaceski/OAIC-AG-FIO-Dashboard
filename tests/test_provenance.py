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


@pytest.fixture(autouse=True)
def _reset_validated_registry():
    """`provenance._VALIDATED` is process-wide state (I1): validate_registry
    stashes the registry it accepted and describe() serves that copy. Left set
    between tests it would make every test after the first depend on ORDER — a
    describe test would pass on a verdict some earlier test earned rather than
    on the registry it set up itself. Cleared either side, so each test states
    its own precondition."""
    provenance._VALIDATED = None
    yield
    provenance._VALIDATED = None


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


def test_a_duplicate_id_fails_loud(tmp_path, monkeypatch):
    """This replaces an assertion that could not fail. The old version loaded
    the real registry and asserted its ids were unique — but `_parse_file`
    raises on a duplicate, so `load_registry` can only ever RETURN unique ids
    and the assertion was true of every input, drifted or not. The check is
    only worth having if a duplicate is actually introduced."""
    d = _registry_copy(tmp_path)
    text = (d / "sources.md").read_text(encoding="utf-8")
    assert text.count("id: workbook-2020-21") == 1
    (d / "sources.md").write_text(
        text.replace("id: workbook-2020-21", "id: workbook-2019-20"),
        encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.load_registry()
    assert "duplicate id" in str(exc.value)


def test_an_unclosed_fence_fails_loud(tmp_path, monkeypatch):
    """A half-written key block must not silently swallow the entries after it.
    Dropping ONE closing fence leaves the file with an odd number, so the fence
    state is still open at EOF and the parser says so instead of returning a
    registry that is missing whatever the open fence ate."""
    d = _registry_copy(tmp_path)
    text = (d / "sources.md").read_text(encoding="utf-8")
    assert text.count("```") % 2 == 0, "the real registry should balance"
    broken = text.replace("verified: 2026-08-26\n```\n", "verified: 2026-08-26\n", 1)
    assert broken.count("```") == text.count("```") - 1
    (d / "sources.md").write_text(broken, encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.load_registry()
    assert "unclosed" in str(exc.value)


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


def test_a_stale_covers_year_fails_validation(tmp_path, monkeypatch):
    """`covers` ties a workbook to the facts it is responsible for, and it is
    the one source key with no shape rule to catch a typo: any comma-separated
    string parses. A year the frame does not carry means the registry is
    describing an ingest that is not the one running.

    The stale year is ADDED, not substituted, and that is load-bearing.
    Replacing 2024-25 with 2027-28 also leaves 2024-25 uncovered, so the
    COVERAGE check fires and the test would have passed with the stale-year
    check deleted — green for a reason other than the one it was written for,
    which is the defect class this whole review round is about (confirmed by
    mutation: with `stale = []` forced, the substituting version still passed).
    Adding a year keeps coverage complete, so only the stale-year check can
    raise, and the assertion names that check's own wording."""
    d = _registry_copy(tmp_path)
    text = (d / "sources.md").read_text(encoding="utf-8")
    assert "covers: 2024-25\n" in text
    (d / "sources.md").write_text(
        text.replace("covers: 2024-25\n", "covers: 2024-25, 2027-28\n", 1),
        encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.validate_registry(_real_frame())
    assert "claims to cover" in str(exc.value)
    assert "2027-28" in str(exc.value)


def test_a_drifted_byte_count_fails_validation(tmp_path, monkeypatch):
    """`bytes` is the claim sources.md leans on for the six workbooks
    data.gov.au publishes no hash for, so it has to be checked, not decorative."""
    d = _registry_copy(tmp_path)
    text = (d / "sources.md").read_text(encoding="utf-8")
    real = next(s for s in provenance.load_registry()["sources"]
                if s.get("bytes"))
    (d / "sources.md").write_text(
        text.replace(f"bytes: {real['bytes']}",
                     f"bytes: {int(real['bytes']) + 1}", 1), encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.validate_registry(_real_frame())
    assert "byte count drift" in str(exc.value)


def test_a_drifted_bucket_fails_validation(tmp_path, monkeypatch):
    """The request-type buckets are what every Type filter on the site selects
    on. A derivation that claims a fourth one is describing a frame this is not."""
    d = _registry_copy(tmp_path)
    text = (d / "derivations.md").read_text(encoding="utf-8")
    assert "buckets: personal, other, total\n" in text
    (d / "derivations.md").write_text(
        text.replace("buckets: personal, other, total\n",
                     "buckets: personal, other, total, aggregate\n", 1),
        encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError) as exc:
        provenance.validate_registry(_real_frame())
    assert "request-type drift" in str(exc.value)


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


# ------------------------------------------ the validated-registry stash (I1) ---

def test_describe_serves_the_validated_registry_not_a_file_edited_after_boot(
        tmp_path, monkeypatch):
    """I1. `load_registry` re-reads the files on every call and enforces SHAPE
    only, so a registry edited after boot parses cleanly and used to be served
    straight to a reader as validated provenance — hash, coverage, measures and
    frame_check all unre-checked since start-up. The edit below is one
    `validate_registry` would REJECT; describe must serve the validated copy
    instead of carrying it."""
    frame = _real_frame()
    real = next(s for s in provenance.load_registry()["sources"]
                if s.get("ingested_as"))
    provenance.validate_registry(frame)          # the boot gate, real registry
    d = _registry_copy(tmp_path)
    text = (d / "sources.md").read_text(encoding="utf-8")
    (d / "sources.md").write_text(text.replace(real["sha256"], "0" * 64),
                                  encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    # the drifted file still PARSES — which is exactly why the shape checks
    # alone were never the guarantee
    assert any(s.get("sha256") == "0" * 64
               for s in provenance.load_registry()["sources"])
    served = {s["id"]: s.get("sha256") for s in provenance.describe(frame)["sources"]}
    assert served[real["id"]] == real["sha256"]
    assert "0" * 64 not in served.values()


def test_describe_before_any_validation_validates_rather_than_serving(
        tmp_path, monkeypatch):
    """I1, the other half. With nothing stashed, describe must not fall back to
    reading the file and serving it. It runs the same gate boot runs, against
    the frame it was handed, so a drifted registry raises here exactly as it
    would at start-up — the answer is never an unvalidated one."""
    d = _registry_copy(tmp_path)
    real = next(s for s in provenance.load_registry()["sources"]
                if s.get("ingested_as"))
    text = (d / "sources.md").read_text(encoding="utf-8")
    (d / "sources.md").write_text(text.replace(real["sha256"], "0" * 64),
                                  encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    assert provenance._VALIDATED is None
    with pytest.raises(provenance.ProvenanceError):
        provenance.describe(_real_frame())


def test_a_failed_validation_stashes_nothing(tmp_path, monkeypatch):
    """The stash is what describe serves, so it must be written only after
    every check has passed — a registry that raised halfway through must not
    leave a partially-checked copy behind for the next reader."""
    d = _registry_copy(tmp_path)
    real = next(s for s in provenance.load_registry()["sources"]
                if s.get("ingested_as"))
    text = (d / "sources.md").read_text(encoding="utf-8")
    (d / "sources.md").write_text(text.replace(real["sha256"], "0" * 64),
                                  encoding="utf-8")
    monkeypatch.setattr(provenance, "_REGISTRY_DIR", d)
    with pytest.raises(provenance.ProvenanceError):
        provenance.validate_registry(_real_frame())
    assert provenance._VALIDATED is None


def test_the_payload_is_a_copy_so_a_caller_cannot_edit_the_validated_registry():
    frame = _real_frame()
    provenance.validate_registry(frame)
    out = provenance.describe(frame)
    out["sources"].append({"id": "not-a-real-source"})
    assert all(s["id"] != "not-a-real-source"
               for s in provenance.describe(frame)["sources"])


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


# ----------------------------------------- the three qualifier classes (I2) ---

_GOLDEN_Q1_KEYS = ("requests_received_q1", "requests_finalised_q1", "decided_q1",
                   "within_statutory_pct_q1", "granted_full_share_q1",
                   "granted_part_share_q1", "refused_share_q1", "withdrawn_q1")


def test_every_qualifier_names_the_view_its_own_payload_claims():
    """THE STRUCTURAL ONE. Three classes of key carry three different
    sentences, and before `_qualifier` all three contained the words "default
    view" for three unrelated reasons — one said "the default view of <key>",
    another said "the page's default view". A guard asserting that substring
    passed on all three BY COINCIDENCE, and a reword of any one of them could
    have dropped the view silently while the guard stayed green.

    So this does not look for a literal. It reads `applies_to` out of the
    payload, maps it through the same table the builder used, and requires the
    result in the qualifier — the sentence and the machine-readable field
    cannot drift apart, and every key in the catalog is covered, not a sample.
    """
    from stats.catalog import FIG_KEYS, STAT_KEYS
    frame = _real_frame()
    for key in FIG_KEYS + STAT_KEYS:
        fig = provenance.describe(frame, key=key)["figure"]
        expected = provenance._APPLIES_TO_PROSE[fig["applies_to"]]
        assert expected in fig["qualifier"], key


def test_a_qualifier_that_does_not_name_its_view_cannot_be_built():
    """The refusal is the guarantee. `_qualifier` is the only constructor, so a
    future sentence that forgets the view is a ProvenanceError at build time
    rather than a false claim in front of a reader."""
    with pytest.raises(provenance.ProvenanceError):
        provenance._qualifier("default_view", "A sentence with no view in it.")
    with pytest.raises(provenance.ProvenanceError):
        provenance._qualifier("filtered_view", "Describes {view}.")
    assert (provenance._qualifier("default_view", "Describes {view}.")
            == "Describes the default view.")


def test_no_stat_key_is_ever_re_derived_in_the_browser():
    """The premise under both stat qualifiers below, asserted rather than
    assumed. `window.__pageData.figures` is built from PAGE_FIGURE_KEYS and
    foi-charts.js reads figures ONLY from there, so a key absent from every
    page's list is never re-derived under a filter — it is server-rendered HTML
    with a fixed basis. If a stat key is ever added to a page's figure list,
    this fails and the qualifier has to be revisited with it."""
    from site.pages import PAGE_FIGURE_KEYS
    from stats.catalog import STAT_KEYS
    shipped = {k for keys in PAGE_FIGURE_KEYS.values() for k in keys}
    assert not (shipped & set(STAT_KEYS)), sorted(shipped & set(STAT_KEYS))


def test_a_transcribed_q1_stat_names_its_transcription_not_a_filter_caveat():
    """I2. The eight golden Q1 keys are the one place on this platform where a
    value was READ OFF the OAIC's published dashboard rather than computed from
    a workbook. `pages.GOLDEN_SOURCE` already tells a reader that beside the
    tile; the provenance answer must not replace it with a filter caveat that
    is both weaker and — for a server-rendered tile — false."""
    frame = _real_frame()
    for key in _GOLDEN_Q1_KEYS:
        q = provenance.describe(frame, key=key)["figure"]["qualifier"]
        assert "transcribed" in q.lower(), key
        # it points at the entries that travel in the same payload, by the words
        # the renderer actually prints for them (see the id test below)
        assert "reference source" in q, key
        assert "curation decisions" in q, key
        # and it does NOT offer a browser re-derivation that cannot happen
        assert "in the browser" not in q, key


def test_no_qualifier_cites_a_registry_id_the_renderer_never_prints():
    """M3. The transcribed qualifier used to tell a reader that "the source
    entry `oaic-dashboard` and the curation decision `golden-q1-transcription`
    below record what was read and when". Measured 2026-08-27 across all 25
    reader-visible rows of a `decided_q1` answer, those two literals appeared in
    exactly ONE row: the qualifier itself. `report._registry_rows` composes
    every row from `title`, `url`, `covers`, `sha256`, `ingested_as` and `date`
    — never `id` — so the reader was told to look for a label that is not on the
    page.

    Asserted over every id in the registry and every key in the catalog rather
    than over the two literals, because the defect is the shape, not those two
    strings. Registry ids are hyphenated and catalog keys use underscores, so no
    key can collide with an id and make this pass by accident."""
    frame = _real_frame()
    from stats.catalog import FIG_KEYS, STAT_KEYS
    reg = provenance.load_registry()
    ids = [e["id"] for kind in ("sources", "derivations", "decisions")
           for e in reg[kind]]
    assert "oaic-dashboard" in ids and "golden-q1-transcription" in ids
    for key in FIG_KEYS + STAT_KEYS:
        q = provenance.describe(frame, key=key)["figure"]["qualifier"]
        for entry_id in ids:
            assert entry_id not in q, (key, entry_id)


def test_the_entries_a_transcribed_qualifier_points_at_travel_with_it():
    """A qualifier that sends a reader to "the reference source below" and "the
    curation decisions" is only useful if those entries are in the same answer.
    Named here by id, which is how the payload identifies them, even though the
    qualifier no longer quotes the ids at a reader."""
    payload = provenance.describe(_real_frame(), key="decided_q1")
    assert any(s["id"] == "oaic-dashboard" for s in payload["sources"])
    assert any(d["id"] == "golden-q1-transcription" for d in payload["decisions"])


def test_the_transcribed_qualifier_states_what_the_boot_check_compares():
    """I1. The qualifier said the service "re-sums those rows against the
    published figures", two sentences after naming "the OAIC's own published FOI
    dashboard" — so a member of the public read it as a re-verification against
    the OAIC at every boot.

    It is not. `Frame.golden_check` sums the frame's fy=2025-26 / quarter=1 /
    bucket=total rows per measure and compares each to
    `config.GOLDEN_Q1_FIGURES`; `normalise._golden_q1_facts` emits those rows
    FROM `GOLDEN_Q1_FIGURES`, one `_fact` per constant with value = the
    constant. This test measures that identity rather than asserting it, then
    requires the sentence to say what the check is against and to disclaim the
    re-read."""
    from config import GOLDEN_Q1_FIGURES
    from ingest.normalise import _golden_q1_facts, _GOLDEN_MEASURE
    # BOTH SIDES ARE THE SAME EIGHT NUMBERS — measured, not assumed
    emitted = {f["measure"]: f["value"] for f in _golden_q1_facts()}
    expected = {_GOLDEN_MEASURE[k]: float(v)
                for k, v in GOLDEN_Q1_FIGURES.items()}
    assert emitted == expected
    assert len(emitted) == 8

    frame = _real_frame()
    for key in _GOLDEN_Q1_KEYS:
        q = provenance.describe(frame, key=key)["figure"]["qualifier"]
        # says what it compares against
        assert "its own configuration" in q, key
        # and says, in the same breath, what it is NOT
        assert "not against the OAIC" in q, key
        assert "nothing here re-reads the dashboard" in q, key
        # the reintroduced overstatement, gone
        assert "against the published figures" not in q, key


def test_a_server_rendered_stat_does_not_promise_a_filter_that_cannot_reach_it():
    """I2. The old qualifier told EVERY stat reader that "any filter a reader
    sets re-derives what is drawn from the same published facts". That is true
    of a chart and false of a KPI tile or a movers table: neither is in
    __pageData.figures, so no filter re-derives either. Claiming otherwise
    sends a reader looking for a control that does not exist."""
    frame = _real_frame()
    for key in ("timeliness_slippage_corr", "refusal_rate_movers",
                "timeliness_movers", "refusal_rate_change_fy23_fy24"):
        q = provenance.describe(frame, key=key)["figure"]["qualifier"]
        assert "in the browser" not in q, key
        assert "re-derives what is drawn" not in q, key
        # it still says which view the count describes — that guarantee holds
        # for every key, only the reason differs
        assert "default view" in q.lower(), key
        # and no raw enum token in a sentence a member of the public reads
        assert "a fy basis" not in q, key


def test_a_chart_figure_keeps_the_default_view_wording():
    """The class split must not have quietly weakened the one qualifier that
    WAS correct: a chart really is re-derived in the browser under a filter."""
    q = provenance.describe(_real_frame(),
                            key="requests_received_trend")["figure"]["qualifier"]
    assert "default view" in q.lower()
    assert "in the browser" in q


def test_only_a_figure_some_page_ships_promises_browser_re_derivation():
    """M2. `FIG_KEYS` is not the set of figures a reader has a filter for.
    Measured 2026-08-27, three of the thirteen — refused_pct_trend,
    agency_contributions_received, agency_contributions_decided — are in no
    page's PAGE_FIGURE_KEYS, so no page ships them into
    window.__pageData.figures and nothing re-derives them in the browser. They
    are reachable only through the model-driven `provenance` op in stats.dsl,
    and there they still said "Any filter a reader sets re-derives the chart in
    the browser". Under-claiming rather than over-claiming, which is why a round
    hunting over-claims walked past it, but the same defect: a promise about a
    control that does not exist.

    The predicate is `key in shipped`, so this test dispatches the same way
    rather than listing the three keys, and a key added to a page flips its
    branch here without an edit."""
    from stats.catalog import FIG_KEYS
    frame = _real_frame()
    shipped = provenance._shipped_figure_keys()
    unshipped = sorted(set(FIG_KEYS) - shipped)
    assert unshipped, "if every figure key now ships, revisit the branch"
    for key in FIG_KEYS:
        q = provenance.describe(frame, key=key)["figure"]["qualifier"]
        if key in shipped:
            assert "in the browser" in q, key
        else:
            assert "in the browser" not in q, key
            assert "no filter re-derives it" in q, key
        # the guarantee that holds for every class, whichever branch ran
        assert "the default view" in q, key


def test_an_unshipped_figure_key_reaches_no_rendered_page():
    """The premise under the sentence above, measured against the rendered HTML
    rather than against PAGE_FIGURE_KEYS alone. A chart container is mounted by
    a hand-written per-page section carrying a LITERAL chart key, so a key could
    in principle reach a page without reaching that dict, and the branch would
    then withhold a filter caveat from a figure that has one."""
    from site.pages import render_all_pages
    from stats.catalog import FIG_KEYS
    frame = _real_frame()
    html = "\n".join(str(p) for p in render_all_pages(frame).values())
    for key in sorted(set(FIG_KEYS) - provenance._shipped_figure_keys()):
        assert key not in html, key


def test_two_unshipped_keys_are_aliases_of_a_chart_that_is_on_a_page():
    """Why the unshipped sentence says "no page ships this figure" and not "this
    chart is on no page". agency_contributions_received and _decided are
    spec-identical to received_top20 and decided_top20 — same kind, measure, n
    and default_fy, and the same rows_hash — and those two ARE drawn, so the
    stronger sentence would have been a fresh false claim in the fix for one.
    Only refused_pct_trend is drawn nowhere."""
    from stats.catalog import FIGURE_SPECS, foi_stats
    frame = _real_frame()
    shipped = provenance._shipped_figure_keys()
    for alias, real in (("agency_contributions_received", "received_top20"),
                        ("agency_contributions_decided", "decided_top20")):
        assert alias not in shipped and real in shipped
        assert FIGURE_SPECS[alias] == FIGURE_SPECS[real]
        assert (foi_stats(frame, alias)["rows_hash"]
                == foi_stats(frame, real)["rows_hash"])
    q = provenance.describe(frame,
                            key="agency_contributions_received")["figure"]["qualifier"]
    assert "on no page" not in q
    assert "not drawn on any page" not in q


def test_an_unshipped_figure_still_carries_its_measured_default_view():
    """The measured detail and the sentence split on DIFFERENT predicates, and
    that is deliberate. `report._registry_rows` marks which of the seven
    workbooks feed a figure using `default_view["financial_years"]` and
    `["measures"]`; without them it falls back to an unmarked list of all seven,
    which is the over-claim it exists to prevent. So moving the unshipped keys
    to the stat branch wholesale would have fixed the sentence and broken the
    rows. Only the closing clause dispatches on `shipped`."""
    fig = provenance.describe(_real_frame(),
                              key="agency_contributions_received")["figure"]
    view = fig["default_view"]
    assert view["financial_years"] == ["2024-25"]
    assert view["measures"] == ["received"]
    assert view["buckets"] == ["total"]
    assert view["distinct_agencies"] == 303
    assert fig["kind"] == "top_n"


def test_a_brace_in_a_template_cannot_break_a_qualifier():
    """M4. `_qualifier` substitutes with `str.replace`, not `str.format`, so a
    brace anywhere else in a template is copied through instead of being read as
    a field name. Correct and cheap — and until this test, UNCOVERED: swapping
    `replace` for `format` left the whole suite green, because every template
    `_live_layer` builds today happens to contain `{view}` and nothing else.

    That is the reason to pin it. The property is about the next template, not
    this one: every template here is an f-string over measured text, and the day
    one interpolates something less controlled, `format` turns a stray brace
    into a KeyError on a provenance answer while `replace` degrades it to a
    literal brace. Under `template.format(view=view)` the call below raises
    KeyError('n')."""
    out = provenance._qualifier(
        "default_view", "A basis of {n} rows describes {view}.")
    assert out == "A basis of {n} rows describes the default view."
    # a doubled brace is not an escape either — replace leaves it alone, where
    # format would collapse it to a single one
    assert (provenance._qualifier("default_view", "{{literal}} in {view}.")
            == "{{literal}} in the default view.")


def test_the_transcribed_basis_predicate_and_the_page_citation_agree():
    """M5. The module docstring used to call these "the same rule". They are
    not: this module dispatches on the basis ENUM (`stat["basis"] ==
    "single_quarter"`), while `pages._source_for_basis` tests for the substring
    "single quarter" inside a DISPLAY label produced by `pages._basis_label`.
    They coincide only because `_BASIS_LABEL` happens to map that one enum value
    to a label containing that substring; reword the label and the citation
    beside the tile detaches from the qualifier in this file, silently.

    So pin them. Over `config.WINDOW_MODES` rather than over the 25 catalog
    keys, because the enum is the whole domain both predicates read from — a
    basis value no key currently produces would still have to agree."""
    from config import WINDOW_MODES
    from site.pages import _basis_label, _source_for_basis
    assert "single_quarter" in WINDOW_MODES
    for mode in WINDOW_MODES:
        enum_says = mode == "single_quarter"
        label_says = _source_for_basis(_basis_label({"basis": mode})) is not None
        assert enum_says == label_says, (mode, _basis_label({"basis": mode}))


# ----------------------------------------------- what the scope sentence says ---

def test_the_scope_sentence_claims_no_portfolio_filter_not_every_portfolio():
    """M6. Measured 2026-08-27: 85 of requests_received_trend's 2,022 basis rows
    carry NO portfolio, and 2,295 of the frame's annual rows do (the
    `portfolio-capture` derivation records why). "Every portfolio" claims a
    completeness the rows do not have; what is true is that nothing was
    filtered out by portfolio."""
    from stats.catalog import _figure_source_rows
    frame = _real_frame()
    rows = _figure_source_rows(frame, "requests_received_trend")
    assert sum(1 for f in rows if not f["portfolio"]) > 0, \
        "if every basis row now carries a portfolio, revisit the wording"
    q = provenance.describe(frame, key="requests_received_trend")["figure"]["qualifier"]
    assert "no portfolio filter" in q
    assert "every portfolio" not in q


def test_a_top_n_scope_sentence_separates_the_ranking_basis_from_what_is_drawn():
    """`received_top20` consumes 303 rows over 303 agencies and draws 20 of
    them. "every reporting agency" beside a chart captioned "Top 20", with a
    source_rows of 303, reads as a contradiction unless the sentence says which
    number is which."""
    frame = _real_frame()
    fig = provenance.describe(frame, key="received_top20")["figure"]
    assert fig["source_rows"] == 303
    assert fig["default_view"]["distinct_agencies"] == 303
    assert "ranking basis" in fig["qualifier"]
    assert "top 20" in fig["qualifier"]


def test_a_multi_year_basis_says_what_its_agency_count_counts():
    """M5. The reader sees "across 433 reporting agencies" in the rendered
    answer, which reads as "433 agencies report" — it is the number of distinct
    NAMES across seven workbooks. A comment in the payload builder does not
    reach the reader; the qualifier does. A one-year top_n has no such gap, so
    it does not carry the sentence."""
    frame = _real_frame()
    trend = provenance.describe(frame, key="requests_received_trend")["figure"]
    assert len(trend["default_view"]["financial_years"]) == 7
    assert trend["default_view"]["distinct_agencies"] == 433
    assert "not the number reporting in any one year" in trend["qualifier"]
    top = provenance.describe(frame, key="received_top20")["figure"]
    assert len(top["default_view"]["financial_years"]) == 1
    assert "not the number reporting in any one year" not in top["qualifier"]


def test_a_financial_year_range_is_only_claimed_when_the_years_are_contiguous():
    """M7. "2019-20 to 2025-26" asserts every year in between, and the sentence
    used to build it from nothing but first-and-last of a set.
    `catalog._figure_source_rows` documents the case that falsifies that: an FY
    can be missing from a figure's basis while the chart still shows the year.
    On the real frame every basis is contiguous, so this is a unit test on the
    phrase itself."""
    assert provenance._fy_phrase([]) == "no financial year"
    assert provenance._fy_phrase(["2024-25"]) == "financial year 2024-25"
    assert (provenance._fy_phrase(["2019-20", "2020-21", "2021-22"])
            == "financial years 2019-20 to 2021-22")
    # the hole: 2021-22 missing. A range here would claim a year the hash does
    # not cover, so the years are listed instead.
    assert (provenance._fy_phrase(["2019-20", "2020-21", "2022-23"])
            == "financial years 2019-20, 2020-21, 2022-23")


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
