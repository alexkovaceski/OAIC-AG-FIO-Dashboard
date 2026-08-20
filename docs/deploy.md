# Deploy — FOI Insights on idc-1 + foi.fartkraft.ai

The POC runs on the existing horizon serving stack: a FastAPI origin on idc-1,
a Cloudflare Tunnel, and a thin Cloudflare Worker. Public URL
`https://foi.fartkraft.ai` → Worker → tunnel → idc-1 origin. No auth — the demo
is open to anyone who reaches the URL, and the 12 static pages render even when
the chat/LLM path is down.

```
browser ──HTTPS──> Cloudflare Worker (foi-insights: thin passthrough, no gate)
                        │  forwards path + query + headers unchanged
                        ▼
                   Cloudflare Tunnel (cloudflared on idc-1)
                        │
                   foi-insights (FastAPI :8097, loopback) — serves EVERYTHING
                        ├─ /                at-a-glance page
                        ├─ /{page}.html     the 12 static pages
                        ├─ /assets/*        site.css
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
Description=FOI Insights dashboard POC (FastAPI origin)
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
FOI_PG_DSN=postgresql://algolotl:algolotl@localhost:5432/horizon
FOI_PORT=8097
```

| Variable | Default (code) | Purpose |
|---|---|---|
| `FOI_LLM_URL` | `http://idc-1:8012/v1/chat/completions` | The local model endpoint `/ask` calls. |
| `FOI_LLM_MODEL` | `qwen3next-80b` | The model name in the completion payload. **Must be the model idc-1 actually serves.** |
| `FOI_PG_DSN` | `postgresql://algolotl:algolotl@localhost:5432/horizon` | Postgres for lineage (fail-open if unreachable). |
| `FOI_PORT` | `8095` | The port the service binds (must match the tunnel ingress). |
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
  - hostname: foi.fartkraft.ai
    service: http://localhost:8097
  - hostname: api.axoquant.com        # keep the existing horizon route
    service: http://localhost:8095
  - service: http_status:404
```

```bash
cloudflared tunnel route dns <TUNNEL_ID> foi.fartkraft.ai
sudo systemctl restart cloudflared
```

Verify the origin is reachable through the tunnel (this is the origin route the
Worker calls):

```bash
curl -s https://foi.fartkraft.ai/health
# {"status":"ok","model":"fartkraft sovereign stack"}
```

## 4. The Cloudflare Worker

A thin, stateless passthrough (mirrors horizon's `bluebell-horizon-demo`) that
forwards every path + query + header unchanged to the tunnel origin. There is
no `/api/*` remap here — the FOI app's routes are already top-level (`/ask`,
`/lineage/{id}`) — so the Worker is just `forward()`.

```js
// foi-insights-worker: thin passthrough to the tunnel origin.
// No gate, no auth — the public demo is open.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // legacy .workers.dev -> canonical host
    if (url.hostname.endsWith(".workers.dev")) {
      return Response.redirect("https://foi.fartkraft.ai" + (url.pathname === "/" ? "" : url.pathname), 301);
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
  { pattern = "foi.fartkraft.ai", custom_domain = true }
]

[vars]
API_ORIGIN = "https://foi.fartkraft.ai"   # the tunnel hostname
```

Deploy (the one-time routing step `scripts/deploy.py` does not touch):

```bash
cd hosting/worker   # the Worker tree (or a foi-insights/hosting/worker copy)
npx wrangler deploy
```

## 5. No auth, and the "static pages with the chat down" guarantee

- **No auth anywhere in the path.** The Worker has no gate, the tunnel forwards
  to a loopback origin, and the FastAPI app has no auth middleware. Anyone who
  reaches `https://foi.fartkraft.ai` can read every page and drive `/ask`. That
  is the spec's choice (§7.3) — it is a public demo, so it must not hold
  personal information or anything non-public. It does not: the data is the
  published OAIC statistics.
- **The 12 static pages render with the chat/LLM path down.** The pages are
  built at boot from platform-computed figures (the frame + catalog), not from
  the LLM. A dead `idc-1:8012`, a wrong `FOI_LLM_MODEL`, a down Postgres — none
  of them touch the pages; only `/ask` and the lineage viewer degrade, and they
  degrade honestly (canned spec / synthetic artifact id, both logged).

## 6. Deploying a change

```bash
# from the repo root on the workstation
python scripts/deploy.py --dry-run      # print every command, run nothing
python scripts/deploy.py --check        # probe idc-1: unit + env + model pin
python scripts/deploy.py                # scp src/ scripts/ data/ + pip install + restart
```

`deploy.py` pushes `src/`, `scripts/`, `data/sources/`, `data/corpus/`,
`requirements.txt`, `pyproject.toml` to `/home/algolotl/foi-insights/` on idc-1,
refreshes the venv, restarts `foi-insights`, and re-checks the model pin. It
does **not** touch the tunnel or Worker — those are one-time setup (sections 3
and 4), changed only when the route itself changes.

## 7. Teardown / rollback

- Stop the origin: `sudo systemctl stop foi-insights` — the site dies (502 from
  the Worker).
- Remove the public route: delete the `foi.fartkraft.ai` hostname from
  `/etc/cloudflared/config.yml` + `cloudflared tunnel route dns` delete, and
  remove the Worker route / `wrangler delete`.
- Rollback a bad deploy: re-run the previous `deploy.py` from the last good
  tree — the unit restarts against whatever is in `/home/algolotl/foi-insights/`
  at that moment.
