"""
strategy/ict_fvg.py — ICT Fair Value Gap (FVG) Detection and Tracking

Responsibilities:
- Detect bullish and bearish Fair Value Gaps in OHLCV data
- Track mitigation status of each FVG (unmitigated = still valid entry zone)
- Provide the nearest unmitigated FVG for signal engine entry zone validation

What is a Fair Value Gap (ICT definition)?
    A 3-bar price imbalance where:
        Bullish FVG: bar[i].low > bar[i-2].high  (gap between candle 1's high and candle 3's low)
        Bearish FVG: bar[i].high < bar[i-2].low  (gap between candle 1's low and candle 3's high)

    The middle bar (bar[i-1]) is the "impulse" candle that created the displacement.
    Price should return to fill (mitigate) the FVG before continuing in the original direction.

Mitigation rules:
    A bullish FVG is mitigated when close price touches or enters the gap zone from above.
    A bearish FVG is mitigated when close price touches or enters the gap zone from below.
    Once fully mitigated (price closes through the entire gap), the FVG is invalidated.

Approximation notes:
- True ICT FVG analysis includes the "50% of the FVG" (equilibrium) as an ideal entry.
  We expose this as fvg_midpoint for use in entry price calculations.
- Partial mitigation (price enters gap but doesn't close through) keeps the FVG valid
  but may reduce its strength. This is flagged but not invalidated.
- FVGs created during off-hours or low-liquidity sessions are lower quality.
  The signal engine applies session filters to gate these separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import pandas as pd

FVGType = Literal["bullish", "bearish"]


@dataclass
class FairValueGap:
    """Represents a single detected FVG and its current mitigation status."""

    id: int                         # Sequential ID for tracking
    fvg_type: FVGType
    bar_index: int                  # Index of bar[i] that completed the FVG
    timestamp: pd.Timestamp
    top: float                      # Upper boundary of the gap
    bottom: float                   # Lower boundary of the gap
    midpoint: float                 # 50% level — ideal ICT entry zone
    impulse_high: float             # High of the middle (impulse) bar
    impulse_low: float              # Low of the middle (impulse) bar
    is_mitigated: bool = False
    is_invalidated: bool = False    # Price closed fully through the gap
    mitigation_bar: Optional[int] = None


def detect_fvgs(df: pd.DataFrame, min_gap_pct: float = 0.05) -> list[FairValueGap]:
    """
    Scan a DataFrame for all Fair Value Gaps.

    Parameters
    ----------
    df          : DataFrame with 'open', 'high', 'low', 'close', 'timestamp' columns
    min_gap_pct : Minimum gap size as % of current price to qualify (filters noise)

    Returns
    -------
    List of FairValueGap objects, sorted by bar_index ascending.
    No lookahead: FVG at index i is only detectable after bar[i] closes.
    """
    required = {"high", "low", "close", "timestamp"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    fvgs: list[FairValueGap] = []
    fvg_id = 0

    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    timestamps = df["timestamp"].tolist()
    n = len(df)

    for i in range(2, n):
        price_ref = closes[i]
        min_gap = price_ref * (min_gap_pct / 100.0)

        # Bullish FVG: gap between bar[i-2].high and bar[i].low
        if lows[i] > highs[i - 2]:
            gap_size = lows[i] - highs[i - 2]
            if gap_size >= min_gap:
                fvgs.append(FairValueGap(
                    id=fvg_id,
                    fvg_type="bullish",
                    bar_index=i,
                    timestamp=timestamps[i],
                    top=lows[i],
                    bottom=highs[i - 2],
                    midpoint=(lows[i] + highs[i - 2]) / 2,
                    impulse_high=highs[i - 1],
                    impulse_low=lows[i - 1],
                ))
                fvg_id += 1

        # Bearish FVG: gap between bar[i].high and bar[i-2].low
        elif highs[i] < lows[i - 2]:
            gap_size = lows[i - 2] - highs[i]
            if gap_size >= min_gap:
                fvgs.append(FairValueGap(
                    id=fvg_id,
                    fvg_type="bearish",
                    bar_index=i,
                    timestamp=timestamps[i],
                    top=lows[i - 2],
                    bottom=highs[i],
                    midpoint=(lows[i - 2] + highs[i]) / 2,
                    impulse_high=highs[i - 1],
                    impulse_low=lows[i - 1],
                ))
                fvg_id += 1

    return fvgs


def update_mitigation(
    fvgs: list[FairValueGap],
    df: pd.DataFrame,
) -> list[FairValueGap]:
    """
    Walk forward through bars after each FVG's creation and update mitigation status.

    Mitigation logic:
        Bullish FVG: mitigated when a subsequent bar's low <= fvg.top (price enters gap)
                     invalidated when a subsequent bar's close < fvg.bottom (gap fully filled)
        Bearish FVG: mitigated when a subsequent bar's high >= fvg.bottom (price enters gap)
                     invalidated when a subsequent bar's close > fvg.top (gap fully filled)

    Parameters
    ----------
    fvgs : List of FairValueGap objects from detect_fvgs()
    df   : Full OHLCV DataFrame (used to walk forward after each FVG's bar_index)

    Returns
    -------
    Updated list of FairValueGap objects with mitigation status set.
    """
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    n = len(df)

    for fvg in fvgs:
        for j in range(fvg.bar_index + 1, n):
            if fvg.fvg_type == "bullish":
                if closes[j] < fvg.bottom:
                    fvg.is_invalidated = True
                    fvg.is_mitigated = True
                    fvg.mitigation_bar = j
                    break
                elif lows[j] <= fvg.top:
                    fvg.is_mitigated = True
                    fvg.mitigation_bar = j
                    # Don't break — continue to check for full invalidation

            elif fvg.fvg_type == "bearish":
                if closes[j] > fvg.top:
                    fvg.is_invalidated = True
                    fvg.is_mitigated = True
                    fvg.mitigation_bar = j
                    break
                elif highs[j] >= fvg.bottom:
                    fvg.is_mitigated = True
                    fvg.mitigation_bar = j

    return fvgs


def annotate_fvgs(df: pd.DataFrame, fvgs: list[FairValueGap]) -> pd.DataFrame:
    """
    Add FVG summary columns to the DataFrame for downstream use.

    Adds:
        'nearest_bull_fvg_top'    : Top of nearest unmitigated bullish FVG
        'nearest_bull_fvg_bottom' : Bottom of nearest unmitigated bullish FVG
        'nearest_bear_fvg_top'    : Top of nearest unmitigated bearish FVG
        'nearest_bear_fvg_bottom' : Bottom of nearest unmitigated bearish FVG
        'in_bull_fvg'             : bool — current close is within a bullish FVG
        'in_bear_fvg'             : bool — current close is within a bearish FVG
    """
    df = df.copy()
    n = len(df)

    nb_top = [float("nan")] * n
    nb_bot = [float("nan")] * n
    nr_top = [float("nan")] * n
    nr_bot = [float("nan")] * n
    in_bull = [False] * n
    in_bear = [False] * n

    closes = df["close"].to_numpy()

    for i in range(n):
        # Only consider FVGs that have been created before bar i (no lookahead)
        active_bulls = [
            f for f in fvgs
            if f.fvg_type == "bullish"
            and f.bar_index < i
            and not f.is_invalidated
        ]
        active_bears = [
            f for f in fvgs
            if f.fvg_type == "bearish"
            and f.bar_index < i
            and not f.is_invalidated
        ]

        if active_bulls:
            nearest_bull = min(active_bulls, key=lambda f: abs(closes[i] - f.midpoint))
            nb_top[i] = nearest_bull.top
            nb_bot[i] = nearest_bull.bottom
            in_bull[i] = nearest_bull.bottom <= closes[i] <= nearest_bull.top

        if active_bears:
            nearest_bear = min(active_bears, key=lambda f: abs(closes[i] - f.midpoint))
            nr_top[i] = nearest_bear.top
            nr_bot[i] = nearest_bear.bottom
            in_bear[i] = nearest_bear.bottom <= closes[i] <= nearest_bear.top

    df["nearest_bull_fvg_top"] = nb_top
    df["nearest_bull_fvg_bottom"] = nb_bot
    df["nearest_bear_fvg_top"] = nr_top
    df["nearest_bear_fvg_bottom"] = nr_bot
    df["in_bull_fvg"] = in_bull
    df["in_bear_fvg"] = in_bear

    return df
