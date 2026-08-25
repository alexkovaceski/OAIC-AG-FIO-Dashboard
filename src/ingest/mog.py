"""MoG renames + agency->portfolio map, curated from the Data-notes corpus."""
RENAME_MAP = {
    # DISR was renamed in the 2022 Machinery of Government changes (the "Energy"
    # portfolio moved out). The data notes say renamed-but-same-responsibility
    # agencies appear under their most recent name, so the pre-2022-23 spelling
    # is resolved to the current one; the dashboard then shows DISR as one series.
    "Department of Industry, Science, Energy and Resources": "Department of Industry, Science and Resources",
}
PORTFOLIO_MAP = {}

def normalise_agency(name: str) -> str:
    n = (name or "").strip()
    if n.startswith("x") or n.startswith("xx"):
        return n  # caller strips these
    return RENAME_MAP.get(n, n)
