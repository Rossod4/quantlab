"""Monthly US factor data: a `FactorProvider` interface and the Ken French
data library implementation.

The library (mba.tuck.dartmouth.edu/pages/faculty/ken.french) publishes zipped
CSVs in PERCENT units; they are parsed here to DECIMALS. Two files are used:
the Fama-French 5 factors (`Mkt-RF, SMB, HML, RMW, CMA, RF`) and the momentum
factor (`Mom`, i.e. UMD).

Network is touched ONLY by `KenFrenchProvider` in `refresh` mode. `cached`
mode (the default) reads `<cache_dir>/factors/` and raises
`FactorDataUnavailable` if it is empty - it never downloads. The library
REVISES its files (the CRSP database is re-cut every month, and the RF series
changed source in 2024), so every cached file has a `.meta.json` sidecar
recording `fetched_at`, the HTTP `Last-Modified`, the file's own preamble
line ("This file was created using the 202608 CRSP database.") and a sha256;
`FactorData.vintage` carries it into every attribution output.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import zipfile
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from quantlab.data.cache import read_json_meta, write_json_meta

FACTOR_COLUMNS = ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom", "RF")

BASE_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FF5_ZIP = "F-F_Research_Data_5_Factors_2x3_CSV.zip"
MOM_ZIP = "F-F_Momentum_Factor_CSV.zip"
_FILES: dict[str, tuple[str, ...]] = {
    FF5_ZIP: ("Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"),
    MOM_ZIP: ("Mom",),
}

# The library marks missing values -99.99 (and -999 in some files).
_MISSING_SENTINELS = (-99.99, -999.0)
_MONTH_ROW = re.compile(r"^\s*(\d{6})\s*,")


class FactorDataUnavailable(RuntimeError):
    """No usable factor data (empty cache in `cached` mode, or a download or
    parse failure in `refresh` mode)."""


@dataclass(frozen=True)
class FactorData:
    """`frame`: PeriodIndex(freq="M"), columns `FACTOR_COLUMNS`, DECIMAL
    returns. `vintage`: provenance of the files it came from."""

    frame: pd.DataFrame
    vintage: dict[str, Any]


class FactorProvider(ABC):
    @abstractmethod
    def load(self) -> FactorData:
        """Monthly factor returns (decimals) plus their vintage."""


def parse_french_csv(text: str, expected_columns: tuple[str, ...]) -> tuple[pd.DataFrame, str]:
    """Parse the MONTHLY block of a Ken French CSV.

    Returns `(frame, preamble)`: `frame` is PeriodIndex(M) x `expected_columns`
    in DECIMALS (percent / 100; the library's missing-value sentinels become
    NaN); `preamble` is the file's first non-empty line (its CRSP-vintage
    note). The block starts at the header line (a leading comma, then the
    column names) and ends at the first line that is not a `YYYYMM,` row - the
    annual table that follows is never read. A header that does not match
    `expected_columns` raises ValueError rather than silently mislabelling."""
    lines = text.splitlines()
    preamble = next((ln.strip() for ln in lines if ln.strip()), "")
    if "database." in preamble:  # the momentum file wraps this sentence mid-line
        preamble = preamble[: preamble.index("database.") + len("database.")]
    header_at = next((i for i, ln in enumerate(lines) if ln.startswith(",")), None)
    if header_at is None:
        raise ValueError("no header line (leading comma) found in factor file")
    header = tuple(c.strip() for c in lines[header_at].split(",")[1:])
    if header != expected_columns:
        raise ValueError(f"unexpected factor columns {header}, expected {expected_columns}")

    index: list[pd.Period] = []
    rows: list[list[float]] = []
    for ln in lines[header_at + 1 :]:
        m = _MONTH_ROW.match(ln)
        if m is None:
            if rows:
                break
            continue
        cells = [c.strip() for c in ln.split(",")[1:]]
        if len(cells) != len(expected_columns):
            raise ValueError(f"row {m.group(1)} has {len(cells)} values, expected {len(header)}")
        values = [float(c) for c in cells]
        rows.append([float("nan") if v in _MISSING_SENTINELS else v / 100.0 for v in values])
        index.append(pd.Period(m.group(1), freq="M"))
    if not rows:
        raise ValueError("factor file has a header but no monthly rows")
    frame = pd.DataFrame(rows, index=pd.PeriodIndex(index, freq="M"), columns=list(header))
    if frame.index.has_duplicates:
        raise ValueError("duplicate months in factor file")
    return frame, preamble


def _zip_text(raw: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError(f"expected exactly one CSV in the zip, found {zf.namelist()}")
        return zf.read(names[0]).decode("latin-1")


Fetch = Callable[[str], tuple[bytes, str | None]]


def _http_fetch(url: str) -> tuple[bytes, str | None]:
    import requests

    resp = requests.get(url, timeout=60, headers={"User-Agent": "quantlab-attribution"})
    resp.raise_for_status()
    return resp.content, resp.headers.get("last-modified")


class KenFrenchProvider(FactorProvider):
    """Ken French library factors, cached under `<cache_dir>/factors/`.

    `mode="cached"` reads the cache only; `mode="refresh"` re-downloads both
    files (the one network call) and overwrites the cache. `fetch` is
    injectable so tests never touch the network."""

    def __init__(self, cache_dir: str | Path, mode: str = "cached", fetch: Fetch | None = None):
        if mode not in ("cached", "refresh"):
            raise ValueError(f"mode must be 'cached' or 'refresh', got {mode!r}")
        self._dir = Path(cache_dir) / "factors"
        self._mode = mode
        self._fetch = fetch or _http_fetch

    def _meta_path(self, name: str) -> Path:
        return self._dir / f"{name}.meta.json"

    def _refresh(self) -> None:
        """Download BOTH files, validate them, and only then replace the cache
        (each file via a temp name + `os.replace`), so a failure on the second
        file or an unparseable payload leaves the previous vintage intact."""
        fetched: dict[str, tuple[bytes, str | None, str]] = {}
        for name, columns in _FILES.items():
            url = BASE_URL + name
            try:
                raw, last_modified = self._fetch(url)
                parse_french_csv(_zip_text(raw), columns)
            except Exception as exc:  # noqa: BLE001 - transport or payload failure
                raise FactorDataUnavailable(f"download of {url} failed: {exc}") from exc
            stamp = pd.Timestamp.now("UTC").isoformat(timespec="seconds")
            fetched[name] = (raw, last_modified, stamp)
        self._dir.mkdir(parents=True, exist_ok=True)
        for name, (raw, last_modified, stamp) in fetched.items():
            tmp = self._dir / f"{name}.tmp"
            tmp.write_bytes(raw)
            os.replace(tmp, self._dir / name)
            write_json_meta(
                self._meta_path(name),
                {
                    "url": BASE_URL + name,
                    "fetched_at": stamp,
                    "last_modified": last_modified,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "bytes": len(raw),
                },
            )

    def load(self) -> FactorData:
        if self._mode == "refresh":
            self._refresh()
        frames: list[pd.DataFrame] = []
        files: dict[str, Any] = {}
        for name, columns in _FILES.items():
            path = self._dir / name
            meta = read_json_meta(self._meta_path(name))
            if not path.exists() or meta is None:
                raise FactorDataUnavailable(
                    f"no cached factor file {path} (or its .meta.json); run "
                    "`quantlab attribute ... --factors refresh` once to download it"
                )
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != meta.get("sha256"):
                raise FactorDataUnavailable(f"{path} does not match its recorded sha256")
            try:
                frame, preamble = parse_french_csv(_zip_text(raw), columns)
            except ValueError as exc:
                raise FactorDataUnavailable(f"cannot parse {path}: {exc}") from exc
            frames.append(frame)
            files[name] = {**meta, "library_note": preamble}
        # Mom starts in 1927, FF5 in 1963: the inner join is the usable range.
        merged = pd.concat(frames, axis=1, join="inner")[list(FACTOR_COLUMNS)]
        fetched = sorted(f["fetched_at"] for f in files.values())
        return FactorData(
            frame=merged,
            vintage={
                "source": "Ken French data library (monthly US factors, percent -> decimal)",
                "fetched_at": fetched[-1],
                "files": files,
                "first_month": str(merged.index[0]),
                "last_month": str(merged.index[-1]),
            },
        )
