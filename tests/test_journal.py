"""Tests for `paper/journal.py`: append-only JSONL round-trip and the
`journal_to_frame()` summary."""

from __future__ import annotations

import pandas as pd

from quantlab.paper.journal import JournalRecord, append_journal, journal_to_frame, read_journal


def _record(
    asof: str,
    strategy_id: str = "test-strat-abc",
    refused: str | None = None,
    kind: str = "run",
) -> JournalRecord:
    return JournalRecord(
        asof=asof,
        strategy_id=strategy_id,
        data_semantics_version="m03b",
        quantlab_git_sha="deadbeef",
        dirty=False,
        targets={"asof": asof, "weights": {"AAA": 0.5}, "strategy_id": strategy_id},
        planned_orders=[],
        results=[],
        account_before={"cash": 1000.0, "equity": 1000.0, "positions": {}},
        account_after={"cash": 900.0, "equity": 1000.0, "positions": {}},
        reconcile_report={
            "ok": True,
            "cash_expected": 1000.0,
            "cash_actual": 1000.0,
            "position_mismatches": [],
            "applied_adjustments": [],
        },
        promoting_report_card="reports/validate/strat/report_card.json",
        kind=kind,
        known_caveats=["some caveat"],
        refused_reason=refused,
        refreshed_actions_tickers=["AAA"],
        dropped_tickers=["BBB"],
        dropped_fraction=0.025,
        unscored_tickers={"CCC": "missing lookback price"},
        forced_exits={"DEAD": "forced exit: no price / delisted"},
        canceled_orders=[{"client_order_id": "x", "ticker": "AAA", "qty": 5.0}],
        resting_orders=[{"client_order_id": "y", "ticker": "AAA", "qty": 3.0}],
        assumed_fill_session="2024-01-16",
    )


def test_append_then_read_round_trips(tmp_path):
    record = _record("2024-01-15")

    path = append_journal(tmp_path, record)

    assert path.exists()
    records = read_journal(tmp_path, "test-strat-abc")
    assert len(records) == 1
    assert records[0]["asof"] == "2024-01-15"
    assert records[0]["account_after"]["cash"] == 900.0


def test_append_is_append_only_across_multiple_runs(tmp_path):
    append_journal(tmp_path, _record("2024-01-15"))
    append_journal(tmp_path, _record("2024-02-15"))

    records = read_journal(tmp_path, "test-strat-abc")

    assert [r["asof"] for r in records] == ["2024-01-15", "2024-02-15"]


def test_read_journal_returns_empty_list_when_nothing_journaled(tmp_path):
    assert read_journal(tmp_path, "nonexistent-strategy") == []


def test_journal_to_frame_is_indexed_by_asof_and_has_documented_columns(tmp_path):
    append_journal(tmp_path, _record("2024-01-15"))
    append_journal(tmp_path, _record("2024-02-15", refused="promotion gate refused"))

    frame = journal_to_frame(tmp_path, "test-strat-abc")

    assert list(frame.index) == [pd.Timestamp("2024-01-15"), pd.Timestamp("2024-02-15")]
    assert frame.loc[pd.Timestamp("2024-01-15"), "cash_after"] == 900.0
    assert frame.loc[pd.Timestamp("2024-02-15"), "refused_reason"] == "promotion gate refused"
    assert "reconciled_ok" in frame.columns


def test_journal_to_frame_carries_the_widened_fields(tmp_path):
    """Quant-gate VERDICT.md M08 cycle-1 carried item: `promoting_report_card`,
    `known_caveats`, `refreshed_actions_tickers` and `targets` used to be in
    the JSONL only, not the frame - plus the M08 cycle-2 fields
    (`kind`, `dropped_tickers`/`dropped_fraction`, `unscored_tickers`,
    `forced_exits`, `n_canceled_orders`/`n_resting_orders`,
    `assumed_fill_session`)."""
    append_journal(tmp_path, _record("2024-01-15"))

    frame = journal_to_frame(tmp_path, "test-strat-abc")
    row = frame.loc[pd.Timestamp("2024-01-15")]

    assert row["kind"] == "run"
    assert row["promoting_report_card"] == "reports/validate/strat/report_card.json"
    assert row["known_caveats"] == ["some caveat"]
    assert row["refreshed_actions_tickers"] == ["AAA"]
    assert row["dropped_tickers"] == ["BBB"]
    assert row["dropped_fraction"] == 0.025
    assert row["unscored_tickers"] == {"CCC": "missing lookback price"}
    assert row["forced_exits"] == {"DEAD": "forced exit: no price / delisted"}
    assert row["n_canceled_orders"] == 1
    assert row["n_resting_orders"] == 1
    assert row["targets"] == {
        "asof": "2024-01-15",
        "weights": {"AAA": 0.5},
        "strategy_id": "test-strat-abc",
    }
    assert row["assumed_fill_session"] == "2024-01-16"


def test_journal_to_frame_shows_a_rebaseline_records_kind(tmp_path):
    append_journal(tmp_path, _record("2024-01-15", kind="rebaseline"))

    frame = journal_to_frame(tmp_path, "test-strat-abc")

    assert frame.loc[pd.Timestamp("2024-01-15"), "kind"] == "rebaseline"


def test_journal_to_frame_is_empty_but_correctly_shaped_when_nothing_journaled(tmp_path):
    frame = journal_to_frame(tmp_path, "nonexistent-strategy")

    assert frame.empty
    assert frame.index.name == "asof"


def test_different_strategies_get_separate_journals(tmp_path):
    append_journal(tmp_path, _record("2024-01-15", strategy_id="strat-a"))
    append_journal(tmp_path, _record("2024-01-15", strategy_id="strat-b"))

    assert len(read_journal(tmp_path, "strat-a")) == 1
    assert len(read_journal(tmp_path, "strat-b")) == 1
