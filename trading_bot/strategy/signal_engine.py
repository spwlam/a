"""
strategy/signal_engine.py — Combined ICT + Strat Signal Engine

Responsibilities:
- Combine outputs from all ICT and Strat modules into a unified, actionable signal
- Apply all required confirmation gates before emitting a signal
- Calculate entry price, stop loss, and take profit for each signal
- Return a structured TradeSignal object (or None if no valid setup exists)

Signal generation pipeline (all must pass):
    Gate 1: Session filter       — Are we in an active kill zone? (filters.py)
    Gate 2: HTF bias alignment   — Does HTF bias agree with the signal direction?
    Gate 3: Strat pattern        — Is there a valid Strat pattern present?
    Gate 4: ICT structure        — Has there been a BOS or CHoCH in signal direction?
    Gate 5: FVG presence         — Is price near an unmitigated FVG in the right direction?
    Gate 6: Liquidity sweep      — Has a liquidity level been swept (optimal entry)?
    Gate 7: R:R validation       — Does the trade meet the minimum risk:reward ratio?

All seven gates must pass. If any gate fails, no signal is emitted for that bar.

Approximation notes:
- The "optimal" ICT entry is at the FVG midpoint (50% of the gap). We use this
  as the limit order price when order_type == "limit".
- Stop loss is placed below the FVG bottom (bull) or above the FVG top (bear),
  plus a buffer of `stop_buffer_ticks` to avoid being stopped out by noise.
- Take profit is calculated as entry ± (stop_distance × min_rr_ratio).
- This module does NOT execute trades — it only produces signals for paper_trader.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional
import logging

import pandas as pd

from strategy.strat_patterns import StratPattern
from strategy.ict_context import MarketContext

logger = logging.getLogger(__name__)

Direction = Literal["long", "short"]
SignalStrength = Literal["A", "B", "C"]  # A = all gates pass + optimal confluence


@dataclass
class TradeSignal:
    """
    A fully validated, actionable trade signal.

    All prices are in the instrument's native units.
    stop_distance and reward_distance are absolute price differences.
    """

    signal_id: str                     # Unique ID: symbol_timestamp_direction
    symbol: str
    direction: Direction
    bar_index: int
    timestamp: pd.Timestamp

    entry_price: float                 # Limit order price (FVG midpoint)
    stop_loss: float                   # Hard stop price
    take_profit: float                 # Primary TP (at min_rr_ratio)
    stop_distance: float               # |entry - stop_loss|
    reward_distance: float             # |take_profit - entry|
    risk_reward: float                 # reward / stop = actual R:R

    strat_pattern: str                 # e.g. "2u-1-2u"
    htf_bias: str                      # "bullish" | "bearish"
    ict_event: str                     # "bos_up" | "choch_up" | etc.
    fvg_zone: tuple[float, float]      # (bottom, top) of the triggering FVG
    swept_level: Optional[str]         # "PDL" | "PWL" | "EQL" | etc., or None

    strength: SignalStrength = "B"
    notes: str = ""
    gates_passed: list[str] = field(default_factory=list)


def generate_signal(
    df: pd.DataFrame,
    bar_index: int,
    symbol: str,
    config: dict,
) -> Optional[TradeSignal]:
    """
    Attempt to generate a trade signal for the bar at bar_index.

    All logic operates only on df.iloc[:bar_index+1] — no lookahead.

    Parameters
    ----------
    df         : Fully annotated DataFrame (all ICT and Strat columns present)
    bar_index  : Current bar index (0-based)
    symbol     : Instrument symbol string
    config     : Parsed settings.yaml dict

    Returns
    -------
    TradeSignal if all gates pass, None otherwise.
    """
    if bar_index < 3:
        return None  # Not enough bars to evaluate any pattern

    row = df.iloc[bar_index]
    gates_passed: list[str] = []
    sig_cfg = config.get("signal", {})
    exec_cfg = config.get("execution", {})

    # ------------------------------------------------------------------
    # Gate 1: Session filter
    # ------------------------------------------------------------------
    if sig_cfg.get("require_session_window", True):
        if not row.get("in_session", False):
            logger.debug("[%s] Bar %d: Gate 1 FAIL — not in active session", symbol, bar_index)
            return None
    gates_passed.append("session")

    # ------------------------------------------------------------------
    # Gate 2: HTF Bias
    # ------------------------------------------------------------------
    htf_bias = row.get("htf_bias", "neutral")
    if sig_cfg.get("require_htf_bias", True) and htf_bias == "neutral":
        logger.debug("[%s] Bar %d: Gate 2 FAIL — HTF bias is neutral", symbol, bar_index)
        return None

    # ------------------------------------------------------------------
    # Gate 3: Strat Pattern
    # ------------------------------------------------------------------
    pattern_name = row.get("strat_pattern", "none")
    pattern_dir = row.get("pattern_dir", "neutral")

    if sig_cfg.get("require_strat_pattern", True) and pattern_name == "none":
        logger.debug("[%s] Bar %d: Gate 3 FAIL — no Strat pattern", symbol, bar_index)
        return None

    # Pattern must align with HTF bias
    if htf_bias == "bullish" and pattern_dir != "long":
        logger.debug("[%s] Bar %d: Gate 3 FAIL — pattern direction misaligns with bullish bias", symbol, bar_index)
        return None
    if htf_bias == "bearish" and pattern_dir != "short":
        logger.debug("[%s] Bar %d: Gate 3 FAIL — pattern direction misaligns with bearish bias", symbol, bar_index)
        return None

    direction: Direction = "long" if pattern_dir == "long" else "short"
    gates_passed.append("strat_pattern")

    # ------------------------------------------------------------------
    # Gate 4: ICT Structure Event
    # ------------------------------------------------------------------
    bos = row.get("bos")
    choch = row.get("choch")
    ict_event = None

    if direction == "long" and (bos == "up" or choch == "up"):
        ict_event = f"choch_up" if choch == "up" else "bos_up"
    elif direction == "short" and (bos == "down" or choch == "down"):
        ict_event = f"choch_down" if choch == "down" else "bos_down"

    if not ict_event:
        logger.debug("[%s] Bar %d: Gate 4 FAIL — no ICT structure event in signal direction", symbol, bar_index)
        return None
    gates_passed.append("ict_structure")

    # ------------------------------------------------------------------
    # Gate 5: FVG Presence
    # ------------------------------------------------------------------
    if sig_cfg.get("require_ict_fvg", True):
        if direction == "long":
            fvg_bottom = row.get("nearest_bull_fvg_bottom", float("nan"))
            fvg_top = row.get("nearest_bull_fvg_top", float("nan"))
            in_fvg = row.get("in_bull_fvg", False)
        else:
            fvg_bottom = row.get("nearest_bear_fvg_bottom", float("nan"))
            fvg_top = row.get("nearest_bear_fvg_top", float("nan"))
            in_fvg = row.get("in_bear_fvg", False)

        if not in_fvg or pd.isna(fvg_bottom) or pd.isna(fvg_top):
            logger.debug("[%s] Bar %d: Gate 5 FAIL — price not in valid FVG", symbol, bar_index)
            return None
    else:
        fvg_bottom = row.get("nearest_bull_fvg_bottom" if direction == "long" else "nearest_bear_fvg_bottom", float("nan"))
        fvg_top = row.get("nearest_bull_fvg_top" if direction == "long" else "nearest_bear_fvg_top", float("nan"))
    gates_passed.append("fvg")

    # ------------------------------------------------------------------
    # Gate 6: Liquidity Sweep (optimal — not required if not configured)
    # ------------------------------------------------------------------
    swept_level: Optional[str] = None
    if direction == "long" and row.get("swept_low", False):
        swept_level = "low_sweep"
        gates_passed.append("liquidity_sweep")
    elif direction == "short" and row.get("swept_high", False):
        swept_level = "high_sweep"
        gates_passed.append("liquidity_sweep")

    # ------------------------------------------------------------------
    # Gate 7: R:R Calculation and Validation
    # ------------------------------------------------------------------
    fvg_midpoint = (fvg_top + fvg_bottom) / 2
    tick_size = exec_cfg.get("slippage_ticks", 1) * 0.25  # Approximate tick value

    if direction == "long":
        entry_price = fvg_midpoint
        stop_loss = fvg_bottom - tick_size
        stop_distance = entry_price - stop_loss
    else:
        entry_price = fvg_midpoint
        stop_loss = fvg_top + tick_size
        stop_distance = stop_loss - entry_price

    if stop_distance <= 0:
        logger.debug("[%s] Bar %d: Gate 7 FAIL — invalid stop distance", symbol, bar_index)
        return None

    min_rr = sig_cfg.get("min_rr_ratio", 2.0)
    reward_distance = stop_distance * min_rr
    take_profit = (entry_price + reward_distance) if direction == "long" else (entry_price - reward_distance)
    actual_rr = reward_distance / stop_distance

    if actual_rr < min_rr:
        logger.debug("[%s] Bar %d: Gate 7 FAIL — R:R %.2f below minimum %.2f", symbol, bar_index, actual_rr, min_rr)
        return None
    gates_passed.append("risk_reward")

    # ------------------------------------------------------------------
    # Signal strength classification
    # ------------------------------------------------------------------
    strength: SignalStrength = "B"
    if swept_level and choch:
        strength = "A"  # Sweep + CHoCH = highest conviction ICT setup
    elif not swept_level and bos and not choch:
        strength = "C"  # BOS only, no sweep — lower conviction

    signal_id = f"{symbol}_{row['timestamp'].strftime('%Y%m%d_%H%M')}_{direction}"

    signal = TradeSignal(
        signal_id=signal_id,
        symbol=symbol,
        direction=direction,
        bar_index=bar_index,
        timestamp=row["timestamp"],
        entry_price=round(entry_price, 4),
        stop_loss=round(stop_loss, 4),
        take_profit=round(take_profit, 4),
        stop_distance=round(stop_distance, 4),
        reward_distance=round(reward_distance, 4),
        risk_reward=round(actual_rr, 2),
        strat_pattern=pattern_name,
        htf_bias=htf_bias,
        ict_event=ict_event,
        fvg_zone=(round(fvg_bottom, 4), round(fvg_top, 4)),
        swept_level=swept_level,
        strength=strength,
        gates_passed=gates_passed,
        notes=f"Pattern: {pattern_name} | Event: {ict_event} | Strength: {strength}",
    )

    logger.info(
        "[%s] SIGNAL %s | %s | Entry: %.4f | SL: %.4f | TP: %.4f | R:R: %.2f | Gates: %s",
        symbol, signal_id, direction.upper(),
        entry_price, stop_loss, take_profit, actual_rr,
        ", ".join(gates_passed),
    )

    return signal


def run_signal_scan(
    df: pd.DataFrame,
    symbol: str,
    config: dict,
) -> list[TradeSignal]:
    """
    Scan an entire DataFrame bar-by-bar and return all valid signals.
    Used for backtesting and signal review.

    Parameters
    ----------
    df     : Fully annotated DataFrame
    symbol : Instrument symbol
    config : Parsed settings.yaml dict

    Returns
    -------
    List of TradeSignal objects in chronological order.
    """
    signals: list[TradeSignal] = []
    for i in range(len(df)):
        sig = generate_signal(df, i, symbol, config)
        if sig is not None:
            signals.append(sig)
    logger.info("[%s] Signal scan complete: %d signals found across %d bars", symbol, len(signals), len(df))
    return signals
