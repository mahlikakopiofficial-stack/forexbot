"""Read-only discovery of broker symbol names for research instruments.

May add candidate symbols to Market Watch to request quotes. Never reads or
prints account identifiers and never sends trade requests.
"""
from __future__ import annotations
import os
from pathlib import Path
import MetaTrader5 as mt5

MT5_PATH = os.environ.get("MT5_PATH", r"C:\Program Files\MetaTrader 5\terminal64.exe")
NEEDLES = {"GOLD": ("GOLD", "XAU"), "EURUSD": ("EURUSD",), "GBPUSD": ("GBPUSD",)}

def main() -> int:
    if not Path(MT5_PATH).is_file():
        raise SystemExit(f"MT5 terminal not found: {MT5_PATH}")
    if not mt5.initialize(path=MT5_PATH, timeout=15000):
        raise SystemExit(f"MT5 initialization failed: {mt5.last_error()}")
    try:
        terminal = mt5.terminal_info()
        if terminal is None or not terminal.connected:
            raise SystemExit("MT5 terminal is not connected")
        symbols = mt5.symbols_get()
        if symbols is None:
            raise SystemExit(f"Could not list symbols: {mt5.last_error()}")
        for asset, needles in NEEDLES.items():
            print(f"\n{asset} candidates:")
            matches = [item for item in symbols if any(n in item.name.upper() for n in needles)]
            if not matches:
                print("  No matching broker symbol found")
                continue
            for item in matches:
                selected = bool(item.select)
                if not selected:
                    selected = bool(mt5.symbol_select(item.name, True))
                tick = mt5.symbol_info_tick(item.name) if selected else None
                info = mt5.symbol_info(item.name)
                quote = "no current quote"
                if tick is not None and tick.bid > 0 and tick.ask >= tick.bid:
                    quote = f"Bid={tick.bid} Ask={tick.ask}"
                mode = getattr(info, "trade_mode", "unknown") if info else "unknown"
                digits = getattr(info, "digits", "unknown") if info else "unknown"
                print(f"  {item.name} | selected={selected} | trade_mode={mode} | digits={digits} | {quote}")
    finally:
        mt5.shutdown()
    print("\nDiscovery only: no account details printed and no orders submitted.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
