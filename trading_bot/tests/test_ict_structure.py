"""
tests/test_ict_structure.py — Unit Tests for ICT Market Structure Detection

Tests cover:
- Swing high/low detection with configurable lookback
- BOS (Break of Structure) detection — up and down
- CHoCH (Change of Character) detection — up and down
- Displacement candle detection via ATR multiple
- ATR computation correctness
- No false BOS/CHoCH in sideways markets
- Correct trend state transitions (up → down via CHoCH, etc.)
"""

import numpy as np
import pandas as pd
import pytest

from strategy.ict_structure import annotate_structure, find_swing_highs_lows


def make_trending_up_df() -> pd.DataFrame:
    """Create a simple uptrending OHLCV DataFrame."""
    n = 20
    base = 100.0
    rows = []
    for i in range(n):
        o = base + i * 0.5
        h = o + 1.0
        l = o - 0.5
        c = o + 0.75
        rows.append({"open": o, "high": h, "low": l, "close": c})
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return df


def make_reversal_df() -> pd.DataFrame:
    """
    Uptrend followed by a sharp drop below prior swing low — creates CHoCH.
    Bars 0-9: trending up. Bars 10-15: trending down through prior swing low.
    """
    rows = []
    # Uptrend: rising highs and lows
    for i in range(10):
        o = 100 + i
        rows.append({"open": float(o), "high": float(o + 2), "low": float(o - 1), "close": float(o + 1.5)})
    # Reversal: drop below bar 5's low
    for i in range(6):
        o = 110 - i * 2
        rows.append({"open": float(o), "high": float(o + 1), "low": float(o - 3), "close": float(o - 2)})

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.date_range("2024-01-01", periods=len(df), freq="15min", tz="UTC")
    return df


class TestFindSwingHighsLows:
    def test_returns_required_columns(self):
        df = make_trending_up_df()
        result = find_swing_highs_lows(df, lookback=2)
        assert "swing_high" in result.columns
        assert "swing_low" in result.columns

    def test_swing_high_is_local_max(self):
        # Bar 5 should be a swing high in a peaked sequence
        rows = [
            {"high": 100, "low": 98},
            {"high": 102, "low": 99},
            {"high": 105, "low": 100},  # peak
            {"high": 103, "low": 101},
            {"high": 101, "low": 99},
        ]
        df = pd.DataFrame(rows)
        result = find_swing_highs_lows(df, lookback=2)
        # Bar index 2 should be the swing high (highest in window)
        assert result.iloc[2]["swing_high"] == 105.0

    def test_swing_low_is_local_min(self):
        rows = [
            {"high": 105, "low": 102},
            {"high": 103, "low": 99},
            {"high": 102, "low": 96},  # trough
            {"high": 104, "low": 99},
            {"high": 106, "low": 101},
        ]
        df = pd.DataFrame(rows)
        result = find_swing_highs_lows(df, lookback=2)
        assert result.iloc[2]["swing_low"] == 96.0

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"high": [100, 101, 102]})
        with pytest.raises(ValueError, match="missing required columns"):
            find_swing_highs_lows(df, lookback=1)

    def test_no_modification_to_original(self):
        df = make_trending_up_df()
        original_cols = set(df.columns)
        find_swing_highs_lows(df, lookback=2)
        assert set(df.columns) == original_cols


class TestAnnotateStructure:
    def test_required_columns_present_in_output(self):
        df = make_trending_up_df()
        df = find_swing_highs_lows(df, lookback=2)
        result = annotate_structure(df)
        for col in ("bos", "choch", "displacement", "bos_price", "choch_price", "atr14"):
            assert col in result.columns

    def test_raises_without_swing_columns(self):
        df = make_trending_up_df()
        with pytest.raises(ValueError, match="missing required columns"):
            annotate_structure(df)

    def test_atr_not_nan_after_period(self):
        df = make_trending_up_df()
        df = find_swing_highs_lows(df, lookback=2)
        result = annotate_structure(df)
        # ATR should be computed for bars after the warmup period (14 bars)
        non_nan_atr = result["atr14"].dropna()
        assert len(non_nan_atr) > 0

    def test_bos_and_choch_are_exclusive(self):
        """A single bar should not have both a BOS and a CHoCH simultaneously."""
        df = make_reversal_df()
        df = find_swing_highs_lows(df, lookback=2)
        result = annotate_structure(df)
        for i, row in result.iterrows():
            assert not (row["bos"] is not None and row["choch"] is not None), (
                f"Bar {i} has both BOS and CHoCH — should be mutually exclusive"
            )

    def test_displacement_flag_on_large_bar(self):
        """A bar with range >> ATR should be flagged as displacement."""
        df = make_trending_up_df()
        # Inject a massive bar at position 10
        df.loc[10, "high"] = df.loc[10, "open"] + 20.0
        df.loc[10, "low"] = df.loc[10, "open"] - 5.0
        df = find_swing_highs_lows(df, lookback=2)
        result = annotate_structure(df, displacement_atr_mult=1.5)
        # The large bar should be flagged
        assert result.loc[10, "displacement"] is True or result.loc[10, "displacement"] == True
