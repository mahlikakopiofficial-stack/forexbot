import argparse
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "forex_lab.db"

MT5_PATH = os.environ.get(
    "MT5_PATH",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
)

SYMBOL = "EURUSD"

# Starting assumptions for simulation only.
DEFAULT_SLIPPAGE = 0.00001
DEFAULT_COMMISSION_PER_SIDE = 0.0

# This timezone interpretation matches the observed XM server
# timestamp offset in our current diagnostics. It must be
# reviewed if the broker or server changes.
SERVER_TIMEZONE = ZoneInfo("Europe/Athens")


def utc_now():
    return datetime.now(timezone.utc)


def utc_text(value=None):
    value = value or utc_now()
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def validate_positive(name, value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def validate_nonnegative(name, value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


def validate_quote(bid, ask):
    bid = validate_positive("bid", bid)
    ask = validate_positive("ask", ask)

    if ask < bid:
        raise ValueError("Ask cannot be less than bid")

    return bid, ask


def server_epoch_to_utc(timestamp):
    encoded = datetime.fromtimestamp(
        float(timestamp),
        tz=timezone.utc,
    )

    # Interpret the observed server clock as broker-local time.
    wall_time = encoded.replace(tzinfo=None)

    first = wall_time.replace(tzinfo=SERVER_TIMEZONE, fold=0)
    second = wall_time.replace(tzinfo=SERVER_TIMEZONE, fold=1)

    if first.utcoffset() != second.utcoffset():
        raise ValueError(
            f"Ambiguous broker timestamp: {wall_time}"
        )

    round_trip = (
        first.astimezone(timezone.utc)
        .astimezone(SERVER_TIMEZONE)
        .replace(tzinfo=None)
    )

    if round_trip != wall_time:
        raise ValueError(
            f"Invalid broker-local timestamp: {wall_time}"
        )

    return first.astimezone(timezone.utc)


def ensure_account_schema():
    """Back up the database before allowing negative simulated equity."""
    if not DB_FILE.is_file():
        raise FileNotFoundError(f"Database missing: {DB_FILE}")

    backup_created = False

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        account_schema = conn.execute("""
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'paper_account'
        """).fetchone()

        if account_schema is None:
            raise RuntimeError("paper_account table is missing")

        normalized = "".join(account_schema[0].lower().split())

        if "check(cash_balance>=0)" in normalized:
            backup_file = DB_FILE.with_name(
                "forex_lab_before_positions.sqlite"
            )

            if not backup_file.exists():
                with sqlite3.connect(backup_file) as backup:
                    conn.backup(backup)
                backup_created = True

            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("BEGIN IMMEDIATE")

            try:
                conn.execute("""
                    CREATE TABLE paper_account_new (
                        account_id INTEGER PRIMARY KEY
                            CHECK (account_id = 1),
                        currency TEXT NOT NULL
                            CHECK (currency = 'USD'),
                        initial_balance REAL NOT NULL
                            CHECK (initial_balance > 0),
                        cash_balance REAL NOT NULL,
                        realized_pnl REAL NOT NULL DEFAULT 0,
                        created_at_utc TEXT NOT NULL
                    )
                """)

                conn.execute("""
                    INSERT INTO paper_account_new
                    SELECT account_id, currency, initial_balance,
                           cash_balance, realized_pnl, created_at_utc
                    FROM paper_account
                """)

                conn.execute("DROP TABLE paper_account")
                conn.execute("""
                    ALTER TABLE paper_account_new
                    RENAME TO paper_account
                """)

                conn.commit()

            except Exception:
                conn.rollback()
                raise

            finally:
                conn.execute("PRAGMA foreign_keys = ON")

            if backup_created:
                print("Database backup:", backup_file.resolve())


def get_live_quote():
    """Read a quote from MT5. This function cannot submit an order."""
    if not Path(MT5_PATH).is_file():
        raise FileNotFoundError(f"MT5 terminal not found: {MT5_PATH}")

    if not mt5.initialize(path=MT5_PATH, timeout=15000):
        raise RuntimeError(
            f"MT5 initialization failed: {mt5.last_error()}"
        )

    try:
        terminal = mt5.terminal_info()

        if terminal is None or not terminal.connected:
            raise RuntimeError("MT5 terminal is disconnected")

        if not mt5.symbol_select(SYMBOL, True):
            raise RuntimeError(
                f"Could not select {SYMBOL}: {mt5.last_error()}"
            )

        tick = mt5.symbol_info_tick(SYMBOL)

        if tick is None:
            raise RuntimeError(
                f"No tick received: {mt5.last_error()}"
            )

        bid, ask = validate_quote(tick.bid, tick.ask)

        raw_time = (
            tick.time_msc / 1000.0
            if tick.time_msc
            else float(tick.time)
        )

        tick_utc = server_epoch_to_utc(raw_time)
        captured_at = utc_now()
        age = (captured_at - tick_utc).total_seconds()

        if abs(age) > 300:
            raise RuntimeError(
                f"Quote timestamp failed validation: "
                f"age={age:.1f}s. No position was created."
            )

        return {
            "symbol": SYMBOL,
            "bid": bid,
            "ask": ask,
            "tick_time_utc": utc_text(tick_utc),
            "captured_at_utc": utc_text(captured_at),
        }

    finally:
        mt5.shutdown()


def open_paper_position(
    direction,
    units,
    bid,
    ask,
    event_time_utc,
    slippage_per_fill=DEFAULT_SLIPPAGE,
    commission_per_side=DEFAULT_COMMISSION_PER_SIDE,
):
    direction = direction.upper()

    if direction not in {"BUY", "SELL"}:
        raise ValueError("Direction must be BUY or SELL")

    units = validate_positive("units", units)
    bid, ask = validate_quote(bid, ask)
    slip = validate_nonnegative("slippage", slippage_per_fill)
    commission = validate_nonnegative(
        "commission", commission_per_side
    )

    entry_price = (
        ask + slip if direction == "BUY" else bid - slip
    )

    if entry_price <= 0:
        raise ValueError("Simulated entry price must be positive")

    spread_cost = ((ask - bid) / 2) * units
    slippage_cost = slip * units
    event_time_utc = str(event_time_utc)

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        account = conn.execute("""
            SELECT cash_balance
            FROM paper_account
            WHERE account_id = 1
        """).fetchone()

        if account is None:
            raise RuntimeError("Virtual account is missing")

        cash = float(account["cash_balance"])

        open_exposure = conn.execute("""
            SELECT COALESCE(
                SUM(quantity_units * entry_price), 0
            )
            FROM paper_trades
            WHERE status = 'OPEN'
        """).fetchone()[0]

        # Conservative 1:1 notional limit. This is not a broker
        # margin model and intentionally does not use leverage.
        new_exposure = units * entry_price
        available = cash - float(open_exposure)

        if cash <= 0 or new_exposure > available + 1e-9:
            raise ValueError(
                f"Position rejected by the 1:1 exposure limit. "
                f"Requested notional=${new_exposure:.2f}; "
                f"available=${max(0, available):.2f}. "
                "No simulated position was created."
            )

        cursor = conn.execute("""
            INSERT INTO paper_trades (
                signal_id, symbol, direction,
                entry_time_utc, entry_price,
                quantity_units, spread_cost_usd,
                commission_usd, slippage_cost_usd,
                status
            )
            VALUES (
                NULL, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN'
            )
        """, (
            SYMBOL,
            direction,
            event_time_utc,
            entry_price,
            units,
            spread_cost,
            commission,
            slippage_cost,
        ))

        trade_id = cursor.lastrowid

    return {
        "trade_id": trade_id,
        "direction": direction,
        "units": units,
        "entry_price": entry_price,
        "spread_cost_usd": spread_cost,
        "slippage_cost_usd": slippage_cost,
        "commission_usd": commission,
        "notional_usd": new_exposure,
    }


def close_paper_position(
    trade_id,
    bid,
    ask,
    event_time_utc,
    slippage_per_fill=DEFAULT_SLIPPAGE,
    commission_per_side=DEFAULT_COMMISSION_PER_SIDE,
):
    trade_id = int(trade_id)
    bid, ask = validate_quote(bid, ask)
    slip = validate_nonnegative("slippage", slippage_per_fill)
    commission = validate_nonnegative(
        "commission", commission_per_side
    )

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")

        trade = conn.execute("""
            SELECT *
            FROM paper_trades
            WHERE id = ? AND status = 'OPEN'
        """, (trade_id,)).fetchone()

        if trade is None:
            raise ValueError(
                f"No open paper position exists with ID {trade_id}"
            )

        direction = trade["direction"]
        units = float(trade["quantity_units"])
        entry_price = float(trade["entry_price"])

        # BUY positions exit at bid; SELL positions exit at ask.
        exit_price = (
            bid - slip if direction == "BUY" else ask + slip
        )

        if exit_price <= 0:
            raise ValueError("Invalid simulated exit price")

        if direction == "BUY":
            gross_fill_pnl = (exit_price - entry_price) * units
        else:
            gross_fill_pnl = (entry_price - exit_price) * units

        total_commission = (
            float(trade["commission_usd"]) + commission
        )

        # Spread and slippage are included in the entry and exit
        # fill prices; only commission is deducted separately.
        net_pnl = gross_fill_pnl - total_commission

        spread_cost = (
            float(trade["spread_cost_usd"])
            + ((ask - bid) / 2) * units
        )

        slippage_cost = (
            float(trade["slippage_cost_usd"]) + slip * units
        )

        account = conn.execute("""
            SELECT cash_balance, realized_pnl
            FROM paper_account
            WHERE account_id = 1
        """).fetchone()

        if account is None:
            raise RuntimeError("Virtual account is missing")

        conn.execute("""
            UPDATE paper_trades
            SET exit_time_utc = ?,
                exit_price = ?,
                spread_cost_usd = ?,
                commission_usd = ?,
                slippage_cost_usd = ?,
                pnl_usd = ?,
                status = 'CLOSED'
            WHERE id = ? AND status = 'OPEN'
        """, (
            str(event_time_utc),
            exit_price,
            spread_cost,
            total_commission,
            slippage_cost,
            net_pnl,
            trade_id,
        ))

        conn.execute("""
            UPDATE paper_account
            SET cash_balance = ?,
                realized_pnl = ?
            WHERE account_id = 1
        """, (
            float(account["cash_balance"]) + net_pnl,
            float(account["realized_pnl"]) + net_pnl,
        ))

    return {
        "trade_id": trade_id,
        "direction": direction,
        "units": units,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_fill_pnl_usd": gross_fill_pnl,
        "spread_cost_usd": spread_cost,
        "slippage_cost_usd": slippage_cost,
        "commission_usd": total_commission,
        "net_pnl_usd": net_pnl,
    }


def show_positions():
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute("""
            SELECT id, direction, quantity_units,
                   entry_time_utc, entry_price
            FROM paper_trades
            WHERE status = 'OPEN'
            ORDER BY id
        """).fetchall()

    if not rows:
        print("No open paper positions.")
        return

    print("Open simulated positions — not broker orders")
    for row in rows:
        print(
            f"ID={row[0]} {row[1]} EURUSD "
            f"units={row[2]} entry={row[4]} "
            f"time={row[3]}"
        )


def main():
    parser = argparse.ArgumentParser(
        description="EURUSD paper-position manager; no live orders"
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("positions", help="List open simulated positions")

    open_parser = sub.add_parser(
        "open", help="Open a simulated position using an MT5 quote"
    )
    open_parser.add_argument("direction", choices=["BUY", "SELL"])
    open_parser.add_argument("units", type=float)
    open_parser.add_argument(
        "--slippage-per-fill",
        type=float,
        default=DEFAULT_SLIPPAGE,
    )
    open_parser.add_argument(
        "--commission-per-side",
        type=float,
        default=DEFAULT_COMMISSION_PER_SIDE,
    )

    close_parser = sub.add_parser(
        "close", help="Close a simulated position using an MT5 quote"
    )
    close_parser.add_argument("trade_id", type=int)
    close_parser.add_argument(
        "--slippage-per-fill",
        type=float,
        default=DEFAULT_SLIPPAGE,
    )
    close_parser.add_argument(
        "--commission-per-side",
        type=float,
        default=DEFAULT_COMMISSION_PER_SIDE,
    )

    args = parser.parse_args()

    try:
        ensure_account_schema()

        if args.command == "positions":
            show_positions()
            return 0

        quote = get_live_quote()
        print("Read-only MT5 quote:", quote)

        if args.command == "open":
            result = open_paper_position(
                args.direction,
                args.units,
                quote["bid"],
                quote["ask"],
                quote["captured_at_utc"],
                args.slippage_per_fill,
                args.commission_per_side,
            )
            print("SIMULATED POSITION CREATED")
            for key, value in result.items():
                print(f"{key}: {value}")

        elif args.command == "close":
            result = close_paper_position(
                args.trade_id,
                quote["bid"],
                quote["ask"],
                quote["captured_at_utc"],
                args.slippage_per_fill,
                args.commission_per_side,
            )
            print("SIMULATED POSITION CLOSED")
            for key, value in result.items():
                print(f"{key}: {value}")

        return 0

    except (ValueError, RuntimeError, FileNotFoundError,
            sqlite3.Error) as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())