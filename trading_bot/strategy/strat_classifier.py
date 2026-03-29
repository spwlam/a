"""
strategy/strat_classifier.py — The Strat Candle Type Classifier

Responsibilities:
- Classify each OHLCV bar as one of four Strat candle types:
    Type 1  : Inside bar  — high <= prior high AND low >= prior low
    Type 2u : Outside-up  — high > prior high AND low >= prior low (bullish engulf of high)
    Type 2d : Outside-down— low < prior low  AND high <= prior high (bearish engulf of low)
    Type 3  : Outside bar — high > prior high AND low < prior low (full engulf, both sides)

- Operate bar-by-bar with no lookahead: classification of bar[i] uses only bar[i-1]
- Annotate an existing DataFrame with a 'strat_type' column

Approximation notes:
- Exact equality (high == prior high) is treated as Type 1 (inside) by default.
  This is consistent with the conservative interpretation used by most Strat traders.
  A tolerance parameter is available but defaults to 0.0.
- Type 2u and 2d are directional — they indicate which side was taken out.
- A true "outside bar" (Type 3) is both a liquidity sweep AND a potential reversal signal.
  ICT context is required before trading a 3 — it can also be a continuation trap.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

StratType = Literal["1", "2u", "2d", "3", "unknown"]

INSIDE = "1"
OUTSIDE_UP = "2u"
OUTSIDE_DOWN = "2d"
OUTSIDE_BAR = "3"
UNKNOWN = "unknown"  # First bar — no prior bar to compare


def classify_bar(
    high: float,
    low: float,
    prior_high: float,
    prior_low: float,
    tolerance: float = 0.0,
) -> StratType:
    """
    Classify a single bar relative to the prior bar.

    Parameters
    ----------
    high, low         : Current bar's high and low
    prior_high/low    : Previous bar's high and low
    tolerance         : Allowable overlap in price units before a bar is no longer
                        considered inside (default 0.0 = strict)

    Returns
    -------
    One of: "1", "2u", "2d", "3", "unknown"
    """
    took_high = high > prior_high + tolerance
    took_low = low < prior_low - tolerance

    if took_high and took_low:
        return OUTSIDE_BAR       # Type 3: engulfs both sides
    elif took_high:
        return OUTSIDE_UP        # Type 2u: only high was taken
    elif took_low:
        return OUTSIDE_DOWN      # Type 2d: only low was taken
    else:
        return INSIDE            # Type 1: inside bar


def classify_dataframe(df: pd.DataFrame, tolerance: float = 0.0) -> pd.DataFrame:
    """
    Classify all bars in a DataFrame and append a 'strat_type' column.

    Input DataFrame must contain 'high' and 'low' columns.
    The first bar is always labeled 'unknown' (no prior bar).

    Parameters
    ----------
    df        : DataFrame with at least 'high' and 'low' columns, sorted ascending
    tolerance : See classify_bar()

    Returns
    -------
    DataFrame with 'strat_type' column added (does not modify in place).
    """
    required = {"high", "low"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    df = df.copy()
    n = len(df)

    strat_types: list[StratType] = [UNKNOWN]  # First bar has no prior context

    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()

    for i in range(1, n):
        strat_types.append(
            classify_bar(
                high=highs[i],
                low=lows[i],
                prior_high=highs[i - 1],
                prior_low=lows[i - 1],
                tolerance=tolerance,
            )
        )

    df["strat_type"] = strat_types
    return df


def get_type_counts(df: pd.DataFrame) -> dict[str, int]:
    """
    Return a summary count of each Strat type in a classified DataFrame.
    Useful for quick distribution checks during research.
    """
    if "strat_type" not in df.columns:
        raise ValueError("DataFrame has not been classified yet. Run classify_dataframe() first.")
    return df["strat_type"].value_counts().to_dict()
