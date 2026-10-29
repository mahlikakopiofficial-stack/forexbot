"""EMA-crossover integration runner for the MT5 DEMO account only.

The EMA values and stop/target distances are example plumbing defaults, not a
validated trading strategy or a profit claim. The runner starts in DRY RUN mode.
A demo order can be sent only after the account/server guards pass and the
explicit MT5_DEMO_ORDER_ENABLED=YES_DEMO_ONLY token is supplied.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ema_strategy import ema_crossover_signal
from mt5_demo_executor import (
    BASE_DIR,
    DEFAULT_MT5_PATH,
    DemoConfig,
    DemoExecutionError,
    MT5DemoExecutor,
    OrderResultUncertain,
    broker_timestamp_to_utc,
    mt5,
)


STATE_DB = BASE_DIR / "data" / "demo_runner.sqlite3"
SYMBOL = os.environ.get("FOREX_DEMO_SYMBOL", "EURUSD").strip()
TIMEFRAME_LABEL = "M15"
TIMEFRAME = getattr(mt5, "TIMEFRAME_M15", None) if mt5 is not None else None
FAST_EMA = int(os.environ.get("FOREX_DEMO_FAST_EMA", "12"))
SLOW_EMA = int(os.environ.get("FOREX_DEMO_SLOW_EMA", "26"))
VOLUME_LOTS = float(os.environ.get("FOREX_DEMO_VOLUME_LOTS", "0.01"))
STOP_LOSS_PIPS = float(os.environ.get("FOREX_DEMO_STOP_PIPS", "20"))
TAKE_PROFIT_PIPS = float(os.environ.get("FOREX_DEMO_TARGET_PIPS", "40"))
POLL_SECONDS = int(os.environ.get("FOREX_DEMO_POLL_SECONDS", "10"))
MAX_ENTRIES_PER_UTC_DAY = int(
    os.environ.get("FOREX_DEMO_MAX_ENTRIES_PER_DAY", "3")
)
MAX_DAILY_EQUITY_LOSS = float(
    os.environ.get("FOREX_DEMO_MAX_DAILY_EQUITY_LOSS", "25")
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_text(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def validate_settings() -> None:
    if not SYMBOL or SYMBOL != "EURUSD":
        raise ValueError("This initial runner only permits EURUSD.")
    if FAST_EMA < 2 or SLOW_EMA < 3 or FAST_EMA >= SLOW_EMA:
        raise ValueError("EMA settings must satisfy 2 <= fast < slow.")
    if not math.isfinite(VOLUME_LOTS) or VOLUME_LOTS <= 0:
        raise ValueError("FOREX_DEMO_VOLUME_LOTS must be positive and finite.")
    if (
        not math.isfinite(STOP_LOSS_PIPS)
        or not math.isfinite(TAKE_PROFIT_PIPS)
        or STOP_LOSS_PIPS <= 0
        or TAKE_PROFIT_PIPS <= 0
    ):
        raise ValueError("Demo stop-loss and take-profit distances must be finite and positive.")
    if POLL_SECONDS < 2 or MAX_ENTRIES_PER_UTC_DAY < 1:
        raise ValueError("Poll interval and daily entry limit are invalid.")
    if not math.isfinite(MAX_DAILY_EQUITY_LOSS) or MAX_DAILY_EQUITY_LOSS <= 0:
        raise ValueError("Daily equity loss limit must be positive and finite.")


def calculate_protective_prices(direction: str, quote: dict, info,
                                stop_pips: float = STOP_LOSS_PIPS,
                                target_pips: float = TAKE_PROFIT_PIPS) -> tuple[float, float]:
    """Return absolute broker SL/TP prices for an illustrative demo signal."""
    direction = direction.upper()
    point = float(info.point)
    digits = int(info.digits)
    pip_size = point * 10 if digits in (3, 5) else point
    distance_sl = float(stop_pips) * pip_size
    distance_tp = float(target_pips) * pip_size

    if direction == "BUY":
        reference = float(quote["ask"])
        return (
            round(reference - distance_sl, digits),
            round(reference + distance_tp, digits),
        )
    if direction == "SELL":
        reference = float(quote["bid"])
        return (
            round(reference + distance_sl, digits),
            round(reference - distance_tp, digits),
        )
    raise ValueError("Direction must be BUY or SELL")


def init_state_db(path=STATE_DB) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=10) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS demo_runner_state (
                state_key TEXT PRIMARY KEY,
                state_value TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS demo_execution_events (
                event_key TEXT PRIMARY KEY,
                candle_time_utc TEXT NOT NULL,
                action TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN ('PENDING', 'COMPLETED', 'REJECTED',
                              'DRY_RUN', 'RECONCILE_REQUIRED')
                ),
                details_json TEXT NOT NULL DEFAULT '{}',
                updated_at_utc TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS demo_daily_limits (
                utc_date TEXT PRIMARY KEY,
                opening_equity REAL NOT NULL,
                entries_count INTEGER NOT NULL DEFAULT 0
            )
        """)


def state_get(key: str, path=STATE_DB):
    with sqlite3.connect(path, timeout=10) as conn:
        row = conn.execute(
            "SELECT state_value FROM demo_runner_state WHERE state_key = ?",
            (key,),
        ).fetchone()
    return row[0] if row else None


def state_set(key: str, value: str, path=STATE_DB):
    with sqlite3.connect(path, timeout=10) as conn:
        conn.execute("""
            INSERT INTO demo_runner_state(state_key, state_value, updated_at_utc)
            VALUES (?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                state_value=excluded.state_value,
                updated_at_utc=excluded.updated_at_utc
        """, (key, value, utc_text()))


def unresolved_events(path=STATE_DB):
    with sqlite3.connect(path, timeout=10) as conn:
        return conn.execute("""
            SELECT event_key, state, details_json
            FROM demo_execution_events
            WHERE state IN ('PENDING', 'RECONCILE_REQUIRED')
            ORDER BY updated_at_utc
        """).fetchall()


def record_event(event_key, candle_time, action, event_state, details, path=STATE_DB):
    with sqlite3.connect(path, timeout=10) as conn:
        conn.execute("""
            INSERT INTO demo_execution_events(
                event_key, candle_time_utc, action, state, details_json, updated_at_utc
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(event_key) DO UPDATE SET
                state=excluded.state,
                details_json=excluded.details_json,
                updated_at_utc=excluded.updated_at_utc
        """, (
            event_key, candle_time, action, event_state,
            json.dumps(details, sort_keys=True, default=str), utc_text(),
        ))


def get_closed_bars(api, symbol: str, timeframe, count: int, timezone_name: str):
    rates = api.copy_rates_from_pos(symbol, timeframe, 1, count)
    if rates is None or len(rates) == 0:
        raise DemoExecutionError(
            f"No completed candles returned: {api.last_error()}"
        )

    rows = []
    for rate in sorted(rates, key=lambda item: int(item["time"])):
        stamp = broker_timestamp_to_utc(
            float(rate["time"]), timezone_name
        )
        rows.append({
            "time_utc": stamp,
            "open": float(rate["open"]),
            "high": float(rate["high"]),
            "low": float(rate["low"]),
            "close": float(rate["close"]),
            "spread": float(rate["spread"]),
        })

    df = pd.DataFrame(rows)
    if df["time_utc"].duplicated().any():
        raise DemoExecutionError("MT5 returned duplicate completed candles")
    if not df["time_utc"].is_monotonic_increasing:
        raise DemoExecutionError("MT5 candles are not chronological")
    for column in ("open", "high", "low", "close", "spread"):
        if not df[column].map(lambda value: pd.notna(value) and value >= 0).all():
            raise DemoExecutionError(f"MT5 candle has invalid {column}")
    if (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise DemoExecutionError("MT5 candle prices must be positive")
    if (
        (df["low"] > df[["open", "close"]].min(axis=1)).any()
        or (df["high"] < df[["open", "close"]].max(axis=1)).any()
        or (df["low"] > df["high"]).any()
    ):
        raise DemoExecutionError("MT5 returned invalid OHLC relationships")
    if (
        (df["time_utc"].dt.minute % 15 != 0).any()
        or (df["time_utc"].dt.second != 0).any()
    ):
        raise DemoExecutionError(
            "Converted timestamps are not aligned to M15; check server timezone."
        )
    if df["time_utc"].iloc[-1] > pd.Timestamp(utc_now()) + pd.Timedelta(minutes=1):
        raise DemoExecutionError("Latest completed candle is future-dated; refusing signal evaluation.")
    return df


def daily_limits(path, equity: float):
    today = utc_now().date().isoformat()
    with sqlite3.connect(path, timeout=10) as conn:
        row = conn.execute("""
            SELECT opening_equity, entries_count
            FROM demo_daily_limits WHERE utc_date = ?
        """, (today,)).fetchone()
        if row is None:
            conn.execute("""
                INSERT INTO demo_daily_limits(utc_date, opening_equity, entries_count)
                VALUES (?, ?, 0)
            """, (today, float(equity)))
            return float(equity), 0
        return float(row[0]), int(row[1])


def increment_daily_entries(path):
    today = utc_now().date().isoformat()
    with sqlite3.connect(path, timeout=10) as conn:
        conn.execute("""
            UPDATE demo_daily_limits SET entries_count = entries_count + 1
            WHERE utc_date = ?
        """, (today,))


def position_direction(position, api) -> str:
    if int(position.type) == int(api.POSITION_TYPE_BUY):
        return "BUY"
    return "SELL"


def process_latest_bar(api, executor: MT5DemoExecutor, path=STATE_DB) -> dict:
    init_state_db(path)
    pending = unresolved_events(path)
    if pending:
        raise OrderResultUncertain(
            "Unresolved execution event exists. Stop and reconcile MT5 "
            f"positions/orders before continuing: {pending[0][0]} ({pending[0][1]})"
        )

    bars = get_closed_bars(
        api, SYMBOL, TIMEFRAME, max(100, SLOW_EMA * 5),
        executor.config.server_timezone,
    )
    latest_time = utc_text(bars["time_utc"].iloc[-1].to_pydatetime())
    last_processed = state_get("last_processed_candle_utc", path)

    # On the first start, anchor to the latest completed candle and do not
    # replay historical EMA crossovers into the broker.
    if last_processed is None:
        state_set("last_processed_candle_utc", latest_time, path)
        return {"status": "INITIALIZED", "candle_time_utc": latest_time, "signal": "HOLD"}

    if latest_time <= last_processed:
        return {"status": "NO_NEW_CANDLE", "candle_time_utc": latest_time, "signal": "HOLD"}

    signal = ema_crossover_signal(
        bars["close"].tolist(), FAST_EMA, SLOW_EMA
    )
    # One idempotency key per closed candle, regardless of later signal recalculation.
    event_key = f"{SYMBOL}|{TIMEFRAME_LABEL}|{latest_time}"

    with sqlite3.connect(path, timeout=10) as conn:
        existing = conn.execute("""
            SELECT state FROM demo_execution_events WHERE event_key = ?
        """, (event_key,)).fetchone()

    if existing:
        if existing[0] in {"PENDING", "RECONCILE_REQUIRED"}:
            raise OrderResultUncertain(
                f"Event {event_key} has unresolved state {existing[0]}"
            )
        state_set("last_processed_candle_utc", latest_time, path)
        return {"status": "ALREADY_RECORDED", "candle_time_utc": latest_time, "signal": signal}

    if signal == "HOLD":
        state_set("last_processed_candle_utc", latest_time, path)
        return {"status": "NO_SIGNAL", "candle_time_utc": latest_time, "signal": signal}

    status = executor.preflight()
    account = api.account_info()
    if account is None:
        raise DemoExecutionError(f"MT5 account information unavailable: {api.last_error()}")
    opening_equity, entries_count = daily_limits(path, float(account.equity))
    daily_loss = max(0.0, opening_equity - float(account.equity))

    # When the order gate is off, evaluate and record the signal without
    # interacting with broker positions or sending an order.
    if not executor.config.orders_enabled:
        record_event(
            event_key, latest_time, signal, "DRY_RUN",
            {
                "signal": signal,
                "account_mode": status["account_mode"],
                "orders_sent": False,
                "note": "Demo order gate is off; no broker order was sent.",
            },
            path,
        )
        state_set("last_processed_candle_utc", latest_time, path)
        return {"status": "DRY_RUN", "candle_time_utc": latest_time, "signal": signal}

    positions = executor.get_positions(SYMBOL)
    if len(positions) > 1:
        raise DemoExecutionError(
            "More than one EURUSD position exists; refusing automated management."
        )

    current_position = positions[0] if positions else None
    if current_position is not None:
        if int(getattr(current_position, "magic", -1)) != executor.config.magic:
            raise DemoExecutionError(
                "EURUSD has a position not owned by this runner; refusing to manage it."
            )
        if (
            float(getattr(current_position, "sl", 0) or 0) <= 0
            or float(getattr(current_position, "tp", 0) or 0) <= 0
        ):
            raise DemoExecutionError(
                "Managed position lacks broker-side stop-loss/take-profit."
            )

        current_direction = position_direction(current_position, api)
        if signal == current_direction:
            state_set("last_processed_candle_utc", latest_time, path)
            return {"status": "POSITION_HELD", "candle_time_utc": latest_time, "signal": signal}
        action = f"CLOSE_{current_direction}"
    else:
        if daily_loss >= MAX_DAILY_EQUITY_LOSS:
            record_event(
                event_key, latest_time, signal, "REJECTED",
                {"reason": "daily equity loss limit reached", "daily_loss": daily_loss},
                path,
            )
            state_set("last_processed_candle_utc", latest_time, path)
            return {"status": "DAILY_LOSS_LIMIT", "candle_time_utc": latest_time, "signal": signal}
        if entries_count >= MAX_ENTRIES_PER_UTC_DAY:
            record_event(
                event_key, latest_time, signal, "REJECTED",
                {"reason": "daily entry limit reached", "entries_count": entries_count},
                path,
            )
            state_set("last_processed_candle_utc", latest_time, path)
            return {"status": "DAILY_ENTRY_LIMIT", "candle_time_utc": latest_time, "signal": signal}
        action = f"OPEN_{signal}"

    # Persist intent before sending. If the process crashes after submission,
    # a PENDING record blocks automatic replay on restart.
    record_event(event_key, latest_time, action, "PENDING", {"signal": signal}, path)

    try:
        if action.startswith("CLOSE_"):
            result = executor.close_managed_position(
                SYMBOL, int(current_position.ticket)
            )
        else:
            quote = executor._quote(SYMBOL, enforce_spread=True)
            info = executor._symbol_info(SYMBOL)
            sl, tp = calculate_protective_prices(signal, quote, info)
            result = executor.place_protected_market_order(
                SYMBOL, signal, VOLUME_LOTS, sl, tp
            )
            increment_daily_entries(path)

        record_event(event_key, latest_time, action, "COMPLETED", result, path)
        state_set("last_processed_candle_utc", latest_time, path)
        return {
            "status": "ORDER_COMPLETED",
            "candle_time_utc": latest_time,
            "signal": signal,
            "action": action,
            "result": result,
        }
    except OrderResultUncertain as exc:
        record_event(
            event_key, latest_time, action, "RECONCILE_REQUIRED",
            {"error": str(exc)}, path,
        )
        raise
    except DemoExecutionError as exc:
        record_event(
            event_key, latest_time, action, "REJECTED",
            {"error": str(exc)}, path,
        )
        state_set("last_processed_candle_utc", latest_time, path)
        return {
            "status": "ORDER_REJECTED",
            "candle_time_utc": latest_time,
            "signal": signal,
            "error": str(exc),
        }


RUNNER_LOCK_FILE = BASE_DIR / "data" / "demo_runner.lock"


class SingleInstanceLock:
    """Prevent two local runner processes from managing the same symbol."""

    _guard = threading.Lock()
    _held_paths: set[str] = set()

    def __init__(self, path=RUNNER_LOCK_FILE):
        self.path = Path(path)
        self.handle = None
        self.key = str(self.path.resolve())
        self.locked = False

    def acquire(self):
        with self._guard:
            if self.key in self._held_paths:
                raise DemoExecutionError(
                    "Another demo_runner instance is already running."
                )
            self._held_paths.add(self.key)

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = self.path.open("a+b")
            self.handle.seek(0, os.SEEK_END)
            if self.handle.tell() == 0:
                self.handle.write(b"\\0")
                self.handle.flush()
            self.handle.seek(0)

            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            self.locked = True
            return self
        except Exception as exc:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            with self._guard:
                self._held_paths.discard(self.key)
            if isinstance(exc, DemoExecutionError):
                raise
            raise DemoExecutionError(
                "Could not acquire runner lock; another instance may be active."
            ) from exc

    def release(self):
        try:
            if self.handle is not None:
                if self.locked:
                    self.handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
                self.handle.close()
        finally:
            self.handle = None
            self.locked = False
            with self._guard:
                self._held_paths.discard(self.key)

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="M15 EMA-crossover integration runner, MT5 demo-only."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once", action="store_true",
        help="check one cycle and exit (default)",
    )
    mode.add_argument(
        "--loop", action="store_true",
        help="poll until interrupted; demo orders still require the explicit gate",
    )
    args = parser.parse_args()

    try:
        validate_settings()
    except ValueError as exc:
        print(f"CONFIGURATION ERROR: {exc}")
        return 2

    if mt5 is None or TIMEFRAME is None:
        print("ERROR: MetaTrader5 package is unavailable.")
        return 2

    lock = SingleInstanceLock()
    try:
        lock.acquire()
    except DemoExecutionError as exc:
        print(f"RUNNER LOCK FAILED: {exc}")
        return 2

    initialized = False
    try:
        init_state_db()
        path = os.environ.get("MT5_PATH", DEFAULT_MT5_PATH)
        if not Path(path).is_file():
            print(f"ERROR: MT5 terminal not found: {path}")
            return 2
        if not mt5.initialize(path=path, timeout=15000):
            print("ERROR: MT5 initialization failed:", mt5.last_error())
            return 2
        initialized = True

        executor = MT5DemoExecutor(mt5, DemoConfig.from_env())
        try:
            status = executor.preflight()
            account = mt5.account_info()
            if account is None:
                raise DemoExecutionError(
                    f"MT5 account information unavailable: {mt5.last_error()}"
                )
            # Establish the UTC-day baseline before waiting for a signal.
            daily_limits(STATE_DB, float(account.equity))

            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)sZ %(levelname)s %(message)s",
            )
            logging.info(
                "Demo runner starting: server=%s mode=%s orders_enabled=%s "
                "strategy=EMA(%s,%s) symbol=%s timeframe=%s",
                status["server"], status["account_mode"], status["orders_enabled"],
                FAST_EMA, SLOW_EMA, SYMBOL, TIMEFRAME_LABEL,
            )
            logging.info(
                "Example settings only: lots=%s SL=%s pips TP=%s pips "
                "max_entries/day=%s max_daily_equity_loss=%s %s",
                VOLUME_LOTS, STOP_LOSS_PIPS, TAKE_PROFIT_PIPS,
                MAX_ENTRIES_PER_UTC_DAY, MAX_DAILY_EQUITY_LOSS,
                account.currency,
            )

            while True:
                try:
                    current_account = mt5.account_info()
                    if current_account is None:
                        raise DemoExecutionError(
                            f"MT5 account information unavailable: {mt5.last_error()}"
                        )
                    # Create a daily baseline on the first observation of each
                    # UTC date, even when there is no crossover signal.
                    daily_limits(STATE_DB, float(current_account.equity))

                    report = process_latest_bar(mt5, executor)
                    logging.info("Cycle: %s", json.dumps(report, default=str))
                except OrderResultUncertain:
                    logging.exception(
                        "HALTING: order state uncertain. Reconcile MT5 manually; "
                        "do not restart the runner until resolved."
                    )
                    return 3
                except DemoExecutionError:
                    logging.exception("HALTING: safety/preflight check failed.")
                    return 2

                if not args.loop:
                    return 0
                time.sleep(POLL_SECONDS)

        except DemoExecutionError as exc:
            logging.error("Startup preflight failed: %s", exc)
            return 2
    finally:
        if initialized:
            mt5.shutdown()
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
