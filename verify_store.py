import os
import sqlite3
from pathlib import Path

DB = Path("data/forex_lab.db")
SYMBOL = os.environ.get("FOREX_SYMBOL", "EURUSD").strip()
TIMEFRAME = "M15"

if not DB.exists():
    raise SystemExit(f"Database not found: {DB.resolve()}")

with sqlite3.connect(DB) as conn:
    count = conn.execute("""
        SELECT COUNT(*)
        FROM market_candles
        WHERE symbol = ? AND timeframe = ?
    """, (SYMBOL, TIMEFRAME)).fetchone()[0]

    latest = conn.execute("""
        SELECT time_utc, open, high, low, close
        FROM market_candles
        WHERE symbol = ? AND timeframe = ?
        ORDER BY time_utc DESC
        LIMIT 5
    """, (SYMBOL, TIMEFRAME)).fetchall()

    account = conn.execute("""
        SELECT currency, initial_balance, cash_balance, realized_pnl
        FROM paper_account
        WHERE account_id = 1
    """).fetchone()

print("Database:", DB.resolve())
print(f"{SYMBOL} {TIMEFRAME} candle count:", count)
print("\nLatest five candles:")
for row in latest:
    print(row)
print("\nVirtual account:", account)
