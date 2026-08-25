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
