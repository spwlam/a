"""
strategy/strat_classifier.py — The Strat Candle Type Classifier

Classifies each candle relative to the prior candle using The Strat framework
originated by Rob Smith. Classification uses only bar[i] and bar[i-1] — no
lookahead, no future bars.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLASSIFICATION RULES  (strict — applied in priority order)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Type 3  (Outside Bar)     : high > prev.high  AND  low < prev.low
                              Engulfs the prior bar on both sides.
                              Highest-impact candle; often a stop-hunt.

  Type 2U (Directional Up)  : high > prev.high  AND  low >= prev.low
                              Only the high was taken out.
                              Bullish directional — long trigger bar.

  Type 2D (Directional Down): low  < prev.low   AND  high <= prev.high
                              Only the low was taken out.
                              Bearish directional — short trigger bar.

  Type 1  (Inside Bar)      : high <= prev.high  AND  low >= prev.low
                              Fully contained within the prior bar's range.
                              Represents consolidation / compression.
                              NOT an entry trigger by itself.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EDGE CASES  (all combinations of equality, documented explicitly)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  high == prev.high  AND  low >  prev.low  →  2U
    Rationale: The high touched the prior high (a liquidity test) while the
    low stayed inside. The candle "reached" the prior high. Treated as
    directional up — the high side was at minimum tested, not protected.
    Rob Smith's Strat treats this as a "2U" because the prior high was
    not defended (equalled = taken for our purposes here).

  high == prev.high  AND  low == prev.low  →  1
    Rationale: Exact doji clone — identical range. No side was taken out.
    Classify conservatively as inside bar (compression).

  high == prev.high  AND  low <  prev.low  →  2D
    Rationale: The low was taken out (strictly). The high only matched.
    Per the 2D rule: low < prev.low AND high <= prev.high — this qualifies.

  high <  prev.high  AND  low == prev.low  →  1
    Rationale: The high stayed inside; the low merely touched (did not
    exceed) the prior low. Nothing was "taken out." Inside bar.
    Symmetric counterpart to the eq_high/inside_low edge case: since we
    classify eq_high+inside_low as 2U (touching the high = tested),
    one might expect eq_low+inside_high to be 2D. We do NOT do this —
    the user's rule only specifies the high-equality case. We keep this
    as Type 1 to remain conservative on the low side.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPLETE 9-CASE TRUTH TABLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  high vs prev  │  low vs prev  │  Type
  ──────────────┼───────────────┼───────
  >             │  <            │  3
  >             │  ==           │  2U
  >             │  >            │  2U
  ==            │  <            │  2D
  ==            │  ==           │  1      ← equal-both edge case
  ==            │  >            │  2U     ← equal-high edge case
  <             │  <            │  2D
  <             │  ==           │  1      ← equal-low edge case (conservative)
  <             │  >            │  1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT COLUMNS (added by classify_candles)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  strat_type        : str   — "1" | "2u" | "2d" | "3" (NaN for bar 0)
  strat_direction   : str   — "bullish" | "bearish" | "neutral"
                               Based on close vs open of the candle itself.
                               Independent of strat_type.
  strat_is_actionable: bool — True if the candle can trigger an entry.
                               True  for types 2u, 2d, 3
                               False for type 1 (wait for breakout of range)
                               False for bar 0 (no classification)
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from loguru import logger

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

StratType = Literal["1", "2u", "2d", "3"]
StratDirection = Literal["bullish", "bearish", "neutral"]

# String constants — used throughout to avoid typo-prone bare strings
T1 = "1"
T2U = "2u"
T2D = "2d"
T3 = "3"

ACTIONABLE_TYPES: frozenset[str] = frozenset({T2U, T2D, T3})
REQUIRED_COLUMNS: frozenset[str] = frozenset({"open", "high", "low", "close"})


# ---------------------------------------------------------------------------
# Single-bar classifier (pure function — primary unit-testable surface)
# ---------------------------------------------------------------------------

def classify_single_candle(
    high: float,
    low: float,
    prev_high: float,
    prev_low: float,
) -> StratType:
    """
    Classify one candle relative to the immediately preceding candle.

    This is a pure function with no side effects. It encodes the complete
    9-case truth table described in the module docstring.

    Parameters
    ----------
    high      : Current bar's high price.
    low       : Current bar's low price.
    prev_high : Prior bar's high price.
    prev_low  : Prior bar's low price.

    Returns
    -------
    One of "1", "2u", "2d", "3".

    Raises
    ------
    ValueError
        If high < low (invalid OHLC bar) or if any argument is NaN.
    """
    # Guard: NaN inputs cannot be classified
    if any(np.isnan(v) for v in (high, low, prev_high, prev_low)):
        raise ValueError(
            f"Cannot classify candle with NaN values: "
            f"high={high}, low={low}, prev_high={prev_high}, prev_low={prev_low}"
        )

    # Guard: malformed bar
    if high < low:
        raise ValueError(
            f"Invalid bar: high ({high}) < low ({low}). "
            "Check data integrity before classifying."
        )

    # ------------------------------------------------------------------
    # Compute the three directional flags once
    # ------------------------------------------------------------------
    took_high: bool = high > prev_high   # Current high exceeded prior high
    eq_high: bool = high == prev_high    # Current high exactly matched prior high

    took_low: bool = low < prev_low      # Current low undercut prior low
    eq_low: bool = low == prev_low       # Current low exactly matched prior low

    # ------------------------------------------------------------------
    # Type 3 — Outside Bar
    # Both sides taken out. Check this FIRST — it would satisfy 2U and 2D
    # conditions individually, so priority ordering prevents misclassification.
    # ------------------------------------------------------------------
    if took_high and took_low:
        return T3

    # ------------------------------------------------------------------
    # Type 2U — Directional Up
    # High exceeded prev.high while low did NOT undercut prev.low.
    # Includes three sub-cases from the truth table:
    #   (high > prev, low == prev)  → standard 2U
    #   (high > prev, low > prev)   → standard 2U
    #   (high == prev, low > prev)  → edge case: doji touching prior high,
    #                                  low stayed inside → treat as 2U
    # ------------------------------------------------------------------
    if took_high:
        # low is >= prev_low (since took_low is False and we already handled T3)
        return T2U

    if eq_high and (not took_low) and (not eq_low):
        # high == prev.high AND low > prev.low
        # The high "tested" the prior high level (touched it) while the low
        # stayed strictly inside. Classify as 2U per the documented edge case.
        return T2U

    # ------------------------------------------------------------------
    # Type 2D — Directional Down
    # Low undercut prev.low while high did NOT exceed prev.high.
    # Includes three sub-cases from the truth table:
    #   (high < prev, low < prev)   → standard 2D
    #   (high == prev, low < prev)  → edge case: high matched, low taken →
    #                                  satisfies (high <= prev AND low < prev) → 2D
    # (high > prev, low < prev) was already handled as T3 above.
    # ------------------------------------------------------------------
    if took_low:
        # high is <= prev_high (since took_high is False and T3 already handled)
        return T2D

    # ------------------------------------------------------------------
    # Type 1 — Inside Bar (all remaining cases)
    # At this point we know:
    #   took_high = False  (high <= prev.high)
    #   took_low  = False  (low  >= prev.low)
    # The only sub-cases that fall here:
    #   (high < prev, low > prev)   → strict inside bar
    #   (high < prev, low == prev)  → inside on top, touching on bottom → 1
    #   (high == prev, low == prev) → exact clone, equal-both edge case → 1
    # ------------------------------------------------------------------
    return T1


# ---------------------------------------------------------------------------
# Direction classifier (pure function)
# ---------------------------------------------------------------------------

def classify_direction(open_: float, close: float) -> StratDirection:
    """
    Determine the candle's directional bias from its open and close.

    Parameters
    ----------
    open_  : Candle open price.
    close  : Candle close price.

    Returns
    -------
    "bullish"  if close > open (green candle)
    "bearish"  if close < open (red candle)
    "neutral"  if close == open (doji)
    """
    if close > open_:
        return "bullish"
    if close < open_:
        return "bearish"
    return "neutral"  # close == open: doji / spinning top


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def classify_candles(df: pd.DataFrame) -> pd.DataFrame:
    """
    Classify every bar in a DataFrame using The Strat rules and annotate
    three new columns:

        strat_type         : "1" | "2u" | "2d" | "3" | NaN (bar 0)
        strat_direction    : "bullish" | "bearish" | "neutral"
        strat_is_actionable: True | False

    The first bar (index 0) cannot be classified because it has no prior
    candle. Its strat_type is set to NaN and strat_is_actionable to False.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: open, high, low, close.
        Must be sorted in ascending chronological order.
        Must not be empty.

    Returns
    -------
    pd.DataFrame
        A copy of the input with the three new columns appended.
        The original DataFrame is never modified.

    Raises
    ------
    ValueError
        If required columns are missing or the DataFrame is empty.
    """
    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------
    if df.empty:
        raise ValueError("classify_candles received an empty DataFrame.")

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(
            f"classify_candles: DataFrame is missing required columns: "
            f"{sorted(missing)}. Present columns: {sorted(df.columns)}"
        )

    logger.debug(
        "classify_candles: classifying {} bars", len(df)
    )

    df = df.copy()

    # ------------------------------------------------------------------
    # Vectorised direction column (no prior bar needed)
    # ------------------------------------------------------------------
    conditions_dir = [
        df["close"] > df["open"],
        df["close"] < df["open"],
    ]
    choices_dir = ["bullish", "bearish"]
    df["strat_direction"] = np.select(
        conditions_dir, choices_dir, default="neutral"
    ).astype(str)

    # ------------------------------------------------------------------
    # strat_type — classified bar-by-bar using shifted arrays
    # ------------------------------------------------------------------
    highs: np.ndarray = df["high"].to_numpy(dtype=np.float64)
    lows: np.ndarray = df["low"].to_numpy(dtype=np.float64)

    # Shift by 1: prev_highs[i] == highs[i-1]; index 0 is NaN (no prior bar)
    prev_highs = np.empty(len(highs), dtype=np.float64)
    prev_lows = np.empty(len(lows), dtype=np.float64)
    prev_highs[0] = np.nan
    prev_lows[0] = np.nan
    prev_highs[1:] = highs[:-1]
    prev_lows[1:] = lows[:-1]

    # Build strat_type array — object dtype to hold strings and NaN
    strat_types: list[str | float] = [np.nan]  # bar 0 has no prior candle

    for i in range(1, len(df)):
        try:
            strat_types.append(
                classify_single_candle(
                    high=highs[i],
                    low=lows[i],
                    prev_high=prev_highs[i],
                    prev_low=prev_lows[i],
                )
            )
        except ValueError as exc:
            # Log the offending bar but keep processing; mark it NaN
            logger.warning(
                "classify_candles: skipping bar {} due to invalid data — {}",
                i, exc,
            )
            strat_types.append(np.nan)

    df["strat_type"] = strat_types  # dtype is object (mixed str/NaN)

    # ------------------------------------------------------------------
    # strat_is_actionable
    # ------------------------------------------------------------------
    df["strat_is_actionable"] = df["strat_type"].isin(ACTIONABLE_TYPES)

    # ------------------------------------------------------------------
    # Summary log
    # ------------------------------------------------------------------
    type_counts: dict[str, int] = (
        df["strat_type"].dropna().value_counts().to_dict()
    )
    logger.debug(
        "classify_candles complete: {} bars | distribution: {}",
        len(df),
        type_counts,
    )

    return df
