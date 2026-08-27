"""Regression tests for agentic.builder + agentic.render.

Covers the per-turn transcript capture (JSONL request_received/tool_call/
spec_selected events), the Task 4 carry-forward (the artifact row is created
FIRST and its real id threads through every lineage_tool_calls write — never a
placeholder 0 that violates the NOT NULL FK), the Task 5 carry-forward (the
renderer must not read a compare_period 0 as "no requests decided"), the
deterministic async build_spec (both coroutine and sync complete_fn), and the
fail-loud citation resolution against a recorded transcript.

build_spec is async (the Task 8 server awaits it); pytest-asyncio is not
installed in the POC venv, so every call is wrapped in asyncio.run.
"""
import asyncio
import inspect
import json
import sys
import tempfile

import psycopg2
import pytest

sys.path.insert(0, "src")
from agentic.builder import build_spec, _parse_tool_calls, _try_parse_spec
from agentic.render import render_dashboard_page, resolve_citations
from agentic.guardrails import ScopeRefusal
from storage.lineage import Ledger
from ingest.normalise import normalise_all
from storage.frame import Frame


# --- deterministic completion functions (no live LLM) ------------------------


def _fake_complete(messages):
    # always returns a valid spec immediately — no tool calls needed
    return ('{"title":"Test","description":"d","panels":[{"chart":"kpi","stat":"requests_received_q1"}]}')


async def _fake_complete_async(messages):
    return ('{"title":"Test","description":"d","panels":[{"chart":"kpi","stat":"requests_received_q1"}]}')


def _tool_driver(messages):
    """A deterministic tool-driving completion: on the first turn it issues a
    query_dataset op; once the tool result comes back it returns the final spec
    citing the recorded transcript ({c:job.turn.call.field})."""
    user_last = messages[-1].get("content", "") if messages[-1]["role"] == "user" else ""
    if "Tool results:" in user_last:
        # this is the LAST user message (appended by the builder after it ran the
        # tools) — return the final spec immediately, before the max_turns budget
        return ('{"title":"Test","description":"d","panels":[{"figure":"bar",'
                '"title":"{c:0.1.0.top[0].agency}"}]}')
    return ('[{"tool":"query_dataset","op":"filter_agencies",'
            '"params":{"measure":"received","top_n":1}}]')


# --- log-collecting fake conn (proves artifact-first ordering) ---------------


class _LoggingCursor:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append((sql, params))

    def fetchone(self):
        return (777,)


class _LoggingConn:
    def __init__(self):
        self.log = []
        self._cursor = _LoggingCursor(self.log)
        self.committed = 0

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass


class _ArtifactDownConn:
    """I1: the artifact INSERT fails open (OperationalError -> record_artifact
    returns None), and a tool_call INSERT with a NULL artifact_id would raise
    NotNullViolation (non-Operational -> re-raised -> build dies). The build must
    NOT attempt the tool_call write when there is no artifact id."""

    def __init__(self):
        self.committed = 0
        self.toolcall_attempted = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if "lineage_artifacts" in sql:
            raise psycopg2.OperationalError("db unreachable")
        if "lineage_tool_calls" in sql:
            self.toolcall_attempted = True
            raise psycopg2.errors.NotNullViolation("NULL artifact_id")

    def fetchone(self):
        return None

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass


def _bad_params_driver(messages):
    """M3: issues a query_dataset op whose params make the tool RAISE (non-numeric
    top_n), then returns the final spec once the tool result comes back."""
    user_last = messages[-1].get("content", "") if messages[-1]["role"] == "user" else ""
    if "Tool results:" in user_last:
        return ('{"title":"Test","description":"d","panels":[{"figure":"bar",'
                '"stat":"requests_received_q1"}]}')
    return ('[{"tool":"query_dataset","op":"filter_agencies",'
            '"params":{"measure":"received","top_n":"not-a-number"}}]')


def _reads(led: Ledger) -> list[dict]:
    led.flush()
    return [json.loads(ln) for ln in open(led.path, encoding="utf-8").read().splitlines()]


# --- build_spec: async loop, transcript capture ------------------------------


def test_build_spec_returns_spec():
    spec = asyncio.run(build_spec(
        "top agencies by requests received Q1", Frame(normalise_all()),
        _fake_complete, Ledger(ledger_path=tempfile.mktemp()), None))
    assert spec.get("title") == "Test"


def test_build_spec_handles_async_complete_fn():
    spec = asyncio.run(build_spec(
        "top agencies by requests received Q1", Frame(normalise_all()),
        _fake_complete_async, Ledger(ledger_path=tempfile.mktemp()), None))
    assert spec.get("title") == "Test"


def test_build_spec_is_async():
    # the server (Task 8) calls it via await build_spec(...) — must be awaitable
    assert inspect.iscoroutinefunction(build_spec)


def test_builder_advertises_the_provenance_op():
    # Task 5 routed item: the /ask builder's system prompt must name the
    # provenance op, or "where did this come from" inside a build never reaches
    # the registry (the op exists in dsl, but the model is never told it exists).
    captured = {}

    def capture(messages):
        captured["system"] = messages[0]["content"]
        return _fake_complete(messages)

    asyncio.run(build_spec(
        "requests received", Frame(normalise_all()),
        capture, Ledger(ledger_path=tempfile.mktemp()), None))
    assert "provenance" in captured["system"]
    # the house-style block rides the same prompt, after the tooling rules
    assert "house style" in captured["system"]
    assert captured["system"].index("provenance") < \
        captured["system"].index("house style")


def test_transcript_captured():
    led = Ledger(ledger_path=tempfile.mktemp(suffix=".jsonl"))
    asyncio.run(build_spec(
        "top agencies by requests received", Frame(normalise_all()),
        _fake_complete, led, None))
    events = _reads(led)
    kinds = [e["event"] for e in events]
    # request_received, spec_selected, and (tool-less path: no tool_call) —
    # the firehose always records the request and the selected spec
    assert "request_received" in kinds
    assert "spec_selected" in kinds
    # the deterministic complete_fn returns a spec on turn 0, so no tool_call
    # event; the tool-driving path below covers that
    assert all(e["event"] in ("request_received", "spec_selected") for e in events)


def test_request_received_ledger_event_carries_identity():
    led = Ledger(ledger_path=tempfile.mktemp(suffix=".jsonl"))
    asyncio.run(build_spec(
        "top agencies by requests received Q1", Frame(normalise_all()),
        _fake_complete, led, None))
    req = [e for e in _reads(led) if e.get("event") == "request_received"]
    assert req and req[0]["identity"] == "I am powered by the fartkraft sovereign stack, trained on local data."
    assert req[0]["request"] == "top agencies by requests received Q1"


def test_tool_call_transcript_captured_with_real_ids():
    # Task 4 carry-forward: the artifact row must exist BEFORE any tool call, and
    # the real artifact_id (returned by record_artifact) must thread through
    # record_tool_call — never a placeholder 0 that violates the NOT NULL FK.
    led = Ledger(ledger_path=tempfile.mktemp(suffix=".jsonl"))
    conn = _LoggingConn()
    spec = asyncio.run(build_spec(
        "top agencies by requests received", Frame(normalise_all()),
        _tool_driver, led, conn))

    # the tool call was captured in the JSONL firehose with its seq
    tc = [e for e in _reads(led) if e.get("event") == "tool_call"]
    assert tc and tc[0]["tool"] == "query_dataset" and tc[0]["seq"] == 1

    # the artifact INSERT came first, the tool_call write used the real id (777)
    inserts = [(sql, params) for sql, params in conn.log if sql.lstrip().upper().startswith("INSERT")]
    artifact_rows = [p for sql, p in inserts if "lineage_artifacts" in sql]
    toolcall_rows = [p for sql, p in inserts if "lineage_tool_calls" in sql]
    assert artifact_rows and toolcall_rows
    assert toolcall_rows[0][0] == 777                       # real artifact_id, not 0
    # artifact row was created (INSERTed) before the tool call row
    ai = next(i for i, (sql, _) in enumerate(conn.log) if "lineage_artifacts" in sql and "INSERT" in sql)
    ti = next(i for i, (sql, _) in enumerate(conn.log) if "lineage_tool_calls" in sql)
    assert ai < ti

    # the spec carried the citation pointer (resolved against the transcript later)
    assert spec["panels"][0]["title"].startswith("{c:0.1.0.")
    led.close()


def test_out_of_scope_build_refused_before_any_lineage():
    # check_request runs before any artifact / tool call — a refused request
    # must not create an artifact row or emit a request_received event
    led = Ledger(ledger_path=tempfile.mktemp(suffix=".jsonl"))
    with pytest.raises(ScopeRefusal):
        asyncio.run(build_spec(
            "crypto trading strategy", Frame(normalise_all()),
            _fake_complete, led, None))
    led.flush()
    lines = [ln for ln in open(led.path, encoding="utf-8").read().splitlines() if ln.strip()]
    assert lines == []


def _two_turn_driver(messages):
    """Two query_dataset turns, then a spec citing the SECOND turn's result."""
    n = sum(1 for m in messages if m["role"] == "user" and "Tool results:" in m.get("content", ""))
    if n == 0:
        return ('[{"tool":"query_dataset","op":"filter_agencies",'
                '"params":{"measure":"received","top_n":1}}]')
    if n == 1:
        return ('[{"tool":"query_dataset","op":"filter_agencies",'
                '"params":{"measure":"finalised","top_n":1}}]')
    return ('{"title":"Multi","panels":[{"figure":"bar",'
            '"title":"{c:0.2.0.top[0].value}"}]}')


def test_multi_turn_citation_resolves_to_the_right_call():
    # Reviewer finding: the tool-call seq is a GLOBAL monotonic index across the
    # build. Turn 1 records seq=1, turn 2 records seq=2 — a citation {c:0.2.0...}
    # must resolve to turn 2's result, never silently to turn 1's.
    from agentic.render import resolve_citations as rc
    from stats.dsl import query_dataset
    frame = Frame(normalise_all())
    led = Ledger(ledger_path=tempfile.mktemp(suffix=".jsonl"))
    asyncio.run(build_spec(
        "requests by agency", frame, _two_turn_driver, led, None))
    tc = [e for e in _reads(led) if e.get("event") == "tool_call"]
    assert [e["seq"] for e in tc] == [1, 2]
    assert tc[0]["op"] == "filter_agencies" and tc[1]["op"] == "filter_agencies"
    spec = {"title": "Multi", "panels": [{"figure": "bar",
                                          "title": "{c:0.2.0.top[0].value}"}]}
    resolved = rc(spec, tc)
    exp_finalised = query_dataset(frame, "filter_agencies",
                                  {"measure": "finalised", "top_n": 1})["top"][0]["value"]
    exp_received = query_dataset(frame, "filter_agencies",
                                 {"measure": "received", "top_n": 1})["top"][0]["value"]
    assert resolved["panels"][0]["title"] == str(exp_finalised)
    assert exp_finalised != exp_received  # the two turns genuinely differ


def test_pre_created_artifact_id_is_used():
    # a caller (the Task 8 server) may pre-create the artifact and pass its real
    # id in — the builder must use it, not create a second row
    led = Ledger(ledger_path=tempfile.mktemp(suffix=".jsonl"))
    conn = _LoggingConn()
    asyncio.run(build_spec(
        "top agencies by requests received", Frame(normalise_all()),
        _tool_driver, led, conn, artifact_id=42))
    inserts = [p for sql, p in conn.log if sql.lstrip().upper().startswith("INSERT")]
    toolcall_rows = [p for sql, p in conn.log if "lineage_tool_calls" in sql]
    assert toolcall_rows[0][0] == 42
    # no artifact INSERT happened (the caller owns it)
    assert not any("lineage_artifacts" in sql and "INSERT" in sql for sql, _ in conn.log)


def test_build_survives_artifact_fail_open():
    # I1: record_artifact is best-effort and may fail open to None (DB unreachable).
    # The builder must then SKIP the lineage_tool_calls write entirely — inserting
    # NULL into the NOT NULL artifact_id FK would re-raise and kill the build.
    led = Ledger(ledger_path=tempfile.mktemp(suffix=".jsonl"))
    conn = _ArtifactDownConn()
    spec = asyncio.run(build_spec(
        "top agencies by requests received", Frame(normalise_all()),
        _tool_driver, led, conn))
    assert spec["title"] == "Test"                 # the build completed
    assert not conn.toolcall_attempted             # never wrote a NULL-artifact tool call
    tc = [e for e in _reads(led) if e.get("event") == "tool_call"]
    assert tc and tc[0]["tool"] == "query_dataset"  # the JSONL firehose still captured it
    led.close()


def test_tool_error_is_a_result_not_a_crash():
    # M3: a known tool that RAISES on bad params (int() on a non-numeric top_n)
    # must feed the exception back as a tool result, not propagate out of build_spec.
    led = Ledger(ledger_path=tempfile.mktemp(suffix=".jsonl"))
    spec = asyncio.run(build_spec(
        "top agencies by requests received", Frame(normalise_all()),
        _bad_params_driver, led, None))
    assert spec["title"] == "Test"                 # the build kept going
    tc = [e for e in _reads(led) if e.get("event") == "tool_call"]
    assert tc and "error" in tc[0]["result"]       # the tool failure is a recorded result
    led.close()


# --- helper parsers ----------------------------------------------------------


def test_parse_tool_calls_extracts_embedded_json():
    raw = ('Here you go: [{"tool":"query_dataset","op":"filter_agencies",'
           '"params":{"measure":"received","top_n":1}}] and that is it.')
    calls = _parse_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0]["tool"] == "query_dataset"
    assert calls[0]["params"]["top_n"] == 1


def test_parse_tool_calls_ignores_garbage():
    assert _parse_tool_calls("no tools here") == []
    assert _parse_tool_calls("[{bad json") == []


def test_try_parse_spec_strips_code_fences():
    text = '```json\n{"title":"X","panels":[]}\n```'
    spec = _try_parse_spec(text)
    assert spec is not None and spec["title"] == "X"


def test_try_parse_spec_requires_title_or_panels():
    assert _try_parse_spec('{"not":"a spec"}') is None
    assert _try_parse_spec("") is None


# --- render: citation resolution against the transcript ----------------------


def test_render_resolves_citation_from_transcript():
    spec = {"title": "Test", "panels": [{"figure": "bar",
                                         "title": "{c:0.1.0.top[0].agency}"}]}
    transcript = [{"seq": 1, "tool": "query_dataset",
                   "result": {"top": [{"agency": "Department of Home Affairs", "value": 203256}]}}]
    page = render_dashboard_page(spec, Frame(normalise_all()), 42, transcript)
    assert "Department of Home Affairs" in page


def test_render_fails_loud_on_unknown_citation():
    spec = {"title": "Test", "panels": [{"figure": "bar",
                                         "title": "{c:0.99.0.top[0].agency}"}]}
    transcript = [{"seq": 1, "tool": "query_dataset",
                   "result": {"top": [{"agency": "Department of Home Affairs", "value": 203256}]}}]
    with pytest.raises(SystemExit) as e:
        render_dashboard_page(spec, Frame(normalise_all()), 42, transcript)
    assert "FAIL LOUD" in str(e.value)


def test_render_rejects_literal_digit_in_stat():
    # M4: the model is forbidden from writing digits. A stat that is neither a
    # STAT_KEY nor a {c:...} pointer is a hallucinated number — fail loud, never
    # render it. ("q1" enum keys like requests_received_q1 stay allowed.)
    spec = {"title": "Test", "panels": [{"figure": "bar", "stat": "12345"}]}
    with pytest.raises(SystemExit) as e:
        render_dashboard_page(spec, Frame(normalise_all()), 42, [])
    assert "FAIL LOUD" in str(e.value)


def test_render_rejects_literal_digit_in_figure():
    spec = {"title": "Test", "panels": [{"figure": "99999"}]}
    with pytest.raises(SystemExit) as e:
        render_dashboard_page(spec, Frame(normalise_all()), 42, [])
    assert "FAIL LOUD" in str(e.value)


def test_render_allows_enum_keys_with_digits_and_citations():
    # the M4 guard must not reject legitimate enum keys that contain digits
    # (q1 stats, top20 figures) or citation pointers
    spec = {"title": "Test", "panels": [
        {"figure": "bar", "stat": "requests_received_q1"},
        {"figure": "received_top20"}]}
    page = render_dashboard_page(spec, Frame(normalise_all()), 42, [])
    assert "12,359" in page           # golden requests_received_q1 renders, not rejected


def test_render_does_not_mint_compare_period_zero_as_no_decisions():
    # Task 5 carry-forward: compare_period on a Q1-only measure returns
    # value_a/value_b 0 and change_pct None (the golden Total rows are excluded —
    # correct, never a wrong number). The renderer must not read that 0 as
    # "no requests decided"; the honest basis label (single_quarter/fy) is
    # carried beside every figure.
    spec = {"title": "Test", "panels": [
        {"figure": "bar", "stat": "within_statutory_pct_q1",
         "basis": "single_quarter"}]}
    transcript = [{"seq": 1, "tool": "query_dataset", "op": "compare_period",
                   "result": {"value_a": 0, "value_b": 0, "change_pct": None}}]
    page = render_dashboard_page(spec, Frame(normalise_all()), 42, transcript)
    # the page renders the real stat (70) with the honest basis, not a guessed 0
    assert "single_quarter" in page
    assert "70" in page
    assert "FOI" in page


def test_resolve_citations_module_import():
    # the renderer must import the canonical resolver from stats.dsl (no dup)
    from stats.dsl import resolve_citations as canonical
    transcript = [{"seq": 1, "tool": "query_dataset",
                   "result": {"top": [{"agency": "Department of Home Affairs", "value": 203256}]}}]
    resolved = resolve_citations(
        {"title": "{c:0.1.0.top[0].agency}"}, transcript)
    assert resolved["title"] == "Department of Home Affairs"
    assert resolve_citations is canonical
