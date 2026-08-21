"""templates — shared OAIC-styled page chrome (header nav, sidenav, footer).

The chrome adopts the OAIC identity: a dark navy masthead with the top-level
OAIC nav (Privacy / FOI / Consumer Data Right / Digital ID / Engage with us /
About — links OUT to the live OAIC site), a breadcrumb, a two-column layout of
sidenav + main, and a footer with the Acknowledgement of Country, ©
Commonwealth of Australia, legal links, and the identity stovepipe
(fartkraft sovereign stack). The stovepipe rides in the footer on every page so
it is never out of sight, exactly as the Task 6 guardrail carries it on the
chat path.
"""
from __future__ import annotations
import html

# top-level OAIC nav; the FOI section carries the POC pages. Entries are
# (label, href); those with a submenu list the POC pages it contains (the
# submenu itself is rendered as the breadcrumb context, not a fly-out). The
# links point OUT to the live OAIC site; the FOI section is where the POC sits.
NAV = [
    ("Privacy", "https://www.oaic.gov.au/privacy"),
    ("Freedom of information", "https://www.oaic.gov.au/freedom-of-information", [
        ("Australian Government FOI statistics", "/"),
    ]),
    ("Consumer Data Right", "https://www.oaic.gov.au/consumer-data-right"),
    ("Digital ID", "https://www.oaic.gov.au/digital-id"),
    ("Engage with us", "https://www.oaic.gov.au/engage-with-us"),
    ("About the OAIC", "https://www.oaic.gov.au/about-the-oaic"),
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

# every page points back to the FOI section; the POC pages live under it
ACTIVE_SECTION = "Freedom of information"
BREADCRUMB = ("Freedom of information › Australian Government "
              "freedom of information statistics")


def _flat_nav():
    out = []
    for t, href, *sub in NAV:
        out.append((t, href))
    return out


def nav_html(active_nav: str | None = None) -> str:
    """Top-level OAIC nav row. `active_nav` marks the current section as active
    (the gold accent)."""
    links = []
    for t, href in _flat_nav():
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


def chrome(title: str, active_nav: str | None = None, body_html: str = "",
           page_key: str | None = None, scripts: str | None = None) -> str:
    """The OAIC-styled shell: dark masthead + top nav, breadcrumb, a two-column
    layout of sidenav + main, and the footer.

    Returns a complete, self-contained HTML document. Every page carries the
    identity stovepipe in the footer (never out of sight).

    `scripts` (a str of <script> tags, e.g. the ECharts + init bundle) is
    rendered immediately before </body>. It is caller-controlled markup, not
    escaped — only the page renderers pass it, never a URL-routed value.

    The title is escaped here (not at call sites) so any caller-supplied
    string — e.g. the URL-routed artifact_id on the lineage page — can never
    become reflected XSS in <title>.
    """
    title = html.escape(title)
    tail_scripts = f"{scripts}\n" if scripts else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/assets/site.css">
<link rel="stylesheet" href="/assets/tailwind.css">
</head>
<body>
<header class="site-header bg-navy text-white border-b-3 border-teal flex items-center justify-between flex-wrap gap-2 px-8 py-3">
  <div class="logo text-xl font-bold"><a class="text-white no-underline" href="/">OAIC <span class="logo-rule text-gold px-0.5">·</span> FOI Insights</a></div>
  <nav class="topnav flex flex-wrap gap-1">{nav_html(active_nav)}</nav>
</header>
<div class="breadcrumb bg-paper border-b border-hair text-muted text-sm px-8 py-2">{BREADCRUMB}</div>
<div class="layout flex items-start max-w-layout mx-auto">
  {sidenav_html(page_key)}
  <main class="flex-1 max-w-main mx-auto bg-white px-8 py-8 min-h-main">{body_html}</main>
</div>
<footer class="sitefoot bg-navy text-neutral-200 text-sm px-8 py-7">
  <div class="country">We acknowledge the Traditional Custodians of Country throughout Australia and pay our respects to Elders past, present and emerging.</div>
  <div class="legal">© Commonwealth of Australia <span class="sep">·</span> <a href="https://www.oaic.gov.au/privacy">Privacy</a> <span class="sep">·</span> <a href="https://www.oaic.gov.au/freedom-of-information">FOI</a></div>
  <div class="stack">FOI Insights — fartkraft sovereign stack · data from data.gov.au (OAIC FOI statistics)</div>
</footer>
{tail_scripts}</body>
</html>"""
