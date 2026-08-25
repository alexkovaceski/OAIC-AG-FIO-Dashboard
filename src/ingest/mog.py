"""MoG renames, curated from the Data-notes corpus."""
RENAME_MAP = {
    # DISR was renamed in the 2022 Machinery of Government changes (the "Energy"
    # portfolio moved out). The data notes say renamed-but-same-responsibility
    # agencies appear under their most recent name, so the pre-2022-23 spelling
    # is resolved to the current one; the dashboard then shows DISR as one series.
    "Department of Industry, Science, Energy and Resources": "Department of Industry, Science and Resources",
    # Stage 1 (2026-08-25 spec S1.2): further verified renames, same
    # most-recent-name convention as DISR. Each pair checked for a clean,
    # non-overlapping FY cutover before adding (Task 4 discovery).
    "Independent Hospital Pricing Authority": "Independent Health and Aged Care Pricing Authority",
    "Asbestos Safety and Eradication Agency": "Asbestos and Silica Safety and Eradication Agency",
    "Department of Health and Aged Care": "Department of Health, Disability and Ageing",
    "Net Zero Economy Agency": "Net Zero Economy Authority",
    # 2021 courts merger — deliberately NOT mapped. The approved design (S1.2)
    # assumed both predecessors (Federal Circuit Court of Australia, Family
    # Court of Australia) aggregate under a single merged name. Task 4
    # discovery found the source instead splits post-merger reporting into TWO
    # separate entities, "Federal Circuit and Family Court of Australia
    # (Division 1)" and "... (Division 2)", each with its own continuous
    # 2021-22..2025-26 series, and no in-source evidence pins which
    # predecessor maps to which division (both predecessors sit in the
    # Attorney-General's portfolio, and both divisions cut over cleanly, so
    # portfolio/timing alone can't disambiguate a 1:1 mapping from a summed
    # one). Mapping both predecessor keys to one division would misattribute
    # the other division's history. Ruling (Alex, 2026-08-25, spec
    # 2026-08-25-foi-feedback-response-design.md): keep all four entities
    # distinct, with disclosure on data-notes. The 2021 merger created
    # Division 1 and Division 2 as separate reporting entities in the source
    # data, matching OAIC's own convention of representing merger-created
    # bodies as new entities — see task-4-report.md for the full discovery
    # output and options.
}

def normalise_agency(name: str) -> str:
    n = (name or "").strip()
    if n.startswith("x") or n.startswith("xx"):
        return n  # caller strips these
    return RENAME_MAP.get(n, n)
