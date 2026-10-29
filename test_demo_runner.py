import sqlite3
from types import SimpleNamespace

import pytest

from demo_runner import (
    calculate_protective_prices,
    DemoExecutionError,
    SingleInstanceLock,
    ema_crossover_signal,
    init_state_db,
    record_event,
    unresolved_events,
    state_get,
    state_set,
)


def test_ema_crossover_uses_only_latest_completed_close_values():
    assert ema_crossover_signal([10, 9, 8, 7, 6, 7, 8], fast=2, slow=4) == "BUY"
    assert ema_crossover_signal([6, 7, 8, 9, 10, 9, 8], fast=2, slow=4) == "SELL"
    assert ema_crossover_signal([1.1, 1.1001], fast=2, slow=4) == "HOLD"


def test_invalid_ema_settings_input_prices_raise():
    with pytest.raises(ValueError, match="invalid close"):
        ema_crossover_signal([1.1, 1.2, float("nan"), 1.3, 1.4], fast=2, slow=3)


def test_protective_price_calculation_for_five_digit_eurusd():
    info = SimpleNamespace(point=0.00001, digits=5)
    quote = {"bid": 1.10000, "ask": 1.10020}

    sl_buy, tp_buy = calculate_protective_prices(
        "BUY", quote, info, stop_pips=20, target_pips=40
    )
    sl_sell, tp_sell = calculate_protective_prices(
        "SELL", quote, info, stop_pips=20, target_pips=40
    )

    assert sl_buy == pytest.approx(1.09820)
    assert tp_buy == pytest.approx(1.10420)
    assert sl_sell == pytest.approx(1.10200)
    assert tp_sell == pytest.approx(1.09600)


def test_execution_ledger_blocks_unresolved_events(tmp_path):
    db = tmp_path / "demo.sqlite3"
    init_state_db(db)
    assert unresolved_events(db) == []

    record_event(
        "EURUSD|M15|2026-10-29T09:15:00Z|BUY",
        "2026-10-29T09:15:00Z",
        "OPEN_BUY",
        "PENDING",
        {"signal": "BUY"},
        db,
    )

    found = unresolved_events(db)
    assert len(found) == 1
    assert found[0][1] == "PENDING"


def test_runner_state_persists_last_processed_bar(tmp_path):
    db = tmp_path / "demo.sqlite3"
    init_state_db(db)

    assert state_get("last_processed_candle_utc", db) is None
    state_set("last_processed_candle_utc", "2026-10-29T09:15:00Z", db)
    assert state_get("last_processed_candle_utc", db) == "2026-10-29T09:15:00Z"



def test_runner_lock_prevents_second_instance_and_releases(tmp_path):
    lock_path = tmp_path / "demo_runner.lock"
    first = SingleInstanceLock(lock_path).acquire()
    try:
        second = SingleInstanceLock(lock_path)
        with pytest.raises(DemoExecutionError, match="already running"):
            second.acquire()
    finally:
        first.release()

    with SingleInstanceLock(lock_path):
        pass
