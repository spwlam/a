"""
strategy/ict_structure.py — ICT Market Structure: BOS, MSS/CHoCH, Displacement

Responsibilities:
- Identify swing highs and swing lows using a configurable lookback
- Detect Break of Structure (BOS): continuation signal in the direction of trend
- Detect Market Structure Shift / Change of Character (CHoCH): reversal signal
- Detect displacement candles: large, impulsive moves that create FVGs

Definitions used in this module:
    Swing High : A bar whose high is the highest within `swing_lookback` bars on each side
    Swing Low  : A bar whose low is the lowest within `swing_lookback` bars on each side

    BOS (Break of Structure):
        Bullish BOS : Close breaks above the most recent significant swing high
        Bearish BOS : Close breaks below the most recent significant swing low
        Interpretation: Trend continuation — institutional order flow is in this direction

    CHoCH (Change of Character) / MSS (Market Structure Shift):
        After a bearish trend, a close above a prior swing high = bullish CHoCH
        After a bullish trend, a close below a prior swing low = bearish CHoCH
        Interpretation: Potential reversal — watch for entry on pullback to FVG/OB

    Displacement:
        A single bar move >= `displacement_atr_mult` × ATR(14)
        Combined with a BOS or CHoCH, this confirms institutional involvement

Approximation notes:
- True ICT swing identification considers the context of the move (not just price levels).
  This implementation uses a symmetric pivot detection which is an approximation.
- BOS vs CHoCH distinction requires knowing the prior trend direction, which is
  determined by the sequence of prior swing highs and lows. We track this with a
  simple state machine.
- Displacement ATR multiplier is configurable. Default 1.5× is conservative;
  reduce to 1.0× for less liquid instruments.
"""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np
import pandas as pd

StructureEvent = Literal["bos_up", "bos_down", "choch_up", "choch_down", None]


def find_swing_highs_lows(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """
    Identify pivot swing highs and swing lows.

    A swing high at bar[i]: df['high'][i] == max(df['high'][i-lookback : i+lookback+1])
    A swing low  at bar[i]: df['low'][i]  == min(df['low'][i-lookback : i+lookback+1])

    NOTE: This requires `lookback` future bars to confirm — the result is shifted
    by `lookback` bars to maintain no-lookahead when used in a rolling context.
    For live trading, use the delayed version in the signal engine.

    Adds columns:
        'swing_high' : float — swing high price (NaN if bar is not a swing high)
        'swing_low'  : float — swing low price (NaN if bar is not a swing low)

    Parameters
    ----------
    df       : DataFrame with 'high' and 'low' columns
    lookback : Bars on each side required to confirm a pivot
    """
    required = {"high", "low"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    df = df.copy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    n = len(df)

    swing_high = np.full(n, np.nan)
    swing_low = np.full(n, np.nan)

    for i in range(lookback, n - lookback):
        window_h = highs[i - lookback: i + lookback + 1]
        window_l = lows[i - lookback: i + lookback + 1]

        if highs[i] == window_h.max():
            swing_high[i] = highs[i]

        if lows[i] == window_l.min():
            swing_low[i] = lows[i]

    df["swing_high"] = swing_high
    df["swing_low"] = swing_low
    return df


def annotate_structure(
    df: pd.DataFrame,
    displacement_atr_mult: float = 1.5,
    bos_confirmation: str = "close",
) -> pd.DataFrame:
    """
    Annotate a DataFrame with BOS, CHoCH, and displacement events.

    Requires 'swing_high', 'swing_low' columns (from find_swing_highs_lows()).
    Adds columns:
        'bos'           : "up" | "down" | None
        'choch'         : "up" | "down" | None
        'displacement'  : bool — True if bar is a displacement candle
        'bos_price'     : float — price level where BOS occurred
        'choch_price'   : float — price level where CHoCH occurred
        'atr14'         : float — 14-period ATR used for displacement threshold

    Parameters
    ----------
    df                    : DataFrame with swing_high, swing_low columns
    displacement_atr_mult : Multiplier for ATR to qualify as displacement
    bos_confirmation      : "close" (conservative) | "wick" (aggressive)
    """
    required = {"swing_high", "swing_low", "high", "low", "close", "open"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"DataFrame missing required columns: {missing}. "
            "Run find_swing_highs_lows() first."
        )

    df = df.copy()
    n = len(df)

    # Compute ATR(14) for displacement detection
    df["atr14"] = _compute_atr(df, period=14)

    bos_col = [None] * n
    choch_col = [None] * n
    displacement_col = [False] * n
    bos_price_col = [float("nan")] * n
    choch_price_col = [float("nan")] * n

    # State tracking
    last_swing_high: Optional[float] = None
    last_swing_low: Optional[float] = None
    trend: Literal["up", "down", "unknown"] = "unknown"

    closes = df["close"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    swing_highs = df["swing_high"].to_numpy()
    swing_lows = df["swing_low"].to_numpy()
    atrs = df["atr14"].to_numpy()

    conf_price = closes if bos_confirmation == "close" else highs  # long BOS uses high on wick mode

    for i in range(1, n):
        # Update swing reference levels
        if not np.isnan(swing_highs[i - 1]):
            last_swing_high = swing_highs[i - 1]
        if not np.isnan(swing_lows[i - 1]):
            last_swing_low = swing_lows[i - 1]

        # Displacement check
        bar_range = highs[i] - lows[i]
        if not np.isnan(atrs[i]) and atrs[i] > 0:
            if bar_range >= displacement_atr_mult * atrs[i]:
                displacement_col[i] = True

        if last_swing_high is None or last_swing_low is None:
            continue

        broke_high = closes[i] > last_swing_high
        broke_low = closes[i] < last_swing_low

        if broke_high:
            if trend == "up":
                # Continuation BOS
                bos_col[i] = "up"
                bos_price_col[i] = last_swing_high
            elif trend in ("down", "unknown"):
                # Reversal — Change of Character
                choch_col[i] = "up"
                choch_price_col[i] = last_swing_high
            trend = "up"

        elif broke_low:
            if trend == "down":
                # Continuation BOS
                bos_col[i] = "down"
                bos_price_col[i] = last_swing_low
            elif trend in ("up", "unknown"):
                # Reversal — Change of Character
                choch_col[i] = "down"
                choch_price_col[i] = last_swing_low
            trend = "down"

    df["bos"] = bos_col
    df["choch"] = choch_col
    df["displacement"] = displacement_col
    df["bos_price"] = bos_price_col
    df["choch_price"] = choch_price_col

    return df


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range using Wilder's smoothing method."""
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return atr
