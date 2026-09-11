"""Validation suite (M05/M06): metrics, rolling/sub-period robustness,
walk-forward weight-choice honesty, and parameter-sensitivity ("no-cliff")
checks on a `BacktestResult`. See plans/M05-validation-1.md.

M05 (this milestone) ships the "basic" tier: `validation.metrics`,
`validation.rolling`, `validation.walk_forward`, `validation.sensitivity`,
and `validation.basic.validate_basic`. Purged CV, PSR/DSR, White RC/SPA,
Monte Carlo, capacity, and the verdict are M06.
"""

from __future__ import annotations
