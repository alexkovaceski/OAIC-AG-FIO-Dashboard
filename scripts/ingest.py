"""ingest — CLI entry point for the FOI ingest pipeline (stub for Task 1).

Task 2 lands the normalising loader (src/ingest/normalise.py); Task 3 wires
Postgres storage. This stub imports config so the scaffold is importable
end-to-end and prints the intended flow.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    print(f"ingest stub: {len(args)} arg(s); sources at {config.DATA_SOURCES_DIR}")
    print("Task 2 (normalise) + Task 3 (storage) land here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
