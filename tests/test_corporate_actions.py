from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import quantlab.data.corporate_actions as corporate_actions_module
from quantlab.core.types import DelistingReason
from quantlab.data.cache import price_cache_path, write_cache
from quantlab.data.corporate_actions import (
    YFinanceCorporateActionsProvider,
    _actions_cache_path,
    _normalize_actions,
    infer_delisting,
)
from quantlab.data.interfaces import ConstituentsProvider


class _FakeConstituentsProvider(ConstituentsProvider):
    """Point-in-time fake: `membership(asof)` returns the tickers of the
    most recent row with date <= asof, mirroring the production as-of
    lookup's semantics (infer_delisting now consults membership at TWO
    dates - the ticker's last trade date and the requested end)."""

    def __init__(self, rows: dict[str, list[str]]):
        self._table = pd.DataFrame(
            {"tickers": list(rows.values())},
            index=pd.DatetimeIndex(list(rows.keys())),
        ).sort_index()

    def membership(self, asof: object) -> list[str]:
        as_of_date = self._table.index.asof(pd.Timestamp(asof))
        if pd.isna(as_of_date):
            raise ValueError(f"no membership data on or before {asof}")
        return list(self._table.loc[as_of_date, "tickers"])

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        raise NotImplementedError


# -- _normalize_actions -------------------------------------------------------


def test_normalize_actions_keeps_only_nonzero_events():
    raw = pd.DataFrame(
        {"Dividends": [0.0, 0.25, 0.0], "Stock Splits": [0.0, 0.0, 4.0]},
        index=pd.DatetimeIndex(["2020-01-01", "2020-02-01", "2020-03-01"]),
    )
    result = _normalize_actions("AAA", raw)

    assert list(result["action_type"]) == ["dividend", "split"]
    assert result.loc[pd.Timestamp("2020-02-01"), "value"] == pytest.approx(0.25)
    assert result.loc[pd.Timestamp("2020-03-01"), "value"] == pytest.approx(4.0)


def test_normalize_actions_empty_when_no_events():
    raw = pd.DataFrame(
        {"Dividends": [0.0, 0.0], "Stock Splits": [0.0, 0.0]},
        index=pd.DatetimeIndex(["2020-01-01", "2020-02-01"]),
    )
    result = _normalize_actions("AAA", raw)
    assert result.empty
    assert list(result.columns) == ["ticker", "action_type", "value"]


# -- YFinanceCorporateActionsProvider ------------------------------------------


@pytest.fixture
def no_network(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("network download attempted - cache should have been used")

    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fail)


def test_get_actions_served_from_cache_without_network(tmp_path, no_network):
    cached = pd.DataFrame(
        {"ticker": ["AAA", "AAA"], "action_type": ["dividend", "split"], "value": [0.5, 2.0]},
        index=pd.DatetimeIndex(["2020-01-10", "2020-06-01"], name="date"),
    )
    write_cache(cached, _actions_cache_path("AAA", tmp_path))
    provider = YFinanceCorporateActionsProvider(cache_dir=tmp_path)

    result = provider.get_actions("AAA", "2020-01-01", "2020-12-31")

    assert len(result) == 2


def test_get_actions_filters_to_requested_window(tmp_path, no_network):
    cached = pd.DataFrame(
        {"ticker": ["AAA", "AAA"], "action_type": ["dividend", "split"], "value": [0.5, 2.0]},
        index=pd.DatetimeIndex(["2018-01-10", "2020-06-01"], name="date"),
    )
    write_cache(cached, _actions_cache_path("AAA", tmp_path))
    provider = YFinanceCorporateActionsProvider(cache_dir=tmp_path)

    result = provider.get_actions("AAA", "2020-01-01", "2020-12-31")

    assert list(result.index) == [pd.Timestamp("2020-06-01")]


def test_get_actions_fetches_and_caches_on_miss(tmp_path, monkeypatch):
    fetched = pd.DataFrame(
        {"ticker": ["AAA"], "action_type": ["dividend"], "value": [0.3]},
        index=pd.DatetimeIndex(["2020-05-01"], name="date"),
    )

    def _fake_download(ticker: str) -> pd.DataFrame:
        assert ticker == "AAA"
        return fetched

    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fake_download)
    provider = YFinanceCorporateActionsProvider(cache_dir=tmp_path)

    result = provider.get_actions("AAA", "2020-01-01", "2020-12-31")

    assert len(result) == 1
    assert _actions_cache_path("AAA", tmp_path).exists()


def test_get_actions_download_failure_is_not_cached_and_is_retried(tmp_path, monkeypatch):
    """REVIEW.md finding 1 (blocker): a transient download failure must NOT
    be frozen into the cache as "this ticker has no actions, ever" - the
    frozen-truncation hazard from plans/QUANT-NOTES.md's M01 note. A failed
    fetch returns empty WITHOUT writing a cache file, so the next call
    re-attempts the download (and can then succeed and cache normally)."""
    attempts = []

    def _fail_once_then_succeed(ticker: str) -> pd.DataFrame:
        attempts.append(ticker)
        if len(attempts) == 1:
            raise ConnectionError("simulated transient network failure")
        return pd.DataFrame(
            {"ticker": [ticker], "action_type": ["dividend"], "value": [0.3]},
            index=pd.DatetimeIndex(["2020-05-01"], name="date"),
        )

    monkeypatch.setattr(corporate_actions_module, "_download_actions", _fail_once_then_succeed)
    provider = YFinanceCorporateActionsProvider(cache_dir=tmp_path)

    first = provider.get_actions("AAA", "2020-01-01", "2020-12-31")
    assert first.empty  # failure surfaced as empty result...
    assert not _actions_cache_path("AAA", tmp_path).exists()  # ...but NOT cached

    second = provider.get_actions("AAA", "2020-01-01", "2020-12-31")
    assert attempts == ["AAA", "AAA"]  # the second call re-attempted the fetch
    assert len(second) == 1  # and this time succeeded...
    assert _actions_cache_path("AAA", tmp_path).exists()  # ...and cached the real data


def test_get_actions_unexpected_exception_propagates(tmp_path, monkeypatch):
    """Only network-level failures are swallowed; a genuine bug (e.g. a
    yfinance API change breaking parsing) must surface loudly, not
    masquerade as an empty actions history."""

    def _raise_bug(ticker: str) -> pd.DataFrame:
        raise TypeError("simulated yfinance API/parsing bug")

    monkeypatch.setattr(corporate_actions_module, "_download_actions", _raise_bug)
    provider = YFinanceCorporateActionsProvider(cache_dir=tmp_path)

    with pytest.raises(TypeError):
        provider.get_actions("AAA", "2020-01-01", "2020-12-31")


# -- infer_delisting -----------------------------------------------------------


def _write_price_cache(cache_dir: Path, ticker: str, dates: list[str]) -> None:
    df = pd.DataFrame({"Close": [1.0] * len(dates)}, index=pd.DatetimeIndex(dates, name="date"))
    write_cache(df, price_cache_path(ticker, cache_dir))


def test_infer_delisting_matches_acceptance_criterion(tmp_path):
    """Last cached bar 2020-06-12, request through 2020-12-31, ticker was a
    member at its last trade date and LEFT the index by the end date ->
    DelistingEvent with last_trade_date 2020-06-12."""
    _write_price_cache(tmp_path, "GONE", ["2020-01-02", "2020-03-15", "2020-06-12"])
    constituents = _FakeConstituentsProvider(
        {
            "2020-01-01": ["GONE", "OTHER"],  # member at last trade date...
            "2020-07-01": ["OTHER"],  # ...then removed: it LEFT the set
        }
    )

    event = infer_delisting("GONE", tmp_path, constituents, "2020-12-31")

    assert event is not None
    assert event.ticker == "GONE"
    assert event.last_trade_date == pd.Timestamp("2020-06-12")
    assert event.reason == DelistingReason.UNKNOWN


def test_infer_delisting_none_when_still_a_constituent(tmp_path):
    _write_price_cache(tmp_path, "STAYS", ["2020-01-02", "2020-06-12"])
    constituents = _FakeConstituentsProvider({"2020-01-01": ["STAYS"]})

    event = infer_delisting("STAYS", tmp_path, constituents, "2020-12-31")

    assert event is None


def test_infer_delisting_none_when_ticker_was_never_a_member(tmp_path):
    """REVIEW.md finding 3: a ticker that was NEVER a member of the tracked
    index but happens to have a stale price cache must not produce a
    spurious DelistingEvent - "left the constituents set" requires having
    been IN it at the last trade date."""
    _write_price_cache(tmp_path, "OUTSIDER", ["2020-01-02", "2020-06-12"])
    constituents = _FakeConstituentsProvider({"2020-01-01": ["SOMEONE_ELSE"]})

    event = infer_delisting("OUTSIDER", tmp_path, constituents, "2020-12-31")

    assert event is None


def test_infer_delisting_none_when_price_data_covers_end(tmp_path):
    _write_price_cache(tmp_path, "ACTIVE", ["2020-01-02", "2020-12-31"])
    # Left the index, but price data still current through end.
    constituents = _FakeConstituentsProvider({"2020-01-01": ["ACTIVE"], "2020-07-01": []})

    event = infer_delisting("ACTIVE", tmp_path, constituents, "2020-12-31")

    assert event is None


def test_infer_delisting_none_when_no_cached_price_data(tmp_path):
    constituents = _FakeConstituentsProvider({"2020-01-01": []})

    event = infer_delisting("NEVERCACHED", tmp_path, constituents, "2020-12-31")

    assert event is None


def test_infer_delisting_none_when_membership_data_starts_too_late(tmp_path):
    """Membership data that doesn't reach back to the last trade date means
    prior membership can't be established -> no inference (the provider's
    ValueError is treated as "cannot tell", not an error)."""
    _write_price_cache(tmp_path, "GONE", ["2020-01-02", "2020-06-12"])
    constituents = _FakeConstituentsProvider({"2020-09-01": []})  # starts after last trade

    event = infer_delisting("GONE", tmp_path, constituents, "2020-12-31")

    assert event is None
