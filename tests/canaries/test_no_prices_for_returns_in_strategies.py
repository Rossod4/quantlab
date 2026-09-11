"""Static canary (M05 packet, carried from the M04 verdict item 5): no
registered strategy's source calls `prices_for_returns` - the accounting
path (raw OHLC + `adj_close`) that a decision context must never expose to
signal logic (CLAUDE.md invariant #1; QUANT-NOTES.md "From M02b verdict").

Superseded-but-not-removed: the M04 gate (VERDICT.2.md "Adjustments to
'From M04 verdict'") notes the accessor is now structurally unreachable
from a decision context (`PITDataContext.__init__`'s `accounting` gate), so
this AST scan is belt-and-braces, not closing an open gap - it complements
the M04 structural guard, per the packet's own framing, by catching a
`prices_for_returns()` call at the source level, on the way in, rather than
relying solely on the runtime gate.

An AST scan (not a plain grep) so a call written across multiple lines, or
via `getattr`, is still normalized to one `ast.Call` node the same way
either style would be - though `getattr(ctx, "prices_for_returns")(...)`
call sites are NOT caught (see the module-level note below); the scan
matches `ast.Attribute(attr="prices_for_returns")` and bare
`ast.Name(id="prices_for_returns")` call targets, which covers every
calling convention actually used in this codebase (`ctx.prices_for_returns
(...)` and a bound/imported bare reference).
"""

from __future__ import annotations

import ast
from pathlib import Path

_STRATEGIES_DIR = Path(__file__).resolve().parents[2] / "src" / "quantlab" / "strategies"
_FORBIDDEN_NAME = "prices_for_returns"


def _iter_strategy_source_files() -> list[Path]:
    return sorted(_STRATEGIES_DIR.rglob("*.py"))


def _calls_forbidden_name(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == _FORBIDDEN_NAME:
            hits.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id == _FORBIDDEN_NAME:
            hits.append(node.lineno)
    return hits


def test_strategies_directory_exists_and_is_nonempty():
    # Guards against the canary silently passing because the path is wrong
    # (e.g. after a package reshuffle) rather than because the code is clean.
    files = _iter_strategy_source_files()
    assert _STRATEGIES_DIR.is_dir()
    assert len(files) > 0


def test_no_strategy_source_calls_prices_for_returns():
    offenders: dict[str, list[int]] = {}
    for path in _iter_strategy_source_files():
        hits = _calls_forbidden_name(path)
        if hits:
            offenders[str(path.relative_to(_STRATEGIES_DIR))] = hits
    assert not offenders, (
        f"{_FORBIDDEN_NAME}() called from strategy source (accounting-path "
        f"accessor must never be reachable from signal logic): {offenders}"
    )


def test_canary_detects_a_planted_violation(tmp_path):
    # Mutation check: prove the AST scan actually fires, not just that it
    # currently finds nothing.
    planted = tmp_path / "hostile_strategy.py"
    planted.write_text(
        "def generate_targets(ctx, date):\n    return ctx.prices_for_returns(['AAPL'], 5)\n"
    )
    hits = _calls_forbidden_name(planted)
    assert hits == [2]
