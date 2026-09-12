"""`build_report_context`: the ONLY place in the reporting package that
formats a number. Turns a `BacktestResult` plus a `ReportCard`-shaped dict
(exactly `ReportCard.to_json()`'s schema - see `validation/report_card.py`,
`validation/basic.py` and each validation submodule's own `to_json()`) into
one flat, pre-formatted context dict that `report.html.j2` and
`report.md.j2` both render without themselves doing any number formatting -
that is what guarantees the two templates stay in numeric lock-step
(acceptance criterion 4).

Number-formatting rules (M06 verdict carried item 6, binding):
  - never `repr` a numpy scalar - every leaf here is a plain Python `str`
    built with an f-string format spec, never `!r` or `str(np.float64(...))`.
  - NaN renders as `"n/a (reason)"`, with the reason taken from whatever the
    gate/flag that produced the NaN already said - never a bare `"nan"`.
  - percentages/ratios use fixed precision (`_pct` = 2dp, `_num` = 2-4dp
    depending on the quantity's usual scale).

`report_card` may be `None` (only `quantlab validate`, without `--full`, was
run - no verdict/gates exist yet) - every section degrades gracefully rather
than crashing, and `header.verdict` reads `"NOT EVALUATED (run 'quantlab
validate --full' for a verdict)"` in that case.
"""

from __future__ import annotations

import ast
import math
from typing import Any

from markupsafe import Markup

from quantlab import __version__
from quantlab.backtest.result import BacktestResult
from quantlab.validation.capacity import (
    OLD_REPO_CAPACITY_RANGE_ASSUMPTION,
    OLD_REPO_CAPACITY_RANGE_USD,
)
from quantlab.validation.reality_check import (
    MEASURED_SIZE_AT_SHIPPED_BLOCK_LEN,
    MEASURED_SIZE_BLOCK_LEN,
    NOMINAL_SIZE_BAR,
)

_ROLLING_TABLE_HEAD_TAIL = 5  # quant-gate VERDICT.md M07 cycle-1 finding 12

# --- literal strings the acceptance criteria require verbatim ---------------
#
# quant-gate REVIEW.md finding 1: these are the ONLY strings in this module
# wrapped in `markupsafe.Markup(...)` - every one is a fixed, hand-written,
# platform-internal literal that never carries external data (a ticker, a
# YAML value, a gate reason built from either) and MUST render
# byte-for-byte identical in the HTML report (which now autoescapes
# everything else by default - see render.py's `_html_environment`) as in
# the markdown twin. Do NOT add a new entry here unless it is equally
# static; anything built with an f-string from `result.provenance`/
# `report_card` stays a PLAIN str so it is escaped like any other
# gate reason or provenance value.

COVERAGE_BOUND_DEFINITION = Markup(
    "worst sampled rebalance-date year, % of point-in-time members with no cached history "
    "or masked before that date; a ceiling on invisibility, not a return impact"
)
SEPARATE_SELECTION_EFFECTS_NOTE = Markup(
    "forced exits, extreme-return exclusions, unscored and dropped tickers are SEPARATE "
    "selection effects from the coverage bound above - they are not additive into one "
    "headline number (carried M04 verdict item 4)."
)
ROLLING_PORTED_CONVENTION_NOTE = Markup(
    "ported convention: each window's first return is omitted from CAGR and hidden from "
    "drawdown (M05 carried item; frozen under CLAUDE.md invariant #4 - see "
    "validation/rolling.py's module docstring)."
)
WALK_FORWARD_NO_EMBARGO_NOTE = Markup(
    "Purged/embargoed CV needs both a purge and an embargo because a contiguous test fold "
    "can sit in the MIDDLE of the series with training data on both sides, so a training "
    "row's own label window can overlap the test fold from either direction; the "
    "walk-forward check needs neither, because its weight choice is made from a STRICTLY "
    "PRIOR training block and applied only to the STRICTLY SUBSEQUENT, not-yet-realized test "
    "block - there is no way for the test block's own returns to leak backward into that "
    "choice."
)
WALK_FORWARD_TRAINING_SHARPES_UNAVAILABLE_NOTE = Markup(
    "per-step training Sharpes are NOT retained on WalkForwardResult, so whether any CHOSEN "
    "step had a NaN training Sharpe (which would lock in the first grid weight regardless of "
    "the others) cannot be verified here - open item, carried to whoever next touches "
    "validation/walk_forward.py; this report does not fabricate the missing figures."
)
EXECUTION_MODE_NOTES = {
    "close": Markup("close = same-session close (the decision date's own close price)."),
    "next_open": Markup(
        "next_open = next session's open; returns are measured open-to-open on an "
        "adjusted basis, one session after the decision date."
    ),
}
# quant-gate VERDICT.md M06 carried item 3 (informational, unchanged since cycle 1):
# neither gate is evidence of quality - say so next to the badges. Both are static
# platform-internal literals (M06 verdict binding text, quoted near-verbatim), same
# Markup treatment as the notes above.
MIN_PSR_INFORMATIONAL_NOTE = Markup(
    "min_psr 0.95 binds only below an annualised Sharpe of about 0.47 on a 12-year "
    "monthly book - neither is evidence of quality."
)
MONTE_CARLO_NULL_INFORMATIONAL_NOTE = Markup(
    "the Monte Carlo drawdown gate sits at the centre of its own statistic's null - "
    "neither is evidence of quality."
)
_GATE_INFORMATIONAL_NOTES = {
    "probabilistic_sharpe_ratio": MIN_PSR_INFORMATIONAL_NOTE,
    "monte_carlo_drawdown": MONTE_CARLO_NULL_INFORMATIONAL_NOTE,
}
# quant-gate VERDICT.md M07 cycle-1 finding 10: the single highest-leverage
# honesty sentence still missing - what the badge actually means, and that it
# is not a claim of edge.
VERDICT_LEGEND = Markup(
    "REJECTED: at least one HARD gate failed. RESEARCH_ONLY: every hard gate passed but "
    "at least one SOFT gate failed. ELIGIBLE_FOR_PAPER: every hard and soft gate passed. "
    "Hard-gate failures cap the verdict at REJECTED; soft-gate failures cap it at "
    "RESEARCH_ONLY; the informational notes beside min_psr and the Monte Carlo drawdown "
    "gate never affect the verdict at all. A verdict is not evidence of edge; it states "
    "which tests the result survived."
)
# quant-gate VERDICT.md M07 cycle-1 finding 4: the unscored-names flag's own
# MEANING changed at the M04b data-semantics boundary (QUANT-NOTES.md, M06
# cycle-3 block) - before it, "unscored" conflated "not selected into the
# book" with "could not be scored" (measured on the real run: 173 dates,
# 467-476 names each against 30 holdings - a selection artefact, not a data
# gap); M04b's `TargetWeights.unscored` made it strategy-self-reported and
# genuinely means "could not be scored" from then on. Which reading applies
# depends on the run's own `data_semantics_version`, so the caveat is built
# per-run, not a single static Markup literal.
_UNSCORED_PRE_M04B_VERSIONS = frozenset({"m00", "m01", "m02", "m02b", "m03", "m03b"})


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


# quant-gate VERDICT.md M07 cycle-1 finding 5: infinity must never render
# bare (`min_track_record_length` returns `inf` when no track-record length
# attains significance at this Sharpe) - a distinct sentence from the NaN
# case, since "unbounded" is a real finding, not a missing value.
_UNBOUNDED = "unbounded (n/a)"


def _num(x: Any, digits: int = 2, reason: str = "not available") -> str:
    v = _f(x)
    if v is None:
        return f"n/a ({reason})"
    if math.isinf(v):
        return _UNBOUNDED
    return f"{v:.{digits}f}"


def _pct(x: Any, digits: int = 2, reason: str = "not available") -> str:
    v = _f(x)
    if v is None:
        return f"n/a ({reason})"
    if math.isinf(v):
        return _UNBOUNDED
    return f"{v * 100:.{digits}f}%"


def _money(x: Any, reason: str = "not available") -> str:
    v = _f(x)
    return f"${v:,.0f}" if v is not None else f"n/a ({reason})"


def _int_or_na(x: Any, reason: str = "not available") -> str:
    if x is None:
        return f"n/a ({reason})"
    try:
        return str(int(x))
    except (TypeError, ValueError):
        return f"n/a ({reason})"


def _measured_size_note(test_name: str, block_len: float) -> str:
    """quant-gate VERDICT.3.md M06 cycle-3 carried item: state the White RC /
    Hansen SPA test's MEASURED size at the shipped block length beside the
    badge, so the `max_rc_pvalue`/`max_spa_pvalue` bar in
    configs/validation.yaml is never read as achieved calibration. Sourced
    from `reality_check.py`'s own documented constant (never recomputed live
    on this run's data), and only attached when this run's own `block_len`
    matches the one the measurement covers."""
    measured = MEASURED_SIZE_AT_SHIPPED_BLOCK_LEN.get(test_name)
    if measured is None or float(block_len) != MEASURED_SIZE_BLOCK_LEN:
        return (
            f"(size calibration not measured at the block_len this run used "
            f"({_num(block_len, digits=1)}) - only measured at the shipped block_len="
            f"{MEASURED_SIZE_BLOCK_LEN:.1f})"
        )
    return (
        f"measured size ≈ {measured:.2f} at the {NOMINAL_SIZE_BAR:.2f} bar "
        f"(block length {MEASURED_SIZE_BLOCK_LEN:.1f}); treat the bar as approximate."
    )


def _gate_by_name(gates: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for g in gates:
        if g["name"] == name:
            return g
    return None


def _format_gate(gate: dict[str, Any]) -> dict[str, str]:
    return {
        "name": gate["name"],
        "kind": gate["kind"],
        "value": _num(gate["value"], digits=4, reason="could not be computed"),
        "threshold": _num(gate["threshold"], digits=4, reason="n/a"),
        "status": "PASS" if gate["passed"] else "FAIL",
        # a PLAIN str - report_card.py builds this from formatted numbers and
        # (for capacity) a list of ticker symbols sourced from the price
        # cache, so it is escaped like any other external-adjacent value,
        # never marked Markup-safe (quant-gate REVIEW.md finding 1).
        "reason": gate["reason"],
        # a static, platform-internal literal (or "") - kept as a SEPARATE
        # field rather than concatenated onto `reason` so the Markup-safe
        # note is never accidentally re-escaped or made to re-escape the
        # plain `reason` string next to it.
        "note": _GATE_INFORMATIONAL_NOTES.get(gate["name"], ""),
    }


# --- section builders ---------------------------------------------------


def _header_section(result: BacktestResult, report_card: dict[str, Any] | None) -> dict[str, Any]:
    prov = result.provenance
    verdict = (
        report_card["verdict"]
        if report_card is not None and report_card.get("verdict")
        else "NOT EVALUATED (run `quantlab validate --full` for a verdict)"
    )
    dirty = bool(prov.get("dirty", False))
    m = report_card["basic"]["metrics"] if report_card is not None else None
    if m is not None:
        summary_line = (
            f"net CAGR {_pct(m['net_cagr'])}, Sharpe {_num(m['net_sharpe'])}, "
            f"max drawdown {_pct(m['net_max_drawdown'])} - verdict {verdict}."
        )
    else:
        summary_line = f"verdict: {verdict}."
    return {
        "verdict": verdict,
        "strategy_id": prov.get("strategy_id", "unknown"),
        "data_semantics_version": prov.get("data_semantics_version", "unknown"),
        "run_date": prov.get("run_timestamp", "unknown"),
        "git_sha": prov.get("quantlab_git_sha", "unknown"),
        "dirty": dirty,
        "dirty_badge": "DIRTY TREE" if dirty else "",
        "quantlab_version": __version__,
        "summary_line": summary_line,
        "verdict_legend": VERDICT_LEGEND,
    }


def _headline_section(result: BacktestResult, report_card: dict[str, Any] | None) -> dict[str, Any]:
    if report_card is None:
        return {"available": False}
    m = report_card["basic"]["metrics"]
    sortino_note = report_card["provenance"]["sharpe_sortino_convention"]
    no_benchmark = math.isnan(m["beta"]) or math.isnan(m["benchmark_sharpe"])
    rows = [
        {"label": "CAGR", "net": _pct(m["net_cagr"]), "gross": _pct(m["gross_cagr"])},
        {"label": "Annualized volatility (net)", "net": _pct(m["net_annualized_vol"])},
        {"label": "Sharpe (net)", "net": _num(m["net_sharpe"])},
        {
            "label": "Sortino (net)",
            "net": _num(m["net_sortino"], reason="no downside observations"),
            "note": sortino_note,
        },
        {"label": "Max drawdown (net)", "net": _pct(m["net_max_drawdown"])},
        {"label": "Calmar (net)", "net": _num(m["net_calmar"])},
        {"label": "Hit rate", "net": _pct(m["hit_rate"])},
        {"label": "Mean turnover", "net": _pct(m["turnover_mean"])},
        {"label": "Cost drag (CAGR impact)", "net": _pct(m["cost_drag_cagr"])},
        {"label": "Benchmark CAGR", "net": _pct(m["benchmark_cagr"])},
        {
            "label": "Benchmark Sharpe",
            "net": _num(m["benchmark_sharpe"], reason="no usable benchmark"),
        },
    ]
    if no_benchmark:
        benchmark_line = "no usable benchmark (beta / information ratio / tracking error undefined)"
    else:
        benchmark_line = (
            f"beta {_num(m['beta'])}  |  information ratio {_num(m['information_ratio'])}  |  "
            f"tracking error {_pct(m['tracking_error'])}  "
            f"(overlap: {m['benchmark_overlap_periods']} periods)"
        )
    return {
        "available": True,
        "rows": rows,
        "benchmark_line": benchmark_line,
        "sortino_note": sortino_note,
    }


def _extreme_return_caveat(qf: dict[str, Any]) -> list[str]:
    caveats = []
    if qf.get("extreme_returns_long"):
        caveats.append(
            f"{qf['extreme_returns_long']} long-book extreme-return exclusion(s) "
            "(CONSERVATIVE: truncates a genuine right tail, understating skew/kurtosis in "
            "this direction)."
        )
    if qf.get("extreme_returns_short"):
        caveats.append(
            f"{qf['extreme_returns_short']} short-book extreme-return exclusion(s) "
            "(ANTI-CONSERVATIVE: hides an adverse move, flattering skew/kurtosis)."
        )
    return caveats


def _unscored_names_caveat(data_semantics_version: str) -> str:
    version = (data_semantics_version or "").lower()
    if version in _UNSCORED_PRE_M04B_VERSIONS:
        return (
            f"this run's data_semantics_version ({data_semantics_version}) predates M04b: "
            "this count conflates names the strategy could not price with names it simply "
            "did not select into the book (measured on a real run: 173 dates, 467-476 "
            "names each against 30 holdings) - read it as a selection artefact, not a "
            "data-quality signal."
        )
    return (
        f"this run's data_semantics_version ({data_semantics_version or 'unknown'}) is at "
        "or after M04b: this count is strategy-self-reported and genuinely means "
        "'could not be scored'."
    )


def _trust_section(result: BacktestResult, report_card: dict[str, Any] | None) -> dict[str, Any]:
    coverage_bound = (
        report_card["coverage_bound"]
        if report_card is not None
        else result.coverage_report.overall_bound
    )
    qf = (
        report_card["quality_flags_summary"]
        if report_card is not None
        else result.quality_flags.to_json()
    )
    untrusted_fraction_line = (
        report_card["provenance"]["untrusted_fraction_line"] if report_card is not None else ""
    )
    known_caveats = list(result.provenance.get("known_caveats", []))
    if report_card is not None:
        known_caveats = list(report_card["known_caveats"])
    return {
        "coverage_bound_pct": _pct(coverage_bound / 100.0, reason="n/a"),
        "coverage_bound_definition": COVERAGE_BOUND_DEFINITION,
        "separate_selection_effects_note": SEPARATE_SELECTION_EFFECTS_NOTE,
        "untrusted_fraction_line": untrusted_fraction_line,
        "forced_exits": qf.get("forced_exits", 0),
        "extreme_returns_long": qf.get("extreme_returns_long", 0),
        "extreme_returns_short": qf.get("extreme_returns_short", 0),
        "extreme_return_caveats": _extreme_return_caveat(qf),
        "unscored_date_count": len(qf.get("unscored_by_date", {})),
        "unscored_names_caveat": _unscored_names_caveat(
            result.provenance.get("data_semantics_version", "")
        ),
        "dropped_ticker_date_count": len(qf.get("dropped_tickers_by_date", {})),
        "degenerate_excluded_book_dates": qf.get("degenerate_excluded_book_dates", {}),
        "known_caveats": known_caveats,
    }


def _gates_section(report_card: dict[str, Any] | None) -> dict[str, Any]:
    if report_card is None:
        return {"available": False, "hard": [], "soft": []}
    gates = report_card["gates"]
    hard = [_format_gate(g) for g in gates if g["kind"] == "hard"]
    soft = [_format_gate(g) for g in gates if g["kind"] == "soft"]

    rc, spa = report_card.get("rc"), report_card.get("spa")
    rc_detail = (
        f"K={rc['n_trials']} realised trials over n_periods={rc['n_periods']} common periods, "
        f"B={rc['b']} bootstrap resamples, block_len={rc['block_len']}."
        if rc is not None
        else "Reality Check did not run - see the reality_check_pvalue gate's own reason."
    )
    if rc is not None:
        rc_detail += " " + _measured_size_note("white_rc", rc["block_len"])
    spa_detail = (
        f"K={spa['n_trials']} realised trials over n_periods={spa['n_periods']} common periods, "
        f"B={spa['b']} bootstrap resamples, block_len={spa['block_len']}."
        if spa is not None
        else "Hansen SPA did not run - see the spa_pvalue gate's own reason."
    )
    if spa is not None:
        spa_detail += " " + _measured_size_note("hansen_spa", spa["block_len"])
    mc = report_card.get("monte_carlo")
    monte_carlo_detail = None
    if mc is not None:
        cagr_pcts = f"{_pct(mc['cagr_p5'])} / {_pct(mc['cagr_p50'])} / {_pct(mc['cagr_p95'])}"
        dd_pcts = (
            f"{_pct(mc['max_drawdown_p5'])} / {_pct(mc['max_drawdown_p50'])} / "
            f"{_pct(mc['max_drawdown_p95'])}"
        )
        sharpe_pcts = (
            f"{_num(mc['sharpe_p5'])} / {_num(mc['sharpe_p50'])} / {_num(mc['sharpe_p95'])}"
        )
        monte_carlo_detail = (
            f"CAGR p5/p50/p95: {cagr_pcts}  |  Max drawdown p5/p50/p95: {dd_pcts}  |  "
            f"Sharpe p5/p50/p95: {sharpe_pcts}  |  observed max drawdown: "
            f"{_pct(mc['observed_max_drawdown'])} ({mc['n_paths']} resamples, "
            f"block_len={mc['block_len']})."
        )
    capacity = report_card.get("capacity")
    capacity_detail = None
    if capacity is not None:
        spread = ", ".join(f"{k}={v:.1f}bps" for k, v in capacity["spread_percentiles"].items())
        ceilings = capacity["capacity_ceilings"]
        old_lo, old_hi = OLD_REPO_CAPACITY_RANGE_USD
        capacity_detail = (
            f"spread percentiles: {spread}  |  AUM ceiling range: "
            f"{_money(min(ceilings.values()))} - {_money(max(ceilings.values()))} "
            f"across {len(ceilings)} liquidity assumption(s), {capacity['n_tickers']} ticker(s). "
            f"For scale only, NOT the output of this run: the old repo capacity "
            f"estimate on real 2012-2026 S&P 500 data was {_money(old_lo)}-{_money(old_hi)} "
            f"AUM, under {OLD_REPO_CAPACITY_RANGE_ASSUMPTION}."
        )
    return {
        "available": True,
        "hard": hard,
        "soft": soft,
        "n_trials": report_card["n_trials"],
        # carried M06 verdict item 7 (regression, quant-gate REVIEW.md finding 3):
        # N deduplicated must print SIDE BY SIDE with the raw record count and
        # the dirty-trial count, not deduplicated N alone.
        "n_trials_raw": report_card["provenance"]["n_trials_raw"],
        "dirty_trial_count": report_card["provenance"]["dirty_trial_count"],
        "psr": _num(report_card["psr"], digits=4),
        "dsr": _num(
            report_card["dsr"], digits=4, reason="registry too thin - fewer than 2 distinct trials"
        ),
        "min_trl": _num(report_card["min_trl"], digits=1),
        "rc_detail": rc_detail,
        "spa_detail": spa_detail,
        "monte_carlo_detail": monte_carlo_detail,
        "capacity_detail": capacity_detail,
        "rc_spa_benchmark_source": report_card["provenance"]["rc_spa_benchmark_source"],
        "headline_retained_fraction": (
            _pct(report_card["provenance"]["headline_retained_fraction"], reason="n/a")
            if report_card["provenance"]["headline_retained_fraction"] is not None
            else "n/a"
        ),
    }


def _rolling_tables(rolling: dict[str, dict[str, dict[str, float]]]) -> list[dict[str, Any]]:
    out = []
    for years, table in sorted(rolling.items(), key=lambda kv: int(kv[0])):
        all_rows = []
        for date in sorted(table):
            row = table[date]
            all_rows.append(
                {
                    "date": date,
                    "cagr": _pct(row.get("CAGR")),
                    "vol": _pct(row.get("Annualized Volatility")),
                    "sharpe": _num(row.get("Sharpe Ratio")),
                    "max_dd": _pct(row.get("Max Drawdown")),
                }
            )
        total = len(all_rows)
        # quant-gate VERDICT.md M07 cycle-1 finding 12 (cosmetic): a 12-year
        # book has ~130 rolling windows - show head/tail with the total
        # count stated, never a silently truncated or unbounded dump.
        truncated = total > 2 * _ROLLING_TABLE_HEAD_TAIL
        if truncated:
            gap = {"date": "...", "cagr": "", "vol": "", "sharpe": "", "max_dd": ""}
            rows = (
                all_rows[:_ROLLING_TABLE_HEAD_TAIL] + [gap] + all_rows[-_ROLLING_TABLE_HEAD_TAIL:]
            )
        else:
            rows = all_rows
        out.append(
            {
                "window_years": years,
                "rows": rows,
                "total_rows": total,
                "truncated": truncated,
                "shown_each_side": _ROLLING_TABLE_HEAD_TAIL,
            }
        )
    return out


def _subperiod_table(subperiods: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows = []
    for name, row in subperiods.items():
        rows.append(
            {
                "name": name,
                "cagr": _pct(row.get("CAGR")),
                "vol": _pct(row.get("Annualized Volatility")),
                "sharpe": _num(row.get("Sharpe Ratio")),
                "max_dd": _pct(row.get("Max Drawdown")),
                "growth": _num(row.get("Growth"), digits=4),
            }
        )
    return rows


def _sensitivity_section(
    sensitivity: dict[str, Any] | None, gates: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if sensitivity is None:
        return None
    no_cliff_gate = _gate_by_name(gates, "no_cliff_score")
    net_sharpe_gate = _gate_by_name(gates, "min_net_sharpe")
    axis_names = list(sensitivity["param_axes"])
    base_point = sensitivity["base_point"]
    base_tuple = tuple(base_point.get(name) for name in axis_names)
    surface_rows = []
    for key, value in sensitivity["surface"].items():
        try:
            point = ast.literal_eval(key)
        except (ValueError, SyntaxError):
            point = (key,)
        # quant-gate VERDICT.md M07 cycle-1 finding 2: the surface must be
        # readable as a TABLE (axis name=value, not a bare tuple), with the
        # base point and any NaN (excluded) cell flagged in text - the
        # sensitivity heatmap PNG is not the only place this exists.
        point_label = ", ".join(
            f"{name}={val}" for name, val in zip(axis_names, point, strict=False)
        )
        surface_rows.append(
            {
                "point_label": point_label,
                "net_sharpe": _num(value, reason="NaN (excluded)"),
                "is_base_point": point == base_tuple,
                "is_nan": value is None or (isinstance(value, float) and math.isnan(value)),
            }
        )
    return {
        "param_axes": sensitivity["param_axes"],
        "base_point": base_point,
        "base_point_label": ", ".join(f"{name}={val}" for name, val in base_point.items()),
        "no_cliff_score": _num(sensitivity["no_cliff_score"], digits=4),
        "neighbourhood_size": sensitivity["neighbourhood_size"],
        "neighbourhood_truncated": sensitivity["neighbourhood_truncated"],
        "nan_points": sensitivity["nan_points"],
        "surface_rows": surface_rows,
        "no_cliff_gate_reason": no_cliff_gate["reason"] if no_cliff_gate else "",
        "min_net_sharpe_gate_reason": net_sharpe_gate["reason"] if net_sharpe_gate else "",
    }


def _transpose_comparison_by_grid_point(
    comparison: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """`WalkForwardResult.comparison` is a DataFrame indexed by METRIC name
    with one column per grid point (`walk_forward.py:200-206` -
    `pd.DataFrame({label: standard_metrics(...), ...})`), so `.to_json()`'s
    `to_dict(orient="index")` emits `{metric_name: {grid_point_label:
    value}}` - quant-gate VERDICT.md M07 cycle-1 finding 1 (BLOCKER): the
    consumer here previously assumed the opposite shape
    (`{grid_point_label: {metric_name: value}}`) and every lookup missed,
    silently rendering every cell `n/a`. Transpose to one row per grid
    point (including the "Walk-Forward" column itself, not only the fixed
    grid points) for the actual table this function builds."""
    by_point: dict[str, dict[str, float]] = {}
    for metric, values_by_point in comparison.items():
        for point, value in values_by_point.items():
            by_point.setdefault(point, {})[metric] = value
    return by_point


def _walk_forward_section(
    walk_forward: dict[str, Any] | None, gates: list[dict[str, Any]]
) -> dict[str, Any] | None:
    if walk_forward is None:
        return None
    stability_gate = _gate_by_name(gates, "walk_forward_stability")
    child_labels = walk_forward["child_labels"]
    chosen_rows = []
    for date in sorted(walk_forward["chosen_weights"]):
        weights = walk_forward["chosen_weights"][date]
        weights_by_child = {
            label: _num(w, digits=2) for label, w in zip(child_labels, weights, strict=True)
        }
        chosen_rows.append(
            {
                "date": date,
                # per-child weight, keyed by label (in `child_labels` order)
                # so both templates can render ONE COLUMN PER CHILD as a
                # real table (quant-gate VERDICT.md M07 cycle-1 finding 2) -
                # the sequence itself, not only a PNG.
                "weights_by_child": weights_by_child,
                # precomputed markdown row - see `chosen_weight_header`'s
                # comment below for why a per-column {% for %} on one
                # template line breaks with `trim_blocks=True`.
                "markdown_line": f"| {date} |"
                + "".join(f" {weights_by_child[label]} |" for label in child_labels),
            }
        )
    comparison_by_point = _transpose_comparison_by_grid_point(walk_forward["comparison"])
    comparison_rows = []
    for label, row in comparison_by_point.items():
        comparison_rows.append(
            {
                "label": str(label),
                "cagr": _pct(row.get("CAGR")),
                "vol": _pct(row.get("Annualized Volatility")),
                "sharpe": _num(row.get("Sharpe Ratio")),
                "max_dd": _pct(row.get("Max Drawdown")),
            }
        )
    # markdown table header/separator, precomputed here rather than built by
    # a per-column {% for %} in report.md.j2: with `trim_blocks=True`, the
    # newline immediately after a block tag is stripped, so a for-loop
    # spanning to end-of-line on the HEADER row eats the line break before
    # the separator row, collapsing both onto one line - reproduced and
    # fixed by moving the column iteration here, into plain strings.
    chosen_weight_header = "| Step date |" + "".join(f" {label} |" for label in child_labels)
    chosen_weight_separator = "|---|" + "---|" * len(child_labels)
    return {
        "child_labels": child_labels,
        "chosen_weight_header": chosen_weight_header,
        "chosen_weight_separator": chosen_weight_separator,
        "chosen_rows": chosen_rows,
        "comparison_rows": comparison_rows,
        "comparison_ported_convention_note": ROLLING_PORTED_CONVENTION_NOTE,
        "no_embargo_note": WALK_FORWARD_NO_EMBARGO_NOTE,
        "ranking_agreement_line": "ranking agreement under both cost conventions: not checked",
        "training_sharpes_note": WALK_FORWARD_TRAINING_SHARPES_UNAVAILABLE_NOTE,
        "stability_reason": stability_gate["reason"] if stability_gate else "",
    }


def _robustness_section(
    result: BacktestResult, report_card: dict[str, Any] | None
) -> dict[str, Any]:
    if report_card is None:
        return {"available": False}
    basic = report_card["basic"]
    # quant-gate VERDICT.md M07 cycle-1 finding 12 (cosmetic): the coverage/
    # selection-effects sentence is `basic.flags[0]` unconditionally
    # (`validation/basic.py`'s own `_quality_flags`) AND already printed
    # verbatim in the trust panel (`trust.untrusted_fraction_line`) - drop
    # the duplicate here rather than print it twice on one page.
    flags = [f for f in basic["flags"] if "SEPARATE selection effects" not in f]
    return {
        "available": True,
        "rolling": _rolling_tables(basic["rolling"]),
        "rolling_ported_convention_note": ROLLING_PORTED_CONVENTION_NOTE,
        "subperiods": _subperiod_table(basic["subperiods"]),
        "sensitivity": _sensitivity_section(basic["sensitivity"], report_card["gates"]),
        "walk_forward": _walk_forward_section(basic["walk_forward"], report_card["gates"]),
        "flags": flags,
    }


_NOT_RECORDED = "not recorded in the backtest_config for this run"


def _execution_section(result: BacktestResult) -> dict[str, Any]:
    bc = result.provenance.get("backtest_config", {})
    strategy_params = result.provenance.get("strategy_params", {})
    execution = bc.get("execution")
    filing_lag = strategy_params.get("filing_lag_sessions")
    if execution is None:
        execution_note = f"execution mode {_NOT_RECORDED}."
    else:
        execution_note = EXECUTION_MODE_NOTES.get(
            execution, f"execution mode {execution!r} - no documented convention on file."
        )
    return {
        "execution_mode": execution or "n/a",
        "execution_note": execution_note,
        "cost_model": bc.get("cost_model") or f"n/a ({_NOT_RECORDED})",
        "one_way_cost_bps": _num(bc.get("one_way_cost_bps"), digits=1, reason=_NOT_RECORDED),
        "borrow_fee_annual_bps": _num(
            bc.get("borrow_fee_annual_bps"), digits=1, reason=_NOT_RECORDED
        ),
        "corwin_schultz_lookback_days": bc.get("corwin_schultz_lookback_days")
        or f"n/a ({_NOT_RECORDED})",
        "delisting_haircut": _pct(bc.get("delisting_haircut"), reason=_NOT_RECORDED),
        "extreme_return_policy": bc.get("extreme_return_policy") or f"n/a ({_NOT_RECORDED})",
        "extreme_return_bound": _num(
            bc.get("extreme_return_bound"), digits=2, reason=_NOT_RECORDED
        ),
        "filing_lag_sessions": (
            str(filing_lag)
            if filing_lag is not None
            else "n/a (strategy has no filing-lag parameter)"
        ),
        "max_dropped_fraction": _pct(bc.get("max_dropped_fraction"), reason=_NOT_RECORDED),
        "abort_on_unscoreable": bc.get("abort_on_unscoreable")
        if bc.get("abort_on_unscoreable") is not None
        else f"n/a ({_NOT_RECORDED})",
    }


def _provenance_section(result: BacktestResult) -> dict[str, Any]:
    prov = result.provenance
    bc = dict(prov.get("backtest_config", {}))
    fetched_at = prov.get("actions_cache_fetched_at", {})
    return {
        "strategy_id": prov.get("strategy_id", "unknown"),
        "strategy_params": prov.get("strategy_params", {}),
        "backtest_config": bc,
        "providers": prov.get("providers", {}),
        "actions_cache_fetched_at_min": fetched_at.get("min") or "n/a",
        "actions_cache_fetched_at_max": fetched_at.get("max") or "n/a",
        "cache_dir": prov.get("cache_dir", "n/a (not recorded in this run's provenance)"),
        "run_seconds": _num(prov.get("run_seconds"), digits=2, reason="not recorded"),
        "quantlab_version": __version__,
        "quarantined_count": prov.get("quarantined_count", 0),
        "masked_start_count": prov.get("masked_start_count", 0),
    }


def build_report_context(
    result: BacktestResult,
    report_card: dict[str, Any] | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the complete, pre-formatted report context. `report_card` is
    `ReportCard.to_json()`'s exact dict shape (or `None` for a basic-only
    validation with no verdict); `config` is currently unused by number
    formatting (every threshold already lives inside each gate's own
    `value`/`threshold`) and accepted for the packet's own signature and for
    future sections that need a config value no gate carries."""
    del config  # not currently needed - see docstring.
    gates = report_card["gates"] if report_card is not None else []
    return {
        "header": _header_section(result, report_card),
        "headline": _headline_section(result, report_card),
        "trust": _trust_section(result, report_card),
        "gates": _gates_section(report_card),
        "robustness": _robustness_section(result, report_card),
        "execution": _execution_section(result),
        "provenance": _provenance_section(result),
        "_gates_raw": gates,
    }
