"""storage.facts — portfolio must survive the DB roundtrip (spec S1.1)."""
import re
from pathlib import Path

from storage import facts as facts_mod


def _read(path):
    return Path(path).read_text(encoding="utf-8")


def test_migrate_sql_adds_portfolio_column():
    sql = _read("src/server/migrate.sql")
    assert re.search(
        r"ALTER TABLE horizon\.foi_facts\s+ADD COLUMN IF NOT EXISTS portfolio TEXT NOT NULL DEFAULT ''",
        sql), "idempotent portfolio ALTER missing from migrate.sql"


def test_insert_includes_portfolio():
    src = _read("src/storage/facts.py")
    m = re.search(r"INSERT INTO horizon\.foi_facts.*?VALUES[^)]*\)", src, re.S)
    assert m and "portfolio" in m.group(0), "foi_facts INSERT must include portfolio"


def test_load_facts_selects_portfolio_not_hardcoded():
    src = _read("src/storage/facts.py")
    assert '"portfolio": ""' not in src, "load_facts still hardcodes portfolio=''"
    m = re.search(r"SELECT[^\"]*?derived, portfolio\s*\"", src) or \
        re.search(r"SELECT.*portfolio.*FROM horizon\.foi_facts", src, re.S)
    assert m, "load_facts SELECT must include the portfolio column"
