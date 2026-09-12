VERDICT: ACCEPT

M06 cycle 3. The cycle-2 blocker is closed, and closed properly — the guard is
load-bearing in `reality_check.py` rather than resting on the `assert` in
`report_card.py`, which I confirmed by re-running the planted case under
`python -O`. Everything else in VERDICT.2.md's scoped list landed and is
visible in the rendered deliverable.

M06 is accepted as the platform's decision function. Four items carry forward
to M07/M09; none of them is a correctness defect and none blocks paper trading
work starting.

Verified at this tree: `uv run pytest tests/ -q` exit 0, 533 tests, ~25 s;
`ruff check` and `ruff format --check` clean (97 files). I mutated no source,
test or config file — `git diff --stat -- src/ tests/ configs/` is byte-identical
to the frozen iteration-4 tree (6 files, 965 insertions, 16 deletions). Only
`plans/QUANT-NOTES.md` and this file differ.

---

## 1. Cycle-2 blocker A — CLOSED, and the invariant is real

**The planted case, re-run verbatim.** Three strong aligned trials on
2014-01..2023-12 plus a worthless headline (per-period Sharpe ≈ 0) on an offset
2019-01..2028-12 window — the exact fixture that produced a PASSING Reality
Check hard gate at p=0.0050 for a strategy absent from its own matrix:

```
rc                         : None
RC HARD GATE               : FAIL
reason                     : "Reality Check could not be run: headline trial excluded
                              by overlap floor (retained_fraction=50%): the headline
                              trial 'momentum-head|m03b|a62b2d31a2' in family
                              'momentum' could not be retained above the 80% overlap
                              floor without removing itself - the Reality Check/SPA
                              refuse to run on its sibling trials alone."
SPA soft gate              : FAIL
headline_retained_fraction : 0.5
headline-cause caveat      : present
verdict                    : REJECTED
```

The gate now fails by the correct, named cause instead of passing on other
trials' behalf.

**The exception path, re-run verbatim.** The benchmark-constrained deadlock that
at cycle 2 discarded every exclusion reason and reported the false "fewer than 2
registered trials with a stored return series" now names the headline cause and
preserves all four exclusion sentences in `known_caveats`, including the
headline's own. `headline_retained_fraction` reads 0.5 rather than `None`.

**Brute force over the invariant.** I swept 200 layouts — headline offsets of
{0, 24, 60, 96, 120} months × headline window lengths of {24, 60, 120, 180} ×
sibling configurations {(3,120), (2,120), (5,60), (2,24), (4,180)} × both
benchmark modes (`embedded` and `zero`) — building each report card through the
real `build_report_card` and then independently reconstructing the trial matrix
to inspect its columns:

```
layouts where RC ran: 16   layouts where RC refused: 184   VIOLATIONS: 0
```

Every layout in which the Reality Check produced a non-None result had the
headline as a matrix column. My reconstruction deliberately passed
`headline_label=None`, disabling the protection, so this checks that the
survivors genuinely contain the headline rather than merely that the guard
fired.

**The headline-with-the-shortest-window case, asked for specifically.** A
24-month headline sitting inside three 120-month siblings: the siblings each
retain 20% of their own windows, fall below the 0.8 floor, and are removed; the
headline is never a candidate, so the resolver ends with one survivor and
`build_trial_matrix` refuses. `headline_retained_fraction` = 1.0, the gate FAILS
with "found 1 after alignment/exclusion (registry held 4 records with a
series)". Conservative and correctly explained — the headline is retained and
the Reality Check declines rather than running over a single column.

**The guard survives `-O`.** `report_card.py:512`'s `assert headline_label in
matrix.columns` is stripped under `python -O`. Re-running the planted case that
way still produces `rc = None` and a FAILING gate with the named headline cause,
because `reality_check.py:309` raises a real `TrialMatrixError`. The assert is
belt-and-braces over a load-bearing check, which is the right way round. I note
this only to record that the two-layer design was tested, not merely asserted.

## 2. Cycle-2 blocker A item 3 (reason kinds) — CLOSED and distinguishable in the deliverable

I constructed all three causes and read the reason out of the **rendered**
`report_card.md` gate table, not out of the exception object:

| cause | rendered reason |
|---|---|
| `too_few_trials_recorded` | "fewer than 2 registered trials in this family have a stored return series - treated as a FAILURE, not a pass by default." |
| `excluded_by_overlap_floor` | "headline trial excluded by overlap floor (retained_fraction=50%) … could not be retained above the 80% overlap floor without removing itself" |
| `no_common_dates` | "no common dates across trials in family 'momentum'." |

The fourth shape — exclusions occurred but left fewer than two survivors —
renders as "found 1 after alignment/exclusion (registry held 4 records with a
series)", which a reader can tell apart from the genuine too-few case. All four
are distinguishable without reading code.

## 3. Cycle-2 items B, C — CLOSED as disclosure

**DSR non-monotonicity.** The DSR gate reason now carries "DSR is not monotone
in N above the variance floor; near-duplicate reruns of one grid point can move
it", appended only when DSR is actually computed. Confirmed in the rendered
markdown of the shipped ELIGIBLE_FOR_PAPER CLI path. The regression test
(`test_dsr_near_duplicate_headline_reruns_move_but_stay_bounded_then_turn_back_down`)
pins both halves — that near-duplicates move DSR up, and that the movement peaks
where the `1/(n_periods-1)` floor binds and then turns back down. Using a small
n=12 fixture found by numeric probe rather than reproducing my literal
144-period numbers is the right call for suite time; it pins the same two
properties.

**Capacity trivial-pass note.** Emitted above 10× the bar and present in the
rendered report: "NOTE: the capacity gate is trivially passable at this stake
(75000x against a 100x bar) - this is not evidence of edge, only that the
resolved intended capital is small relative to the instrument's liquidity."
This discharges the half of the orchestrator's decision (d) that cycle 2 found
missing.

## 4. Cycle-2 item D (calibration test power) — PARTIALLY closed, carried

`test_white_rc_size_at_shipped_block_length_is_bounded` now measures actual size
at the gate's own 0.10 bar, at the shipped `block_len=6.0`, over 300 sims, and
the pre-existing uniformity test documents inline that it runs at
`block_len=3.0` and is a construction sanity check rather than a calibration
measurement. That is the honest framing and it is what I asked for.

The asserted band is 0.04–0.28 around a measured ~0.12. At 300 sims the standard
error is about 0.019, so the band sits roughly four standard errors below and
eight above — it will not flake, and it will catch a gross regression, but it
cannot distinguish 0.12 from 0.25, nor notice the over-sizing disappearing. The
test's own docstring says as much. Accepted as scoped.

One thing the module asks for and does not yet do: `reality_check.py`'s own
module docstring states "the gate REASON should state the measured over-sizing
rather than imply nominal calibration". Grepping `report_card.py` for any
mention of the measured size finds nothing — the RC gate reason still reads
"White Reality Check p=0.0050 against the 0.10 bar" with no hint that the bar is
nominal rather than achieved. Carried to M07, not blocking: the fact is
documented where an implementer will find it, and the direction is known.

## 5. Finding E (cosmetic markdown rendering) — untouched, as instructed

`_report_card_markdown` still uses `{gate.value!r}`, so the rendered table shows
`np.float64(1.0)` in the `no_cliff_score` row and bare `nan` for Calmar and
Sortino. Correctly left alone — it was outside this cycle's scope. Carried to
M07, which replaces this renderer anyway.

---

## What M06 ships, for the record

The decision function is sound. Every closed-form statistic was re-derived
independently at cycle 1 and matches to 0.0 absolute: PSR, DSR's `SR*` with the
Euler-Mascheroni term and both `Φ⁻¹` arguments, MinTRL (which round-trips
exactly — PSR at `n = MinTRL(c)` returns `c` to ten decimal places), the purged
split construction, White's full recentring, Hansen's consistent recentring
threshold, the stationary bootstrap's `1/L` parameter, and the Corwin-Schultz
port.

The four gate-found holes that mattered are closed: the Reality Check counts the
trials it should and always includes the strategy under evaluation; the
benchmark is a stated config choice used consistently across every gate; the
deflated Sharpe ratio's trial count is deduplicated on the return series with a
variance floor, and the one residual is disclosed on the report card itself; and
the sub-period statistic is named and described as what it is rather than as a
purged cross-validation. `ELIGIBLE_FOR_PAPER` is reachable through the real CLI
against the real config, pinned by a test that asserts zero failing gates.

The report card tells a referee what it needs: N as a number alongside the raw
key count, the realised Reality Check trial count K, the resolved benchmark, the
headline's own retained fraction, the dirty-tree provenance and dirty trial
count, the coverage-versus-selection "untrusted fraction" sentence, the
Sharpe/Sortino denominator mismatch beside the numbers, and a caveat list that
now includes an honest retraction of the earlier "over-counting N is
conservative" claim.

I have no reservations about M06 proceeding to M07.
