"""templates — shared OAIC-styled page chrome (nav, breadcrumb, footer).

The chrome mirrors the OAIC site: masthead, top-level nav (Privacy / FOI /
Consumer Data Right / Digital ID / Engage with us / About), a breadcrumb, and a
footer with the Acknowledgement of Country. The identity stovepipe
(fartkraft sovereign stack) rides in the footer on every page so it is never
out of sight, exactly as the Task 6 guardrail carries it on the chat path.
"""
from __future__ import annotations
import html

# top-level nav mirroring the OAIC site; the FOI section carries the POC pages.
# Entries are (label, href); those with a submenu list the POC pages it contains
# (the submenu itself is rendered as the breadcrumb context, not a fly-out).
NAV = [
    ("Privacy", "#"),
    ("Freedom of information", "/", [
        ("Australian Government FOI statistics", "/"),
        ("Requests received", "/requests-received.html"),
        ("Decision outcomes", "/decision-outcomes.html"),
        ("Timeliness", "/timeliness.html"),
    ]),
    ("Consumer Data Right", "#"),
    ("Digital ID", "#"),
    ("Engage with us", "#"),
    ("About the OAIC", "#"),
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
    """Top-level nav row. `active_nav` marks the current section as active."""
    links = []
    for t, href in _flat_nav():
        cls = 'nav-link active' if t == active_nav else 'nav-link'
        links.append(f'<a class="{cls}" href="{href}">{t}</a>')
    return "\n".join(links)


def chrome(title: str, active_nav: str | None = None, body_html: str = "") -> str:
    """The OAIC-styled shell: masthead + nav, breadcrumb, body, footer.

    Returns a complete, self-contained HTML document. Every page carries the
    identity stovepipe in the footer (never out of sight).

    The title is escaped here (not at call sites) so any caller-supplied
    string — e.g. the URL-routed artifact_id on the lineage page — can never
    become reflected XSS in <title>.
    """
    title = html.escape(title)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="/assets/site.css">
</head>
<body>
<header class="masthead">
  <div class="logo"><a href="/">OAIC <span class="logo-rule">·</span> FOI Insights</a></div>
  <nav class="topnav">{nav_html(active_nav)}</nav>
</header>
<div class="breadcrumb">{BREADCRUMB}</div>
<main>{body_html}</main>
<footer class="sitefoot">
  <div class="country">We acknowledge the Traditional Custodians of Country throughout Australia and pay our respects to Elders past, present and emerging.</div>
  <div class="stack">FOI Insights — fartkraft sovereign stack · data from data.gov.au (OAIC FOI statistics)</div>
</footer>
</body>
</html>"""
