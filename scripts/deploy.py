#!/usr/bin/env python3
"""Deploy the Bluebird FOI Insights POC to idc-1 (mirrors horizon's tools/deploy_site.py).

scp the service + pinned data to idc-1, install/refresh the venv, and restart
the systemd unit that serves the origin. Run from the repo root:

    python scripts/deploy.py            # copy + install + restart (real deploy)
    python scripts/deploy.py --dry-run  # print every command, run nothing
    python scripts/deploy.py --no-restart   # copy + install, leave the unit alone
    python scripts/deploy.py --check    # verify ssh + the unit + the env file

Auth is your existing SSH key for algolotl@idc-1 (tailnet IP 100.86.3.50); there
is no password prompt. The public hostname (foi.axoquant.com) is NOT touched by
this script - the Cloudflare Worker + tunnel route is one-time setup, documented
in docs/deploy.md.

Why the FOI_LLM_MODEL check matters: the demo's /ask path calls the local model
at FOI_LLM_URL and falls back to a deterministic canned spec on any failure. If
FOI_LLM_MODEL is not the model idc-1 actually serves (qwen3next-80b-a3b-q4),
the endpoint answers 404 and every request silently demos the canned spec - the
demo still 200s, but the "real LLM completion" never happens. The deploy script
flags a missing/wrong FOI_LLM_MODEL in /etc/foi-insights.env rather than hiding
it.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# idc-1 (see horizon SERVICES.md): tailnet IP, algolotl user.
REMOTE_USER = "algolotl"
IDC1 = "100.86.3.50"
REMOTE = "/home/algolotl/foi-insights"
UNIT = "foi-insights"
ENV_FILE = "/etc/foi-insights.env"
ORIGIN_PORT = "8097"          # the service's systemd port on idc-1 (FOI_PORT)
KNOWN_GOOD_MODEL = "qwen3next-80b-a3b-q4"   # what idc-1:8012 serves today

# Service code + pinned data. data/generated/ is deliberately excluded - the
# JSONL lineage ledger is a runtime firehose regenerated per boot; copying a
# stale local copy over the live one would clobber demo-day events.
PUSH = [
    "src",
    "scripts",
    "data/sources",
    "data/corpus",
    "requirements.txt",
    "pyproject.toml",
]

# The DB probe for --check: run through the FOI venv's own python + psycopg2
# (guaranteed present on idc-1) so the check exercises exactly the DSN and
# driver the app uses — the host may not have a psql binary (Postgres runs in
# the algolotl-pg container). Prints role column presence + portfolio column
# presence + pilot-account count, one per line. No single quotes inside (the
# shell wraps it in single quotes).
#
# Both information_schema lookups are schema-qualified to "horizon", the schema
# the app's own queries use. Unqualified, they match a same-named table in ANY
# schema on the instance, so the probe could report "role column: present" for a
# table the service never reads and pass a --check on an unmigrated horizon.
_DB_PROBE = (
    'import os, psycopg2\n'
    'c = psycopg2.connect(os.environ["FOI_PG_DSN"])\n'
    'with c.cursor() as cur:\n'
    '    cur.execute("SELECT column_name FROM information_schema.columns "\n'
    '                "WHERE table_schema=%s AND table_name=%s AND column_name=%s",\n'
    '                ("horizon", "foi_chat_users", "role"))\n'
    '    role = cur.fetchone()\n'
    '    cur.execute("SELECT column_name FROM information_schema.columns "\n'
    '                "WHERE table_schema=%s AND table_name=%s AND column_name=%s",\n'
    '                ("horizon", "foi_facts", "portfolio"))\n'
    '    portfolio = cur.fetchone()\n'
    '    cur.execute("SELECT count(*) FROM horizon.foi_chat_users "\n'
    '                "WHERE username IN (%s,%s,%s,%s,%s)",\n'
    '                ("pilot01.user", "pilot02.user", "pilot03.user", "pilot04.user", "pilot05.user"))\n'
    '    n = cur.fetchone()[0]\n'
    'print(role[0] if role else "NO_ROLE_COLUMN")\n'
    'print(portfolio[0] if portfolio else "NO_PORTFOLIO_COLUMN")\n'
    'print(n)\n'
)


def ssh_target() -> str:
    return f"{REMOTE_USER}@{IDC1}"


def _remote_dir(item: str) -> str:
    """The remote directory an item belongs in, preserving its parent prefix.

    `scp -r data/corpus host:/rem/` copies the SOURCE's basename to `/rem/corpus/`
    — the `data/` prefix is dropped. The app reads `data/corpus`, so pushing a
    nested item to the target root silently misses it: the service boots against
    the stale `data/corpus` and a newly-added registry file (data/corpus/provenance)
    is never served. The destination must carry the parent prefix back.
    """
    normalized = item.replace("\\", "/")
    if "/" in normalized:
        return f"{REMOTE}/{normalized.rsplit('/', 1)[0]}/"
    return f"{REMOTE}/"


def run(cmd: list[str], dry_run: bool, description: str) -> None:
    print(f"[{description}] $ {' '.join(cmd)}", flush=True)
    if not dry_run:
        subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="print every command without executing anything "
                             "(safe first step; no ssh/scp happens)")
    parser.add_argument("--no-restart", action="store_true",
                        help="copy files + install deps, but do not touch the "
                             "systemd unit")
    parser.add_argument("--check", action="store_true",
                        help="verify ssh reachability, the unit, and the env "
                             "file on idc-1; change nothing")
    args = parser.parse_args()

    if not (ROOT / "src").is_dir() or not (ROOT / "requirements.txt").is_file():
        print(f"error: run from the repo root (this is {ROOT}); "
              "missing src/ or requirements.txt", file=sys.stderr)
        return 2

    mode = "DRY-RUN (nothing executed)" if args.dry_run else "REAL"
    print(f"Bluebird FOI Insights deploy -> {ssh_target()}:{REMOTE}   [{mode}]")

    if args.check:
        # One-shot read-only probe: unit state, env file presence, model pin,
        # the AutoGluon risk fit, the role access tier, and the pilot accounts.
        # Runs through the remote shell; no process substitution (plain POSIX).
        cmd = (
            f"systemctl is-active {UNIT}; "
            f"test -f {ENV_FILE} && echo 'env file: present' || echo 'env file: MISSING'; "
            f"v=$(grep '^FOI_LLM_MODEL=' {ENV_FILE} 2>/dev/null | cut -d= -f2); "
            f"if [ \"$v\" = \"{KNOWN_GOOD_MODEL}\" ]; then "
            f"echo \"FOI_LLM_MODEL: pinned ({KNOWN_GOOD_MODEL})\"; else "
            f"echo \"FOI_LLM_MODEL: NOT pinned to {KNOWN_GOOD_MODEL} (got '$v')\"; fi; "
            f"cd {REMOTE} && .venv/bin/python -c \"import autogluon; "
            f"from autogluon.common import __version__ as v; print('autogluon:', v)\" "
            f"2>/dev/null && echo 'autogluon: installed' || "
            f"echo 'autogluon: MISSING (run .venv/bin/pip install -r requirements.txt; "
            f"~6-9GB, idc-1 only)'; "
            f"d=$(grep '^FOI_PG_DSN=' {ENV_FILE} 2>/dev/null | cut -d= -f2-); "
            f"out=$(FOI_PG_DSN=\"$d\" .venv/bin/python -c '{_DB_PROBE}' 2>/dev/null); "
            f"r=$(printf '%s\\n' \"$out\" | sed -n 1p); "
            f"p=$(printf '%s\\n' \"$out\" | sed -n 2p); "
            f"n=$(printf '%s\\n' \"$out\" | sed -n 3p); "
            f"if [ \"$r\" = \"role\" ]; then echo 'role column: present'; else "
            f"echo 'role column: MISSING (not migrated, or DB/probe unreachable; "
            f"apply the Task 1 ALTER from src/server/migrate.sql)'; fi; "
            f"if [ \"$p\" = \"portfolio\" ]; then echo 'portfolio column: present'; else "
            f"echo 'portfolio column: MISSING (apply the Stage-1 ALTER from "
            f"src/server/migrate.sql)'; fi; "
            f"if [ \"$n\" = \"5\" ]; then echo 'pilot accounts: seeded (5/5)'; else "
            f"echo 'pilot accounts: MISSING ('${{n:-none}}'/5; run "
            f"scripts/reset_pilot_users.py)'; fi"
        )
        run(["ssh", ssh_target(), cmd], dry_run=args.dry_run,
            description="probe idc-1 (unit + env)")
        return 0

    # 1. Push the service + pinned data.
    for item in PUSH:
        src = ROOT / item
        if not src.exists():
            print(f"skip {item} (missing locally)", flush=True)
            continue
        run(["scp", "-r", str(src), f"{ssh_target()}:{_remote_dir(item)}"],
            dry_run=args.dry_run, description=f"push {item}")

    # 2. Install/refresh the venv (idempotent; first deploy creates it).
    # axoquant-llm is installed from the LOCAL clone on idc-1
    # (/home/algolotl/axoquant-llm, pinned to 235ce71) — the git+https line in
    # requirements.txt fails because the repo is private. Install it first, then
    # the rest of requirements (pip resolves the already-present dist).
    run(["ssh", ssh_target(),
         f"cd {REMOTE} && python3 -m venv .venv && "
         f".venv/bin/pip install -q -e /home/algolotl/axoquant-llm && "
         f".venv/bin/pip install -r requirements.txt"],
        dry_run=args.dry_run, description="install python deps (axoquant-llm local)")

    if args.no_restart:
        print(f"\n--no-restart: files pushed + deps installed; {UNIT} untouched.")
        print(f"  restart manually when ready: "
              f"ssh {ssh_target()} 'sudo systemctl restart {UNIT}'")
        return 0

    # 3. Restart the unit and surface its status.
    run(["ssh", ssh_target(),
         f"sudo systemctl restart {UNIT} && systemctl --no-pager status {UNIT}"],
        dry_run=args.dry_run, description="restart foi-insights")

    # 4. Post-deploy guard: confirm the model pin, so the demo is not silently
    #    running on the canned fallback.
    run(["ssh", ssh_target(),
         f"grep -q '^FOI_LLM_MODEL={KNOWN_GOOD_MODEL}$' {ENV_FILE} && "
         f"echo 'FOI_LLM_MODEL: pinned ({KNOWN_GOOD_MODEL})' || "
         f"echo 'WARNING: FOI_LLM_MODEL in {ENV_FILE} is not {KNOWN_GOOD_MODEL} "
         f"- /ask will fall back to the canned spec every time'"],
        dry_run=args.dry_run, description="check FOI_LLM_MODEL pin")

    if args.dry_run:
        print("\n--dry-run: nothing was executed. Remove the flag to deploy for "
              "real. (Also check docs/deploy.md for the one-time tunnel/Worker "
              "setup.)")
    else:
        print(f"\nDeployed. Verify the origin: ssh {ssh_target()} "
              f"'curl -s http://localhost:{ORIGIN_PORT}/health'"
              f" then open https://foi.axoquant.com")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
