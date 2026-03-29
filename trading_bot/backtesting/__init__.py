"""
backtesting/ — Walk-Forward Backtesting Package

This package provides a rigorous, no-lookahead backtesting framework.

Modules:
    backtest_engine   : Core walk-forward backtester. Feeds bars one at a time
                        to the full strategy pipeline (signal → risk → execution).
                        Enforces bar-close-only signal generation.
    metrics           : Computes standard quantitative trading performance metrics:
                        win rate, profit factor, expectancy, Sharpe ratio, max drawdown,
                        Calmar ratio, and per-trade statistics.
    results_analyzer  : Processes raw trade results into reports and equity curves.
                        Produces plots via Plotly and exportable JSON/CSV summaries.

Key anti-lookahead rules enforced:
    - Signal generation uses only df.iloc[:i+1] — never future bars
    - HTF bias is forward-filled from the most recently CLOSED HTF bar
    - FVG mitigation is only checked up to the current bar
    - Limit orders fill only when a subsequent bar's price crosses the limit level
"""
