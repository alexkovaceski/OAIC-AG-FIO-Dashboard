"""api — read-only data API + rate limiter for FOI Insights.

The visualisations are built from platform-computed figures (foi_stats) over
the canonical long-form facts (the frame). This module exposes the SAME data
as a read-only JSON API, so a consumer can pull the underlying numbers behind
any chart without touching the builder or the LLM.

Endpoints (mounted in server/app.py):
  GET /api/          dataset info: snapshot, window modes, measures, keys
  GET /api/figures   all platform-computed figures (foi_stats), with basis
  GET /api/facts     long-form canonical facts, filterable (fy, measure,
                     bucket, agency, quarter); paged (limit/offset)
  GET /api/measures  the measure groups + their measures

Rate limiting: every /api/* request is throttled per client IP via a simple
in-memory fixed-window counter (limiter.check). The public no-auth demo must
not get hammered. The bucket is per process — fine for the single-origin POC.
"""
from __future__ import annotations

import time
from collections import defaultdict

from stats.catalog import foi_stats, FIG_KEYS, STAT_KEYS, FIG_CAPTIONS

# --- rate limiter: fixed-window per-IP --------------------------------------
# A tiny, dependency-free throttle. Per IP we allow RATE_LIMIT requests per
# WINDOW seconds; the 429 response tells the client to back off. This is not a
# security boundary — it is a "don't get smashed" throttle for a public demo.
RATE_LIMIT = int(__import__("os").environ.get("FOI_RATE_LIMIT", "60"))   # per window
RATE_WINDOW = float(__import__("os").environ.get("FOI_RATE_WINDOW", "60"))  # seconds

_buckets: dict[str, tuple[float, int]] = defaultdict(lambda: (0.0, 0))


def check(ip: str) -> tuple[bool, int, float]:
    """Return (allowed, remaining, retry_after). Throttles per IP in a window."""
    now = time.monotonic()
    window_start, count = _buckets[ip]
    if now - window_start >= RATE_WINDOW:
        window_start, count = now, 0
    count += 1
    _buckets[ip] = (window_start, count)
    if count > RATE_LIMIT:
        return False, 0, RATE_WINDOW - (now - window_start)
    return True, RATE_LIMIT - count, 0.0


def _client_ip(request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# --- the data payloads --------------------------------------------------------

def dataset_info(frame) -> dict:
    """Dataset snapshot + what the API exposes."""
    measures = sorted({f["measure"] for f in frame.facts})
    measure_groups = sorted({f["measure_group"] for f in frame.facts})
    fy = sorted({f["fy"] for f in frame.facts})
    return {
        "dataset": "data.gov.au OAIC FOI statistics",
        "dataset_id": "b0771c28-09cc-4c4e-9e61-9a96f6e3d040",
        "window_modes": ["single_quarter", "cumulative", "fy"],
        "measures": measures,
        "measure_groups": measure_groups,
        "fy": fy,
        "fact_count": len(frame.facts),
        "figure_keys": list(FIG_KEYS),
        "stat_keys": list(STAT_KEYS),
        "source": "https://data.gov.au/data/dataset/freedom-of-information-statistics",
        "disclaimer": "Data provided by Australian Government agencies and "
                      "ministers under the FOI Act 1982. See /data-notes.html.",
    }


def figures(frame) -> dict:
    """Every platform-computed figure/stat, with basis, from the SAME catalog
    the visualisations use. Never a model number."""
    out = {}
    for k in STAT_KEYS:
        try:
            v = foi_stats(frame, k)
            out[k] = {"value": v["value"], "basis": v["basis"]}
        except KeyError:
            continue  # a key the frame can't compute stays absent (no fabrication)
    for k in FIG_KEYS:
        try:
            v = foi_stats(frame, k)
            out[k] = {"value": v["value"], "basis": v["basis"]}
        except KeyError:
            continue
    return out


def facts(frame, *, fy=None, measure=None, bucket=None, agency=None,
          quarter=None, limit=1000, offset=0) -> dict:
    """Long-form canonical facts, filtered + paged. Read-only, no derived
    surprises — the same facts the figures are computed from."""
    rows = frame.facts
    if fy:
        rows = [r for r in rows if r["fy"] == fy]
    if measure:
        rows = [r for r in rows if r["measure"] == measure]
    if bucket:
        rows = [r for r in rows if r["bucket"] == bucket]
    if agency:
        rows = [r for r in rows if agency.lower() in r["agency_name"].lower()]
    if quarter is not None:
        rows = [r for r in rows if r["quarter"] == quarter]
    total = len(rows)
    page = rows[offset:offset + limit]
    return {
        "count": len(page),
        "total": total,
        "offset": offset,
        "limit": limit,
        "facts": page,
    }


def measures(frame) -> dict:
    """Measure groups and the measures within each."""
    groups: dict[str, list[str]] = defaultdict(set)
    for f in frame.facts:
        groups[f["measure_group"]].add(f["measure"])
    return {g: sorted(m) for g, m in sorted(groups.items())}
