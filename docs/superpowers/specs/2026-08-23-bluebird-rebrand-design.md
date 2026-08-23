# Design — Rebrand: Bluebird FOI Insights

**Date:** 2026-08-23
**Status:** Agreed design (approved 2026-08-23)
**Owner:** Alex

## 1. Purpose

Rename the product from **FOI Insights** to **Bluebird FOI Insights** across the
site and the codebase. The name matches the existing escalation domain
(`contact@bluebirdadvisory.com.au`) already used by the chat/report escalation
paths, so the site and the email it directs users to will share a brand.

## 2. Rule that governs this feature

The rebrand is a **presentation-layer rename only**. It changes no data, no
auth, no report/chat behaviour, and no figure. The descriptive line
"Australian Government FOI statistics" that follows the name is unchanged.

The existing **rebrand rule** (from the chat-reporting spec) still holds:
**OAIC appears nowhere on the public site except inside the verbatim
data-notes corpus.** This change adds "Bluebird" to the name; it does not
touch the corpus.

## 3. The change

`FOI Insights` → `Bluebird FOI Insights` everywhere it names the site.
Case-insensitive occurrences of "FOI Insights" in the source, tests, and
docs follow the same replacement.

## 4. Files touched (expected)

**User-facing product strings:**

- `src/site/templates.py` — masthead logo (`>FOI Insights</a>`), breadcrumb
  (`BREADCRUMB`), footer stack (`FOI Insights — fartkraft sovereign stack`).
- `src/server/app.py` — `FastAPI(title="FOI Insights")` (line 365) and the
  API-docs description string (line 647).
- `src/agentic/render.py` — dashboard builder footer (lines 107, 110).
- `src/agentic/guardrails.py` — the two scope-refusal messages (lines 82, 84).
- `src/agentic/chat.py` — the assistant identity line in the system prompt
  (line 26).
- `src/agentic/builder.py` — the dashboard-architect identity (line 88).
- `src/site/pages.py` — intro copy (line 477).

**Tests:**

- `tests/test_ui.py:258` — masthead assertion `>FOI Insights</a>` →
  `>Bluebird FOI Insights</a>`. (This is the **only** test asserting the brand
  — verified by grep.)

**Docs describing the product:**

- `README.md`
- `docs/deploy.md`

**Internal docstrings / comments (consistency):**

- `src/api.py`, `src/config.py`, `src/__init__.py`, `src/server/__init__.py`,
  `src/agentic/__init__.py`, `src/site/assets/site.css`,
  `src/site/assets/foi-charts.js`, `tailwind/input.css`,
  `scripts/serve.py`, `scripts/deploy.py`.

**NOT touched (point-in-time records — the audit trail):**

- `docs/superpowers/specs/*`, `docs/superpowers/plans/*`, journals. These
  describe work at a moment in time; rewriting them would falsify history.
- `data/corpus/*` — the verbatim data-notes corpus (holds no brand string
  anyway; verified).

## 5. Verification

- The masthead test passes (`tests/test_ui.py::test_every_page_has_skip_link_and_main_landmark`
  or whichever asserts the brand).
- `grep -rn "FOI Insights" src tests README.md docs/deploy.md` returns **no
  hits** (all rebranded).
- `grep -rni "oaic" src/site` still returns **no hits** (the rebrand rule
  holds).
- Local serve: masthead reads "Bluebird FOI Insights"; chat/report/login pages
  render it.

## 6. Deploy

A follow-up `python scripts/deploy.py` after the chat-reporting deploy lands,
so the live site masthead reads "Bluebird FOI Insights".

## 7. Not in scope

- Changing the descriptive "Australian Government FOI statistics" copy.
- Any change to the data path (ingest/catalog/figures), auth, or chat/report
  behaviour.
- Rewriting historical specs/plans/journals.
- Renaming the `national-workforce` service or any other product.
