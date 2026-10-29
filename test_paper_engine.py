import pytest

from paper_engine import simulate_round_trip


def test_buy_round_trip_includes_all_costs():
    result = simulate_round_trip(
        "BUY", 1000,
        1.10000, 1.10020,
        1.10100, 1.10120,
        slippage_per_fill=0.00001,
        commission_round_trip=0.10,
    )

    assert result["mid_pnl_usd"] == pytest.approx(1.00)
    assert result["spread_cost_usd"] == pytest.approx(0.20)
    assert result["slippage_cost_usd"] == pytest.approx(0.02)
    assert result["commission_usd"] == pytest.approx(0.10)
    assert result["net_pnl_usd"] == pytest.approx(0.68)


def test_sell_round_trip_calculation():
    result = simulate_round_trip(
        "SELL", 1000,
        1.10100, 1.10120,
        1.10000, 1.10020,
        slippage_per_fill=0.00001,
        commission_round_trip=0.10,
    )

    assert result["mid_pnl_usd"] == pytest.approx(1.00)
    assert result["net_pnl_usd"] == pytest.approx(0.68)


def test_rejects_invalid_direction():
    with pytest.raises(ValueError):
        simulate_round_trip(
            "HOLD", 1000,
            1.10000, 1.10020,
            1.10100, 1.10120,
        )


def test_rejects_crossed_quotes():
    with pytest.raises(ValueError):
        simulate_round_trip(
            "BUY", 1000,
            1.10020, 1.10000,
            1.10100, 1.10120,
        )


def test_rejects_nonpositive_units():
    with pytest.raises(ValueError):
        simulate_round_trip(
            "BUY", 0,
            1.10000, 1.10020,
            1.10100, 1.10120,
        )