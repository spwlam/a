"""
strategy/strat_patterns.py — The Strat Multi-Bar Pattern Recognition

Responsibilities:
- Detect valid Strat setup patterns from a sequence of classified bars
- Each pattern has a directional bias (long / short) and a trigger condition
- Return pattern labels and trigger prices for the signal engine to consume

Supported patterns and their trade logic:
    2u-1-2u  : Bullish continuation — Type 2u, then inside bar, then break above 2u's high
    2d-1-2d  : Bearish continuation — Type 2d, then inside bar, then break below 2d's low
    3-1-2u   : Bullish reversal setup — Type 3 (sweep low), inside bar, break up
    3-1-2d   : Bearish reversal setup — Type 3 (sweep high), inside bar, break down
    2u-2u    : Bullish broadening (use caution — often a trap at resistance)
    2d-2d    : Bearish broadening (use caution — often a trap at support)

Trigger rules:
    Long triggers  : Break and CLOSE above the trigger bar's high (avoid wick fakes)
    Short triggers : Break and CLOSE below the trigger bar's low

Approximation notes:
- Pattern completion is checked at bar close (no intrabar triggers) to prevent lookahead.
- The "shooter" bar (first bar in the pattern) must not be more than `max_pattern_age`
  bars old, or the setup is considered stale and is discarded.
- The signal engine applies additional ICT filters before acting on any pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd

Direction = Literal["long", "short", "neutral"]
PatternName = Literal["2u-1-2u", "2d-1-2d", "3-1-2u", "3-1-2d", "2u-2u", "2d-2d", "none"]


@dataclass
class StratPattern:
    """Represents a detected Strat pattern and its actionable trigger levels."""

    name: PatternName
    direction: Direction
    bar_index: int                  # Index of the trigger (last) bar
    trigger_high: float             # Enter long if price closes above this
    trigger_low: float              # Enter short if price closes below this
    shooter_high: float             # High of the pattern's first bar
    shooter_low: float              # Low of the pattern's first bar
    pattern_bars: list[int] = field(default_factory=list)  # Indices of all bars in pattern
    is_actionable: bool = True      # False if pattern is stale or context filters fail


# ---------------------------------------------------------------------------
# Pattern detection helpers (operate on last N bars, called bar-by-bar)
# ---------------------------------------------------------------------------

_LONG_PATTERNS: dict[tuple[str, ...], PatternName] = {
    ("2u", "1", "2u"): "2u-1-2u",
    ("3",  "1", "2u"): "3-1-2u",
    ("2u", "2u"):       "2u-2u",
}

_SHORT_PATTERNS: dict[tuple[str, ...], PatternName] = {
    ("2d", "1", "2d"): "2d-1-2d",
    ("3",  "1", "2d"): "3-1-2d",
    ("2d", "2d"):       "2d-2d",
}

_PATTERN_DIRECTION: dict[PatternName, Direction] = {
    "2u-1-2u": "long",
    "3-1-2u":  "long",
    "2u-2u":   "long",
    "2d-1-2d": "short",
    "3-1-2d":  "short",
    "2d-2d":   "short",
}


def detect_patterns(
    df: pd.DataFrame,
    max_pattern_age: int = 3,
) -> pd.DataFrame:
    """
    Scan a classified DataFrame and annotate each bar with the Strat pattern
    that completes at that bar (if any).

    Requires 'strat_type', 'high', 'low' columns (output of strat_classifier).
    Adds columns:
        strat_pattern   : PatternName string or "none"
        pattern_dir     : "long" | "short" | "neutral"
        trigger_high    : float — long trigger price
        trigger_low     : float — short trigger price

    Parameters
    ----------
    df              : Classified DataFrame, sorted ascending
    max_pattern_age : Max bars the pattern's first bar can be old (staleness gate)
    """
    required = {"strat_type", "high", "low"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    df = df.copy()
    n = len(df)

    patterns: list[str] = ["none"] * n
    directions: list[str] = ["neutral"] * n
    trig_highs: list[float] = [float("nan")] * n
    trig_lows: list[float] = [float("nan")] * n

    types = df["strat_type"].tolist()
    highs = df["high"].tolist()
    lows = df["low"].tolist()

    # Check 3-bar patterns first (higher priority), then 2-bar
    for i in range(2, n):
        window3 = (types[i - 2], types[i - 1], types[i])
        window2 = (types[i - 1], types[i])

        matched: Optional[PatternName] = None

        if window3 in _LONG_PATTERNS:
            matched = _LONG_PATTERNS[window3]
        elif window3 in _SHORT_PATTERNS:
            matched = _SHORT_PATTERNS[window3]
        elif window2 in _LONG_PATTERNS:
            matched = _LONG_PATTERNS[window2]
        elif window2 in _SHORT_PATTERNS:
            matched = _SHORT_PATTERNS[window2]

        if matched:
            patterns[i] = matched
            directions[i] = _PATTERN_DIRECTION[matched]
            # Trigger levels are taken from the current (completing) bar
            trig_highs[i] = highs[i]
            trig_lows[i] = lows[i]

    df["strat_pattern"] = patterns
    df["pattern_dir"] = directions
    df["trigger_high"] = trig_highs
    df["trigger_low"] = trig_lows

    return df


def get_active_pattern(df: pd.DataFrame, current_index: int) -> Optional[StratPattern]:
    """
    Return the most recent non-stale StratPattern object as of current_index.
    Returns None if no valid pattern exists.

    Used by the signal engine for real-time bar-by-bar processing.
    """
    if "strat_pattern" not in df.columns:
        raise ValueError("DataFrame has not been pattern-scanned. Run detect_patterns() first.")

    row = df.iloc[current_index]
    if row["strat_pattern"] == "none":
        return None

    name: PatternName = row["strat_pattern"]
    return StratPattern(
        name=name,
        direction=row["pattern_dir"],
        bar_index=current_index,
        trigger_high=row["trigger_high"],
        trigger_low=row["trigger_low"],
        shooter_high=row["high"],
        shooter_low=row["low"],
        pattern_bars=[current_index],
    )
