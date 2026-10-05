"""Active-return decomposition identity, the beta-matched benchmark line, and
the concentration measures."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantlab.attribution.decompose import (
    annualised_geometric,
    decompose_active_return,
    effective_holdings,
    idiosyncratic_concentration,
)


def _series(n: int = 120, seed: int = 11):
    idx = pd.period_range("2014-01", periods=n, freq="M")
    rng = np.random.default_rng(seed)
    rf = pd.Series(rng.uniform(0.0, 0.003, n), index=idx)
    bench = pd.Series(rng.normal(0.01, 0.04, n), index=idx)
    strat = pd.Series(rf + 0.0015 + 1.25 * (bench - rf) + rng.normal(0.0, 0.02, n), index=idx)
    return strat, bench, rf


def test_the_three_components_sum_to_the_geometric_excess_return():
    strat, bench, rf = _series()

    d = decompose_active_return(strat, bench, rf, hac_lags=6)

    c = d["components"]
    total = c["leverage_on_beta"] + c["alpha"] + c["compounding"]
    assert total == pytest.approx(d["excess_cagr_aligned"], abs=1e-12)
    assert d["excess_cagr_aligned"] == pytest.approx(
        annualised_geometric(strat) - annualised_geometric(bench), abs=1e-14
    )
    assert abs(d["identity_gap"]) < 1e-12


def test_leverage_plus_alpha_is_exactly_the_arithmetic_active_return():
    """The OLS-with-intercept identity the decomposition rests on."""
    strat, bench, rf = _series(seed=21)

    d = decompose_active_return(strat, bench, rf, hac_lags=6)

    c = d["components"]
    arithmetic_active = 12 * (strat.mean() - bench.mean())
    assert c["leverage_on_beta"] + c["alpha"] == pytest.approx(arithmetic_active, abs=1e-12)


def test_compounding_term_is_the_geometric_minus_arithmetic_differential():
    strat, bench, rf = _series(seed=31)

    d = decompose_active_return(strat, bench, rf, hac_lags=6)

    expected = (annualised_geometric(strat) - 12 * strat.mean()) - (
        annualised_geometric(bench) - 12 * bench.mean()
    )
    assert d["components"]["compounding"] == pytest.approx(expected, abs=1e-14)


def test_planted_beta_and_alpha_are_recovered_and_split_correctly():
    idx = pd.period_range("2015-01", periods=96, freq="M")
    rng = np.random.default_rng(2)
    rf = pd.Series(0.001, index=idx)
    bench = pd.Series(rng.normal(0.012, 0.04, 96), index=idx)
    strat = rf + 0.002 + 1.3 * (bench - rf)  # exact line, no noise

    d = decompose_active_return(strat, bench, rf, hac_lags=6)

    assert d["beta_vs_benchmark"] == pytest.approx(1.3, abs=1e-10)
    assert d["components"]["alpha"] == pytest.approx(0.002 * 12, abs=1e-10)
    premium = 12 * (bench - rf).mean()
    assert d["benchmark_premium_annualised"] == pytest.approx(premium, abs=1e-12)
    assert d["components"]["leverage_on_beta"] == pytest.approx(0.3 * premium, abs=1e-10)


def test_a_series_against_itself_has_beta_one_and_nothing_to_decompose():
    _, bench, rf = _series()

    d = decompose_active_return(bench, bench, rf, hac_lags=6)

    assert d["beta_vs_benchmark"] == pytest.approx(1.0, abs=1e-12)
    for value in d["components"].values():
        assert value == pytest.approx(0.0, abs=1e-12)


def test_beta_matched_benchmark_has_the_benchmarks_own_sharpe():
    strat, bench, rf = _series(seed=41)

    m = decompose_active_return(strat, bench, rf, hac_lags=6)["beta_matched_benchmark"]

    assert m["sharpe_excess_rf_levered"] == pytest.approx(
        m["sharpe_excess_rf_benchmark"], abs=1e-12
    )
    assert m["sharpe_excess_rf_strategy"] != pytest.approx(m["sharpe_excess_rf_benchmark"])


def test_beta_matched_cagr_is_the_levered_series_compounded_and_the_gap_is_stated():
    strat, bench, rf = _series(seed=51)

    d = decompose_active_return(strat, bench, rf, hac_lags=6)

    levered = rf + d["beta_vs_benchmark"] * (bench - rf)
    m = d["beta_matched_benchmark"]
    assert m["cagr_aligned"] == pytest.approx(annualised_geometric(levered), abs=1e-14)
    assert m["strategy_minus_levered_cagr"] == pytest.approx(
        annualised_geometric(strat) - annualised_geometric(levered), abs=1e-14
    )


def test_appraisal_ratio_is_alpha_over_idiosyncratic_volatility():
    strat, bench, rf = _series(seed=61)

    d = decompose_active_return(strat, bench, rf, hac_lags=6)

    xs, xb = strat - rf, bench - rf
    slope = np.cov(xs, xb, ddof=1)[0, 1] / xb.var(ddof=1)
    resid = xs - (xs.mean() - slope * xb.mean()) - slope * xb
    vol = resid.std(ddof=1) * np.sqrt(12)
    bm = d["beta_matched_benchmark"]
    assert bm["idiosyncratic_volatility_annualised"] == pytest.approx(vol, abs=1e-12)
    assert bm["appraisal_ratio"] == pytest.approx(d["components"]["alpha"] / vol, abs=1e-12)


def test_mismatched_indexes_are_refused():
    strat, bench, rf = _series()

    with pytest.raises(ValueError, match="share one index"):
        decompose_active_return(strat.iloc[1:], bench, rf, hac_lags=6)


# --- concentration -------------------------------------------------------------


def test_idiosyncratic_share_is_one_minus_r_squared():
    strat, bench, rf = _series(seed=71)
    ys, xs = strat - rf, bench - rf

    out = idiosyncratic_concentration(ys, xs, window=36)

    r2 = np.corrcoef(ys, xs)[0, 1] ** 2
    assert out["full_sample_share"] == pytest.approx(1 - r2, abs=1e-12)
    assert 0 < out["rolling"]["mean_share"] < 1
    assert out["rolling"]["worst_share"] >= out["rolling"]["mean_share"]
    assert out["rolling"]["n_windows"] == len(ys) - 36 + 1


def test_a_single_huge_residual_month_is_flagged_as_the_largest():
    idx = pd.period_range("2014-01", periods=80, freq="M")
    rng = np.random.default_rng(81)
    mkt = pd.Series(rng.normal(0.01, 0.04, 80), index=idx)
    y = 1.1 * mkt + pd.Series(rng.normal(0, 0.002, 80), index=idx)
    y.iloc[50] += 0.15

    out = idiosyncratic_concentration(y, mkt)["largest_residual_month"]

    assert out["month"] == str(idx[50])
    assert out["share_of_squared_residuals"] > 0.9
    assert out["residual"] > 0.1


def test_short_series_has_no_rolling_block():
    idx = pd.period_range("2014-01", periods=20, freq="M")
    rng = np.random.default_rng(91)
    mkt = pd.Series(rng.normal(0, 0.04, 20), index=idx)
    y = mkt + pd.Series(rng.normal(0, 0.01, 20), index=idx)

    assert idiosyncratic_concentration(y, mkt)["rolling"] is None


def test_effective_holdings_of_equal_weights_is_the_count():
    holdings = {
        "2020-01-31": dict.fromkeys(range(30), 1 / 30),
        "2020-02-29": dict.fromkeys(range(10), 0.1),
    }

    out = effective_holdings({d: {str(k): v for k, v in w.items()} for d, w in holdings.items()})

    assert out["n_dates"] == 2
    assert out["effective_n_max"] == pytest.approx(30.0)
    assert out["effective_n_min"] == pytest.approx(10.0)
    assert out["effective_n_mean"] == pytest.approx(20.0)
    assert out["positions_mean"] == pytest.approx(20.0)


def test_effective_holdings_of_a_concentrated_book_is_small():
    out = effective_holdings({"d": {"A": 0.9, "B": 0.05, "C": 0.05}})

    assert out["effective_n_mean"] == pytest.approx(1 / (0.81 + 0.0025 + 0.0025))


def test_effective_holdings_normalises_to_gross_exposure_and_skips_empty_dates():
    out = effective_holdings(
        {
            "2020-01-31": {"A": 0.25, "B": 0.25},  # half in cash: still 2 effective names
            "2020-02-29": {},  # nothing held
            "2020-03-31": {"A": 0.5, "B": -0.5},  # long/short: gross-normalised
        }
    )

    assert out["n_dates"] == 2 and out["n_empty_dates"] == 1
    assert out["effective_n_mean"] == pytest.approx(2.0)


def test_effective_holdings_with_no_positions_at_all():
    assert effective_holdings({"d": {}}) == {"n_dates": 0, "n_empty_dates": 1}
