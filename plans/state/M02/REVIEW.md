VERDICT: REVISE

# M02 code review (iteration 1)

## Verification performed
- `python -m uv run pytest tests/ -q` → 135 passed, 3 deselected (network). Matches handoff.
- `python -m uv run ruff check` → clean; `ruff format --check` → 35 files already formatted.
- Acceptance criterion 3 (fundamentals parity) verified INDEPENDENTLY: ran the OLD repo's
  `get_point_in_time_fundamentals` (MomentumValueStrategy/src/data_layer/fundamentals.py)
  against the committed NATH fixture at asof=2022-06-01. All 7 fields match the hard-coded
  test expectations and the new module's output to full precision; the old and new
  flattened fact frames are byte-identical. Line-by-line diff of the ported extraction
  helpers confirms numerical/gating logic is verbatim (only mechanical changes:
  `_flatten_company_facts` extraction, `zip(..., strict=True)`, imports/docstrings —
  all listed in the handoff).
- Acceptance criterion 2 verified by mutation testing: temporarily removing the hard
  slice + assertion in `pit._sliced_price_panel` made canary (a) fail; temporarily
  removing the `filed <= as_of_date` gate in edgar_fundamentals made canary (b) fail.
  Both mutations reverted; full suite re-verified green afterwards. Canaries (d)/(e)
  fail-on-guard-removal by construction (column gating / fresh-call assertion).
  Canary (c) is only partially guard-coupled — see finding 2.
- Acceptance criteria 4, 5, 6 each have a direct test asserting the packet's exact
  numbers/behavior (test_survivorship.py 30%/0%, test_corporate_actions.py
  2020-06-12 DelistingEvent, test_pit.py UndeclaredDataError/LookaheadError/lookback cap).
  All pass offline and deterministically.

## Findings

1. **blocker** — src/quantlab/data/corporate_actions.py:108-113
   (`YFinanceCorporateActionsProvider.get_actions`): a download failure is permanently
   frozen into the cache as "this ticker has no actions, ever". On cache miss,
   `except Exception: cached = _empty_actions()` is followed by an unconditional
   `write_cache(cached, cache_path)`, so a single transient network error (or any
   yfinance bug — the bare `except Exception` catches everything) writes an empty
   frame that every subsequent call treats as a legitimate cache hit. There is no
   metadata to distinguish "fetched and genuinely empty" from "fetch failed". This is
   exactly the frozen-truncation hazard QUANT-NOTES' M01 note flags — which this same
   milestone builds measurement machinery for in survivorship.py — reintroduced in a
   new cache path with no measurement. It is silent data corruption today
   (`actions()` returns empty forever) and becomes price-corrupting the moment these
   events drive as-of adjustment per the handoff's own follow-up plan.
   Fix expected: on failure, return `_empty_actions()` WITHOUT writing the cache
   (matching the port precedent — edgar_fundamentals.get_company_facts returns None
   on RequestException and does not cache), narrow the except to the vendor's
   expected exceptions, and add a test asserting a failed download does not create a
   cache file (a second call re-attempts the fetch).

2. **minor** — tests/canaries/test_lookahead.py:52-65, 157-164 (canary (c)): the
   "earlier row only" guard the canary asserts lives inside the test-local
   `_TwoRowConstituentsProvider`, not in production code. The canary does prove
   `PITDataContext.universe()` forwards `asof` faithfully, and the production as-of
   lookup is separately covered by M01's test_constituents — but deleting/weakening
   the production guard (`_membership_from_table`, sp500_constituents.py:127-143)
   would not fail this canary, unlike canary (b), which deliberately wraps the real
   extraction logic for exactly this reason.
   Fix expected: have the fake delegate to the production lookup, e.g.
   `membership()` returns `_membership_from_table(self._table, asof)` (tickers
   without dots are unaffected by normalize_ticker), so the canary exercises the
   real as-of gate end-to-end.

3. **minor** — src/quantlab/data/corporate_actions.py:150-156 (`infer_delisting`):
   the packet's rule is "ticker LEFT the constituents set"; the implementation only
   checks non-membership as of `end`. A ticker that was never a member but has a
   stale price cache produces a spurious DelistingEvent. The docstring documents the
   approximation, but the cheap tightening is available with the providers already
   in hand. Fix expected: also require membership at (or near) `last_trade_date`
   before inferring, or explicitly justify the looser rule in the handoff.

4. **minor** — src/quantlab/data/pit.py:169-177 (`_sliced_price_panel`): the hard
   slice bounds rows by `<= self._asof` (a calendar date) and the lookback cap counts
   distinct *available* dates, not calendar sessions. A misbehaving provider can
   inject a non-session row (e.g. a Saturday between the last session and a weekend
   `asof`) that both passes the slice and consumes one of the N lookback slots. No
   look-ahead risk (still `<= asof`), but criterion 6's "N sessions ending at the
   last session <= asof" is only guaranteed for well-behaved providers.
   Fix expected (cheap): slice to `last_session` (already computed) instead of
   `self._asof`, or intersect `keep_dates` with the `sessions` calendar index.

## Observation on the central design decision (methodology — quant gate's call)
Mechanically, the raw-vs-`prices_for_returns()` split is implemented consistently:
the decision path is column-gated by a module-level constant, canary (e) asserts
adj_close absence adversarially, and the limitation (split discontinuities in raw
close) is documented in code and handoff as the packet requires. I found no
mechanical defect in it. Whether the escape hatch is acceptable for M03+ signal
work is the quant gate's ACCEPT/REJECT, not mine. One mechanical caveat feeding
that decision: finding 1 must be fixed before this module's events can be trusted
to drive any future as-of adjustment.

## Answers to the handoff's open questions
1. *Should corporate_actions.py's real events drive prices() adjustment in M03/M04
   once parity-tested?* The sequencing judgment (adjusted-but-unproven vs
   unadjusted-but-zero-look-ahead) is methodology — defer to the quant gate. From
   the code-review side: (a) do it as a dedicated follow-up packet with its own
   parity fixtures (hand-computed adjustment factors for a known split/dividend
   sequence), not folded silently into M03/M04; (b) fix finding 1 first — an
   adjustment replay built on a cache that can freeze transient failures as "no
   splits ever" would silently produce unadjusted prices for affected tickers;
   (c) decide in that packet whether adjusted prices change `prices()` semantics
   (a breaking behavior change for anything built on M03's frozen Strategy ABC) or
   arrive via a new accessor — don't let M03 freeze a signature that forces the
   silent-change option.
2. *`actions()` has no DataRequirements gate — intended?* It is consistent with the
   packet: the packet's DataRequirements spec lists only price lookback,
   fundamental fields, and universe membership, so no finding. But it leaves
   `actions()` as the only accessor callable with a fully-empty declaration, which
   undercuts the "declaration is honest" property requirements.py's own docstring
   claims. Recommend adding `needs_actions: bool = False` BEFORE M03 freezes the
   declaration surface — it is one line now and a breaking ABC change later. Put it
   in the M03 packet (or fold into this revision, developer's choice; not required
   for M02 approval).

## Not blocking, for the record
- Packet criterion 1 said "all four canary tests" but lists five scenarios (a)-(e);
  all five are implemented — treated the list as authoritative.
- survivorship.py is a re-specification of the old script (per-year gap % vs the
  old quarter-end coverage/return-spread analysis) — the packet defines its own
  acceptance numbers, so no old-repo numerical parity applies; implementation
  matches the packet's spec including the masked-truncation surfacing.
- `core/errors.py` change is exactly the packet-sanctioned +UndeclaredDataError.
  No M01 provider files touched, as the handoff claims.
