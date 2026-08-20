"""stats — the enum-constrained stat catalog + DSL ops.

The never-invent-a-number contract: the model may only cite keys in
stats.catalog.FIG_KEYS / STAT_KEYS, and every figure is computed from the
canonical facts in the Frame. The DSL (stats.dsl) is the only read path the
agent drives.
"""
