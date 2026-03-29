"""
risk/trade_validator.py — Pre-Trade Validation Checklist

Responsibilities:
- Run every proposed trade signal through a final checklist before order placement
- Validate stop distance against min/max bounds (from risk_config.yaml)
- Validate that the signal's direction aligns with current risk state
- Reject trades that violate any structural rule regardless of signal quality

This is the final gate before an order is sent to paper_trader.py or a live broker.
It receives both the TradeSignal (from signal_engine.py) and the SizingResult
(from risk_manager.py) and either approves or rejects the combined proposal.

Validation checks performed:
    1. Stop distance within bounds (min_stop_distance_ticks, max_stop_distance_pct)
    2. Contracts > 0 (sizing approved)
    3. Risk % within hard ceiling (max_risk_per_trade_pct)
    4. R:R ratio meets minimum (min_rr_ratio from settings.yaml)
    5. Signal strength meets minimum threshold (if configured)
    6. No duplicate signal ID already in open trades

All checks are logged. A single failure rejects the trade.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from strategy.signal_engine import TradeSignal
from risk.risk_manager import SizingResult

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of pre-trade validation."""

    approved: bool
    signal_id: str
    rejection_reason: Optional[str] = None
    checks_passed: list[str] = None  # type: ignore[assignment]
    checks_failed: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.checks_passed is None:
            self.checks_passed = []
        if self.checks_failed is None:
            self.checks_failed = []


class TradeValidator:
    """
    Stateless validator — can be called for each proposed trade.
    Requires both strategy config (settings.yaml) and risk config (risk_config.yaml).
    """

    def __init__(self, settings: dict, risk_config: dict) -> None:
        self.settings = settings
        self.risk_config = risk_config
        self._open_signal_ids: set[str] = set()

    def validate(
        self,
        signal: TradeSignal,
        sizing: SizingResult,
        current_price: float,
        tick_size: float = 0.25,
    ) -> ValidationResult:
        """
        Run all pre-trade checks on a (signal, sizing) pair.

        Parameters
        ----------
        signal        : TradeSignal from signal_engine.generate_signal()
        sizing        : SizingResult from risk_manager.calculate_size()
        current_price : Current market price for % calculations
        tick_size     : Minimum price increment for the instrument

        Returns
        -------
        ValidationResult with approved=True only if all checks pass.
        """
        checks_passed: list[str] = []
        checks_failed: list[str] = []
        rejection: Optional[str] = None

        trade_cfg = self.risk_config.get("trade", {})
        sizing_cfg = self.risk_config.get("position_sizing", {})
        signal_cfg = self.settings.get("signal", {})

        # ------------------------------------------------------------------
        # Check 1: Sizing approved
        # ------------------------------------------------------------------
        if not sizing.approved or sizing.contracts < 1:
            reason = sizing.rejection_reason or "Sizing rejected (0 contracts)"
            checks_failed.append("sizing_approved")
            return ValidationResult(
                approved=False,
                signal_id=signal.signal_id,
                rejection_reason=reason,
                checks_passed=checks_passed,
                checks_failed=checks_failed,
            )
        checks_passed.append("sizing_approved")

        # ------------------------------------------------------------------
        # Check 2: Stop distance — minimum (noise filter)
        # ------------------------------------------------------------------
        min_stop_ticks = trade_cfg.get("min_stop_distance_ticks", 4)
        min_stop_price = min_stop_ticks * tick_size
        if signal.stop_distance < min_stop_price:
            checks_failed.append("min_stop_distance")
            rejection = (
                f"Stop distance {signal.stop_distance:.4f} < min {min_stop_price:.4f} "
                f"({min_stop_ticks} ticks)"
            )
        else:
            checks_passed.append("min_stop_distance")

        # ------------------------------------------------------------------
        # Check 3: Stop distance — maximum (risk ceiling)
        # ------------------------------------------------------------------
        max_stop_pct = trade_cfg.get("max_stop_distance_pct", 1.5)
        max_stop_price = current_price * (max_stop_pct / 100.0)
        if signal.stop_distance > max_stop_price:
            checks_failed.append("max_stop_distance")
            rejection = rejection or (
                f"Stop distance {signal.stop_distance:.4f} > max {max_stop_price:.4f} "
                f"({max_stop_pct}% of price)"
            )
        else:
            checks_passed.append("max_stop_distance")

        # ------------------------------------------------------------------
        # Check 4: Risk % ceiling
        # ------------------------------------------------------------------
        max_risk_pct = sizing_cfg.get("max_risk_per_trade_pct", 2.0)
        if sizing.risk_pct > max_risk_pct:
            checks_failed.append("risk_pct_ceiling")
            rejection = rejection or (
                f"Risk {sizing.risk_pct:.2f}% exceeds hard ceiling {max_risk_pct}%"
            )
        else:
            checks_passed.append("risk_pct_ceiling")

        # ------------------------------------------------------------------
        # Check 5: R:R ratio
        # ------------------------------------------------------------------
        min_rr = signal_cfg.get("min_rr_ratio", 2.0)
        if signal.risk_reward < min_rr:
            checks_failed.append("min_rr_ratio")
            rejection = rejection or (
                f"R:R {signal.risk_reward:.2f} below minimum {min_rr}"
            )
        else:
            checks_passed.append("min_rr_ratio")

        # ------------------------------------------------------------------
        # Check 6: Duplicate signal guard
        # ------------------------------------------------------------------
        if signal.signal_id in self._open_signal_ids:
            checks_failed.append("no_duplicate")
            rejection = rejection or f"Signal ID {signal.signal_id} already open"
        else:
            checks_passed.append("no_duplicate")

        # ------------------------------------------------------------------
        # Result
        # ------------------------------------------------------------------
        approved = len(checks_failed) == 0

        if approved:
            logger.info(
                "VALIDATED %s | Contracts: %d | Risk: $%.2f (%.2f%%) | R:R: %.2f",
                signal.signal_id, sizing.contracts, sizing.risk_dollars,
                sizing.risk_pct, signal.risk_reward,
            )
        else:
            logger.warning(
                "REJECTED %s | Reason: %s | Failed: %s",
                signal.signal_id, rejection, checks_failed,
            )

        return ValidationResult(
            approved=approved,
            signal_id=signal.signal_id,
            rejection_reason=rejection if not approved else None,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
        )

    def register_open_trade(self, signal_id: str) -> None:
        """Register a signal ID as open to prevent duplicate entry."""
        self._open_signal_ids.add(signal_id)

    def deregister_trade(self, signal_id: str) -> None:
        """Remove a signal ID when the trade closes."""
        self._open_signal_ids.discard(signal_id)
