"""
risk/risk_manager.py — Position Sizing and Session-Level Risk Controls

Responsibilities:
- Calculate position size (contracts) for a given trade signal and account state
- Track daily P&L, open trade count, and consecutive losses
- Enforce daily loss limits, max trades per day, and drawdown controls
- Reduce position size when drawdown thresholds are crossed

Position sizing methods:
    fixed_risk_pct : size = (account_balance × risk_pct) / stop_distance_in_dollars
    fixed_contracts: always trade N contracts regardless of stop distance
    kelly          : fractional Kelly based on historical win rate and avg R:R
                     (requires backtest stats — not used in live without sufficient data)

Important:
    - Position size is always floored to an integer (whole contracts)
    - Size is capped by max_contracts regardless of calculation result
    - If daily loss limit is breached, size = 0 (no new trades)
    - At drawdown reduce_size_at_pct, size is halved (floor division)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

logger = logging.getLogger(__name__)

SizingMethod = Literal["fixed_risk_pct", "fixed_contracts", "kelly"]


@dataclass
class SessionState:
    """Tracks intraday and session-level risk state. Reset daily."""

    trading_date: date
    starting_balance: float
    current_balance: float
    daily_pnl: float = 0.0
    trades_taken: int = 0
    consecutive_losses: int = 0
    open_positions: int = 0
    peak_balance: float = 0.0
    is_halted: bool = False
    halt_reason: str = ""

    def __post_init__(self) -> None:
        if self.peak_balance == 0.0:
            self.peak_balance = self.starting_balance


@dataclass
class SizingResult:
    """Output from the position sizing calculation."""

    contracts: int                          # Final approved contract count (0 = no trade)
    risk_dollars: float                     # Dollar amount being risked
    risk_pct: float                         # % of account being risked
    approved: bool                          # False if any hard limit vetoes the trade
    rejection_reason: Optional[str] = None  # Set if approved=False
    notes: str = ""


class RiskManager:
    """
    Stateful risk manager for a single trading session.

    One instance per live/paper session. Reset between sessions via reset_daily().
    """

    def __init__(self, risk_config: dict) -> None:
        self.cfg = risk_config
        account_cfg = risk_config.get("account", {})
        sizing_cfg = risk_config.get("position_sizing", {})
        daily_cfg = risk_config.get("daily_limits", {})
        dd_cfg = risk_config.get("drawdown", {})
        portfolio_cfg = risk_config.get("portfolio", {})

        self.starting_balance: float = account_cfg.get("starting_balance", 100_000.0)
        self.sizing_method: SizingMethod = sizing_cfg.get("method", "fixed_risk_pct")
        self.risk_per_trade_pct: float = sizing_cfg.get("risk_per_trade_pct", 1.0)
        self.max_risk_per_trade_pct: float = sizing_cfg.get("max_risk_per_trade_pct", 2.0)
        self.max_contracts: int = sizing_cfg.get("max_contracts", 5)
        self.max_daily_loss_pct: float = daily_cfg.get("max_daily_loss_pct", 3.0)
        self.max_daily_loss_usd: float = daily_cfg.get("max_daily_loss_usd", 3000.0)
        self.max_trades_per_day: int = daily_cfg.get("max_trades_per_day", 6)
        self.consecutive_loss_halt: int = daily_cfg.get("consecutive_loss_halt", 3)
        self.max_drawdown_pct: float = dd_cfg.get("max_drawdown_pct", 10.0)
        self.reduce_size_at_pct: float = dd_cfg.get("reduce_size_at_pct", 5.0)
        self.max_open_positions: int = portfolio_cfg.get("max_open_positions", 2)

        self.state = SessionState(
            trading_date=date.today(),
            starting_balance=self.starting_balance,
            current_balance=self.starting_balance,
            peak_balance=self.starting_balance,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_size(
        self,
        stop_distance: float,
        point_value: float = 20.0,
        entry_price: Optional[float] = None,
    ) -> SizingResult:
        """
        Calculate position size in contracts for a prospective trade.

        Parameters
        ----------
        stop_distance : Distance from entry to stop loss in price points
        point_value   : Dollar value per 1-point move per contract
                        NQ futures: $20/pt  |  ES futures: $50/pt
        entry_price   : Optional — used for fixed_risk_pct when stop_distance
                        is expressed as a fraction of price

        Returns
        -------
        SizingResult with approved=False and rejection_reason if any hard limit fails.
        """
        # Pre-sizing halts
        rejection = self._check_hard_limits()
        if rejection:
            return SizingResult(
                contracts=0,
                risk_dollars=0.0,
                risk_pct=0.0,
                approved=False,
                rejection_reason=rejection,
            )

        balance = self.state.current_balance

        if self.sizing_method == "fixed_risk_pct":
            contracts = self._size_fixed_risk_pct(balance, stop_distance, point_value)
        elif self.sizing_method == "fixed_contracts":
            contracts = self.cfg.get("position_sizing", {}).get("fixed_contracts", 1)
        else:
            contracts = self._size_fixed_risk_pct(balance, stop_distance, point_value)
            logger.warning("Kelly sizing not implemented — falling back to fixed_risk_pct")

        # Apply drawdown reduction
        current_dd = self._current_drawdown_pct()
        if current_dd >= self.reduce_size_at_pct:
            original = contracts
            contracts = max(1, contracts // 2)
            logger.info(
                "Drawdown %.1f%% exceeded reduce threshold %.1f%% — size reduced %d → %d",
                current_dd, self.reduce_size_at_pct, original, contracts,
            )

        # Hard cap
        contracts = min(contracts, self.max_contracts)

        if contracts < 1:
            return SizingResult(
                contracts=0,
                risk_dollars=0.0,
                risk_pct=0.0,
                approved=False,
                rejection_reason="Position size rounds to 0 contracts — stop too far or balance too low",
            )

        risk_dollars = contracts * stop_distance * point_value
        risk_pct = (risk_dollars / balance) * 100

        # Max risk per trade ceiling
        if risk_pct > self.max_risk_per_trade_pct:
            contracts = max(1, int(balance * (self.max_risk_per_trade_pct / 100) / (stop_distance * point_value)))
            risk_dollars = contracts * stop_distance * point_value
            risk_pct = (risk_dollars / balance) * 100
            logger.info("Risk capped at %.1f%% — contracts adjusted to %d", self.max_risk_per_trade_pct, contracts)

        return SizingResult(
            contracts=contracts,
            risk_dollars=round(risk_dollars, 2),
            risk_pct=round(risk_pct, 3),
            approved=True,
            notes=f"Method: {self.sizing_method} | DD: {current_dd:.1f}%",
        )

    def record_trade_open(self) -> None:
        """Call when a trade is opened. Updates open position count and trade counter."""
        self.state.trades_taken += 1
        self.state.open_positions += 1
        logger.debug("Trade opened. Daily count: %d | Open: %d", self.state.trades_taken, self.state.open_positions)

    def record_trade_close(self, pnl: float) -> None:
        """
        Call when a trade closes. Updates P&L, consecutive loss counter, and balance.

        Parameters
        ----------
        pnl : Realized P&L in dollars (negative = loss)
        """
        self.state.open_positions = max(0, self.state.open_positions - 1)
        self.state.daily_pnl += pnl
        self.state.current_balance += pnl

        if pnl < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

        if self.state.current_balance > self.state.peak_balance:
            self.state.peak_balance = self.state.current_balance

        logger.info(
            "Trade closed: P&L $%.2f | Daily P&L $%.2f | Balance $%.2f | Consec losses: %d",
            pnl, self.state.daily_pnl, self.state.current_balance, self.state.consecutive_losses,
        )

        # Check if we should halt after this close
        self._evaluate_halt_conditions()

    def reset_daily(self, new_date: Optional[date] = None) -> None:
        """Reset intraday counters. Call at the start of each new trading day."""
        from datetime import date as date_type
        self.state.trading_date = new_date or date_type.today()
        self.state.daily_pnl = 0.0
        self.state.trades_taken = 0
        self.state.consecutive_losses = 0
        self.state.open_positions = 0
        self.state.is_halted = False
        self.state.halt_reason = ""
        logger.info("Daily risk counters reset for %s", self.state.trading_date)

    def get_state_summary(self) -> dict:
        """Return a serializable snapshot of current risk state."""
        return {
            "date": str(self.state.trading_date),
            "balance": self.state.current_balance,
            "daily_pnl": self.state.daily_pnl,
            "trades_taken": self.state.trades_taken,
            "open_positions": self.state.open_positions,
            "consecutive_losses": self.state.consecutive_losses,
            "drawdown_pct": round(self._current_drawdown_pct(), 2),
            "is_halted": self.state.is_halted,
            "halt_reason": self.state.halt_reason,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _size_fixed_risk_pct(
        self, balance: float, stop_distance: float, point_value: float
    ) -> int:
        """Calculate contracts using fixed % risk per trade."""
        if stop_distance <= 0 or point_value <= 0:
            return 0
        dollar_risk = balance * (self.risk_per_trade_pct / 100.0)
        contracts = int(dollar_risk / (stop_distance * point_value))
        return max(0, contracts)

    def _current_drawdown_pct(self) -> float:
        """Current drawdown from peak balance as a percentage."""
        if self.state.peak_balance <= 0:
            return 0.0
        dd = (self.state.peak_balance - self.state.current_balance) / self.state.peak_balance * 100
        return max(0.0, dd)

    def _check_hard_limits(self) -> Optional[str]:
        """Return a rejection reason string if any hard limit blocks trading, else None."""
        if self.state.is_halted:
            return f"Session halted: {self.state.halt_reason}"

        if self.state.trades_taken >= self.max_trades_per_day:
            return f"Max daily trades reached ({self.max_trades_per_day})"

        if self.state.open_positions >= self.max_open_positions:
            return f"Max open positions reached ({self.max_open_positions})"

        # Daily loss check
        daily_loss_pct = abs(self.state.daily_pnl) / self.state.starting_balance * 100
        if self.state.daily_pnl < 0:
            if daily_loss_pct >= self.max_daily_loss_pct:
                return f"Daily loss limit hit ({daily_loss_pct:.1f}% >= {self.max_daily_loss_pct}%)"
            if abs(self.state.daily_pnl) >= self.max_daily_loss_usd:
                return f"Daily loss USD limit hit (${abs(self.state.daily_pnl):.2f} >= ${self.max_daily_loss_usd})"

        # Drawdown check
        dd = self._current_drawdown_pct()
        if dd >= self.max_drawdown_pct:
            return f"Max drawdown hit ({dd:.1f}% >= {self.max_drawdown_pct}%)"

        return None

    def _evaluate_halt_conditions(self) -> None:
        """Check post-trade conditions that trigger a session halt."""
        if self.state.consecutive_losses >= self.consecutive_loss_halt:
            self.state.is_halted = True
            self.state.halt_reason = f"{self.state.consecutive_losses} consecutive losses"
            logger.warning("SESSION HALTED: %s", self.state.halt_reason)
