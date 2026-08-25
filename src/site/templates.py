"""templates — shared Bluebird FOI Insights page chrome (header nav, sidenav, footer).

The chrome is the Bluebird FOI Insights identity, styled after Bluebird Horizon
(horizon.axoquant.com): a light surface masthead with the navy "Bluebird" word
and violet "FOI INSIGHTS" product label, the top-level nav (Overview / Requests /
Decisions / Timeliness / Reference — all internal, the POC must not link out to
the source agency site), a breadcrumb, a two-column layout of sidenav + main,
and a footer with the Acknowledgement of Country, in-site legal links, and the
identity stovepipe (fartkraft sovereign stack). The stovepipe rides in the
footer on every page so it is never out of sight, exactly as the Task 6
guardrail carries it on the chat path.
"""
from __future__ import annotations
import html
import hashlib
from pathlib import Path

# top-level nav: the FOI section's own groups (all internal — the POC must not
# link out to the source agency site). Entries are (label, first_page_key); nav_html
# resolves the href from SIDENAV_GROUPS, and chrome() marks the group that
# contains the current page active.
NAV = [
    ("Overview", "at-a-glance"),
    ("Requests", "requests-received"),
    ("Decisions", "requests-decided"),
    ("Timeliness", "timeliness"),
    ("Reference", "data-notes"),
]

# left portal nav groups: (group_label, [(page_key, label)])
SIDENAV_GROUPS = [
    ("Overview", [("at-a-glance", "FOI at a glance")]),
    ("Requests", [("requests-received", "Requests received"),
                  ("key-agency-contributions-received", "Key agency contributions"),
                  ("requests-finalised", "Requests finalised")]),
    ("Decisions", [("requests-decided", "Requests decided"),
                   ("key-agency-contributions-decided", "Key agency contributions"),
                   ("decision-outcomes", "Decision outcomes"),
                   ("change-decision-outcomes", "Change in decision outcomes")]),
    ("Timeliness", [("timeliness", "Timeliness"),
                    ("change-timeliness", "Change in timeliness")]),
    ("Reference", [("data-notes", "Data notes"),
                   ("how-to-use", "How to use"),
                   ("api", "API access")]),
]

BREADCRUMB = ("Bluebird FOI Insights › FOI statistics")


_ASSETS = Path(__file__).resolve().parent / "assets"


def _css_link(rel: str, name: str) -> str:
    """A versioned stylesheet link: a ?v= content-hash suffix so a CSS change
    changes the URL and any browser holding the pre-fix cached sheet re-fetches
    (the site serves stylesheets with Cache-Control: public, max-age=14400)."""
    digest = hashlib.sha256((_ASSETS / name).read_bytes()).hexdigest()[:12]
    return f'<link rel="{rel}" href="/assets/{name}?v={digest}">'


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


def nav_html(active_nav: str | None = None) -> str:
    """Top-level FOI section nav row. `active_nav` marks the current group as
    active (the seal underline). Links point at each group's first page."""
    links = []
    for t, first_key in NAV:
        href = f"/{_group_page(t)}.html"
        cls = 'nav-link active' if t == active_nav else 'nav-link'
        links.append(f'<a class="{cls}" href="{href}">{t}</a>')
    return "\n".join(links)


def sidenav_html(page_key: str) -> str:
    # layout is Tailwind utilities (fixed 216px column, sticky); the inner
    # .group/.navbtn styling stays in site.css. Class names are static literals
    # so Tailwind's content scan compiles them. The 216px width is the
    # w-sidenav theme token (see tailwind/input.css) — Tailwind's arbitrary
    # values are flaky under the v4 content scan, named tokens are not.
    out = ['<nav class="sidenav shrink-0 w-sidenav sticky top-0 self-start '
           'max-h-screen overflow-y-auto pt-6 pr-4 pb-8 pl-8" '
           'aria-label="FOI statistics">']
    for group, items in SIDENAV_GROUPS:
        out.append(f'<div class="group">{html.escape(group)}</div>')
        for key, label in items:
            cls = "navbtn active" if key == page_key else "navbtn"
            out.append(f'<a class="{cls}" href="/{key}.html">{html.escape(label)}</a>')
    out.append("</nav>")
    return "\n".join(out)


def _user_nav(user) -> str:
    if user is None:
        return '<a class="nav-link btn-login" href="/login">Log in</a>'
    risk = ('<a class="nav-link" href="/risk.html">Risk</a>'
            if user.get("role") == "internal" else "")
    return ('<a class="nav-link" href="/chat.html">Chat</a>'
            '<a class="nav-link" href="/reports.html">Reports</a>' + risk
            + '<span class="nav-username">'
            + html.escape(str(user.get("username", ""))) + '</span>'
            '<a class="nav-link" href="/logout">Log out</a>')


def chrome(title: str, body_html: str = "", page_key: str | None = None,
           scripts: str | None = None, user: dict | None = None) -> str:
    """The Bluebird FOI Insights shell: Bluebird Horizon masthead + top nav,
    breadcrumb, a two-column layout of sidenav + main, and the footer.

    Returns a complete, self-contained HTML document. Every page carries the
    identity stovepipe in the footer (never out of sight).

    `page_key` selects the active sidenav entry AND the active top-nav group
    (via _page_group). `scripts` (a str of <script> tags) is rendered
    immediately before </body>; caller-controlled markup, never a URL-routed
    value. The title is escaped here so a URL-routed value can never become
    reflected XSS in <title>.

    `user` (a session dict) selects the masthead account nav; with
    `user=None` the pre-existing shell content is byte-identical to the old
    behaviour — only the masthead Log in link is added, and all 13 existing
    callers omit the param.
    """
    title = html.escape(title)
    active = _page_group(page_key) if page_key else None
    tail_scripts = f"{scripts}\n" if scripts else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<script>document.documentElement.setAttribute("data-theme","light");</script>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{_css_link("stylesheet", "site.css")}
{_css_link("stylesheet", "tailwind.css")}
</head>
<body>
<a class="skip-link" href="#main">Skip to main content</a>
<header class="site-header flex items-center justify-between flex-wrap gap-2 px-8 py-3">
  <div class="logo"><img class="bb-mark" src="/assets/bb-logo.png" alt="Bluebird" width="34" height="34"><a class="wordmark" href="/"><span class="wordmark-name">Bluebird</span><span class="wordmark-product">FOI INSIGHTS</span></a></div>
  <nav class="topnav flex flex-wrap gap-1" aria-label="Primary">{nav_html(active)}</nav>
  {_user_nav(user)}
</header>
<div class="hairlines"></div>
<div class="breadcrumb text-sm px-8 py-2">{BREADCRUMB}</div>
<div class="layout flex items-start max-w-layout mx-auto">
  {sidenav_html(page_key)}
  <main id="main" class="flex-1 max-w-main mx-auto px-8 py-8 min-h-main">{body_html}</main>
</div>
<footer class="sitefoot text-sm px-8 py-7">
  <div class="country">We acknowledge the Traditional Custodians of Country throughout Australia and pay our respects to Elders past, present and emerging.</div>
  <div class="legal"><a href="/data-notes.html">Data notes</a> <span class="sep">·</span> <a href="/how-to-use.html">How to use</a> <span class="sep">·</span> <a href="/api.html">API access</a></div>
  <div class="stack">Bluebird FOI Insights — fartkraft sovereign stack · data from data.gov.au (FOI statistics)</div>
</footer>
{tail_scripts}</body>
</html>"""
