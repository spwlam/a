"""
execution/paper_trader.py — Simulated Paper Trading Broker

Implements BrokerBase for paper (simulated) trading.

Responsibilities:
- Accept orders from order_manager.py and simulate fills
- Apply configurable slippage (ticks) and commission per side
- Simulate limit order fills: fill only when price crosses the limit level
- Track open positions, realized P&L, and account balance in memory
- Emit structured fill events for the trade journal

Fill simulation rules:
    Market order : Filled immediately at current_price ± slippage
    Limit order  : Filled when bar's high/low crosses the limit price
                   (uses bar data provided via process_bar())
    Stop-loss    : Triggered when bar's low/high crosses the stop price
                   (long: low <= stop | short: high >= stop)
    Take-profit  : Triggered when bar's high/low crosses the TP price
                   (long: high >= tp   | short: low <= tp)

Approximation notes:
- We do not simulate partial fills in this version.
- Slippage is applied uniformly (N ticks adverse). In reality, slippage
  varies by liquidity and order size. This is conservative for NQ futures.
- Commission is charged per side (entry + exit) as configured in settings.yaml.
- Stop and TP checks use bar high/low, not intrabar tick data. This means
  on a wide bar that hits both stop and TP, the stop is prioritized (worst case).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

import pandas as pd

from execution.broker_base import BrokerBase, Order, OrderSide, OrderStatus

logger = logging.getLogger(__name__)


class PaperTrader(BrokerBase):
    """
    In-memory paper trading broker.

    Usage:
        broker = PaperTrader(config=settings, starting_balance=100_000)
        order = broker.submit_order(order)
        fills = broker.process_bar(bar)   # Call once per bar
    """

    def __init__(self, config: dict, starting_balance: float = 100_000.0) -> None:
        exec_cfg = config.get("execution", {})
        self._slippage_ticks = exec_cfg.get("slippage_ticks", 1)
        self._tick_size = 0.25                    # NQ/ES minimum tick — override per instrument
        self._commission_per_side = exec_cfg.get("commission_per_side", 0.65)
        self._fill_timeout_bars = exec_cfg.get("fill_timeout_bars", 3)
        self._point_value = 20.0                  # NQ default; override as needed

        self._balance: float = starting_balance
        self._starting_balance: float = starting_balance
        self._orders: dict[str, Order] = {}       # order_id → Order
        self._bar_count: dict[str, int] = {}      # order_id → bars since submission

    # ------------------------------------------------------------------
    # BrokerBase implementation
    # ------------------------------------------------------------------

    def submit_order(self, order: Order) -> Order:
        """Accept and register an order. Market orders fill immediately."""
        if order.order_id in self._orders:
            logger.warning("Duplicate order_id %s — ignoring", order.order_id)
            return order

        self._orders[order.order_id] = order
        self._bar_count[order.order_id] = 0

        logger.info(
            "ORDER SUBMITTED | %s | %s %s %d @ %s | SL: %s | TP: %s",
            order.order_id, order.side.upper(), order.symbol, order.quantity,
            order.limit_price or "MARKET", order.stop_price, order.take_profit_price,
        )
        return order

    def cancel_order(self, order_id: str) -> Order:
        """Cancel a pending order."""
        order = self._get_or_raise(order_id)
        if order.status != "PENDING":
            raise ValueError(f"Cannot cancel order {order_id} with status {order.status}")
        order.status = "CANCELLED"
        logger.info("ORDER CANCELLED | %s", order_id)
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._orders.get(order_id)

    def get_open_positions(self) -> list[Order]:
        return [o for o in self._orders.values() if o.status == "FILLED"]

    def close_position(self, order_id: str, close_price: float) -> Order:
        """Manually close an open position at the given price."""
        order = self._get_or_raise(order_id)
        if order.status != "FILLED":
            raise ValueError(f"Cannot close order {order_id} with status {order.status}")
        return self._close_order(order, close_price, reason="manual_close")

    def get_account_balance(self) -> float:
        return self._balance

    # ------------------------------------------------------------------
    # Paper-specific: bar processing
    # ------------------------------------------------------------------

    def process_bar(self, bar: pd.Series) -> list[Order]:
        """
        Process one completed OHLCV bar. Attempt fills and check stops/TPs.

        Call this once per bar close, in chronological order.
        Returns a list of orders whose status changed this bar (fills, closes).

        Parameters
        ----------
        bar : pandas Series with 'open', 'high', 'low', 'close', 'timestamp' fields
        """
        changed: list[Order] = []
        bar_time: datetime = bar["timestamp"].to_pydatetime() if hasattr(bar["timestamp"], "to_pydatetime") else bar["timestamp"]

        for order_id, order in list(self._orders.items()):
            if order.status == "PENDING":
                self._bar_count[order_id] = self._bar_count.get(order_id, 0) + 1

                # Timeout check
                if self._bar_count[order_id] > self._fill_timeout_bars:
                    order.status = "CANCELLED"
                    order.notes = f"Fill timeout after {self._fill_timeout_bars} bars"
                    logger.info("ORDER TIMED OUT | %s", order_id)
                    changed.append(order)
                    continue

                # Attempt limit fill
                filled = self._attempt_limit_fill(order, bar, bar_time)
                if filled:
                    changed.append(order)

            elif order.status == "FILLED":
                # Check stop-loss and take-profit
                closed = self._check_exit_conditions(order, bar, bar_time)
                if closed:
                    changed.append(order)

        return changed

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _attempt_limit_fill(self, order: Order, bar: pd.Series, bar_time: datetime) -> bool:
        """Try to fill a pending limit order on the current bar."""
        if order.limit_price is None:
            # Market order — fill at open + slippage
            slippage = self._slippage_ticks * self._tick_size
            fill_px = bar["open"] + slippage if order.side == "buy" else bar["open"] - slippage
            self._fill_order(order, fill_px, bar_time)
            return True

        # Limit order: buy limit fills when bar low <= limit, sell limit when bar high >= limit
        if order.side == "buy" and bar["low"] <= order.limit_price:
            slippage = self._slippage_ticks * self._tick_size
            fill_px = order.limit_price + slippage  # Adverse slippage on fill
            self._fill_order(order, fill_px, bar_time)
            return True

        if order.side == "sell" and bar["high"] >= order.limit_price:
            slippage = self._slippage_ticks * self._tick_size
            fill_px = order.limit_price - slippage
            self._fill_order(order, fill_px, bar_time)
            return True

        return False

    def _fill_order(self, order: Order, fill_price: float, fill_time: datetime) -> None:
        """Record a fill. Charges entry commission."""
        order.status = "FILLED"
        order.fill_price = round(fill_price, 4)
        order.fill_time = fill_time
        order.commission += self._commission_per_side * order.quantity

        logger.info(
            "ORDER FILLED | %s | %s %d @ %.4f | Commission: $%.2f",
            order.order_id, order.symbol, order.quantity, fill_price,
            order.commission,
        )

    def _check_exit_conditions(self, order: Order, bar: pd.Series, bar_time: datetime) -> bool:
        """
        Check if stop-loss or take-profit was hit on this bar.
        Stop takes priority over TP on bars where both are hit (worst case).
        """
        if order.fill_price is None:
            return False

        # Long position
        if order.side == "buy":
            if order.stop_price and bar["low"] <= order.stop_price:
                self._close_order(order, order.stop_price, bar_time, reason="stop_loss")
                return True
            if order.take_profit_price and bar["high"] >= order.take_profit_price:
                self._close_order(order, order.take_profit_price, bar_time, reason="take_profit")
                return True

        # Short position
        elif order.side == "sell":
            if order.stop_price and bar["high"] >= order.stop_price:
                self._close_order(order, order.stop_price, bar_time, reason="stop_loss")
                return True
            if order.take_profit_price and bar["low"] <= order.take_profit_price:
                self._close_order(order, order.take_profit_price, bar_time, reason="take_profit")
                return True

        return False

    def _close_order(
        self,
        order: Order,
        close_price: float,
        bar_time: Optional[datetime] = None,
        reason: str = "manual",
    ) -> Order:
        """Close a filled position. Calculate P&L and update balance."""
        order.status = "CLOSED"
        order.close_price = round(close_price, 4)
        order.close_time = bar_time or datetime.utcnow()
        order.commission += self._commission_per_side * order.quantity

        # P&L = (close - entry) × contracts × point_value for long
        price_diff = order.close_price - order.fill_price  # type: ignore[operator]
        if order.side == "sell":
            price_diff = -price_diff

        gross_pnl = price_diff * order.quantity * self._point_value
        net_pnl = gross_pnl - order.commission
        order.realized_pnl = round(net_pnl, 2)
        order.notes = f"Exit reason: {reason}"

        self._balance += net_pnl

        logger.info(
            "POSITION CLOSED | %s | %s | Entry: %.4f | Exit: %.4f | "
            "Gross: $%.2f | Commission: $%.2f | Net P&L: $%.2f | Reason: %s",
            order.order_id, order.symbol,
            order.fill_price, order.close_price,
            gross_pnl, order.commission, net_pnl, reason,
        )

        return order

    def _get_or_raise(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order {order_id} not found")
        return order

    @staticmethod
    def make_order_id() -> str:
        """Generate a unique order ID."""
        return f"PT-{uuid.uuid4().hex[:8].upper()}"
