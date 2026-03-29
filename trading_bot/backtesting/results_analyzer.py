"""
backtesting/results_analyzer.py — Trade Results Analysis and Reporting

Responsibilities:
- Accept a BacktestResult and compute a full PerformanceReport via metrics.py
- Generate an equity curve plot (Plotly)
- Produce a per-trade breakdown DataFrame (entry/exit/P&L/R-multiple per trade)
- Export results as JSON summary and CSV trade log

This module is for analysis and visualization only — no trading logic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import pandas as pd

from backtesting.backtest_engine import BacktestResult
from backtesting.metrics import PerformanceReport, compute_metrics

logger = logging.getLogger(__name__)


class ResultsAnalyzer:
    """
    Analyze and report on a completed BacktestResult.

    Usage:
        analyzer = ResultsAnalyzer(result)
        report = analyzer.compute_report()
        analyzer.print_summary(report)
        analyzer.export_csv("results/trades.csv")
        analyzer.plot_equity_curve()
    """

    def __init__(self, result: BacktestResult) -> None:
        self.result = result
        self._trade_df: Optional[pd.DataFrame] = None

    def compute_report(self) -> PerformanceReport:
        """Compute and return full PerformanceReport from the backtest result."""
        closed_orders = [o for o in self.result.orders if o.status == "CLOSED" and o.realized_pnl is not None]

        pnls = [o.realized_pnl for o in closed_orders]  # type: ignore[misc]
        risk_per_trade = [
            s.stop_distance * 20.0  # stop_distance × NQ point value
            for s in self.result.signals
            if s.signal_id in {o.signal_id for o in closed_orders}
        ]

        # Bars held: fill_time → close_time approximation using bar timestamps
        bars_held: Optional[list[int]] = None

        report = compute_metrics(
            pnls=pnls,
            equity_curve=self.result.equity_curve,
            risk_per_trade=risk_per_trade if len(risk_per_trade) == len(pnls) else None,
            bars_held=bars_held,
            starting_balance=self.result.starting_balance,
        )

        logger.info("Performance report computed: %d trades analyzed", len(pnls))
        return report

    def build_trade_dataframe(self) -> pd.DataFrame:
        """
        Build a per-trade DataFrame for detailed analysis.

        Columns:
            order_id, signal_id, symbol, side, quantity,
            fill_price, close_price, stop_price, take_profit_price,
            fill_time, close_time, realized_pnl, commission, exit_reason
        """
        closed = [o for o in self.result.orders if o.status == "CLOSED"]
        if not closed:
            return pd.DataFrame()

        rows = []
        for o in closed:
            rows.append({
                "order_id": o.order_id,
                "signal_id": o.signal_id,
                "symbol": o.symbol,
                "side": o.side,
                "quantity": o.quantity,
                "fill_price": o.fill_price,
                "close_price": o.close_price,
                "stop_price": o.stop_price,
                "take_profit_price": o.take_profit_price,
                "fill_time": o.fill_time,
                "close_time": o.close_time,
                "realized_pnl": o.realized_pnl,
                "commission": o.commission,
                "exit_reason": o.notes,
            })

        self._trade_df = pd.DataFrame(rows)
        return self._trade_df

    def print_summary(self, report: PerformanceReport) -> None:
        """Print a formatted performance summary to stdout."""
        r = report
        sep = "─" * 55

        print(f"\n{'=' * 55}")
        print(f"  BACKTEST REPORT: {self.result.symbol} [{self.result.timeframe}]")
        print(f"  {self.result.start_date}  →  {self.result.end_date}")
        print(f"{'=' * 55}")
        print(f"  Bars Analyzed     : {self.result.total_bars:,}")
        print(f"  Signals Generated : {self.result.signals_generated:,}")
        print(f"  Trades Taken      : {r.total_trades:,}")
        print(f"  Trades Rejected   : {self.result.trades_rejected:,}")
        print(sep)
        print(f"  Win Rate          : {r.win_rate_pct:.1f}%  "
              f"({r.winning_trades}W / {r.losing_trades}L)")
        print(f"  Profit Factor     : {r.profit_factor or 'N/A'}")
        print(f"  Expectancy        : ${r.expectancy_dollar:,.2f} / trade")
        if r.expectancy_r is not None:
            print(f"  Expectancy (R)    : {r.expectancy_r:.2f}R")
        print(sep)
        print(f"  Total P&L         : ${r.total_pnl:+,.2f}")
        print(f"  Total Return      : {r.total_return_pct:+.2f}%")
        print(f"  Starting Balance  : ${self.result.starting_balance:,.2f}")
        print(f"  Ending Balance    : ${self.result.ending_balance:,.2f}")
        print(sep)
        print(f"  Avg Winner        : ${r.avg_winner:,.2f}")
        print(f"  Avg Loser         : ${r.avg_loser:,.2f}")
        print(f"  Largest Winner    : ${r.largest_winner:,.2f}")
        print(f"  Largest Loser     : ${r.largest_loser:,.2f}")
        print(sep)
        print(f"  Max Drawdown      : {r.max_drawdown_pct:.2f}%  (${r.max_drawdown_dollar:,.2f})")
        print(f"  Sharpe Ratio      : {r.sharpe_ratio or 'N/A'}")
        print(f"  Calmar Ratio      : {r.calmar_ratio or 'N/A'}")
        print(f"{'=' * 55}\n")

    def export_csv(self, path: str) -> None:
        """Export trade log to CSV."""
        df = self.build_trade_dataframe()
        if df.empty:
            logger.warning("No closed trades to export")
            return
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        logger.info("Trade log exported to %s (%d rows)", path, len(df))

    def export_json(self, path: str, report: PerformanceReport) -> None:
        """Export full report as JSON (metrics + metadata)."""
        payload = {
            "metadata": {
                "symbol": self.result.symbol,
                "timeframe": self.result.timeframe,
                "start_date": self.result.start_date,
                "end_date": self.result.end_date,
                "total_bars": self.result.total_bars,
            },
            "metrics": asdict(report),
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        logger.info("JSON report exported to %s", path)

    def plot_equity_curve(self, show: bool = True, save_path: Optional[str] = None) -> None:
        """
        Plot the equity curve using Plotly.

        Parameters
        ----------
        show      : Display the chart interactively
        save_path : Optional path to save as HTML file
        """
        try:
            import plotly.graph_objects as go
        except ImportError:
            logger.error("Plotly not installed. Run: pip install plotly")
            return

        curve = self.result.equity_curve
        if not curve:
            logger.warning("No equity curve data to plot")
            return

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=curve,
            mode="lines",
            name="Equity Curve",
            line=dict(color="steelblue", width=2),
        ))
        fig.add_hline(
            y=self.result.starting_balance,
            line_dash="dash",
            line_color="gray",
            annotation_text="Starting Balance",
        )
        fig.update_layout(
            title=f"Equity Curve — {self.result.symbol} [{self.result.timeframe}] "
                  f"{self.result.start_date} to {self.result.end_date}",
            xaxis_title="Bar Index",
            yaxis_title="Account Balance ($)",
            template="plotly_dark",
        )

        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            fig.write_html(save_path)
            logger.info("Equity curve saved to %s", save_path)

        if show:
            fig.show()
