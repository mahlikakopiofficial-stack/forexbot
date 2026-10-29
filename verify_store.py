import os
import sqlite3
from pathlib import Path

db = Path("data/forex_lab.db")

if not db.exists():
    raise SystemExit(f"Database not found: {db.resolve()}")

with sqlite3.connect(db) as conn:
    count = conn.execute("""
        SELECT COUNT(*)
        FROM market_candles
        WHERE symbol = 'EURUSD' AND timeframe = 'M15'
    """).fetchone()[0]

    latest = conn.execute("""
        SELECT time_utc, open, high, low, close
        FROM market_candles
        WHERE symbol = 'EURUSD' AND timeframe = 'M15'
        ORDER BY time_utc DESC
        LIMIT 5
    """).fetchall()

    account = conn.execute("""
        SELECT currency, initial_balance, cash_balance, realized_pnl
        FROM paper_account
        WHERE account_id = 1
    """).fetchone()

print("Database:", db.resolve())
print("EURUSD M15 candle count:", count)
print("\nLatest five candles:")
for row in latest:
    print(row)

print("\nVirtual account:", account)