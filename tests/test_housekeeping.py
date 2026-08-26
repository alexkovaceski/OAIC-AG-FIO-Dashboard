"""Stage-1 housekeeping contracts (spec S1.7)."""
from pathlib import Path


def test_deploy_probe_checks_the_five_pilot_accounts():
    src = Path("scripts/deploy.py").read_text(encoding="utf-8")
    for name in ("pilot01.user", "pilot02.user", "pilot03.user",
                 "pilot04.user", "pilot05.user"):
        assert name in src, f"probe missing {name}"
    for old in ("foi.public", "foi.pilot", "foi.internal", "foi.officer"):
        assert old not in src, f"probe still references retired account {old}"
    assert "(5/5)" in src and "/5; run" in src, "probe denominator still /4"


def test_deploy_probe_checks_the_portfolio_column():
    # Stage-1 migration guard: the probe must also verify foi_facts.portfolio,
    # not just the role column, so --check catches an unapplied Stage-1 ALTER.
    src = Path("scripts/deploy.py").read_text(encoding="utf-8")
    assert "portfolio" in src and "foi_facts" in src
    assert "portfolio column:" in src


def test_deploy_probe_queries_are_schema_qualified():
    # Unqualified, the information_schema lookups match a same-named table in
    # ANY schema on the instance, so --check could report "role column:
    # present" for a table the service never reads and pass on an unmigrated
    # horizon. Both lookups name the schema the app queries.
    src = Path("scripts/deploy.py").read_text(encoding="utf-8")
    assert src.count("table_schema=%s AND table_name=%s AND column_name=%s") == 2, \
        "both information_schema lookups must carry a schema predicate"
    assert src.count('("horizon", "foi_chat_users", "role")') == 1
    assert src.count('("horizon", "foi_facts", "portfolio")') == 1


def test_deploy_probe_survives_the_remote_single_quote_wrapper():
    # The probe is passed to a remote `python -c '<probe>'`, so a single quote
    # anywhere inside it would end the shell string. It must also still print
    # exactly the three lines the sed extraction reads (1p/2p/3p).
    import importlib.util
    spec = importlib.util.spec_from_file_location("_deploy", "scripts/deploy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    probe = module._DB_PROBE
    assert "'" not in probe, "a single quote would break the remote -c wrapper"
    compile(probe, "<probe>", "exec")          # the probe must be valid python
    assert probe.count("\nprint(") == 3, "the probe must print exactly 3 lines"


def test_readme_advertises_the_live_hostname():
    src = Path("README.md").read_text(encoding="utf-8")
    assert "foi.fartkraft.ai" not in src
    assert "foi.axoquant.com" in src


def test_gitignore_covers_memories():
    src = Path(".gitignore").read_text(encoding="utf-8")
    assert "docs/memories/" in src


def test_scratch_files_are_gone():
    assert not Path("background").exists()
    assert not Path("main.py").exists()
