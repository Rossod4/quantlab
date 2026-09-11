VERDICT: ACCEPT

# M04 quant gate — cycle 2

Scope: developer iteration 3 (`plans/state/M04/HANDOFF.3.md`), code review
`REVIEW.3.md`, the orchestrator decision recorded under "Orchestrator decisions" in
`plans/QUANT-NOTES.md`, and re-verification of all five cycle-1 findings plus the
orchestrator-added item 6.

Tree at gate time: 329 tests pass, ruff clean. All 74 tracked `.py`/`.yaml` files are
md5-identical to my pre-gate baseline — no repo file was mutated by this gate; every
probe ran from the session scratchpad.

All five cycle-1 findings are fixed and re-verified by re-running my original
cycle-1 reproductions unchanged against the current tree. Finding 4 is accepted on the
orchestrator's reasoning, whose factual premise I verified directly in the old repo.

---

## Cycle-1 findings, re-probed with the original fixtures

**Finding 1 — coverage bound over the universe. FIXED.** My exact cycle-1 fixture (10-name
universe, every name fully cached on disk, top-3 strategy) now reads:

```
coverage by_year: 2020    0.0
overall_bound: 0.0        (was 70.0)
```

`all_universe_tickers` accumulates the union of `ctx.universe()` across rebalances,
separate from the held set, and their union feeds `price_availability_from_cache`. The
code review's independent fixture with a never-held masked name returned 10.0, which is
the correct number for what it planted and rules out a false-clean zero.

**Finding 2 — haircut reaches the reported returns. FIXED.** Same fixture, three haircuts:

```
haircut=0.0  net_equity 1.00   ledger 1,000,000
haircut=0.5  net_equity 0.75   ledger   750,000
haircut=1.0  net_equity 0.50   ledger   500,000
```

The headline curve and the ledger now agree exactly, closing the 50%-of-capital gap the
cycle-1 probe found. Strictly monotonic in the haircut.

**Finding 3 — forced exit on the total-return basis. FIXED.** My 1-for-10
reverse-split-then-delist fixture now books `+0.0000` and a final `net_equity` of 1.0,
against the cycle-1 result of +450% and 5.5x. The keeps-trading control is unchanged at
0.0000, so the fix is in the forced-exit branch and nowhere else. The dividend fixture
still returns exactly +5.263158% in the ex-dividend period and 0.0 elsewhere — counted
once, no regression. The guard now also covers forced exits on the corrected basis,
which is the re-examination the finding asked for rather than a silent re-exemption.

**Finding 5 — `next_open` measures open-to-open. FIXED.** My cycle-1 fixture (flat open,
rallying close on the fill day) no longer leaks the fill-day intraday move into the
outgoing book: `+0.100000` became `+0.000000`. I built a sharper confirmation to rule out
a fix that merely zeroes everything — a panel whose open rises 20% and whose close rises
30% over the same two fill dates:

```
next_open period 2020-03-02 -> 2020-04-01: +0.200000
   open-to-open truth +0.200000 | close-to-close would be +0.300000
```

Genuinely open-to-open. `close` mode reduces algebraically to plain `adj_close`;
`git diff tests/parity/` is empty and all 9 parity tests pass, so the frozen numerics are
untouched.

**Finding 4 — the guard's sign behaviour on shorts. ACCEPTED as inherited parity; my
cycle-1 framing of the provenance was wrong.**

I treated this in cycle 1 as a generalisation error introduced by M04. It is not. I read
the old repo directly at `MomentumValueStrategy/src/backtest/long_short_engine.py:268-291`
and it applies the *same* upside-only guard to the short basket, with per-book counts, and
its own comment anticipates this exact hazard:

> Applying the >300% exclusion to the SHORT book too is a deliberate judgment call: the
> test is about whether the DATA is trustworthy, and a price series doesn't become more
> believable because we happen to be short it. The uncomfortable flip side — a >300%
> underlying gain, if REAL, would be a catastrophic loss to a short seller, and this
> guard would hide it — is exactly why the exclusions are counted per book and discussed
> in notebook 04's Limitations rather than buried.

So the trigger is frozen numerics under CLAUDE.md invariant #4, and changing it would
have been the invariant violation. The orchestrator's premise is correct as stated, and
the code review was right to ask for the paper trail, which now exists.

The residual hazard is real and large. My end-to-end probe on a dollar-neutral book whose
short leg squeezes +500%:

```
exclude_legacy   Mar-2020 period return  +0.0000   (truth: -2.5000)
                 extreme_returns_short=1, known_caveats: 1 entry
flag_only        Mar-2020 period return  -2.5000
                 extreme_returns_short=1, known_caveats: 0 entries
```

`exclude_legacy` hides 250% of capital. I accept it anyway, on four conditions that I
verified rather than took on trust:

1. **It is counted per book.** `extreme_returns_long`/`extreme_returns_short` populate
   correctly and survive `save`/`load`.
2. **It announces itself.** A `known_caveats` entry naming the short book fires under the
   default policy whenever `extreme_returns_short > 0`, and does not fire under
   `flag_only`. It round-trips through serialisation, so M05–M07 cannot lose it.
3. **There is an opt-out that gives the truth.** `flag_only` counts without excluding and
   returns the full −250%.
4. **No shipped configuration is exposed.** Every backtest config in `configs/backtests/`
   resolves to a long-only strategy (`momentum_12_1` twice, `value_composite`,
   `blend_50_50`). `momentum_130_30.yaml` and `momentum_ls.yaml` exist but are referenced
   by no backtest config, so the exposure is latent, not live.

This is strictly better than the old repo, which had the same trigger, the same counts,
and no opt-out. The sign-aware trigger stays a carried item against whichever milestone
first promotes a long-short strategy — see QUANT-NOTES.md.

The degenerate-book edge I raised alongside finding 4 is also closed:
`_weighted_return_excluding` returns the affected book names and the engine records them
in `quality_flags.degenerate_excluded_book_dates`, verified on a fixture where every long
is excluded.

## Item 6 — the structural accounting gate. VERIFIED, including the paths I was asked to attack

I ran a hostile strategy that calls `ctx.prices_for_returns()` on whatever context it is
handed, at every rebalance, in three positions:

| position | invocations | result |
|---|---|---|
| top-level strategy | 4 of 4 rebalances | `UndeclaredDataError` every time |
| blend child | all | `UndeclaredDataError` every time |
| nested blend grandchild (2 children) | all | `UndeclaredDataError` every time |

Twelve child invocations across the blend cases, three distinct outcomes, all raising. The
engine defines exactly one `context_factory`, passes that same closure object to
`set_context_factory`, and never sets `accounting`; only `_accounting_context` passes
`True`, and it is never exposed to a strategy. There is no path today by which a strategy
or a blend child receives an accounting-capable context.

One honest caveat, not a finding: a strategy that deliberately does
`object.__setattr__(ctx, "_accounting", True)` can still reach the accessor. I confirmed
this works. No Python guard can prevent it, it requires code that obviously subverts the
gate, and it is the same class of escape as a plugin importing a provider directly. The
canary and the structural default are the right level of protection.

## Other checks

- **Suite stability.** The code review recorded a single unreproducible canary (j) failure
  on its first run. I deleted every `__pycache__` directory outside `.venv` and ran the
  full suite three times with the pytest cache disabled: 329, 329, 329. The canary file
  alone ran clean five consecutive times. I could not reproduce it either. The mutation
  evidence (flipping the `accounting` default to `True` makes it fail) shows the canary has
  real power, so I read the one-off as a stale-bytecode artifact from the moment the tree
  was frozen. I agree with the review's recommendation of one CI run from a clean checkout
  before this ships; that is a process step, not a gate condition.
- **Parity.** `tests/parity/test_engine_parity.py` is unmodified (empty diff) and all 9
  parity tests pass, so the finding 2/3/5 formula changes are parity-neutral in `close`
  mode by test, not by assertion.
- **Serialisation.** The new `QualityFlags` fields and `known_caveats` round-trip exactly;
  `net_equity` round-trips to 0.0 absolute difference.
- **Docstrings.** The "agree to first order" claim my cycle-1 probe falsified is gone and
  now correctly attributes the ledger gap to uncredited dividends, with a direct
  instruction that M05+ compute metrics from `net_returns`/`net_equity` only. The
  `delisting_haircut` comment no longer contradicts itself on which direction is
  conservative.
- **Handoff inventory.** `src/quantlab/strategies/base.py` was changed but is not listed in
  HANDOFF.3's file inventory. The change is documentation-only and accurate, as the review
  found. Noted, not a finding.

## Left open deliberately

`quality_flags.missing_forward_prices` still duplicates `forced_exits`, and
`provenance.quantlab_git_sha` still carries no dirty-tree flag. Both were cycle-1
non-blocking notes, both remain carried items against M05/M07 and M06 respectively, and
neither was part of the five numbered findings. That is the right call for this milestone.

M04 is accepted. The engine no longer produces a result I would expect a referee to
reject on a long-only configuration, and the one remaining methodological compromise is
inherited, counted, caveated, opt-outable, and unreachable from any shipped config.
