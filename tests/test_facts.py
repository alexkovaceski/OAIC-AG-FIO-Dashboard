"""Regression tests for storage.facts — must run without a live Postgres.

test_load_facts_select_columns_exist_in_schema is a static schema-vs-query
check that catches the UndefinedColumn class of bug: a real DB would raise if
load_facts SELECTs a column foi_facts does not define (it previously selected
`portfolio`, which is not a schema column, and swallowed the error -> None).
"""
from pathlib import Path
import re
import sys
sys.path.insert(0, "src")
from storage import facts as facts_mod

_PROJECT = Path(__file__).resolve().parent.parent
_SQL_PATH = _PROJECT / "src" / "server" / "migrate.sql"


def _schema_columns():
    sql = _SQL_PATH.read_text(encoding="utf-8")
    cols = set()
    # Extract columns from CREATE TABLE block
    table = re.search(
        r"CREATE TABLE IF NOT EXISTS horizon\.foi_facts \((.*?)\);", sql, re.S
    ).group(1)
    cols.update({ln.strip().split()[0] for ln in table.splitlines() if ln.strip()})
    # Extract columns from ALTER TABLE ADD COLUMN statements
    for alter_match in re.finditer(
        r"ALTER TABLE horizon\.foi_facts\s+ADD COLUMN IF NOT EXISTS\s+(\w+)",
        sql, re.S
    ):
        cols.add(alter_match.group(1))
    return cols


def _load_facts_select_columns():
    src = Path(facts_mod.__file__).read_text(encoding="utf-8")
    sel = re.search(
        r"SELECT\s+(agency_key[\s\S]*?)FROM\s+horizon\.foi_facts", src, re.S
    ).group(1)
    sel = sel.replace('"', "")  # strip Python string-literal quote chars
    return {c.strip() for c in sel.split(",") if c.strip()}


def test_load_facts_select_columns_exist_in_schema():
    sel_cols = _load_facts_select_columns()
    schema_cols = _schema_columns()
    missing = sel_cols - schema_cols
    assert not missing, f"load_facts SELECTs columns not in horizon.foi_facts: {missing}"


def test_load_facts_returns_canonical_dicts():
    """load_facts maps DB rows back to canonical fact dicts (no live DB)."""
    class FakeCursor:
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False
        def execute(self, sql, params=None):
            self.sql = sql
            self.params = params
        def fetchall(self):
            # matches the SELECT column order in load_facts (includes portfolio column)
            return [("_all", "Total", "2025-26", 1, "requests", "received",
                     "total", 12359.0, True, "Health")]

    class FakeConn:
        def cursor(self):
            return FakeCursor()
        def commit(self):
            pass
        def rollback(self):
            pass

    out = facts_mod.load_facts(1, conn=FakeConn())
    assert out is not None, "load_facts returned None (error swallowed)"
    assert len(out) == 1
    row = out[0]
    assert row["agency_key"] == "_all"
    assert row["fy"] == "2025-26" and row["quarter"] == 1
    assert row["measure"] == "received" and row["bucket"] == "total"
    assert row["value"] == 12359.0 and row["derived"] is True
    assert "portfolio" in row  # canonical fact shape preserved
    assert row["portfolio"] == "Health"  # portfolio value round-trips
