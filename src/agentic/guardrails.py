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

IDENTITY_STOVE = "I am powered by the axoquant sovereign stack, trained on local data."

# Layer 1: deterministic regex scope screen (mirrors request_governor.rule_screen)
_OUT_OF_SCOPE_RE = re.compile(
    r"immigration|visa|citizenship|tax (advice|return)|"
    r"welfare|centrelink|benefit (payments?|recipients?|claims?|advice)|pension|medicare|"
    r"health (advice|treatment)|defence (ops|operations|planning)|military (ops|strategy)|"
    r"united states|\busa\b|\buk\b|united kingdom|france|germany|china|russia|"
    r"canada|canadian|new zealand|mexico|mexican|japan|japanese|india|indian|"
    r"italy|italian|spain|spanish|europe|european|dutch|"
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
# other countries' FOI — the country-noun list above misses country ADJECTIVES and
# the two-letter codes ("German FOI requests", "Canadian FOI", "NZ FOI"). The
# adjectives are matched case-insensitively (unambiguous: "german", "french", ...);
# the two-letter codes are matched case-sensitively so the pronoun "us"/"uk"
# ("give us FOI statistics") is never caught. "Australian FOI" is deliberately not
# in either list.
_FOREIGN_FOI_RE = re.compile(
    r"\b(?:german|french|british|american|canadian|chinese|russian|japanese|"
    r"european|italian|spanish|mexican|indian|dutch|new zealand)"
    r"\s+(?:foi|freedom(?: of information)?)\b",
    re.I,
)
_FOREIGN_FOI_CODE_RE = re.compile(
    r"\b(?:US|UK|USA|NZ)\s+(?:FOI|freedom(?: of information)?)\b",
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

_WORD_RE = re.compile(r"[a-z]+")

# Agency NAMES stay substring-only in the fuzzy matcher: a one-edit slack on
# "home" makes "come from" read as an FOI signal, and no router pattern uses
# agency names, so nothing is lost by keeping them exact.
_AGENCY_TERMS = ("home affairs", "services australia")
_FUZZY_TERM_WORDS = frozenset(
    w for term in _FOI_TERMS if term not in _AGENCY_TERMS
    for w in _WORD_RE.findall(term))


def _levenshtein(a: str, b: str) -> int:
    """Edit distance, no deps. Requests and terms are short."""
    if a == b:
        return 0
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for i, cb in enumerate(b, 1):
        cur = [i]
        for j, ca in enumerate(a, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fuzzy_typo_distance(token: str) -> int:
    """The slack a token of this length gets against the FOI vocabulary: one
    edit for ordinary words, two for long ones (a dropped letter in
    "timeliness" writes "timlines", two edits from the term)."""
    return 2 if len(token) >= 8 else 1


def _has_foi_signal(text: str) -> bool:
    """Does the request carry an FOI positive signal, typos included?

    The exact substring check stays the fast path ("finalis" matches
    "finalised"). The fuzzy pass then admits near-miss spellings a real user
    types: "fio requets by agencie for home afairs" must clear the screen and
    reach the router, not get refused at the door. One edit of slack for
    ordinary words, two for long ones; a term word is only compared when its
    length is within that slack, so "chart" cannot become "quarter".
    """
    lowered = text.lower()
    if any(w in lowered for w in _FOI_TERMS):
        return True
    for token in _WORD_RE.findall(lowered):
        if len(token) < 4:
            continue
        slack = _fuzzy_typo_distance(token)
        for term in _FUZZY_TERM_WORDS:
            if abs(len(token) - len(term)) <= slack \
                    and _levenshtein(token, term) <= slack:
                return True
    return False


def check_request(text: str) -> None:
    t = (text or "").strip()
    if not t:
        raise ScopeRefusal("empty request")
    if _JAILBREAK_RE.search(t):
        raise ScopeRefusal("I'm going to stay on task — that request looks like it's trying to change what I do. Ask me about Australian FOI statistics instead.")
    if _OUT_OF_SCOPE_RE.search(t) or _US_COUNTRY_RE.search(t) \
            or _FOREIGN_FOI_RE.search(t) or _FOREIGN_FOI_CODE_RE.search(t):
        raise ScopeRefusal("Bluebird FOI Insights builds dashboards and reports from Australian Government freedom-of-information statistics. That request is outside that scope — ask me about FOI requests, decision outcomes, timeliness, or agency/portfolio trends instead.")
    if not _has_foi_signal(t):
        raise ScopeRefusal("Bluebird FOI Insights is focused on Australian Government FOI statistics — that's what I can build dashboards for. Ask me about requests received, decision outcomes, timeliness, or an agency trend. If you are asking where a figure came from, name it — \"where did the requests received figures come from?\" — and you will get its source files, hashes and curation decisions.")
