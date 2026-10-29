"""Strict demo-account-only MT5 market execution adapter.

This module never switches MT5 accounts or logs in with credentials. It uses the
account already open in the local terminal and refuses to send unless that
account is explicitly confirmed as DEMO on the expected server. Order sending
is disabled unless MT5_DEMO_ORDER_ENABLED=YES_DEMO_ONLY is set.
"""
from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import MetaTrader5 as mt5
except ImportError:  # Keep safety logic unit-testable without the native package.
    mt5 = None


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_MT5_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
SUPPORTED_SYMBOLS = frozenset({"EURUSD"})
ENABLE_TOKEN = "YES_DEMO_ONLY"


class DemoExecutionError(RuntimeError):
    """A verified pre-send failure or rejected request."""


class OrderResultUncertain(DemoExecutionError):
    """A send may have reached the server; never retry automatically."""


@dataclass(frozen=True)
class DemoConfig:
    expected_server: str = "XMGlobal-MT5 2"
    expected_login: int | None = None
    orders_enabled: bool = False
    magic: int = 261029
    deviation_points: int = 20
    max_spread_points: float = 30.0
    server_timezone: str = "Europe/Athens"
    allowed_symbols: tuple[str, ...] = ("EURUSD",)

    @classmethod
    def from_env(cls) -> "DemoConfig":
        enabled = os.environ.get("MT5_DEMO_ORDER_ENABLED", "").strip()
        login_text = os.environ.get("MT5_DEMO_LOGIN", "").strip()
        return cls(
            expected_server=os.environ.get(
                "MT5_DEMO_SERVER", "XMGlobal-MT5 2"
            ).strip(),
            expected_login=int(login_text) if login_text else None,
            orders_enabled=(enabled == ENABLE_TOKEN),
            magic=int(os.environ.get("MT5_DEMO_MAGIC", "261029")),
            deviation_points=int(
                os.environ.get("MT5_DEMO_DEVIATION_POINTS", "20")
            ),
            max_spread_points=float(
                os.environ.get("MT5_DEMO_MAX_SPREAD_POINTS", "30")
            ),
            server_timezone=os.environ.get(
                "MT5_SERVER_TIMEZONE", "Europe/Athens"
            ).strip(),
        )


def broker_timestamp_to_utc(raw_timestamp: float, timezone_name: str) -> datetime:
    """Convert the observed broker wall-clock timestamp to UTC.

    The current user's MT5 feed was observed to return timestamps shifted by
    the broker's UTC offset. Ambiguous/nonexistent DST wall times are rejected
    rather than guessed. Revalidate this mapping if the broker/server changes.
    """
    try:
        server_tz = ZoneInfo(timezone_name)
    except Exception as exc:
        raise DemoExecutionError(
            f"Invalid MT5_SERVER_TIMEZONE {timezone_name!r}"
        ) from exc

    encoded = datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc)
    wall_time = encoded.replace(tzinfo=None)
    first = wall_time.replace(tzinfo=server_tz, fold=0)
    second = wall_time.replace(tzinfo=server_tz, fold=1)

    if first.utcoffset() != second.utcoffset():
        raise DemoExecutionError(
            f"Ambiguous broker-local timestamp: {wall_time}"
        )

    converted = first.astimezone(timezone.utc)
    if converted.astimezone(server_tz).replace(tzinfo=None) != wall_time:
        raise DemoExecutionError(
            f"Invalid broker-local timestamp: {wall_time}"
        )
    return converted


class MT5DemoExecutor:
    """An explicitly gated MT5 executor; all orders require server-side SL/TP."""

    def __init__(self, api, config: DemoConfig, now_fn=None):
        self.api = api
        self.config = config
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self._verified_login: int | None = None

    def _require_orders_enabled(self):
        if not self.config.orders_enabled:
            raise DemoExecutionError(
                "Order submission is disabled. Set "
                "MT5_DEMO_ORDER_ENABLED=YES_DEMO_ONLY only for a confirmed "
                "broker demo account."
            )
        if not self.config.expected_server:
            raise DemoExecutionError("Expected MT5 demo server is not configured")

    def preflight(self) -> dict:
        if not self.config.expected_server:
            raise DemoExecutionError("Expected MT5 demo server is not configured")

        terminal = self.api.terminal_info()
        account = self.api.account_info()

        if terminal is None:
            raise DemoExecutionError(
                f"MT5 terminal status unavailable: {self.api.last_error()}"
            )
        if account is None:
            raise DemoExecutionError(
                f"MT5 account status unavailable: {self.api.last_error()}"
            )
        if not bool(getattr(terminal, "connected", False)):
            raise DemoExecutionError("MT5 terminal is disconnected")
        if str(getattr(account, "server", "")) != self.config.expected_server:
            raise DemoExecutionError(
                "MT5 server mismatch: expected "
                f"{self.config.expected_server!r}, got "
                f"{getattr(account, 'server', None)!r}"
            )

        current_login = getattr(account, "login", None)
        if current_login is None:
            raise DemoExecutionError(
                "MT5 did not expose the connected account login; refusing orders."
            )
        try:
            current_login = int(current_login)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DemoExecutionError("Invalid MT5 account login value") from exc
        if (
            self.config.expected_login is not None
            and current_login != int(self.config.expected_login)
        ):
            raise DemoExecutionError("MT5 account login does not match MT5_DEMO_LOGIN")
        if self._verified_login is None:
            self._verified_login = current_login
        elif current_login != self._verified_login:
            raise DemoExecutionError(
                "Connected MT5 account changed during this runner session; "
                "restart only after confirming the intended demo account."
            )

        demo_mode = getattr(self.api, "ACCOUNT_TRADE_MODE_DEMO", None)
        if demo_mode is None or getattr(account, "trade_mode", None) != demo_mode:
            raise DemoExecutionError(
                "Account is not confirmed as a demo account; refusing orders"
            )

        if not bool(getattr(terminal, "trade_allowed", False)):
            raise DemoExecutionError("MT5 terminal trading is not enabled")
        if bool(getattr(terminal, "tradeapi_disabled", False)):
            raise DemoExecutionError("MT5 external trading API is disabled")
        if not bool(getattr(account, "trade_allowed", False)):
            raise DemoExecutionError("Trading is not allowed for this account")
        if not bool(getattr(account, "trade_expert", False)):
            raise DemoExecutionError(
                "Automated trading is not allowed for this account"
            )

        return {
            "connected": True,
            "server": str(account.server),
            "account_mode": "DEMO",
            "currency": str(getattr(account, "currency", "")),
            "orders_enabled": bool(self.config.orders_enabled),
        }

    def _symbol_info(self, symbol: str):
        if symbol not in self.config.allowed_symbols or symbol not in SUPPORTED_SYMBOLS:
            raise DemoExecutionError(f"Symbol is not allowlisted: {symbol!r}")

        info = self.api.symbol_info(symbol)
        if info is None:
            raise DemoExecutionError(
                f"Symbol information unavailable for {symbol}: "
                f"{self.api.last_error()}"
            )

        if not bool(getattr(info, "visible", True)):
            if not self.api.symbol_select(symbol, True):
                raise DemoExecutionError(
                    f"Could not select {symbol}: {self.api.last_error()}"
                )
            info = self.api.symbol_info(symbol)
            if info is None:
                raise DemoExecutionError(
                    f"Symbol information unavailable after selection: {symbol}"
                )

        point = float(getattr(info, "point", 0) or 0)
        digits = int(getattr(info, "digits", -1))
        if not math.isfinite(point) or point <= 0 or digits < 0:
            raise DemoExecutionError(f"Invalid point/digits for {symbol}")

        disabled = getattr(self.api, "SYMBOL_TRADE_MODE_DISABLED", 0)
        if getattr(info, "trade_mode", None) == disabled:
            raise DemoExecutionError(f"Trading is disabled for {symbol}")

        # This project stores and backtests EURUSD OHLC as Bid prices.
        # Refuse an unverified or Last-based chart instead of applying the
        # wrong bid/ask spread model.
        if symbol == "EURUSD":
            bid_mode = getattr(self.api, "SYMBOL_CHART_MODE_BID", None)
            chart_mode = getattr(info, "chart_mode", None)
            if bid_mode is None or chart_mode is None:
                raise DemoExecutionError(
                    "Cannot verify EURUSD chart mode; Bid-based history "
                    "assumption is unverified."
                )
            if chart_mode != bid_mode:
                raise DemoExecutionError(
                    "EURUSD chart mode is not Bid-based; this project requires "
                    "Bid-based bars for its current backtest cost model."
                )
        return info

    def _quote(self, symbol: str, enforce_spread: bool = True) -> dict:
        info = self._symbol_info(symbol)
        tick = self.api.symbol_info_tick(symbol)
        if tick is None:
            raise DemoExecutionError(
                f"No live tick for {symbol}: {self.api.last_error()}"
            )

        bid, ask = float(tick.bid), float(tick.ask)
        point = float(info.point)
        if (
            not math.isfinite(bid) or not math.isfinite(ask)
            or bid <= 0 or ask < bid
        ):
            raise DemoExecutionError("MT5 returned an invalid bid/ask quote")

        raw_time = (
            float(tick.time_msc) / 1000.0
            if getattr(tick, "time_msc", 0)
            else float(getattr(tick, "time", 0))
        )
        if raw_time <= 0:
            raise DemoExecutionError("MT5 quote has no valid timestamp")

        tick_time = broker_timestamp_to_utc(
            raw_time, self.config.server_timezone
        )
        now = self.now_fn().astimezone(timezone.utc)
        age_seconds = (now - tick_time).total_seconds()
        if abs(age_seconds) > 300:
            raise DemoExecutionError(
                f"Quote is stale or timestamp mapping is wrong "
                f"(age={age_seconds:.1f}s); refusing order"
            )

        spread_points = (ask - bid) / point
        if enforce_spread and spread_points > self.config.max_spread_points:
            raise DemoExecutionError(
                f"Spread too wide: {spread_points:.1f} points "
                f"(limit {self.config.max_spread_points:.1f})"
            )

        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "point": point,
            "digits": int(info.digits),
            "spread_points": spread_points,
            "tick_time_utc": tick_time.isoformat(),
            "info": info,
        }

    def get_positions(self, symbol: str):
        self._symbol_info(symbol)
        positions = self.api.positions_get(symbol=symbol)
        if positions is None:
            raise DemoExecutionError(
                f"Could not read positions for {symbol}: {self.api.last_error()}"
            )
        return list(positions)

    @staticmethod
    def _validate_volume(volume_lots: float, info) -> float:
        try:
            value = Decimal(str(volume_lots))
            minimum = Decimal(str(info.volume_min))
            maximum = Decimal(str(info.volume_max))
            step = Decimal(str(info.volume_step))
        except (InvalidOperation, AttributeError) as exc:
            raise DemoExecutionError("Invalid broker volume settings") from exc

        if not value.is_finite() or value <= 0 or step <= 0:
            raise DemoExecutionError("Volume must be finite and positive")
        if value < minimum or value > maximum:
            raise DemoExecutionError(
                f"Volume {value} is outside broker limits {minimum}..{maximum}"
            )
        steps = (value / step).quantize(Decimal("1"))
        normalized = steps * step
        if abs(value - normalized) > Decimal("0.00000001"):
            raise DemoExecutionError(
                f"Volume {value} does not align with broker step {step}"
            )
        return float(value)

    def _send_once(self, request: dict, expected_position_ticket=None) -> dict:
        # order_check is side-effect free. Try broker-supported filling modes
        # only; after order_send is called, never retry automatically.
        candidates = []
        for name in ("ORDER_FILLING_FOK", "ORDER_FILLING_IOC", "ORDER_FILLING_RETURN"):
            value = getattr(self.api, name, None)
            if value is not None and value not in candidates:
                candidates.append(value)

        if not candidates:
            raise DemoExecutionError("MT5 exposes no supported filling modes")

        last_check = None
        selected_request = None
        for filling in candidates:
            probe = dict(request)
            probe["type_filling"] = filling
            checked = self.api.order_check(probe)
            if checked is not None and getattr(checked, "retcode", None) == 0:
                selected_request = probe
                break
            last_check = (
                getattr(checked, "comment", None)
                if checked is not None
                else self.api.last_error()
            )

        if selected_request is None:
            raise DemoExecutionError(
                f"MT5 order_check rejected all filling modes: {last_check}"
            )

        # Re-check the connected account immediately before the side effect.
        # This narrows the window in which a terminal account switch could
        # invalidate the original preflight.
        self.preflight()
        result = self.api.order_send(selected_request)
        if result is None:
            raise OrderResultUncertain(
                f"MT5 order_send returned no result: {self.api.last_error()}; "
                "inspect broker positions/history manually. Do not retry."
            )

        retcode = getattr(result, "retcode", None)
        done = getattr(self.api, "TRADE_RETCODE_DONE", 10009)
        partial = getattr(self.api, "TRADE_RETCODE_DONE_PARTIAL", 10010)
        placed = getattr(self.api, "TRADE_RETCODE_PLACED", 10008)

        details = {
            "retcode": retcode,
            "order": getattr(result, "order", 0),
            "deal": getattr(result, "deal", 0),
            "volume": getattr(result, "volume", None),
            "price": getattr(result, "price", None),
            "comment": getattr(result, "comment", ""),
        }

        if retcode in (partial, placed):
            raise OrderResultUncertain(
                f"MT5 returned non-final order state {details}; "
                "inspect broker positions/orders before proceeding."
            )
        if retcode != done:
            raise DemoExecutionError(f"MT5 rejected the order: {details}")

        # After a successful send, all verification failures are UNCERTAIN,
        # not ordinary rejections: an order may exist and must never be retried.
        symbol = str(selected_request["symbol"])
        try:
            positions = self.get_positions(symbol)
            if expected_position_ticket is None:
                own = [
                    p for p in positions
                    if int(getattr(p, "magic", -1)) == self.config.magic
                ]
                if len(own) != 1:
                    raise OrderResultUncertain(
                        "Order reported DONE but exactly one managed position "
                        "could not be verified; inspect MT5 manually."
                    )
                position = own[0]
                if (
                    float(getattr(position, "sl", 0) or 0) <= 0
                    or float(getattr(position, "tp", 0) or 0) <= 0
                ):
                    raise OrderResultUncertain(
                        "Broker position is missing its required stop-loss or "
                        "take-profit; stop the runner and inspect MT5 manually."
                    )
                details["position_ticket"] = getattr(position, "ticket", None)
            else:
                still_open = any(
                    int(getattr(p, "ticket", -1)) == int(expected_position_ticket)
                    for p in positions
                )
                if still_open:
                    raise OrderResultUncertain(
                        "Close order reported DONE but the position is still open; "
                        "inspect MT5 manually before any further action."
                    )
        except OrderResultUncertain:
            raise
        except Exception as exc:
            raise OrderResultUncertain(
                "Order was sent and the response was DONE, but broker state "
                f"verification failed: {exc}. Do not retry; inspect MT5 manually."
            ) from exc
        return details

    def place_protected_market_order(
        self,
        symbol: str,
        direction: str,
        volume_lots: float,
        stop_loss: float,
        take_profit: float,
    ) -> dict:
        self._require_orders_enabled()
        self.preflight()
        direction = direction.upper()
        if direction not in {"BUY", "SELL"}:
            raise DemoExecutionError("Direction must be BUY or SELL")

        info = self._symbol_info(symbol)
        volume = self._validate_volume(volume_lots, info)
        quote = self._quote(symbol, enforce_spread=True)
        existing_positions = self.get_positions(symbol)
        if existing_positions:
            raise DemoExecutionError(
                f"Refusing to add a position while {symbol} already has "
                "an open broker position."
            )

        pending = self.api.orders_get(symbol=symbol)
        if pending is None:
            raise DemoExecutionError(
                f"Could not read pending orders: {self.api.last_error()}"
            )
        if pending:
            raise DemoExecutionError(
                f"Refusing to duplicate an order while {symbol} has pending orders."
            )

        bid, ask = quote["bid"], quote["ask"]
        digits = quote["digits"]
        point = quote["point"]
        stop_distance = float(getattr(info, "trade_stops_level", 0) or 0) * point
        try:
            sl = round(float(stop_loss), digits)
            tp = round(float(take_profit), digits)
        except (TypeError, ValueError, OverflowError) as exc:
            raise DemoExecutionError("Invalid stop-loss/take-profit values") from exc
        if not all(math.isfinite(v) and v > 0 for v in (sl, tp)):
            raise DemoExecutionError("Stop-loss and take-profit must be positive")

        if direction == "BUY":
            entry_price = ask
            if sl >= bid or tp <= ask:
                raise DemoExecutionError(
                    "BUY requires stop-loss below bid and take-profit above ask"
                )
            if ask - sl < stop_distance or tp - ask < stop_distance:
                raise DemoExecutionError(
                    "BUY stop-loss/take-profit violates broker stop distance"
                )
            order_type = self.api.ORDER_TYPE_BUY
        else:
            entry_price = bid
            if sl <= ask or tp >= bid:
                raise DemoExecutionError(
                    "SELL requires stop-loss above ask and take-profit below bid"
                )
            if sl - bid < stop_distance or bid - tp < stop_distance:
                raise DemoExecutionError(
                    "SELL stop-loss/take-profit violates broker stop distance"
                )
            order_type = self.api.ORDER_TYPE_SELL

        request = {
            "action": self.api.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": round(entry_price, digits),
            "sl": sl,
            "tp": tp,
            "deviation": int(self.config.deviation_points),
            "magic": int(self.config.magic),
            "comment": "ForexResearch DEMO",
            "type_time": self.api.ORDER_TIME_GTC,
        }
        # MT5 Market Execution requests must omit the price field.
        market_execution = getattr(
            self.api, "SYMBOL_TRADE_EXECUTION_MARKET", object()
        )
        if getattr(info, "trade_exemode", None) == market_execution:
            request.pop("price", None)
        return self._send_once(request)

    def close_managed_position(self, symbol: str, ticket: int) -> dict:
        self._require_orders_enabled()
        self.preflight()
        positions = self.get_positions(symbol)
        matches = [
            p for p in positions
            if int(getattr(p, "ticket", -1)) == int(ticket)
        ]
        if len(matches) != 1:
            raise DemoExecutionError(
                f"Position ticket {ticket} was not found exactly once"
            )
        position = matches[0]
        if int(getattr(position, "magic", -1)) != self.config.magic:
            raise DemoExecutionError(
                "Refusing to close a position not owned by this bot"
            )

        pending = self.api.orders_get(symbol=symbol)
        if pending is None:
            raise DemoExecutionError(
                f"Could not read pending orders before close: {self.api.last_error()}"
            )
        if pending:
            raise DemoExecutionError(
                "Refusing to close while this symbol has pending orders; "
                "inspect and reconcile them manually first."
            )

        info = self._symbol_info(symbol)
        quote = self._quote(symbol, enforce_spread=False)
        volume = self._validate_volume(float(position.volume), info)
        buy_type = getattr(self.api, "POSITION_TYPE_BUY", 0)
        if int(position.type) == buy_type:
            order_type = self.api.ORDER_TYPE_SELL
            price = quote["bid"]
        else:
            order_type = self.api.ORDER_TYPE_BUY
            price = quote["ask"]

        request = {
            "action": self.api.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "position": int(position.ticket),
            "volume": volume,
            "type": order_type,
            "price": round(price, quote["digits"]),
            "deviation": int(self.config.deviation_points),
            "magic": int(self.config.magic),
            "comment": "ForexResearch DEMO close",
            "type_time": self.api.ORDER_TIME_GTC,
        }
        # MT5 Market Execution requests must omit the price field.
        market_execution = getattr(
            self.api, "SYMBOL_TRADE_EXECUTION_MARKET", object()
        )
        if getattr(info, "trade_exemode", None) == market_execution:
            request.pop("price", None)
        return self._send_once(
            request, expected_position_ticket=int(position.ticket)
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only MT5 demo-account preflight. No orders are sent."
    )
    parser.add_argument(
        "command", choices=["preflight"],
        help="preflight checks the existing MT5 terminal/account without trading",
    )
    parser.parse_args()
    if mt5 is None:
        print("ERROR: MetaTrader5 Python package is not installed.")
        return 2

    path = os.environ.get("MT5_PATH", DEFAULT_MT5_PATH)
    if not Path(path).is_file():
        print(f"ERROR: MT5 terminal not found: {path}")
        return 2
    if not mt5.initialize(path=path, timeout=15000):
        print("ERROR: MT5 initialize failed:", mt5.last_error())
        return 2

    try:
        executor = MT5DemoExecutor(mt5, DemoConfig.from_env())
        try:
            status = executor.preflight()
            quote = executor._quote("EURUSD", enforce_spread=False)
        except DemoExecutionError as exc:
            print(f"PREFLIGHT FAILED: {exc}")
            return 1

        print("MT5 demo preflight: PASS")
        print("Server:", status["server"])
        print("Account mode:", status["account_mode"])
        print("Currency:", status["currency"])
        print("Symbol:", quote["symbol"])
        print(f"Bid/ask: {quote['bid']:.5f} / {quote['ask']:.5f}")
        print(f"Spread: {quote['spread_points']:.1f} points")
        print("Order submission enabled:", status["orders_enabled"])
        print("No order was submitted.")
        if not status["orders_enabled"]:
            print(
                "To enable demo-only orders later, set "
                "MT5_DEMO_ORDER_ENABLED=YES_DEMO_ONLY in this terminal session."
            )
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
