"""
execution/broker_base.py — Abstract Broker Interface

Defines the contract that all broker implementations must satisfy.
The paper_trader.py implements this for simulation.
Future live broker adapters (IBKR, Tradovate, etc.) must also implement this.

The interface is intentionally minimal — only the operations needed for
the order lifecycle are exposed. Broker-specific features are not abstracted here.

Order lifecycle:
    PENDING  → order submitted, awaiting fill
    FILLED   → order executed at fill_price
    PARTIAL  → partially filled (not yet handled — reserved for future)
    CANCELLED→ order cancelled before fill (timeout or manual)
    CLOSED   → position fully closed (stop hit, TP hit, or manual close)
    REJECTED → broker or risk rejected the order
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

OrderStatus = Literal["PENDING", "FILLED", "PARTIAL", "CANCELLED", "CLOSED", "REJECTED"]
OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop"]


@dataclass
class Order:
    """Represents a single order in its current lifecycle state."""

    order_id: str
    signal_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: int                           # Contracts
    limit_price: Optional[float]            # None for market orders
    stop_price: Optional[float]             # Stop-loss price
    take_profit_price: Optional[float]

    status: OrderStatus = "PENDING"
    fill_price: Optional[float] = None
    fill_time: Optional[datetime] = None
    close_price: Optional[float] = None
    close_time: Optional[datetime] = None
    realized_pnl: Optional[float] = None

    commission: float = 0.0
    slippage: float = 0.0
    created_at: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""


class BrokerBase(ABC):
    """
    Abstract base class for broker adapters.

    Subclasses must implement all abstract methods.
    The paper_trader.PaperTrader is the primary implementation.
    """

    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        """
        Submit an order to the broker.

        Returns the order with updated status (PENDING or REJECTED).
        For market orders in paper mode, may return FILLED immediately.
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> Order:
        """
        Cancel a pending order by ID.

        Returns the updated Order with status CANCELLED.
        Raises ValueError if order is not in PENDING state.
        """
        ...

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]:
        """
        Retrieve current state of an order by ID.
        Returns None if order_id is not found.
        """
        ...

    @abstractmethod
    def get_open_positions(self) -> list[Order]:
        """Return all currently FILLED (open position) orders."""
        ...

    @abstractmethod
    def close_position(self, order_id: str, close_price: float) -> Order:
        """
        Close an open position at the given price.

        Updates order status to CLOSED, sets close_price and realized_pnl.
        """
        ...

    @abstractmethod
    def get_account_balance(self) -> float:
        """Return current account balance in USD."""
        ...
