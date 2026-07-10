"""Interface-conformant `PriceProvider` stub for a future Norgate vendor
integration.

Establishes the drop-in contract: `configs/platform.yaml` can name
`providers.prices: norgate` and `build_provider` will happily construct this
class, but every method raises `NotImplementedError` until a real Norgate
integration is written. This lets the rest of the platform (config loading,
the factory, CLI wiring) be built and tested against the vendor swap today,
without waiting on a real Norgate implementation.
"""

from __future__ import annotations

import pandas as pd

from quantlab.data.interfaces import PriceProvider


class NorgatePriceProvider(PriceProvider):
    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        raise NotImplementedError("NorgatePriceProvider is a drop-in stub; not yet implemented")
