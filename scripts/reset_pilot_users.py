"""reset_pilot_users — delete the old pilot/test accounts and re-seed the five.

Deletes every chat message + row in horizon.foi_chat_users (child messages
first, to satisfy the FK), then creates the five pilot accounts
(pilot01.user..pilot05.user) fresh, printing a new password for each.
Passwords are never recoverable once printed, so capture stdout. Re-run
safely any time (idempotent once run: old accounts already gone).

Usage:  .venv/bin/python scripts/reset_pilot_users.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.db import get_conn, ensure_schema
from seed_pilot_users import ACCOUNTS, create_accounts


def main() -> None:
    conn = get_conn()
    ensure_schema(conn)
    try:
        with conn.cursor() as cur:
            # child chat messages reference foi_chat_users; delete them first
            cur.execute("DELETE FROM horizon.foi_chat_messages")
            print(f"deleted {cur.rowcount} chat message(s)")
            cur.execute("DELETE FROM horizon.foi_chat_users")
            print(f"deleted {cur.rowcount} existing account(s)")
        conn.commit()
        create_accounts(conn, ACCOUNTS)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
