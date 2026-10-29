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
