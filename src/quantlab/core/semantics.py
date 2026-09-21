"""Data-semantics versioning (M03b verdict carried item 11 / M04 packet).

`strategy_id` (strategies/base.py) hashes a strategy's own validated params;
it does NOT encode anything about what the PLATFORM's data layer does with
those params (e.g. the M03b share-terms restatement changed `fundamentals()`
output for split-spanning names without changing any `strategy_id`). The M06
multiple-testing trials registry must key on `strategy_id` PLUS this version
string, or a pre-/post-semantics-change rerun of the same YAML silently
collides with an earlier trial that produced different numbers.

Bump this constant whenever a merged milestone changes what a strategy sees
through `PITDataContext` (a new accessor, a changed adjustment/restatement
rule, a changed gating window) - not for pure refactors or new strategies.

Bumped to "m09" (from "m03b") for the M09 per-component TTM EPS share-terms
restatement (data/pit.py's `fundamentals()`, closing plans/QUANT-NOTES.md's
"From M03b verdict" item 1): a value/blend strategy's `ttm_eps` output can
change for a name whose TTM sum straddles a split between two component
filings, even though no `strategy_id` changes - every trial recorded under
"m03b" or earlier is a DIFFERENT data-semantics boundary from one recorded
under "m09" and the trials registry must not conflate them.
"""

from __future__ import annotations

DATA_SEMANTICS_VERSION = "m09"
