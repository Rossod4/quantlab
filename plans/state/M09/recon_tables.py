"""Recomputes the M09 reconciliation tables quoted in the README from the local,
git-ignored trials registry series. Nothing is re-run. From the repo root:

    uv run python plans/state/M09/recon_tables.py

Needs: reports/trials (momentum grid and headline series), reports/trials.bak_pre_cleanrun_
2026-10-01 (the September value series), reports/value_composite/net_returns.parquet and
data/cache/fundamentals (file times). Conventions: equity = cumprod(1 + r) from 1.0, CAGR over
len(r)/12 years, Sharpe = mean/std(ddof=1) * sqrt(12)."""

import datetime as dt
import json
import os
from pathlib import Path

import pandas as pd

R = Path(__file__).resolve().parents[3]


def series(path):
    s = pd.read_parquet(path)
    s = s["net_return"] if "net_return" in s else s.squeeze()
    s.index = pd.DatetimeIndex(s.index)
    return s


def cagr(r):
    return (1 + r).prod() ** (12 / len(r)) - 1


def sharpe(r):
    return r.mean() / r.std() * 12**0.5


def maxdd(r):
    eq = pd.concat([pd.Series([1.0]), (1 + r.reset_index(drop=True)).cumprod()], ignore_index=True)
    return (eq / eq.cummax() - 1).min()


# ---- momentum: the predecessor's own parameterisation is a committed grid point ----
print("MOMENTUM (registry series)")
rows = [json.loads(line) for line in open(R / "reports/trials/trials.jsonl")]
seen = set()
for r in rows:
    key = r["key"][0]
    if key in ("momentum_12_1-c993bc68ed", "momentum-2b2c9fd50a") and r["series_path"]:
        s = series(r["series_path"])
        if key in seen:
            continue
        seen.add(key)
        label = "headline (12, 30)" if key.startswith("momentum-") else "grid (12, 50)"
        print(
            f"{label:20s} {key:28s} CAGR {cagr(s):.4%} Sharpe {sharpe(s):.4f} "
            f"maxDD {maxdd(s):.4%} hash {r['series_hash'][:10]} n={len(s)}"
        )

# ---- value: 13 Sept vs 25 Sept (same params, both unscanned) vs final ----
bak = R / "reports/trials.bak_pre_cleanrun_2026-10-01/series"
s13 = series(bak / "f22358628c03a714.parquet")  # value_composite-b6fdfec048, 13 Sept headline
s25 = series(bak / "cbc6db3a900b31e5.parquet")  # value_composite-b67309d696, 25 Sept grid point
final = series(R / "reports/value_composite/net_returns.parquet")
wins = {
    "full": (None, None),
    "2012-19": ("2012-01-01", "2019-12-31"),
    "2020": ("2020-01-01", "2020-12-31"),
    "2021-22": ("2021-01-01", "2022-12-31"),
    "2023+": ("2023-01-01", None),
}
print("VALUE")
for name, s in (("13 Sept", s13), ("25 Sept", s25), ("final", final)):
    cells = [f"{w} {cagr(s.loc[a:b] if (a or b) else s):.2%}" for w, (a, b) in wins.items()]
    print(name, "|", " | ".join(cells), f"| Sharpe {sharpe(s):.4f}")
d25f = (s25 - final).abs() > 1e-12
print("13 vs 25 Sept differing periods", int(((s13 - s25).abs() > 0).sum()), "of", len(s13))
print("25 Sept vs final differing periods", int(d25f.sum()), "first", d25f[d25f].index.min().date())

# ---- fundamentals files first written after the 13 Sept value run ended ----
fd = R / "data/cache/fundamentals"
late = sorted(
    (dt.datetime.fromtimestamp(os.path.getctime(fd / f)), f)
    for f in os.listdir(fd)
    if dt.datetime.fromtimestamp(os.path.getctime(fd / f)) >= dt.datetime(2026, 9, 14)
)
print("fundamentals files first written after 2026-09-14:", len(late), late[0][0], late[-1][0])
print(sorted({f.split(".")[0] for _, f in late}))
