"""validation/netted_grid.py + the CLI/report-card wiring of the walk-forward
ranking-agreement check (M09 carried item 7): inputs come from real saved
BacktestResult directories, each grid point's provenance is recorded, the
window is the walk-forward OOS window, and any missing/mismatched input
degrades to an explicit "not checked: <reason>"."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import quantlab.cli as cli_module
from quantlab.reporting.context import _ranking_agreement_line
from quantlab.validation.basic import ValidationConfig, WalkForwardAxisConfig
from quantlab.validation.metrics import sharpe_ratio
from quantlab.validation.netted_grid import build_netted_book_grid, parse_grid_spec
from quantlab.validation.registry import TrialsRegistry
from quantlab.validation.report_card import build_report_card
from quantlab.validation.walk_forward import walk_forward_blend
from tests._validation_fixtures import make_backtest_result

N = 84
DATES = pd.date_range("2015-01-31", periods=N, freq="ME")
GRID = [(1.0, 0.0), (0.75, 0.25), (0.5, 0.5), (0.25, 0.75), (0.0, 1.0)]
CHILD_PARAMS = [
    {"strategy": "momentum", "params": {"n_long": 30}},
    {"strategy": "value_composite", "params": {"n_holdings": 30}},
]
FULL_CFG = {
    "execution": "close",
    "cost_model": "flat_bps",
    "one_way_cost_bps": 10.0,
    "borrow_fee_annual_bps": 30.0,
    "delisting_haircut": 0.0,
    "extreme_return_policy": "exclude_legacy",
    "extreme_return_bound": 3.0,
    "corwin_schultz_lookback_days": 60,
}


def _result(returns, strategy_id, *, weights=None, cfg_overrides=None, params=None):
    result = make_backtest_result(
        net_returns=returns,
        strategy_id=strategy_id,
        data_semantics_version="m09",
        start="2015-01-31",
        end=str(DATES[-1].date()),
    )
    result.provenance["backtest_config"].update(FULL_CFG)
    result.provenance["backtest_config"].update(cfg_overrides or {})
    if weights is not None:
        result.provenance["strategy_params"] = {
            "children": [dict(c, weight=w) for c, w in zip(CHILD_PARAMS, weights, strict=True)]
        }
    if params is not None:
        result.provenance["strategy_params"] = params
    return result


@pytest.fixture
def world(tmp_path):
    rng = np.random.default_rng(7)
    mom = pd.Series(rng.normal(0.012, 0.04, N), index=DATES)
    val = pd.Series(rng.normal(0.008, 0.03, N), index=DATES)
    dirs, results = {}, {}

    def put(name, result):
        d = tmp_path / name
        result.save(d)
        dirs[name] = d
        results[name] = result

    put("mom", _result(mom, "momentum-aaaa", params={"n_long": 30}))
    put("val", _result(val, "value_composite-bbbb", params={"n_holdings": 30}))
    for w in (0.75, 0.5, 0.25):
        # a netted book is not exactly the blend of nets: shave a little off
        netted = mom * w + val * (1 - w) + 0.0005
        put(f"b{w}", _result(netted, f"blend-{w}", weights=(w, 1 - w)))
    headline = results["b0.5"]
    wf = walk_forward_blend(
        [mom, val],
        GRID,
        train_years=5,
        test_years=1,
        periods_per_year=12,
        child_labels=("momentum", "value"),
    )
    return {"dirs": dirs, "results": results, "headline": headline, "wf": wf}


def _build(world, specs=None, **overrides):
    d = world["dirs"]
    specs = (
        [((0.75, 0.25), d["b0.75"]), ((0.5, 0.5), d["b0.5"]), ((0.25, 0.75), d["b0.25"])]
        if specs is None
        else specs
    )
    kwargs = {
        "headline": world["headline"],
        "walk_forward": world["wf"],
        "weight_grid": GRID,
        "child_results": [world["results"]["mom"], world["results"]["val"]],
        "child_dirs": [d["mom"], d["val"]],
        "grid_specs": specs,
    }
    kwargs.update(overrides)
    return build_netted_book_grid(**kwargs)


def test_parse_grid_spec():
    assert parse_grid_spec("0.25,0.75=some/dir") == ((0.25, 0.75), Path("some/dir"))
    with pytest.raises(ValueError):
        parse_grid_spec("0.25,0.75")


def test_all_five_points_resolve_with_provenance_on_the_oos_window(world):
    outcome = _build(world)

    assert outcome.reason is None
    assert set(outcome.sharpes) == set(GRID)
    oos = world["wf"].oos_returns.index
    assert outcome.window["start"] == str(oos.min().date())
    assert outcome.window["n_periods"] == len(oos)
    assert outcome.window["periods_per_year"] == 12
    expected = sharpe_ratio(world["results"]["mom"].net_returns.loc[oos], 0.0, 12)
    assert outcome.sharpes[(1.0, 0.0)] == pytest.approx(expected)
    by_weights = {tuple(i["weights"]): i for i in outcome.inputs}
    assert by_weights[(1.0, 0.0)]["source"] == "standalone child run"
    assert by_weights[(1.0, 0.0)]["strategy_id"] == "momentum-aaaa"
    assert by_weights[(0.75, 0.25)]["strategy_id"] == "blend-0.75"
    assert by_weights[(0.75, 0.25)]["run_dir"].endswith("b0.75")


def test_sharpes_equal_the_comparison_convention_when_series_are_the_plain_blend(world):
    """Both conventions use sharpe_ratio on the same index, so a netted series
    identical to the blend of nets reproduces comparison's own Sharpe."""
    rng = np.random.default_rng(7)
    mom = world["results"]["mom"].net_returns
    val = world["results"]["val"].net_returns
    plain = _result(mom * 0.5 + val * 0.5, "blend-plain", weights=(0.5, 0.5))
    plain.save(world["dirs"]["b0.5"])
    del rng
    outcome = _build(world, headline=plain)
    wf_sharpe = world["wf"].comparison.loc["Sharpe Ratio", "Fixed 50% momentum/50% value"]
    assert outcome.sharpes[(0.5, 0.5)] == pytest.approx(wf_sharpe)


def test_no_grid_specs_is_not_checked_with_a_reason(world):
    outcome = _build(world, specs=[])
    assert outcome.sharpes is None
    assert "no --netted-grid-result" in outcome.reason


def test_missing_interior_point_is_refused(world):
    d = world["dirs"]
    outcome = _build(world, specs=[((0.5, 0.5), d["b0.5"])])
    assert outcome.sharpes is None
    assert "[0.75, 0.25]" in outcome.reason


def test_cost_config_mismatch_between_child_and_blend_is_refused(world, tmp_path):
    bad = _result(
        world["results"]["mom"].net_returns,
        "momentum-aaaa",
        cfg_overrides={"one_way_cost_bps": 25.0},
        params={"n_long": 30},
    )
    bad_dir = tmp_path / "bad_mom"
    bad.save(bad_dir)
    outcome = _build(
        world,
        child_results=[bad, world["results"]["val"]],
        child_dirs=[bad_dir, world["dirs"]["val"]],
    )
    assert outcome.sharpes is None
    assert "one_way_cost_bps differs" in outcome.reason


def test_window_mismatch_is_refused(world, tmp_path):
    bad = _result(
        world["results"]["val"].net_returns,
        "value_composite-bbbb",
        cfg_overrides={"start": "2014-01-01"},
        params={"n_holdings": 30},
    )
    bad_dir = tmp_path / "bad_val"
    bad.save(bad_dir)
    outcome = _build(
        world,
        child_results=[world["results"]["mom"], bad],
        child_dirs=[world["dirs"]["mom"], bad_dir],
    )
    assert "start differs" in outcome.reason


def test_interior_run_with_the_wrong_weights_is_refused(world):
    d = world["dirs"]
    # claim b0.5's run is the 25/75 point
    specs = [((0.75, 0.25), d["b0.75"]), ((0.5, 0.5), d["b0.5"]), ((0.25, 0.75), d["b0.5"])]
    outcome = _build(world, specs=specs)
    assert outcome.sharpes is None
    assert "do not match the claimed" in outcome.reason


def test_swapped_child_order_is_refused(world):
    outcome = _build(
        world,
        child_results=[world["results"]["val"], world["results"]["mom"]],
        child_dirs=[world["dirs"]["val"], world["dirs"]["mom"]],
    )
    assert outcome.sharpes is None
    assert "is not the headline blend's child" in outcome.reason


def test_child_param_mismatch_is_refused(world, tmp_path):
    other = _result(world["results"]["mom"].net_returns, "momentum-cccc", params={"n_long": 50})
    other_dir = tmp_path / "mom50"
    other.save(other_dir)
    outcome = _build(
        world,
        child_results=[other, world["results"]["val"]],
        child_dirs=[other_dir, world["dirs"]["val"]],
    )
    assert "n_long" in outcome.reason


def test_unloadable_grid_dir_degrades(world, tmp_path):
    outcome = _build(world, specs=[((0.5, 0.5), tmp_path / "nope")])
    assert outcome.sharpes is None
    assert "could not load" in outcome.reason


def test_series_not_covering_the_oos_window_is_refused(world, tmp_path):
    short = _result(
        world["results"]["b0.75"].net_returns.iloc[:70], "blend-0.75", weights=(0.75, 0.25)
    )
    short_dir = tmp_path / "short"
    short.save(short_dir)
    d = world["dirs"]
    outcome = _build(
        world,
        specs=[((0.75, 0.25), short_dir), ((0.5, 0.5), d["b0.5"]), ((0.25, 0.75), d["b0.25"])],
    )
    assert "do not cover the walk-forward out-of-sample window" in outcome.reason


# --- report card + CLI wiring ----------------------------------------------


def _config():
    return ValidationConfig(
        walk_forward=WalkForwardAxisConfig(
            train_years=5, test_years=1, weight_grid=[list(g) for g in GRID]
        )
    )


def test_cli_helper_returns_real_sharpes_and_detail(world):
    d = world["dirs"]
    specs = [f"0.75,0.25={d['b0.75']}", f"0.5,0.5={d['b0.5']}", f"0.25,0.75={d['b0.25']}"]
    kwargs = cli_module._build_ranking_kwargs(
        world["headline"], world["wf"], [d["mom"], d["val"]], specs, _config()
    )
    assert set(kwargs["netted_book_grid_sharpes"]) == set(GRID)
    assert kwargs["ranking_agreement_detail"]["window"]["kind"].startswith("walk-forward")
    assert len(kwargs["ranking_agreement_detail"]["inputs"]) == 5


def test_cli_helper_degrades_on_a_malformed_spec_instead_of_crashing(world):
    d = world["dirs"]
    kwargs = cli_module._build_ranking_kwargs(
        world["headline"], world["wf"], [d["mom"], d["val"]], ["garbage"], _config()
    )
    assert "could not assemble inputs" in kwargs["ranking_not_checked_reason"]


def test_cli_helper_is_empty_without_a_walk_forward(world):
    assert cli_module._build_ranking_kwargs(world["headline"], None, [], [], _config()) == {}


def test_report_card_records_checked_block_with_window_and_inputs(world, tmp_path):
    d = world["dirs"]
    specs = [f"0.75,0.25={d['b0.75']}", f"0.5,0.5={d['b0.5']}", f"0.25,0.75={d['b0.25']}"]
    kwargs = cli_module._build_ranking_kwargs(
        world["headline"], world["wf"], [d["mom"], d["val"]], specs, _config()
    )
    registry = TrialsRegistry(tmp_path / "reg", repo_root=tmp_path)
    card = build_report_card(
        world["headline"], None, registry, _config(), walk_forward=world["wf"], **kwargs
    )

    block = card.ranking_agreement
    assert block["status"] == "checked"
    assert block["n_points"] == 5
    assert block["window"]["n_periods"] == len(world["wf"].oos_returns)
    assert {tuple(i["weights"]) for i in block["inputs"]} == set(GRID)
    line = _ranking_agreement_line(block)
    assert "Kendall tau=" in line and "walk-forward out-of-sample window" in line
    assert "blend-0.75" in line


def test_report_card_says_not_checked_with_reason(world, tmp_path):
    registry = TrialsRegistry(tmp_path / "reg", repo_root=tmp_path)
    card = build_report_card(
        world["headline"],
        None,
        registry,
        _config(),
        walk_forward=world["wf"],
        ranking_not_checked_reason="no --netted-grid-result supplied",
    )
    assert card.ranking_agreement == {
        "status": "not_checked",
        "reason": "no --netted-grid-result supplied",
    }
    assert any("not checked - no --netted-grid-result supplied" in c for c in card.known_caveats)
    assert _ranking_agreement_line(card.ranking_agreement).startswith(
        "ranking agreement under both cost conventions: not checked - no --netted"
    )
