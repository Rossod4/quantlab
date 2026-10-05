"""Ken French factor provider: offline parse + cache + vintage (fixtures in
tests/fixtures/factors/); one `network` test does the real download."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantlab.attribution.factors import (
    BASE_URL,
    FACTOR_COLUMNS,
    FF5_ZIP,
    MOM_ZIP,
    FactorData,
    FactorDataUnavailable,
    FactorProvider,
    KenFrenchProvider,
    parse_french_csv,
)

FIXTURES = Path(__file__).parent / "fixtures" / "factors"
FF5_COLUMNS = ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF")


def _zip_bytes(csv_name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(csv_name, text)
    return buf.getvalue()


def _fixture_fetch(calls: list[str] | None = None):
    payloads = {
        BASE_URL + FF5_ZIP: _zip_bytes("ff5.csv", (FIXTURES / "ff5_sample.csv").read_text()),
        BASE_URL + MOM_ZIP: _zip_bytes("mom.csv", (FIXTURES / "mom_sample.csv").read_text()),
    }

    def fetch(url: str):
        if calls is not None:
            calls.append(url)
        return payloads[url], "Fri, 25 Sep 2026 21:55:02 GMT"

    return fetch


def _never_fetch(url: str):
    raise AssertionError(f"network touched: {url}")


# --- parse --------------------------------------------------------------------


def test_parse_converts_percent_to_decimal_and_indexes_by_month():
    frame, _ = parse_french_csv((FIXTURES / "ff5_sample.csv").read_text(), FF5_COLUMNS)

    assert isinstance(frame.index, pd.PeriodIndex)
    assert frame.index[0] == pd.Period("2020-01", freq="M")
    assert frame.index[-1] == pd.Period("2020-12", freq="M")
    assert frame.loc[pd.Period("2020-03", freq="M"), "Mkt-RF"] == pytest.approx(-0.1339)
    assert frame.loc[pd.Period("2020-01", freq="M"), "RF"] == pytest.approx(0.0013)
    assert list(frame.columns) == list(FF5_COLUMNS)


def test_parse_reads_only_the_monthly_block_not_the_annual_table():
    frame, _ = parse_french_csv((FIXTURES / "ff5_sample.csv").read_text(), FF5_COLUMNS)

    assert len(frame) == 12  # the 2020 annual row (4 digits) is not a month


def test_parse_turns_the_missing_value_sentinel_into_nan():
    frame, _ = parse_french_csv((FIXTURES / "ff5_sample.csv").read_text(), FF5_COLUMNS)

    assert np.isnan(frame.loc[pd.Period("2020-11", freq="M"), "Mkt-RF"])
    assert frame["Mkt-RF"].notna().sum() == 11


def test_parse_returns_the_vintage_preamble_even_when_the_line_is_wrapped():
    _, ff5_note = parse_french_csv((FIXTURES / "ff5_sample.csv").read_text(), FF5_COLUMNS)
    _, mom_note = parse_french_csv((FIXTURES / "mom_sample.csv").read_text(), ("Mom",))

    assert ff5_note == "This file was created using the 202608 CRSP database."
    assert mom_note == "This file was created using the 202608 CRSP database."


def test_parse_rejects_a_header_that_does_not_match():
    with pytest.raises(ValueError, match="unexpected factor columns"):
        parse_french_csv((FIXTURES / "ff5_sample.csv").read_text(), ("Mom",))


def test_parse_rejects_text_without_a_header_or_rows():
    with pytest.raises(ValueError, match="no header"):
        parse_french_csv("nothing here\n202001, 1.0\n", ("Mom",))
    with pytest.raises(ValueError, match="no monthly rows"):
        parse_french_csv("note\n\n,Mom\n\nfooter\n", ("Mom",))


# --- provider / cache ---------------------------------------------------------


def test_cached_mode_with_an_empty_cache_refuses_and_never_touches_the_network(tmp_path):
    provider = KenFrenchProvider(tmp_path, mode="cached", fetch=_never_fetch)

    with pytest.raises(FactorDataUnavailable, match="--factors refresh"):
        provider.load()


def test_refresh_downloads_caches_and_records_the_vintage(tmp_path):
    calls: list[str] = []
    provider = KenFrenchProvider(tmp_path, mode="refresh", fetch=_fixture_fetch(calls))

    data = provider.load()

    assert isinstance(provider, FactorProvider) and isinstance(data, FactorData)
    assert calls == [BASE_URL + FF5_ZIP, BASE_URL + MOM_ZIP]
    assert list(data.frame.columns) == list(FACTOR_COLUMNS)
    # the momentum fixture has 2019-12 too; the inner join keeps the 12 shared months
    assert len(data.frame) == 12
    assert data.frame.loc[pd.Period("2020-06", freq="M"), "Mom"] == pytest.approx(0.1246)

    cache = tmp_path / "factors"
    for name in (FF5_ZIP, MOM_ZIP):
        assert (cache / name).exists()
        meta = json.loads((cache / f"{name}.meta.json").read_text())
        assert meta["url"] == BASE_URL + name
        assert meta["last_modified"] == "Fri, 25 Sep 2026 21:55:02 GMT"
        pd.Timestamp(meta["fetched_at"])  # parseable
        assert len(meta["sha256"]) == 64

    vintage = data.vintage
    assert vintage["first_month"] == "2020-01" and vintage["last_month"] == "2020-12"
    assert vintage["fetched_at"] == max(
        json.loads((cache / f"{n}.meta.json").read_text())["fetched_at"] for n in (FF5_ZIP, MOM_ZIP)
    )
    assert vintage["files"][FF5_ZIP]["library_note"].startswith("This file was created")


def test_cached_mode_reads_what_refresh_wrote_without_any_download(tmp_path):
    first = KenFrenchProvider(tmp_path, mode="refresh", fetch=_fixture_fetch()).load()

    second = KenFrenchProvider(tmp_path, mode="cached", fetch=_never_fetch).load()

    pd.testing.assert_frame_equal(first.frame, second.frame)
    assert first.vintage == second.vintage


def test_a_tampered_cache_file_is_refused(tmp_path):
    KenFrenchProvider(tmp_path, mode="refresh", fetch=_fixture_fetch()).load()
    (tmp_path / "factors" / FF5_ZIP).write_bytes(b"not the file that was fetched")

    with pytest.raises(FactorDataUnavailable, match="sha256"):
        KenFrenchProvider(tmp_path, mode="cached", fetch=_never_fetch).load()


def test_a_download_failure_is_reported_as_unavailable(tmp_path):
    def broken(url: str):
        raise ConnectionError("no route")

    with pytest.raises(FactorDataUnavailable, match="download of .* failed"):
        KenFrenchProvider(tmp_path, mode="refresh", fetch=broken).load()


def test_an_unknown_mode_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        KenFrenchProvider(tmp_path, mode="sometimes")


@pytest.mark.network
def test_real_ken_french_download_parses_and_covers_the_backtest_window(tmp_path):
    """The one live call: both library files download, parse, and span the
    2012-2026 window the committed backtests cover."""
    data = KenFrenchProvider(tmp_path, mode="refresh").load()

    frame = data.frame
    assert list(frame.columns) == list(FACTOR_COLUMNS)
    assert frame.index[0] <= pd.Period("2012-01", freq="M")
    assert frame.index[-1] >= pd.Period("2026-06", freq="M")
    assert frame.drop(columns="RF").abs().max().max() < 0.5  # decimals, not percent
    assert (frame["RF"] >= 0).all()
    for meta in data.vintage["files"].values():
        assert meta["library_note"].startswith("This file was created")
        print(meta["library_note"], "| Last-Modified:", meta["last_modified"])
