import pandas as pd
import pytest

from backtest import run_backtest, validate_history


def synthetic_history():
    times = pd.date_range(
        "2026-01-01T00:00:00Z",
        periods=5,
        freq="15min",
    )

    return pd.DataFrame({
        "time_utc": times,
        "open":  [1.1000, 1.1002, 1.1008, 1.1012, 1.1015],
        "high":  [1.1005, 1.1010, 1.1012, 1.1015, 1.1020],
        "low":   [1.0995, 1.1000, 1.1005, 1.1008, 1.1010],
        "close": [1.1000, 1.1007, 1.1010, 1.1013, 1.1018],
        "spread": [0, 0, 0, 0, 0],
        "tick_volume": [100, 100, 100, 100, 100],
    })


def test_no_trade_strategy_preserves_balance():
    data = synthetic_history()

    result = run_backtest(
        data,
        strategy=lambda history: "HOLD",
        starting_balance=100,
        units=50,
        slippage_points=0,
        commission_per_side=0,
    )

    assert result["trade_count"] == 0
    assert result["final_balance"] == pytest.approx(100.0)
    assert result["net_pnl_usd"] == pytest.approx(0.0)


def test_signals_execute_on_next_candle_and_no_future_data():
    data = synthetic_history()
    observed_history_ends = []

    def toy_test_strategy(history):
        observed_history_ends.append(history["time_utc"].iloc[-1])

        if len(history) == 1:
            return "BUY"
        if len(history) == 3:
            return "EXIT"
        return "HOLD"

    result = run_backtest(
        data,
        strategy=toy_test_strategy,
        starting_balance=100,
        units=50,
        slippage_points=0,
        commission_per_side=0,
    )

    assert observed_history_ends == list(data["time_utc"].iloc[:-1])
    assert result["trade_count"] == 1
    assert result["trades"][0]["entry_time"] == data["time_utc"].iloc[1]
    assert result["trades"][0]["exit_time"] == data["time_utc"].iloc[3]
    assert result["net_pnl_usd"] == pytest.approx(0.05)


def test_exposure_limit_rejects_oversized_entry():
    result = run_backtest(
        synthetic_history(),
        strategy=lambda history: "BUY",
        starting_balance=100,
        units=1000,
        slippage_points=0,
        commission_per_side=0,
    )

    assert result["trade_count"] == 0
    assert result["rejected_entries"] > 0
    assert result["final_balance"] == pytest.approx(100.0)


def test_invalid_signal_is_rejected():
    with pytest.raises(ValueError, match="Invalid strategy signal"):
        run_backtest(
            synthetic_history(),
            strategy=lambda history: "MAYBE",
        )


def test_invalid_ohlc_is_rejected():
    data = synthetic_history()
    data.loc[2, "high"] = 0.5

    with pytest.raises(ValueError, match="Invalid OHLC"):
        validate_history(data)

def test_infinite_spread_is_rejected():
    data = synthetic_history()
    data["spread"] = data["spread"].astype("float64")
    data.loc[1, "spread"] = float("inf")
    with pytest.raises(ValueError, match="Spread must contain finite"):
        validate_history(data)


def test_misaligned_m15_timestamp_is_rejected():
    data = synthetic_history()
    data.loc[2, "time_utc"] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="align to 15-minute"):
        validate_history(data)


def test_numeric_parameters_are_normalized_and_nonfinite_costs_rejected():
    data = synthetic_history()
    result = run_backtest(
        data,
        strategy=lambda history: "HOLD",
        starting_balance="100",
        units="50",
        point_size="0.00001",
        slippage_points="0",
        commission_per_side="0",
    )
    assert result["starting_balance"] == pytest.approx(100.0)
    assert result["assumptions"]["point_size"] == pytest.approx(0.00001)
    assert result["assumptions"]["leverage_used"] is False

    with pytest.raises(ValueError, match="slippage_points must be finite"):
        run_backtest(
            data,
            strategy=lambda history: "HOLD",
            slippage_points=float("inf"),
        )



def test_bid_bar_buy_pays_spread_at_entry_not_exit():
    data = synthetic_history()
    data.loc[1, "spread"] = 10
    data.loc[3, "spread"] = 30

    def strategy(history):
        if len(history) == 1:
            return "BUY"
        if len(history) == 3:
            return "EXIT"
        return "HOLD"

    result = run_backtest(
        data, strategy=strategy, starting_balance=2000,
        units=1000, slippage_points=0, commission_per_side=0,
    )

    trade = result["trades"][0]
    assert trade["entry_price"] == pytest.approx(1.1002 + 0.0001)
    assert trade["exit_price"] == pytest.approx(1.1012)
    assert trade["spread_cost_usd"] == pytest.approx(0.10)
    assert trade["net_pnl_usd"] == pytest.approx(0.90)
    assert result["assumptions"]["price_basis"] == "bid"


def test_bid_bar_sell_pays_spread_when_buying_back():
    data = synthetic_history()
    data.loc[1, "spread"] = 10
    data.loc[3, "spread"] = 30

    def strategy(history):
        if len(history) == 1:
            return "SELL"
        if len(history) == 3:
            return "EXIT"
        return "HOLD"

    result = run_backtest(
        data, strategy=strategy, starting_balance=2000,
        units=1000, slippage_points=0, commission_per_side=0,
    )

    trade = result["trades"][0]
    assert trade["entry_price"] == pytest.approx(1.1002)
    assert trade["exit_price"] == pytest.approx(1.1012 + 0.0003)
    assert trade["spread_cost_usd"] == pytest.approx(0.30)
    assert trade["net_pnl_usd"] == pytest.approx(-1.30)



def test_stop_loss_wins_when_both_buy_barriers_touched():
    data = synthetic_history()

    result = run_backtest(
        data,
        strategy=lambda history: "BUY" if len(history) == 1 else "HOLD",
        starting_balance=100,
        units=50,
        slippage_points=0,
        commission_per_side=0,
        stop_loss_pips=2,
        take_profit_pips=4,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["reason"] == "STOP_LOSS"
    assert result["trades"][0]["exit_price"] == pytest.approx(1.1000)
    assert result["trades"][0]["exit_time"] == data["time_utc"].iloc[2]
    assert result["assumptions"]["stop_loss_pips"] == 2
    assert result["assumptions"]["take_profit_pips"] == 4


def test_buy_take_profit_can_trigger_without_stop_touch():
    data = synthetic_history()
    data.loc[1, "low"] = 1.10015
    data.loc[1, "high"] = 1.10080

    result = run_backtest(
        data,
        strategy=lambda history: "BUY" if len(history) == 1 else "HOLD",
        starting_balance=100,
        units=50,
        slippage_points=0,
        commission_per_side=0,
        stop_loss_pips=2,
        take_profit_pips=4,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["reason"] == "TAKE_PROFIT"
    assert result["trades"][0]["exit_price"] == pytest.approx(1.1006)


def test_sell_stop_uses_bid_high_plus_spread_ask_approximation():
    data = synthetic_history()
    data.loc[1, "spread"] = 10
    data.loc[1, "low"] = 1.10015
    data.loc[1, "high"] = 1.10080

    result = run_backtest(
        data,
        strategy=lambda history: "SELL" if len(history) == 1 else "HOLD",
        starting_balance=100,
        units=50,
        slippage_points=0,
        commission_per_side=0,
        stop_loss_pips=2,
        take_profit_pips=4,
    )

    assert result["trade_count"] == 1
    assert result["trades"][0]["reason"] == "STOP_LOSS"
    assert result["trades"][0]["exit_price"] == pytest.approx(1.1004)


def test_stop_loss_and_take_profit_must_be_enabled_together():
    with pytest.raises(ValueError, match="must be set together"):
        run_backtest(
            synthetic_history(),
            strategy=lambda history: "HOLD",
            stop_loss_pips=20,
        )


def test_opposite_direction_signal_closes_and_reverses_on_next_candle():
    data = synthetic_history()

    def strategy(history):
        if len(history) == 1:
            return "BUY"
        if len(history) == 3:
            return "SELL"
        return "HOLD"

    result = run_backtest(
        data,
        strategy=strategy,
        starting_balance=100,
        units=50,
        slippage_points=0,
        commission_per_side=0,
    )

    assert result["trade_count"] == 2
    assert result["trades"][0]["side"] == "BUY"
    assert result["trades"][0]["reason"] == "OPPOSITE_SIGNAL"
    assert result["trades"][0]["exit_time"] == data["time_utc"].iloc[3]
    assert result["trades"][1]["side"] == "SELL"
    assert result["trades"][1]["entry_time"] == data["time_utc"].iloc[3]
