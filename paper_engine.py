import argparse
import math
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "forex_lab.db"


def _positive_finite(name, value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def simulate_round_trip(
    direction,
    units,
    entry_bid,
    entry_ask,
    exit_bid,
    exit_ask,
    slippage_per_fill=0.0,
    commission_round_trip=0.0,
):
    """
    Calculate a hypothetical EURUSD round trip.

    units: EUR base-currency units.
    slippage_per_fill: adverse price movement per execution.
    commission_round_trip: total commission in USD for both sides.

    Does not connect to MT5, write to SQLite, or place orders.
    """
    direction = direction.upper()

    if direction not in {"BUY", "SELL"}:
        raise ValueError("direction must be BUY or SELL")

    units = _positive_finite("units", units)
    entry_bid = _positive_finite("entry_bid", entry_bid)
    entry_ask = _positive_finite("entry_ask", entry_ask)
    exit_bid = _positive_finite("exit_bid", exit_bid)
    exit_ask = _positive_finite("exit_ask", exit_ask)

    slippage_per_fill = float(slippage_per_fill)
    commission_round_trip = float(commission_round_trip)

    if not math.isfinite(slippage_per_fill) or slippage_per_fill < 0:
        raise ValueError("slippage_per_fill must be finite and nonnegative")

    if (
        not math.isfinite(commission_round_trip)
        or commission_round_trip < 0
    ):
        raise ValueError("commission must be finite and nonnegative")

    if entry_ask < entry_bid or exit_ask < exit_bid:
        raise ValueError("Ask must be greater than or equal to bid")

    entry_mid = (entry_bid + entry_ask) / 2
    exit_mid = (exit_bid + exit_ask) / 2

    if direction == "BUY":
        mid_pnl = (exit_mid - entry_mid) * units
    else:
        mid_pnl = (entry_mid - exit_mid) * units

    spread_cost = (
        (entry_ask - entry_bid) / 2
        + (exit_ask - exit_bid) / 2
    ) * units

    slippage_cost = 2 * slippage_per_fill * units

    net_pnl = (
        mid_pnl
        - spread_cost
        - slippage_cost
        - commission_round_trip
    )

    return {
        "symbol": "EURUSD",
        "direction": direction,
        "units": units,
        "mid_pnl_usd": mid_pnl,
        "spread_cost_usd": spread_cost,
        "slippage_cost_usd": slippage_cost,
        "commission_usd": commission_round_trip,
        "net_pnl_usd": net_pnl,
    }


def show_status():
    if not DB_FILE.is_file():
        raise SystemExit(f"Database not found: {DB_FILE}")

    with sqlite3.connect(DB_FILE) as conn:
        account = conn.execute("""
            SELECT currency, initial_balance, cash_balance, realized_pnl
            FROM paper_account
            WHERE account_id = 1
        """).fetchone()

        candle_count = conn.execute("""
            SELECT COUNT(*)
            FROM market_candles
            WHERE symbol = 'EURUSD' AND timeframe = 'M15'
        """).fetchone()[0]

        latest = conn.execute("""
            SELECT MAX(time_utc)
            FROM market_candles
            WHERE symbol = 'EURUSD' AND timeframe = 'M15'
        """).fetchone()[0]

        trade_counts = conn.execute("""
            SELECT status, COUNT(*)
            FROM paper_trades
            GROUP BY status
        """).fetchall()

    if account is None:
        raise SystemExit("Virtual account has not been initialized.")

    print("Paper engine status")
    print("Database:", DB_FILE.resolve())
    print("Instrument: EURUSD")
    print("Strategy: NOT CONFIGURED")
    print("Live order submission: NOT IMPLEMENTED")
    print("Currency:", account[0])
    print(f"Initial virtual balance: ${account[1]:.2f}")
    print(f"Virtual cash balance: ${account[2]:.2f}")
    print(f"Realized P&L: ${account[3]:.2f}")
    print("Stored M15 candles:", candle_count)
    print("Latest stored candle UTC:", latest)
    print("Existing paper trades:", trade_counts or "None")


def run_self_test():
    # Entirely synthetic quotes; this does not represent a real trade.
    result = simulate_round_trip(
        direction="BUY",
        units=1000,
        entry_bid=1.10000,
        entry_ask=1.10020,
        exit_bid=1.10100,
        exit_ask=1.10120,
        slippage_per_fill=0.00001,
        commission_round_trip=0.10,
    )

    print("SYNTHETIC TEST ONLY — NO TRADE WAS OPENED OR SAVED")
    print("Direction:", result["direction"])
    print("Simulated EUR units:", result["units"])
    print(f"Mid-price P&L: ${result['mid_pnl_usd']:.4f}")
    print(f"Estimated spread cost: ${result['spread_cost_usd']:.4f}")
    print(f"Estimated slippage cost: ${result['slippage_cost_usd']:.4f}")
    print(f"Commission: ${result['commission_usd']:.4f}")
    print(f"Net simulated P&L: ${result['net_pnl_usd']:.4f}")


def main():
    parser = argparse.ArgumentParser(
        description="Read-only status and synthetic paper-trading test"
    )
    parser.add_argument(
        "command",
        choices=["status", "self-test"],
        help="status reads the database; self-test uses synthetic prices",
    )
    args = parser.parse_args()

    if args.command == "status":
        show_status()
    elif args.command == "self-test":
        run_self_test()


if __name__ == "__main__":
    main()