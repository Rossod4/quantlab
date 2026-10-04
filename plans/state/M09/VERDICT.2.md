VERDICT: ACCEPT

M09 quant gate, cycle 2. Branch `m09-end-to-end`, HEAD 73b351e, tree clean at start and at finish (apart from this file and QUANT-NOTES.md). Changes judged: `git diff a001d03..HEAD`, answering VERDICT.md through HANDOFF.3.md (REVIEW.3 APPROVE). I re-checked every closure against the repository myself, not against the handoff. Both cycle-1 blockers and both required items are closed. Three non-blocking items are carried forward (section C).

## A. Measured

- Power: on battery (BatteryStatus 1, 27%).
- `uv run pytest -q`: exit 0, 2m20s wall including `uv` start-up. My mutation runs below overlapped it, so this is not a budget figure; the developer reports 51.69 s by pytest's own timer, also on battery.
- `ruff check` clean; `ruff format --check`: 137 files formatted.
- No os error 4551.
- `git diff a001d03..HEAD -- src/quantlab/backtest src/quantlab/data src/quantlab/strategies` is empty. No numerics moved, and the committed cards are untouched.
- Every mutation below was reverted. `git status --short` was clean before this file was written.

## B. Cycle-1 findings: re-verified

1. **Momentum reconciliation: CLOSED.**
   - I re-ran `plans/state/M09/recon_tables.py`; it is read-only (only `open()` reads, no writes).
   - Output: grid point (12, 50) 16.2899% / 0.9906 / -20.0879%, hash 9d6aa6d258; headline 17.6532% / 0.9783 / -23.2508%, hash d02dafe6e9. Both match my cycle-1 numbers.
   - README "Reconciliation" now says "It is not the same strategy". It shows the three-row table, puts portfolio size first as the dominant mechanism (+1.36 pp CAGR, -3.16 pp drawdown) and states the residual (~0.6 pp / 0.4 pp) against SPY's +0.3 pp and quarantine's -0.18 pp. "Not decomposable" is applied only to that residual.
   - HANDOFF.md:11 matches. EVIDENCE.md section 5 holds the table, the hashes and the command.
   - A grep for remaining "SAME strategy" claims finds none (the remaining "SAME" hits are about share terms, or the value section's correct "SAME parameters").
2. **Value September→final attribution: CLOSED.**
   - The script reproduces the three-way table exactly: 13 Sept 17.62% / 0.9747, 25 Sept 17.49% / 0.9701, final 17.19% / 0.9493, with the sub-periods as in VERDICT.md.
   - 13 vs 25 Sept differ in 172/173 periods; 25 Sept vs final in 39, the first on 2021-09-30. The script also lists the 66 late fundamentals files.
   - README marks 13→25 Sept "NOT quarantine" and "UNRESOLVED", names both candidates (dirty-tree code; 66 fundamentals files first written 23-24 Sept), and confines "consistent with quarantine" to 25 Sept→final while noting that code moved there too.
   - The phrases "lines up", "strongest evidence", "same code path" and the "6.5 h re-run" claim are gone.
   - **Gate ruling on the developer's open question:** leaving 13→25 Sept unresolved is ACCEPTABLE. It concerns a superseded run from a dirty tree, not a published number. Every published value figure comes from clean dc5356d on the current cache, and the verdict is REJECTED on hard gates that do not depend on it. A ~7 h clean re-run is not justified now. The reproducibility gap behind it is carried (C1).
   - Wording nit, not blocking: "that is the only window in which the 36 contaminated series could matter" overclaims. BMC and COL are contaminated from 2012. The supportable statement is "the only window where removing them changed the series". Carried (C3).
3. **Drift timing convention: CLOSED.**
   - `drift.py` now reports `timing_gap_bps` (open of `assumed_fill_session` vs the decision-bar close) and `execution_gap_bps` (fill vs that open).
   - `assumed_fill_session` selects the open. A missing session, a missing price-asof entry or a missing/zero bar gives no figure and a `gaps_not_computed` reason, never 0.
   - Intervening split: `_split_between` reads the shared actions path for (decision date, fill session], so a split or unreadable actions gives no figure.
   - Mutations, each failing ≥1 test in `tests/test_drift.py`:

     | Mutation | Result |
     |---|---|
     | unreadable actions treated as computable | killed |
     | split check disabled | killed |
     | timing gap computed from the fill price | killed |
     | open taken from the decision date | killed |
     | split window made inclusive at the decision date | killed |

   - Residual, non-blocking: an ex-dividend date between the two sessions still lands inside `timing_gap_bps` as a raw-price drop. That is honest for a raw-price buyer, but it is not the backtest's total-return basis. Carried as a one-line doc item (C2).
4. **Blend N wording: CLOSED.**
   - README:254-263 and HANDOFF.md:20 say 0.75, 0.50 and 0.25 are each counted twice, and that the endpoints enter the blend family only through the historical rows.
   - They also state that series-less rows raise N but not the trial variance, so the count is conservative. That matches `registry.var_sr_trials`.
   - The ranking paragraph now calls tau=1.0 weak evidence and gives the reason.
5. **Ranking-check comparability: CLOSED.**
   - A child param missing from provenance is now refused.
   - Vintage (`quantlab_git_sha`, `dirty`, `actions_cache_fetched_at`, `quarantined_count`) is compared and disclosed in `ranking_agreement.vintage_mismatches` and on the report line. Disclosing rather than refusing is the right call: a different-vintage child is still the same strategy on the same window, and the reader can now see it.
   - Mutations: missing-param check disabled → killed; vintage not collected → killed.
6. **`ttm_eps_split_factor` with sign-mixed components: LEFT, ACCEPTED.** It is provenance-only and no code reads it (re-grepped). `ttm_eps` itself is correct for sign-mixed components (cycle-1 probe: -1.0). It stays carried for whoever next touches the restatement.
7. **Promotion gate vs an unscanned cache: CLOSED.**
   - The card gains `unscanned_cached_tickers_count` = never-scanned minus no_data-suppressed names. `find_promoting_report_card` refuses anything but exactly 0, including None, and `run_once` names the refused cards in its message.
   - The provenance keys exist on real runs: on `reports/momentum_12_1/provenance.json`, never_scanned 168, no_data 168, difference 0. So a real scanned-cache run would pass the gate rather than be refused by key-name drift.
   - Mutations:

     | Mutation | Result |
     |---|---|
     | accept None | killed |
     | gate disabled | killed |
     | no_data exclusion removed | killed |

   - Residual: the count is a snapshot taken at validation time. A later cache rebuild, which this project has seen wipe quarantine, would not be noticed by `paper run` at trade time. Carried (C4).
8. **value_composite.yaml header: CLOSED.** It no longer says "quarterly" and names month_end and the predecessor's quarterly sweep. The strategy id is unchanged.
9. **Suite time: LEFT, ACCEPTED.** All measurements so far are under load or on battery. The developer's 51.69 s and the reviewer's 86 s on AC are inside the 90 s budget, and no new slow tests were added. It stays carried until a quiet-AC measurement exists.

## C. Carried (non-blocking)

- **C1.** Fundamentals-cache vintage is not in provenance. Actions have `actions_cache_fetched_at`, prices have scan and quarantine state, and EDGAR facts have nothing. That gap is exactly why the 13→25 Sept value movement could only be inferred from file mtimes. Record a fundamentals fetched-at range (min/max per run universe) in provenance, and add it to `netted_grid._VINTAGE_KEYS`.
- **C2.** `docs/paper-trading.md` section 7 / the drift docstring should say that an ex-dividend date between the decision close and the fill-session open is included in `timing_gap_bps` (raw prices).
- **C3.** README value section: reword "the only window in which the 36 contaminated series could matter" to "the only window where removing them changed the series".
- **C4.** Before the first real promotion, `run_once` should check the CURRENT cache's scan coverage for the declared universe, not only the card's validation-time count. Cards can outlive a cache rebuild.
