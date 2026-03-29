"""
strategy/filters.py — Session, Volatility, and Spread Filters

Responsibilities:
- Session filter: flag bars that fall within configured kill zones (NYC open, London, etc.)
- Volatility filter: suppress signals when ATR is too low (choppy) or too high (news spike)
- Spread filter: suppress signals when bid-ask spread exceeds acceptable threshold
  (relevant for live trading; approximated in paper trading using recent ATR)

Why session filtering matters:
    ICT kill zones are time windows where institutional order flow is most active.
    Trading outside these windows significantly degrades signal quality and increases
    the likelihood of false breakouts and stop hunts.

Kill zones used (configurable in settings.yaml):
    London open     : 02:00 – 05:00 UTC
    New York open   : 09:30 – 11:00 UTC  ← Primary kill zone for NQ/ES
    London close    : 15:00 – 16:00 UTC

Approximation notes:
- All session times are in UTC. Convert to Eastern Time: UTC-5 (EST) or UTC-4 (EDT).
- Session boundaries are approximate — ICT identifies these by price behavior,
  not rigid clock times. These window defaults capture the core of each session.
- Volatility thresholds (ATR multiples) are calibrated for NQ futures at 15m timeframe.
  Adjust for other instruments using the config multipliers.
"""

from __future__ import annotations

from datetime import time
from typing import Optional

import pandas as pd

# Default kill zone windows (UTC, inclusive)
DEFAULT_KILL_ZONES: dict[str, tuple[time, time]] = {
    "london":          (time(2, 0),  time(5, 0)),
    "new_york_open":   (time(9, 30), time(11, 0)),
    "london_close":    (time(15, 0), time(16, 0)),
}


def annotate_sessions(
    df: pd.DataFrame,
    kill_zones: Optional[dict[str, tuple[time, time]]] = None,
    enabled_zones: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Add 'in_session' and 'session_name' columns to each bar.

    Parameters
    ----------
    df            : DataFrame with 'timestamp' column (UTC)
    kill_zones    : Dict of {name: (start_time, end_time)} in UTC
                    Defaults to DEFAULT_KILL_ZONES if None
    enabled_zones : List of zone names that are active; defaults to all

    Returns
    -------
    df with 'in_session' (bool) and 'session_name' (str | None) columns.
    """
    required = {"timestamp"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"DataFrame missing required columns: {missing}")

    df = df.copy()
    zones = kill_zones or DEFAULT_KILL_ZONES
    active_zones = enabled_zones or list(zones.keys())

    bar_times = df["timestamp"].dt.time
    in_session = pd.Series(False, index=df.index)
    session_name: list[Optional[str]] = [None] * len(df)

    for name in active_zones:
        if name not in zones:
            continue
        start, end = zones[name]
        mask = (bar_times >= start) & (bar_times <= end)
        in_session = in_session | mask
        for i in df.index[mask]:
            session_name[i] = name

    df["in_session"] = in_session
    df["session_name"] = session_name
    return df


def annotate_volatility_filter(
    df: pd.DataFrame,
    atr_col: str = "atr14",
    low_vol_mult: float = 0.3,
    high_vol_mult: float = 3.0,
) -> pd.DataFrame:
    """
    Add 'vol_ok' column — True when ATR is within acceptable range.

    Low volatility (below low_vol_mult × median ATR): choppy, low-quality signals.
    High volatility (above high_vol_mult × median ATR): news spike, unpredictable fills.

    Parameters
    ----------
    df             : DataFrame with ATR column
    atr_col        : Name of the ATR column (default 'atr14')
    low_vol_mult   : ATR must be above this × median ATR
    high_vol_mult  : ATR must be below this × median ATR

    Returns
    -------
    df with 'vol_ok' (bool) and 'vol_regime' (str) columns.
    """
    if atr_col not in df.columns:
        raise ValueError(f"ATR column '{atr_col}' not found. Run ict_structure.annotate_structure() first.")

    df = df.copy()
    median_atr = df[atr_col].median()

    if median_atr == 0 or pd.isna(median_atr):
        df["vol_ok"] = True
        df["vol_regime"] = "unknown"
        return df

    low_thresh = median_atr * low_vol_mult
    high_thresh = median_atr * high_vol_mult

    atr = df[atr_col]
    df["vol_ok"] = (atr >= low_thresh) & (atr <= high_thresh)
    df["vol_regime"] = "normal"
    df.loc[atr < low_thresh, "vol_regime"] = "low"
    df.loc[atr > high_thresh, "vol_regime"] = "spike"
    return df


def annotate_spread_filter(
    df: pd.DataFrame,
    max_spread_atr_fraction: float = 0.15,
    atr_col: str = "atr14",
    spread_col: Optional[str] = None,
) -> pd.DataFrame:
    """
    Add 'spread_ok' column — True when spread is acceptable.

    In paper trading, the actual spread is unknown. We approximate it using
    a fraction of ATR. In live trading, pass actual spread data via spread_col.

    Parameters
    ----------
    df                      : DataFrame with ATR column
    max_spread_atr_fraction : Max acceptable spread as fraction of ATR
    atr_col                 : ATR column name
    spread_col              : Optional column with actual spread values

    Returns
    -------
    df with 'spread_ok' (bool) column.
    """
    df = df.copy()

    if spread_col and spread_col in df.columns:
        # Real spread data available
        max_spread = df[atr_col] * max_spread_atr_fraction
        df["spread_ok"] = df[spread_col] <= max_spread
    else:
        # Paper mode: assume spread is always within limits during session
        df["spread_ok"] = True

    return df


def apply_all_filters(
    df: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    Run all filters in order and add a combined 'filters_ok' column.

    Parameters
    ----------
    df     : DataFrame with required columns from prior pipeline steps
    config : Parsed settings.yaml dict

    Returns
    -------
    df with all filter columns plus 'filters_ok' (True only if all filters pass).
    """
    session_cfg = config.get("sessions", {})
    enabled_zones = [
        name for name, vals in session_cfg.items()
        if isinstance(vals, dict) and vals.get("enabled", False)
    ]

    # Build kill zones from config
    kill_zones: dict[str, tuple[time, time]] = {}
    for name, vals in session_cfg.items():
        if isinstance(vals, dict) and "start" in vals and "end" in vals:
            start_h, start_m = map(int, vals["start"].split(":"))
            end_h, end_m = map(int, vals["end"].split(":"))
            kill_zones[name] = (time(start_h, start_m), time(end_h, end_m))

    df = annotate_sessions(df, kill_zones=kill_zones, enabled_zones=enabled_zones)
    df = annotate_volatility_filter(df)
    df = annotate_spread_filter(df)

    df["filters_ok"] = df["in_session"] & df["vol_ok"] & df["spread_ok"]
    return df
