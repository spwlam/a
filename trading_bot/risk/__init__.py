"""
risk/ — Risk Management Package

This package enforces all risk rules before any order reaches the execution layer.
It is the last gate between signal generation and order placement.

Modules:
    risk_manager    : Position sizing, daily loss tracking, drawdown controls
    trade_validator : Pre-trade validation — checks every proposed trade against
                      all hard limits defined in risk_config.yaml

Design contract:
    - Risk rules are NEVER relaxed or bypassed, even in paper trading mode
    - Position sizing math must be deterministic and reproducible
    - All rejections are logged with the specific rule that failed
    - The risk_manager maintains state across the trading session (daily P&L, open positions)
"""
