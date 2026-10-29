from backtest import load_history, run_backtest
from backtest_report import write_report


def hold_only_strategy(history):
    # Intentionally generate no trading signals.
    # This validates the pipeline without assuming your strategy.
    return "HOLD"


def main():
    print("Loading historical candles...")
    history = load_history()

    print("Candles loaded:", len(history))
    print("First candle:", history["time_utc"].iloc[0])
    print("Last candle:", history["time_utc"].iloc[-1])

    print("\nRunning no-trade smoke test...")

    result = run_backtest(
        history=history,
        strategy=hold_only_strategy,
        starting_balance=100.0,
        units=50.0,
        slippage_points=1.0,
        commission_per_side=0.0,
    )

    if result["trade_count"] != 0:
        raise RuntimeError(
            "Smoke test failed: HOLD strategy generated trades"
        )

    if abs(result["final_balance"] - 100.0) > 1e-9:
        raise RuntimeError(
            "Smoke test failed: virtual balance changed"
        )

    paths = write_report(
        result,
        output_dir="reports/smoke_test",
    )

    print("\nSMOKE TEST PASSED")
    print("Trades:", result["trade_count"])
    print(f"Final virtual balance: ${result['final_balance']:.2f}")
    print("Reports created:")

    for name, path in paths.items():
        print(f"{name}: {path.resolve()}")

    print("\nNo trades were opened or sent to MT5.")


if __name__ == "__main__":
    main()