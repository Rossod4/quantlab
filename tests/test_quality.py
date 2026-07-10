from __future__ import annotations

import pandas as pd
import pytest

from quantlab.core.errors import DataQualityError
from quantlab.data.quality import QualityGate


def _panel(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df.set_index("date")
    df.index = pd.to_datetime(df.index)
    return df


def _clean_rows(ticker: str, dates: list[str], closes: list[float]) -> list[dict]:
    return [
        {
            "date": d,
            "ticker": ticker,
            "open": c,
            "high": c * 1.01,
            "low": c * 0.99,
            "close": c,
            "adj_close": c,
            "volume": 1000,
        }
        for d, c in zip(dates, closes, strict=True)
    ]


def test_scan_empty_panel_returns_empty_flags():
    gate = QualityGate()
    columns = ["ticker", "open", "high", "low", "close", "adj_close", "volume"]
    result = gate.scan(pd.DataFrame(columns=columns))
    assert result.empty
    assert list(result.columns) == ["ticker", "date", "reason"]


def test_scan_missing_columns_raises_data_quality_error():
    gate = QualityGate()
    bad = pd.DataFrame({"ticker": ["A"], "close": [1.0]}, index=pd.to_datetime(["2020-01-01"]))
    with pytest.raises(DataQualityError):
        gate.scan(bad)


def test_flags_synthetic_plus_60pct_move_not_plus_10pct():
    dates = pd.date_range("2020-01-01", periods=6, freq="B")
    closes = [100.0, 101.0, 102.0, 101.0, 100.0, 110.0]  # last move is +10%
    rows = _clean_rows("A", [d.strftime("%Y-%m-%d") for d in dates], closes)
    panel = _panel(rows)

    # Inject a +60% single-day move on day index 3.
    panel.loc[panel.index[3], ["open", "high", "low", "close", "adj_close"]] = [
        v * 1.6 for v in [102.0, 102.0 * 1.01, 102.0 * 0.99, 102.0, 102.0]
    ]

    gate = QualityGate(outlier_threshold=0.5)
    flags = gate.scan(panel)

    outlier_flags = flags[flags["reason"].str.startswith("outlier_return")]
    assert len(outlier_flags) >= 1
    # The +10% move at the end must NOT be flagged.
    last_date = panel.index[-1]
    assert not (outlier_flags["date"] == last_date).any()


def test_no_false_positives_on_normal_returns():
    """Regression parity with the old repo: DataFrame.stack() must not
    surface spurious NaN-masked rows as flags."""
    dates = pd.date_range("2020-01-01", periods=10, freq="B")
    closes_a = [100, 101, 99, 100, 102, 101, 103, 104, 102, 105]
    closes_b = [50, 51, 52, 53, 54, 55, 56, 57, 58, 59]
    rows = _clean_rows("A", [d.strftime("%Y-%m-%d") for d in dates], [float(c) for c in closes_a])
    rows += _clean_rows("B", [d.strftime("%Y-%m-%d") for d in dates], [float(c) for c in closes_b])
    panel = _panel(rows)

    gate = QualityGate(outlier_threshold=0.5)
    flags = gate.scan(panel)

    assert flags.empty


def test_ohlc_sanity_flags_low_greater_than_high():
    rows = _clean_rows("A", ["2020-01-01", "2020-01-02"], [100.0, 101.0])
    panel = _panel(rows)
    panel.loc[panel.index[0], "low"] = 200.0  # low > high: invalid

    gate = QualityGate()
    flags = gate.scan(panel)

    ohlc_flags = flags[flags["reason"].str.startswith("ohlc_sanity")]
    assert len(ohlc_flags) == 1
    assert ohlc_flags.iloc[0]["ticker"] == "A"


def test_ohlc_sanity_flags_negative_volume():
    rows = _clean_rows("A", ["2020-01-01", "2020-01-02"], [100.0, 101.0])
    panel = _panel(rows)
    panel.loc[panel.index[0], "volume"] = -5

    gate = QualityGate()
    flags = gate.scan(panel)

    assert any(flags["reason"].str.contains("negative_volume"))


def test_ohlc_sanity_flags_non_positive_price():
    rows = _clean_rows("A", ["2020-01-01", "2020-01-02"], [100.0, 101.0])
    panel = _panel(rows)
    panel.loc[panel.index[0], "close"] = 0.0

    gate = QualityGate()
    flags = gate.scan(panel)

    assert any(flags["reason"].str.contains("non_positive_price"))


def test_duplicate_date_ticker_rows_are_flagged_not_silently_averaged():
    """A duplicate (date, ticker) pair is itself a data-quality bug: it must
    surface as a `duplicate_row` flag, not be silently averaged away (as
    pivot_table's default aggfunc would have done)."""
    rows = _clean_rows("A", ["2020-01-01", "2020-01-02", "2020-01-03"], [100.0, 101.0, 102.0])
    # Inject an exact duplicate of the middle (date, ticker) row.
    rows.append(dict(rows[1]))
    panel = _panel(rows)

    gate = QualityGate()
    flags = gate.scan(panel)

    dup_flags = flags[flags["reason"] == "duplicate_row"]
    assert len(dup_flags) == 1
    assert dup_flags.iloc[0]["ticker"] == "A"
    assert dup_flags.iloc[0]["date"] == pd.Timestamp("2020-01-02")
    # The clean series around the duplicate must not produce outlier flags.
    assert not flags["reason"].str.startswith("outlier_return").any()


def test_wholly_corrupt_panel_raises_data_quality_error():
    """Every row fails OHLC sanity -> raise, rather than flag-and-continue."""
    rows = _clean_rows("A", ["2020-01-01", "2020-01-02", "2020-01-03"], [100.0, 101.0, 102.0])
    panel = _panel(rows)
    panel["low"] = 999999.0  # every row now has low > high

    gate = QualityGate()
    with pytest.raises(DataQualityError):
        gate.scan(panel)
