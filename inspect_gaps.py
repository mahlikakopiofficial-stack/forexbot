import sqlite3
from pathlib import Path

import pandas as pd

DB = Path("data/forex_lab.db")
TIMEFRAME = pd.Timedelta(minutes=15)

with sqlite3.connect(DB) as conn:
    df = pd.read_sql_query("""
        SELECT time_utc
        FROM market_candles
        WHERE symbol = 'EURUSD' AND timeframe = 'M15'
        ORDER BY time_utc
    """, conn)

if df.empty:
    raise SystemExit("No EURUSD candles found.")

df["time_utc"] = pd.to_datetime(df["time_utc"], utc=True)
delta = df["time_utc"].diff()

gaps = df.loc[
    delta > TIMEFRAME,
    ["time_utc"]
].copy()

gaps["previous_candle_utc"] = df["time_utc"].shift(1).loc[gaps.index]
gaps["gap"] = delta.loc[gaps.index]
gaps["missing_15m_slots"] = (
    gaps["gap"] / TIMEFRAME
).astype(int) - 1

print("Total candles:", len(df))
print("Gaps greater than 15 minutes:", len(gaps))
print()

for _, row in gaps.iterrows():
    previous = row["previous_candle_utc"]
    following = row["time_utc"]

    print(
        f"Previous: {previous.isoformat()} | "
        f"Next: {following.isoformat()} | "
        f"Gap: {row['gap']} | "
        f"Missing 15m slots: {row['missing_15m_slots']}"
    )

    if (
        previous.weekday() == 4
        and following.weekday() in (6, 0)
        and row["gap"] >= pd.Timedelta(days=1)
    ):
        print("  Classification: likely weekend closure")
    else:
        print("  Classification: inspect session or missing data")

print("\nRead-only inspection complete.")