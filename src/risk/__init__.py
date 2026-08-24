"""risk — the risk layer: no-leakage features, forecasts, and render helpers.

Features are strict trailing statistics (warmup NaN, no lookahead). Labels
are produced by the fit script from a time-split, never from data the model
saw. See `risk.features` for the feature build.
"""
