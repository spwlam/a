"""
monitoring/ — Observability, Logging, and Alerting Package

Modules:
    trade_journal  : Structured per-trade logging. Every trade action (signal,
                     fill, stop hit, TP hit, close) is recorded as a JSON log
                     entry with full context for post-session review.
    dashboard      : CLI or web dashboard showing live session metrics.
                     Uses Rich for terminal display or Plotly Dash for browser.
    alerting       : Alert dispatch for significant events (new signal, trade
                     closed, daily limit hit, session halt). Supports terminal,
                     file log, and extensible notification channels.

Design principle:
    Monitoring modules are read-only with respect to trading state.
    They receive events from other modules but do not influence trading decisions.
"""
