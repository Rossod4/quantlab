"""Golden-number parity tests for the ported momentum/value signal math
(CLAUDE.md invariant #4; work packet acceptance criterion 2).

**Choice of parity method** (the work packet offers two: importing the old
repo's modules via a sys.path insertion, or hard-coded golden numbers with
provenance comments): this file uses HARD-CODED GOLDEN NUMBERS, computed by
hand from the same formulas documented in
...\\MomentumValueStrategy\\src\\strategy\\{momentum,value}.py's docstrings
(reproduced in strategies/{momentum,value}.py's own module docstrings). This
is the more robust choice: a sys.path insertion makes this test's pass/fail
depend on the old repo's checkout still existing at a hard-coded relative
path outside this repository (broken by moving/deleting that checkout, or by
running these tests in an environment - e.g. CI - that never had it in the
first place) and can silently import stale bytecode. Hard-coded numbers have
no such external dependency and every one below carries a comment deriving
it, so the "golden" value is exactly as auditable as a diff against the old
repo would be.

Every value here is checked to `abs=1e-10` per the packet's acceptance
criterion 2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.strategies.momentum import compute_momentum_signal
from quantlab.strategies.momentum import select_top_n as momentum_top_n
from quantlab.strategies.value import (
    _PointInTimeFundamentals,
    compute_composite_score,
    compute_value_ratios,
)
from quantlab.strategies.value import (
    select_top_n as value_top_n,
)

TOL = 1e-10

# -- momentum -----------------------------------------------------------
# Golden fixture and expected values reproduced from the old repo's
# tests/test_momentum.py::test_momentum_formula_exact_value: "A" grows 1%
# every month, "B" grows 5% every month, formation_date = index[13],
# lookback_months=12, skip_months=1 -> momentum = growth^(12-1) - 1.


def _month_end_prices(n_months: int = 20) -> pd.DataFrame:
    dates = pd.date_range("2020-01-31", periods=n_months, freq="ME")
    return pd.DataFrame(
        {
            "A": [100 * 1.01**i for i in range(n_months)],
            "B": [100 * 1.05**i for i in range(n_months)],
        },
        index=dates,
    )


def test_momentum_signal_matches_hand_derived_golden_values():
    prices = _month_end_prices()
    formation_date = prices.index[13]

    scores = compute_momentum_signal(prices, formation_date, lookback_months=12, skip_months=1)

    expected_a = 1.01**11 - 1  # Price[t-1]/Price[t-12] - 1 = growth^(12-1) - 1
    expected_b = 1.05**11 - 1
    assert scores["A"] == pytest.approx(expected_a, abs=TOL)
    assert scores["B"] == pytest.approx(expected_b, abs=TOL)


def test_momentum_top_n_selection_order_matches_old_repo():
    # Golden from the old repo's test_select_top_n_ranks_descending.
    scores = pd.Series({"A": 0.1, "B": 0.5, "C": 0.3})
    assert momentum_top_n(scores, 2) == ["B", "C"]


# -- value ----------------------------------------------------------------
# Golden fixture reproduced from the old repo's
# tests/test_value.py::test_compute_value_ratios_basic_arithmetic:
# market cap = shares_outstanding * price; pb = market_cap / equity;
# pe = price / ttm_eps.


def _fundamentals(**overrides) -> _PointInTimeFundamentals:
    base = {
        "shares_outstanding": 1000.0,
        "stockholders_equity": 5000.0,
        "ttm_eps": 2.0,
        "ttm_ebitda": 1000.0,
        "total_debt": 500.0,
        "cash": 200.0,
        "annual_eps_growth": 0.10,
    }
    base.update(overrides)
    return _PointInTimeFundamentals(**base)


def test_compute_value_ratios_basic_arithmetic_matches_old_repo():
    fundamentals = {
        "A": _fundamentals(shares_outstanding=100.0, stockholders_equity=1000.0, ttm_eps=5.0)
    }
    ratios = compute_value_ratios(fundamentals, {"A": 20.0})

    # market cap = 100 * 20 = 2000
    assert ratios.loc["A", "pb"] == pytest.approx(2000.0 / 1000.0, abs=TOL)
    assert ratios.loc["A", "pe"] == pytest.approx(20.0 / 5.0, abs=TOL)


def test_growth_adjusted_value_least_attractive_when_growth_negative_matches_old_repo():
    fundamentals = {"A": _fundamentals(ttm_eps=5.0, annual_eps_growth=-0.10)}
    ratios = compute_value_ratios(fundamentals, {"A": 20.0})
    assert ratios.loc["A", "growth_adjusted_value"] == float("inf")


# Hand-derived composite-score golden (see module docstring's derivation in
# the review notes / plans/state/M03/HANDOFF.md): 4 tickers, only "pb" and
# "pe" populated (ev_ebitda/growth_adjusted_value NaN for all -> exactly
# MIN_AVAILABLE_METRICS=2 available per ticker, so every ticker gets a
# determinate composite). "D" is a loss-maker (negative on both metrics).
#
#   pb: A=1, B=2, C=3, D=-5(->+inf)   ascending order A<B<C<D -> pct ranks
#       A=0.25, B=0.50, C=0.75, D=1.00
#   pe: A=2, B=1, C=4, D=-3(->+inf)   ascending order B<A<C<D -> pct ranks
#       B=0.25, A=0.50, C=0.75, D=1.00
#   composite = mean(pb_rank, pe_rank):
#       A=(0.25+0.50)/2=0.375  B=(0.50+0.25)/2=0.375  C=0.75  D=1.00
#
# A and B tie for cheapest (both loss-free, symmetric ratios); D (the
# loss-maker) is forced to the single worst score on both legs, pinning the
# "negative ratios rank worst, not artificially cheap" rule numerically.


def _composite_golden_ratios() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "pb": {"A": 1.0, "B": 2.0, "C": 3.0, "D": -5.0},
            "pe": {"A": 2.0, "B": 1.0, "C": 4.0, "D": -3.0},
            "ev_ebitda": {"A": np.nan, "B": np.nan, "C": np.nan, "D": np.nan},
            "growth_adjusted_value": {"A": np.nan, "B": np.nan, "C": np.nan, "D": np.nan},
        }
    )


def test_composite_score_matches_hand_derived_golden_values():
    scores = compute_composite_score(_composite_golden_ratios())

    assert scores["A"] == pytest.approx(0.375, abs=TOL)
    assert scores["B"] == pytest.approx(0.375, abs=TOL)
    assert scores["C"] == pytest.approx(0.75, abs=TOL)
    assert scores["D"] == pytest.approx(1.0, abs=TOL)


def test_value_top_n_selection_order_matches_golden_tie_break():
    scores = compute_composite_score(_composite_golden_ratios())
    # A and B tie at 0.375; pandas' stable sort preserves the Series'
    # original (insertion) order among ties, so A (inserted first) comes
    # before B.
    assert value_top_n(scores, 2) == ["A", "B"]
