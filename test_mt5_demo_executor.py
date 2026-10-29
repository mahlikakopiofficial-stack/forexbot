from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from mt5_demo_executor import (
    DemoConfig,
    DemoExecutionError,
    MT5DemoExecutor,
    OrderResultUncertain,
)


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    SYMBOL_TRADE_MODE_DISABLED = 0
    SYMBOL_CHART_MODE_BID = 0
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_DONE_PARTIAL = 10010
    TRADE_RETCODE_PLACED = 10008
    POSITION_TYPE_BUY = 0
    SYMBOL_TRADE_EXECUTION_MARKET = 2

    def __init__(
        self, now, *, real_account=False, send_result=True,
        check_retcode=0, market_execution=False,
        fail_position_read_after_send=False,
        switch_to_real_on_order_check=False,
    ):
        self.now = now
        self.terminal = SimpleNamespace(
            connected=True, trade_allowed=True, tradeapi_disabled=False
        )
        self.account = SimpleNamespace(
            server="XMGlobal-MT5 2",
            login=123456,
            trade_mode=2 if real_account else self.ACCOUNT_TRADE_MODE_DEMO,
            currency="USD",
            trade_allowed=True,
            trade_expert=True,
            balance=10000.0,
            equity=10000.0,
        )
        self.info = SimpleNamespace(
            visible=True, point=0.00001, digits=5, trade_mode=4,
            volume_min=0.01, volume_max=100.0, volume_step=0.01,
            trade_stops_level=0,
            chart_mode=self.SYMBOL_CHART_MODE_BID,
            trade_exemode=(
                self.SYMBOL_TRADE_EXECUTION_MARKET
                if market_execution else 0
            ),
        )
        wall_label = now.astimezone(ZoneInfo("Europe/Athens")).replace(
            tzinfo=timezone.utc
        )
        self.raw_tick_time = wall_label.timestamp()
        self.tick = SimpleNamespace(
            bid=1.10000, ask=1.10020,
            time=self.raw_tick_time,
            time_msc=int(self.raw_tick_time * 1000),
        )
        self.positions = []
        self.pending = []
        self.send_result = send_result
        self.check_retcode = check_retcode
        self.check_calls = 0
        self.send_calls = 0
        self.positions_get_calls = 0
        self.fail_position_read_after_send = fail_position_read_after_send
        self.switch_to_real_on_order_check = switch_to_real_on_order_check
        self.last_request = None
        self._last_error = (1, "fake error")

    def terminal_info(self):
        return self.terminal

    def account_info(self):
        return self.account

    def last_error(self):
        return self._last_error

    def symbol_info(self, symbol):
        return self.info if symbol == "EURUSD" else None

    def symbol_info_tick(self, symbol):
        return self.tick if symbol == "EURUSD" else None

    def symbol_select(self, symbol, selected):
        return True

    def positions_get(self, symbol=None, ticket=None):
        self.positions_get_calls += 1
        if self.fail_position_read_after_send and self.send_calls > 0:
            return None
        rows = list(self.positions)
        if symbol:
            rows = [p for p in rows if p.symbol == symbol]
        if ticket is not None:
            rows = [p for p in rows if p.ticket == ticket]
        return tuple(rows)

    def orders_get(self, symbol=None):
        return tuple(self.pending)

    def order_check(self, request):
        self.check_calls += 1
        if self.switch_to_real_on_order_check:
            self.account.trade_mode = 2
        return SimpleNamespace(retcode=self.check_retcode, comment="fake check")

    def order_send(self, request):
        self.send_calls += 1
        self.last_request = dict(request)
        if not self.send_result:
            return None
        if "position" in request:
            self.positions = [
                p for p in self.positions if p.ticket != request["position"]
            ]
        else:
            self.positions.append(SimpleNamespace(
                ticket=42, symbol=request["symbol"], magic=request["magic"],
                volume=request["volume"], type=request["type"],
                sl=request["sl"], tp=request["tp"],
            ))
        return SimpleNamespace(
            retcode=self.TRADE_RETCODE_DONE, order=11, deal=12,
            volume=request["volume"], price=request.get("price", 0.0), comment="done",
        )


def setup_executor(**fake_kwargs):
    now = datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
    api = FakeMT5(now, **fake_kwargs)
    config = DemoConfig(
        expected_server="XMGlobal-MT5 2",
        orders_enabled=True,
        server_timezone="Europe/Athens",
        max_spread_points=30,
    )
    executor = MT5DemoExecutor(api, config, now_fn=lambda: now)
    return api, executor


def test_preflight_confirms_demo_server_and_mode():
    api, executor = setup_executor()
    status = executor.preflight()
    assert status["account_mode"] == "DEMO"
    assert status["server"] == "XMGlobal-MT5 2"
    assert executor._verified_login == 123456


def test_real_account_is_rejected_before_any_order():
    api, executor = setup_executor(real_account=True)
    with pytest.raises(DemoExecutionError, match="not confirmed as a demo"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )
    assert api.send_calls == 0


def test_order_gate_defaults_to_off():
    api, _ = setup_executor()
    config = DemoConfig(
        expected_server="XMGlobal-MT5 2",
        orders_enabled=False,
        server_timezone="Europe/Athens",
    )
    executor = MT5DemoExecutor(api, config, now_fn=lambda: api.now)
    with pytest.raises(DemoExecutionError, match="Order submission is disabled"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )
    assert api.send_calls == 0


def test_order_check_then_protected_demo_order():
    api, executor = setup_executor()
    result = executor.place_protected_market_order(
        "EURUSD", "BUY", 0.01, 1.09900, 1.10200
    )
    assert result["position_ticket"] == 42
    assert api.check_calls == 1
    assert api.send_calls == 1
    assert api.last_request["sl"] == 1.09900
    assert api.last_request["tp"] == 1.10200


def test_existing_position_prevents_duplicate_order():
    api, executor = setup_executor()
    api.positions.append(SimpleNamespace(
        ticket=7, symbol="EURUSD", magic=1, volume=0.01,
        type=api.ORDER_TYPE_BUY, sl=1.09, tp=1.12,
    ))
    with pytest.raises(DemoExecutionError, match="already has an open"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )
    assert api.send_calls == 0


def test_bad_volume_is_rejected_before_order_send():
    api, executor = setup_executor()
    with pytest.raises(DemoExecutionError, match="does not align"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.015, 1.09900, 1.10200
        )
    assert api.send_calls == 0


def test_wide_spread_is_rejected_before_order_send():
    api, executor = setup_executor()
    api.tick.ask = 1.10100
    with pytest.raises(DemoExecutionError, match="Spread too wide"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )
    assert api.send_calls == 0


def test_order_check_rejection_never_sends_order():
    api, executor = setup_executor(check_retcode=10016)
    with pytest.raises(DemoExecutionError, match="order_check rejected"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )
    assert api.send_calls == 0


def test_unknown_send_result_is_not_retried():
    api, executor = setup_executor(send_result=False)
    with pytest.raises(OrderResultUncertain, match="Do not retry"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )
    assert api.send_calls == 1


def test_executor_only_closes_its_own_position():
    api, executor = setup_executor()
    api.positions.append(SimpleNamespace(
        ticket=77, symbol="EURUSD", magic=999, volume=0.01,
        type=api.POSITION_TYPE_BUY, sl=1.09, tp=1.12,
    ))
    with pytest.raises(DemoExecutionError, match="not owned by this bot"):
        executor.close_managed_position("EURUSD", 77)
    assert api.send_calls == 0


def test_managed_position_can_be_closed_and_is_verified():
    api, executor = setup_executor()
    api.positions.append(SimpleNamespace(
        ticket=42, symbol="EURUSD", magic=executor.config.magic, volume=0.01,
        type=api.POSITION_TYPE_BUY, sl=1.09, tp=1.12,
    ))
    result = executor.close_managed_position("EURUSD", 42)
    assert result["deal"] == 12
    assert api.send_calls == 1
    assert api.positions == []



def test_market_execution_omits_price_from_order_request():
    api, executor = setup_executor()
    api.info.trade_exemode = api.SYMBOL_TRADE_EXECUTION_MARKET

    executor.place_protected_market_order(
        "EURUSD", "BUY", 0.01, 1.09900, 1.10200
    )

    assert "price" not in api.last_request


def test_post_send_verification_failure_is_uncertain_not_retried():
    api, executor = setup_executor(fail_position_read_after_send=True)

    with pytest.raises(OrderResultUncertain, match="Do not retry|verification failed"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )

    assert api.send_calls == 1



def test_account_switch_to_real_after_order_check_is_blocked_before_send():
    api, executor = setup_executor(switch_to_real_on_order_check=True)

    with pytest.raises(DemoExecutionError, match="not confirmed as a demo"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )

    assert api.check_calls == 1
    assert api.send_calls == 0



def test_last_price_chart_mode_is_rejected_for_bid_based_model():
    api, executor = setup_executor()
    api.info.chart_mode = 1

    with pytest.raises(DemoExecutionError, match="not Bid-based"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )

    assert api.send_calls == 0



def test_expected_demo_login_mismatch_is_rejected():
    api, executor = setup_executor()
    executor.config = DemoConfig(
        expected_server="XMGlobal-MT5 2",
        expected_login=999999,
        orders_enabled=True,
        server_timezone="Europe/Athens",
    )

    with pytest.raises(DemoExecutionError, match="does not match MT5_DEMO_LOGIN"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )

    assert api.send_calls == 0


def test_account_login_change_during_session_is_rejected():
    api, executor = setup_executor()
    executor.preflight()
    api.account.login = 654321

    with pytest.raises(DemoExecutionError, match="account changed"):
        executor.place_protected_market_order(
            "EURUSD", "BUY", 0.01, 1.09900, 1.10200
        )

    assert api.send_calls == 0



def test_managed_close_refuses_unreconciled_pending_orders():
    api, executor = setup_executor()
    api.positions.append(SimpleNamespace(
        ticket=42, symbol="EURUSD", magic=executor.config.magic, volume=0.01,
        type=api.POSITION_TYPE_BUY, sl=1.09, tp=1.12,
    ))
    api.pending.append(SimpleNamespace(ticket=99, symbol="EURUSD"))

    with pytest.raises(DemoExecutionError, match="pending orders"):
        executor.close_managed_position("EURUSD", 42)

    assert api.send_calls == 0
