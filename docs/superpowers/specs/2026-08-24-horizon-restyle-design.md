# Bluebird Horizon restyle — Bluebird FOI Insights

## Goal

Restyle the FOI Insights portal to match the Bluebird Horizon visual identity as
shipped on axoquant.com/horizon (the "governed, sovereign AI" product family).
Keep the product wordmark **Bluebird FOI Insights**. This is a presentational
change only: no data, report, or figure values change, and the rebrand rule
(O A I C appears nowhere except the verbatim data-notes corpus) is untouched.

## Reference — Bluebird Horizon design system (fetched live from axoquant.com/horizon)

The Horizon page's compiled stylesheet (`_astro/_product_.DmgY100U.css`) defines:

- `--ink: #0e1419`, `--ink-raised: #141B22` — near-black surfaces
- `--paper: #EDEAE2`, `--paper-dim: #B7B4AA` — off-white text/surfaces
- `--seal: #2F9E6E`, `--seal-dim: #1F6B4A` — primary accent (green)
- `--evidence: #C77B3A` — amber accent
- `--ledger: #6E7680` — muted slate
- `--rule: rgba(237,234,226,.12)` — faint hairlines
- `--font-display: "Fraunces", Georgia, serif`
- `--font-sans: "Inter", -apple-system, "Segoe UI", Roboto, sans-serif`
- `--font-mono: "IBM Plex Mono", ui-monospace, Consolas, monospace`
- `--radius-sm: 2px`, `--radius-md: 3px` (small radii)
- `--space-*: .25rem→4rem`, `--max-w: 1120px`, `--max-w-narrow: 68ch`
- Masthead: `background: #0e1419e6; backdrop-filter: blur(10px)`, sticky
- Usage: `::selection{background:var(--seal)}`, `:focus-visible{outline:2px solid var(--seal)}`,
  `.btn--primary{background:var(--seal)}`, `.logo__word em{color:var(--seal)}`,
  small-caps uppercase section labels with `.14em` letter-spacing and `color:var(--seal)`,
  body `line-height:1.6`, `-webkit-font-smoothing`.

User decision: **faithful dark theme** — flip the whole portal to the dark
Horizon theme (not a light adaptation). Wordmark stays **Bluebird FOI Insights**.

## Token mapping (current → Horizon)

| Current token (navy/gold) | Horizon replacement |
|---|---|
| `--navy #002a3a` (masthead/header) | `--ink #0e1419` (masthead/header) |
| `--dark #003347` (depth/footer) | `--ink-raised #141B22` (footer/depth) |
| `--teal #00567d` (primary accent) | `--seal #2F9E6E` (primary accent) |
| `--blue #26547b` (secondary) | `--seal-dim #1F6B4A` (secondary/depth green) |
| `--ink #0c3c60` (body text) | `--paper #EDEAE2` (body text on dark) |
| `--paper #f7f7f7` (page bg) | `--ink #0e1419` (page bg) |
| `--white #ffffff` (cards/surfaces) | `--ink-raised #141B22` (cards/surfaces) |
| `--gold #ffcc00` (active underline) | `--seal #2F9E6E` (active underline) |
| `--hair #e6e6e6` (hairlines) | `--rule rgba(237,234,226,.12)` |
| `--muted #6b7a86` (secondary text) | `--paper-dim #B7B4AA` |
| `--c1 teal / c2 blue / c3 gold / c4 orange / c5 green` | Horizon-consistent categorical: `--c1 #2F9E6E` (seal), `--c2 #C77B3A` (evidence), `--c3 #B7B4AA` (paper-dim), `--c4 #6E7680` (ledger), `--c5 #1F6B4A` (seal-dim) |
| `--pos #1baf7a` / `--neg #eb6834` | keep semantic green/amber: `--pos #2F9E6E`, `--neg #C77B3A` |

## Scope — files and their changes

### 1. `tailwind/input.css` (the `@theme` block, recompiled via `npm run build:css`)

Replace the OAIC token values with the Horizon values so utilities like
`bg-navy`, `text-ink`, `border-gold`, `bg-paper`, `bg-white` compile to the
Horizon colors. **Also introduce new named tokens** so markup reads honestly:
`--color-ink: #0e1419`, `--color-ink-raised: #141B22`, `--color-paper: #edeae2`,
`--color-paper-dim: #b7b4aa`, `--color-seal: #2f9e6e`, `--color-seal-dim: #1f6b4a`,
`--color-evidence: #c77b3a`, `--color-ledger: #6e7680`, plus `--color-gold`
remapped to seal-green for the active accent and chart `c1–c5`.

**This requires the compiled `src/site/assets/tailwind.css` to be regenerated**
(`npm run build:css`) so the served CSS picks up the new token values. The
compiled file is committed, so both `input.css` and the built artifact ship.

### 2. `src/site/assets/site.css` (the `:root` block + component layer)

Update `:root` tokens to the Horizon values (same mapping above) and add the
Horizon typography: `--serif: "Fraunces", Georgia, serif` (display), plus the
Inter/IBM Plex Mono stacks. Replace the masthead/breadcrumb/footer/nav component
rules to the dark theme (masthead `#0e1419e6` + blur, hairline `--rule` rules,
seal-green active underline, small-caps uppercase section labels with `.14em`
tracking). Keep `:focus-visible` (now 2px seal) and `::selection` seal. Keep
the existing layout geometry (masthead px, sidenav 216px, two-column) — only
colors/type change.

### 3. `src/site/templates.py` (chrome markup)

The masthead currently uses Tailwind utilities `bg-navy text-white border-b-3
border-teal` and the footer `bg-navy text-neutral-200`, breadcrumb `bg-paper
border-hair text-muted`, and the logo `text-xl font-bold`. Because the token
values are re-mapped in step 1, most classes keep working — but for honesty
the markup should be updated to the Horizon names: `bg-ink text-paper
border-b-3 border-seal` for the masthead, `bg-ink-raised` for the footer,
`bg-ink text-paper-dim` for the breadcrumb. Update the `chrome()` docstring and
the `BREADCRUMB`/module comments that say "dark navy masthead" → "dark Horizon
masthead". Keep the wordmark **Bluebird FOI Insights** and the `_user_nav`
markup (Risk link, Log in CTA) exactly as-is — those are Task 6's.

### 4. `src/site/assets/foi-charts.js` (and any chart JS using `PAL`)

The charts' `PAL` map currently holds the navy/teal series colors. For the dark
theme, series colors and axis/grid hairlines must read on `#0e1419`. Update the
`PAL` categorical to Horizon-consistent series (above) and the axis/grid
`hair` line to `rgba(237,234,226,.12)`. Charts are dark-theme-appropriate.

### 5. `src/agentic/render.py` + `src/agentic/report.py` (report/chat figure palettes)

Grep shows these import or reference the same `PAL`/chart palette. They must be
updated to the Horizon palette wherever they define series colors, so chat and
report figures match.

### 6. Accessibility (WCAG AA on dark)

- Body text `#EDEAE2` on `#0e1419` ≈ 15.9:1 — AA AAA.
- Muted `#B7B4AA` on `#0e1419` ≈ 7.5:1 — AA.
- Seal-green `#2F9E6E` on `#0e1419` ≈ 6.6:1 for accents/links — AA; on
  `#141B22` still ≈ 5.9:1 — AA. (Do not use `--seal-dim` for text accents on
  dark surfaces; reserve it for filled buttons where white text sits on it,
  `#fff` on `#1F6B4A` ≈ 7.0:1.)
- The amber `#C77B3A` on dark ≈ 6.1:1 — AA (used for negative/evidence accents).
- Focus ring 2px seal; selection seal.

## Explicitly out of scope

- The public site stays O A I C-free (only the verbatim data-notes corpus).
- No figure/data values change; no reports recompute.
- The wordmark stays **Bluebird FOI Insights**.
- No new dependencies (Fraunces/Inter/IBM Plex Mono are loaded from Google
  Fonts or left as stack fallbacks — decide during implementation; if we load
  webfonts, gate them so they don't block; the stacks already include good
  fallbacks).
- The login page and chat/reports UI are restyled only insofar as they inherit
  the shared chrome/palette — no bespoke redesign.

## Acceptance

- Every page renders in the Horizon dark theme: ink body, paper text,
  seal-green accents, Fraunces display for headings.
- Charts and report figures use the Horizon-consistent series palette and
  readable hairlines on dark.
- Masthead wordmark reads **Bluebird FOI Insights**.
- Contrast of all body/muted/accent text meets WCAG AA on the dark surfaces.
- Existing layout (sidenav 216px, two-column, masthead geometry) unchanged.
- No `O A I C` introduced outside the data-notes corpus.

## Implementation notes

- The restyle spans 5-6 files and the compiled Tailwind artifact; treat it as
  one change so the theme flips coherently (a half-flipped site looks broken).
- Because Task 6 is mid-flight on `templates.py`/`site.css`, sequence the
  restyle to start only after Task 6 lands, to avoid edit collisions on the
  same lines.
- Verify by starting the server and opening the key pages (at-a-glance, a
  chart page, chat, reports, login, risk if internal) rather than relying on
  unit tests alone — this is a visual change.
