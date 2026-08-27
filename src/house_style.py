"""house_style — the runtime wiring of the house-style repo into LLM prompts.

The house-style repo (github.com/alexkovaceski/house-style) is the single source
of truth for the voice and the anti-slop banlist. This module reads the linked
.house-style/ files at boot and returns the block the LLM prompts append;
scripts/deploy.py ships the folder to idc-1 with the service, so an edit to the
style repo propagates on the next deploy without touching this code. When the
folder is absent (a checkout without the link, the test suite), a short fallback
block keeps the same voice in outline.

The block is injected into every prompt that authors prose a reader sees: the
chat narrative answers and the builder's panel titles and descriptions. Platform
curated text (notes, escalations, the provenance registry) is written by hand
and never routed through the model.
"""
from __future__ import annotations
from pathlib import Path

from config import PROJECT_ROOT

_STYLE_DIR = PROJECT_ROOT / ".house-style"

# Fallback when the linked repo is not present (hermetic tests, a checkout
# without the link). Deliberately short: the live files are the authority.
_FALLBACK_BLOCK = (
    "House style: short, fewer sentences than feel right. Plain Australian "
    "English with AU spelling. Quiet authority, own the call. Numbers over "
    "adjectives. No em dashes, no curly quotes, no bold-first bullets, no "
    "\"it's not X, it's Y\", no magic adverbs (quietly, seamlessly, deeply), "
    "no delve, leverage, robust, tapestry, landscape, paradigm, synergy, "
    "ecosystem, framework, seamless, elevate, unlock. No stakes inflation, "
    "no \"let's unpack\", no signposted conclusions. If it reads like a "
    "LinkedIn post or a McKinsey deck, rewrite."
)

# The files that shape generated prose. voice.md is the register and the banlist;
# tropes.md is the catalog of AI-writing tells. prose.md (research notes) and
# lrs.md (expert-to-expert documents) are not injected: a chat answer is neither.
_STYLE_FILES = ("voice.md", "tropes.md")


def load_style_block() -> str:
    """The house-style prompt block: the linked files when present, the short
    fallback otherwise. The app calls this once at import (boot), matching the
    no-hot-reload discipline of the rest of the boot surface."""
    parts = []
    for name in _STYLE_FILES:
        try:
            text = (_STYLE_DIR / name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            parts.append(text)
    if not parts:
        return _FALLBACK_BLOCK
    return "\n\n".join(parts)
