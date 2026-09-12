"""`render_report`: the public entry point of the reporting package.

Loads a saved `BacktestResult` (`--result`) plus, if present, a saved
`report_card.json` (`--card`, defaulting to `--result`'s own directory - a
report and its validation output are usually written to the same
directory) - or, failing that, a saved `validation_basic.json` alone
(basic-tier validation with no `--full` verdict yet) - builds one context
via `context.build_report_context`, generates every plot via `plots.py`,
and renders both `report.html.j2` (PNGs inlined as base64, fully
self-contained) and `report.md.j2` (PNGs written as sibling `.png` files
next to `report.md`).

Every plot is generated defensively: a plot whose inputs are missing (no
sensitivity grid, no walk-forward, no holdings history, ...) is skipped
(`None`) rather than raising, so one missing optional section never blocks
the rest of the report - consistent with `report_card.py`'s own "a missing
optional input is a documented gap, not a crash" posture.
"""

from __future__ import annotations

import ast
import base64
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from quantlab.backtest.result import BacktestResult
from quantlab.reporting import context as context_module
from quantlab.reporting import plots

_logger = logging.getLogger(__name__)
_TEMPLATES_DIR = Path(__file__).parent / "templates"
_PLOT_NAMES = (
    "equity_curve",
    "drawdown",
    "universe_size",
    "rolling_sharpe",
    "subperiod_bars",
    "sensitivity_heatmap",
    "walk_forward_weights",
    "monte_carlo_fan",
)


def _base_kwargs() -> dict[str, Any]:
    return {
        "loader": FileSystemLoader(str(_TEMPLATES_DIR)),
        "trim_blocks": True,
        "lstrip_blocks": True,
    }


def _html_environment() -> Environment:
    # quant-gate REVIEW.md finding 1 (BLOCKER): autoescape must be ON for
    # report.html.j2. A gate reason can carry ticker symbols sourced from
    # the price cache (capacity.py's `missing_tickers`, via
    # report_card.py's capacity gate reason), and `provenance.strategy_
    # params`/`backtest_config` come from a user-edited YAML file - neither
    # is a platform-internal literal, and with autoescape off a `<`/`&` in
    # either breaks the HTML structure instead of displaying literally.
    # The handful of hand-written carried-note constants that MUST render
    # byte-for-byte identical to the markdown twin are individually wrapped
    # in `markupsafe.Markup(...)` in context.py, so they bypass this default
    # rather than the whole page bypassing it.
    return Environment(autoescape=True, **_base_kwargs())


def _markdown_environment() -> Environment:
    # report.md.j2 has no HTML-injection surface WHEN READ AS PLAIN TEXT
    # (it is never parsed as HTML by this package), so autoescape stays off
    # - an escaped ticker/apostrophe would only make the markdown itself
    # less readable, not unsafe. quant-gate VERDICT.md M07 cycle-1 finding
    # 8: this is a property of THIS contract, not a universal one - if a
    # caller pipes `report.md` through a markdown renderer that permits
    # inline HTML, a hostile string (a ticker, a YAML value) becomes LIVE
    # markup there. `report.html.j2` (escaped) is the safe artifact to
    # share where that risk matters; the markdown twin is safe only when
    # read/diffed as plain text, as the packet's own "diffable in git"
    # goal intends.
    return Environment(autoescape=False, **_base_kwargs())


def _monte_carlo_seed(config: Any) -> int:
    if config is None:
        return 1
    bootstrap = getattr(config, "bootstrap", None)
    if bootstrap is not None:
        return int(getattr(bootstrap, "monte_carlo_seed", 1))
    if isinstance(config, dict):
        return int(config.get("bootstrap", {}).get("monte_carlo_seed", 1))
    return 1


def _synthesize_report_card_from_basic(
    basic: dict[str, Any], result: BacktestResult
) -> dict[str, Any]:
    """Wrap a bare `validation_basic.json` (no `--full` run yet, so no
    verdict/gates/PSR/DSR exist) into the same `ReportCard.to_json()` shape
    `context.build_report_context` expects, with every M06-only field
    honestly absent (`None`/`nan`/empty) rather than fabricated."""
    prov = result.provenance
    # quant-gate VERDICT.md M07 cycle-1 finding 9: `flags[0]` is an arbitrary
    # position, not a stable contract - `validate_basic`'s own
    # `_coverage_and_selection_flag` always emits this sentence (and only
    # this sentence) containing "SEPARATE selection effects"; find it by
    # that content rather than assuming it is first, and leave the line
    # empty (never mislabel a different flag) if it is ever absent.
    flags = basic.get("flags") or []
    untrusted_fraction_line = next((f for f in flags if "SEPARATE selection effects" in f), "")
    return {
        "basic": basic,
        "psr": float("nan"),
        "dsr": float("nan"),
        "min_trl": float("nan"),
        "n_trials": 0,
        "cv": {"fold_sharpes": [], "mean_oof_sharpe": float("nan"), "periods_per_year": 0},
        "rc": None,
        "spa": None,
        "monte_carlo": None,
        "capacity": None,
        "coverage_bound": result.coverage_report.overall_bound,
        "quality_flags_summary": result.quality_flags.to_json(),
        "known_caveats": list(prov.get("known_caveats", [])),
        "gates": [],
        "verdict": None,
        "provenance": {
            "strategy_id": prov.get("strategy_id", "unknown"),
            "data_semantics_version": prov.get("data_semantics_version", "unknown"),
            "quantlab_git_sha": prov.get("quantlab_git_sha", "unknown"),
            "dirty": bool(prov.get("dirty", False)),
            "dirty_source": "provenance" if prov.get("dirty") is not None else "unknown",
            "n_trials": 0,
            "n_trials_raw": 0,
            "dirty_trial_count": 0,
            "rc_trial_count": None,
            "rc_spa_benchmark_source": "n/a (no --full report card was run)",
            "headline_retained_fraction": None,
            "untrusted_fraction_line": untrusted_fraction_line,
            "sharpe_sortino_convention": (
                "Sharpe: pandas ddof=1 (sample std), annualized. Sortino: target return 0, "
                "full-sample N at ddof=0. The two denominators are on different footings."
            ),
        },
    }


def _load_report_card(result: BacktestResult, card_dir: Path) -> dict[str, Any] | None:
    report_card_path = card_dir / "report_card.json"
    if report_card_path.exists():
        return json.loads(report_card_path.read_text(encoding="utf-8"))
    basic_path = card_dir / "validation_basic.json"
    if basic_path.exists():
        basic = json.loads(basic_path.read_text(encoding="utf-8"))
        return _synthesize_report_card_from_basic(basic, result)
    return None


def _portfolio_size_series(result: BacktestResult) -> pd.Series | None:
    if not result.holdings_history:
        return None
    sizes = {
        d: sum(1 for w in tw.weights.values() if w != 0)
        for d, tw in result.holdings_history.items()
    }
    return pd.Series(sizes).sort_index()


def _build_plots(
    result: BacktestResult, report_card: dict[str, Any] | None, config: Any
) -> tuple[dict[str, bytes | None], dict[str, str | None]]:
    """Returns `(plot_bytes, plot_errors)`, both keyed by `_PLOT_NAMES`.
    quant-gate VERDICT.md M07 cycle-1 finding 7: a crashed plot and a
    legitimately-absent one used to be indistinguishable (`None` either
    way, silently swallowed) - every failure here is now LOGGED and its
    message carried in `plot_errors` so the template can render "plot
    unavailable: <reason>" instead of silently omitting the section."""
    out: dict[str, bytes | None] = dict.fromkeys(_PLOT_NAMES)
    errors: dict[str, str | None] = dict.fromkeys(_PLOT_NAMES)

    def _try(name: str, build: Any) -> None:
        try:
            out[name] = build()
        except Exception as exc:  # noqa: BLE001 - a plot must never block the report
            out[name] = None
            errors[name] = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            _logger.warning("report plot %r failed to render: %s", name, exc, exc_info=exc)

    _try(
        "equity_curve",
        lambda: plots.plot_equity_curves(
            result.gross_equity, result.net_equity, result.benchmark_equity
        ),
    )
    _try("drawdown", lambda: plots.plot_drawdown(result.net_equity, title="Drawdown (net)"))

    def _universe_size() -> bytes | None:
        sizes = _portfolio_size_series(result)
        return plots.plot_universe_size(sizes) if sizes is not None else None

    _try("universe_size", _universe_size)

    if report_card is None:
        return out, errors
    basic = report_card["basic"]

    def _rolling_sharpe() -> bytes | None:
        rolling = {
            int(years): pd.DataFrame.from_dict(table, orient="index")
            for years, table in basic["rolling"].items()
        }
        if not any(not t.empty for t in rolling.values()):
            return None
        return plots.plot_rolling_sharpe(rolling)

    _try("rolling_sharpe", _rolling_sharpe)

    def _subperiod_bars() -> bytes | None:
        subperiods = pd.DataFrame.from_dict(basic["subperiods"], orient="index")
        return plots.plot_subperiod_bars(subperiods) if not subperiods.empty else None

    _try("subperiod_bars", _subperiod_bars)

    sensitivity = basic.get("sensitivity")
    if sensitivity is not None:

        def _sensitivity_heatmap() -> bytes:
            surface = pd.Series({ast.literal_eval(k): v for k, v in sensitivity["surface"].items()})
            return plots.plot_sensitivity_heatmap(
                surface, sensitivity["param_axes"], sensitivity["base_point"]
            )

        _try("sensitivity_heatmap", _sensitivity_heatmap)

    walk_forward = basic.get("walk_forward")
    if walk_forward is not None:

        def _walk_forward_weights() -> bytes:
            child_labels = tuple(walk_forward["child_labels"])
            chosen = pd.DataFrame.from_dict(
                walk_forward["chosen_weights"], orient="index", columns=list(child_labels)
            )
            chosen.index = pd.to_datetime(chosen.index)
            chosen = chosen.sort_index()
            return plots.plot_walk_forward_weights(chosen, child_labels)

        _try("walk_forward_weights", _walk_forward_weights)

    monte_carlo = report_card.get("monte_carlo")
    if monte_carlo is not None:

        def _monte_carlo_fan() -> bytes:
            seed = _monte_carlo_seed(config)
            return plots.plot_monte_carlo_fan(
                result.net_returns, monte_carlo["n_paths"], monte_carlo["block_len"], seed
            )

        _try("monte_carlo_fan", _monte_carlo_fan)

    return out, errors


def render_report(
    result_dir: str | Path,
    out_dir: str | Path,
    *,
    card_dir: str | Path | None = None,
    config: Any = None,
    fmt: str = "both",
) -> dict[str, Path]:
    """Render `report.html` and/or `report.md` for the `BacktestResult`
    saved at `result_dir` into `out_dir`. `card_dir` (default: `result_dir`)
    is where `report_card.json`/`validation_basic.json` are looked up.
    `fmt` is one of `"html"`, `"md"`, `"both"`. Returns the paths actually
    written, keyed `"html"`/`"md"`."""
    if fmt not in ("html", "md", "both"):
        raise ValueError(f"fmt must be 'html', 'md' or 'both', got {fmt!r}")

    result = BacktestResult.load(result_dir)
    resolved_card_dir = Path(card_dir) if card_dir is not None else Path(result_dir)
    report_card = _load_report_card(result, resolved_card_dir)

    context = context_module.build_report_context(result, report_card, config)
    plot_bytes, plot_errors = _build_plots(result, report_card, config)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    if fmt in ("html", "both"):
        html_context = dict(context)
        html_context["plots"] = {
            name: (base64.b64encode(png).decode("ascii") if png is not None else None)
            for name, png in plot_bytes.items()
        }
        html_context["plot_errors"] = plot_errors
        html = _html_environment().get_template("report.html.j2").render(**html_context)
        html_path = out / "report.html"
        html_path.write_text(html, encoding="utf-8")
        written["html"] = html_path

    if fmt in ("md", "both"):
        plot_files: dict[str, str | None] = {}
        for name, png in plot_bytes.items():
            if png is None:
                plot_files[name] = None
                continue
            filename = f"{name}.png"
            (out / filename).write_bytes(png)
            plot_files[name] = filename
        md_context = dict(context)
        md_context["plot_files"] = plot_files
        md_context["plot_errors"] = plot_errors
        md = _markdown_environment().get_template("report.md.j2").render(**md_context)
        md_path = out / "report.md"
        md_path.write_text(md, encoding="utf-8")
        written["md"] = md_path

    return written
