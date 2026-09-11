"""Transaction cost model.

`apply_transaction_costs` is a VERBATIM port of
...\\MomentumValueStrategy\\src\\costs\\transaction_costs.py's function of the
same name (frozen numerics - CLAUDE.md invariant #4). `compute_turnover`
below is NOT a verbatim port: the old repo's version was a SET-based formula
over equal-weight ticker lists (`1 - |old ∩ new| / top_n`), which only makes
sense when every holding has the same weight. M04's engine works with
arbitrary `TargetWeights` (long-only, long-short, 130/30, blended), so
turnover is generalized to the standard weight-vector definition:

    turnover = 0.5 * sum(|w_new[t] - w_old[t]| for t in old | new)

`test_costs.py::test_turnover_generalisation_matches_old_formula_on_equal_weights`
proves this reduces EXACTLY to the old formula whenever `old`/`new` are both
equal-weight sets of the SAME size (the case every existing config exercises
before names are added/dropped, and the case
`tests/parity/test_engine_parity.py` relies on for 1e-10 parity) - see that
test's docstring for the algebra. `old`/`new` here are two CONSECUTIVE
rebalances' TARGET weights (not weights drifted by interim price movement -
see engine.py's module docstring, "Turnover convention" section, for why:
the old engine's reference turnover is itself undrifted, and exact parity
requires matching it, not a more realistic drift-aware figure).

`transaction_cost_fraction` generalizes `apply_transaction_costs` to a
per-ticker cost rate (needed for the optional `corwin_schultz` cost model,
where each name has its own estimated one-way spread) while proving
identical to `apply_transaction_costs`'s scalar-bps subtraction when given a
uniform bps rate (see test_costs.py's flat-bps equivalence test) -
`engine.py` uses `transaction_cost_fraction` uniformly for both cost models
rather than branching between two subtly-different formulas.

`corwin_schultz_spread` is a verbatim port of
...\\MomentumValueStrategy\\scripts\\cost_realism_analysis.py's function of the
same name (median Corwin-Schultz high/low spread estimator). `monthly_borrow_fee`
is a verbatim port of
...\\MomentumValueStrategy\\src\\backtest\\long_short_engine.py's function of the
same name; `borrow_fee_for_period` generalizes it to non-monthly rebalance
frequencies (weekly/daily), reducing to `monthly_borrow_fee` exactly at
`periods_per_year=12` (proven in test_costs.py).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MONTHS_PER_YEAR = 12


def compute_turnover(old_weights: dict[str, float], new_weights: dict[str, float]) -> float:
    """Fraction of the book that had to change hands, generalized to
    arbitrary weight vectors - see module docstring. 0.0 when `old_weights
    == new_weights`; 0.5 * (gross of old + gross of new) when they share no
    tickers at all (e.g. a full turnover into a brand-new book).

    Two special cases mirror the old repo's function EXACTLY (needed for
    1e-10 engine parity, since these are not "the same-size nonempty
    weight-vector" case the general formula reduces to the old one on -
    see this module's docstring): `old_weights` empty (the very first
    rebalance of a run - old repo's `compute_turnover([], new, top_n)`
    hardcodes 1.0 regardless of size) returns 1.0 rather than the general
    formula's 0.5*gross(new); `new_weights` empty (old repo's
    `top_n == len(new_portfolio) == 0` branch) returns 0.0 rather than the
    general formula's 0.5*gross(old).
    """
    if not old_weights and new_weights:
        return 1.0
    if not new_weights:
        return 0.0
    tickers = set(old_weights) | set(new_weights)
    return 0.5 * sum(abs(new_weights.get(t, 0.0) - old_weights.get(t, 0.0)) for t in tickers)


def apply_transaction_costs(gross_return: float, turnover: float, one_way_cost_bps: float) -> float:
    """VERBATIM port (frozen numerics) - see module docstring.

    Replacing a holding is TWO trades (sell the outgoing name, buy the
    incoming one), each paying the one-way cost, so the round-trip charge on
    `turnover` (the fraction of the book replaced) is `2 * turnover *
    one_way_cost_bps / 10_000`.
    """
    cost = 2 * turnover * (one_way_cost_bps / 10_000)
    return gross_return - cost


def weight_deltas(old_weights: dict[str, float], new_weights: dict[str, float]) -> dict[str, float]:
    """Per-ticker signed weight change `new - old` over the union of both
    weight vectors' tickers."""
    tickers = set(old_weights) | set(new_weights)
    return {t: new_weights.get(t, 0.0) - old_weights.get(t, 0.0) for t in tickers}


def transaction_cost_fraction(
    old_weights: dict[str, float],
    new_weights: dict[str, float],
    one_way_cost_bps: float | dict[str, float],
) -> float:
    """Total round-trip transaction cost as a fraction of portfolio equity.

    `one_way_cost_bps` is either a single flat rate applied to every name,
    or a per-ticker dict (the `corwin_schultz` cost model - a ticker absent
    from the dict is treated as 0bps, which only matters for a ticker with a
    zero weight delta anyway). Cost = sum over tickers of
    `|delta| * one_way_cost_bps / 10_000` - for a flat scalar rate this is
    algebraically identical to `apply_transaction_costs`'s
    `2 * turnover * bps / 10_000` (since `turnover = 0.5 * sum(|delta|)`),
    proven in test_costs.py, EXCEPT for `compute_turnover`'s two special
    cases (empty `old_weights`/`new_weights` - see its docstring), which
    this function mirrors directly rather than going through
    `weight_deltas` (a raw delta-sum would silently disagree with
    `compute_turnover`'s hardcoded 1.0/0.0 in exactly those cases, breaking
    the identity this docstring claims and, on the very first rebalance of
    a run, 1e-10 engine parity with the old repo).
    """
    if not new_weights:
        return 0.0
    if not old_weights:
        if isinstance(one_way_cost_bps, dict):
            return 2 * sum(
                abs(w) * one_way_cost_bps.get(t, 0.0) / 10_000 for t, w in new_weights.items()
            )
        return 2 * sum(abs(w) for w in new_weights.values()) * (one_way_cost_bps / 10_000)

    deltas = weight_deltas(old_weights, new_weights)
    if isinstance(one_way_cost_bps, dict):
        return sum(abs(d) * one_way_cost_bps.get(t, 0.0) / 10_000 for t, d in deltas.items())
    return sum(abs(d) for d in deltas.values()) * (one_way_cost_bps / 10_000)


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> float:
    """VERBATIM port (frozen numerics) of
    ...\\MomentumValueStrategy\\scripts\\cost_realism_analysis.py's function of
    the same name.

    Median Corwin-Schultz estimated full spread, as a fraction of price.
    `beta` = sum of squared log(high/low) over two consecutive days; `gamma`
    = squared log of the two-day high over the two-day low. Solving the
    model for the spread gives `alpha` below; negative alphas (where the
    model breaks) are floored at zero, the standard treatment. The MEDIAN
    across days is reported - the estimator is noisy day to day, and the
    median resists its extreme tails. Returns `nan` if fewer than 2 valid
    rows are available.
    """
    h, low_arr = high.to_numpy(dtype=float), low.to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.log(h / low_arr) ** 2
        beta = hl[:-1] + hl[1:]
        h2 = np.maximum(h[:-1], h[1:])
        l2 = np.minimum(low_arr[:-1], low_arr[1:])
        gamma = np.log(h2 / l2) ** 2
    k = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    alpha = np.where(alpha < 0, 0, alpha)
    s = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    s = s[np.isfinite(s)]
    return float(np.median(s)) if len(s) else float("nan")


def monthly_borrow_fee(short_exposure: float, borrow_fee_annual_bps: float) -> float:
    """VERBATIM port (frozen numerics) of
    ...\\MomentumValueStrategy\\src\\backtest\\long_short_engine.py's function
    of the same name: one month's stock-borrow carrying cost on the short
    book, as a fraction of portfolio capital."""
    return short_exposure * borrow_fee_annual_bps / MONTHS_PER_YEAR / 10_000


def borrow_fee_for_period(
    short_exposure: float, borrow_fee_annual_bps: float, periods_per_year: float
) -> float:
    """Generalization of `monthly_borrow_fee` to any rebalance frequency -
    reduces to it exactly at `periods_per_year=12` (month_end rebalancing).
    Used by engine.py so weekly/daily-rebalanced long-short books still pay
    a correctly-scaled carrying cost per period rather than a flat monthly
    figure regardless of period length."""
    return short_exposure * borrow_fee_annual_bps / periods_per_year / 10_000
