"""
monitoring/dashboard.py — Session Metrics Dashboard

Responsibilities:
- Display live (or post-session) trading metrics in the terminal using Rich
- Show open positions, daily P&L, signal count, and risk state
- Refresh automatically during live/paper trading sessions

Two display modes:
    Terminal (Rich): Rendered table in the CLI — no browser required.
                     Suitable for paper trading and backtesting review.
    Web (Plotly Dash): Full browser dashboard — planned for future iteration.
                       Placeholder here.

Usage:
    dashboard = Dashboard(risk_manager, order_manager, journal)
    dashboard.render()          # One-time snapshot
    dashboard.run_live(interval=5)  # Auto-refresh every N seconds (blocking)
"""

from __future__ import annotations

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class Dashboard:
    """
    Terminal dashboard using Rich for live session display.

    Accepts references to live risk_manager and order_manager instances.
    Reads state without modifying it.
    """

    def __init__(
        self,
        risk_manager=None,
        order_manager=None,
        journal=None,
        symbol: str = "N/A",
    ) -> None:
        self.risk_manager = risk_manager
        self.order_manager = order_manager
        self.journal = journal
        self.symbol = symbol

    def render(self) -> None:
        """Render a one-time snapshot of session state to the terminal."""
        try:
            from rich.console import Console
            from rich.table import Table
            from rich import box
        except ImportError:
            logger.error("Rich not installed. Run: pip install rich")
            self._fallback_render()
            return

        console = Console()

        console.print(f"\n[bold cyan]ICT+Strat Trading Bot[/bold cyan] — {self.symbol}", justify="center")
        console.print("─" * 60, justify="center")

        # Risk state table
        if self.risk_manager:
            state = self.risk_manager.get_state_summary()
            table = Table(title="Session Risk State", box=box.ROUNDED, header_style="bold magenta")
            table.add_column("Metric", style="dim")
            table.add_column("Value", justify="right")

            color = "red" if state["is_halted"] else "green"
            table.add_row("Status", f"[{color}]{'HALTED' if state['is_halted'] else 'ACTIVE'}[/{color}]")
            table.add_row("Balance", f"${state['balance']:,.2f}")
            daily_color = "green" if state["daily_pnl"] >= 0 else "red"
            table.add_row("Daily P&L", f"[{daily_color}]${state['daily_pnl']:+,.2f}[/{daily_color}]")
            table.add_row("Trades Taken", str(state["trades_taken"]))
            table.add_row("Open Positions", str(state["open_positions"]))
            table.add_row("Consec. Losses", str(state["consecutive_losses"]))
            dd_color = "red" if state["drawdown_pct"] > 5 else "yellow" if state["drawdown_pct"] > 2 else "green"
            table.add_row("Drawdown", f"[{dd_color}]{state['drawdown_pct']:.2f}%[/{dd_color}]")
            console.print(table)

        # Open positions table
        if self.order_manager:
            positions = self.order_manager.broker.get_open_positions()
            if positions:
                pos_table = Table(title="Open Positions", box=box.SIMPLE_HEAD)
                pos_table.add_column("Order ID")
                pos_table.add_column("Symbol")
                pos_table.add_column("Side")
                pos_table.add_column("Qty", justify="right")
                pos_table.add_column("Entry", justify="right")
                pos_table.add_column("SL", justify="right")
                pos_table.add_column("TP", justify="right")
                for p in positions:
                    pos_table.add_row(
                        p.order_id, p.symbol, p.side.upper(), str(p.quantity),
                        f"{p.fill_price:.2f}" if p.fill_price else "—",
                        f"{p.stop_price:.2f}" if p.stop_price else "—",
                        f"{p.take_profit_price:.2f}" if p.take_profit_price else "—",
                    )
                console.print(pos_table)
            else:
                console.print("[dim]No open positions[/dim]")

        # Journal summary
        if self.journal and self.journal.in_memory:
            summary = self.journal.session_summary()
            console.print(
                f"\n[bold]Journal:[/bold] "
                f"{summary['signals_generated']} signals | "
                f"{summary['trades_closed']} closed | "
                f"Win rate {summary['win_rate_pct']}% | "
                f"P&L ${summary['total_pnl']:+,.2f}"
            )

        console.print()

    def run_live(self, interval: int = 5) -> None:
        """
        Auto-refresh the dashboard every `interval` seconds.
        Blocking — run in a thread for non-blocking operation.

        Parameters
        ----------
        interval : Refresh interval in seconds
        """
        try:
            from rich.live import Live
            from rich.console import Console
            console = Console()
            logger.info("Dashboard live mode started. Press Ctrl+C to stop.")
            while True:
                console.clear()
                self.render()
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Dashboard stopped by user")
        except ImportError:
            logger.error("Rich not installed — cannot run live dashboard")

    def _fallback_render(self) -> None:
        """Minimal fallback renderer when Rich is not available."""
        print("\n=== ICT+Strat Session Dashboard ===")
        if self.risk_manager:
            state = self.risk_manager.get_state_summary()
            for k, v in state.items():
                print(f"  {k}: {v}")
        print("===================================\n")
