from __future__ import annotations

import pandas as pd
import pytest

from quantlab.core.errors import DataQualityError
from quantlab.data.interfaces import PriceProvider
from quantlab.data.quality import (
    QualityGate,
    heal_or_flag_new_listings,
    membership_start_by_ticker,
    scan_price_cache,
    symbol_reuse_gap_reasons,
    symbol_reuse_new_listing_reason,
    unexplained_jump_dates,
    zero_volume_fraction,
)


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


# ============================================================================
# Cache-level quarantine checks (M04b quant-gate VERDICT.md cycle 1 finding 2)
# ============================================================================


def test_zero_volume_fraction_flags_a_ptv_like_series():
    """The gate's own evidence: PTV cached at 47.7% zero-volume bars - each
    with its OWN (non-repeated) close, ruling out the padding exclusion."""
    n = 1000
    volumes = [0] * 477 + [1000] * (n - 477)
    # Every close distinct from its neighbour, real or not, so none of the
    # zero-volume rows look like a repeated-close padding artifact.
    closes = [22_500.0 + i for i in range(n)]
    panel = pd.DataFrame({"volume": volumes, "close": closes})
    assert zero_volume_fraction(panel) == pytest.approx(0.477, abs=1e-6)


def test_zero_volume_fraction_is_zero_for_a_clean_control():
    panel = pd.DataFrame({"volume": [50_000] * 500, "close": [100.0 + i for i in range(500)]})
    assert zero_volume_fraction(panel) == 0.0


def test_zero_volume_fraction_empty_panel_is_zero():
    assert zero_volume_fraction(pd.DataFrame(columns=["volume", "close"])) == 0.0


def test_zero_volume_fraction_excludes_forward_fill_padding():
    """Cycle-2 regression: the shared cache's own EA entry is 6 rows, 4 of
    them an IDENTICAL repeated close at volume=0 - a yfinance batch-download
    padding artifact (a non-trading date in the batch's combined date range,
    forward-filled), not 4 genuine zero-volume sessions. Real bars: 2 of 2,
    zero of them zero-volume -> a real fraction of 0.0%, not 66.7%."""
    panel = pd.DataFrame(
        {
            "close": [208.9, 209.7, 209.7, 209.7, 209.7, 209.7],
            "volume": [3_883_020, 48_713_698, 0, 0, 0, 0],
        }
    )
    assert zero_volume_fraction(panel) == 0.0


def test_zero_volume_fraction_padding_exclusion_still_flags_a_genuinely_dead_series():
    """A ticker that is ENTIRELY flat-and-zero-volume (CCE/MHS-style, a
    genuinely dead reused symbol) must still read 100%, not 0% - the
    padding exclusion removes REPEATS, not the whole series (the first row
    has no "prior" to repeat, so it survives as one real bar, itself
    zero-volume)."""
    panel = pd.DataFrame({"close": [50.0] * 138, "volume": [0] * 138})
    assert zero_volume_fraction(panel) == pytest.approx(1.0)


def test_level_implausible_flags_a_two_regime_series():
    from quantlab.data.quality import _level_implausible

    closes = pd.Series([16.0] * 500 + [8000.0] * 252)
    assert _level_implausible(closes, ratio_threshold=20.0) is True


def test_level_implausible_false_for_a_stable_series():
    from quantlab.data.quality import _level_implausible

    closes = pd.Series([500.0 + i * 0.1 for i in range(750)])
    assert _level_implausible(closes, ratio_threshold=20.0) is False


def test_unexplained_jump_dates_flags_a_tie_like_interleaved_series():
    """The gate's own evidence: TIE interleaved ~$16 real bars with
    ~$7,000-8,200 garbage bars at a >400x ratio."""
    dates = pd.bdate_range("2012-01-01", periods=10)
    closes = [16.0 if i % 2 == 0 else 8000.0 for i in range(10)]
    panel = pd.DataFrame({"close": closes}, index=dates)

    jumps = unexplained_jump_dates(panel, actions=None, ratio_threshold=4.0)

    assert len(jumps) >= 8  # every alternating transition is an unexplained jump


def test_unexplained_jump_dates_excuses_a_jump_explained_by_a_split_on_that_ex_date():
    dates = pd.bdate_range("2012-01-01", periods=10)
    closes = [100.0] * 5 + [10.0] * 5  # a 10:1 split-sized drop
    panel = pd.DataFrame({"close": closes}, index=dates)
    actions = pd.DataFrame(
        {"ticker": ["X"], "action_type": ["split"], "value": [10.0]},
        index=pd.DatetimeIndex([dates[5]], name="date"),
    )

    jumps = unexplained_jump_dates(panel, actions=actions, ratio_threshold=4.0)

    assert dates[5] not in jumps


def test_unexplained_jump_dates_excuses_a_split_recorded_a_few_sessions_off():
    """Cycle-2 widening: a split recorded 2 sessions away from the jump
    (within the default 3-session excuse window) still excuses it - vendor
    actions-feed timing is not always exactly the jump date."""
    dates = pd.bdate_range("2012-01-01", periods=10)
    closes = [100.0] * 5 + [10.0] * 5
    panel = pd.DataFrame({"close": closes}, index=dates)
    actions = pd.DataFrame(
        {"ticker": ["X"], "action_type": ["split"], "value": [10.0]},
        index=pd.DatetimeIndex([dates[7]], name="date"),  # 2 sessions after the jump at dates[5]
    )

    jumps = unexplained_jump_dates(panel, actions=actions, ratio_threshold=4.0)

    assert dates[5] not in jumps


def test_unexplained_jump_dates_does_not_excuse_a_split_far_outside_the_window():
    dates = pd.bdate_range("2012-01-01", periods=10)
    closes = [100.0] * 5 + [10.0] * 5
    panel = pd.DataFrame({"close": closes}, index=dates)
    actions = pd.DataFrame(
        {"ticker": ["X"], "action_type": ["split"], "value": [10.0]},
        index=pd.DatetimeIndex([dates[0]], name="date"),  # far outside a 3-session window
    )

    jumps = unexplained_jump_dates(panel, actions=actions, ratio_threshold=4.0)

    assert dates[5] in jumps


def test_unexplained_jump_dates_empty_for_a_flat_series():
    dates = pd.bdate_range("2012-01-01", periods=10)
    panel = pd.DataFrame({"close": [100.0] * 10}, index=dates)
    assert unexplained_jump_dates(panel, actions=None, ratio_threshold=4.0) == []


def test_symbol_reuse_gap_reasons_flags_a_level_jump_across_a_missing_run():
    from quantlab.core.calendar import trading_days

    sessions = trading_days("2005-01-03", "2007-01-03")
    before, after = sessions[:200], sessions[210:]  # a 10-session gap
    panel = pd.DataFrame(
        {"close": [16.0] * len(before) + [8000.0] * len(after)},
        index=before.append(after),
    )

    reasons = symbol_reuse_gap_reasons(panel, ratio_threshold=4.0, min_gap_sessions=5)

    assert len(reasons) == 1


def test_symbol_reuse_gap_reasons_empty_for_a_clean_continuous_series():
    from quantlab.core.calendar import trading_days

    sessions = trading_days("2005-01-03", "2007-01-03")
    panel = pd.DataFrame({"close": [500.0] * len(sessions)}, index=sessions)

    assert symbol_reuse_gap_reasons(panel, ratio_threshold=4.0, min_gap_sessions=5) == []


def test_symbol_reuse_gap_reasons_ignores_a_gap_too_short_to_count():
    from quantlab.core.calendar import trading_days

    sessions = trading_days("2005-01-03", "2007-01-03")
    before, after = sessions[:200], sessions[202:]  # a 2-session gap, below min_gap_sessions
    panel = pd.DataFrame(
        {"close": [16.0] * len(before) + [8000.0] * len(after)},
        index=before.append(after),
    )

    assert symbol_reuse_gap_reasons(panel, ratio_threshold=4.0, min_gap_sessions=5) == []


def _interleaved_jumps(n: int, lo: float, hi: float, period: int) -> list[float]:
    """A price series that jumps between `lo` and `hi` every `period`
    sessions - several genuinely unexplained level transitions, the
    TIE/BMC/CBE-style reuse signature (MANY transitions, not one)."""
    out = []
    level = lo
    for i in range(n):
        if i % period == 0 and i > 0:
            level = hi if level == lo else lo
        out.append(level)
    return out


def test_scan_price_cache_quarantines_corrupted_tickers_and_spares_live_names(tmp_path):
    """Cycle 2 (orchestrator follow-up to VERDICT.md finding 2): synthetic
    data shaped like BOTH the gate's original evidence (PTV/BMC/TIE/CBE/MEE
    - genuinely contaminated) AND the cycle-1 false positives it caused
    (EA/EQR/FERG/AMCR - live large caps wrongly quarantined purely from
    yfinance zero-volume PADDING; KDP - a live name with a single genuine,
    real price-level shift and no split on file, wrongly quarantined at
    n=1 unexplained jump). Every one of these names must land on the
    correct side after the tightening."""
    from quantlab.core.calendar import trading_days
    from quantlab.data.cache import price_cache_path, price_meta_path, read_json_meta

    sessions = trading_days("2010-06-01", "2020-12-30")
    n = len(sessions)

    def _write(ticker: str, closes: list[float], volumes: list[int]) -> None:
        df = pd.DataFrame(
            {
                "Open": closes,
                "High": [c * 1.001 for c in closes],
                "Low": [c * 0.999 for c in closes],
                "Close": closes,
                "Adj Close": closes,
                "Volume": volumes,
            },
            index=sessions[: len(closes)],
        )
        path = price_cache_path(ticker, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)

    # -- positives: genuinely contaminated (>= 3 unexplained jumps, or a
    # genuinely dead series) -----------------------------------------------
    _write("PTV", _interleaved_jumps(n, 22.0, 1_330_000.0, period=400), [1000] * n)
    _write("BMC", _interleaved_jumps(n, 45.0, 30_050.0, period=60), [1000] * n)
    _write("TIE", [16.0 if i % 2 == 0 else 8000.0 for i in range(n)], [11_000] * n)
    _write("CBE", _interleaved_jumps(n, 20.0, 900.0, period=6), [1000] * n)
    # MEE-like: genuinely dead - a slowly, monotonically drifting close
    # (NEVER repeated, so never excluded as padding) with ~90% real
    # zero-volume bars.
    _write(
        "MEE",
        [100.0 + i * 0.001 for i in range(n)],
        [0 if i % 10 != 0 else 1000 for i in range(n)],
    )

    # -- negative controls: live, legitimate names ---------------------------
    # EA/EQR/FERG/AMCR-like: a clean, continuously-growing series with
    # yfinance batch-download PADDING at the tail (a REPEATED close at
    # volume=0 for a stretch of non-trading dates in the batch's combined
    # date range) - the exact shape that wrongly quarantined these names.
    for ticker in ("EA", "EQR", "FERG", "AMCR"):
        real_closes = [150.0 + i * 0.05 for i in range(n - 20)]
        padded_closes = real_closes + [real_closes[-1]] * 20
        volumes = [50_000] * (n - 20) + [0] * 20
        _write(ticker, padded_closes, volumes)
    # KDP-like: ONE genuine, real level shift (a merger), no split on file -
    # must NOT quarantine (a single jump is below min_unexplained_jumps).
    kdp_closes = [120.0] * (n // 2) + [27.0] * (n - n // 2)
    _write("KDP", kdp_closes, [1_000_000] * n)
    # NVR/AZO-like: clean, continuous, gradual growth, no zero-volume bars.
    _write("NVR", [575.0 + i * (9924.0 - 575.0) / n for i in range(n)], [50_000] * n)
    _write("AZO", [186.0 + i * (4355.0 - 186.0) / n for i in range(n)], [40_000] * n)

    report = scan_price_cache(tmp_path)

    assert set(report.quarantined) == {"PTV", "BMC", "TIE", "CBE", "MEE"}
    assert report.scanned_count == 12

    for ticker in ("PTV", "BMC", "TIE", "CBE", "MEE"):
        meta = read_json_meta(price_meta_path(ticker, tmp_path))
        assert meta["quarantined"] is True
        assert meta["reasons"]  # non-empty

    for ticker in ("EA", "EQR", "FERG", "AMCR", "KDP", "NVR", "AZO"):
        meta = read_json_meta(price_meta_path(ticker, tmp_path))
        assert meta is None or not meta.get("quarantined"), (
            f"{ticker} was wrongly quarantined: {meta}"
        )


def test_scan_price_cache_preserves_existing_positive_sidecar_metadata(tmp_path):
    """Quarantining a ticker must MERGE into its sidecar, not replace it -
    a real ticker's `requested_start`/`requested_end` (data/cache.py's
    `write_price_cache_meta`) must survive quarantine."""
    from quantlab.core.calendar import trading_days
    from quantlab.data.cache import (
        price_cache_path,
        price_meta_path,
        read_json_meta,
        write_price_cache_meta,
    )

    sessions = trading_days("2005-01-03", "2011-12-30")
    n = len(sessions)
    # A monotonically drifting close (never repeated, so never excluded as
    # padding - see `zero_volume_fraction`'s docstring) with ~90% real
    # zero-volume bars, well above the hard quarantine threshold.
    closes = [22_500.0 + i * 0.01 for i in range(n)]
    volumes = [0 if i % 10 != 0 else 1000 for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.001 for c in closes],
            "Low": [c * 0.999 for c in closes],
            "Close": closes,
            "Adj Close": closes,
            "Volume": volumes,
        },
        index=sessions,
    )
    path = price_cache_path("PTV", tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    write_price_cache_meta("PTV", "2005-01-01", "2026-06-30", tmp_path)

    scan_price_cache(tmp_path)

    meta = read_json_meta(price_meta_path("PTV", tmp_path))
    assert meta["quarantined"] is True
    assert meta["requested_start"] == "2005-01-01"
    assert meta["requested_end"] == "2026-06-30"


# ============================================================================
# Membership-aware symbol reuse (M04b quant-gate cycle-2 review): Yahoo
# reassigns a delisted ticker's symbol to a NEW listing, whose own price
# series is clean and healthy-looking - the price-arithmetic checks above
# cannot see this at all. A membership-start comparison catches it directly.
# ============================================================================


def test_membership_start_by_ticker_takes_the_earliest_appearance():
    history = pd.DataFrame(
        {
            "tickers": [["AAA"], ["AAA", "BBB"], ["AAA", "BBB", "CCC"]],
        },
        index=pd.DatetimeIndex(["2000-01-01", "2005-01-01", "2010-01-01"]),
    )
    starts = membership_start_by_ticker(history)
    assert starts == {
        "AAA": pd.Timestamp("2000-01-01"),
        "BBB": pd.Timestamp("2005-01-01"),
        "CCC": pd.Timestamp("2010-01-01"),
    }


def test_membership_start_by_ticker_dates_a_reentry_to_its_latest_contiguous_span():
    """A ticker that LEAVES the index and is later re-admitted (or whose
    symbol is reused by an unrelated company) must be dated to its LATEST
    contiguous span, not its original historical entry - `symbol_reuse_new_
    listing_reason` needs the CURRENT holder's own span start, and an old,
    unrelated span decades ago must not count against a symbol legitimately
    in use today (the SNDK/AMTM real-world case this guards against - see
    `membership_start_by_ticker`'s own docstring)."""
    history = pd.DataFrame(
        {
            # SNDK present 2000-2010, ABSENT 2015 (a real gap), present again
            # from 2020 (a new company reusing the symbol). AAA never leaves.
            "tickers": [
                ["AAA", "SNDK"],
                ["AAA", "SNDK"],
                ["AAA"],  # SNDK dropped out of the index here
                ["AAA", "SNDK"],  # SNDK re-enters - a DIFFERENT span
            ],
        },
        index=pd.DatetimeIndex(["2000-01-01", "2010-01-01", "2015-01-01", "2020-01-01"]),
    )

    starts = membership_start_by_ticker(history)

    assert starts["AAA"] == pd.Timestamp("2000-01-01")  # continuous - unaffected by re-entry logic
    assert starts["SNDK"] == pd.Timestamp("2020-01-01")  # LATEST span, not the original 2000-01-01


def test_symbol_reuse_new_listing_reason_flags_an_ea_like_reissue():
    """The gate's own evidence: EA - requested from 2010-06-01, S&P
    membership since 2002-07-22, cached history starting 2026-07-17 (the
    week the symbol was reissued) - far past BOTH reference points."""
    reason = symbol_reuse_new_listing_reason(
        first_bar=pd.Timestamp("2026-07-17"),
        membership_start=pd.Timestamp("2002-07-22"),
        requested_start=pd.Timestamp("2010-06-01"),
        tolerance_sessions=400,
    )
    assert reason is not None
    assert "symbol_reuse_new_listing" in reason


def test_symbol_reuse_new_listing_reason_none_for_a_genuine_new_member():
    """AMTM-like: membership begins essentially AT the first cached bar - a
    genuinely new S&P member, not a reused symbol - even though the cache's
    own requested_start (2010) is far earlier still."""
    reason = symbol_reuse_new_listing_reason(
        first_bar=pd.Timestamp("2024-09-24"),
        membership_start=pd.Timestamp("2024-09-30"),
        requested_start=pd.Timestamp("2010-06-01"),
        tolerance_sessions=400,
    )
    assert reason is None


def test_symbol_reuse_new_listing_reason_none_when_price_history_predates_membership():
    """FERG/AMCR-like: a company's price history routinely predates its OWN
    index membership - never a reuse signal."""
    reason = symbol_reuse_new_listing_reason(
        first_bar=pd.Timestamp("2010-06-01"),
        membership_start=pd.Timestamp("2026-08-05"),
        requested_start=pd.Timestamp("2010-06-01"),
        tolerance_sessions=400,
    )
    assert reason is None


def test_symbol_reuse_new_listing_reason_none_when_first_bar_matches_the_cache_requested_start():
    """IBM/MSFT/JNJ-style regression: a ticker whose S&P membership predates
    this cache's OWN 2010-06-01 prefetch floor, but whose cached data starts
    EXACTLY at that floor, must NEVER be flagged - the cache was simply
    never asked to reach back further, a documented, deliberate limitation
    of THIS cache's fetch window, not evidence of anything wrong with the
    ticker. This is the false-positive an earlier version of this check
    produced for nearly the whole shared cache."""
    reason = symbol_reuse_new_listing_reason(
        first_bar=pd.Timestamp("2010-06-01"),
        membership_start=pd.Timestamp("1996-01-02"),  # decades before the cache's own floor
        requested_start=pd.Timestamp("2010-06-01"),
        tolerance_sessions=400,
    )
    assert reason is None


def test_symbol_reuse_new_listing_reason_none_within_tolerance():
    reason = symbol_reuse_new_listing_reason(
        first_bar=pd.Timestamp("2010-08-01"),
        membership_start=pd.Timestamp("2010-01-01"),  # a few months, well under 400 sessions
        requested_start=pd.Timestamp("2010-06-01"),
        tolerance_sessions=400,
    )
    assert reason is None


def test_symbol_reuse_new_listing_reason_none_when_membership_unknown():
    assert (
        symbol_reuse_new_listing_reason(
            pd.Timestamp("2026-07-17"), None, pd.Timestamp("2010-06-01")
        )
        is None
    )


def test_symbol_reuse_new_listing_reason_none_when_requested_start_unknown():
    assert (
        symbol_reuse_new_listing_reason(
            pd.Timestamp("2026-07-17"), pd.Timestamp("2002-07-22"), None
        )
        is None
    )


def test_scan_price_cache_quarantines_a_reused_symbol_via_membership_and_spares_a_new_member(
    tmp_path,
):
    from quantlab.core.calendar import trading_days
    from quantlab.data.cache import (
        price_cache_path,
        price_meta_path,
        read_json_meta,
        write_price_cache_meta,
    )

    sessions = trading_days("2026-01-01", "2026-08-31")
    n = len(sessions)

    def _write(ticker: str) -> None:
        closes = [100.0 + i * 0.1 for i in range(n)]
        df = pd.DataFrame(
            {
                "Open": closes,
                "High": [c * 1.001 for c in closes],
                "Low": [c * 0.999 for c in closes],
                "Close": closes,
                "Adj Close": closes,
                "Volume": [50_000] * n,
            },
            index=sessions,
        )
        path = price_cache_path(ticker, tmp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path)
        # A cache requested from well before the ticker's cached history OR
        # its membership start - the standard shared-cache convention -
        # so the "requested_start" side of the check is also satisfied.
        write_price_cache_meta(ticker, "2010-06-01", "2026-09-11", tmp_path)

    _write("EA")  # clean, healthy series - the price checks alone see nothing wrong
    _write("AMTM")  # equally clean - a genuine new listing

    membership = {
        "EA": pd.Timestamp("2002-07-22"),  # far earlier -> reused symbol
        "AMTM": sessions[0],  # membership starts at the first cached bar -> genuine
    }

    report = scan_price_cache(tmp_path, membership_start_by_ticker_map=membership)

    assert "EA" in report.quarantined
    assert any("symbol_reuse_new_listing" in r for r in report.quarantined["EA"])
    assert "AMTM" not in report.quarantined

    ea_meta = read_json_meta(price_meta_path("EA", tmp_path))
    assert ea_meta["quarantined"] is True


class _FakeRefetchProvider(PriceProvider):
    """Records requested tickers, serves a per-ticker canned response, AND
    writes it to the on-disk cache (raw Yahoo-style columns) - mirroring
    the real `YFinancePriceProvider`'s own side effect of caching whatever
    it fetches. `heal_or_flag_new_listings` re-reads the cache after
    calling this provider, exactly as it would a real one, so the fake must
    behave the same way for the "healed" path to be observable at all."""

    def __init__(self, cache_dir, responses: dict[str, pd.DataFrame]):
        self._cache_dir = cache_dir
        self._responses = responses
        self.requested: list[str] | None = None

    def get_prices(self, tickers: list[str], start: object, end: object) -> pd.DataFrame:
        from quantlab.data.cache import price_cache_path, write_cache

        self.requested = list(tickers)
        frames = []
        for t in tickers:
            if t not in self._responses:
                continue
            long_panel = self._responses[t]
            raw = pd.DataFrame(
                {
                    "Open": long_panel["open"],
                    "High": long_panel["high"],
                    "Low": long_panel["low"],
                    "Close": long_panel["close"],
                    "Adj Close": long_panel["adj_close"],
                    "Volume": long_panel["volume"],
                },
                index=long_panel.index,
            )
            write_cache(raw, price_cache_path(t, self._cache_dir))
            frames.append(long_panel)
        if not frames:
            return pd.DataFrame(
                columns=["ticker", "open", "high", "low", "close", "adj_close", "volume"]
            )
        return pd.concat(frames)


def _long_panel(ticker: str, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    n = len(sessions)
    return pd.DataFrame(
        {
            "ticker": [ticker] * n,
            "open": [100.0 + i * 0.01 for i in range(n)],
            "high": [100.0 + i * 0.01 for i in range(n)],
            "low": [100.0 + i * 0.01 for i in range(n)],
            "close": [100.0 + i * 0.01 for i in range(n)],
            "adj_close": [100.0 + i * 0.01 for i in range(n)],
            "volume": [50_000] * n,
        },
        index=sessions,
    )


def _write_raw_cache(ticker: str, sessions: pd.DatetimeIndex, cache_dir) -> None:
    from quantlab.data.cache import price_cache_path

    n = len(sessions)
    closes = [100.0 + i * 0.1 for i in range(n)]
    df = pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.001 for c in closes],
            "Low": [c * 0.999 for c in closes],
            "Close": closes,
            "Adj Close": closes,
            "Volume": [50_000] * n,
        },
        index=sessions,
    )
    path = price_cache_path(ticker, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)


def test_heal_or_flag_new_listings_heals_a_ticker_whose_refetch_grows_the_cache(tmp_path):
    """M04b quant-gate cycle-2 review: a live member's cache that merely
    LOOKS like a reused symbol (a stale/incomplete prior fetch - the M01
    hazard) must be given one real chance to heal before being quarantined."""
    from quantlab.core.calendar import trading_days

    short_sessions = trading_days("2026-07-01", "2026-08-31")
    _write_raw_cache("EQR", short_sessions, tmp_path)
    membership = {"EQR": pd.Timestamp("2001-12-03")}

    full_sessions = trading_days("2001-12-03", "2026-08-31")
    provider = _FakeRefetchProvider(tmp_path, {"EQR": _long_panel("EQR", full_sessions)})

    result = heal_or_flag_new_listings(
        tmp_path, provider, membership, "2001-12-03", "2026-08-31", tolerance_sessions=400
    )

    assert result == {"EQR": "healed"}
    assert provider.requested == ["EQR"]


def test_heal_or_flag_new_listings_leaves_a_genuine_reuse_still_late(tmp_path):
    """The SAME short series comes back on re-fetch (Yahoo genuinely has
    nothing earlier for the current holder of the symbol) - stays flagged
    for `scan_price_cache` to quarantine."""
    from quantlab.core.calendar import trading_days

    short_sessions = trading_days("2026-07-01", "2026-08-31")
    _write_raw_cache("EA", short_sessions, tmp_path)
    membership = {"EA": pd.Timestamp("2002-07-22")}

    provider = _FakeRefetchProvider(tmp_path, {"EA": _long_panel("EA", short_sessions)})

    result = heal_or_flag_new_listings(
        tmp_path, provider, membership, "2002-07-22", "2026-08-31", tolerance_sessions=400
    )

    assert result == {"EA": "still_late"}


def test_heal_or_flag_new_listings_never_touches_a_genuine_new_member(tmp_path):
    """A ticker whose membership starts AT its first cached bar is never a
    candidate at all - no re-fetch attempted, provider never called."""
    from quantlab.core.calendar import trading_days

    sessions = trading_days("2024-09-24", "2026-08-31")
    _write_raw_cache("AMTM", sessions, tmp_path)
    membership = {"AMTM": sessions[0]}

    provider = _FakeRefetchProvider(tmp_path, {})

    result = heal_or_flag_new_listings(
        tmp_path, provider, membership, "2024-09-24", "2026-08-31", tolerance_sessions=400
    )

    assert result == {}
    assert provider.requested is None
