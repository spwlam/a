"""
execution/ — Order Execution Package

This package handles all order lifecycle management: creation, placement,
fill simulation (paper), and closure.

Modules:
    broker_base     : Abstract base class defining the broker interface contract.
                      All concrete broker implementations must subclass this.
    paper_trader    : Simulated order execution for paper trading.
                      Implements broker_base.BrokerBase with in-memory order state.
    order_manager   : Manages the lifecycle of open orders (pending → filled → closed).
                      Works with any broker implementation.

Design contract:
    - All execution modules receive validated TradeSignal + SizingResult pairs only.
      The risk and validation layers must be passed before anything reaches here.
    - Execution modules must NEVER make strategy decisions (no buy/sell logic here).
    - Paper trader must enforce slippage and commission to produce realistic results.
    - Switching from paper to live is achieved by swapping the broker implementation,
      not by changing any other module.
"""
