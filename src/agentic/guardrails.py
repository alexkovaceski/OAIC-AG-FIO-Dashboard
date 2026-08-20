"""guardrails — FOI-scope screen, jailbreak scan, identity. Defence-in-depth.

Two deterministic layers (mirroring horizon's request_governor.rule_screen +
dash_builder._JAILBREAK_RE) plus an in-scope FOI positive-signal check, so a
scope violation is caught even if one layer is bypassed. check_request raises
ScopeRefusal on anything outside the Australian Government FOI statistics use
case; it runs BEFORE the request reaches the model and before any artifact or
tool call is recorded.
"""
from __future__ import annotations
import re

class ScopeRefusal(Exception):
    pass

IDENTITY_STOVE = "I am powered by the fartkraft sovereign stack, trained on local data."

# Layer 1: deterministic regex scope screen (mirrors request_governor.rule_screen)
_OUT_OF_SCOPE_RE = re.compile(
    r"immigration|visa|citizenship|tax (advice|return)|benefit|pension|medicare|"
    r"health (advice|treatment)|defence (ops|operations|planning)|military (ops|strategy)|"
    r"united states|\busa\b|\buk\b|united kingdom|france|germany|china|russia|"
    r"crypto|bitcoin|stock (market|tip)|trading strategy|foreign (foi|freedom)|"
    r"personal (medical|financial) (info|record)|named individual|(?:a|an) (?:specific )?(?:person|individual)\b",
    re.I,
)
# the two-letter country code "US" (the plan's \busa\b misses it) — a separate
# context-gated alternation so the English pronoun "us" ("show us the trend")
# is NOT caught. Case-sensitive on purpose: the country code is written "US",
# "U.S." or "u.s." — the lowercase pronoun "us" must never trigger a refusal.
# "USA"/"United States" are already covered above. \s+ (not a trailing \b) after
# the dotted forms, because there is no word boundary between a dot and a space.
_US_COUNTRY_RE = re.compile(
    r"\b(?:US|U\.S\.|u\.s\.)\s+(?i:government|federal|state|health|healthcare|defen|"
    r"military|agenc|congress|president|citizenship|visa|state department|foi|freedom)",
)
# Layer 2: prompt-injection / jailbreak patterns (mirrors dash_builder._JAILBREAK_RE)
_JAILBREAK_RE = re.compile(
    r"ignore (all |any |your )?(previous|prior|above)|you are now|"
    r"act as (if )?(an? )?(unrestricted|dan|jailbreak)|disregard (your )?(rules|instructions)|"
    r"reveal (your |the )?(system |model |prompt|instructions|key)|"
    r"what('s| is) your (system prompt|instructions|model)|"
    r"execute (arbitrary )?(shell|code|command)|run (any )?code|"
    r"export (your |the )?(api|key|secret)|access (the )?(file system|database|server)|"
    r"show (me )?(your )?(internal|hidden|raw) (prompt|output|instructions)",
    re.I,
)
# in-scope positive signal (mirrors dash_builder workforce_terms)
_FOI_TERMS = (
    "foi", "freedom of information", "request", "requests", "received", "finalis",
    "decided", "decision", "outcome", "granted", "refused", "withdrawn", "timeliness",
    "statutory", "agency", "agencies", "portfolio", "quarter", "year", "trend",
    "compare", "top", "contributor", "home affairs", "services australia",
)

def check_request(text: str) -> None:
    t = (text or "").strip()
    if not t:
        raise ScopeRefusal("empty request")
    if _JAILBREAK_RE.search(t):
        raise ScopeRefusal("I'm going to stay on task — that request looks like it's trying to change what I do. Ask me about Australian FOI statistics instead.")
    if _OUT_OF_SCOPE_RE.search(t) or _US_COUNTRY_RE.search(t):
        raise ScopeRefusal("FOI Insights builds dashboards and reports from Australian Government freedom-of-information statistics. That request is outside that scope — ask me about FOI requests, decision outcomes, timeliness, or agency/portfolio trends instead.")
    if not any(w in t.lower() for w in _FOI_TERMS):
        raise ScopeRefusal("FOI Insights is focused on Australian Government FOI statistics — that's what I can build dashboards for. Ask me about requests received, decision outcomes, timeliness, or an agency trend.")
