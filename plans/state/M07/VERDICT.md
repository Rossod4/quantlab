VERDICT: REJECT

Gate cycle 1 on M07 (reporting), reviewed as the referee who will read the report, not
as a code reviewer. Verification re-run against the tree as handed off (`git status
--short` identical before and after; fixture checksums unchanged; no source, test,
config or fixture file was mutated by this gate):

- `uv run pytest tests/ -q` — exit 0, ~53 s.
- `uv run ruff check .` — all checks passed. `uv run ruff format --check .` — 107 files
  already formatted.
- All three rendered fixtures: zero external `http(s)` `src=`/`href=`, 252–348 KB, no
  numpy repr, no bare `nan` outside base64 payloads.

Most of this milestone is right, and the parts that are right are the hard parts. The
three REVIEW.md blockers are genuinely closed and I re-derived the autoescape one
adversarially rather than trusting the handoff (finding 0 below). The carried-note
coverage in sections 3, 4 and 6 is close to complete and mostly verbatim. The plots are
methodologically correct. What fails is section 5's walk-forward block, where the one
table that answers "did adapting the weight beat holding a fixed one?" renders four rows
of `n/a (not available)` under the wrong labels while the real numbers sit unread in the
JSON, and where the chosen-weight sequence a binding carried item requires printed is
built into the context and rendered by neither template. A report that prints "not
available" over data it holds is the precise inverse of an honesty surface, so this is a
REJECT rather than a list of notes.

---

## 0. What I verified positively (not findings — recorded so cycle 2 need not redo it)

**Autoescape, re-derived through the real injection route.** I did not take the
handoff's word. I built an `ELIGIBLE_FOR_PAPER` report card through `build_report_card`
with `price_panel_missing_tickers=["<script>alert(1)</script>"]`, which is the actual
route `cli.py`'s `validate --full` uses to put vendor-sourced ticker symbols into
`report_card.py:891-925`'s capacity gate reason, and confirmed the payload reaches the
gate `reason` string. Rendered:

| surface | result |
|---|---|
| hostile ticker raw in HTML | absent |
| hostile ticker escaped in HTML (`&lt;script&gt;alert(1)&lt;/script&gt;`) | present |
| HTML still closes `</html>` | yes |
| hostile ticker raw in markdown twin | present (correct — plain text, see finding 8) |

Separately, through `provenance`: a hostile YAML param
(`{"lookback_months": "<img src=x onerror=alert(2)>"}`) and a hostile
`known_caveats` entry (`<h1>hostile caveat</h1>`) both render escaped in HTML and raw in
markdown. The Markup allowlist in `context.py:48-109` is correctly scoped — every entry
is a fixed hand-written literal, none is built from `result.provenance` or `report_card`.
Design accepted.

**Execution-mode note is truthful.** `EXECUTION_MODE_NOTES["next_open"]` claims returns
are measured open-to-open on an adjusted basis. I checked this against the engine rather
than against the packet: `backtest/engine.py:140-153` and `:949-951` confirm the
`next_open` return basis is the adjusted OPEN, so the ledger and the return series agree
about when the position started. The sentence the report prints is true of the shipped
engine. Rendering it with `execution: next_open` in the config produces the correct
sentence (verified live — see finding 6 for why no fixture shows it).

**Plots.** Gross dashed / net solid / benchmark neutral grey, log-scale equity (old
repo's own default and rationale), drawdown signed negative and filled downward,
Monte Carlo fan labelled "5th-95th pct" with median and observed distinguished,
sensitivity base point starred and NaN cells annotated rather than blank. I opened the
PNGs, not just the code. `plot_universe_size` being a portfolio-size proxy is disclosed
at the module docstring and the plot is titled "Portfolio size over time", not
"Universe size" — honest.

**Carried items confirmed closed:** coverage-bound definition verbatim beside the number;
separate-selection-effects note; `known_caveats` verbatim; rolling first-return-blind
convention beside every rolling table; `no_cliff_score` never described as quality and
printed only beside `min_net_sharpe` with `nan_points`/`neighbourhood_size`/
`neighbourhood_truncated`; DSR non-monotonicity beside the DSR badge; N deduplicated /
raw / dirty side by side; K and common-period count on both RC and SPA; RC/SPA benchmark
source; measured over-sizing, correctly block-length-gated so it is never misattached to
a run at a different `block_len`; the two M06 informational sentences on exactly the two
right gates; Sharpe/Sortino ddof conventions beside Sortino; the distinct DSR-NaN
"registry too thin" reason; capacity spread percentiles; the capacity trivial-pass
sentence; the dirty-tree badge. `missing_forward_prices` is correctly absent from the
report (M04/M05 carried item: never quote it as a second corroborating number) —
DISCHARGED.

---

## Blocking findings

### 1. The walk-forward comparison table reads the JSON with the axes transposed, so it renders four rows of `n/a` under metric names instead of one row per grid point

**Risk.** This is the table that gives the walk-forward its apples-to-apples baseline —
"did adapting the weight beat just picking one and holding it?" It renders as a
well-formed table whose row labels are `Annualized Volatility`, `CAGR`, `Max Drawdown`,
`Sharpe Ratio` and whose every cell is `n/a (not available)`. A referee reads that as
"these figures could not be computed", a data gap. They exist; they are in the card JSON;
the report simply asks for them by the wrong key. Presenting held data as unavailable is
worse than omitting the table.

**Evidence (reproduced, not inferred).** `WalkForwardResult.comparison` is built at
`src/quantlab/validation/walk_forward.py:200-206` as `pd.DataFrame(columns)` where
`columns` is keyed by grid-point label and each value is a `standard_metrics` series —
so the DataFrame's **index is the metric names** and its **columns are the grid points**:

```
                       Walk-Forward  ...  Fixed 100% momentum/0% value
CAGR                       0.050675  ...                      0.054505
Annualized Volatility      0.058532  ...                      0.094345
Sharpe Ratio               0.851644  ...                      0.517643
Max Drawdown              -0.112313  ...                     -0.171494
```

`to_json` at `walk_forward.py:103` serialises `self.comparison.to_dict(orient="index")`,
giving `{metric: {grid_point: value}}` — keys `['CAGR', 'Annualized Volatility',
'Sharpe Ratio', 'Max Drawdown']`. `context.py:466` then does
`for label, row in walk_forward["comparison"].items()` and reads `row.get("CAGR")` etc.,
i.e. it assumes `{grid_point: {metric: value}}`. Every lookup misses.

Rendered output from a real `walk_forward_blend` (10 steps, 2 children, 5 grid points)
pushed through `build_report_card` → `render_report`:

```
| Grid point | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| Annualized Volatility | n/a (not available) | n/a (not available) | n/a (not available) | n/a (not available) |
| CAGR | n/a (not available) | n/a (not available) | n/a (not available) | n/a (not available) |
| Max Drawdown | n/a (not available) | n/a (not available) | n/a (not available) | n/a (not available) |
| Sharpe Ratio | n/a (not available) | n/a (not available) | n/a (not available) | n/a (not available) |
```

**This is live, not latent.** `cli.py:177-187` builds a real `WalkForwardResult` via
`_build_walk_forward_result` and passes it to `validate_basic`/`build_report_card`
whenever a child result is supplied, which is exactly the blend case M06 carried item 2
is written about.

**Why no test caught it.** `tests/test_report_context.py:338-353` is the only
walk-forward context test, and its `comparison` fixture is a hand-written dict in the
shape `{"(0.5, 0.5)": {"CAGR": ..., ...}}` — the shape `context.py` assumes, not the
shape `WalkForwardResult.to_json()` produces. The test certifies the bug. No
`_report_fixtures.py` verdict supplies a walk-forward at all, so no rendered fixture
exercises the path either.

**Required remedy.** Read the comparison with the axes as `to_json` actually emits them
(one row per grid point, transposing at the boundary), and replace the hand-written
`comparison` dict in the context test with one produced by a real
`walk_forward_blend(...).to_json()`, so the fixture can never again disagree with the
producer. Add a walk-forward-bearing verdict to `_report_fixtures.py` (or a fourth
rendered fixture) so section 5's walk-forward block is rendered by the acceptance suite,
not only by a unit test.

### 2. The chosen-weight sequence is built into the context and rendered by neither template

**Risk.** M06 carried item 2 is binding through the packet's own "Carried from the M06
verdict" section: "retain and print the per-step training Sharpes ..., **the
chosen-weight sequence**, and the ranking-agreement line". The sequence is the whole
point of the walk-forward honesty check — a reader needs to see that the chosen weight
flipped 0.75 → 0.0 → 1.0 across steps, not just a summary fraction. It appears in the
report only as a PNG. In the markdown twin that PNG is an external sibling file, so the
sequence exists as text in neither format and is not diffable in git, which the packet's
goal statement names as a reason the markdown twin exists at all.

**Evidence.** `context.py:453-464` builds `chosen_rows` (one entry per step, weights
formatted `label=0.50`) and `context.py:478` puts it in the context;
`test_report_context.py:362` asserts it. Neither `report.html.j2` nor `report.md.j2`
contains `chosen_rows` — grep returns hits only in `context.py`. The rendered
walk-forward block I produced shows the no-embargo note, the ranking-agreement line, the
training-Sharpes note, the stability reason and the plot, and no weight numbers.

**Same root cause, same fix needed:** `_sensitivity_section` likewise builds
`surface_rows`, `base_point` and `param_axes` (`context.py:433-443`) and no template
renders any of them, so the sensitivity surface's actual values, the base point's
coordinates and which cells are NaN exist only inside the heatmap PNG. The `nan_points`
count is printed, which partly covers it; the surface itself is not.

**Required remedy.** Render `chosen_rows` as a table in both templates. Do the same for
`surface_rows` with the base point marked in text, or delete the unused context keys —
but a key that a test asserts and no template renders is a trap for the next milestone
either way.

### 3. Carried M06 item 4 is half-implemented: the old repo's $95M–$335M capacity range is nowhere in the report

**Risk.** The packet's binding text: "`intended_capital_usd` is printed with the capacity
ceiling **and the old repo's own $95M–$335M range for context**; at Alex's retail stake
the capacity gate is trivially passable and the report must say that plainly rather than
let a green badge imply an edge." The second half is done well — the capacity gate reason
carries the trivial-pass sentence verbatim in spirit. The first half is missing, and it
is the half that tells a reader whether this platform's capacity estimate is in the same
universe as the one the old repo measured on real data. Without it, an AUM ceiling of
`$2,000,000,000` on a synthetic fixture has no reference scale at all.

**Evidence.** `context.py:348-356` builds `capacity_detail` from spread percentiles,
ceiling min/max, assumption count and ticker count. Grepping the whole reporting package,
both templates and all three rendered fixtures for `95`/`335` returns nothing; the only
in-tree occurrence is `src/quantlab/validation/capacity.py:6`'s module docstring.

**Required remedy.** Print the old repo's $95M–$335M reference range beside the AUM
ceiling range, sourced from a named constant rather than a literal typed into the
template, with the assumption it was measured under (50-name book) stated, so a reader
knows it is a reference point and not this run's output.

---

## Non-blocking findings (fix in cycle 2 if cheap; otherwise carried to M09)

4. **A trust-panel number carries no caveat, and the caveat it needs already exists.**
   The trust panel prints "Rebalance dates with unscored names" as a bare count beside
   the coverage bound and the forced-exit count, framed as a selection effect. The M06
   cycle-3 verdict measured what that flag actually holds on the real run: 173 rebalance
   dates carrying 467–476 names each against 30 holdings, roughly 82,000 entries — it is
   recording "not selected", not "could not be scored" (`QUANT-NOTES.md`, M06 cycle-3
   block). On a real run this row will read `173` and a referee will read it as "173
   dates had unscoreable names". The upstream fix is not M07's, but the caveat beside the
   number is exactly M07's job, and the packet's own section-3 bar ("every caveat next to
   the number it qualifies") demands it. Add a one-line qualifier, or drop the row until
   the flag means what its label says.

5. **`inf` renders bare.** The `REJECTED` fixture prints "min track-record length inf",
   gate value `inf`, and "needs >= inf observations for significance". Carried item 6
   covers NaN → `"n/a (reason)"` but `_num` (`context.py:122-124`) passes infinity
   straight through `f"{v:.2f}"`. "min track-record length inf" tells a reader nothing;
   "n/a (no track record length attains significance at this Sharpe)" tells them the
   actual finding. Low severity, one line.

6. **Acceptance criterion 3 does not actually cover section 6's carried sentence.** Every
   fixture in `_report_fixtures.py` leaves `execution` unset, so
   `test_render.py:100-106` asserts only the "execution mode not recorded in the
   backtest_config for this run" fallback. The M04 carried note — which price the entry
   is measured at — appears in no rendered fixture and no rendering test. I verified by
   hand that the `next_open` sentence renders correctly when the key is present, so this
   is coverage rather than behaviour, but the criterion reads as satisfied when it is not.
   Give one fixture a fully populated `backtest_config`.

7. **Plot failures are swallowed silently.** `render.py:152-220` wraps every plot in a
   bare `except Exception` and sets the slot to `None`; the template then omits the
   section entirely. A crashed plot and a legitimately absent one are indistinguishable
   to the reader. Record the failure and print a one-line "plot unavailable: <reason>"
   rather than letting the page close over it.

8. **The markdown twin is plain text by contract, and a hostile ticker survives into it
   raw.** Correct within the report's own contract and correctly reasoned in
   `render.py:70-75`. Worth one sentence in the module docstring anyway: if someone pipes
   `report.md` through a markdown renderer that passes inline HTML, the payload becomes
   live. The HTML twin is the safe artifact; the markdown one is safe only as text.

9. **`_synthesize_report_card_from_basic` labels an arbitrary flag as the untrusted
   fraction.** `render.py:126` sets `"untrusted_fraction_line": flags[0] if flags else ""`
   — the first flag in the list, whatever it happens to be, printed under the
   untrusted-fraction slot in the trust panel. On the basic-only path that will
   eventually mislabel something. Select the flag by content or leave the line empty.

10. **No legend for what a verdict or a soft gate means.** The header shows a green badge
    reading `ELIGIBLE_FOR_PAPER` above "net CAGR 43.10%, Sharpe 5.15, max drawdown 0.00%".
    Nothing in the report says that the verdict means "cleared the platform's gates for
    paper trading" and not "has an edge", and nothing says a soft-gate failure caps the
    verdict rather than rejecting it. The gate table's `Kind` column is the only signal.
    The capacity gate already models the right behaviour with its own "this is not
    evidence of edge" sentence; the verdict badge deserves the same treatment. This is the
    single highest-leverage honesty sentence still missing from the page.

11. **The Monte Carlo fan's seed is hardcoded.** `cli.report` never passes `config`
    (`cli.py:501`), so `_monte_carlo_seed(None)` returns `1` (`render.py:78-85`). That
    matches `configs/validation.yaml:114` today, so the fan currently is the same draw as
    the quoted percentiles — but if that seed is ever changed the fan silently becomes a
    different draw sitting under the percentile line, with nothing on the page saying so.
    Pass the loaded validation config through, or caption the fan.

12. **Cosmetic.** The coverage-bound/selection-effects sentence prints twice (trust panel
    and again under Robustness → Flags). The markdown twin carries HTML entities
    (`&middot;`, 8 per report) rather than plain separators. `Sortino n/a (not available)`
    gives a generic reason where "no losing periods" is the real and more informative one.
    The rolling table dumps every window row (50 in the fixture, ~130 on a 12-year book)
    with no truncation.

---

## Recommendation

REJECT, one more loop iteration. Nothing here is a design error and nothing needs
escalating to Alex: findings 1 and 2 are a wiring fault and an unrendered context key,
finding 3 is a missing constant. The statistical content, the caveat coverage, the
escaping design and the plots are sound and should not be reopened. Cycle 2 should fix
1–3, and fold in 4, 5, 6 and 10 if they are as cheap as they look.
