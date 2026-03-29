"""
execution/order_manager.py — Order Lifecycle Management

Responsibilities:
- Convert validated TradeSignal + SizingResult pairs into Order objects
- Submit orders to the broker (paper or live via BrokerBase)
- Track all open and closed orders for the session
- Coordinate stop-loss and take-profit management
- Emit events to the trade journal on fill and close

This module is the bridge between the signal/risk layer and the broker layer.
It holds no strategy logic — it only manages order state.

Order construction logic:
    - Direction "long"  → submit BUY limit at signal.entry_price
    - Direction "short" → submit SELL limit at signal.entry_price
    - Attach SL and TP prices from the signal
    - Commission and slippage are applied by the broker, not here
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from execution.broker_base import BrokerBase, Order
from execution.paper_trader import PaperTrader
from strategy.signal_engine import TradeSignal
from risk.risk_manager import SizingResult

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Manages the full lifecycle of orders for one trading session.

    One instance per session. Works with any BrokerBase implementation.
    """

    def __init__(self, broker: BrokerBase) -> None:
        self.broker = broker
        self._active_signals: dict[str, str] = {}   # signal_id → order_id
        self._order_history: list[Order] = []

    def place_trade(
        self,
        signal: TradeSignal,
        sizing: SizingResult,
        order_type: str = "limit",
    ) -> Optional[Order]:
        """
        Construct and submit an order from a validated signal.

        Parameters
        ----------
        signal     : Validated TradeSignal from signal_engine
        sizing     : Approved SizingResult from risk_manager
        order_type : "limit" | "market"

        Returns
        -------
        The submitted Order object, or None if submission fails.
        """
        if not sizing.approved or sizing.contracts < 1:
            logger.warning("Skipping trade for %s — sizing not approved", signal.signal_id)
            return None

        side = "buy" if signal.direction == "long" else "sell"
        limit_price = signal.entry_price if order_type == "limit" else None

        order = Order(
            order_id=PaperTrader.make_order_id(),
            signal_id=signal.signal_id,
            symbol=signal.symbol,
            side=side,
            order_type=order_type,  # type: ignore[arg-type]
            quantity=sizing.contracts,
            limit_price=limit_price,
            stop_price=signal.stop_loss,
            take_profit_price=signal.take_profit,
        )

        submitted = self.broker.submit_order(order)
        self._active_signals[signal.signal_id] = submitted.order_id

        logger.info(
            "TRADE PLACED | Signal: %s | Order: %s | Side: %s | Qty: %d | "
            "Limit: %s | SL: %.4f | TP: %.4f",
            signal.signal_id, submitted.order_id, side.upper(), sizing.contracts,
            f"{limit_price:.4f}" if limit_price else "MARKET",
            signal.stop_loss, signal.take_profit,
        )

        return submitted

    def process_bar(self, bar) -> list[Order]:
        """
        Forward a bar to the broker for fill/exit checks.
        Returns orders that changed status this bar.

        Call once per bar close during paper trading or backtesting.
        """
        if not hasattr(self.broker, "process_bar"):
            return []   # Live broker handles fills asynchronously

        changed: list[Order] = self.broker.process_bar(bar)  # type: ignore[attr-defined]

        for order in changed:
            if order.status == "CLOSED":
                self._order_history.append(order)
                # Clean up active signal mapping
                sig_id = order.signal_id
                self._active_signals.pop(sig_id, None)

        return changed

    def cancel_all_pending(self) -> list[Order]:
        """Cancel all pending (unfilled) orders. Used at session end."""
        cancelled = []
        for order in self.broker.get_open_positions():
            pass  # get_open_positions returns FILLED only

        # Cancel pending differently — iterate broker orders directly
        if hasattr(self.broker, "_orders"):
            for order_id, order in list(self.broker._orders.items()):  # type: ignore[attr-defined]
                if order.status == "PENDING":
                    cancelled.append(self.broker.cancel_order(order_id))

        logger.info("Cancelled %d pending orders at session end", len(cancelled))
        return cancelled

    def get_session_summary(self) -> dict:
        """Return a summary of all closed trades for this session."""
        closed = [o for o in self._order_history if o.status == "CLOSED" and o.realized_pnl is not None]
        if not closed:
            return {"trades": 0, "total_pnl": 0.0, "wins": 0, "losses": 0}

        total_pnl = sum(o.realized_pnl for o in closed)  # type: ignore[misc]
        wins = sum(1 for o in closed if o.realized_pnl > 0)  # type: ignore[operator]
        losses = sum(1 for o in closed if o.realized_pnl <= 0)  # type: ignore[operator]

        return {
            "trades": len(closed),
            "total_pnl": round(total_pnl, 2),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
            "avg_win": round(
                sum(o.realized_pnl for o in closed if o.realized_pnl > 0) / wins, 2  # type: ignore
            ) if wins else 0.0,
            "avg_loss": round(
                sum(o.realized_pnl for o in closed if o.realized_pnl <= 0) / losses, 2  # type: ignore
            ) if losses else 0.0,
        }
