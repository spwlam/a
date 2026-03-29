"""
strategy/ict_levels.py — ICT Key Price Levels: PDH/PDL, PWH/PWL, Liquidity Pools

Responsibilities:
- Compute Previous Day High/Low (PDH/PDL) — reset daily at midnight UTC
- Compute Previous Week High/Low (PWH/PWL) — reset weekly on Monday open
- Compute Previous Month High/Low (PMH/PML) — optional, lower priority
- Identify equal highs/equal lows as liquidity pool targets
- Flag when price is "at" or "sweeping" a key level

Why these levels matter (ICT):
    PDH/PDL, PWH/PWL are areas where stop orders cluster (sell stops below lows,
    buy stops above highs). ICT refers to these as "buy-side liquidity" (above highs)
    and "sell-side liquidity" (below lows). The smart money will sweep these levels
    to fill large orders before reversing.

    Equal highs/lows (within proximity_pct) signal a double-top/bottom liquidity pool —
    a magnet for price before it reverses.

Usage in signals:
    - A sweep of PDL followed by a bullish FVG and bullish CHoCH = strong long setup
    - A sweep of PDH followed by a bearish FVG and bearish CHoCH = strong short setup

Approximation notes:
- "Previous" day/week refers to the session that has fully closed, not the current one.
  We use UTC midnight for daily resets. Adjust to exchange session close if needed.
- Equal highs/lows comparison uses proximity_pct as a tolerance band, not exact equality.
  Default 0.1% is tight — increase for less precise instruments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd

LevelType = Literal["PDH", "PDL", "PWH", "PWL", "PMH", "PML", "EQH", "EQL"]


@dataclass
class PriceLevel:
    """A named key price level and its current status."""

    level_type: LevelType
    price: float
    created_at: pd.Timestamp       # When this level became active
    is_swept: bool = False         # True if price has taken out this level
    swept_at: Optional[pd.Timestamp] = None


def compute_daily_levels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add PDH and PDL columns to every bar — the high and low of the prior completed day.

    Each bar's PDH/PDL is the high/low of the most recently completed UTC day
    (i.e., the day whose midnight has already passed relative to bar's timestamp).

    Parameters
    ----------
    df : DataFrame with 'timestamp', 'high', 'low' columns

    Returns
    -------
    df with 'pdh' and 'pdl' columns added (NaN for first day's bars).
    """
    required = {"timestamp", "high", "low"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    df = df.copy()
    df["_date"] = df["timestamp"].dt.normalize()  # UTC midnight truncation

    # Compute each calendar day's high and low
    daily = df.groupby("_date").agg(day_high=("high", "max"), day_low=("low", "min")).reset_index()
    daily["_prev_date"] = daily["_date"] + pd.Timedelta(days=1)  # Shift forward to apply to next day

    # Merge previous day's levels onto each bar
    df = df.merge(
        daily[["_prev_date", "day_high", "day_low"]].rename(columns={"_prev_date": "_date"}),
        on="_date",
        how="left",
    )
    df.rename(columns={"day_high": "pdh", "day_low": "pdl"}, inplace=True)
    df.drop(columns=["_date"], inplace=True)

    return df


def compute_weekly_levels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add PWH and PWL columns — the high and low of the prior completed ISO week.

    Week resets at Monday 00:00 UTC.

    Parameters
    ----------
    df : DataFrame with 'timestamp', 'high', 'low' columns

    Returns
    -------
    df with 'pwh' and 'pwl' columns added (NaN for first week's bars).
    """
    required = {"timestamp", "high", "low"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    df = df.copy()
    df["_week"] = df["timestamp"].dt.to_period("W").apply(lambda p: p.start_time)

    weekly = df.groupby("_week").agg(week_high=("high", "max"), week_low=("low", "min")).reset_index()
    weekly["_next_week"] = weekly["_week"] + pd.Timedelta(weeks=1)

    df = df.merge(
        weekly[["_next_week", "week_high", "week_low"]].rename(columns={"_next_week": "_week"}),
        on="_week",
        how="left",
    )
    df.rename(columns={"week_high": "pwh", "week_low": "pwl"}, inplace=True)
    df.drop(columns=["_week"], inplace=True)

    return df


def detect_equal_highs_lows(
    df: pd.DataFrame,
    lookback: int = 20,
    proximity_pct: float = 0.1,
) -> pd.DataFrame:
    """
    Detect equal highs (EQH) and equal lows (EQL) within a rolling lookback window.

    Two swing highs are "equal" if they are within proximity_pct% of each other.
    These represent double-top/bottom liquidity pools.

    Requires 'swing_high' and 'swing_low' columns from ict_structure.py.

    Adds columns:
        'eqh' : float — price of equal high cluster (NaN if none)
        'eql' : float — price of equal low cluster (NaN if none)

    Parameters
    ----------
    df           : DataFrame with swing_high, swing_low columns
    lookback     : Number of bars to look back for equal level comparison
    proximity_pct: Tolerance as % of price for "equal" determination
    """
    required = {"swing_high", "swing_low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"DataFrame missing required columns: {missing}. "
            "Run ict_structure.find_swing_highs_lows() first."
        )

    df = df.copy()
    n = len(df)
    eqh = np.full(n, np.nan)
    eql = np.full(n, np.nan)

    swing_highs = df["swing_high"].to_numpy()
    swing_lows = df["swing_low"].to_numpy()
    closes = df["close"].to_numpy()

    for i in range(lookback, n):
        current_sh = swing_highs[i]
        current_sl = swing_lows[i]

        if not np.isnan(current_sh):
            # Find prior swing highs in lookback window
            prior_sh = swing_highs[i - lookback: i]
            prior_sh_valid = prior_sh[~np.isnan(prior_sh)]
            tolerance = closes[i] * (proximity_pct / 100.0)
            if len(prior_sh_valid) > 0 and np.any(np.abs(prior_sh_valid - current_sh) <= tolerance):
                eqh[i] = current_sh

        if not np.isnan(current_sl):
            prior_sl = swing_lows[i - lookback: i]
            prior_sl_valid = prior_sl[~np.isnan(prior_sl)]
            tolerance = closes[i] * (proximity_pct / 100.0)
            if len(prior_sl_valid) > 0 and np.any(np.abs(prior_sl_valid - current_sl) <= tolerance):
                eql[i] = current_sl

    df["eqh"] = eqh
    df["eql"] = eql
    return df


def flag_level_sweeps(df: pd.DataFrame, proximity_pct: float = 0.1) -> pd.DataFrame:
    """
    Flag bars where price sweeps (wicks through then closes back inside) a key level.

    A sweep of a high level (PDH, PWH, EQH):
        bar.high > level AND bar.close < level  →  'swept_high' = True

    A sweep of a low level (PDL, PWL, EQL):
        bar.low < level AND bar.close > level  →  'swept_low' = True

    Adds columns:
        'swept_high' : bool — a liquidity sweep above a key high level occurred
        'swept_low'  : bool — a liquidity sweep below a key low level occurred

    Parameters
    ----------
    df            : DataFrame with key level columns (pdh, pdl, pwh, pwl, eqh, eql)
    proximity_pct : Not used here — reserved for future fuzzy matching
    """
    df = df.copy()
    high_levels = [c for c in ("pdh", "pwh", "eqh") if c in df.columns]
    low_levels = [c for c in ("pdl", "pwl", "eql") if c in df.columns]

    swept_high = pd.Series(False, index=df.index)
    swept_low = pd.Series(False, index=df.index)

    for col in high_levels:
        level = df[col]
        mask = df["high"] > level
        close_back = df["close"] < level
        swept_high = swept_high | (mask & close_back)

    for col in low_levels:
        level = df[col]
        mask = df["low"] < level
        close_back = df["close"] > level
        swept_low = swept_low | (mask & close_back)

    df["swept_high"] = swept_high
    df["swept_low"] = swept_low
    return df


def annotate_all_levels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convenience function: run all level computations in the correct order.
    Assumes ict_structure swing columns are already present.
    """
    df = compute_daily_levels(df)
    df = compute_weekly_levels(df)

    if "swing_high" in df.columns and "swing_low" in df.columns:
        df = detect_equal_highs_lows(df)

    df = flag_level_sweeps(df)
    return df
