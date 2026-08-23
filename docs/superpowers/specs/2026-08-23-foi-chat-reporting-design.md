# Design — FOI Insights: gated chat & reporting with test accounts

**Date:** 2026-08-23
**Status:** Agreed design (approved 2026-08-23)
**Owner:** Alex

## 1. Purpose

Add a login-gated **Chat & reports** section to foi.axoquant.com, porting the
proven horizon pattern from the NationalWorkforce app (journal
`2026-08-22_bluebell_national_workforce.md`): a grounded Q&A chat over the FOI
statistics + corpus, and a report that turns a request into real figures. The
public statistics pages stay open; only the new section is gated. Out-of-scope
or unfulfillable requests escalate to an email redirect
(contact@bluebirdadvisory.com.au). No email registration — the email is the
escalation path only.

The data, lineage, governance, chart figures, and the "never invent a number"
contract are **not** changed — this adds a presentation + access layer on top
of the existing frame and corpus.

## 2. Rule that governs this feature

**The model never writes a digit.** Every figure surfaced by the chat or the
report is a direct read from the platform frame (`stats.catalog.foi_stats` over
the normalised data) or from the verbatim corpus. The LLM selects intent and
writes prose; it never produces a number. Where the platform cannot compute a
figure, the response says so and escalates to the email redirect — it never
invents one.

## 3. Auth model (test accounts)

- New table `horizon.foi_chat_users`: `id, username (unique), pw_hash, salt,
  display_name, created_at, is_active`. `pw_hash` = PBKDF2-HMAC-SHA256 with a
  per-user random salt (stdlib `hashlib.pbkdf2_hmac`, no new dependency).
- **Pre-seeded accounts** created by a new `scripts/seed_chat_users.py`
  (idempotent: skips existing usernames; prints generated passwords once to
  stdout — never stored plaintext). Alex distributes credentials to nominees.
- **Login page** `/login` — username + password form. On success, set a
  **hand-rolled signed-cookie session** (HMAC-SHA256 over
  `{user_id, username, exp}` with a server secret, constant-time compare;
  stdlib only — Starlette 1.6.0's SessionMiddleware needs `itsdangerous`,
  which is not installed and will not be added). Session expiry ~12h.
- **Logout** `/logout` clears the cookie.
- **Gate:** the new section's routes require a valid session;
  unauthenticated → 303 redirect to `/login`. Everything else on the site
  stays public.

## 4. Chat (grounded Q&A)

Port the NationalWorkforce `/chat` pipeline (`src/agentic/chat.py`) onto FOI:

- **Scope screen** (deterministic, before the model): refuses individual-advice
  / out-of-scope asks (personal case details, legal advice, non-FOI topics)
  with a helpful refusal that carries the email redirect.
- **Retrieval**: keyword/BM25 over the FOI **corpus** (`data/corpus/`, currently
  `data-notes.md`) plus measure/figure descriptions from `stats.catalog` —
  top-N context docs.
- **Grounded prompt** → sovereign LLM via `axoquant_llm.chat("author", …,
  app="foi-insights/chat", temperature=0.2, no_thinking=True)` (same call path
  as the existing `/ask`), rules: answer from context only, cite sources,
  never invent a digit, identity stovepipe.
- **Deterministic fallback**: on any model failure (or empty completion), an
  answer is assembled from the retrieved context — the chat never dies and
  never fabricates.
- **Citations** rendered under each answer ("Sources: …").

## 5. Report (figures, not prose)

Port the NationalWorkforce `/report` discipline (`src/agentic/report.py`):

- **Deterministic keyword router** over the FOI catalog
  (`stats.catalog.foi_stats` / `FIG_KEYS` / `STAT_KEYS`) → selects a stat key.
  The model never writes a digit; the number is computed by the platform from
  the frame.
- Response: `{request, stat_key, stat_label, data, dataset_registry}` — the
  same figures the charts render.
- Rendered as a report card with the real figure and its lineage/citation
  pointer. A request the router cannot map escalates to the email redirect.

## 6. Email escalation

When the chat scope screen refuses, the report router finds no match, or the
user asks for something the site cannot compute, the response carries
`escalate: true` and the UI shows a line with a `mailto:contact@bluebirdadvisory.com.au`
link. This is the only redirect mechanism; there is no email registration
workflow.

## 7. Pages & navigation

- New gated pages `/chat.html` and `/reports.html` in the existing `chrome()`
  (masthead "FOI Insights", no OAIC branding; rebrand rules hold).
- Navigation: a "Log in" link for anonymous visitors; once logged in, the nav
  shows the chat/reports entries and a "Log out" link.
- `/chat.html` — message log + input (vanilla JS, in the style of
  `foi-charts.js`); `/reports.html` — request box → report card.

## 8. Data & storage

- `horizon.foi_chat_users` — accounts (above).
- **`horizon.foi_chat_messages`** — append-only per-user message log:
  `id, user_id, role, content, created_at`. Lightweight audit trail
  ("note what we have done"). No session-replay UI in this pass.
- `ensure_schema()` (`src/server/migrate.sql`) gains the two tables
  (idempotent `CREATE TABLE IF NOT EXISTS`).

## 9. Security & correctness

- Passwords PBKDF2-hashed with per-user salt; never stored plaintext;
  credentials printed once by the seed script.
- Signed-cookie session, constant-time verification, expiry.
- **Never invent a number holds**: report figures come only from the frame;
  chat cites corpus/sources; fallback never fabricates. The data path
  (ingest/catalog/figures) is untouched.
- New pages carry no OAIC branding (corpus verbatim only).
- Scope screen runs before the model for chat; the report router is fully
  deterministic.

## 10. Testing & deploy

- New tests:
  - **Auth**: login success sets a session cookie; wrong password refused;
    unauthenticated access to gated routes redirects to `/login`; logout
    clears the session; session expiry.
  - **Chat**: scope refusal returns `escalate: true` + email; LLM failure →
    deterministic fallback (never dies, never fabricates); citations present
    on success.
  - **Report**: a request routes to the right `stat_key` and the figure matches
    the frame (no invented digits); unmappable request escalates.
  - **Branding**: the new pages are OAIC-free.
- Deploy via existing `scripts/deploy.py` (the new tables are created by
  `ensure_schema` at boot); seed accounts via `scripts/seed_chat_users.py` on
  idc-1; live verification of login + chat + report.
- Full suite stays green (139 today).

## 11. Files touched (expected)

- `src/server/migrate.sql` — two new tables.
- `src/server/app.py` — `/login`, `/logout`, `/chat.html`, `/reports.html`,
  `/chat`, `/report` routes; session middleware; gate on the new section.
- `src/agentic/chat.py` (new) — scope screen, retrieval, grounded prompt,
  fallback.
- `src/agentic/report.py` (new) — deterministic router over the FOI catalog.
- `src/corpus.py` (new) — retrieval over corpus + catalog descriptions.
- `src/site/pages.py` / `src/site/templates.py` — new pages + nav login state.
- `src/site/assets/chat.js`, `report.js` (new) — vanilla JS for the two pages.
- `scripts/seed_chat_users.py` (new) — idempotent account seeding.
- `tests/` — auth/chat/report/branding tests.

## 12. Not in scope

- Email registration or any account self-service.
- Session replay / conversation history UI.
- Gating the public statistics pages.
- Any change to the data path (ingest/catalog/figures).
