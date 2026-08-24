# FOI Insights POC — Public vs Internal, Risk Layer, Pilot Accounts

**Status:** Approved design
**Date:** 2026-08-24
**Product:** Bluebird FOI Insights (`foi.axoquant.com`)
**Spec supersedes / extends:** `2026-08-23-foi-chat-reporting-design.md`, `2026-08-20-foi-dashboard-poc-design.md`

## 1. Context and goal

The FOI Insights POC currently serves the twelve published FOI statistics pages
to everyone, and a login-gated Chat & Reports section to three `foi.tester*`
accounts. The capability paper (docs/Bluebird-FOI-Insights-capability-paper.docx,
section 6) describes what the platform makes possible: richer public insight
(6a), a chat interface (6b), and for internal users risk-based insights built on
time-series forecasting and tabular classification (6c), linked with an
agency's own data (6d).

This spec builds the next slice as a POC: an explicit public-vs-authenticated
split, pilot accounts, and a risk-insights layer (6c) running on real AutoGluon
models, deployed live.

Decisions (approved by Alex, 2026-08-24):

- **Risk engine: full AutoGluon on idc-1.** `autogluon[tabarena]==1.5.0`
  (TabPFN tabular foundation model) + torch-CUDA, installed into the FOI venv on
  idc-1 (RTX 3090, 24 GB; 1 TB free disk; PyPI reachable — all verified
  2026-08-24). Forecasting via AutoGluon-Chronos (`TimeSeriesPredictor`),
  classification via `TabularPredictor` with TabPFN.
- **Two access tiers:** `viewer` (public pages + Chat & Reports) and `internal`
  (viewer scope + the Risk insights page). The split is explicit: **external
  users only ever see published data; internal users get forecasts and risk
  views.**
- **Pilot accounts:** four, two tiers.
- **Model-absent state first:** the risk page ships with an honest "models not
  yet fitted" state; an offline fit (`scripts/fit_risk_models.py`) on idc-1
  upgrades it. The live service never blocks on a fit and never renders a broken
  risk page.

Standing constraints carried forward (verbatim intent from prior specs):

- **The model never writes a digit.** All report figures come from the frame
  (`stats.catalog.foi_stats`); chat cites corpus/sources; the deterministic
  fallback never fabricates. The data path (ingest/catalog/figures) is
  untouched. The risk layer adds *platform/model-computed* numbers with
  provenance — never invented ones.
- **Rebrand rule:** OAIC appears nowhere on the public site EXCEPT inside the
  verbatim data-notes corpus. New pages are OAIC-free. Product name is **Bluebird
  FOI Insights**.
- **No leakage, no bias** (global CLAUDE.md): strict trailing windows,
  causal labels, no selection bias, honest survivorship, no lookahead features.
  `pd.rolling(window, min_periods=window)` → NaN warmup; never `.shift(-N)`;
  never full-series statistics; labels use only data observable before the label
  date.
- **Passwords never stored plaintext** — PBKDF2 per-user salt; printed once by
  the seed script, never recoverable; **credentials are session-only, never
  committed.**
- Commit footer on every commit: `Co-Authored-By: Claude Fable 5
  <noreply@anthropic.com>` as a proper git trailer (blank line before).

## 2. Access model

### 2.1 Roles

| Role | Sees | Route gate |
|---|---|---|
| `public` (unauthenticated) | 12 published pages | none |
| `viewer` (pilot) | public pages + Chat & Reports | session exists |
| `internal` (pilot) | everything a viewer sees + Risk insights | session exists **and** `role == "internal"` |

### 2.2 Schema

`horizon.foi_chat_users` gains a `role` column:

```sql
ALTER TABLE horizon.foi_chat_users
  ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'viewer'
  CHECK (role IN ('viewer','internal'));
```

Idempotent (matches `ensure_schema`'s `CREATE IF NOT EXISTS` pattern — migrate.sql
uses `ADD COLUMN IF NOT EXISTS`).

### 2.3 Session

`storage.auth.encode_session` currently stores `{user_id, username, exp}`.
It gains `role`. `_session_user` normalises it to `{"id", "username", "role"}`
(the same shape `_authenticate` returns). The existing fail-hard secret guard is
unchanged.

```python
# storage/auth.py
def encode_session(user_id, username, role, secret, ttl=43_200):
    payload = {"user_id": user_id, "username": username, "role": role,
               "exp": int(time.time()) + ttl}
    ...
```

Existing sessions minted before the role column are treated as `viewer` (the
default) — `payload.get("role", "viewer")`.

## 3. Pilot accounts

New idempotent seed script `scripts/seed_pilot_users.py` (same PBKDF2
discipline as `scripts/seed_chat_users.py`, which stays). Passwords generated
once, printed to stdout, never stored, never committed. Four accounts:

| Username | role | Persona |
|---|---|---|
| `foi.public` | `viewer` | a pilot who is logged in but public-scope |
| `foi.pilot` | `internal` | the general pilot persona |
| `foi.internal` | `internal` | the internal-user persona |
| `foi.officer` | `internal` | an OAIC-style officer persona (no OAIC branding on site) |

The seed sets `role` explicitly for new accounts and leaves existing accounts
untouched (idempotent). Pilot passwords are delivered in-session to Alex, never
written to the repo.

## 4. The Risk insights page (6c)

### 4.1 Route and gating

- `GET /risk.html` — gated on `user["role"] == "internal"`; anonymous or
  viewer → `303` to `/login` (viewer) or a "not authorised" 403 (internal-only).
- Masthead nav: authenticated users see **Chat / Reports / Risk / username /
  Log out**. The Risk link only renders for `role == "internal"`.
- `page_key="risk"` is added so the sidenav/top-nav active-state resolves; it
  does not appear in the public `NAV`.

### 4.2 Content

The page renders three sections, each platform/model-computed with a provenance
line:

1. **Forecast — request volume (next 1–3 FY).** From the FY received series,
   `TimeSeriesPredictor` (AutoGluon-Chronos). Shows the historical series, the
   forecast points, and prediction intervals. Provenance: model, basis, source
   rows, rows_hash, fitted-at.
2. **Forecast — timeliness share.** Same treatment for the within-statutory
   share series (computed from the annual within_statutory/decided rows).
3. **Classification — risk tiers.** `TabularPredictor` (TabPFN) over per-agency
   per-FY feature rows → timeliness-risk and volume/outcome-risk tiers. Renders
   tier, class probability, and top features per agency.

### 4.3 Data build (no leakage)

Feature rows: one row per (agency, FY) from the canonical facts — volume
(received/decided), timeliness share, outcome mix (granted_full/part, refused,
withdrawn), and YoY deltas. Labels use a **future** outcome with strict trailing
windows:

- `pd.rolling(window, min_periods=window)` so warmup bars return NaN.
- `.shift(1)` on any feature that is derived from the current bar (a bar is
  never its own feature/label).
- No `.shift(-N)`, no full-series quantiles, no `bfill`.
- Time-split train (FY ≤ N) / test (FY > N); the model is never scored on data
  it saw.

Forecast features are computed the same way (trailing windows over the FY
series). The existing catalog's `_fy_series` (annual FY totals, quarter=None)
is the source — it is pure frame → data with no lookahead.

### 4.4 Model-absent state (first live deploy)

Until the fit produces artifacts, `GET /risk.html` renders an honest state:

> Risk models are not yet fitted. Run `scripts/fit_risk_models.py` on idc-1 to
> train the forecast and classification models; this page will then show
> model-computed forecasts and risk tiers.

No fabricated number, no broken page. The `scripts/fit_risk_models.py` offline
run upgrades it.

### 4.5 Artifacts and provenance

- Fit writes to `data/generated/risk/` on idc-1: model artifacts
  (`forecast/`, `classify/`), a `risk_metadata.json` with `{model, fitted_at,
  basis, source_rows, rows_hash, feature_version}`.
- The service **loads fitted artifacts at boot**; boot never blocks on a fit.
- A provenance record rides the lineage tables (reusing the existing
  `lineage_ops` / `lineage_artifacts` pattern) so every risk figure traces like
  every other figure.

### 4.6 Dependencies

`autogluon[tabarena]==1.5.0` + torch-CUDA added to the FOI venv on idc-1.
The fit runs on the RTX 3090. `requirements.txt` gains the pin (or a dedicated
`requirements-risk.txt` if install size/order warrants — decided at
implementation; the deploy installs it). The **runtime app import** of autogluon
is lazy (inside the risk module, only when artifacts exist), so the public pages
and chat/report paths never import torch.

## 5. The logon button and flow

- Masthead (public): a branded **Log in** button (already exists as a link;
  styled as a clear CTA).
- Authenticated: the account block — Chat / Reports / Risk (internal only) /
  username / Log out.
- `_user_nav` in `site/templates.py` is updated: `user` now carries `role`, and
  the Risk link is conditional on it.

## 6. Deploy

- `docs/deploy.md`: document the AutoGluon venv install on idc-1, the `role`
  migration, `seed_pilot_users.py`, the offline fit, and the model-pin verify.
- `scripts/deploy.py` `--check`: verify autogluon is installed + the role column
  exists + pilot accounts are seeded.
- Live host: `foi.axoquant.com` (the current, correct host — the deploy doc's
  `foi.fartkraft.ai` reference is stale and is corrected as part of this work).

## 7. Out of scope (this POC)

- Real OAIC data-lake integration (6d) — capability described in the paper, not
  built here. The risk layer is built to accept a joined dataset later without
  re-architecting.
- Anything beyond the four pilot accounts.
- Front-end UI polish beyond the masthead button + Risk page rendering.

## 8. Acceptance criteria

1. Unauthenticated visitors see only the 12 public pages; masthead shows the
   Log in button.
2. `foi.public` logs in → sees Chat & Reports, **no** Risk link, `/risk.html`
   403/redirect.
3. `foi.pilot` / `foi.internal` / `foi.officer` log in → see Chat, Reports,
   Risk; `/risk.html` renders.
4. Before fit: `/risk.html` renders the honest model-absent state. After
   `scripts/fit_risk_models.py`: the page renders model-computed forecasts and
   risk tiers with provenance, and the model never writes a digit.
5. The full suite passes (existing + new tests for role gating, session role,
   model-absent render, feature-build no-leakage invariants).
6. Deployed to `foi.axoquant.com` and verified live (masthead, log in, tier
   gating, Risk page state).
