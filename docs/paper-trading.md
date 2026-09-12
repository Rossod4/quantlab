# Paper trading

QuantLab's paper-trading system runs a strategy that has already been
validated (`quantlab validate --full`, verdict `ELIGIBLE_FOR_PAPER`) against
a paper broker on a schedule. **It never touches a live account.** The
Alpaca adapter (`src/quantlab/paper/alpaca.py`) always constructs its client
with `paper=True` and additionally asserts the resolved endpoint is Alpaca's
paper URL before doing anything else - there is no code path in this
platform to a live endpoint, and no flag turns this into live trading.

## 1. Get a promoted strategy

Before `quantlab paper run` will do anything (short of `--force-research`,
see below), you need a `report_card.json` somewhere under
`platform.yaml`'s `reports_dir` with verdict `ELIGIBLE_FOR_PAPER` for your
strategy:

```
quantlab backtest --config configs/backtests/momentum_12_1.yaml --out reports/bt/momentum
quantlab validate --result reports/bt/momentum --out reports/validate/momentum --full
```

Check the printed verdict. Only `ELIGIBLE_FOR_PAPER` unlocks paper trading.

## 2. Alpaca paper account setup

1. Create a free account at https://alpaca.markets and generate **paper**
   API keys (Alpaca dashboard -> Paper Trading -> API Keys). Do not use live
   keys anywhere near this platform.
2. Install the optional paper-trading dependency:

   ```
   uv sync --extra paper
   ```

3. Set the two environment variables QuantLab reads credentials from -
   **never** put these in a config file or commit them:

   PowerShell (persists for your user account):

   ```powershell
   [Environment]::SetEnvironmentVariable("ALPACA_API_KEY", "<your paper key>", "User")
   [Environment]::SetEnvironmentVariable("ALPACA_SECRET_KEY", "<your paper secret>", "User")
   ```

   Or for the current session only:

   ```powershell
   $env:ALPACA_API_KEY = "<your paper key>"
   $env:ALPACA_SECRET_KEY = "<your paper secret>"
   ```

## 3. Try it with `--dry-run` first

`--dry-run` builds the exact same decision context and rebalance plan a real
run would, but never calls `broker.submit()` - nothing is sent anywhere:

```
uv run quantlab paper run --strategy configs/strategies/momentum_12_1.yaml --broker mock --dry-run
```

This prints the planned buy/sell orders (or "no orders" if the current mock
account is already within every drift band). Once you're ready for a real
paper run:

```
uv run quantlab paper run --strategy configs/strategies/momentum_12_1.yaml --broker alpaca
```

## 4. Schedule it (Windows Task Scheduler)

This platform is EOD/monthly, not intraday - schedule the run for the first
trading session after each month-end, after the US market closes (16:30
America/New_York = 21:30 UK time, ignoring DST edge days - check the actual
session close on the day). A `schtasks` example (adjust paths and the
Python/uv location for your machine):

```powershell
schtasks /Create /TN "QuantLab Paper Trading" /SC MONTHLY /D 1 /ST 21:35 ^
  /TR "C:\Users\<you>\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe run --directory C:\path\to\quantlab quantlab paper run --strategy configs/strategies/momentum_12_1.yaml --broker alpaca"
```

`/D 1` schedules the 1st of the month; since the 1st is not always a trading
day, the runner's own `--asof` resolution (see below) always steps back to
the last real, fully-closed NYSE session regardless of which calendar day
the task actually fires on - a task firing on a weekend or holiday, or a
few days into the month, still resolves to the correct prior session, not a
partial or future one. Running it more often than needed is harmless: a
day with nothing to do (already within every drift band, or the same
`client_order_id`s already filled) produces an empty or duplicate-safe
order list.

Environment variables set via `setx`/`[Environment]::SetEnvironmentVariable`
(User scope) are visible to a Task Scheduler task run as the same user;
variables set only in an interactive PowerShell session are not.

## 5. What a `ReconcileError` means and how to clear it

Every run (after the first) compares the broker's actual account against
what the journal's last TRADED (or re-baselined - see below) run expected
it to be, ROLLED FORWARD through any dividend/split the platform's own
corporate-actions data knows about between those two dates
(`paper/reconcile.py`'s `roll_forward_expected`). An ordinary dividend or
split paid inside the paper account is therefore explained automatically -
the record's `reconcile_report.applied_adjustments` lists exactly what was
credited/restated - and does NOT refuse the run. If cash or a position
still disagrees beyond tolerance (`ReconcileTolerances`, default $1 cash /
1e-6 shares) after that adjustment, the run refuses to trade and raises
`ReconcileError` - printed by the CLI and recorded in the journal with
`refused_reason` set. This is not a bug to route around; it means the
platform's own belief about the account no longer matches reality for a
reason it could not explain, and trading on top of that belief would
compound whatever caused the mismatch. Common causes of a GENUINE refusal
(the ordinary corporate-action case above no longer reaches here):

- **A manual trade or transfer** was made in the Alpaca paper account
  outside this platform.
- **A previous run crashed** between submitting orders and journaling the
  result (rare, since the journal is written after `broker.submit()`
  returns, but always possible before that).
- **A corporate action this platform's actions provider does not carry**
  (or could not fetch for the affected ticker at reconcile time) changed
  share counts or cash the roll-forward could not explain.

**To clear it:** inspect `quantlab paper status --strategy <yaml>` and the
raw journal (`quantlab paper journal --strategy <yaml>`, or the JSONL file
directly under `reports_dir/paper/<strategy_id>/journal.jsonl`) alongside
the Alpaca dashboard's actual positions/cash. Once you understand and are
comfortable with the discrepancy, run:

```
uv run quantlab paper rebaseline --strategy configs/strategies/momentum_12_1.yaml --broker alpaca --reason "<what happened, in your own words>"
```

This is the explicit, human-approved escape hatch: it never trades, it
writes one loud `kind: "rebaseline"` journal record that accepts the
broker's CURRENT account as the new baseline and records the diff against
what was previously expected (`--reason` is required and is stored
verbatim), and the next ordinary `quantlab paper run` reconciles cleanly
against it. There is deliberately no AUTOMATIC "accept the new reality"
command beyond the corporate-action roll-forward above - a human decides,
and that decision is always on the record. If the mismatch is severe (e.g.
the account was reset or heavily hand-edited), `rebaseline` still works;
closing and recreating the Alpaca paper account is only needed if you also
want a genuinely fresh account, not just a fresh baseline.

## 6. `--force-research`

`quantlab paper run --strategy ... --broker alpaca --force-research`
bypasses the promotion gate (no `ELIGIBLE_FOR_PAPER` report card required)
so you can test the plumbing - broker wiring, rebalancing, reconciliation,
journaling - on a strategy that was REJECTED or never validated at all. The
journal records `force_research: true` and a `known_caveats` entry stating
the gate was bypassed, on every such run, so it can never be mistaken for a
genuinely promoted run when reviewing history later. **Never use this for a
strategy you intend to actually trust with money, paper or otherwise** - it
exists purely to let a developer exercise the runner's non-signal machinery
independently of validation status.

## 7. Timing convention

The runner decides using the last COMPLETED session's close (never today's
still-open one - see `resolve_asof`) and submits market orders, which fill
at whatever the broker actually does - assumed, for planning and for M09's
drift comparison, to be the NEXT session's open. That is roughly one and a
half sessions later than the backtest's own `close`-mode convention, which
acts and fills on the SAME session's close for the same nominal rebalance
date. This is expected and is not a bug to chase: a real market order
placed after a session has closed cannot fill at that session's own close.
Every journal record carries `assumed_fill_session` (the ISO date this
convention implies) precisely so M09's forward-vs-backtest drift check can
model the lag explicitly rather than misattributing it to strategy drift.

## 8. Data degradation and coverage

The runner builds its decision context through the SAME per-ticker
data-availability filter the backtest engine uses: a ticker whose
corporate-actions probe fails is dropped from `ctx.universe()` before the
strategy ever sees it (journaled under `dropped_tickers`/`dropped_fraction`),
and the run refuses to trade - loudly, journaled, never a partial or
concentrated book - if more than 5% of the raw membership fails that probe
in one cycle (matching `BacktestConfig.max_dropped_fraction`'s own default;
override via `PaperRunConfig` if you call `run_once` directly). A name the
strategy itself could not score (e.g. a missing lookback price) is recorded
under `unscored_tickers` - both fields exist so you (and M09) can tell a
data outage from a genuine signal change, rather than reading either as
silently absorbed into "the strategy chose not to hold this."

## Guarantees

- No environment variable other than `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` is
  ever read for credentials, and neither is ever written to a config file,
  log line, or the journal.
- `AlpacaPaperBroker`'s constructor raises `NotPaperAccountError`
  (`core/errors.py`) rather than ever proceeding against a resolved
  non-paper endpoint.
- The runner's decision context is built through the exact same shared
  helper (`backtest.context.build_decision_context`) the backtest engine's
  own `run_backtest` calls - including the per-ticker data-availability
  filter and its abort threshold, and a blend strategy's per-child context
  guard (`set_context_factory`) - so a strategy's paper targets match what
  the same strategy would have done in a backtest on the same data, not
  only on a clean fixture. No second, paper-specific signal implementation
  exists to drift out of sync with the backtested one.
- `run_once` always appends exactly one journal record for a scheduled
  cycle. This is a STRUCTURAL guarantee, not a list of anticipated failure
  modes: one outer catch wraps the whole cycle and journals ANY `Exception`
  that reaches it - a strategy bug (an under-declared blend child, say)
  is recorded exactly like a promotion-gate refusal, a reconciliation
  mismatch, an exhausted actions-cache refresh, data degradation, or an
  order planning/submission failure - and the journaling step itself
  (`broker.account()`) is guarded too, so an unreachable or unauthenticated
  broker (an expired key, an API outage) still leaves a record rather than
  being the one failure that slips through the guarantee meant to catch
  it. No exit path crashes without leaving a record, and the record names
  both the exception class and which stage
  (`context`/`targets`/`reconcile`/`plan`/`submit`) it happened in. This
  guarantee is deliberately scoped to `Exception`, not `BaseException`: a
  `KeyboardInterrupt` (an operator's own Ctrl-C) is never caught or
  journaled, so an interrupt is never delayed and no record is ever
  written from a partially unwound stack where the runner genuinely does
  not know what reached the broker - a process killed outright by a
  scheduled-task manager leaves no Python exception at all, so this only
  ever matters on an interactive run where the human already knows what
  they did.
- A held position with no available current price (a delisted or otherwise
  unpriceable ticker) is force-exited rather than crashing the run, and the
  reason is journaled under `forced_exits`.
- A resting order left open by a prior cycle is canceled before the next
  cycle plans (`cancel_open_before_plan`, default on) and any still-needed
  remainder is resubmitted under a genuinely new order id - a duplicate or
  replayed outcome is always reported as such (`DUPLICATE`), never
  misreported as a fresh fill.
