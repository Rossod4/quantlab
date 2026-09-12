"""Stationary bootstrap (Politis & Romano, "The Stationary Bootstrap",
JASA 1994) - shared by `reality_check.py` (White RC / Hansen SPA resampling
under the null) and `monte_carlo.py` (return/drawdown percentiles).

Unlike a FIXED-length block bootstrap, the stationary bootstrap's block
lengths are i.i.d. Geometric(1/`block_len`) - drawing a run of consecutive
observations and continuing it with constant probability `1 - 1/block_len`
each step, restarting at a fresh random (wrap-around) position otherwise.
This keeps the resampled series exactly stationary whenever the original is
(fixed blocks do not have this property at their boundaries), which is what
lets `reality_check.py` treat a bootstrap resample as a valid draw from "the
same data-generating process" rather than an artifact of block placement.
"""

from __future__ import annotations

import numpy as np


def stationary_bootstrap_indices(n: int, block_len: float, rng: np.random.Generator) -> np.ndarray:
    """`n` integer indices (with replacement, wrapping circularly) into a
    length-`n` original series, drawn via the stationary bootstrap: a
    uniformly random start, extended by one position (mod `n`) with
    probability `1 - 1/block_len` each step, else restarted at a fresh
    uniformly random position.

    `block_len=1` makes the continuation probability exactly 0, so every
    "block" is length 1 - i.e. plain i.i.d. resampling with replacement
    (acceptance criterion 5's degenerate case).
    """
    if n <= 0:
        return np.empty(0, dtype=int)
    if block_len < 1:
        raise ValueError(f"block_len must be >= 1, got {block_len}")
    p_continue = 1 - 1 / block_len

    continue_draws = rng.random(n)
    restart_draws = rng.integers(0, n, size=n)

    indices = np.empty(n, dtype=int)
    indices[0] = restart_draws[0]
    for i in range(1, n):
        if continue_draws[i] < p_continue:
            nxt = indices[i - 1] + 1
            indices[i] = 0 if nxt == n else nxt
        else:
            indices[i] = restart_draws[i]
    return indices


def stationary_bootstrap_resample(
    values: np.ndarray, block_len: float, rng: np.random.Generator
) -> np.ndarray:
    """One stationary-bootstrap resample of `values` (same length, drawn
    with replacement per `stationary_bootstrap_indices`)."""
    values = np.asarray(values)
    indices = stationary_bootstrap_indices(len(values), block_len, rng)
    return values[indices]
