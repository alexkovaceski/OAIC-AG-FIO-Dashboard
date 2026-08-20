"""MoG renames + agency->portfolio map, curated from the Data-notes corpus."""
RENAME_MAP = {
    # example — the ingest resolves old names to the current name once
}
PORTFOLIO_MAP = {}

def normalise_agency(name: str) -> str:
    n = (name or "").strip()
    if n.startswith("x") or n.startswith("xx"):
        return n  # caller strips these
    return RENAME_MAP.get(n, n)
