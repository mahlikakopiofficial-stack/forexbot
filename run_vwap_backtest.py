"""Historical Gold M5 rolling-VWAP(200) paper backtest; sends no orders."""
import argparse
import os
from pathlib import Path

from backtest import load_history, run_backtest
from backtest_report import write_report
from vwap_strategy import DEFAULT_VWAP_PERIOD, vwap_crossover_signals


def make_vwap_strategy(history, period=DEFAULT_VWAP_PERIOD):
    """Precompute causal rolling-VWAP signals and adapt them to history prefixes."""
    signals = vwap_crossover_signals(history, period=period)

    def strategy(history_so_far):
        index = len(history_so_far) - 1
        if index < 0 or index >= len(signals):
            return "HOLD"
        return signals[index]

    return strategy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--starting-balance", type=float, default=5000.0)
    parser.add_argument("--units", type=float, default=1.0)
    parser.add_argument("--point-size", type=float, default=float(os.environ.get("FOREX_POINT_SIZE", "0.01")))
    parser.add_argument("--slippage-points", type=float, default=1.0)
    parser.add_argument("--commission-per-side", type=float, default=0.0)
    parser.add_argument("--stop-loss-pips", type=float, default=500.0)
    parser.add_argument("--take-profit-pips", type=float, default=1000.0)
    parser.add_argument("--period", type=int, default=DEFAULT_VWAP_PERIOD)
    parser.add_argument("--output-dir", default="reports/gold_vwap200_m5")
    args = parser.parse_args()

    if args.period < 2:
        parser.error("--period must be at least 2")

    try:
        history = load_history()
        strategy = make_vwap_strategy(history, args.period)
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
        f"M5 rolling VWAP({args.period}): BUY when a completed close crosses "
        "from at/below to above the rolling VWAP; SELL on the opposite cross; "
        "close/reverse on the next candle open. SL/TP use the paper model's "
        f"price-point scaling ({args.stop_loss_pips} and "
        f"{args.take_profit_pips} pips at point size {args.point_size})."
    )
    result["assumptions"]["vwap_period"] = args.period
    result["assumptions"]["vwap_weighting"] = "MT5 tick_volume proxy for Gold CFD activity"
    result["assumptions"]["symbol"] = os.environ.get("FOREX_SYMBOL", "GOLD#").strip()
    paths = write_report(result, output_dir=args.output_dir)

    print("=== GOLD M5 ROLLING VWAP PAPER BACKTEST ===")
    print("Mode: historical paper simulation; no broker orders")
    print("Symbol:", result["assumptions"]["symbol"])
    print("Timeframe: M5 | VWAP period:", args.period)
    print("VWAP weighting: MT5 tick-volume proxy")
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
    for name, output_path in paths.items():
        print(f"  {name}: {Path(output_path).resolve()}")
    print("Historical bar spreads/slippage are approximations; results do not guarantee future performance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
