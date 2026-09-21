"""Tests for the M09 per-component TTM EPS share-terms restatement in
`PITDataContext.fundamentals()` (data/pit.py) and
`data/providers/edgar_fundamentals.py`'s `_ttm_duration_components` -
closing plans/QUANT-NOTES.md's "From M03b verdict" item 1 (the TTM EPS
mixed-share-terms residual).

The gate's canonical straddling-split fixture: four standalone TTM EPS
quarters, the first two filed BEFORE a 4:1 split and the last two filed
AFTER it. The pre-M09 single-factor restatement (keyed to the LATEST
component's filed date) finds no split in its own (latest_filed, asof]
window and reports the unrestated raw sum, 10.0; the correct, per-component
restatement is 4.0 (see this module's own constants for the derivation).
"""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import pytest

from quantlab.data.interfaces import (
    ConstituentsProvider,
    CorporateActionsProvider,
    FundamentalsProvider,
    PriceProvider,
)
from quantlab.data.pit import PITDataContext
from quantlab.data.providers.edgar_fundamentals import get_point_in_time_fundamentals
from quantlab.data.requirements import DataRequirements

# -- the gate's straddling-split fixture -------------------------------------
#
# Two quarters (q1, q2) filed BEFORE the split, each reporting EPS in the
# OLD (pre-split) share terms - "large" per-share numbers, since dividing
# the same earnings over fewer shares. Two quarters (q3, q4) filed AFTER the
# split, already reporting EPS in the NEW (post-split) share terms - the
# split lowered per-share earnings by the same ratio it raised share count.
# raw_sum = 4+4+1+1 = 10.0 (what the OLD single-factor code reports:
# the window (latest_filed=FILED_Q4, asof] contains no further split, so its
# factor is 1.0 and it sums the raw, un-restated values as filed).
# restated_sum = 4/4 + 4/4 + 1 + 1 = 4.0 (correct: q1/q2 divided by the
# split ratio to bring them into asof's post-split share terms; q3/q4
# already there).
FILED_Q1 = pd.Timestamp("2020-01-15")
FILED_Q2 = pd.Timestamp("2020-04-15")
SPLIT_DATE = pd.Timestamp("2020-05-01")  # strictly between Q2 and Q3 filings
FILED_Q3 = pd.Timestamp("2020-07-15")
FILED_Q4 = pd.Timestamp("2020-10-15")
ASOF = pd.Timestamp("2021-01-15")
SPLIT_RATIO = 4.0

Q1_VAL, Q2_VAL, Q3_VAL, Q4_VAL = 4.0, 4.0, 1.0, 1.0
RAW_SUM = Q1_VAL + Q2_VAL + Q3_VAL + Q4_VAL  # 10.0
CORRECT_RESTATED_SUM = Q1_VAL / SPLIT_RATIO + Q2_VAL / SPLIT_RATIO + Q3_VAL + Q4_VAL  # 4.0


class _FakePriceProvider(PriceProvider):
    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        empty = pd.DataFrame(columns=["ticker", "open", "high", "low", "close", "volume"])
        empty.index = pd.DatetimeIndex([], name="date")
        return empty


class _FakeConstituentsProvider(ConstituentsProvider):
    def membership(self, asof: object) -> list[str]:
        return ["AAA"]

    def membership_history(self, start: object, end: object) -> pd.DataFrame:
        raise NotImplementedError


class _FactsBackedFundamentalsProvider(FundamentalsProvider):
    """Wraps the real (ported-frozen-plus-M09-additive) extraction logic
    directly - same pattern as tests/test_share_terms.py."""

    def __init__(self, facts: pd.DataFrame):
        self._facts = facts

    def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
        return asdict(get_point_in_time_fundamentals(self._facts, asof))


class _FixedActionsProvider(CorporateActionsProvider):
    def __init__(self, actions: pd.DataFrame | None):
        self._actions = actions

    def get_actions(self, ticker: str, start: object, end: object) -> pd.DataFrame:
        if self._actions is None:
            df = pd.DataFrame(columns=["ticker", "action_type", "value"])
            df.index = pd.DatetimeIndex([], name="date")
            return df
        return self._actions[self._actions["ticker"] == ticker].copy()


def _quarter_row(start: str, end: str, filed: pd.Timestamp, val: float) -> dict:
    return {
        "tag": "EarningsPerShareDiluted",
        "start": pd.Timestamp(start),
        "end": pd.Timestamp(end),
        "filed": filed,
        "val": val,
    }


def _straddling_split_facts() -> pd.DataFrame:
    rows = [
        _quarter_row("2019-01-01", "2019-03-31", FILED_Q1, Q1_VAL),
        _quarter_row("2019-04-01", "2019-06-30", FILED_Q2, Q2_VAL),
        _quarter_row("2019-07-01", "2019-09-30", FILED_Q3, Q3_VAL),
        _quarter_row("2019-10-01", "2019-12-31", FILED_Q4, Q4_VAL),
    ]
    return pd.DataFrame(rows)


def _split(ex_date: pd.Timestamp, ratio: float = SPLIT_RATIO) -> pd.DataFrame:
    return pd.DataFrame(
        {"ticker": ["AAA"], "action_type": ["split"], "value": [ratio]},
        index=pd.DatetimeIndex([ex_date], name="date"),
    )


def _context(actions: pd.DataFrame | None, facts: pd.DataFrame) -> PITDataContext:
    return PITDataContext(
        asof=ASOF,
        requirements=DataRequirements(
            price_lookback_days=1, fundamental_fields=frozenset({"ttm_eps"})
        ),
        price_provider=_FakePriceProvider(),
        constituents_provider=_FakeConstituentsProvider(),
        fundamentals_provider=_FactsBackedFundamentalsProvider(facts),
        corporate_actions_provider=_FixedActionsProvider(actions),
    )


def test_straddling_split_gives_the_correct_per_component_restatement():
    """The gate's canonical fixture: TTM EPS 4.0, not the pre-M09 10.0."""
    ctx = _context(_split(SPLIT_DATE), _straddling_split_facts())

    raw = ctx.fundamentals("AAA")

    assert raw["ttm_eps"] == pytest.approx(CORRECT_RESTATED_SUM, abs=1e-9)
    assert raw["ttm_eps"] == pytest.approx(4.0, abs=1e-9)
    # Sanity check against the pre-M09 (buggy) single-factor result: the old
    # code's window is (latest_filed=FILED_Q4, asof], which contains no
    # split at all here, so it reports the raw, un-restated sum unchanged.
    assert RAW_SUM == pytest.approx(10.0)
    assert raw["ttm_eps"] != pytest.approx(RAW_SUM)


def test_straddling_split_effective_split_factor_is_the_raw_over_restated_ratio():
    ctx = _context(_split(SPLIT_DATE), _straddling_split_facts())

    raw = ctx.fundamentals("AAA")

    assert raw["ttm_eps_split_factor"] == pytest.approx(RAW_SUM / CORRECT_RESTATED_SUM, abs=1e-9)
    assert raw["ttm_eps_split_factor"] == pytest.approx(2.5, abs=1e-9)


def test_no_split_leaves_the_per_component_sum_unrestated():
    """Frozen numerics when no split: every component's factor is 1.0, so
    the per-component sum equals the plain raw sum, exactly as the
    single-component (pre-M09) path already guaranteed."""
    ctx = _context(actions=None, facts=_straddling_split_facts())

    raw = ctx.fundamentals("AAA")

    assert raw["ttm_eps"] == pytest.approx(RAW_SUM, abs=1e-9)
    assert raw["ttm_eps_split_factor"] == pytest.approx(1.0, abs=1e-9)


def test_single_filed_date_matches_the_pre_m09_single_factor_result():
    """When every component shares ONE filed date (the common case, and
    every pre-M09 fixture), per-component restatement is algebraically
    identical to the old single-factor approach - not merely coincidentally
    close."""
    same_filed = pd.Timestamp("2020-01-15")
    rows = [
        _quarter_row("2019-01-01", "2019-03-31", same_filed, 2.0),
        _quarter_row("2019-04-01", "2019-06-30", same_filed, 2.0),
        _quarter_row("2019-07-01", "2019-09-30", same_filed, 2.0),
        _quarter_row("2019-10-01", "2019-12-31", same_filed, 2.0),
    ]
    facts = pd.DataFrame(rows)
    split_after_filing = pd.Timestamp("2020-06-01")
    ctx = _context(_split(split_after_filing), facts)

    raw = ctx.fundamentals("AAA")

    assert raw["ttm_eps"] == pytest.approx(8.0 / SPLIT_RATIO, abs=1e-9)
    assert raw["ttm_eps_split_factor"] == pytest.approx(SPLIT_RATIO, abs=1e-9)


def test_provider_without_components_falls_back_to_single_factor_path():
    """A `FundamentalsProvider` that supplies `ttm_eps_filed` but no
    `ttm_eps_components` (e.g. a hand-written test double) must still work,
    via the pre-M09 single-filed-date restatement."""

    class _LegacyFundamentalsProvider(FundamentalsProvider):
        def get_pit_fundamentals(self, ticker: str, asof: object) -> dict:
            return {
                "shares_outstanding": None,
                "stockholders_equity": None,
                "ttm_eps": 8.0,
                "ttm_ebitda": None,
                "total_debt": 0.0,
                "cash": None,
                "annual_eps_growth": None,
                "shares_outstanding_filed": None,
                "ttm_eps_filed": FILED_Q1,
                "ttm_eps_components": None,
            }

    ctx = PITDataContext(
        asof=ASOF,
        requirements=DataRequirements(
            price_lookback_days=1, fundamental_fields=frozenset({"ttm_eps"})
        ),
        price_provider=_FakePriceProvider(),
        constituents_provider=_FakeConstituentsProvider(),
        fundamentals_provider=_LegacyFundamentalsProvider(),
        corporate_actions_provider=_FixedActionsProvider(_split(SPLIT_DATE)),
    )

    raw = ctx.fundamentals("AAA")

    assert raw["ttm_eps"] == pytest.approx(8.0 / SPLIT_RATIO, abs=1e-9)
    assert raw["ttm_eps_split_factor"] == pytest.approx(SPLIT_RATIO, abs=1e-9)
