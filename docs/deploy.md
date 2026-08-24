# Deploy — Bluebird FOI Insights on idc-1 + foi.axoquant.com

The POC runs on the existing horizon serving stack: a FastAPI origin on idc-1,
a Cloudflare Tunnel, and a thin Cloudflare Worker. Public URL
`https://foi.axoquant.com` → Worker → tunnel → idc-1 origin. The chat, reports
and risk views are session-gated (login required); the statistics pages and
`/ask` are public and render even when the chat/LLM path is down.

```
browser ──HTTPS──> Cloudflare Worker (foi-insights: thin passthrough)
                        │  forwards path + query + headers unchanged
                        ▼
                   Cloudflare Tunnel (cloudflared on idc-1)
                        │
                   foi-insights (FastAPI :8097, loopback) — serves EVERYTHING
                        ├─ /                at-a-glance page
                        ├─ /{page}.html     the static pages
                        ├─ /assets/*        site.css
                        ├─ /login           session login (foi_chat_users)
                        ├─ /chat.html       session-gated chat
                        ├─ /reports.html    session-gated reports
                        ├─ /risk.html       internal-only risk views (role)
                        ├─ /ask             agentic builder (LLM via idc-1:8012)
                        ├─ /lineage/{id}    explainability page
                        └─ /health
```

## 1. The idc-1 systemd unit

The origin listens on loopback + tailnet, port **8097** (`FOI_PORT`), so
cloudflared is the only public listener — no firewall change.

**`/etc/systemd/system/foi-insights.service`** on idc-1:

```ini
[Unit]
Description=Bluebird FOI Insights dashboard POC (FastAPI origin)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=algolotl
WorkingDirectory=/home/algolotl/foi-insights
EnvironmentFile=/etc/foi-insights.env
ExecStart=/home/algolotl/foi-insights/.venv/bin/python scripts/serve.py
Restart=on-failure
RestartSec=3
# The origin is only reachable via the tunnel; 127.0.0.1 would be fine too.
Environment=FOI_HOST=0.0.0.0

[Install]
WantedBy=multi-user.target
```

Install + start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now foi-insights
systemctl status foi-insights
```

The app's golden boot check runs at startup: if the loaded frame disagrees with
the published Q1 2025-26 figures, the process aborts loudly and the unit goes
into a restart loop — that is the data-integrity gate refusing to serve wrong
data, not a hang.

## 2. Environment file — `/etc/foi-insights.env`

Owned by `root:algolotl`, `0640`. Read by the unit via `EnvironmentFile`:

```bash
# LLM endpoint for /ask. Defaults (code-side) are shown; set at least FOI_LLM_MODEL.
FOI_LLM_URL=http://idc-1:8012/v1/chat/completions
FOI_LLM_MODEL=qwen3next-80b-a3b-q4
FOI_PG_DSN=postgresql://algolotl:<real-role-password>@localhost:5432/horizon
FOI_PORT=8097
FOI_SESSION_SECRET=<generated-on-idc-1, never committed>
```

| Variable | Default (code) | Purpose |
|---|---|---|
| `FOI_LLM_URL` | `http://idc-1:8012/v1/chat/completions` | The local model endpoint `/ask` calls. |
| `FOI_LLM_MODEL` | `qwen3next-80b` | The model name in the completion payload. **Must be the model idc-1 actually serves.** |
| `FOI_PG_DSN` | `postgresql://algolotl:algolotl@localhost:5432/horizon` | Postgres for auth, chat audit + lineage (fail-open if unreachable). |
| `FOI_PORT` | `8095` | The port the service binds (must match the tunnel ingress). |
| `FOI_SESSION_SECRET` | `dev-insecure-secret` (insecure) | Signs login sessions. Must be a real secret in prod. |
| `FOI_LEDGER` | `data/generated/lineage.jsonl` | JSONL lineage firehose path (relative to the working dir). |

**`FOI_LLM_MODEL` is the one that bites.** The default `qwen3next-80b` 404s on
idc-1:8012 — the endpoint answers but rejects that model name, so every `/ask`
falls back to the deterministic canned spec. The demo still 200s, but the "real
LLM completion" never happens. The model idc-1 serves is
`qwen3next-80b-a3b-q4` (Qwen3-Next-80B-A3B Q4_K_XL, the `algolotl-llm-author`
unit on :8012). Verify after deploy:

```bash
ssh 100.86.3.50 "curl -s http://localhost:8012/v1/models"
# find the exact id, then:
grep '^FOI_LLM_MODEL=' /etc/foi-insights.env
```

`scripts/deploy.py --check` runs this check for you and flags a missing/wrong pin.

**`FOI_PG_DSN` carries the real credential.** The documented default
`algolotl:algolotl` does NOT authenticate over the network — the horizon
Postgres (`algolotl-pg` container) requires the real role password. The live
env file holds the working DSN (password never surfaced). `FOI_SESSION_SECRET`
was generated on idc-1 and never committed anywhere.

## 3. The Cloudflare Tunnel

The tunnel exposes the origin as a hostname the Worker can reach, without any
public port. It is the same pattern as horizon's `api.axoquant.com`, and the
existing `cloudflared` on idc-1 is reused.

Add the ingress to **`/etc/cloudflared/config.yml`** (with the tunnel ID from
`cloudflared tunnel list`):

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /root/.cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: foi.axoquant.com
    service: http://localhost:8097
  - hostname: api.axoquant.com        # keep the existing horizon route
    service: http://localhost:8095
  - service: http_status:404
```

```bash
cloudflared tunnel route dns <TUNNEL_ID> foi.axoquant.com
sudo systemctl restart cloudflared
```

Verify the origin is reachable through the tunnel (this is the origin route the
Worker calls):

```bash
curl -s https://foi.axoquant.com/health
# {"status":"ok","model":"fartkraft sovereign stack"}
```

## 4. The Cloudflare Worker

A thin, stateless passthrough (mirrors horizon's `bluebell-horizon-demo`) that
forwards every path + query + header unchanged to the tunnel origin. There is
no `/api/*` remap here — the FOI app's routes are already top-level (`/ask`,
`/lineage/{id}`) — so the Worker is just `forward()`. Access control lives in
the app (session login + the internal-only risk role), not in the Worker.

```js
// foi-insights-worker: thin passthrough to the tunnel origin.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // legacy .workers.dev -> canonical host
    if (url.hostname.endsWith(".workers.dev")) {
      return Response.redirect("https://foi.axoquant.com" + (url.pathname === "/" ? "" : url.pathname), 301);
    }
    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.delete("content-length");
    const init = { method: request.method, headers, redirect: "manual" };
    if (request.method === "POST" || request.method === "PATCH" || request.method === "PUT" || request.method === "DELETE") {
      init.body = await request.arrayBuffer();
    }
    try {
      const resp = await fetch(env.API_ORIGIN + url.pathname + url.search, init);
      const outHeaders = new Headers(resp.headers);
      outHeaders.set("Cache-Control", "no-store, must-revalidate");
      return new Response(resp.body, { status: resp.status, headers: outHeaders });
    } catch (err) {
      return new Response(JSON.stringify({ error: `origin unreachable: ${err.message}` }), {
        status: 502, headers: { "Content-Type": "application/json" },
      });
    }
  },
};
```

`wrangler.toml`:

```toml
name = "foi-insights"
main = "src/index.js"
compatibility_date = "2026-07-01"
# routes must stay ABOVE [vars] (any key below a TOML table header is a var).
routes = [
  { pattern = "foi.axoquant.com", custom_domain = true }
]

[vars]
API_ORIGIN = "https://foi.axoquant.com"   # the tunnel hostname
```

Deploy (the one-time routing step `scripts/deploy.py` does not touch):

```bash
cd hosting/worker   # the Worker tree (or a foi-insights/hosting/worker copy)
npx wrangler deploy
```

## 5. Login gate, and the "static pages with the chat down" guarantee

- **The chat, reports and risk views are session-gated.** `/chat.html` and
  `/reports.html` redirect anonymous visitors to `/login` (303); `/risk.html`
  additionally returns 403 for logged-in accounts without the `internal` role.
  Logins authenticate against `horizon.foi_chat_users` (PBKDF2-hashed
  passwords). The statistics pages and `/ask` stay public. The live box was
  verified from `https://foi.axoquant.com`: anonymous 303s on the gated pages,
  authenticated 200s with the "FOI Insights" masthead.
- **Pilot accounts.** The four accounts (`foi.public` viewer, `foi.pilot`,
  `foi.internal`, `foi.officer` internal) are created by
  `scripts/seed_pilot_users.py` (idempotent; passwords printed once to stdout,
  never stored plaintext, never recoverable). This requires the `role` column
  from `src/server/migrate.sql` (`ALTER TABLE horizon.foi_chat_users ADD COLUMN
  IF NOT EXISTS role ...`).
- **The static pages render with the chat/LLM path down.** The pages are built
  at boot from platform-computed figures (the frame + catalog), not from the
  LLM. A dead `idc-1:8012`, a wrong `FOI_LLM_MODEL`, a down Postgres — none of
  them touch the pages; only `/ask` and the lineage viewer degrade, and they
  degrade honestly (canned spec / synthetic artifact id, both logged). The data
  is the published statistics, so the public pages carry nothing non-public.
- **There is no auth-free guarantee.** Earlier versions of this doc described a
  no-auth open demo; that is no longer the case. The login gate is real and the
  session secret must be set in `/etc/foi-insights.env` (the code refuses to
  mint or accept sessions signed with the public `dev-insecure-secret` default).

## 6. Deploying a change

```bash
# from the repo root on the workstation
python scripts/deploy.py --dry-run      # print every command, run nothing
python scripts/deploy.py --check        # probe idc-1: unit + env + model pin
                                        #   + autogluon + role column + pilots
python scripts/deploy.py                # scp src/ scripts/ data/ + pip install + restart
```

`deploy.py` pushes `src/`, `scripts/`, `data/sources/`, `data/corpus/`,
`requirements.txt`, `pyproject.toml` to `/home/algolotl/foi-insights/` on idc-1,
refreshes the venv, restarts `foi-insights`, and re-checks the model pin. It
does **not** touch the tunnel or Worker — those are one-time setup (sections 3
and 4), changed only when the route itself changes.

`--check` now also verifies the risk-model deploy story, and all three will
report MISSING until the steps below are run:

```
autogluon: MISSING (run .venv/bin/pip install -r requirements.txt; ~6-9GB, idc-1 only)
role column: MISSING (apply the Task 1 ALTER from src/server/migrate.sql)
pilot accounts: MISSING (0/4; run scripts/seed_pilot_users.py)
```

**One-time setup after a fresh deploy:**

```bash
# 1. role migration (Task 1) — the ALTER lives in src/server/migrate.sql; the
#    app's boot ensure_schema() also applies it on a reachable DB.
ssh algolotl@100.86.3.50 'cd /home/algolotl/foi-insights && .venv/bin/python -c \
  "from storage.db import get_conn, ensure_schema; ensure_schema(get_conn())"'

# 2. pilot accounts (Task 2) — idempotent; passwords printed once, never stored.
ssh algolotl@100.86.3.50 'cd /home/algolotl/foi-insights && .venv/bin/python scripts/seed_pilot_users.py'

# 3. AutoGluon risk fit (Task 7) — offline; ~6-9GB venv install on idc-1 only.
ssh algolotl@100.86.3.50 'cd /home/algolotl/foi-insights && .venv/bin/pip install -r requirements.txt'
ssh algolotl@100.86.3.50 'cd /home/algolotl/foi-insights && .venv/bin/python scripts/fit_risk_models.py'
# then restart the unit so the fitted artifacts are picked up:
ssh algolotl@100.86.3.50 'sudo systemctl restart foi-insights'
```

Until `fit_risk_models.py` runs on idc-1, `/risk.html` renders the honest
"not yet fitted" state — the service never fabricates a forecast or tier.

## 7. Fitted risk models

`scripts/fit_risk_models.py` is an **offline, idc-1-only** step. It loads the
canonical facts (the same frame + golden gate as the ingest path), builds
no-leakage features, and fits:

- `TimeSeriesPredictor` (AutoGluon-Chronos, preset `chronos2_small`) over the
  FY received series → `data/generated/risk/forecast/` with `predictions.json`.
- `TabularPredictor` (TabPFN via `autogluon[tabarena]`, `best_quality`) over
  per-agency per-FY features, labelled with the **next-FY** timeliness tier →
  `data/generated/risk/classify/` with `tiers.json`.
- `risk_metadata.json` `{model, fitted_at, basis, source_rows, rows_hash,
  feature_version}` + a best-effort Postgres lineage record.

Labels are strictly future: the label for agency A at FY `n` is A's
timeliness share at FY `n+1`, the split is hard on the FY boundary, and the
final FY (no next-FY outcome) is unlabeled and excluded from training.

**Renderer contract.** The risk renderers (`src/risk/forecast.py`,
`classify.py`) were built against `[{fy, value, lo, hi}]` / `[{agency, tier,
prob}]` contracts. The real AutoGluon predictors do not return those shapes and
`TimeSeriesPredictor.predict` cannot take the `build_forecast_series` dict the
renderers pass, so the fit script does prediction **at fit time**, stores the
adapted output as JSON sidecars (`forecast/predictions.json`,
`classify/tiers.json`), and saves the raw predictors at
`forecast/model/` + `classify/model/`. Because the predictor artifacts sit one
level below the directory the renderers load, the current renderers' `load()`
fails cleanly into the honest "not yet fitted" section — a fitted idc-1 never
500s. To surface the fitted numbers, apply these one-line adjustments (deferred
to a follow-up; they change the render contract from "load + predict" to "load
+ read sidecar"):

- `src/risk/forecast.py` `render_forecast_section`: replace
  `points = _points(pred.predict(series))` with
  `points = json.load(open(os.path.join(model_dir, "predictions.json")))`
  (import `json`/`os`).
- `src/risk/classify.py` `render_classify_section`: replace
  `tiers = _tiers(pred.predict(features))` with
  `tiers = json.load(open(os.path.join(model_dir, "tiers.json")))`.

Every number the risk page shows comes from these artifacts or the frame — the
model never writes a digit.

## 8. Teardown / rollback

- Stop the origin: `sudo systemctl stop foi-insights` — the site dies (502 from
  the Worker).
- Remove the public route: delete the `foi.axoquant.com` hostname from
  `/etc/cloudflared/config.yml` + `cloudflared tunnel route dns` delete, and
  remove the Worker route / `wrangler delete`.
- Rollback a bad deploy: re-run the previous `deploy.py` from the last good
  tree — the unit restarts against whatever is in `/home/algolotl/foi-insights/`
  at that moment.
