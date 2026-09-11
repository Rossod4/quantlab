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
"""

from __future__ import annotations

DATA_SEMANTICS_VERSION = "m03b"
