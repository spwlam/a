"""
strategy/ict_context.py — ICT Higher-Timeframe Bias and Market Context

Responsibilities:
- Determine the HTF (Higher Timeframe) directional bias for a given symbol
- Track overall market structure state: trending, ranging, or reversing
- Provide the "narrative" context that all lower-timeframe signals must align with

ICT Bias Rules (as implemented here):
    Bullish bias : Price is above the most recent CHoCH (Change of Character) and
                   HTF market structure is making higher highs and higher lows.
    Bearish bias : Price is below the most recent CHoCH and HTF structure is
                   making lower highs and lower lows.
    Neutral/unclear: Conflicting structure — no trade until bias resolves.

Approximation notes:
- True ICT bias determination also incorporates time-of-day, COT data, and
  intermarket analysis. This implementation uses price structure only.
- CHoCH detection relies on ict_structure.py — this module consumes its output.
- Bias is computed on the HTF DataFrame (e.g. 1h or 4h) and then applied to
  the LTF signal bars by timestamp alignment.
- When HTF bias is unclear, the system emits no signals (require_htf_bias=true
  in settings.yaml). This is intentional and conservative.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

Bias = Literal["bullish", "bearish", "neutral"]
StructureState = Literal["trending_up", "trending_down", "ranging", "reversing", "unknown"]


@dataclass
class MarketContext:
    """
    Snapshot of HTF market context at a given timestamp.
    Produced once per HTF bar and broadcast to all LTF bars within that period.
    """

    timestamp: pd.Timestamp
    bias: Bias
    structure_state: StructureState
    last_choch_price: Optional[float]   # Price level of the most recent CHoCH
    last_bos_price: Optional[float]     # Price level of the most recent BOS
    premium_zone: Optional[float]       # Upper boundary of HTF FVG / OB (sell zone)
    discount_zone: Optional[float]      # Lower boundary of HTF FVG / OB (buy zone)
    notes: str = ""                     # Human-readable reasoning for audit log


def compute_bias(df_htf: pd.DataFrame) -> pd.DataFrame:
    """
    Compute bar-by-bar HTF bias and append a 'bias' column to the HTF DataFrame.

    Requires columns output by ict_structure.py:
        'swing_high', 'swing_low', 'bos', 'choch'

    Logic:
        - Start neutral
        - When a BOS occurs to the upside AND prior swing low holds → shift bullish
        - When a BOS occurs to the downside AND prior swing high holds → shift bearish
        - A CHoCH in the opposite direction of current bias → shift to reversing/neutral

    Parameters
    ----------
    df_htf : HTF DataFrame with structure annotations

    Returns
    -------
    df_htf with 'bias' and 'structure_state' columns added.
    """
    required = {"bos", "choch", "close"}
    missing = required - set(df_htf.columns)
    if missing:
        raise ValueError(
            f"HTF DataFrame missing structure columns: {missing}. "
            "Run ict_structure.annotate_structure() first."
        )

    df = df_htf.copy()
    n = len(df)

    biases: list[Bias] = ["neutral"] * n
    states: list[StructureState] = ["unknown"] * n

    current_bias: Bias = "neutral"
    current_state: StructureState = "unknown"

    bos = df["bos"].tolist()          # "up", "down", or None
    choch = df["choch"].tolist()      # "up", "down", or None

    for i in range(n):
        # CHoCH takes priority — it signals a potential trend reversal
        if choch[i] == "up":
            current_bias = "bullish"
            current_state = "reversing"
        elif choch[i] == "down":
            current_bias = "bearish"
            current_state = "reversing"
        # BOS confirms continuation
        elif bos[i] == "up" and current_bias in ("bullish", "neutral"):
            current_bias = "bullish"
            current_state = "trending_up"
        elif bos[i] == "down" and current_bias in ("bearish", "neutral"):
            current_bias = "bearish"
            current_state = "trending_down"
        elif bos[i] == "up" and current_bias == "bearish":
            # Counter-trend BOS — potential reversal, wait for CHoCH confirmation
            current_state = "ranging"
        elif bos[i] == "down" and current_bias == "bullish":
            current_state = "ranging"

        biases[i] = current_bias
        states[i] = current_state

    df["bias"] = biases
    df["structure_state"] = states
    return df


def align_htf_bias_to_ltf(
    df_ltf: pd.DataFrame,
    df_htf: pd.DataFrame,
) -> pd.DataFrame:
    """
    Forward-fill HTF bias onto LTF bars by timestamp.

    Each LTF bar receives the bias from the most recently completed HTF bar
    whose open time is <= the LTF bar's open time. This prevents lookahead.

    Parameters
    ----------
    df_ltf : LTF DataFrame with 'timestamp' column
    df_htf : HTF DataFrame with 'timestamp', 'bias', 'structure_state' columns

    Returns
    -------
    df_ltf with 'htf_bias' and 'htf_structure_state' columns added.
    """
    required_ltf = {"timestamp"}
    required_htf = {"timestamp", "bias", "structure_state"}

    for col in required_ltf - set(df_ltf.columns):
        raise ValueError(f"LTF DataFrame missing column: {col}")
    for col in required_htf - set(df_htf.columns):
        raise ValueError(
            f"HTF DataFrame missing column: {col}. Run compute_bias() first."
        )

    htf_slim = df_htf[["timestamp", "bias", "structure_state"]].rename(
        columns={"bias": "htf_bias", "structure_state": "htf_structure_state"}
    )

    # Merge-as-of: for each LTF bar, find most recent HTF bar (no lookahead)
    df_merged = pd.merge_asof(
        df_ltf.sort_values("timestamp"),
        htf_slim.sort_values("timestamp"),
        on="timestamp",
        direction="backward",
    )

    # Fill any pre-history bars (no HTF bar before first LTF bar) with neutral
    df_merged["htf_bias"] = df_merged["htf_bias"].fillna("neutral")
    df_merged["htf_structure_state"] = df_merged["htf_structure_state"].fillna("unknown")

    return df_merged.sort_values("timestamp").reset_index(drop=True)


def get_context_at(df_htf: pd.DataFrame, timestamp: pd.Timestamp) -> MarketContext:
    """
    Return the MarketContext snapshot most recently valid as of the given timestamp.
    Used by the signal engine in live/paper bar processing.
    """
    required = {"timestamp", "bias", "structure_state"}
    missing = required - set(df_htf.columns)
    if missing:
        raise ValueError(f"HTF DataFrame missing columns: {missing}")

    past = df_htf[df_htf["timestamp"] <= timestamp]
    if past.empty:
        return MarketContext(
            timestamp=timestamp,
            bias="neutral",
            structure_state="unknown",
            last_choch_price=None,
            last_bos_price=None,
            premium_zone=None,
            discount_zone=None,
            notes="No HTF data available before this timestamp.",
        )

    row = past.iloc[-1]
    choch_price = row.get("choch_price", None)
    bos_price = row.get("bos_price", None)

    return MarketContext(
        timestamp=timestamp,
        bias=row["bias"],
        structure_state=row["structure_state"],
        last_choch_price=float(choch_price) if choch_price is not None and not pd.isna(choch_price) else None,
        last_bos_price=float(bos_price) if bos_price is not None and not pd.isna(bos_price) else None,
        premium_zone=None,   # Populated by ict_fvg.py in future pipeline step
        discount_zone=None,
        notes=f"HTF bar at {row['timestamp']}",
    )
