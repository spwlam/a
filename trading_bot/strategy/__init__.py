"""
strategy/ — ICT + Strat Signal Generation Package

This package contains all strategy logic. The processing pipeline flows as:

    1. strat_classifier   → label each bar as Type 1, 2u, 2d, or 3
    2. strat_patterns     → detect multi-bar Strat patterns (2-1-2, 3-1-2, etc.)
    3. ict_levels         → mark key price levels (PDH/PDL, PWH/PWL, liquidity)
    4. ict_structure      → detect BOS, MSS, displacement
    5. ict_fvg            → identify and track unmitigated Fair Value Gaps
    6. ict_context        → determine HTF bias and market structure context
    7. filters            → session, volatility, spread gate checks
    8. signal_engine      → combine all inputs into actionable trade signals

No module in this package should import from execution/, risk/, or monitoring/.
Strategy logic must be pure: given price data, produce signals.
"""
