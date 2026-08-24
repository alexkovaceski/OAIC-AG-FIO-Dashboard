"""seed_pilot_users — idempotent pilot accounts with access tiers.

Creates the four pilot accounts in horizon.foi_chat_users (PBKDF2-hashed
passwords) with their role (viewer/internal). Existing usernames are skipped
(idempotent). Passwords are generated once and printed to stdout — never stored
plaintext, never recoverable. Re-run safely any time.

Usage:  .venv/bin/python scripts/seed_pilot_users.py
"""
from __future__ import annotations
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.auth import hash_password
from storage.db import get_conn, ensure_schema

# The four pilot accounts. Passwords are generated fresh per NEW account;
# existing accounts are never touched.
ACCOUNTS = [
    {"username": "foi.public",   "role": "viewer",   "display_name": "Public Pilot"},
    {"username": "foi.pilot",    "role": "internal", "display_name": "Pilot User"},
    {"username": "foi.internal", "role": "internal", "display_name": "Internal User"},
    {"username": "foi.officer",  "role": "internal", "display_name": "FOI Officer"},
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
                    "(username, pw_hash, display_name, role) VALUES (%s,%s,%s,%s)",
                    (uname, hash_password(pw), acct["display_name"], acct["role"]))
                print(f"CREATED {uname}  role={acct['role']}  password={pw}")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
