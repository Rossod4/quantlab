"""OLS + Newey-West regressions: planted loadings, HAC against a statsmodels
reference (tests/fixtures/hac_reference.json) and an independent loop
implementation, exact alignment drop counts, rolling beta."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantlab.attribution.regression import (
    DEFAULT_HAC_LAGS,
    FF5_MOM_FACTORS,
    LAG_SENSITIVITY,
    align_to_factors,
    hac_covariance,
    ols,
    regression_summary,
    rolling_capm,
    to_month_periods,
)

REFERENCE = json.loads((Path(__file__).parent / "fixtures" / "hac_reference.json").read_text())


def _loop_hac_se(x: np.ndarray, resid: np.ndarray, lags: int) -> np.ndarray:
    """Newey-West written the slow, literal way (scalar loops over t and lag),
    independent of regression.hac_covariance's matrix form."""
    n, k = x.shape
    xtx_inv = np.linalg.inv(x.T @ x)
    s = np.zeros((k, k))
    for t in range(n):
        s += resid[t] ** 2 * np.outer(x[t], x[t])
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        for t in range(lag, n):
            term = (
                resid[t]
                * resid[t - lag]
                * (np.outer(x[t], x[t - lag]) + np.outer(x[t - lag], x[t]))
            )
            s += w * term
    return np.sqrt(np.diag(xtx_inv @ s @ xtx_inv))


def test_default_hac_lag_is_six_months():
    assert DEFAULT_HAC_LAGS == 6


# --- planted loadings ---------------------------------------------------------


def test_planted_loadings_are_recovered_to_1e_10_without_noise():
    rng = np.random.default_rng(7)
    n = 120
    factors = rng.normal(0.0, 0.03, size=(n, 6))
    loadings = np.array([1.2, 0.3, -0.4, 0.15, 0.05, 0.5])
    y = 0.0031 + factors @ loadings

    fit = ols(y, factors, FF5_MOM_FACTORS, hac_lags=DEFAULT_HAC_LAGS)

    assert fit.names == ("alpha", *FF5_MOM_FACTORS)
    np.testing.assert_allclose(fit.coef[1:], loadings, atol=1e-10, rtol=0)
    assert fit.coef[0] == pytest.approx(0.0031, abs=1e-10)
    assert fit.r2 == pytest.approx(1.0, abs=1e-10)
    assert fit.n == n


def test_excess_return_regression_recovers_alpha_and_beta_through_rf():
    """Total returns built as RF + alpha + beta * Mkt-RF: aligning subtracts
    RF, so the regression sees (alpha, beta) exactly."""
    months = pd.period_range("2015-01", periods=60, freq="M")
    rng = np.random.default_rng(3)
    mkt = rng.normal(0.008, 0.04, 60)
    rf = np.full(60, 0.002)
    factors = pd.DataFrame({"Mkt-RF": mkt, "RF": rf}, index=months)
    total = pd.Series(rf + 0.0025 + 1.35 * mkt, index=months.to_timestamp("M"))

    excess, x, _, info = align_to_factors(total, factors, ("Mkt-RF",))
    summary = regression_summary(excess, x)

    assert info.n_used == 60
    assert summary["alpha_monthly"] == pytest.approx(0.0025, abs=1e-12)
    assert summary["loadings"]["Mkt-RF"]["coef"] == pytest.approx(1.35, abs=1e-10)
    assert summary["alpha_annualised_arithmetic"] == pytest.approx(0.0025 * 12, abs=1e-10)
    assert summary["alpha_annualised_geometric"] == pytest.approx(1.0025**12 - 1, abs=1e-10)


# --- HAC ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def reference_problem():
    y = np.array(REFERENCE["y"])
    x = np.array(REFERENCE["x"])
    return y, x


def test_ols_matches_the_statsmodels_reference(reference_problem):
    y, x = reference_problem

    fit = ols(y, x, ("a", "b", "c"), hac_lags=6)

    np.testing.assert_allclose(fit.coef, REFERENCE["coef"], atol=1e-10, rtol=0)
    np.testing.assert_allclose(fit.se_ols, REFERENCE["se_ols"], atol=1e-8, rtol=0)
    assert fit.r2 == pytest.approx(REFERENCE["r2"], abs=1e-10)
    assert fit.adj_r2 == pytest.approx(REFERENCE["adj_r2"], abs=1e-10)


@pytest.mark.parametrize("lags", [0, 4, 6, 12])
def test_hac_standard_errors_match_statsmodels_to_1e_8(reference_problem, lags):
    y, x = reference_problem

    fit = ols(y, x, ("a", "b", "c"), hac_lags=lags)

    np.testing.assert_allclose(fit.se_hac, REFERENCE["hac"][str(lags)], atol=1e-8, rtol=0)


@pytest.mark.parametrize("lags", [0, 3, 6])
def test_hac_matches_an_independent_loop_implementation(reference_problem, lags):
    y, x = reference_problem
    fit = ols(y, x, ("a", "b", "c"), hac_lags=lags)
    design = np.column_stack([np.ones(len(y)), x])

    np.testing.assert_allclose(fit.se_hac, _loop_hac_se(design, fit.resid, lags), atol=1e-12)


def test_hac_with_more_lags_changes_the_answer_when_errors_are_autocorrelated(reference_problem):
    y, x = reference_problem
    se0 = ols(y, x, ("a", "b", "c"), 0).se_hac
    se6 = ols(y, x, ("a", "b", "c"), 6).se_hac

    assert not np.allclose(se0, se6)


def test_hac_covariance_rejects_impossible_lags():
    x = np.column_stack([np.ones(10), np.arange(10.0)])
    resid = np.zeros(10)
    with pytest.raises(ValueError):
        hac_covariance(x, resid, -1)
    with pytest.raises(ValueError):
        hac_covariance(x, resid, 10)


def test_ols_needs_more_observations_than_parameters():
    with pytest.raises(ValueError, match="observations"):
        ols(np.ones(3), np.ones((3, 2)), ("a", "b"), 0)


def test_regression_summary_reports_alpha_t_at_every_sensitivity_lag(reference_problem):
    y, x = reference_problem
    xf = pd.DataFrame(x, columns=["a", "b", "c"])

    summary = regression_summary(pd.Series(y), xf, hac_lags=6)

    assert set(summary["alpha_t_hac_by_lag"]) == {str(k) for k in LAG_SENSITIVITY}
    assert summary["alpha_t_hac_by_lag"]["6"] == pytest.approx(summary["alpha_t_hac"])
    ref_se = REFERENCE["hac"]["6"][0]
    assert summary["alpha_t_hac"] == pytest.approx(REFERENCE["coef"][0] / ref_se, abs=1e-6)
    assert summary["alpha_se_annualised_hac"] == pytest.approx(ref_se * 12, abs=1e-8)
    lo, hi = summary["alpha_ci95_annualised_hac"]
    assert lo < summary["alpha_annualised_arithmetic"] < hi


# --- alignment ----------------------------------------------------------------


def _factor_frame(months: str, periods: int) -> pd.DataFrame:
    idx = pd.period_range(months, periods=periods, freq="M")
    rng = np.random.default_rng(1)
    return pd.DataFrame(
        {"Mkt-RF": rng.normal(0, 0.04, periods), "SMB": rng.normal(0, 0.02, periods), "RF": 0.001},
        index=idx,
    )


def test_alignment_counts_every_dropped_month_exactly():
    # factors cover 2020-03 .. 2020-12 (10 months); 2020-07 has a NaN SMB
    factors = _factor_frame("2020-03", 10)
    factors.loc[pd.Period("2020-07", freq="M"), "SMB"] = np.nan
    # the series covers 2020-01 .. 2021-02 (14 months): Jan, Feb (before the
    # factor data), Jul (NaN factor) and Jan, Feb 2021 (after) cannot be used
    dates = pd.date_range("2020-01-31", periods=14, freq="ME")
    returns = pd.Series(np.linspace(0.01, 0.02, 14), index=dates)

    excess, x, rf, info = align_to_factors(returns, factors, ("Mkt-RF", "SMB"))

    assert info.n_returns == 14
    assert info.n_used == 9 == len(excess) == len(x) == len(rf)
    assert info.n_dropped == 5
    assert info.dropped_months == ("2020-01", "2020-02", "2020-07", "2021-01", "2021-02")
    assert info.first_month == "2020-03" and info.last_month == "2020-12"
    # factor rows the series does not cover at all: none (2020-03..12 all inside it)
    assert info.factor_months_outside_window == 0


def test_alignment_counts_factor_months_outside_the_series_window():
    factors = _factor_frame("2019-01", 24)  # 2019-01 .. 2020-12
    dates = pd.date_range("2020-01-31", periods=6, freq="ME")  # 2020-01 .. 2020-06
    returns = pd.Series(0.01, index=dates)

    _, _, _, info = align_to_factors(returns, factors, ("Mkt-RF",))

    assert info.n_dropped == 0
    assert info.factor_months_outside_window == 18


def test_alignment_subtracts_rf_month_by_month():
    factors = _factor_frame("2020-01", 3)
    factors["RF"] = [0.001, 0.002, 0.003]
    returns = pd.Series([0.01, 0.01, 0.01], index=pd.date_range("2020-01-31", periods=3, freq="ME"))

    excess, _, rf, _ = align_to_factors(returns, factors, ("Mkt-RF",))

    np.testing.assert_allclose(excess.to_numpy(), [0.009, 0.008, 0.007])
    np.testing.assert_allclose(rf.to_numpy(), [0.001, 0.002, 0.003])


def test_returns_labelled_with_the_last_trading_day_map_to_that_month():
    # 2012-03-30 was the last trading day of March 2012 (the 31st was a Saturday)
    series = pd.Series([0.1, 0.2], index=pd.to_datetime(["2012-02-29", "2012-03-30"]))

    monthly = to_month_periods(series)

    assert list(monthly.index) == [pd.Period("2012-02", freq="M"), pd.Period("2012-03", freq="M")]


def test_two_returns_in_one_calendar_month_are_refused():
    series = pd.Series([0.1, 0.2], index=pd.to_datetime(["2012-03-15", "2012-03-30"]))

    with pytest.raises(ValueError, match="same calendar month"):
        to_month_periods(series)


# --- rolling beta ---------------------------------------------------------------


def test_rolling_beta_recovers_a_planted_beta_and_labels_by_window_end():
    months = pd.period_range("2018-01", periods=50, freq="M")
    mkt = pd.Series(np.random.default_rng(5).normal(0.01, 0.04, 50), index=months)
    y = 1.5 * mkt + 0.001

    rolled = rolling_capm(y, mkt, window=36)

    assert len(rolled) == 15
    assert rolled.index[0] == months[35] and rolled.index[-1] == months[-1]
    np.testing.assert_allclose(rolled["beta"], 1.5, atol=1e-10)
    np.testing.assert_allclose(rolled["r2"], 1.0, atol=1e-10)


def test_rolling_beta_with_a_changing_beta_follows_it():
    months = pd.period_range("2018-01", periods=72, freq="M")
    mkt = pd.Series(np.random.default_rng(6).normal(0.01, 0.04, 72), index=months)
    beta = np.where(np.arange(72) < 36, 0.8, 1.6)
    y = pd.Series(beta * mkt.to_numpy(), index=months)

    rolled = rolling_capm(y, mkt, window=36)

    assert rolled["beta"].iloc[0] == pytest.approx(0.8, abs=1e-10)
    assert rolled["beta"].iloc[-1] == pytest.approx(1.6, abs=1e-10)


def test_rolling_beta_on_a_series_shorter_than_the_window_is_empty():
    months = pd.period_range("2018-01", periods=10, freq="M")
    s = pd.Series(np.arange(10.0), index=months)

    assert len(rolling_capm(s, s, window=36)) == 0
