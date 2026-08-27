"""server.worker — the queued build theatre: attempts, retries, fallback.

Hermetic: every test drives run_job with a fake conn and a deterministic
complete_fn; no live DB, no live model.
"""
import asyncio
import json
import sys
import tempfile

sys.path.insert(0, "src")
import site_shim
site_shim.install()

from ingest.normalise import normalise_all
from storage.frame import Frame
from storage.lineage import Ledger
from server.worker import run_job, _fallback_result, MAX_ATTEMPTS


class _FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.sqls.append((sql, params))

    def fetchone(self):
        return self.conn.fetchone_result

    def fetchall(self):
        return self.conn.fetchall_result


class _FakeConn:
    def __init__(self, fetchone=None, fetchall=None, rowcount=1):
        self.sqls = []
        self.fetchone_result = fetchone
        self.fetchall_result = fetchall or []
        self.rowcount = rowcount
        self.committed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass


_FRAME = Frame(normalise_all())
_GOOD = ('{"title": "T", "panels": ['
         '{"figure": "kpi", "stat": "requests_received_q1"}]}')


def _conn_for(spec_json):
    return _FakeConn(fetchone=(json.dumps(spec_json),), fetchall=[])


def test_run_job_ready_on_first_attempt():
    conn = _conn_for({"panels": [{"figure": "kpi",
                                  "stat": "requests_received_q1"}]})

    async def complete(messages):
        return _GOOD

    job = {"id": 7, "request_text": "build a dashboard of requests by agency",
           "user_id": None, "dataset_id": 1}
    status = asyncio.run(run_job(_FRAME, conn, job, complete,
                                 Ledger(ledger_path=tempfile.mktemp())))
    assert status == "ready"
    # one attempt: one tool-call reset, and a terminal ready write
    assert sum(1 for sql, _ in conn.sqls
               if "DELETE FROM horizon.lineage_tool_calls" in sql) == 1
    ready = [p for sql, p in conn.sqls if "SET status = %s" in sql]
    assert any(p and p[0] == "ready" for p in ready)
    # progress steps were appended
    assert any("progress_json" in sql for sql, _ in conn.sqls)


def test_run_job_retries_then_succeeds():
    conn = _conn_for({"panels": [{"figure": "kpi",
                                  "stat": "requests_received_q1"}]})
    calls = {"n": 0}

    def flaky(messages):
        calls["n"] += 1
        return '{"panels": []}' if calls["n"] == 1 else _GOOD

    job = {"id": 8, "request_text": "build a dashboard of requests by agency",
           "user_id": None, "dataset_id": 1}
    status = asyncio.run(run_job(_FRAME, conn, job, flaky,
                                 Ledger(ledger_path=tempfile.mktemp())))
    assert status == "ready"
    assert calls["n"] == 2                       # one retry after the empty spec
    # each attempt reset the tool calls: two deletes
    assert sum(1 for sql, _ in conn.sqls
               if "DELETE FROM horizon.lineage_tool_calls" in sql) == 2


def test_run_job_falls_back_to_the_deterministic_answer():
    conn = _conn_for({})
    job = {"id": 9, "request_text": "build a dashboard of requests received by agency",
           "user_id": None, "dataset_id": 1}

    async def empty(messages):
        return '{"panels": []}'

    status = asyncio.run(run_job(_FRAME, conn, job, empty,
                                 Ledger(ledger_path=tempfile.mktemp())))
    assert status == "fallback"
    terminal = [(sql, p) for sql, p in conn.sqls
                if "SET status = %s" in sql and p and p[0] == "error"]
    assert terminal
    result_writes = [(sql, p) for sql, p in conn.sqls
                     if "result_json" in sql and p]
    assert result_writes
    # the fallback result is the router's deterministic answer, hashed
    result = result_writes[-1][1][1]
    assert json.loads(result)["stat_key"] == "received_top20"


def test_run_job_error_when_no_fallback_exists():
    conn = _conn_for({})
    job = {"id": 10, "request_text": "make a chart of compliance by agency",
           "user_id": None, "dataset_id": 1}

    async def empty(messages):
        return '{"panels": []}'

    status = asyncio.run(run_job(_FRAME, conn, job, empty,
                                 Ledger(ledger_path=tempfile.mktemp())))
    assert status == "error"
    result_writes = [(sql, p) for sql, p in conn.sqls
                     if "result_json" in sql and p]
    assert json.loads(result_writes[-1][1][1]) == {}


def test_fallback_result_uses_the_router():
    out = _fallback_result("build a dashboard of requests received by agency",
                           _FRAME)
    assert out is not None
    assert out["stat_key"] == "received_top20"
    assert out["dataset_registry"]["rows_hash"]
    assert _fallback_result("make a chart of compliance by agency",
                            _FRAME) is None


def test_max_attempts_is_two():
    assert MAX_ATTEMPTS == 2
