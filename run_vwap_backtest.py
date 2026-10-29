"""Historical M15 session-VWAP crossover paper backtest.

The strategy uses MT5 tick volume as a proxy for Forex activity. No broker
connection or live orders are used by this script.
"""
import argparse
import os
from pathlib import Path

from backtest import POINT_SIZE, load_history, run_backtest
from backtest_report import write_report
from vwap_strategy import vwap_crossover_signals


def make_vwap_strategy(history, session_timezone="Europe/Athens"):
    """Precompute causal signals once, then adapt them to backtest prefixes."""
    signals = vwap_crossover_signals(history, session_timezone=session_timezone)

    def strategy(history_so_far):
        index = len(history_so_far) - 1
        if index < 0 or index >= len(signals):
            return "HOLD"
        return signals[index]

    return strategy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--starting-balance", type=float, default=100.0)
    parser.add_argument("--units", type=float, default=50.0)
    parser.add_argument("--point-size", type=float, default=POINT_SIZE)
    parser.add_argument("--slippage-points", type=float, default=1.0)
    parser.add_argument("--commission-per-side", type=float, default=0.0)
    parser.add_argument("--stop-loss-pips", type=float, default=20.0)
    parser.add_argument("--take-profit-pips", type=float, default=40.0)
    parser.add_argument(
        "--session-timezone",
        default=os.environ.get("MT5_SERVER_TIMEZONE", "Europe/Athens"),
        help="Broker-local timezone used to reset session VWAP",
    )
    parser.add_argument("--output-dir", default="reports/vwap_m15")
    args = parser.parse_args()

    try:
        history = load_history()
        strategy = make_vwap_strategy(history, args.session_timezone)
        result = run_backtest(
            history=history,
            strategy=strategy,
            starting_balance=args.starting_balance,
            units=args.units,
            point_size=args.point_size,
            slippage_points=args.slippage_points,
            commission_per_side=args.commission_per_side,
            stop_loss_pips=args.stop_loss_pips,
            take_profit_pips=args.take_profit_pips,
        )
    except (OSError, ValueError) as exc:
        print(f"VWAP BACKTEST FAILED: {exc}")
        return 2

    result["strategy_rules"] = (
        "M15 session VWAP: BUY when a completed close crosses from at/below "
        "to above broker-local-day VWAP; SELL when it crosses from at/above "
        "to below; close and reverse on the opposite cross; execute on the "
        "next candle open; exits also protected by provisional "
        f"{args.stop_loss_pips}-pip SL and {args.take_profit_pips}-pip TP."
    )
    result["assumptions"]["vwap_session_timezone"] = args.session_timezone
    result["assumptions"]["vwap_weighting"] = "MT5 tick_volume proxy (not centralized Forex volume)"
    paths = write_report(result, output_dir=args.output_dir)

    print("=== M15 SESSION-VWAP PAPER BACKTEST ===")
    print("Mode: historical paper simulation; no broker orders")
    print("Symbol:", result["assumptions"]["symbol"])
    print("Session timezone:", args.session_timezone)
    print("VWAP weighting: MT5 tick volume proxy")
    print("Candles:", len(history))
    print("Date range:", history["time_utc"].iloc[0].isoformat(), "->", history["time_utc"].iloc[-1].isoformat())
    print(f"Starting balance: {result['starting_balance']:.2f}")
    print(f"Final balance: {result['final_balance']:.2f}")
    print(f"Net P&L: {result['net_pnl_usd']:.4f}")
    print(f"Return: {result['return_pct']:.3f}%")
    print("Trades:", result["trade_count"])
    print("Wins / losses:", result["wins"], "/", result["losses"])
    print(f"Win rate: {result['win_rate_pct']:.2f}%")
    print("Profit factor:", result["profit_factor"])
    print(f"Maximum drawdown: {result['max_drawdown_pct']:.3f}%")
    print("Orders sent: 0")
    print("Reports:")
    for name, path in paths.items():
        print(f"  {name}: {Path(path).resolve()}")
    print("Tick volume is an FX proxy, spread/slippage are approximations, and results do not guarantee future performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
