# M06 handoff (iteration 1, updated per team-lead escalation decisions)

## Files
New: `validation/{registry,deflated_sharpe,purged_cv,bootstrap,monte_carlo,
reality_check,capacity,report_card}.py` + matching `tests/test_*.py` +
`tests/parity/test_capacity_parity.py`. Edited: `validation/basic.py`
(`BootstrapConfig`, additive), `cli.py` (`validate --full`, builds capacity
panel from cache), `configs/validation.yaml` (M06 thresholds/bootstrap),
`tests/_validation_fixtures.py` (new optional kwargs incl. `dirty`/`start`/
`end`, backward-compatible).

## References
PSR/DSR/MinTRL: Bailey & López de Prado 2012 eq. 5/8, 2014 eq. 10-11 (incl.
the `var_sr_trials == 0` case, #4 below). Purged CV: AFML ch. 7 (own
`label_horizon` kwarg, beyond the packet's literal 3-arg signature). White
RC: White 2000; Hansen SPA: Hansen 2005 eq. 16-17. Bootstrap: Politis &
Romano 1994. Capacity: verbatim port of the old repo's script.

## Escalation resolutions (this update)
1. **Dirty flag**: `registry.record_backtest` prefers
   `provenance["dirty"]` (M04b, in progress) when present
   (`dirty_source="provenance"`); falls back to `git status --porcelain` at
   record time otherwise (`"registry_at_record_time"`); historical entries
   get `"historical"`. Both branches tested.
2. **Two more soft gates**: `max_drawdown_floor` (full-sample
   `net_max_drawdown` only, never rolling) and
   `max_negative_rolling_window_fraction` (worst fraction across configured
   windows; reason states the frozen first-return-blind convention). Both
   soft - RESEARCH_ONLY at worst. The three criterion-8 fixtures needed no
   changes (strictly-positive headline already clears both); added two new
   tests exercising each gate's failure path.
3. **Capacity wired end-to-end in `--full`**: `cli._build_capacity_price_
   panel` reads held tickers from `holdings_history`, fetches OHLCV via
   `build_provider("prices", ...)` (cache-backed, offline when warm),
   converts via new `capacity.price_panel_from_long`. Missing tickers are
   named in the gate's reason (`price_panel_missing_tickers` kwarg).
   Tested with a temp cache dir + monkeypatched `_download_batch`.
4. **PSR/DSR sanity anchors**: `PSR(SR=SR*)=0.5` (already present) and
   `DSR -> PSR` at `var_sr_trials == 0` (any N, incl. N=1). Required a real
   formula fix: `deflated_sharpe_ratio` used to NaN unconditionally for
   `n_trials < 2`; now treats `var_sr_trials == 0` as SR*=0 at any N
   (avoids the `0 * Φ⁻¹(0)` indeterminate form, models "no dispersion, no
   correction needed"). `n_trials==1` with `var_sr_trials>0` still NaN
   (genuinely undefined). Full case table in the docstring.

## Still open
Sensitivity base-point vs. headline double-counting unreconciled
(deliberate, conservative for DSR). RC/SPA/capacity hard-fail on missing
inputs (confirmed correct for RC/SPA; capacity now usually populated).
Walk-forward NaN-training-Sharpe check still can't be verified from
`WalkForwardResult` alone - stated in `known_caveats`.

## Tests
`uv run pytest tests/ -q`: **exit 0, 506 dots, ~18s** (budget 90s).
`uv run ruff check`: clean. `uv run ruff format --check`: clean (97 files).
