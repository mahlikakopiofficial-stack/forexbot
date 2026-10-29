"""Read-only diagnosis for MT5 account permissions and EURUSD symbol availability.

Prints no account login, balance, password, or credentials. Never sends orders.
"""
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import time

import MetaTrader5 as mt5

MT5_PATH = os.environ.get(
    "MT5_PATH",
    r"C:\Program Files\MetaTrader 5\terminal64.exe",
)
SERVER_TZ = os.environ.get("MT5_SERVER_TIMEZONE", "Europe/Athens")


def safe_int(obj, key):
    value = getattr(obj, key, None)
    return value if value is not None else "unavailable"


def main() -> int:
    if not Path(MT5_PATH).is_file():
        print("ERROR: MT5 terminal not found:", MT5_PATH)
        print("Set MT5_PATH to the running terminal64.exe path.")
        return 2

    if not mt5.initialize(path=MT5_PATH, timeout=15000):
        print("ERROR: initialize failed:", mt5.last_error())
        return 2

    try:
        now = datetime.now(timezone.utc)
        terminal = mt5.terminal_info()
        account = mt5.account_info()

        print("=== READ-ONLY MT5 BROKER DIAGNOSTIC ===")
        print("Computer UTC:", now.isoformat())
        print("MT5 version:", mt5.version())
        print("Python package:", mt5.__version__)
        print("Terminal connected:", bool(terminal and terminal.connected))
        print("Terminal trade allowed:", safe_int(terminal, "trade_allowed"))
        print("Terminal API disabled:", safe_int(terminal, "tradeapi_disabled"))
        print("Terminal path:", safe_int(terminal, "path"))

        if account is None:
            print("Account info unavailable:", mt5.last_error())
            return 2

        trade_mode_names = {
            getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", object()): "DEMO",
            getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", object()): "CONTEST",
            getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", object()): "REAL",
        }
        print("Broker server:", account.server)
        print(
            "Account mode:",
            trade_mode_names.get(account.trade_mode, f"UNKNOWN({account.trade_mode})"),
        )
        print("Account trading allowed:", safe_int(account, "trade_allowed"))
        print("Account expert trading allowed:", safe_int(account, "trade_expert"))
        print("Deposit currency:", account.currency)

        print("\n=== SYMBOL CONSTANTS ===")
        for name in (
            "SYMBOL_TRADE_MODE_DISABLED",
            "SYMBOL_TRADE_MODE_LONGONLY",
            "SYMBOL_TRADE_MODE_SHORTONLY",
            "SYMBOL_TRADE_MODE_CLOSEONLY",
            "SYMBOL_TRADE_MODE_FULL",
            "SYMBOL_CHART_MODE_BID",
            "SYMBOL_CHART_MODE_LAST",
            "SYMBOL_TRADE_EXECUTION_MARKET",
        ):
            print(f"{name}={getattr(mt5, name, 'not exposed by package')}")

        names = ["EURUSD"]
        all_symbols = mt5.symbols_get()
        if all_symbols is None:
            print("\nCould not enumerate symbols:", mt5.last_error())
        else:
            matches = [
                s.name for s in all_symbols
                if "EURUSD" in s.name.upper()
            ]
            print("\nEURUSD-name candidates:", matches[:100])
            names = list(dict.fromkeys(names + matches))

        for name in names:
            info = mt5.symbol_info(name)
            if info is None:
                print(f"\n=== {name} ===\nsymbol_info=None; error={mt5.last_error()}")
                continue

            selected_before = bool(getattr(info, "select", False))
            if not selected_before:
                selection_ok = bool(mt5.symbol_select(name, True))
                print(f"\n{name}: symbol_select(True)={selection_ok}")
                if not selection_ok:
                    print("Could not select symbol:", mt5.last_error())
                    continue
                # Symbol metadata may update immediately, but the first tick can
                # arrive shortly afterwards. Wait a bounded 5 seconds only.
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    info = mt5.symbol_info(name)
                    tick = mt5.symbol_info_tick(name)
                    if (
                        info is not None and tick is not None
                        and float(tick.bid) > 0 and float(tick.ask) >= float(tick.bid)
                    ):
                        break
                    time.sleep(0.25)
                info = mt5.symbol_info(name)
                if info is None:
                    print("Symbol info disappeared after selection.")
                    continue

            disabled_value = getattr(mt5, "SYMBOL_TRADE_MODE_DISABLED", 0)
            long_value = getattr(mt5, "SYMBOL_TRADE_MODE_LONGONLY", 1)
            short_value = getattr(mt5, "SYMBOL_TRADE_MODE_SHORTONLY", 2)
            close_value = getattr(mt5, "SYMBOL_TRADE_MODE_CLOSEONLY", 3)
            full_value = getattr(mt5, "SYMBOL_TRADE_MODE_FULL", 4)
            modes = {
                disabled_value: "DISABLED",
                long_value: "LONG_ONLY",
                short_value: "SHORT_ONLY",
                close_value: "CLOSE_ONLY",
                full_value: "FULL",
            }

            print(f"\n=== SYMBOL {name} ===")
            print("Reported symbol name:", info.name)
            print("Path:", info.path)
            print("Visible / selected:", info.visible, "/", info.select)
            print("Was selected before diagnostic:", selected_before)
            print("Trade mode raw:", info.trade_mode)
            print("Trade mode meaning:", modes.get(info.trade_mode, "UNKNOWN"))
            print("Chart mode:", info.chart_mode)
            print("Digits / point:", info.digits, "/", info.point)
            print("Execution mode:", info.trade_exemode)
            print("Order mode flags:", info.order_mode)
            print("Filling mode flags:", info.filling_mode)
            print("Minimum / step / maximum lots:",
                  info.volume_min, "/", info.volume_step, "/", info.volume_max)
            print("Minimum stop distance (points):", info.trade_stops_level)
            print("Bid / ask:", info.bid, "/", info.ask)

            tick = mt5.symbol_info_tick(name)
            if tick is None or float(tick.bid) <= 0 or float(tick.ask) < float(tick.bid):
                print("Usable tick unavailable after selection:", mt5.last_error())
                if tick is not None:
                    print("Returned bid/ask:", tick.bid, "/", tick.ask)
                continue

            raw_seconds = (
                tick.time_msc / 1000.0 if tick.time_msc else float(tick.time)
            )
            raw_utc = datetime.fromtimestamp(raw_seconds, tz=timezone.utc)
            try:
                server_tz = ZoneInfo(SERVER_TZ)
                wall = raw_utc.replace(tzinfo=None)
                local = wall.replace(tzinfo=server_tz, fold=0)
                adjusted = local.astimezone(timezone.utc)
                age = (now - adjusted).total_seconds()
                print("Tick raw interpreted UTC:", raw_utc.isoformat())
                print("Tick adjusted UTC (hypothesis only):", adjusted.isoformat())
                print("Adjusted tick age seconds:", round(age, 2))
            except Exception as exc:
                print("Could not interpret broker timestamp:", repr(exc))

        print("\nNo orders were checked or sent.")
        print("Do not change the trade-mode guard based on this output alone.")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
