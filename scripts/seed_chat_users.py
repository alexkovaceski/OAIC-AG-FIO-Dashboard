"""seed_chat_users — idempotent pre-seeded test accounts.

Creates the nominated test accounts in horizon.foi_chat_users (PBKDF2-hashed
passwords). Existing usernames are skipped (idempotent). Passwords are
generated once and printed to stdout — never stored plaintext, never
recoverable. Re-run safely any time.

Usage:  .venv/bin/python scripts/seed_chat_users.py
"""
from __future__ import annotations
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.auth import hash_password
from storage.db import get_conn, ensure_schema

# The nominated test accounts. Passwords are generated fresh per NEW account;
# existing accounts are never touched.
ACCOUNTS = [
    {"username": "foi.tester1", "display_name": "FOI Tester One"},
    {"username": "foi.tester2", "display_name": "FOI Tester Two"},
    {"username": "foi.tester3", "display_name": "FOI Tester Three"},
]


def main() -> None:
    conn = get_conn()
    ensure_schema(conn)
    try:
        with conn.cursor() as cur:
            for acct in ACCOUNTS:
                uname = acct["username"]
                cur.execute("SELECT id FROM horizon.foi_chat_users "
                            "WHERE username = %s", (uname,))
                if cur.fetchone() is not None:
                    print(f"skip {uname}: exists")
                    continue
                pw = secrets.token_urlsafe(12)
                cur.execute(
                    "INSERT INTO horizon.foi_chat_users "
                    "(username, pw_hash, display_name) VALUES (%s,%s,%s)",
                    (uname, hash_password(pw), acct["display_name"]))
                print(f"CREATED {uname}  password={pw}  "
                      f"display={acct['display_name']}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
