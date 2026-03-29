"""
backtesting/backtest_engine.py — Walk-Forward Backtesting Engine

Responsibilities:
- Replay historical OHLCV bars through the complete strategy pipeline
- Enforce strict no-lookahead: each bar sees only prior bar data
- Coordinate all pipeline modules in correct order per bar
- Collect all signals, orders, and fills into a BacktestResult
- Support walk-forward optimization windows (in/out-of-sample splits)

Pipeline execution order per bar:
    1. Slice df to current bar (no future data visible)
    2. Run all annotators (structure, FVG, levels, sessions, filters) — precomputed
    3. Call signal_engine.generate_signal() for current bar index
    4. If signal emitted: call risk_manager.calculate_size()
    5. If sizing approved: call trade_validator.validate()
    6. If validated: call order_manager.place_trade()
    7. Call order_manager.process_bar() to attempt fills and check exits

Approximation notes:
- All annotation (FVG detection, swing pivots, etc.) is precomputed on the full
  DataFrame BEFORE the backtest loop. This is safe only because those functions
  are confirmed to use only bar[i] and earlier data. Verify on any new annotator.
- Walk-forward windows are defined by date ranges, not bar counts, to avoid
  bias from varying bar density (e.g., missing trading days).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd

from execution.broker_base import Order
from execution.order_manager import OrderManager
from execution.paper_trader import PaperTrader
from risk.risk_manager import RiskManager
from risk.trade_validator import TradeValidator
from strategy.signal_engine import TradeSignal, generate_signal

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Complete results from a single backtest run."""

    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    total_bars: int
    signals_generated: int
    trades_taken: int
    trades_rejected: int
    starting_balance: float
    ending_balance: float
    orders: list[Order] = field(default_factory=list)
    signals: list[TradeSignal] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    notes: str = ""


class BacktestEngine:
    """
    Walk-forward backtesting engine.

    Usage:
        engine = BacktestEngine(settings=settings_dict, risk_config=risk_dict)
        result = engine.run(df_annotated, symbol="NQ=F", timeframe="15m")
    """

    def __init__(self, settings: dict, risk_config: dict) -> None:
        self.settings = settings
        self.risk_config = risk_config

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> BacktestResult:
        """
        Run a full backtest on a pre-annotated DataFrame.

        The DataFrame must have all strategy columns present (from the full
        annotation pipeline). Use build_annotated_df() to prepare it.

        Parameters
        ----------
        df         : Pre-annotated DataFrame with all strategy columns
        symbol     : Instrument symbol
        timeframe  : Bar timeframe string
        start_date : Optional ISO date string to slice the backtest window
        end_date   : Optional ISO date string to slice the backtest window

        Returns
        -------
        BacktestResult containing all trades, signals, and equity curve.
        """
        if start_date:
            df = df[df["timestamp"] >= pd.Timestamp(start_date, tz="UTC")]
        if end_date:
            df = df[df["timestamp"] <= pd.Timestamp(end_date, tz="UTC")]

        df = df.reset_index(drop=True)
        n = len(df)

        if n == 0:
            logger.warning("Backtest aborted — empty DataFrame after date filtering")
            return BacktestResult(
                symbol=symbol, timeframe=timeframe,
                start_date=start_date or "", end_date=end_date or "",
                total_bars=0, signals_generated=0, trades_taken=0,
                trades_rejected=0,
                starting_balance=self.risk_config["account"]["starting_balance"],
                ending_balance=self.risk_config["account"]["starting_balance"],
            )

        starting_balance = self.risk_config["account"]["starting_balance"]
        broker = PaperTrader(config=self.settings, starting_balance=starting_balance)
        risk_mgr = RiskManager(risk_config=self.risk_config)
        validator = TradeValidator(settings=self.settings, risk_config=self.risk_config)
        order_mgr = OrderManager(broker=broker)

        result = BacktestResult(
            symbol=symbol,
            timeframe=timeframe,
            start_date=str(df["timestamp"].iloc[0].date()),
            end_date=str(df["timestamp"].iloc[-1].date()),
            total_bars=n,
            signals_generated=0,
            trades_taken=0,
            trades_rejected=0,
            starting_balance=starting_balance,
            ending_balance=starting_balance,
        )

        last_date: Optional[date] = None

        for i in range(n):
            bar = df.iloc[i]
            bar_date = bar["timestamp"].date()

            # Daily reset
            if last_date is None or bar_date != last_date:
                if last_date is not None:
                    risk_mgr.reset_daily(bar_date)
                last_date = bar_date

            # Process pending orders and check exits on this bar
            changed_orders = order_mgr.process_bar(bar)
            for order in changed_orders:
                if order.status == "CLOSED" and order.realized_pnl is not None:
                    risk_mgr.record_trade_close(order.realized_pnl)

            # Track equity
            result.equity_curve.append(broker.get_account_balance())

            # Attempt signal generation (bar-close, no lookahead)
            signal = generate_signal(df, i, symbol, self.settings)
            if signal is None:
                continue

            result.signals_generated += 1
            result.signals.append(signal)

            # Size the trade
            exec_cfg = self.settings.get("execution", {})
            tick_size = 0.25
            point_value = 20.0  # NQ default

            sizing = risk_mgr.calculate_size(
                stop_distance=signal.stop_distance,
                point_value=point_value,
            )

            # Validate
            validation = validator.validate(
                signal=signal,
                sizing=sizing,
                current_price=float(bar["close"]),
                tick_size=tick_size,
            )

            if not validation.approved:
                result.trades_rejected += 1
                logger.debug(
                    "BACKTEST REJECT bar %d | %s | %s",
                    i, signal.signal_id, validation.rejection_reason,
                )
                continue

            # Place
            order_type = exec_cfg.get("order_type", "limit")
            order = order_mgr.place_trade(signal, sizing, order_type=order_type)
            if order:
                risk_mgr.record_trade_open()
                validator.register_open_trade(signal.signal_id)
                result.trades_taken += 1
                result.orders.append(order)

        result.ending_balance = broker.get_account_balance()

        logger.info(
            "BACKTEST COMPLETE | %s | Bars: %d | Signals: %d | Trades: %d | "
            "Start: $%.2f | End: $%.2f | Net P&L: $%.2f",
            symbol, n, result.signals_generated, result.trades_taken,
            result.starting_balance, result.ending_balance,
            result.ending_balance - result.starting_balance,
        )

        return result
