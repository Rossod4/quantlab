"""Data quality checks for price panels.

Vendor data isn't guaranteed to be clean - bad prints, unadjusted splits,
and other glitches happen. We can't fix bad data, but we CAN flag it
instead of trusting it silently, and record how many flagged observations a
backtest consumed. That turns "trust the vendor blindly" into "trust the
vendor, but flag what looks wrong".

Two independent checks feed `QualityGate.scan`:

1. Outlier returns (ported from the old repo's `quality_checks.py`):
   single-day |adjusted-close return| beyond a threshold (default 50%) is
   far more often a bad print or an unadjusted corporate action slipping
   through than genuine price action, especially for large, liquid names.
2. OHLC sanity (added per plans/QUANT-NOTES.md's M00 gate): low <= open/close
   <= high, non-negative volume, strictly positive prices. Individual bad
   rows are flagged, not dropped; `DataQualityError` is raised only when the
   *entire* input panel fails sanity, since that indicates wholly corrupt
   input (e.g. a malformed vendor response) rather than a handful of bad
   prints worth flagging and moving on from.
"""

from __future__ import annotations

import pandas as pd

from quantlab.core.errors import DataQualityError

REQUIRED_PRICE_COLUMNS = ("ticker", "open", "high", "low", "close", "adj_close", "volume")

_FLAG_COLUMNS = ("ticker", "date", "reason")


class QualityGate:
    """Scans a long-format price panel (see `PriceProvider.get_prices`) for
    suspicious rows and returns a flag report; never mutates or drops rows
    from the input itself."""

    def __init__(self, outlier_threshold: float = 0.5):
        self.outlier_threshold = outlier_threshold

    def scan(self, panel: pd.DataFrame) -> pd.DataFrame:
        """Return a long DataFrame of flags: columns [ticker, date, reason].

        Raises `DataQualityError` if every row in a non-empty panel fails
        the OHLC sanity check (wholly corrupt input) or if the panel is
        missing required columns.
        """
        if panel.empty:
            return pd.DataFrame(columns=list(_FLAG_COLUMNS))

        missing = [c for c in REQUIRED_PRICE_COLUMNS if c not in panel.columns]
        if missing:
            raise DataQualityError(f"price panel missing required columns: {missing}")

        ohlc_flags = self._scan_ohlc_sanity(panel)
        if len(ohlc_flags) == len(panel):
            raise DataQualityError(
                f"all {len(panel)} rows failed OHLC sanity checks - input looks wholly corrupt"
            )

        duplicate_flags, deduped = self._scan_duplicates(panel)
        outlier_flags = self._scan_outliers(deduped)

        flags = pd.concat([ohlc_flags, duplicate_flags, outlier_flags], ignore_index=True)
        if flags.empty:
            return pd.DataFrame(columns=list(_FLAG_COLUMNS))
        return flags.sort_values(["date", "ticker"]).reset_index(drop=True)

    def _scan_duplicates(self, panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Flag duplicate (date, ticker) rows and return (flags, deduped panel).

        A duplicate (date, ticker) pair is itself a data-quality bug in the
        input; silently averaging it away (as `pivot_table`'s default
        aggfunc would) runs against QualityGate's whole purpose. Instead,
        every occurrence after the first is flagged as `duplicate_row`, and
        the outlier scan runs on the first-occurrence-only panel so `pivot`
        (which raises on duplicates, rather than averaging) stays safe.
        """
        pair_key = pd.MultiIndex.from_arrays([panel.index, panel["ticker"]])
        dup_mask = pair_key.duplicated(keep="first")
        if not dup_mask.any():
            return pd.DataFrame(columns=list(_FLAG_COLUMNS)), panel

        flags = pd.DataFrame(
            {
                "ticker": panel.loc[dup_mask, "ticker"].to_numpy(),
                "date": panel.index[dup_mask],
                "reason": "duplicate_row",
            }
        )
        return flags, panel.loc[~dup_mask]

    def _scan_ohlc_sanity(self, panel: pd.DataFrame) -> pd.DataFrame:
        low_le_open = panel["low"] <= panel["open"]
        open_le_high = panel["open"] <= panel["high"]
        low_le_close = panel["low"] <= panel["close"]
        close_le_high = panel["close"] <= panel["high"]
        nonneg_volume = panel["volume"] >= 0
        price_cols = panel[["open", "high", "low", "close", "adj_close"]]
        positive_prices = (price_cols > 0).all(axis=1)

        checks = {
            "low_gt_open": ~low_le_open,
            "open_gt_high": ~open_le_high,
            "low_gt_close": ~low_le_close,
            "close_gt_high": ~close_le_high,
            "negative_volume": ~nonneg_volume,
            "non_positive_price": ~positive_prices,
        }
        invalid = pd.concat(checks.values(), axis=1).any(axis=1)
        if not invalid.any():
            return pd.DataFrame(columns=list(_FLAG_COLUMNS))

        bad_idx = panel.index[invalid]
        bad = panel.loc[invalid]
        reasons = []
        for pos in range(len(bad)):
            row_failed = [name for name, mask in checks.items() if mask.loc[invalid].iloc[pos]]
            reasons.append(",".join(row_failed))

        return pd.DataFrame(
            {
                "ticker": bad["ticker"].to_numpy(),
                "date": bad_idx,
                "reason": [f"ohlc_sanity:{r}" for r in reasons],
            }
        )

    def _scan_outliers(self, panel: pd.DataFrame) -> pd.DataFrame:
        # `panel` has already been deduplicated by _scan_duplicates, so
        # `pivot` cannot hit its duplicate-entries error; it is used instead
        # of `pivot_table` precisely because it raises rather than silently
        # averaging should that invariant ever break.
        # noqa rationale: PD010 prefers pivot_table, but pivot_table's
        # default aggfunc silently AVERAGES duplicates - the exact failure
        # mode this method must not have.
        wide = (
            panel.reset_index(names="date")  # noqa: PD010
            .pivot(index="date", columns="ticker", values="adj_close")
            .sort_index()
        )
        daily_returns = wide.pct_change()
        flagged = daily_returns[daily_returns.abs() > self.outlier_threshold]

        # NOTE: DataFrame.stack() does not drop all-NaN rows by default in
        # this pandas version, so it must be dropped explicitly - otherwise
        # every non-flagged (NaN-masked) cell would show up as a spurious
        # "flagged" row. See the old repo's quality_checks.py for the same
        # fix under pandas 2.x.
        # noqa rationale: PD013 suggests melt, but stack().dropna() is the
        # old repo's frozen ported logic (parity; see module docstring).
        flagged_long = flagged.stack().dropna().reset_index()  # noqa: PD013
        flagged_long.columns = ["date", "ticker", "daily_return"]
        if flagged_long.empty:
            return pd.DataFrame(columns=list(_FLAG_COLUMNS))

        flagged_long["reason"] = flagged_long["daily_return"].map(
            lambda r: f"outlier_return:{r:+.1%}"
        )
        return flagged_long[["ticker", "date", "reason"]]
