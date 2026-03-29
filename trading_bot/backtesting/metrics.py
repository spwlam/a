"""
backtesting/metrics.py — Performance Metrics Calculator

Responsibilities:
- Compute standard quantitative trading metrics from a list of closed trades
- All metrics computed from realized P&L only (no open position valuation)
- Return a structured PerformanceReport dataclass

Metrics computed:
    Win rate            : % of trades with positive realized P&L
    Profit factor       : Gross profit / Gross loss (>1.5 is acceptable, >2.0 is good)
    Expectancy          : Average P&L per trade in dollars
    Expectancy (R)      : Average P&L per trade normalized to initial risk (R-multiple)
    Average winner      : Mean P&L of winning trades
    Average loser       : Mean P&L of losing trades
    Largest winner      : Single best trade
    Largest loser       : Single worst trade
    Max drawdown        : Largest peak-to-trough decline in equity curve (%)
    Max drawdown ($)    : Same in absolute dollars
    Sharpe ratio        : Annualized Sharpe using daily returns (risk-free = 0)
    Calmar ratio        : Annualized return / Max drawdown
    Total return (%)    : (ending - starting) / starting × 100
    Bars held avg       : Average number of bars a trade was open

All metrics are computed without lookahead. Inputs are completed trade records only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class PerformanceReport:
    """All computed performance metrics for a backtest or live session."""

    # Trade counts
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float

    # P&L
    total_pnl: float
    gross_profit: float
    gross_loss: float
    profit_factor: Optional[float]          # None if no losing trades
    expectancy_dollar: float
    expectancy_r: Optional[float]           # None if risk data unavailable

    # Per-trade
    avg_winner: float
    avg_loser: float
    largest_winner: float
    largest_loser: float
    avg_r_multiple: Optional[float]

    # Drawdown
    max_drawdown_pct: float
    max_drawdown_dollar: float

    # Risk-adjusted
    sharpe_ratio: Optional[float]
    calmar_ratio: Optional[float]
    total_return_pct: float

    # Duration
    avg_bars_held: Optional[float]


def compute_metrics(
    pnls: list[float],
    equity_curve: list[float],
    risk_per_trade: Optional[list[float]] = None,
    bars_held: Optional[list[int]] = None,
    starting_balance: float = 100_000.0,
    bars_per_year: int = 252 * 26,   # 252 trading days × 26 x 15min bars/day ≈ 6552
) -> PerformanceReport:
    """
    Compute all performance metrics from raw trade and equity data.

    Parameters
    ----------
    pnls            : List of realized P&L per closed trade (dollars)
    equity_curve    : List of account balance after each BAR (not each trade)
    risk_per_trade  : Optional list of dollar risk for each trade (for R-multiple calc)
    bars_held       : Optional list of bars each trade was open
    starting_balance: Initial account balance
    bars_per_year   : Used for Sharpe annualization (default 15m bars in a trading year)

    Returns
    -------
    PerformanceReport dataclass
    """
    if not pnls:
        return _empty_report()

    pnls_arr = np.array(pnls, dtype=float)
    winners = pnls_arr[pnls_arr > 0]
    losers = pnls_arr[pnls_arr <= 0]

    total_trades = len(pnls_arr)
    winning_trades = len(winners)
    losing_trades = len(losers)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

    gross_profit = float(winners.sum()) if len(winners) > 0 else 0.0
    gross_loss = float(abs(losers.sum())) if len(losers) > 0 else 0.0
    total_pnl = float(pnls_arr.sum())

    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None
    expectancy_dollar = float(pnls_arr.mean())

    # R-multiple stats
    expectancy_r: Optional[float] = None
    avg_r_multiple: Optional[float] = None
    if risk_per_trade and len(risk_per_trade) == total_trades:
        risk_arr = np.array(risk_per_trade, dtype=float)
        valid = risk_arr > 0
        if valid.any():
            r_multiples = pnls_arr[valid] / risk_arr[valid]
            expectancy_r = float(r_multiples.mean())
            avg_r_multiple = float(r_multiples.mean())

    avg_winner = float(winners.mean()) if len(winners) > 0 else 0.0
    avg_loser = float(losers.mean()) if len(losers) > 0 else 0.0
    largest_winner = float(winners.max()) if len(winners) > 0 else 0.0
    largest_loser = float(losers.min()) if len(losers) > 0 else 0.0

    # Drawdown from equity curve
    max_dd_pct, max_dd_dollar = _compute_drawdown(equity_curve, starting_balance)

    # Sharpe ratio (annualized, using bar-level equity changes)
    sharpe = _compute_sharpe(equity_curve, bars_per_year)

    # Total return
    ending_balance = equity_curve[-1] if equity_curve else starting_balance
    total_return_pct = (ending_balance - starting_balance) / starting_balance * 100

    # Calmar ratio
    calmar: Optional[float] = None
    if max_dd_pct > 0:
        annualized_return = total_return_pct  # Single period approximation
        calmar = annualized_return / max_dd_pct

    # Average bars held
    avg_bars: Optional[float] = None
    if bars_held:
        avg_bars = float(np.mean(bars_held))

    return PerformanceReport(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_pct=round(win_rate, 2),
        total_pnl=round(total_pnl, 2),
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        profit_factor=round(profit_factor, 3) if profit_factor is not None else None,
        expectancy_dollar=round(expectancy_dollar, 2),
        expectancy_r=round(expectancy_r, 3) if expectancy_r is not None else None,
        avg_winner=round(avg_winner, 2),
        avg_loser=round(avg_loser, 2),
        largest_winner=round(largest_winner, 2),
        largest_loser=round(largest_loser, 2),
        avg_r_multiple=round(avg_r_multiple, 3) if avg_r_multiple is not None else None,
        max_drawdown_pct=round(max_dd_pct, 2),
        max_drawdown_dollar=round(max_dd_dollar, 2),
        sharpe_ratio=round(sharpe, 3) if sharpe is not None else None,
        calmar_ratio=round(calmar, 3) if calmar is not None else None,
        total_return_pct=round(total_return_pct, 2),
        avg_bars_held=round(avg_bars, 1) if avg_bars is not None else None,
    )


def _compute_drawdown(equity_curve: list[float], starting_balance: float) -> tuple[float, float]:
    """Compute max drawdown as (pct, dollar) from an equity curve."""
    if not equity_curve:
        return 0.0, 0.0

    curve = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(curve)
    dd_dollar = peak - curve
    dd_pct = dd_dollar / peak * 100

    max_dd_dollar = float(dd_dollar.max())
    max_dd_pct = float(dd_pct.max())
    return max_dd_pct, max_dd_dollar


def _compute_sharpe(equity_curve: list[float], bars_per_year: int) -> Optional[float]:
    """Compute annualized Sharpe ratio from bar-level equity curve (risk-free = 0)."""
    if len(equity_curve) < 2:
        return None

    curve = np.array(equity_curve, dtype=float)
    returns = np.diff(curve) / curve[:-1]  # Bar-level returns

    if returns.std() == 0:
        return None

    sharpe = (returns.mean() / returns.std()) * math.sqrt(bars_per_year)
    return float(sharpe)


def _empty_report() -> PerformanceReport:
    """Return a zeroed report when there are no trades."""
    return PerformanceReport(
        total_trades=0, winning_trades=0, losing_trades=0,
        win_rate_pct=0.0, total_pnl=0.0, gross_profit=0.0,
        gross_loss=0.0, profit_factor=None, expectancy_dollar=0.0,
        expectancy_r=None, avg_winner=0.0, avg_loser=0.0,
        largest_winner=0.0, largest_loser=0.0, avg_r_multiple=None,
        max_drawdown_pct=0.0, max_drawdown_dollar=0.0,
        sharpe_ratio=None, calmar_ratio=None, total_return_pct=0.0,
        avg_bars_held=None,
    )
