"""Regression tests for storage.lineage — must run without a live Postgres.

Three layers are covered:

- Ledger (JSONL firehose): append never raises on bad input; valid events land
  as one JSON line each.
- record_* (Postgres): the Task 3 fail-open split — psycopg2.OperationalError ->
  fail-open (None / swallowed, the build must never fail), any other
  psycopg2.Error -> raise (a schema/programming error should surface, not be
  silently hidden). Static schema-vs-INSERT checks catch the UndefinedColumn
  class of bug that bit load_facts (a column in the INSERT that the table does
  not define).
- replay_verify: recomputes the op and compares to the stored rows_hash — never
  trusts the stored value; never raises.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

import psycopg2
import pytest

sys.path.insert(0, "src")
from storage import lineage as lineage_mod

_PROJECT = Path(__file__).resolve().parent.parent
_SQL_PATH = _PROJECT / "src" / "server" / "migrate.sql"


# --- Ledger: JSONL firehose, best-effort -------------------------------


class _BadStr:
    """str() raises — forces json.dumps(default=str) to fail inside append."""

    def __str__(self):
        raise RuntimeError("boom")


def test_ledger_append_never_raises_on_bad_input():
    led = lineage_mod.Ledger(ledger_path=tempfile.mktemp(suffix=".jsonl"))
    try:
        led.append({"event": "request_received", "request": "x", "ts": "t"})
        led.append(None)                                    # not a dict
        led.append("a string")                              # wrong type
        led.append(123)                                     # wrong type
        led.append({"event": "x", "v": _BadStr()})          # unserializable
        led.flush()
    finally:
        led.close()


def test_ledger_writes_valid_json_lines():
    p = tempfile.mktemp(suffix=".jsonl")
    led = lineage_mod.Ledger(ledger_path=p)
    led.append({"event": "request_received", "request": "x"})
    led.append({"event": "tool_call", "tool": "query_dataset", "result": {"value": 1}})
    led.flush()
    led.close()
    lines = [ln for ln in Path(p).read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    for ln in lines:
        assert isinstance(json.loads(ln), dict)


def test_ledger_degrades_to_noop_when_file_unwritable():
    # an existing file used as the parent dir makes mkdir/open fail — the ledger
    # must construct as a no-op writer, and append/flush/close must not raise.
    blocker = tempfile.mktemp()
    Path(blocker).write_text("", encoding="utf-8")
    led = lineage_mod.Ledger(ledger_path=str(Path(blocker) / "x" / "ledger.jsonl"))
    try:
        assert led._f is None
        led.append({"event": "request_received", "request": "x"})  # must not raise
        led.flush()
        led.close()
    finally:
        led.close()


# --- record_*: Postgres lineage tables, best-effort with the Task 3 split ----


class _FakeCursor:
    def __init__(self, fetchone_result=None):
        self.fetchone_result = fetchone_result
        self.sql = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return self.fetchone_result


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


def test_record_artifact_returns_id():
    cur = _FakeCursor(fetchone_result=(42,))
    conn = _FakeConn(cur)
    out = lineage_mod.record_artifact(
        conn, artifact_type="dashboard", artifact_key="at-a-glance", user_id=None,
        dataset_id=1, request_text="r", spec_json={"panels": []},
        model="claude", status="ok")
    assert out == 42
    assert "lineage_artifacts" in cur.sql


def test_record_artifact_fails_open_on_operational_error():
    class _BoomCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            raise psycopg2.OperationalError("horizon db unreachable")

    conn = _FakeConn(_BoomCursor())
    out = lineage_mod.record_artifact(
        conn, artifact_type="dashboard", artifact_key="k", user_id=None,
        dataset_id=1, request_text="r", spec_json={}, model="m", status="ok")
    assert out is None  # best-effort fail-open, not a raise


def test_record_artifact_raises_on_programming_error():
    # non-Operational psycopg2.Error (UndefinedColumn / NotNullViolation, ...)
    # must surface — fail-loud, the same split as ingest_facts/load_facts.
    class _BoomCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            raise psycopg2.errors.UndefinedColumn('column "x" does not exist')

    conn = _FakeConn(_BoomCursor())
    with pytest.raises(psycopg2.Error):
        lineage_mod.record_artifact(
            conn, artifact_type="dashboard", artifact_key="k", user_id=None,
            dataset_id=1, request_text="r", spec_json={}, model="m", status="ok")


def test_record_op_and_tool_call_write_rows_with_fake_conn():
    conn = _FakeConn(_FakeCursor())
    lineage_mod.record_op(conn, artifact_id=1, dataset_id=1, kind="figure",
                          op="requests_received_q1", params={}, row_count=1,
                          rows_hash="abc", result_value=12359)
    lineage_mod.record_tool_call(conn, artifact_id=1, seq=1, tool="query_dataset",
                                 op="filter_agencies", input_json={}, output_json={})
    assert conn.committed


def test_record_op_fails_open_on_operational_error():
    class _BoomCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            raise psycopg2.OperationalError("db down")

    conn = _FakeConn(_BoomCursor())
    lineage_mod.record_op(conn, artifact_id=1, dataset_id=1, kind="figure",
                          op="requests_received_q1", params={}, row_count=1,
                          rows_hash="abc", result_value=12359)  # must not raise


def test_list_artifacts_returns_created_at_and_panel_count():
    rows = [(22, "breakup by compliance", "ready",
             "2026-08-27T09:00:00+00:00", 0)]

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params

        def fetchall(self):
            return rows

    cur = _Cursor()
    conn = _FakeConn(cur)
    out = lineage_mod.list_artifacts(conn)
    assert out == [{"id": 22, "request_text": "breakup by compliance",
                    "status": "ready", "created_at": "2026-08-27T09:00:00+00:00",
                    "panel_count": 0}]
    assert "user_id" not in cur.sql  # unscoped listing keeps the old shape


def test_list_artifacts_scopes_to_one_user():
    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params

        def fetchall(self):
            return []

    cur = _Cursor()
    conn = _FakeConn(cur)
    assert lineage_mod.list_artifacts(conn, user_id=7) == []
    assert "user_id = %s" in cur.sql
    assert cur.params[0] == "builder_request"
    assert cur.params[1] == 7


def test_list_artifacts_fails_open_on_operational_error():
    class _BoomCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            raise psycopg2.OperationalError("db down")

    conn = _FakeConn(_BoomCursor())
    assert lineage_mod.list_artifacts(conn) == []


def test_delete_artifact_deletes_children_then_row_and_commits():
    class _Cursor:
        def __init__(self):
            self.sqls = []
            self.rowcount = 1

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.sqls.append(sql)

    cur = _Cursor()
    conn = _FakeConn(cur)
    assert lineage_mod.delete_artifact(conn, 42) is True
    assert conn.committed
    assert len(cur.sqls) == 3
    assert "lineage_tool_calls" in cur.sqls[0]
    assert "lineage_ops" in cur.sqls[1]
    assert "lineage_artifacts" in cur.sqls[2]


def test_delete_artifact_scoped_to_caller_guards_ownership():
    class _Cursor:
        def __init__(self):
            self.sqls = []
            self.rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.sqls.append((sql, params))

    cur = _Cursor()
    conn = _FakeConn(cur)
    assert lineage_mod.delete_artifact(conn, 42, user_id=7) is False
    sql, params = cur.sqls[2]
    assert "user_id = %s OR user_id IS NULL" in sql
    assert params == (42, 7)


def test_delete_artifact_returns_false_when_row_absent():
    class _Cursor:
        def __init__(self):
            self.rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            pass

    conn = _FakeConn(_Cursor())
    assert lineage_mod.delete_artifact(conn, 999) is False


# --- Static schema-vs-INSERT checks (the load_facts UndefinedColumn class) ----


def _table_columns(table: str) -> set[str]:
    sql = _SQL_PATH.read_text(encoding="utf-8")
    m = re.search(
        rf"CREATE TABLE IF NOT EXISTS horizon\.{table} \((.*?)\);", sql, re.S)
    assert m, f"no CREATE TABLE for horizon.{table} in migrate.sql"
    return {ln.strip().split()[0] for ln in m.group(1).splitlines() if ln.strip()}


def _insert_columns(table: str) -> set[str]:
    src = Path(lineage_mod.__file__).read_text(encoding="utf-8")
    m = re.search(rf"INSERT INTO horizon\.{table}\s*\((.*?)\)", src, re.S)
    assert m, f"no INSERT for horizon.{table} in lineage.py"
    return {c.strip() for c in m.group(1).split(",")}


def test_record_artifact_columns_exist_in_schema():
    missing = _insert_columns("lineage_artifacts") - _table_columns("lineage_artifacts")
    assert not missing, f"record_artifact INSERTs columns not in schema: {missing}"


def test_record_op_columns_exist_in_schema():
    missing = _insert_columns("lineage_ops") - _table_columns("lineage_ops")
    assert not missing, f"record_op INSERTs columns not in schema: {missing}"


def test_record_tool_call_columns_exist_in_schema():
    missing = _insert_columns("lineage_tool_calls") - _table_columns("lineage_tool_calls")
    assert not missing, f"record_tool_call INSERTs columns not in schema: {missing}"


# --- replay_verify: recompute-and-compare, never trust the stored value ------


def test_replay_verify_passes_on_matching_hash():
    row = {"dataset_id": 1, "kind": "figure", "op": "requests_received_q1",
           "params": {}, "result_value": 12359, "rows_hash": "H"}

    def compute(op_row):
        return (12359, "H")

    assert lineage_mod.replay_verify(None, row, compute=compute) is True


def test_replay_verify_detects_corruption():
    # stored rows_hash differs from the recomputed one -> False
    row = {"dataset_id": 1, "kind": "figure", "op": "requests_received_q1",
           "params": {}, "result_value": 999, "rows_hash": "wrong"}

    def compute(op_row):
        return (12359, "right")

    assert lineage_mod.replay_verify(None, row, compute=compute) is False


def test_replay_verify_default_is_lazy_and_fails_open():
    # no compute passed: the default lazily imports Task 5's foi_stats and loads
    # facts for the dataset_id — no live Postgres here, so load_facts fails and
    # replay must return False (fail-open), never raise.
    row = {"dataset_id": 1, "op": "requests_received_q1", "params": {},
           "result_value": 12359, "rows_hash": "x"}
    assert lineage_mod.replay_verify(None, row) is False


def test_replay_default_produces_real_hash_for_figure_key():
    # carry-forward reconciliation: the replay default must not be a silent
    # no-op for figure keys — it recomputes foi_stats over the loaded facts and
    # yields the exact source-row hash, so a correctly-recorded op passes.
    import storage.facts
    from ingest.normalise import normalise_all
    from stats.catalog import hash_rows

    facts = normalise_all()
    real_hash = hash_rows([f for f in facts if f["fy"] == "2025-26" and f["quarter"] == 1
                           and f["measure"] == "received" and f["bucket"] == "total"])

    # patch the module the default compute imports load_facts from (at call
    # time), so no live Postgres is needed.
    storage.facts.load_facts = lambda dataset_id, *, conn=None: facts

    row = {"dataset_id": 99, "op": "requests_received_q1", "params": {},
           "result_value": 12359, "rows_hash": real_hash}
    assert lineage_mod.replay_verify(None, row) is True

    # a corrupted stored hash no longer passes — the default computes a real one
    bad = dict(row, rows_hash="deadbeef")
    assert lineage_mod.replay_verify(None, bad) is False


def test_replay_verify_fails_open_on_non_dict_row():
    # a non-dict op_row (None / a list) must return False, never raise — the
    # stored-hash access lives inside the same try as the recompute.
    def compute(op_row):
        return (1, "H")

    assert lineage_mod.replay_verify(None, None, compute=compute) is False
    assert lineage_mod.replay_verify(None, ["not", "a", "dict"], compute=compute) is False
