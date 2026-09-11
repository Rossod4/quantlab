"""Tests for strategies/registry.py: registration, YAML round-tripping
(acceptance criterion 6), and the unknown-name error."""

from __future__ import annotations

from pathlib import Path

import pytest

# Importing quantlab.strategies registers every real plugin (momentum,
# value_composite, blend) as a side effect - see its module docstring.
import quantlab.strategies as strategies
from quantlab.core.errors import UnknownStrategyError
from quantlab.strategies.blend import BlendStrategy
from quantlab.strategies.momentum import MomentumStrategy
from quantlab.strategies.value import ValueStrategy

CONFIGS_DIR = Path(__file__).resolve().parents[1] / "configs" / "strategies"


def test_real_plugins_are_registered():
    assert "momentum" in strategies.known_strategy_names()
    assert "value_composite" in strategies.known_strategy_names()
    assert "blend" in strategies.known_strategy_names()


def test_load_strategy_from_dict():
    strat = strategies.load_strategy({"strategy": "momentum", "params": {"n_long": 10}})
    assert isinstance(strat, MomentumStrategy)
    assert strat.params["n_long"] == 10


def test_load_strategy_unknown_name_raises_and_lists_known_names():
    with pytest.raises(UnknownStrategyError) as exc_info:
        strategies.load_strategy({"strategy": "not_a_real_strategy"})
    message = str(exc_info.value)
    assert "not_a_real_strategy" in message
    assert "momentum" in message


@pytest.mark.parametrize(
    "filename,expected_type",
    [
        ("momentum_12_1.yaml", MomentumStrategy),
        ("momentum_ls.yaml", MomentumStrategy),
        ("momentum_130_30.yaml", MomentumStrategy),
        ("value_composite.yaml", ValueStrategy),
        ("blend_50_50.yaml", BlendStrategy),
    ],
)
def test_every_config_yaml_round_trips(filename, expected_type):
    strat = strategies.load_strategy(CONFIGS_DIR / filename)
    assert isinstance(strat, expected_type)
    assert strat.strategy_id  # non-empty, does not raise


def test_momentum_configs_have_distinct_strategy_ids():
    ids = {
        strategies.load_strategy(CONFIGS_DIR / name).strategy_id
        for name in ("momentum_12_1.yaml", "momentum_ls.yaml", "momentum_130_30.yaml")
    }
    assert len(ids) == 3
