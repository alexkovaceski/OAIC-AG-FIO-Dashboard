# FOI Insights: Load Speed + WCAG Stylesheet + FOI Rebrand — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the POC faster (smaller echarts bundle + gzip + cache headers), fix stylesheet WCAG/readability issues, and rebrand the public site from the OAIC identity to FOI Insights — with the data/figures/contract untouched.

**Architecture:** Three independent tracks: (1) replace the full echarts bundle with the prebuilt "common" dist, add GZipMiddleware + asset cache headers; (2) strip dead pre-ECharts CSS, fix AA contrast + type + skip-link/focus; (3) rebrand the chrome (masthead, top nav, breadcrumb, footer) + prose away from "OAIC", keeping the verbatim data-notes corpus byte-identical under a framing line.

**Tech Stack:** Python 3.13, FastAPI/Starlette 1.6.0, pytest. No build step (ECharts prebuilt dist).

## Global Constraints

- **Never invent a number.** No figure, fact, or series changes. Only the presentation layer and static-asset delivery.
- **OAIC appears nowhere on the public site except inside the verbatim data-notes corpus.** The corpus (`data/corpus/data-notes.md`) is byte-identical — every site-authored string is OAIC-free.
- **Version pin:** echarts `5.6.0` (the newest published 5.x; **5.6.1 does not exist on npm**). Same 5.x line as the vendored bundle.
- **Measured sizes (2026-08-21):** common dist = 664,311 bytes raw / 219,469 gzip. Full bundle = 1,034,102 raw / 335,351 gzip.
- **Design language kept:** dark `#002a3a` navy masthead, gold `#ffcc00` accent, two-level nav (top nav + sidenav) — the OAIC-derived style stays; only the OAIC *name* and outbound links are dropped.
- **The fartkraft sovereign stack stovepipe stays in the footer** on every page (identity element).
- **The 3 text pages** (`data-notes`, `how-to-use`, `api`) never load echarts (unchanged).
- All 126 existing tests stay green.

---

### Task 1: Swap the echarts bundle for the common dist

**Files:**
- Create: `src/site/assets/echarts.common.min.js`
- Delete: `src/site/assets/echarts.min.js`
- Modify: `src/site/pages.py:26-27` (`_CHART_SCRIPTS`)

**Interfaces:**
- Consumes: nothing (self-contained).
- Produces: `_CHART_SCRIPTS` now references `/assets/echarts.common.min.js`; the file `src/site/assets/echarts.common.min.js` exists on disk and is what every chart page loads.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui.py`:

```python
def test_echarts_uses_common_dist_not_full_bundle():
    # the full echarts bundle is ~1MB; the prebuilt common dist (bar/line/pie)
    # is all the chart system renders, at ~36% smaller. Guards a regression
    # back to the heavyweight bundle.
    from pathlib import Path
    common = Path("src/site/assets/echarts.common.min.js")
    assert common.exists(), "common dist not vendored"
    assert common.stat().st_size < 750_000, "common dist suspiciously large"
    assert not Path("src/site/assets/echarts.min.js").exists(), \
        "full bundle should have been removed"
    for key in ["at-a-glance", "requests-received", "decision-outcomes",
                "timeliness"]:
        assert "/assets/echarts.common.min.js" in _pages()[key]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ui.py::test_echarts_uses_common_dist_not_full_bundle -v -p no:cacheprovider --color=no -o addopts=`
Expected: FAIL — common dist missing; `echarts.min.js` still referenced.

- [ ] **Step 3: Download the common dist**

```bash
curl -sL "https://cdn.jsdelivr.net/npm/echarts@5.6.0/dist/echarts.common.min.js" \
  -o src/site/assets/echarts.common.min.js
ls -la src/site/assets/echarts.common.min.js   # expect 664,311 bytes
```

Verify it is a JS file and registers the chart types the system uses:
```bash
grep -oc '"bar"' src/site/assets/echarts.common.min.js
grep -oc '"line"' src/site/assets/echarts.common.min.js
grep -oc '"pie"' src/site/assets/echarts.common.min.js
```
Expected: each ≥ 1. (Minified ECharts registers chart types by these string literals.)

- [ ] **Step 4: Remove the full bundle and update the reference**

```bash
git rm src/site/assets/echarts.min.js
```

In `src/site/pages.py` `_CHART_SCRIPTS`:
```python
_CHART_SCRIPTS = ('<script src="/assets/echarts.common.min.js"></script>\n'
                  '<script src="/assets/foi-charts.js"></script>')
```

- [ ] **Step 5: Update the two other test references**

`tests/test_ui.py:35` and `:52` reference `echarts.min.js` — change to `echarts.common.min.js` in `test_pages_emit_echarts_containers_and_pagedata` and `test_echarts_asset_present`.

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --color=no -o addopts=`
Expected: green (127 = 126 + the new test).

- [ ] **Step 7: Commit**

```bash
git add src/site/assets/echarts.common.min.js src/site/pages.py tests/test_ui.py
git commit -m "perf(assets): swap full echarts bundle for the prebuilt common dist
```

Commit footer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` (prepend `\n\n` to the body).

---

### Task 2: GZip compression + asset cache headers

**Files:**
- Modify: `src/server/app.py` (imports, `create_app`)

**Interfaces:**
- Consumes: the FastAPI `app` in `create_app()` (defined at `app.py:266`).
- Produces: every response over ~1KB gzipped when the client accepts it; `/assets/*` responses carry `Cache-Control: public, no-cache`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_server.py`:

```python
def test_gzip_compresses_pages_and_assets():
    c = TestClient(create_app())
    for path in ["/at-a-glance.html", "/assets/site.css"]:
        r = c.get(path, headers={"Accept-Encoding": "gzip"})
        assert r.status_code == 200
        assert r.headers.get("content-encoding") == "gzip"


def test_assets_carry_revalidation_cache_header():
    c = TestClient(create_app())
    r = c.get("/assets/site.css")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, no-cache"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_server.py::test_gzip_compresses_pages_and_assets tests/test_server.py::test_assets_carry_revalidation_cache_header -v -p no:cacheprovider --color=no -o addopts=`
Expected: FAIL — no `content-encoding`; no `cache-control`.

- [ ] **Step 3: Add GZipMiddleware**

In `src/server/app.py`:
```python
from starlette.middleware.gzip import GZipMiddleware  # after the other starlette imports
```
In `create_app()`, immediately after `app = FastAPI(title="FOI Insights")`:
```python
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

- [ ] **Step 4: Add the asset cache-header middleware**

Starlette 1.6.0's `StaticFiles` has no `headers=` kwarg (verified), so add a tiny middleware. Below `app.mount(...)`:

```python
    @app.middleware("http")
    async def _asset_cache(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/assets/"):
            response.headers.setdefault("Cache-Control", "public, no-cache")
        return response
```

(`Request` is already imported at `app.py:50`.)

- [ ] **Step 5: Run to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_server.py::test_gzip_compresses_pages_and_assets tests/test_server.py::test_assets_carry_revalidation_cache_header -v -p no:cacheprovider --color=no -o addopts=`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --color=no -o addopts=`
Expected: green (129).

- [ ] **Step 7: Commit**

```bash
git add src/server/app.py tests/test_server.py
git commit -m "perf(server): gzip responses + revalidation cache headers on /assets
```

Commit footer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 3: Stylesheet cleanup (WCAG AA contrast, dead CSS, type, a11y)

**Files:**
- Modify: `src/site/assets/site.css`
- Modify: `src/site/templates.py` (skip link + `<main id="main">` — needed so the skip link has a target and the test passes)

**Interfaces:**
- Consumes: the current `site.css` (`:root` tokens, `.kpi`/`.figure-card`/`.chartbox`/`.nodata`/`.sidenav`/`.sitefoot` blocks).
- Produces: same class names (no template changes beyond `<main id="main">`); AA-passing tokens; dead CSS removed; skip-link styles.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui.py`:

```python
def test_every_page_has_skip_link_and_main_landmark():
    for html in _pages().values():
        assert '<a class="skip-link" href="#main"' in html, "skip link missing"
        assert '<main id="main">' in html, "main landmark missing"


def test_top_nav_has_primary_aria_label():
    for html in _pages().values():
        assert 'aria-label="Primary"' in html


def test_muted_token_passes_aa_on_white():
    # --muted must reach 4.5:1 on white for the small labels that use it.
    from pathlib import Path
    css = Path("src/site/assets/site.css").read_text(encoding="utf-8")
    m = re.search(r"--muted:\s*(#[0-9a-fA-F]{6})", css)
    assert m, "no --muted token"
    lum = _relative_luminance(m.group(1))
    ratio = (1.05) / (lum + 0.05)
    assert ratio >= 4.5, f"--muted {m.group(1)} is {ratio:.2f}:1 (needs >= 4.5:1)"


def _relative_luminance(hex6):
    import math
    vals = []
    for i in (0, 2, 4):
        c = int(hex6[i:i + 2], 16) / 255
        vals.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]
```

(Place `_relative_luminance` as a module-level helper in `test_ui.py`.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ui.py -k "skip_link or primary_aria or muted_token" -v -p no:cacheprovider --color=no -o addopts=`
Expected: FAIL — no skip link, no `aria-label="Primary"`, `--muted` below 4.5:1.

- [ ] **Step 3: Fix the contrast tokens**

In `src/site/assets/site.css` `:root`, darken `--muted` from `#6b7a86` to **`#54626f`** (passes 4.5:1 on white). Recompute and confirm ≥ 4.5 if you adjust it further.

- [ ] **Step 4: Fix `:focus-visible`**

```css
:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}
```
(Gold-on-white was ~1.6:1; `currentColor` adapts to the background. Keep the gold active-nav underline in `.topnav .nav-link.active`.)

- [ ] **Step 5: Bump the tiny type**

In `site.css`:
- `.sidenav .group` `font-size: 0.72rem` → `0.78rem`
- `.kpi .tlabel` `0.72rem` → `0.78rem`
- `.kpi .basis` `0.72rem` → `0.78rem`

- [ ] **Step 6: Delete the dead pre-ECharts CSS**

Remove these blocks from `site.css`: `.chart`, `.chart-h`, `.chart-h-tall`, `.bar-row`, `.bar-row::after`, `.bar-end`, `.bar-end.none`, `.bval`, `.bcat`, `.bseries`. Confirm they are referenced nowhere first:
Run: `grep -rn "bar-row\|bar-end\|bval\|bcat\|bseries\|chart-h" src/site/`
Expected: only `site.css` itself. Keep `.chartbox` and `.nodata` (still used).

- [ ] **Step 7: Add the skip-link CSS + update the site.css header comment**

```css
/* --- skip link (WCAG 2.4.1): visually hidden until focused ------------------ */

.skip-link {
  position: absolute;
  left: -9999px;
  top: 0;
  z-index: 100;
}
.skip-link:focus {
  left: 0;
  top: 0;
  background: var(--white);
  color: var(--ink);
  padding: 0.6rem 1rem;
  border: 2px solid var(--navy);
  border-radius: 0 0 6px 0;
  text-decoration: none;
}
```

Update the `site.css` header comment to drop the "OAIC identity" phrasing (e.g. "FOI Insights chrome + the FOI Insights chart system") and note the AA-contrast/`currentColor`-focus choices.

- [ ] **Step 8: Add the skip link + main landmark in templates.py**

In `chrome()` (`src/site/templates.py:106-131`), immediately after `<body>`:
```html
<a class="skip-link" href="#main">Skip to main content</a>
```
and change the main element to `<main id="main" class="flex-1 ...">` (same classes, add `id="main"`). Give the top nav `aria-label="Primary"`:
```html
<nav class="topnav flex flex-wrap gap-1" aria-label="Primary">...</nav>
```

- [ ] **Step 9: Run the tests + full suite**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ui.py -k "skip_link or primary_aria or muted_token" -v -p no:cacheprovider --color=no -o addopts=`
Then: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --color=no -o addopts=`
Expected: all green (132).

- [ ] **Step 10: Commit**

```bash
git add src/site/assets/site.css src/site/templates.py tests/test_ui.py
git commit -m "fix(site): WCAG AA contrast, skip link, dead CSS removal, larger labels
```

Commit footer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 4: Rebrand the chrome (masthead, top nav, breadcrumb, footer)

**Files:**
- Modify: `src/site/templates.py`

**Interfaces:**
- Consumes: `NAV`/`SIDENAV_GROUPS`/`BREADCRUMB`/`ACTIVE_SECTION` (`templates.py:19-50`), `chrome()` (`:88-131`), `nav_html()` (`:60-67`).
- Produces: `nav_html()` takes an active group name; `chrome()` derives the active group from `page_key` via a `_group_for()` helper; `NAV` becomes the 5 internal FOI groups; masthead "FOI Insights"; breadcrumb "FOI Insights › FOI statistics"; footer de-OAIC'd with in-site links. `ACTIVE_SECTION`/the `active_nav` parameter are removed.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui.py`:

```python
def test_no_outbound_oaic_links_or_branding():
    for key, html in _pages().items():
        assert "oaic.gov.au" not in html, f"{key}: outbound OAIC link remains"
        if key == "data-notes":
            assert "OAIC" in html  # verbatim corpus keeps the publisher's name
        else:
            assert "OAIC" not in html, f"{key}: OAIC name remains outside corpus"
        assert "© Commonwealth of Australia" not in html, f"{key}: AG copyright"


def test_masthead_is_foi_insights():
    for html in _pages().values():
        assert ">FOI Insights</a>" in html, "masthead missing FOI Insights"


def test_top_nav_links_are_all_internal():
    for html in _pages().values():
        nav = re.search(r'<nav[^>]*aria-label="Primary"[^>]*>(.*?)</nav>', html, re.S)
        assert nav, "primary nav not found"
        for href in re.findall(r'href="([^"]+)"', nav.group(1)):
            assert href.startswith("/"), f"external top-nav link: {href}"


def test_footer_has_in_site_links():
    html = _pages()["at-a-glance"]
    for link in ["/data-notes.html", "/how-to-use.html", "/api.html"]:
        assert link in html, f"footer missing in-site link {link}"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ui.py -k "oaic or masthead or internal or footer" -v -p no:cacheprovider --color=no -o addopts=`
Expected: FAIL — outbound OAIC links, "OAIC" in masthead, external top-nav links, no in-site footer links.

- [ ] **Step 3: Rewrite NAV as the 5 FOI groups**

In `src/site/templates.py`, replace `NAV` (lines 19-28) with:

```python
# top-level nav: the FOI section's own groups (all internal — the POC must not
# link out to the OAIC site). Entries are (label, first_page_key); nav_html
# resolves the href from SIDENAV_GROUPS, and chrome() marks the group that
# contains the current page active.
NAV = [
    ("Overview", "at-a-glance"),
    ("Requests", "requests-received"),
    ("Decisions", "requests-decided"),
    ("Timeliness", "timeliness"),
    ("Reference", "data-notes"),
]
```

Remove `ACTIVE_SECTION`. Replace `BREADCRUMB` with `("FOI Insights › FOI statistics")`.

- [ ] **Step 4: Add the group resolver**

```python
def _page_group(page_key: str) -> str | None:
    """The top-nav group containing `page_key` (from SIDENAV_GROUPS), or None."""
    for group, items in SIDENAV_GROUPS:
        for key, _label in items:
            if key == page_key:
                return group
    return None


def _group_page(group: str) -> str:
    """First page key of a top-nav group (its href target)."""
    for g, items in SIDENAV_GROUPS:
        if g == group:
            return items[0][0]
    raise ValueError(group)
```

- [ ] **Step 5: Rewrite nav_html to render internal links + active group**

```python
def nav_html(active_nav: str | None = None) -> str:
    """Top-level FOI section nav row. `active_nav` marks the current group as
    active (the gold underline). Links point at each group's first page."""
    links = []
    for t, first_key in NAV:
        href = f"/{_group_page(t)}.html"
        cls = 'nav-link active' if t == active_nav else 'nav-link'
        links.append(f'<a class="{cls}" href="{href}">{t}</a>')
    return "\n".join(links)
```

- [ ] **Step 6: Derive the active group in chrome(); update the shell**

Change `chrome()`'s signature: **drop the `active_nav` parameter entirely** and compute the active group from `page_key` inside:

```python
def chrome(title: str, body_html: str = "", page_key: str | None = None,
           scripts: str | None = None) -> str:
    """The FOI Insights shell: dark navy masthead + top nav, breadcrumb, a
    two-column layout of sidenav + main, and the footer.

    Returns a complete, self-contained HTML document. Every page carries the
    identity stovepipe in the footer (never out of sight).

    `page_key` selects the active sidenav entry AND the active top-nav group
    (via _page_group). `scripts` (a str of <script> tags) is rendered
    immediately before </body>; caller-controlled markup, never a URL-routed
    value. The title is escaped here so a URL-routed value can never become
    reflected XSS in <title>.
    """
    active = _page_group(page_key) if page_key else None
```

Update the header:
```html
<div class="logo text-xl font-bold"><a class="text-white no-underline" href="/">FOI Insights</a></div>
<nav class="topnav flex flex-wrap gap-1" aria-label="Primary">{nav_html(active)}</nav>
```
Update the breadcrumb to `{BREADCRUMB}` (already a constant). Add the skip link + `<main id="main">` if not already present from Task 3.

- [ ] **Step 7: De-OAIC the footer**

```html
<footer class="sitefoot bg-navy text-neutral-200 text-sm px-8 py-7">
  <div class="country">We acknowledge the Traditional Custodians of Country throughout Australia and pay our respects to Elders past, present and emerging.</div>
  <div class="legal"><a href="/data-notes.html">Data notes</a> <span class="sep">·</span> <a href="/how-to-use.html">How to use</a> <span class="sep">·</span> <a href="/api.html">API access</a></div>
  <div class="stack">FOI Insights — fartkraft sovereign stack · data from data.gov.au (FOI statistics)</div>
</footer>
```

- [ ] **Step 8: Update every chrome() call site — all 15 callers**

Because the second positional arg is removed, **every** caller must drop its `"Freedom of information"` argument (not just the pages): grep first, then fix all of these:

```bash
grep -rn "chrome(" src/ --include="*.py" | grep -v "def chrome"
```

The full set (verified):
- `src/site/pages.py` — 13 calls (lines 317, 333, 347, 365, 380, 393, 411, 425, 441, 454, 468, 502, 553): remove the `"Freedom of information"` positional arg; keep the `page_key=` kwarg on each.
- `src/site/lineage_viewer.py:224` — `chrome(f"Lineage — {artifact_id}", "Freedom of information", body, page_key="lineage")` → drop the `"Freedom of information"` arg (keep `page_key="lineage"`).
- `src/server/app.py:259` — `chrome(f"Dashboard — {artifact_id}", "Freedom of information", body)` → drop the `"Freedom of information"` arg (no `page_key`, so no active group).

Then run `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --color=no -o addopts=` and fix any remaining `TypeError` from a missed caller.

- [ ] **Step 9: Run the tests + full suite**

Run: `.venv\Scripts\python.exe -m pytest tests/test_ui.py -k "oaic or masthead or internal or footer" -v -p no:cacheprovider --color=no -o addopts=`
Then: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --color=no -o addopts=`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add src/site/templates.py src/site/pages.py src/server/app.py tests/test_ui.py
git commit -m "feat(site): rebrand chrome from OAIC to FOI Insights

Masthead 'FOI Insights'; top nav becomes the five FOI groups with
all-internal links; breadcrumb 'FOI Insights > FOI statistics'; footer
carries in-site links and no AG copyright. The OAIC name survives only
inside the verbatim data-notes corpus.
```

Commit footer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 5: Prose scrub (how-to-use, api) + data-notes framing line + foi-charts comment

**Files:**
- Modify: `src/site/pages.py` (how-to-use + api prose, data-notes framing line)
- Modify: `src/site/assets/foi-charts.js` (palette comment only)

**Interfaces:**
- Consumes: `_page_how_to_use()` (`pages.py:472`), `_page_api()` (`:507`), `_page_data_notes()` (`:458`).
- Produces: no "OAIC" outside the verbatim corpus; a framing line above the verbatim notes block; a neutral palette comment.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pages.py`:

```python
def test_data_notes_carries_verbatim_framing_line():
    html = _pages()["data-notes"]
    assert "reproduced verbatim from the source" in html.lower()
    assert "OAIC" in html  # the corpus itself keeps the publisher's name
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pages.py::test_data_notes_carries_verbatim_framing_line -v -p no:cacheprovider --color=no -o addopts=`
Expected: FAIL — no framing line.

- [ ] **Step 3: Scrubbing the prose**

In `src/site/pages.py`:
- `_page_how_to_use` intro: "published on data.gov.au (OAIC FOI statistics)" → "published on data.gov.au (FOI statistics)".
- `_page_how_to_use` data-notes line: "the OAIC's definitional notes verbatim" → "the publisher's definitional notes verbatim".
- `_page_api` intro: "the canonical data sourced from data.gov.au (OAIC FOI statistics)" → "… (FOI statistics)".
- `_page_api` source line: link label "OAIC FOI statistics dataset" → "FOI statistics dataset"; the data.gov.au href and dataset id are unchanged.

- [ ] **Step 4: Add the framing line**

In `_page_data_notes`, above the `.notes` div:

```python
    body = ("<h1>Data notes and disclaimer</h1>"
            '<p class="intro">These notes are reproduced verbatim from the '
            "source dataset (FOI statistics) on data.gov.au.</p>"
            f'<div class="notes">{_md(notes)}</div>')
```

Do **not** touch `data/corpus/data-notes.md`.

- [ ] **Step 5: Neutral palette comment in foi-charts.js**

`foi-charts.js:24` — `// OAIC brand palette (validated categorical slots — see site.css tokens).` → `// Brand palette (validated categorical slots — see site.css tokens).`

- [ ] **Step 6: Run the tests + full suite**

Run: `.venv\Scripts\python.exe -m pytest tests/test_pages.py::test_data_notes_carries_verbatim_framing_line -v -p no:cacheprovider --color=no -o addopts=`
Then: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --color=no -o addopts=`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/site/pages.py src/site/assets/foi-charts.js tests/test_pages.py
git commit -m "feat(site): scrub OAIC from prose, frame the verbatim data notes, neutral palette comment
```

Commit footer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 6: Local serve check + deploy

**Files:**
- None expected (verify only).

- [ ] **Step 1: Full suite once more**

Run: `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --color=no -o addopts=`
Expected: green.

- [ ] **Step 2: Local serve check**

Start the server: `FOI_PORT=8095 .venv\Scripts\python.exe scripts/serve.py` (background). Then:
```bash
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null http://localhost:8095/at-a-glance.html | grep -i "content-encoding"
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null http://localhost:8095/assets/echarts.common.min.js | grep -i "content-length\|content-encoding"
curl -s -D - -o /dev/null http://localhost:8095/assets/site.css | grep -i "cache-control"
```
Expected: `gzip`; content-length < 300000; `public, no-cache`. Then grep a page for the masthead and the absence of "oaic.gov.au".

- [ ] **Step 3: Commit any fixes, then deploy**

```bash
git commit -am "fix: ..."  # only if the serve check found something
.venv\Scripts\python.exe scripts/deploy.py
```

- [ ] **Step 4: Verify the live site**

```bash
curl -s -H "Accept-Encoding: gzip" -D - -o /dev/null https://foi.axoquant.com/assets/echarts.common.min.js | grep -i "content-encoding\|content-length"
curl -s https://foi.axoquant.com/ | grep -c "OAIC\|oaic.gov.au"   # expect 0 on non-data-notes pages
curl -s https://foi.axoquant.com/data-notes.html | grep -c "OAIC"   # expect >= 1 (verbatim corpus)
curl -s -D - -o /dev/null https://foi.axoquant.com/assets/site.css | grep -i cache-control
```
Expected: gzip + size < 300000 on the echarts asset; no OAIC on the landing page; OAIC present on data-notes; cache-control on assets.

---

## Self-Review

- **Spec coverage:** §3 load (Tasks 1-2), §4 stylesheet (Task 3), §5 rebrand (Tasks 4-5), §7 testing across all, §8 not-in-scope untouched. Manual serve + live deploy in Task 6. All spec sections map to a task.
- **Placeholder scan:** all code blocks are concrete. Version pinned to 5.6.0 (5.6.1 does not exist); sizes are measured, not estimates.
- **Type consistency:** `_CHART_SCRIPTS` string updated in Task 1 and consumed identically in `chrome()`/`pages.py`; `nav_html(active_nav)`/`chrome(...)` signatures changed in Task 4 and their call sites updated in the same task; `_group_page`/`_page_group` names consistent. `test_ui.py` helpers (`_pages`, `_relative_luminance`) consistent across the tasks that add to that file.
- **Cross-task:** Task 3 (skip link + `<main id="main">`) and Task 4 (nav aria-label) both touch `templates.py:116-123`; Task 4's Step 6 notes not to duplicate Task 3's skip-link. If tasks run in sequence, no conflict.
