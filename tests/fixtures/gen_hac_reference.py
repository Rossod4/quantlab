"""Generates tests/fixtures/hac_reference.json: a seeded regression problem
(AR(1) errors, 3 regressors, n=96) and the coefficients / classical and
Newey-West standard errors / R-squared that statsmodels computes for it.

statsmodels is NOT a quantlab dependency; run this once, ad hoc:

    uv run --with statsmodels python tests/fixtures/gen_hac_reference.py

and commit the JSON it writes. tests/test_regression.py compares
quantlab.attribution.regression to it (HAC SEs to 1e-8). The reference uses
`cov_type="HAC"` with `cov_kwds={"maxlags": L, "use_correction": False}`, the
convention documented in regression.py (Bartlett kernel, no n/(n-k) factor).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import statsmodels
import statsmodels.api as sm

LAGS = (0, 4, 6, 12)


def main() -> None:
    rng = np.random.default_rng(20261005)
    n, k = 96, 3
    x = rng.normal(0.0, 0.04, size=(n, k))
    eps = np.empty(n)
    shock = rng.normal(0.0, 0.02, size=n)
    eps[0] = shock[0]
    for t in range(1, n):
        eps[t] = 0.4 * eps[t - 1] + shock[t]
    beta = np.array([1.1, -0.3, 0.5])
    y = 0.002 + x @ beta + eps

    design = sm.add_constant(x)
    out: dict = {
        "generator": "tests/fixtures/gen_hac_reference.py",
        "statsmodels_version": statsmodels.__version__,
        "y": y.tolist(),
        "x": x.tolist(),
        "hac": {},
    }
    base = sm.OLS(y, design).fit()
    out["coef"] = base.params.tolist()
    out["se_ols"] = base.bse.tolist()
    out["r2"] = float(base.rsquared)
    out["adj_r2"] = float(base.rsquared_adj)
    for lag in LAGS:
        res = sm.OLS(y, design).fit(
            cov_type="HAC", cov_kwds={"maxlags": lag, "use_correction": False}
        )
        out["hac"][str(lag)] = res.bse.tolist()
    path = Path(__file__).with_name("hac_reference.json")
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {path} (statsmodels {statsmodels.__version__})")


if __name__ == "__main__":
    main()
