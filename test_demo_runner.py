import sqlite3
from types import SimpleNamespace

import pytest
import pandas as pd

import demo_runner
from ema_strategy import ema_crossover_signal
from demo_runner import (
    calculate_protective_prices,
    validate_latest_bar_freshness,
    DemoExecutionError,
    SingleInstanceLock,
    decide_existing_position_action,
    init_state_db,
    record_event,
    unresolved_events,
    state_get,
    state_set,
    last_processed_state_key,
    validate_settings,
)


@pytest.mark.parametrize("symbol", ["GOLD", "GOLD#"])
def test_runner_accepts_allowlisted_symbol(monkeypatch, symbol):
    monkeypatch.setattr(demo_runner, "SYMBOL", symbol)
    validate_settings()


@pytest.mark.parametrize("symbol", ["", "EURUSD", "GBPUSD"])
def test_runner_rejects_unlisted_symbol(monkeypatch, symbol):
    monkeypatch.setattr(demo_runner, "SYMBOL", symbol)
    with pytest.raises(ValueError, match="Unsupported FOREX_SYMBOL"):
        validate_settings()


def test_last_processed_checkpoint_is_scoped_per_symbol():
    assert last_processed_state_key("GOLD") != last_processed_state_key("GOLD#")


def test_ema_crossover_uses_only_latest_completed_close_values():
    assert ema_crossover_signal([10, 9, 8, 7, 6, 7, 8], fast=2, slow=4) == "BUY"
    assert ema_crossover_signal([6, 7, 8, 9, 10, 9, 8], fast=2, slow=4) == "SELL"
    assert ema_crossover_signal([1.1, 1.1001], fast=2, slow=4) == "HOLD"


def test_invalid_ema_settings_input_prices_raise():
    with pytest.raises(ValueError, match="invalid close"):
        ema_crossover_signal([1.1, 1.2, float("nan"), 1.3, 1.4], fast=2, slow=3)


def test_protective_price_calculation_for_gold():
    info = SimpleNamespace(point=0.01, digits=2)
    quote = {"bid": 4000.00, "ask": 4000.20}

    sl_buy, tp_buy = calculate_protective_prices(
        "BUY", quote, info, stop_distance=5.0, target_distance=10.0
    )
    sl_sell, tp_sell = calculate_protective_prices(
        "SELL", quote, info, stop_distance=5.0, target_distance=10.0
    )

    assert sl_buy == pytest.approx(3995.20)
    assert tp_buy == pytest.approx(4010.20)
    assert sl_sell == pytest.approx(4005.00)
    assert tp_sell == pytest.approx(3990.00)

def test_execution_ledger_blocks_unresolved_events(tmp_path):
    db = tmp_path / "demo.sqlite3"
    init_state_db(db)
    assert unresolved_events(db) == []

    record_event(
        "GOLD#|M5|2026-10-29T09:15:00Z|BUY",
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



@pytest.mark.parametrize(
    ("signal", "direction", "expected"),
    [
        ("HOLD", "BUY", "HOLD"),
        ("HOLD", "SELL", "HOLD"),
        ("BUY", "BUY", "HOLD"),
        ("SELL", "SELL", "HOLD"),
        ("SELL", "BUY", "REVERSE_TO_SELL"),
        ("BUY", "SELL", "REVERSE_TO_BUY"),
    ],
)
def test_existing_position_reverses_on_opposite_signal(signal, direction, expected):
    assert decide_existing_position_action(signal, direction) == expected



def test_freshness_check_accepts_recent_completed_m5_candle():
    bars = pd.DataFrame({
        "time_utc": [pd.Timestamp("2026-10-29T10:00:00Z")]
    })
    validate_latest_bar_freshness(
        bars,
        now_utc=pd.Timestamp("2026-10-29T10:10:00Z").to_pydatetime(),
        timeframe_minutes=5,
        max_stale_minutes=15,
    )


def test_freshness_check_rejects_stale_m5_candle():
    bars = pd.DataFrame({
        "time_utc": [pd.Timestamp("2026-10-29T10:00:00Z")]
    })
    with pytest.raises(DemoExecutionError, match="is stale"):
        validate_latest_bar_freshness(
            bars,
            now_utc=pd.Timestamp("2026-10-29T10:30:00Z").to_pydatetime(),
            timeframe_minutes=5,
            max_stale_minutes=15,
        )


def test_freshness_check_rejects_m5_candle_that_closes_in_future():
    bars = pd.DataFrame({
        "time_utc": [pd.Timestamp("2026-10-29T10:00:00Z")]
    })
    with pytest.raises(DemoExecutionError, match="closes in the future"):
        validate_latest_bar_freshness(
            bars,
            now_utc=pd.Timestamp("2026-10-29T10:02:00Z").to_pydatetime(),
            timeframe_minutes=5,
            max_stale_minutes=15,
        )
