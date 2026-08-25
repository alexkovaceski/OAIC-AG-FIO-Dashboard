"""Lineage for static pages: key resolution (B1 fix) + boot seeding (S1.5)."""
import re
from pathlib import Path


class _Cursor:
    """Stub cursor recording SQL; returns canned rows per query shape."""
    def __init__(self, artifact_row=None, key_row=None):
        self.artifact_row = artifact_row
        self.key_row = key_row
        self.executed = []
    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))
        self._last = sql
    def fetchone(self):
        if "artifact_key = " in self._last or "artifact_key=" in self._last:
            return self.key_row
        return self.artifact_row
    def fetchall(self):
        return []
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Conn:
    def __init__(self, cursor): self._cur = cursor
    def cursor(self): return self._cur


def test_load_artifact_resolves_page_key_not_dataerror():
    # B1: a non-numeric id must resolve via artifact_key, never hit the bigint
    # id compare (which raises psycopg2.DataError -> 500 on the live site).
    from site.lineage_viewer import _load_artifact
    cur = _Cursor(key_row=(7,),
                  artifact_row=("static_page", "at-a-glance", None, 1,
                                "static render", "{}", "static-render", "rendered"))
    art = _load_artifact("at-a-glance", _Conn(cur))
    id_queries = [q for q, _ in cur.executed if "WHERE id = " in q]
    key_queries = [q for q, _ in cur.executed if "artifact_key" in q]
    assert key_queries, "non-numeric id must be resolved by artifact_key first"
    for q, params in cur.executed:
        if "WHERE id = " in q:
            assert all(not (isinstance(p, str) and not p.isdigit())
                       for p in (params or ())), "raw page-key hit the id compare"
    assert art is not None and art["artifact_key"] == "at-a-glance"


def test_load_artifact_unknown_key_degrades_to_none():
    from site.lineage_viewer import _load_artifact
    cur = _Cursor(key_row=None, artifact_row=None)
    assert _load_artifact("no-such-page", _Conn(cur)) is None


def test_boot_seeds_static_lineage():
    # app.py must define _seed_static_lineage and call it from the facts seed;
    # source-level contract check (a live-DB integration test needs Postgres).
    src = Path("src/server/app.py").read_text(encoding="utf-8")
    assert "_seed_static_lineage" in src
    assert re.search(r"artifact_type=.static_page.", src)
    assert src.index("_seed_static_lineage(") < len(src)
