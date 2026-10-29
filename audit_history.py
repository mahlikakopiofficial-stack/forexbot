import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
CSV_FILE = BASE_DIR / "data" / "eurusd_m15_utc_corrected.csv"
DB_FILE = BASE_DIR / "data" / "forex_lab.db"

TIMEFRAME_MINUTES = 15


def main():
    if not CSV_FILE.is_file():
        raise SystemExit(f"CSV not found: {CSV_FILE}")

    if not DB_FILE.is_file():
        raise SystemExit(f"Database not found: {DB_FILE}")

    df = pd.read_csv(CSV_FILE)

    required = ["time", "open", "high", "low", "close"]
    missing_columns = [c for c in required if c not in df.columns]

    if missing_columns:
        raise SystemExit(f"Missing CSV columns: {missing_columns}")

    original_count = len(df)

    df["time"] = pd.to_datetime(
        df["time"], utc=True, errors="coerce"
    )

    for column in ["open", "high", "low", "close"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    bad_time = int(df["time"].isna().sum())
    duplicate_times = int(df["time"].duplicated().sum())
    chronological = bool(df["time"].is_monotonic_increasing)

    valid_times = df["time"].dropna()

    if valid_times.empty:
        raise SystemExit("No valid timestamps were found.")

    aligned = (
        (valid_times.dt.minute % TIMEFRAME_MINUTES == 0)
        & (valid_times.dt.second == 0)
    )
    misaligned_times = int((~aligned).sum())

    prices = df[["open", "high", "low", "close"]]
    finite_prices = prices.notna().all(axis=1)

    ohlc_valid = (
        (df["low"] <= df["open"])
        & (df["low"] <= df["close"])
        & (df["high"] >= df["open"])
        & (df["high"] >= df["close"])
        & (df["low"] <= df["high"])
        & (df[["open", "high", "low", "close"]] > 0).all(axis=1)
    )

    invalid_ohlc = int(
        (~finite_prices | ~ohlc_valid).sum()
    )

    now_utc = pd.Timestamp(datetime.now(timezone.utc))
    future_rows = int(
        (df["time"] > now_utc + pd.Timedelta(minutes=1)).sum()
    )

    ordered_times = valid_times.sort_values()
    gaps = ordered_times.diff().dropna()

    gaps_over_15m = int(
        (gaps > pd.Timedelta(minutes=TIMEFRAME_MINUTES)).sum()
    )

    largest_gap = (
        str(gaps.max()) if not gaps.empty else "None"
    )

    with sqlite3.connect(DB_FILE) as conn:
        db_count = conn.execute("""
            SELECT COUNT(*)
            FROM market_candles
            WHERE symbol = 'EURUSD' AND timeframe = 'M15'
        """).fetchone()[0]

        db_latest = conn.execute("""
            SELECT MAX(time_utc)
            FROM market_candles
            WHERE symbol = 'EURUSD' AND timeframe = 'M15'
        """).fetchone()[0]

        account = conn.execute("""
            SELECT initial_balance, cash_balance, realized_pnl
            FROM paper_account
            WHERE account_id = 1
        """).fetchone()

    print("=== EURUSD M15 DATA AUDIT ===")
    print("CSV:", CSV_FILE.resolve())
    print("Database:", DB_FILE.resolve())
    print("Audit time UTC:", now_utc.isoformat())
    print("CSV candle rows:", original_count)
    print("Invalid timestamps:", bad_time)
    print("Duplicate timestamps:", duplicate_times)
    print("Chronological order:", chronological)
    print("Misaligned 15-minute timestamps:", misaligned_times)
    print("Invalid OHLC rows:", invalid_ohlc)
    print("Future-dated rows:", future_rows)
    print("Gaps greater than 15 minutes:", gaps_over_15m)
    print("Largest observed gap:", largest_gap)

    print("\nFirst CSV candle:", valid_times.min())
    print("Last CSV candle:", valid_times.max())
    print("Database candle count:", db_count)
    print("Latest database candle UTC:", db_latest)

    if db_latest:
        latest = pd.to_datetime(db_latest, utc=True)
        completed_at = latest + pd.Timedelta(minutes=15)
        age_after_close = now_utc - completed_at

        print(
            "Time since latest candle should have closed:",
            age_after_close,
        )

        if age_after_close > pd.Timedelta(minutes=30):
            print(
                "WARNING: Database may be stale. "
                "Refresh live data before backtesting."
            )

    print("\nVirtual account:", account)

    checks = {
        "nonempty CSV": original_count > 0,
        "valid timestamps": bad_time == 0,
        "no duplicate timestamps": duplicate_times == 0,
        "chronological ordering": chronological,
        "15-minute alignment": misaligned_times == 0,
        "valid OHLC": invalid_ohlc == 0,
        "no future-dated bars": future_rows == 0,
    }

    print("\n=== CHECK RESULTS ===")

    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'}: {name}")

    if not all(checks.values()):
        print("\nData needs attention before backtesting.")
        return 1

    print(
        "\nInternal data checks passed. "
        "Timestamp provenance still requires independent validation."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())