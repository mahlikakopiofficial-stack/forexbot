"""Additive MT5 history sync for GOLD/EURUSD/GBPUSD.

Reads completed MT5 candles only and writes validated OHLC history into the
existing market_candles table. It never sends trade requests. MT5 rate
timestamps are Unix timestamps and are stored as UTC.
"""
from __future__ import annotations
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import MetaTrader5 as mt5

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "forex_lab.db"
MT5_PATH = os.environ.get("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
HISTORY_COUNT = int(os.environ.get("RESEARCH_HISTORY_BARS", "20000"))
TIMEFRAMES = {"M5": mt5.TIMEFRAME_M5, "H1": mt5.TIMEFRAME_H1}
ASSETS = {
    "GOLD": os.environ.get("RESEARCH_GOLD_SYMBOL", "").strip(),
    "EURUSD": os.environ.get("RESEARCH_EURUSD_SYMBOL", "EURUSD#").strip(),
    "GBPUSD": os.environ.get("RESEARCH_GBPUSD_SYMBOL", "").strip(),
}

def utc_text(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def validate_rate(rate, symbol: str, timeframe: str):
    stamp = utc_text(rate["time"])
    values = [float(rate[name]) for name in ("open", "high", "low", "close")]
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError(f"{symbol} {timeframe}: invalid price at {stamp}")
    open_price, high, low, close = values
    if low > min(open_price, close) or high < max(open_price, close) or low > high:
        raise ValueError(f"{symbol} {timeframe}: invalid OHLC at {stamp}")
    return (
        symbol, timeframe, stamp, open_price, high, low, close,
        int(rate["tick_volume"]), int(rate["spread"]), int(rate["real_volume"]),
    )

def main() -> int:
    if not DB_FILE.is_file():
        raise SystemExit(f"Existing database not found: {DB_FILE}. Will not create or replace it.")
    if not Path(MT5_PATH).is_file():
        raise SystemExit(f"MT5 terminal not found: {MT5_PATH}")
    if not 100 <= HISTORY_COUNT <= 100000:
        raise SystemExit("RESEARCH_HISTORY_BARS must be between 100 and 100000")
    if not ASSETS["GOLD"] or not ASSETS["GBPUSD"]:
        raise SystemExit(
            "Set RESEARCH_GOLD_SYMBOL and RESEARCH_GBPUSD_SYMBOL to exact broker "
            "symbols from diagnose_research_symbols.py. EURUSD defaults to EURUSD#."
        )
    if not mt5.initialize(path=MT5_PATH, timeout=15000):
        raise SystemExit(f"MT5 initialization failed: {mt5.last_error()}")

    all_rows = []
    try:
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            raise RuntimeError("MT5 terminal is disconnected")
        for asset, symbol in ASSETS.items():
            info = mt5.symbol_info(symbol)
            if info is None:
                raise RuntimeError(f"{asset}: broker symbol {symbol!r} not found; run symbol diagnostic.")
            if not info.visible and not mt5.symbol_select(symbol, True):
                raise RuntimeError(f"{asset}: cannot select {symbol}: {mt5.last_error()}")
            for timeframe_name, timeframe_value in TIMEFRAMES.items():
                rates = mt5.copy_rates_from_pos(symbol, timeframe_value, 1, HISTORY_COUNT)
                if rates is None or len(rates) == 0:
                    raise RuntimeError(f"{asset} {timeframe_name}: no history: {mt5.last_error()}")
                rows = [validate_rate(rate, symbol, timeframe_name)
                        for rate in sorted(rates, key=lambda item: int(item["time"]))]
                stamps = [row[2] for row in rows]
                if len(stamps) != len(set(stamps)) or stamps != sorted(stamps):
                    raise RuntimeError(f"{asset} {timeframe_name}: duplicate or unordered UTC candles")
                all_rows.extend(rows)
                print(f"Fetched {asset} ({symbol}) {timeframe_name}: {len(rows)} candles, {stamps[0]} to {stamps[-1]}")
    finally:
        mt5.shutdown()

    # Validate schema and all conflicts before inserting any rows.
    with sqlite3.connect(DB_FILE, timeout=20) as conn:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='market_candles'"
        ).fetchone()
        if table is None:
            raise RuntimeError("Existing database has no market_candles table; no changes made.")
        existing_rows = conn.execute(
            "SELECT symbol, timeframe, time_utc, open, high, low, close FROM market_candles"
        ).fetchall()
        existing = {(r[0], r[1], r[2]): r[3:] for r in existing_rows}
        for row in all_rows:
            key = (row[0], row[1], row[2])
            old = existing.get(key)
            if old is not None and any(abs(float(a) - float(b)) > 1e-8 for a, b in zip(old, row[3:7])):
                raise RuntimeError(f"Existing candle conflicts at {key}; no rows inserted.")
        before = conn.total_changes
        conn.executemany("""
            INSERT OR IGNORE INTO market_candles (
                symbol, timeframe, time_utc, open, high, low, close,
                tick_volume, spread, real_volume
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, all_rows)
        inserted = conn.total_changes - before
        conn.commit()

    print("\nHistory sync completed.")
    print("Assets:", ", ".join(f"{key}={value}" for key, value in ASSETS.items()))
    print("Timeframes: M5, H1")
    print("Validated rows:", len(all_rows))
    print("New rows inserted:", inserted)
    print("Existing database preserved; sync is additive.")
    print("No trading or order requests were made.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
