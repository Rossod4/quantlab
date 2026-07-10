# M01 — Data layer I: interfaces, cache, quality, prices + constituents providers

Goal: Establish the provider-agnostic data interfaces and port the proven yfinance
price provider and point-in-time S&P 500 constituents provider (with caching and
quality checks) from the old repo. Providers are dumb and cacheable; they are NEVER
handed to strategies (that is M02's PITDataContext).

## In scope (create these)
- src/quantlab/data/__init__.py, src/quantlab/data/providers/__init__.py
- src/quantlab/data/interfaces.py — ABCs:
  - `PriceProvider.get_prices(tickers: list[str], start, end) -> pd.DataFrame`
    (long or wide panel — pick one, document it; must include adjusted close and raw
    close; index tz-naive midnight timestamps)
  - `ConstituentsProvider.membership(asof) -> list[str]` and
    `.membership_history(start, end) -> pd.DataFrame`
  - `FundamentalsProvider` (signature only, implemented M02):
    `get_pit_fundamentals(ticker, asof) -> dict`
  - `CorporateActionsProvider` (signature only, implemented M02):
    `get_actions(ticker, start, end)`
  - A `build_provider(kind, name, config)` factory reading names from PlatformConfig
    (raise ConfigError for unknown names; register "norgate" as a stub provider class
    that raises NotImplementedError on every method — the drop-in contract).
- src/quantlab/data/cache.py — port parquet cache helpers + per-ticker cache metadata
  (the "known empty range for delisted tickers" logic is the valuable part — keep it).
- src/quantlab/data/quality.py — port outlier flagging (>50% single-day |return|);
  add `QualityGate.scan(panel) -> pd.DataFrame` of flags (ticker, date, reason) so
  backtests can record how many flagged observations they consumed. Per
  plans/QUANT-NOTES.md (M00 gate): also validate OHLC sanity at the ingestion boundary
  (low <= open/close <= high, non-negative volume, non-positive prices) — flag rows,
  raise DataQualityError only on wholly corrupt input.
- src/quantlab/data/providers/yfinance_prices.py — port the old prices module behind
  `PriceProvider`. Network calls only inside the provider; everything testable via the
  cache layer with fixtures.
- src/quantlab/data/providers/sp500_constituents.py — port the old constituents module
  (fja05680 CSV download, ticker normalization dot→hyphen, asof membership with
  no-look-ahead) behind `ConstituentsProvider`.
- src/quantlab/data/providers/norgate_prices.py — interface-conformant stub.
- tests/test_interfaces.py (factory + norgate stub contract), tests/test_cache.py,
  tests/test_quality.py, tests/test_prices_provider.py, tests/test_constituents.py —
  port/adapt the old repo's tests for constituents, prices (cache paths only),
  quality_checks. All offline: commit small fixtures to tests/fixtures/ (a constituents
  CSV slice covering 2015-2024 with a handful of add/remove events, e.g. reconstruct
  from a few rows of the real file; tiny price parquet).
- Network-tier tests marked @pytest.mark.network for one real yfinance download and
  one real constituents CSV download (excluded by default).

## Out of scope
pit.py, fundamentals, survivorship, corporate_actions implementation (M02). No changes
to core/ except adding error types if genuinely needed (justify in handoff).

## Context (read these, nothing else)
- This packet; CLAUDE.md
- Existing quantlab files: src/quantlab/core/{types,config,errors,calendar}.py,
  configs/platform.yaml
- Port sources (read-only, adapt minimally, do NOT improve numerical logic):
  - C:\Users\arwga\Developer\ClaudeProjects\Trading\MomentumValueStrategy\src\data_layer\prices.py
  - C:\Users\arwga\Developer\ClaudeProjects\Trading\MomentumValueStrategy\src\data_layer\constituents.py
  - C:\Users\arwga\Developer\ClaudeProjects\Trading\MomentumValueStrategy\src\data_layer\cache_utils.py
  - C:\Users\arwga\Developer\ClaudeProjects\Trading\MomentumValueStrategy\src\data_layer\quality_checks.py
  - Old tests: ...\MomentumValueStrategy\tests\test_constituents.py, test_prices.py,
    test_quality_checks.py
- NOTE: this environment has pandas 3.x / numpy 2.x; the old repo ran pandas 2.x.
  If ported code needs mechanical API updates (e.g. deprecated kwargs), make the
  minimal change and list each one in the handoff.

## Interfaces to honor
core/types.py models; PlatformConfig provider names (yfinance, sp500_community,
edgar, norgate); errors from core/errors.py (add DataQualityError usage in quality.py).

## Acceptance criteria
1. `uv run pytest` green offline; `uv run ruff check` clean.
2. Constituents parity: membership(asof) on the committed fixture CSV equals the old
   repo's as-of semantics — verified with hand-computed expectations for 3 asof dates
   in the fixture, including one date BETWEEN membership-change rows (must return the
   earlier row's membership — no look-ahead) and one before the first row (must raise
   or return empty per old behavior — match it, document which).
3. Ticker normalization: BRK.B -> BRK-B round-trips as in the old module.
4. Cache: writing then reading a panel round-trips exactly; delisted-ticker metadata
   prevents re-fetch attempts for known-empty ranges (test with a mock fetcher counting
   calls).
5. QualityGate flags a synthetic +60% single-day move and not a +10% one.
6. norgate stub satisfies the PriceProvider contract test (instantiable, methods raise
   NotImplementedError).
7. build_provider("prices", "yfinance", cfg) returns the provider; unknown name raises
   ConfigError naming it.

## Verification commands
- `uv run pytest tests/ -q` → all pass offline
- `uv run ruff check` → clean

## Parity fixtures
Fixture CSV in tests/fixtures/constituents_slice.csv (real rows from the fja05680
format); expectations hand-derived from those rows and asserted literally in tests.
