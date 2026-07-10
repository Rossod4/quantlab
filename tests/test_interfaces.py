from __future__ import annotations

import pytest

from quantlab.core.config import PlatformConfig, ProvidersConfig
from quantlab.core.errors import ConfigError
from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
    build_provider,
)
from quantlab.data.providers.norgate_prices import NorgatePriceProvider
from quantlab.data.providers.sp500_constituents import SP500CommunityConstituentsProvider
from quantlab.data.providers.yfinance_prices import YFinancePriceProvider


def _config(tmp_path) -> PlatformConfig:
    return PlatformConfig(
        cache_dir=tmp_path / "cache",
        reports_dir=tmp_path / "reports",
        providers=ProvidersConfig(
            prices="yfinance", constituents="sp500_community", fundamentals="edgar"
        ),
    )


def test_build_provider_prices_yfinance(tmp_path):
    provider = build_provider("prices", "yfinance", _config(tmp_path))
    assert isinstance(provider, YFinancePriceProvider)
    assert isinstance(provider, PriceProvider)


def test_build_provider_prices_norgate(tmp_path):
    provider = build_provider("prices", "norgate", _config(tmp_path))
    assert isinstance(provider, NorgatePriceProvider)
    assert isinstance(provider, PriceProvider)


def test_build_provider_constituents_sp500_community(tmp_path):
    provider = build_provider("constituents", "sp500_community", _config(tmp_path))
    assert isinstance(provider, SP500CommunityConstituentsProvider)
    assert isinstance(provider, ConstituentsProvider)


def test_build_provider_unknown_prices_name_raises_config_error_naming_it(tmp_path):
    with pytest.raises(ConfigError, match="bloomberg"):
        build_provider("prices", "bloomberg", _config(tmp_path))


def test_build_provider_unknown_constituents_name_raises_config_error_naming_it(tmp_path):
    with pytest.raises(ConfigError, match="wikipedia"):
        build_provider("constituents", "wikipedia", _config(tmp_path))


def test_build_provider_unknown_kind_raises_config_error_naming_it(tmp_path):
    with pytest.raises(ConfigError, match="fundamentals"):
        build_provider("fundamentals", "edgar", _config(tmp_path))


def test_norgate_stub_conforms_to_price_provider_contract():
    """The drop-in contract: the stub is instantiable and satisfies the
    PriceProvider ABC, but every method raises NotImplementedError."""
    provider = NorgatePriceProvider()
    assert isinstance(provider, PriceProvider)
    with pytest.raises(NotImplementedError):
        provider.get_prices(["AAPL"], "2020-01-01", "2020-12-31")


def test_fundamentals_provider_is_abstract_signature_only():
    with pytest.raises(TypeError):
        FundamentalsProvider()  # type: ignore[abstract]


def test_corporate_actions_provider_is_abstract_signature_only():
    with pytest.raises(TypeError):
        CorporateActionsProvider()  # type: ignore[abstract]


def test_price_provider_is_abstract():
    with pytest.raises(TypeError):
        PriceProvider()  # type: ignore[abstract]


def test_constituents_provider_is_abstract():
    with pytest.raises(TypeError):
        ConstituentsProvider()  # type: ignore[abstract]
