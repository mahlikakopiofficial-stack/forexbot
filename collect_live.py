import logging
import math
import os
import sqlite3
import time

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "data" / "forex_lab.db"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "live_collector.log"

MT5_PATH = os.environ.get(
    "MT5_PATH",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
)

SYMBOL = "EURUSD"
TIMEFRAME_NAME = "M15"
TIMEFRAME = mt5.TIMEFRAME_M15
POLL_SECONDS = 30

# Selected from the observed XM server-time discrepancy.
# Refuse to write data if live-tick validation fails.
SERVER_TIMEZONE = ZoneInfo("Europe/Athens")


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(
        LOG_FILE,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[console, file_handler],
        force=True,
    )


def server_epoch_to_utc(raw_timestamp):
    """
    Convert an MT5 timestamp interpreted as broker wall-clock time
    into UTC. This assumption must be validated against live ticks.
    """
    encoded = datetime.fromtimestamp(
        float(raw_timestamp),
        tz=timezone.utc,
    )

    wall_time = encoded.replace(tzinfo=None)

    first = wall_time.replace(
        tzinfo=SERVER_TIMEZONE,
        fold=0,
    )
    second = wall_time.replace(
        tzinfo=SERVER_TIMEZONE,
        fold=1,
    )

    if first.utcoffset() != second.utcoffset():
        raise ValueError(
            f"Ambiguous broker-local timestamp: {wall_time}"
        )

    result = first.astimezone(timezone.utc)

    if (
        result.astimezone(SERVER_TIMEZONE).replace(tzinfo=None)
        != wall_time
    ):
        raise ValueError(
            f"Invalid broker-local timestamp: {wall_time}"
        )

    return result


def validate_prices(rate):
    prices = [
        float(rate[name])
        for name in ("open", "high", "low", "close")
    ]

    if not all(math.isfinite(p) and p > 0 for p in prices):
        raise ValueError("Invalid candle price values")

    open_price, high, low, close = prices

    if (
        high < max(prices)
        or low > min(prices)
        or low > high
    ):
        raise ValueError("Invalid candle OHLC relationship")

    return open_price, high, low, close


def save_completed_candles(rates, now_utc):
    inserted = 0

    sql = """
        INSERT OR IGNORE INTO market_candles (
            symbol, timeframe, time_utc,
            open, high, low, close,
            tick_volume, spread, real_volume
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    with sqlite3.connect(DB_FILE, timeout=10) as conn:
        conn.execute("PRAGMA foreign_keys = ON")

        for rate in rates:
            candle_time = server_epoch_to_utc(rate["time"])

            if (candle_time - now_utc).total_seconds() > 60:
                raise ValueError(
                    "Candle timestamp is in the future: "
                    f"{candle_time.isoformat()}. "
                    "No unvalidated candle should be stored."
                )

            open_price, high, low, close = validate_prices(rate)

            cursor = conn.execute(
                sql,
                (
                    SYMBOL,
                    TIMEFRAME_NAME,
                    candle_time.isoformat(
                        timespec="seconds"
                    ).replace("+00:00", "Z"),
                    open_price,
                    high,
                    low,
                    close,
                    int(rate["tick_volume"]),
                    int(rate["spread"]),
                    int(rate["real_volume"]),
                ),
            )

            inserted += cursor.rowcount

    return inserted


def main():
    setup_logging()

    if not Path(MT5_PATH).is_file():
        logging.error("MT5 terminal not found: %s", MT5_PATH)
        return 1

    if not DB_FILE.is_file():
        logging.error("Database not found: %s", DB_FILE)
        return 1

    logging.info("Starting read-only Forex data collector")
    logging.info("Symbol=%s timeframe=%s", SYMBOL, TIMEFRAME_NAME)
    logging.info("Database=%s", DB_FILE)
    logging.info(
        "Computer UTC=%s",
        datetime.now(timezone.utc).isoformat(),
    )
    logging.info("No live orders will be submitted")

    if not mt5.initialize(path=MT5_PATH, timeout=15000):
        logging.error("MT5 initialization failed: %s", mt5.last_error())
        return 2

    try:
        terminal = mt5.terminal_info()

        if terminal is None or not terminal.connected:
            logging.error("MT5 terminal is not connected")
            return 3

        account = mt5.account_info()
        logging.info(
            "Broker server=%s",
            account.server if account else "unavailable",
        )

        if not mt5.symbol_select(SYMBOL, True):
            logging.error("Symbol selection failed: %s", mt5.last_error())
            return 4

        while True:
            try:
                tick = mt5.symbol_info_tick(SYMBOL)

                if tick is None:
                    logging.warning(
                        "No live tick available: %s",
                        mt5.last_error(),
                    )
                    time.sleep(POLL_SECONDS)
                    continue

                raw_tick_time = (
                    tick.time_msc / 1000.0
                    if tick.time_msc
                    else float(tick.time)
                )

                tick_utc = server_epoch_to_utc(raw_tick_time)
                now_utc = datetime.now(timezone.utc)
                tick_age = (now_utc - tick_utc).total_seconds()

                logging.info(
                    "Tick UTC=%s age_seconds=%.1f bid=%s ask=%s",
                    tick_utc.isoformat(),
                    tick_age,
                    tick.bid,
                    tick.ask,
                )

                # Fail closed if the selected timezone mapping does
                # not agree with a fresh live quote.
                if abs(tick_age) > 300:
                    logging.error(
                        "Timestamp validation failed. "
                        "Skipping database writes this cycle."
                    )
                else:
                    terminal = mt5.terminal_info()

                    if terminal is None or not terminal.connected:
                        logging.warning("MT5 terminal disconnected")
                    else:
                        # Position zero is the forming candle.
                        # Position one starts with completed candles.
                        rates = mt5.copy_rates_from_pos(
                            SYMBOL,
                            TIMEFRAME,
                            1,
                            5,
                        )

                        if rates is None or len(rates) == 0:
                            logging.warning(
                                "No candle data: %s",
                                mt5.last_error(),
                            )
                        else:
                            inserted = save_completed_candles(
                                rates,
                                now_utc,
                            )

                            latest_candle = max(
                                server_epoch_to_utc(rate["time"])
                                for rate in rates
                            )

                            logging.info(
                                "Retrieved=%d inserted=%d "
                                "latest_completed_utc=%s",
                                len(rates),
                                inserted,
                                latest_candle.isoformat(),
                            )

            except Exception:
                logging.exception("Collector cycle failed")

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        logging.info("Collector stopped by user")

    finally:
        mt5.shutdown()
        logging.info("MT5 connection closed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())