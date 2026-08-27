# Bluebird FOI Insights

A hosted demo that replaces the OAIC "Australian Government FOI statistics" page
plus its embedded Power BI report with a dashboard built on the horizon
platform. It replicates the 12 Power BI pages on the real data.gov.au FOI data,
adds a natural-language dashboard/report builder, and records lineage for
everything: data sourced → calculations applied → outcomes, and every
dashboard-builder request.

Public demo: **`https://foi.axoquant.com`** (no auth).

## What it is

- **The 12 Power BI pages**, data-backed and basis-labelled. Every KPI and trend
  point is a platform-computed figure; every figure carries its `basis`
  (`single_quarter`, `cumulative`, or `fy`).
- **An agentic "Ask" path** — type a natural-language request and the builder
  returns a dashboard/report spec. The model never writes a digit: it emits
  structure + enum-constrained keys + citation pointers, and the platform
  computes every number.
- **Lineage** — a hybrid ledger (JSONL event firehose + Postgres tables)
  records the artifact, the dataset snapshot, the tool-call transcript, and the
  computed figures. `/lineage/{artifact_id}` renders the explainability page.
- **The golden boot check** — at startup the app asserts the published Q1
  2025-26 headline figures (requests received 12,359; finalised 11,549; decided
  7,344; within statutory 5,167; granted full 1,426 / part 3,968 / refused
  1,950; withdrawn 3,955). A mismatch aborts loudly, so the app never serves
  wrong data.

## What the POC can answer

The pinned snapshot covers the golden Q1 2025-26 headline figures plus the
per-agency **requests received** and **requests finalised** series (the annual
files publish those at agency granularity). Everything else the demo shows is
either a platform-computed share of those, or an honest "No published data"
gap — the POC does not fabricate a number it cannot source. Specifically, the
four acceptance questions are only partially answerable with the published
data: per-agency **refusal movers** (refusal rate per agency), a **timeliness
correlation**, **portfolio** breakdowns, and the **data-notes** citations need
measures (decided, refused, within-statutory, notes) that only exist as
single-quarter Q1 facts or are not published at agency granularity, so those
pages report the gap rather than guessing.

## Run it locally

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows; venv/activate on POSIX
pip install -r requirements.txt
python scripts/serve.py                          # uvicorn on :8095 (or $FOI_PORT)
```

Then open `http://localhost:8095/` — the at-a-glance page. Smoke-check:

```bash
curl localhost:8095/health                        # {"status":"ok","model":"fartkraft sovereign stack"}
curl localhost:8095/at-a-glance.html              # 200; "12,359" + basis + "fartkraft"
curl -X POST localhost:8095/ask -H "Content-Type: application/json" \
     -d '{"request":"top agencies by requests received Q1 2025-26"}'
curl localhost:8095/lineage/<artifact_id>         # the lineage page
```

There is no live data fetch: the pinned data snapshot in `data/sources/` is the
only input, and the golden check refuses to boot on stale or wrong data.
Postgres is optional — `/ask` and `/lineage` fail open to a degraded (but
honest) reply when the DB is unreachable.

## Data source

- **data.gov.au dataset** `b0771c28-09cc-4c4e-9e61-9a96f6e3d040` — *Australian
  Government FOI statistics* (Office of the Australian Information
  Commissioner, OAIC).
- Files are **pinned in `data/sources/`** (the as-at-18-May-2026 snapshot):
  the current file `agency-foi-data-2025-26-q1-to-q3.xlsx` (Q1–Q3 cumulative +
  derived single-quarter Q1 headline), the annual `agency-foi-data-2019-20.xlsx`
  → `2024-25.xlsx` (FY totals), and the long-run
  `foi-requests-costs-and-charges-1982-2024.csv`.
- The normalising ingest resolves every data quirk once: `x`-prefixed note rows,
  Total rows that do not re-sum (the trusted Total is never re-summed), MoG
  renames (curated map from the Data-notes corpus), the cumulative-vs-single-
  quarter discrepancy, and the `window_mode` basis on every fact.

## Lineage model

Every number on the site and every builder response traces a chain:

```
data sourced (pinned snapshot, sha256, dataset row)
  → calculations applied (normalising ingest → canonical facts → DSL ops,
    each recorded as a lineage_ops row with row_count + rows_hash)
  → outcomes (the rendered figure / dashboard, cited as {c:job.turn.call.field}
    pointers that resolve against the recorded transcript — an unknown pointer
    fails loud, never prints a guessed number)
```

The ledger is **best-effort by design**: a ledger failure never fails a build,
but it also never pretends it wrote something it did not — an unreachable DB
degrades the reply honestly. Replay verification recomputes each op and compares
the stored hash, never trusting the stored value.

## Governance

The chat and agentic builder are hard-scoped to this use case, defence-in-depth:

1. **Deterministic scope screen** — a regex/token screen runs before the model,
   refuses out-of-scope requests (other countries' FOI, immigration/visa, tax/
   benefit advice, health, defence ops, named individuals, anything beyond the
   published statistics) without invoking the model.
2. **Prompt-level scope block** — a strict FOI scope block in the system prompt
   catches what the screen lets through.
3. **Jailbreak scan** — prompt-injection / jailbreak patterns ("ignore previous
   instructions", "reveal your system prompt", role-play) are refused.
4. **Tool sandbox** — read-only by construction: no shell, no file access, no
   arbitrary execution.
5. **Identity stovepipe** — the model never reveals its vendor, weights,
   hardware, or prompt. The one and only disclosure is:

   > "I am powered by the fartkraft sovereign stack, trained on local data."

   The demo is served from the sovereign local stack (public hostname:
   foi.axoquant.com).

## Deploy

- **Public hostname:** `https://foi.axoquant.com` — Cloudflare Worker →
  Cloudflare tunnel → idc-1 origin, no auth.
- **Deploy script:** `python scripts/deploy.py` (dry-run/`--check`/`--no-restart`
  modes) pushes the service + pinned data to idc-1 and restarts the unit. Full
  runbook in `docs/deploy.md`.
- **Static pages render with the chat path down** — the 12 pages are built from
  platform-computed figures at boot; the chat/LLM path can be dead and every
  page still 200s.

### Deploy note: LLM resolution

The demo's `/ask` and `/chat` call the local model through
`axoquant_llm.chat("author", …)` — resolved by **role**, not by URL or a model
name. The `author` role now serves **Qwen3.8-27B-FP8** (the fleet consolidated
the old Qwen3-Next-80B-A3B MoE into a dense 27B on 2026-08-26). The
`FOI_LLM_URL`/`FOI_LLM_MODEL` env vars are vestigial and no longer read by the
app; a stale value cannot cause the silent canned-spec fallback the old note
warned about.

`scripts/deploy.py --check` probes the served model list directly and flags a
missing `qwen3.8-27b-fp8`.

## Layout

```
src/
  config.py        env + paths + constants (golden figures, dataset id)
  ingest/          normalising loader (xlsx → long-form facts, MoG renames)
  storage/         Postgres schema + frame + hybrid lineage ledger
  stats/           enum-constrained catalog + DSL ops (never invent a number)
  agentic/         builder loop + governance (scope, jailbreak, identity)
  site/            the 12 static pages + lineage viewer + OAIC-style chrome
  server/          FastAPI app (/, /{page}.html, /ask, /lineage/{id}, /health)
data/
  sources/         pinned data.gov.au snapshot (baked into the deploy)
  corpus/          Data notes + disclaimer (definitional authority, verbatim)
  generated/       lineage JSONL firehose (runtime; regenerated per boot)
scripts/
  serve.py         run the app locally
  deploy.py        deploy to idc-1 + foi.axoquant.com
docs/
  deploy.md        the idc-1 systemd unit, tunnel + Worker route, env vars
```
