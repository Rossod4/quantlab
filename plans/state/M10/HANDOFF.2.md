# M10 HANDOFF.2 (answers REVIEW.md: 0 blocker, 1 major, 4 minor) - developer

Not committed. Numbers/tables in HANDOFF.md are unchanged except the correction in item 4 below.

| # | Status | What changed / evidence |
|---|---|---|
| 1 MAJOR C4 vs --force-research | fixed (per lead's decision) | The current-cache scan re-check is moved out of the `if match is not None` branch in `paper/runner.py::run_once`: it runs ALWAYS (card or no card, force or no force), before any order is planned or the context built. It refuses via `_refuse` (journaled) + `PromotionGateError`, naming the first 10 unscanned tickers and the count. Correction to HANDOFF.md: it is NOT skipped under `--force-research`. docs/paper-trading.md section 6 now says force waives eligibility only, not data quality. Tests: parametrised card x force matrix (all four paths refuse an unscanned cached ticker; no-card-no-force refuses earlier at the promotion gate, journal has one record, no orders), 14-ticker message shows 10 + count, force with a fully scanned cache still runs, plus the earlier planted-ticker test. |
| 2 DEFAULT_HAC_LAGS unpinned | fixed | `test_default_hac_lag_is_six_months`; CLI end-to-end asserts `att["hac"]["lags"] == 6` and both regressions' `hac_lags == 6`. Rule is in the regression.py docstring (fixed half-year; Newey-West plug-in floor(4(T/100)^(2/9)) = 4 at T=173, so 6 is the more conservative). |
| 3 README blend wording | fixed | "value on HML and RMW; the blend on HML and Mom". |
| 4 handoff alpha SE | corrected | From the JSONs, alpha HAC SE %/yr: FF5+Mom 1.92 / 1.59 / 1.34 (momentum / value / blend); CAPM 2.74 / 2.24 / 1.85. So t >= 2 needs roughly a 3-4 pp FF5+Mom alpha (5-5.5 pp on CAPM), not ">5 pp" and not "~2.5". Conclusion unchanged (no alpha is significant; the sample is too short to detect anything under ~3 pp). The HANDOFF.md sentence about the Norgate/power point should read with these figures. |
| 5 `_refresh` atomic | fixed | `KenFrenchProvider._refresh` downloads BOTH files and parse-validates them in memory first; only then writes each via temp name + `os.replace`. Tests: a failing second download leaves every cache file byte-identical and the loaded vintage unchanged; an unparseable payload does not replace the cache. |
| nit spy_calibration "run" field | left | Harmless; the field names the source run dir the series was read from. |

## Side fix (needed by item 1)
`tests/test_cli_paper.py`: two tests patched `quantlab.backtest.engine.build_backtest_providers`, but `paper/runner.py` binds the name at import, so the fake only took effect when the test was the first to import the runner. In the full suite the real provider ran and cached a ticker into the tmp cache, which the (now unconditional) scan check correctly refused. They now patch `quantlab.paper.runner.build_backtest_providers` like their neighbours. Test-only.

## Verification
`uv run pytest` default tier: 990 passed, 102 deselected, 90.77 s (pytest's own timer), on BATTERY (BatteryStatus 1, ~1.4 GHz clock), other agents idle-ish; not an AC-quiet measurement (a prior run today took 135 s). `uv run ruff check` and `ruff format --check` clean (147 files). `-m network tests/test_factors.py`: 1 passed.
