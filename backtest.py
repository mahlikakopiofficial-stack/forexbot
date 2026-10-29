import argparse
import math
import sqlite3
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "forex_lab.db"

SYMBOL = "EURUSD"
TIMEFRAME = "M15"
BAR_MINUTES = 15

# EURUSD commonly uses 5 decimal places. Verify against the broker's
# actual symbol point before treating historical costs as definitive.
POINT_SIZE = 0.00001

ACTIONS = {"BUY", "SELL", "EXIT", "HOLD"}


def load_history(db_file=DB_FILE):
    if not Path(db_file).is_file():
        raise FileNotFoundError(f"Database not found: {db_file}")

    with sqlite3.connect(db_file) as conn:
        df = pd.read_sql_query(
            """
            SELECT time_utc, open, high, low, close, spread, tick_volume
            FROM market_candles
            WHERE symbol = ? AND timeframe = ?
            ORDER BY time_utc
            """,
            conn,
            params=(SYMBOL, TIMEFRAME),
        )

    if df.empty:
        raise ValueError("No historical candles found")

    return validate_history(df)


def validate_history(df):
    required = {
        "time_utc", "open", "high", "low", "close", "spread"
    }

    if not required.issubset(df.columns):
        raise ValueError(f"Missing columns: {required - set(df.columns)}")

    result = df.copy()
    result["time_utc"] = pd.to_datetime(
        result["time_utc"], utc=True, errors="raise"
    )

    for column in ["open", "high", "low", "close", "spread"]:
        result[column] = pd.to_numeric(
            result[column], errors="raise"
        )

    if result["time_utc"].duplicated().any():
        raise ValueError("Duplicate candle timestamps")

    if not result["time_utc"].is_monotonic_increasing:
        raise ValueError("Candles must be in chronological order")

    prices = result[["open", "high", "low", "close"]]

    if not prices.map(lambda x: math.isfinite(float(x))).all().all():
        raise ValueError("Non-finite candle prices")

    if (prices <= 0).any().any():
        raise ValueError("Candle prices must be positive")

    valid_ohlc = (
        (result["low"] <= result["open"])
        & (result["low"] <= result["close"])
        & (result["high"] >= result["open"])
        & (result["high"] >= result["close"])
        & (result["low"] <= result["high"])
        & (result["spread"] >= 0)
    )

    if not valid_ohlc.all():
        raise ValueError("Invalid OHLC prices or spread values")

    if not result["spread"].map(
        lambda value: math.isfinite(float(value)) and float(value) >= 0
    ).all():
        raise ValueError("Spread must contain finite, nonnegative values")

    aligned = (
        (result["time_utc"].dt.minute % BAR_MINUTES == 0)
        & (result["time_utc"].dt.second == 0)
        & (result["time_utc"].dt.microsecond == 0)
    )
    if not aligned.all():
        raise ValueError(
            f"Candle timestamps must align to {BAR_MINUTES}-minute boundaries"
        )

    return result.reset_index(drop=True)


def candle_fill(bar, side, field, point_size, slippage_points):
    """
    Model a hypothetical fill from a candle's mid-price and spread.

    BUY executes at mid + half-spread + slippage.
    SELL executes at mid - half-spread - slippage.
    """
    mid = float(bar[field])
    spread_points = float(bar["spread"])
    half_spread = spread_points * point_size / 2
    slippage = slippage_points * point_size

    if side == "BUY":
        fill = mid + half_spread + slippage
    elif side == "SELL":
        fill = mid - half_spread - slippage
    else:
        raise ValueError(f"Invalid execution side: {side}")

    if not math.isfinite(fill) or fill <= 0:
        raise ValueError("Invalid simulated fill price")

    return fill


def close_position(position, bar, exit_time, point_size,
                   slippage_points, commission_per_side, reason):
    side = position["side"]
    units = position["units"]

    # Close a long with a SELL; close a short with a BUY.
    exit_side = "SELL" if side == "BUY" else "BUY"

    exit_mid = float(bar["open"])
    exit_fill = candle_fill(
        bar, exit_side, "open", point_size, slippage_points
    )

    sign = 1 if side == "BUY" else -1

    mid_pnl = (
        (exit_mid - position["entry_mid"]) * units * sign
    )

    spread_cost = (
        position["entry_spread_half_cost"]
        + float(bar["spread"]) * point_size / 2 * units
    )

    slippage_cost = (
        position["entry_slippage_cost"]
        + slippage_points * point_size * units
    )

    commissions = (
        position["entry_commission"] + commission_per_side
    )

    net_pnl = mid_pnl - spread_cost - slippage_cost - commissions

    return {
        "side": side,
        "units": units,
        "entry_time": position["entry_time"],
        "exit_time": exit_time,
        "entry_price": position["entry_fill"],
        "exit_price": exit_fill,
        "mid_pnl_usd": mid_pnl,
        "spread_cost_usd": spread_cost,
        "slippage_cost_usd": slippage_cost,
        "commission_usd": commissions,
        "net_pnl_usd": net_pnl,
        "reason": reason,
    }


def run_backtest(
    history,
    strategy,
    starting_balance=100.0,
    units=50.0,
    point_size=POINT_SIZE,
    slippage_points=1.0,
    commission_per_side=0.0,
):
    """
    Generic, single-position paper backtester.

    strategy(history_so_far) returns BUY, SELL, EXIT, or HOLD.
    Each signal is evaluated after a candle is complete and, when
    actionable, filled at the NEXT candle's open.

    One open position maximum. No leverage. No broker orders.
    """
    df = validate_history(history)

    try:
        starting_balance = float(starting_balance)
        units = float(units)
        point_size = float(point_size)
        slippage_points = float(slippage_points)
        commission_per_side = float(commission_per_side)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Backtest numeric settings must be valid numbers") from exc

    for name, value in [
        ("starting_balance", starting_balance),
        ("units", units),
        ("point_size", point_size),
    ]:
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be positive and finite")

    if not math.isfinite(slippage_points) or slippage_points < 0:
        raise ValueError("slippage_points must be finite and nonnegative")

    if not math.isfinite(commission_per_side) or commission_per_side < 0:
        raise ValueError("commission must be finite and nonnegative")

    if not callable(strategy):
        raise ValueError("strategy must be a callable function")

    if len(df) < 2:
        raise ValueError("At least two candles are required")

    balance = float(starting_balance)
    position = None
    trades = []
    rejected_entries = 0

    equity_curve = [{
        "time_utc": df.iloc[0]["time_utc"],
        "equity": balance,
    }]

    for index in range(len(df) - 1):
        signal_history = df.iloc[:index + 1].copy(deep=True)
        signal = strategy(signal_history)

        if not isinstance(signal, str):
            raise ValueError("Strategy must return a string action")

        signal = signal.upper().strip()

        if signal not in ACTIONS:
            raise ValueError(
                f"Invalid strategy signal {signal!r}; "
                f"choose from {sorted(ACTIONS)}"
            )

        # Execution uses the following candle, not the candle that
        # generated the signal: this avoids intrabar look-ahead.
        bar = df.iloc[index + 1]
        event_time = bar["time_utc"]

        if position is None:
            if signal in {"BUY", "SELL"}:
                entry_fill = candle_fill(
                    bar, signal, "open", point_size,
                    slippage_points
                )

                # Conservative 1:1 notional limit; no leverage.
                if units * entry_fill > balance + 1e-9:
                    rejected_entries += 1
                else:
                    position = {
                        "side": signal,
                        "units": float(units),
                        "entry_time": event_time,
                        "entry_mid": float(bar["open"]),
                        "entry_fill": entry_fill,
                        "entry_commission": float(
                            commission_per_side
                        ),
                        "entry_spread_half_cost": (
                            float(bar["spread"])
                            * point_size / 2 * units
                        ),
                        "entry_slippage_cost": (
                            slippage_points * point_size * units
                        ),
                    }

        else:
            opposite = (
                (position["side"] == "BUY" and signal == "SELL")
                or
                (position["side"] == "SELL" and signal == "BUY")
            )

            if signal == "EXIT" or opposite:
                trade = close_position(
                    position=position,
                    bar=bar,
                    exit_time=event_time,
                    point_size=point_size,
                    slippage_points=slippage_points,
                    commission_per_side=commission_per_side,
                    reason=(
                        "OPPOSITE_SIGNAL" if opposite
                        else "EXIT_SIGNAL"
                    ),
                )

                trades.append(trade)
                balance += trade["net_pnl_usd"]
                position = None

        # Mark open positions at the current candle's close using
        # a hypothetical executable exit price.
        unrealized = 0.0

        if position is not None:
            exit_side = (
                "SELL" if position["side"] == "BUY" else "BUY"
            )

            mark_fill = candle_fill(
                bar, exit_side, "close", point_size,
                slippage_points
            )

            sign = 1 if position["side"] == "BUY" else -1

            unrealized = (
                (mark_fill - position["entry_fill"])
                * position["units"] * sign
                - position["entry_commission"]
                - commission_per_side
            )

        equity_curve.append({
            "time_utc": event_time + pd.Timedelta(minutes=BAR_MINUTES),
            "equity": balance + unrealized,
        })

    # Close any remaining position at the final candle's close.
    if position is not None:
        last = df.iloc[-1]
        exit_mid = float(last["close"])
        side = "SELL" if position["side"] == "BUY" else "BUY"

        spread = float(last["spread"]) * point_size / 2
        slip = slippage_points * point_size

        exit_fill = (
            exit_mid - spread - slip
            if side == "SELL"
            else exit_mid + spread + slip
        )

        sign = 1 if position["side"] == "BUY" else -1
        units_open = position["units"]

        mid_pnl = (
            (exit_mid - position["entry_mid"])
            * units_open * sign
        )

        spread_cost = (
            position["entry_spread_half_cost"]
            + spread * units_open
        )

        slippage_cost = (
            position["entry_slippage_cost"]
            + slip * units_open
        )

        commissions = (
            position["entry_commission"] + commission_per_side
        )

        net_pnl = mid_pnl - spread_cost - slippage_cost - commissions

        trades.append({
            "side": position["side"],
            "units": units_open,
            "entry_time": position["entry_time"],
            "exit_time": (
                last["time_utc"]
                + pd.Timedelta(minutes=BAR_MINUTES)
            ),
            "entry_price": position["entry_fill"],
            "exit_price": exit_fill,
            "mid_pnl_usd": mid_pnl,
            "spread_cost_usd": spread_cost,
            "slippage_cost_usd": slippage_cost,
            "commission_usd": commissions,
            "net_pnl_usd": net_pnl,
            "reason": "END_OF_DATA",
        })

        balance += net_pnl
        position = None
        equity_curve[-1]["equity"] = balance

    pnls = [trade["net_pnl_usd"] for trade in trades]
    wins = sum(pnl > 0 for pnl in pnls)
    losses = sum(pnl < 0 for pnl in pnls)
    gross_wins = sum(pnl for pnl in pnls if pnl > 0)
    gross_losses = -sum(pnl for pnl in pnls if pnl < 0)

    peak = float(starting_balance)
    max_drawdown = 0.0

    for point in equity_curve:
        equity = point["equity"]
        peak = max(peak, equity)

        if peak > 0:
            max_drawdown = max(
                max_drawdown,
                (peak - equity) / peak,
            )

    return {
        "starting_balance": float(starting_balance),
        "final_balance": balance,
        "net_pnl_usd": balance - starting_balance,
        "return_pct": (
            (balance / starting_balance - 1) * 100
        ),
        "trade_count": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": (
            wins / len(trades) * 100 if trades else 0.0
        ),
        "profit_factor": (
            gross_wins / gross_losses
            if gross_losses > 0
            else None
        ),
        "max_drawdown_pct": max_drawdown * 100,
        "rejected_entries": rejected_entries,
        "assumptions": {
            "symbol": SYMBOL,
            "timeframe": TIMEFRAME,
            "point_size": point_size,
            "units_per_trade": units,
            "slippage_points_per_fill": slippage_points,
            "commission_per_side_usd": commission_per_side,
            "max_open_positions": 1,
            "leverage_used": False,
            "fill_timing": "next_candle_open",
        },
        "trades": trades,
        "equity_curve": equity_curve,
    }


def audit_database():
    df = load_history()

    gaps = df["time_utc"].diff().dropna()
    large_gaps = gaps[gaps > pd.Timedelta(minutes=BAR_MINUTES)]

    print("=== BACKTEST DATA AUDIT ===")
    print("Database:", DB_FILE.resolve())
    print("Symbol:", SYMBOL)
    print("Timeframe:", TIMEFRAME)
    print("Candles:", len(df))
    print("First candle UTC:", df["time_utc"].iloc[0].isoformat())
    print("Last candle UTC:", df["time_utc"].iloc[-1].isoformat())
    print("Gaps over 15 minutes:", len(large_gaps))

    if not large_gaps.empty:
        print("Largest gap:", large_gaps.max())
        print(
            "Gaps may include weekends or missing broker history; "
            "inspect them before interpreting results."
        )

    print("Strategy configured: NO")
    print("Backtest trades run: NO")
    print("Real orders: NEVER")
    print("Data validated for structural checks.")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Strategy-neutral historical backtesting framework"
    )
    parser.add_argument(
        "command",
        choices=["audit"],
        help="audit validates stored history; no strategy runs",
    )
    args = parser.parse_args()

    if args.command == "audit":
        return audit_database()


if __name__ == "__main__":
    raise SystemExit(main())