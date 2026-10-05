"""Assemble one run's attribution (`attribution.json` + `attribution.md`).

Reads ONLY files the run already wrote (`net_returns`, `benchmark_returns`,
the two equity curves, `provenance.json`, and `holdings_history.json` when it
is present - it is git-ignored). Writes nothing but the two attribution files
into the directory it is told to. Never runs a backtest.

`series="benchmark"` runs the identical machinery on the run's embedded
benchmark (SPY) series as a calibration of the pipeline: against `Mkt-RF` its
beta should be ~1 and its alpha ~0; whatever gap there is gets reported, with
its mechanical causes (SPY is the S&P 500, the library's market is the CRSP
value-weighted universe; SPY nets a ~0.09% expense ratio).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quantlab.attribution import decompose as dec
from quantlab.attribution import regression as reg
from quantlab.attribution.factors import FactorData
from quantlab.validation.metrics import MONTHS_PER_YEAR, cagr, information_ratio, sharpe_ratio

SCHEMA_VERSION = 1
ATTRIBUTION_JSON = "attribution.json"
ATTRIBUTION_MD = "attribution.md"

SECTOR_NOTE = (
    "not available: the constituents provider carries no point-in-time-safe sector mapping, "
    "and none was added for this milestone."
)


class AttributionError(RuntimeError):
    """The run directory cannot be attributed (missing provenance, wrong
    periodicity, series not covered by the factor data)."""


def _read_series(run_dir: Path, name: str) -> pd.Series:
    path = run_dir / f"{name}.parquet"
    if not path.exists():
        raise AttributionError(f"{path} is missing")
    frame = pd.read_parquet(path)
    return frame["value"].astype(float)


def _load_inputs(run_dir: Path) -> dict[str, Any]:
    prov_path = run_dir / "provenance.json"
    if not prov_path.exists():
        raise AttributionError(
            f"{prov_path} is missing: refusing to attribute a run directory without provenance"
        )
    provenance = json.loads(prov_path.read_text(encoding="utf-8"))
    freq = provenance.get("backtest_config", {}).get("rebalance_freq")
    if freq != "month_end":
        raise AttributionError(
            f"rebalance_freq is {freq!r}; the factor data are monthly, only 'month_end' runs "
            "can be attributed"
        )
    holdings_path = run_dir / "holdings_history.json"
    holdings = None
    if holdings_path.exists():
        raw = json.loads(holdings_path.read_text(encoding="utf-8"))
        holdings = {d: v["weights"] for d, v in raw.items()}
    return {
        "provenance": provenance,
        "net_returns": _read_series(run_dir, "net_returns"),
        "benchmark_returns": _read_series(run_dir, "benchmark_returns"),
        "net_equity": _read_series(run_dir, "net_equity"),
        "benchmark_equity": _read_series(run_dir, "benchmark_equity"),
        "holdings": holdings,
    }


def build_attribution(
    run_dir: str | Path,
    factors: FactorData,
    *,
    series: str = "strategy",
    hac_lags: int = reg.DEFAULT_HAC_LAGS,
) -> dict[str, Any]:
    """The attribution dict for `run_dir` (JSON-ready). `series` is
    `"strategy"` or `"benchmark"` (the calibration, see module docstring)."""
    if series not in ("strategy", "benchmark"):
        raise ValueError(f"series must be 'strategy' or 'benchmark', got {series!r}")
    run_dir = Path(run_dir)
    inputs = _load_inputs(run_dir)
    is_strategy = series == "strategy"
    returns = inputs["net_returns"] if is_strategy else inputs["benchmark_returns"]
    equity = inputs["net_equity"] if is_strategy else inputs["benchmark_equity"]

    excess, x, rf, info = reg.align_to_factors(returns, factors.frame, reg.FF5_MOM_FACTORS)
    if info.n_used < reg.ROLLING_WINDOW + 12:
        raise AttributionError(
            f"only {info.n_used} months overlap the factor data (dropped: {info.dropped_months})"
        )
    months = excess.index
    monthly_returns = reg.to_month_periods(returns).loc[months]

    out: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run": run_dir.name,
        "series": "strategy net returns" if is_strategy else "embedded benchmark (SPY) returns",
        "strategy_id": inputs["provenance"].get("strategy_id") if is_strategy else None,
        "benchmark": "SPY",
        "convention": (
            "Monthly decimal returns. Regressions use returns in EXCESS of the factor library's "
            "RF. Sharpe figures labelled excess_rf use that RF; the platform's own Sharpe "
            "(rf=0) is quoted separately as sharpe_platform_rf0."
        ),
        "sample": {
            "first_month": info.first_month,
            "last_month": info.last_month,
            "n_returns": info.n_returns,
            "n_used": info.n_used,
            "n_dropped_by_alignment": info.n_dropped,
            "dropped_months": list(info.dropped_months),
            "factor_months_outside_window": info.factor_months_outside_window,
        },
        "factor_vintage": factors.vintage,
        "hac": {
            "kernel": "Bartlett (Newey-West), no small-sample correction",
            "lags": hac_lags,
            "rule": (
                "fixed 6 months for monthly data (half a year); the Newey-West plug-in "
                f"floor(4*(T/100)^(2/9)) would give {int(4 * (info.n_used / 100) ** (2 / 9))} "
                "here. Six is a defensible robustness choice against longer-memory autocorrelation "
                "(more lags is not uniformly more conservative: it can raise a t-stat); see "
                "each regression's alpha_t_hac_by_lag."
            ),
            "p_values": "two-sided, normal distribution",
        },
        "sharpe_platform_rf0": float(sharpe_ratio(monthly_returns, 0.0, MONTHS_PER_YEAR)),
        "sharpe_excess_rf": float(sharpe_ratio(excess, 0.0, MONTHS_PER_YEAR)),
        "capm": reg.regression_summary(excess, x[list(reg.CAPM_FACTORS)], hac_lags),
        "ff5_mom": reg.regression_summary(excess, x, hac_lags),
    }

    rolled = reg.rolling_capm(excess, x["Mkt-RF"])
    out["rolling_beta_36m"] = {
        "window_months": reg.ROLLING_WINDOW,
        "mean": float(rolled["beta"].mean()),
        "min": float(rolled["beta"].min()),
        "min_window_ends": str(rolled["beta"].idxmin()),
        "max": float(rolled["beta"].max()),
        "max_window_ends": str(rolled["beta"].idxmax()),
        "last": float(rolled["beta"].iloc[-1]),
        "series": {str(p): float(b) for p, b in rolled["beta"].items()},
    }

    if is_strategy:
        bench_monthly = reg.to_month_periods(inputs["benchmark_returns"])
        missing = months.difference(bench_monthly.index)
        if len(missing):
            raise AttributionError(f"benchmark has no return for months {list(map(str, missing))}")
        bench = bench_monthly.loc[months]
        decomposition = dec.decompose_active_return(monthly_returns, bench, rf, hac_lags)
        platform_s = float(cagr(equity))
        platform_b = float(cagr(inputs["benchmark_equity"]))
        decomposition["platform_cagr"] = {
            "strategy": platform_s,
            "benchmark": platform_b,
            "excess": platform_s - platform_b,
            "gap_to_aligned_excess": (platform_s - platform_b)
            - decomposition["excess_cagr_aligned"],
            "note": (
                "the platform CAGR is date-based on the equity curve (blind to its first "
                "return); the components above use month counts on the aligned sample"
            ),
        }
        out["decomposition"] = decomposition
        out["information_ratio_vs_spy"] = float(
            information_ratio(inputs["net_returns"], inputs["benchmark_returns"], MONTHS_PER_YEAR)
        )
        out["gate_note"] = (
            "The existing net_sharpe_vs_benchmark gate compares total-risk-adjusted return. SPY "
            "levered to the strategy's beta has SPY's Sharpe exactly, so the gate gives no credit "
            "for beta leverage and charges for idiosyncratic variance (concentration). The "
            "beta-matched comparison belongs in alpha and appraisal-ratio terms (informational "
            "only; no gate is changed)."
        )
        mkt_excess_for_conc = x["Mkt-RF"]
        out["concentration"] = {
            "idiosyncratic_variance": dec.idiosyncratic_concentration(excess, mkt_excess_for_conc),
            "holdings": (
                dec.effective_holdings(inputs["holdings"])
                if inputs["holdings"] is not None
                else "not available: holdings_history.json is not present in the run directory"
            ),
        }
    else:
        mkt_total = x["Mkt-RF"] + rf
        diff = monthly_returns - mkt_total
        out["calibration"] = {
            "mean_diff_vs_library_market_annualised": float(diff.mean() * MONTHS_PER_YEAR),
            "tracking_error_vs_library_market_annualised": float(
                diff.std(ddof=1) * np.sqrt(MONTHS_PER_YEAR)
            ),
            "correlation_with_library_market": float(monthly_returns.corr(mkt_total)),
            "expected_gap_causes": [
                "SPY holds the S&P 500 (large caps); the library's market is the CRSP "
                "value-weighted return of all US listings (and Mkt-RF is that minus RF)",
                "SPY's ~0.09% annual expense ratio is netted out of its return",
                "SPY's return here is the data vendor's adjusted close (dividends reinvested "
                "at the ex-date); the library compounds monthly total returns",
                "RF is the library's 1-month T-bill series (Ibbotson to 2024-05, ICE BofA "
                "thereafter)",
            ],
        }
    out["sector_exposure"] = SECTOR_NOTE
    return out


def _pct(x: float, digits: int = 2) -> str:
    return f"{x * 100:+.{digits}f}%"


def _signif(t: float) -> str:
    if abs(t) >= 2.58:
        return "significant at the 1% level"
    if abs(t) >= 1.96:
        return "significant at the 5% level"
    if abs(t) >= 1.645:
        return "significant at the 10% level only"
    return "NOT distinguishable from zero (|t| < 1.645)"


def _regression_rows(reg_dict: dict[str, Any]) -> list[str]:
    rows = [
        "| term | coefficient | HAC s.e. | t (HAC) |",
        "|---|---|---|---|",
        f"| alpha (monthly) | {reg_dict['alpha_monthly'] * 100:+.4f}% | "
        f"{reg_dict['alpha_se_annualised_hac'] / MONTHS_PER_YEAR * 100:.4f}% | "
        f"{reg_dict['alpha_t_hac']:+.2f} |",
    ]
    for name, row in reg_dict["loadings"].items():
        rows.append(f"| {name} | {row['coef']:+.4f} | {row['se_hac']:.4f} | {row['t_hac']:+.2f} |")
    return rows


def _regression_block(title: str, r: dict[str, Any]) -> list[str]:
    lo, hi = r["alpha_ci95_annualised_hac"]
    by_lag = ", ".join(f"lag {k}: {v:+.2f}" for k, v in r["alpha_t_hac_by_lag"].items())
    return [
        f"### {title}",
        "",
        *_regression_rows(r),
        "",
        f"- Alpha annualised: {_pct(r['alpha_annualised_arithmetic'])} (monthly x12), "
        f"{_pct(r['alpha_annualised_geometric'])} (geometric); 95% interval (HAC) "
        f"{_pct(lo)} to {_pct(hi)}.",
        f"- Alpha t-stat (HAC, {r['hac_lags']} lags) {r['alpha_t_hac']:+.2f}: "
        f"{_signif(r['alpha_t_hac'])}. Plain-OLS t {r['alpha_t_ols']:+.2f}; "
        f"HAC t by lag: {by_lag}.",
        f"- R-squared {r['r2']:.4f} (adjusted {r['adj_r2']:.4f}), N = {r['n']} months.",
        "",
    ]


def render_markdown(att: dict[str, Any]) -> str:
    s = att["sample"]
    v = att["factor_vintage"]
    title = att["strategy_id"] or "SPY calibration"
    lines = [
        f"# Attribution - {att['run']} ({title})",
        "",
        f"Series: {att['series']}. Informational: nothing here changes a gate.",
        "",
        "## Sample and data vintage",
        "",
        f"- Window {s['first_month']} to {s['last_month']}: {s['n_used']} of {s['n_returns']} "
        f"monthly returns used; {s['n_dropped_by_alignment']} dropped by alignment"
        + (f" ({', '.join(s['dropped_months'])})" if s["dropped_months"] else "")
        + f"; {s['factor_months_outside_window']} factor months fall outside the window.",
        f"- Factors: {v['source']}, fetched {v['fetched_at']}; "
        + "; ".join(
            f"{name}: {meta['library_note']} (Last-Modified {meta.get('last_modified')})"
            for name, meta in v["files"].items()
        )
        + ".",
        f"- {att['convention']}",
        f"- Sharpe (rf=0, platform convention) {att['sharpe_platform_rf0']:.3f}; Sharpe on "
        f"excess over the library's RF {att['sharpe_excess_rf']:.3f}.",
        f"- HAC: {att['hac']['kernel']}; {att['hac']['lags']} lags - {att['hac']['rule']} "
        f"P-values: {att['hac']['p_values']}.",
        "",
        "## Regressions",
        "",
        *_regression_block("CAPM: excess return on Mkt-RF", att["capm"]),
        *_regression_block("Fama-French 5 factors + Momentum", att["ff5_mom"]),
    ]
    rb = att["rolling_beta_36m"]
    lines += [
        "## Rolling 36-month CAPM beta",
        "",
        f"Mean {rb['mean']:.3f}; low {rb['min']:.3f} (window ending {rb['min_window_ends']}); "
        f"high {rb['max']:.3f} (window ending {rb['max_window_ends']}); latest {rb['last']:.3f}. "
        "The full series is in attribution.json.",
        "",
    ]
    if "decomposition" in att:
        d = att["decomposition"]
        c = d["components"]
        m = d["beta_matched_benchmark"]
        p = d["platform_cagr"]
        lines += [
            "## Excess return over SPY: where it comes from",
            "",
            f"Beta against SPY excess returns: {d['beta_vs_benchmark']:.3f}. SPY's premium over "
            f"RF in this sample: {_pct(d['benchmark_premium_annualised'])} a year.",
            "",
            "| component | pp / yr |",
            "|---|---|",
            f"| leverage on beta = (beta - 1) x SPY premium | {c['leverage_on_beta'] * 100:+.2f} |",
            f"| alpha vs SPY (regression intercept x 12) | {c['alpha'] * 100:+.2f} |",
            f"| compounding (geometric vs arithmetic annualisation) | "
            f"{c['compounding'] * 100:+.2f} |",
            "| **excess CAGR on the aligned months** | "
            f"**{d['excess_cagr_aligned'] * 100:+.2f}** |",
            "",
            f"Identity gap (excess minus the three components): {d['identity_gap']:.1e}. "
            f"The platform's date-based CAGRs are {_pct(p['strategy'])} vs "
            f"{_pct(p['benchmark'])} ({_pct(p['excess'])} excess; "
            f"{p['gap_to_aligned_excess'] * 100:+.2f} pp from the aligned figure). "
            f"Alpha t-stat vs SPY: {d['alpha_t_hac']:+.2f}.",
            "",
            "### Beta-matched SPY (informational)",
            "",
            f"SPY levered to beta {d['beta_vs_benchmark']:.3f} compounds at "
            f"{_pct(m['cagr_aligned'])}; the strategy at {_pct(d['strategy_cagr_aligned'])} "
            f"({m['strategy_minus_levered_cagr'] * 100:+.2f} pp). Sharpe on excess over RF: "
            f"strategy {m['sharpe_excess_rf_strategy']:.3f}, "
            f"SPY {m['sharpe_excess_rf_benchmark']:.3f}, "
            f"levered SPY {m['sharpe_excess_rf_levered']:.3f} (equal to SPY by construction). "
            f"Appraisal ratio vs SPY (alpha / idiosyncratic volatility "
            f"{m['idiosyncratic_volatility_annualised'] * 100:.2f}%): {m['appraisal_ratio']:+.3f}. "
            "Information ratio vs SPY (platform definition): "
            f"{att['information_ratio_vs_spy']:+.3f}.",
            "",
            att["gate_note"],
            "",
            "## Concentration",
            "",
        ]
        conc = att["concentration"]
        iv = conc["idiosyncratic_variance"]
        lines.append(
            f"- Idiosyncratic share of variance (1 - R-squared of CAPM): "
            f"{iv['full_sample_share']:.3f} over the sample."
        )
        if iv["rolling"]:
            r = iv["rolling"]
            lines.append(
                f"- In trailing {r['window_months']}-month windows: mean {r['mean_share']:.3f}, "
                f"worst {r['worst_share']:.3f} (window ending {r['worst_window_ends']})."
            )
        lm = iv["largest_residual_month"]
        lines.append(
            f"- Largest single idiosyncratic month: {lm['month']} ({_pct(lm['residual'])}), "
            f"{lm['share_of_squared_residuals'] * 100:.1f}% of all squared residuals."
        )
        h = conc["holdings"]
        if isinstance(h, str):
            lines.append(f"- Effective number of holdings: {h}.")
        else:
            lines.append(
                f"- Effective number of holdings (1 / sum w^2): mean {h['effective_n_mean']:.1f}, "
                f"min {h['effective_n_min']:.1f}, max {h['effective_n_max']:.1f} over "
                f"{h['n_dates']} rebalances (mean {h['positions_mean']:.1f} positions)."
            )
        lines.append("")
    else:
        cal = att["calibration"]
        lines += [
            "## Calibration: SPY against the library's market",
            "",
            f"SPY minus the library's total market return: "
            f"{_pct(cal['mean_diff_vs_library_market_annualised'])} a year on average, tracking "
            f"error {cal['tracking_error_vs_library_market_annualised'] * 100:.2f}%, correlation "
            f"{cal['correlation_with_library_market']:.4f}. Expected causes of any gap:",
            "",
            *[f"- {cause}" for cause in cal["expected_gap_causes"]],
            "",
        ]
    lines += ["## Sector exposure", "", f"Sector exposure {att['sector_exposure']}", ""]
    return "\n".join(lines)


def write_attribution(att: dict[str, Any], out_dir: str | Path) -> tuple[Path, Path]:
    """Write `attribution.json` and `attribution.md` (and nothing else) into
    `out_dir`, creating it if needed."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, md_path = out / ATTRIBUTION_JSON, out / ATTRIBUTION_MD
    json_path.write_text(json.dumps(att, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(att), encoding="utf-8")
    return json_path, md_path
