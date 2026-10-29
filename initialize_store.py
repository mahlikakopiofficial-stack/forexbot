import csv
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "data" / "eurusd_m15_utc_corrected.csv"
DB_FILE = BASE_DIR / "data" / "forex_lab.db"

STARTING_BALANCE = 1000.00


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_utc(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        raise ValueError(f"Timestamp has no timezone: {value}")

    return dt.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def load_candles():
    if not CSV_FILE.is_file():
        raise FileNotFoundError(f"Missing input CSV: {CSV_FILE}")

    candles = []
    seen = set()

    with CSV_FILE.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        required = {"time", "open", "high", "low", "close"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(
                f"CSV must contain these columns: {sorted(required)}"
            )

        for row in reader:
            timestamp = normalize_utc(row["time"])
            key = ("EURUSD", "M15", timestamp)

            if key in seen:
                raise ValueError(f"Duplicate candle timestamp: {timestamp}")
            seen.add(key)

            prices = {
                name: float(row[name])
                for name in ("open", "high", "low", "close")
            }

            if not all(math.isfinite(v) and v > 0 for v in prices.values()):
                raise ValueError(f"Invalid candle prices: {timestamp}")

            if (
                prices["high"] < max(prices.values())
                or prices["low"] > min(prices.values())
                or prices["low"] > prices["high"]
            ):
                raise ValueError(f"Invalid OHLC relationship: {timestamp}")

            candles.append((
                "EURUSD",
                "M15",
                timestamp,
                prices["open"],
                prices["high"],
                prices["low"],
                prices["close"],
                int(row.get("tick_volume") or 0),
                int(row.get("spread") or 0),
                int(row.get("real_volume") or 0),
            ))

    if not candles:
        raise ValueError("The CSV contains no candles.")

    return candles


def main():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    candles = load_candles()

    schema = """
    CREATE TABLE IF NOT EXISTS market_candles (
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        time_utc TEXT NOT NULL,
        open REAL NOT NULL,
        high REAL NOT NULL,
        low REAL NOT NULL,
        close REAL NOT NULL,
        tick_volume INTEGER NOT NULL DEFAULT 0,
        spread INTEGER NOT NULL DEFAULT 0,
        real_volume INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (symbol, timeframe, time_utc),
        CHECK (low <= high),
        CHECK (low <= open AND open <= high),
        CHECK (low <= close AND close <= high)
    );

    CREATE TABLE IF NOT EXISTS paper_account (
        account_id INTEGER PRIMARY KEY CHECK (account_id = 1),
        currency TEXT NOT NULL CHECK (currency = 'USD'),
        initial_balance REAL NOT NULL CHECK (initial_balance > 0),
        cash_balance REAL NOT NULL CHECK (cash_balance >= 0),
        realized_pnl REAL NOT NULL DEFAULT 0,
        created_at_utc TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS strategy_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        candle_time_utc TEXT NOT NULL,
        direction TEXT NOT NULL
            CHECK (direction IN ('BUY', 'SELL', 'HOLD')),
        reason TEXT NOT NULL DEFAULT '',
        created_at_utc TEXT NOT NULL,
        UNIQUE (strategy_name, symbol, timeframe, candle_time_utc)
    );

    CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_id INTEGER,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL
            CHECK (direction IN ('BUY', 'SELL')),
        entry_time_utc TEXT NOT NULL,
        entry_price REAL NOT NULL CHECK (entry_price > 0),
        exit_time_utc TEXT,
        exit_price REAL,
        quantity_units REAL NOT NULL CHECK (quantity_units > 0),
        spread_cost_usd REAL NOT NULL DEFAULT 0,
        commission_usd REAL NOT NULL DEFAULT 0,
        slippage_cost_usd REAL NOT NULL DEFAULT 0,
        pnl_usd REAL,
        status TEXT NOT NULL DEFAULT 'OPEN'
            CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED')),
        FOREIGN KEY (signal_id) REFERENCES strategy_signals(id)
    );
    """

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema)

        # Create the account only once. Never reset its balance
        # when this initializer is run again.
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_account
            (account_id, currency, initial_balance, cash_balance,
             realized_pnl, created_at_utc)
            VALUES (1, 'USD', ?, ?, 0, ?)
            """,
            (STARTING_BALANCE, STARTING_BALANCE, utc_now()),
        )

        before = conn.execute(
            "SELECT COUNT(*) FROM market_candles"
        ).fetchone()[0]

        conn.executemany(
            """
            INSERT OR IGNORE INTO market_candles
            (symbol, timeframe, time_utc, open, high, low, close,
             tick_volume, spread, real_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            candles,
        )

        after = conn.execute(
            "SELECT COUNT(*) FROM market_candles"
        ).fetchone()[0]

        account = conn.execute(
            """
            SELECT currency, initial_balance, cash_balance, realized_pnl
            FROM paper_account WHERE account_id = 1
            """
        ).fetchone()

        bounds = conn.execute(
            """
            SELECT MIN(time_utc), MAX(time_utc)
            FROM market_candles
            WHERE symbol = 'EURUSD' AND timeframe = 'M15'
            """
        ).fetchone()

    print("Database initialized successfully.")
    print("Database:", DB_FILE.resolve())
    print("Input candles:", len(candles))
    print("New candles inserted:", after - before)
    print("Total candles in database:", after)
    print("EURUSD M15 date range:", bounds[0], "to", bounds[1])
    print("Account currency:", account[0])
    print(f"Initial virtual balance: ${account[1]:.2f}")
    print(f"Current virtual cash balance: ${account[2]:.2f}")
    print(f"Realized simulated P&L: ${account[3]:.2f}")
    print("Live orders: NOT IMPLEMENTED")
    print("Strategy: NOT CONFIGURED")


if __name__ == "__main__":
    main()