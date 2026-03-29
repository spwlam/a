"""
tests/test_strat_classifier.py — Unit Tests for The Strat Candle Classifier

Coverage matrix:
  classify_single_candle()
    ├── All four canonical types (standard cases)
    ├── All nine high/low equality combinations (truth table)
    ├── Every documented edge case with explanatory comment
    ├── NaN input guard
    └── Malformed bar guard (high < low)

  classify_direction()
    ├── Bullish (close > open)
    ├── Bearish (close < open)
    └── Neutral doji (close == open)

  classify_candles()
    ├── Returns a copy (original unmodified)
    ├── Adds exactly the three expected columns
    ├── Bar 0 → strat_type is NaN, strat_is_actionable is False
    ├── strat_is_actionable True for 2u/2d/3, False for 1
    ├── strat_direction independent of strat_type
    ├── Missing column raises ValueError
    ├── Empty DataFrame raises ValueError
    └── 10-candle sequence with fully specified expected output
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from strategy.strat_classifier import (
    T1, T2D, T2U, T3,
    classify_candles,
    classify_direction,
    classify_single_candle,
)


# ============================================================================
# Helpers
# ============================================================================

def make_bar(
    open_: float = 100.0,
    high: float = 105.0,
    low: float = 95.0,
    close: float = 102.0,
) -> dict[str, float]:
    """Return a minimal OHLC dict."""
    return {"open": open_, "high": high, "low": low, "close": close}


def make_df(rows: list[dict[str, float]]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame from a list of OHLC dicts."""
    df = pd.DataFrame(rows)
    if "volume" not in df.columns:
        df["volume"] = 1000.0
    return df


# ============================================================================
# classify_single_candle — canonical types
# ============================================================================

class TestClassifySingleCandleCanonicalTypes:
    """Standard cases where strict inequalities unambiguously determine type."""

    def test_type_1_strict_inside(self):
        # high strictly less than prev.high, low strictly greater than prev.low
        assert classify_single_candle(
            high=99.0, low=91.0, prev_high=100.0, prev_low=90.0
        ) == T1

    def test_type_2u_standard(self):
        # high > prev.high, low > prev.low  (took high only, stayed inside on low)
        assert classify_single_candle(
            high=101.0, low=91.0, prev_high=100.0, prev_low=90.0
        ) == T2U

    def test_type_2u_with_equal_low(self):
        # high > prev.high, low == prev.low  (took high, low exactly matched)
        # Rule: 2U requires low >= prev.low — equality satisfies this
        assert classify_single_candle(
            high=101.0, low=90.0, prev_high=100.0, prev_low=90.0
        ) == T2U

    def test_type_2d_standard(self):
        # low < prev.low, high < prev.high  (took low only, stayed inside on high)
        assert classify_single_candle(
            high=99.0, low=89.0, prev_high=100.0, prev_low=90.0
        ) == T2D

    def test_type_2d_with_equal_high(self):
        # low < prev.low, high == prev.high  (took low, high exactly matched)
        # Rule: 2D requires high <= prev.high — equality satisfies this
        assert classify_single_candle(
            high=100.0, low=89.0, prev_high=100.0, prev_low=90.0
        ) == T2D

    def test_type_3_outside_bar(self):
        # high > prev.high AND low < prev.low — full outside engulf
        assert classify_single_candle(
            high=101.0, low=89.0, prev_high=100.0, prev_low=90.0
        ) == T3


# ============================================================================
# classify_single_candle — edge cases (all 9 truth-table cells)
# ============================================================================

class TestClassifySingleCandleEdgeCases:
    """
    Exhaustive coverage of all nine (high_rel, low_rel) combinations.
    Each test references the truth table in the module docstring.
    """

    # Row 1: high > prev, low < prev → handled above as Type 3

    # Row 2: high > prev, low == prev → Type 2U (standard)
    def test_took_high_eq_low_is_2u(self):
        assert classify_single_candle(
            high=101.0, low=90.0, prev_high=100.0, prev_low=90.0
        ) == T2U

    # Row 3: high > prev, low > prev → Type 2U (standard)
    def test_took_high_inside_low_is_2u(self):
        assert classify_single_candle(
            high=101.0, low=91.0, prev_high=100.0, prev_low=90.0
        ) == T2U

    # Row 4: high == prev, low < prev → Type 2D
    # The low was taken out; the high only matched (high <= prev.high is satisfied)
    def test_eq_high_took_low_is_2d(self):
        assert classify_single_candle(
            high=100.0, low=89.0, prev_high=100.0, prev_low=90.0
        ) == T2D

    # Row 5: high == prev, low == prev → Type 1 (equal-both edge case)
    # Exact clone of the prior bar — no side taken out — inside bar
    def test_eq_high_eq_low_is_1(self):
        # "Equal high AND equal low: classify as 1"
        assert classify_single_candle(
            high=100.0, low=90.0, prev_high=100.0, prev_low=90.0
        ) == T1

    # Row 6: high == prev, low > prev → Type 2U (doji-high edge case)
    # "Doji where high == prev.high: classify as 2U if low is higher"
    # The high was tested (touched) while the low stayed inside — bullish read
    def test_eq_high_inside_low_is_2u(self):
        assert classify_single_candle(
            high=100.0, low=91.0, prev_high=100.0, prev_low=90.0
        ) == T2U

    # Row 7: high < prev, low < prev → Type 2D (standard)
    def test_inside_high_took_low_is_2d(self):
        assert classify_single_candle(
            high=99.0, low=89.0, prev_high=100.0, prev_low=90.0
        ) == T2D

    # Row 8: high < prev, low == prev → Type 1 (conservative equal-low)
    # The low touched but did not exceed the prior low.
    # Nothing was "taken out" — conservative classification as inside bar.
    # NOTE: we do NOT mirror the eq_high rule here; only the high-equality
    # edge case is explicitly specified. Low-equality → Type 1.
    def test_inside_high_eq_low_is_1(self):
        assert classify_single_candle(
            high=99.0, low=90.0, prev_high=100.0, prev_low=90.0
        ) == T1

    # Row 9: high < prev, low > prev → Type 1 (strict inside)
    def test_inside_high_inside_low_is_1(self):
        assert classify_single_candle(
            high=99.0, low=91.0, prev_high=100.0, prev_low=90.0
        ) == T1


# ============================================================================
# classify_single_candle — boundary / precision edge cases
# ============================================================================

class TestClassifySingleCandleBoundaryValues:
    """Near-zero differences, float precision, extreme prices."""

    def test_tiny_new_high_is_2u(self):
        # Only 0.01 above prev high — still unambiguously 2U
        assert classify_single_candle(
            high=100.01, low=91.0, prev_high=100.0, prev_low=90.0
        ) == T2U

    def test_tiny_new_low_is_2d(self):
        # Only 0.01 below prev low — still 2D
        assert classify_single_candle(
            high=99.0, low=89.99, prev_high=100.0, prev_low=90.0
        ) == T2D

    def test_type_1_touching_neither_extreme(self):
        # Both within but not at the boundary
        assert classify_single_candle(
            high=99.99, low=90.01, prev_high=100.0, prev_low=90.0
        ) == T1

    def test_large_outside_bar_is_3(self):
        # Bar range 10× the prior range
        assert classify_single_candle(
            high=200.0, low=50.0, prev_high=110.0, prev_low=100.0
        ) == T3

    def test_very_large_prices(self):
        # ES at high prices — high > prev_high, low > prev_low → clean 2U
        # high(5050.25) > prev_high(5050.00): took high ✓
        # low(5042.00)  > prev_low(5041.00):  did NOT take low ✓
        assert classify_single_candle(
            high=5050.25, low=5042.00,
            prev_high=5050.00, prev_low=5041.00
        ) == T2U

    def test_very_large_prices_2d(self):
        # Corrected: 5040 < 5041 and 5050.25 > 5050.00 → Type 3
        assert classify_single_candle(
            high=5050.25, low=5040.00,
            prev_high=5050.00, prev_low=5041.00
        ) == T3  # took both sides

    def test_2u_large_prices_clean(self):
        assert classify_single_candle(
            high=5051.00, low=5042.00,
            prev_high=5050.00, prev_low=5041.00
        ) == T2U

    def test_equal_prices_is_1(self):
        # Both high and low identical to prev → inside (exact clone)
        assert classify_single_candle(
            high=100.0, low=90.0, prev_high=100.0, prev_low=90.0
        ) == T1


# ============================================================================
# classify_single_candle — guard clauses
# ============================================================================

class TestClassifySingleCandleGuards:

    def test_nan_high_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            classify_single_candle(
                high=float("nan"), low=90.0, prev_high=100.0, prev_low=89.0
            )

    def test_nan_low_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            classify_single_candle(
                high=101.0, low=float("nan"), prev_high=100.0, prev_low=89.0
            )

    def test_nan_prev_high_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            classify_single_candle(
                high=101.0, low=90.0, prev_high=float("nan"), prev_low=89.0
            )

    def test_nan_prev_low_raises(self):
        with pytest.raises(ValueError, match="NaN"):
            classify_single_candle(
                high=101.0, low=90.0, prev_high=100.0, prev_low=float("nan")
            )

    def test_high_less_than_low_raises(self):
        # Structurally invalid bar — high must be >= low
        with pytest.raises(ValueError, match="Invalid bar"):
            classify_single_candle(
                high=89.0, low=91.0, prev_high=100.0, prev_low=90.0
            )

    def test_high_equal_to_low_is_valid(self):
        # A doji with zero range is structurally valid (high == low)
        # high(100) == prev_high(100) AND low(100) > prev_low(90) → 2U edge case
        result = classify_single_candle(
            high=100.0, low=100.0, prev_high=100.0, prev_low=90.0
        )
        # high == prev_high AND low(100) > prev_low(90) → 2U
        assert result == T2U


# ============================================================================
# classify_direction
# ============================================================================

class TestClassifyDirection:

    def test_bullish(self):
        assert classify_direction(open_=100.0, close=105.0) == "bullish"

    def test_bearish(self):
        assert classify_direction(open_=105.0, close=100.0) == "bearish"

    def test_neutral_doji(self):
        assert classify_direction(open_=100.0, close=100.0) == "neutral"

    def test_tiny_positive_move_is_bullish(self):
        assert classify_direction(open_=100.0, close=100.0001) == "bullish"

    def test_tiny_negative_move_is_bearish(self):
        assert classify_direction(open_=100.0001, close=100.0) == "bearish"


# ============================================================================
# classify_candles — output structure
# ============================================================================

class TestClassifyCandlesOutputStructure:

    def _two_bar_df(self) -> pd.DataFrame:
        return make_df([
            make_bar(open_=100, high=105, low=95,  close=103),   # bar 0
            make_bar(open_=103, high=106, low=96,  close=104),   # bar 1 → 2U
        ])

    def test_returns_dataframe(self):
        result = classify_candles(self._two_bar_df())
        assert isinstance(result, pd.DataFrame)

    def test_three_new_columns_added(self):
        result = classify_candles(self._two_bar_df())
        for col in ("strat_type", "strat_direction", "strat_is_actionable"):
            assert col in result.columns, f"Missing column: {col}"

    def test_no_extra_columns_added(self):
        df = self._two_bar_df()
        original_cols = set(df.columns)
        result = classify_candles(df)
        new_cols = set(result.columns) - original_cols
        assert new_cols == {"strat_type", "strat_direction", "strat_is_actionable"}

    def test_does_not_modify_original(self):
        df = self._two_bar_df()
        original_cols = set(df.columns)
        classify_candles(df)
        assert set(df.columns) == original_cols
        assert "strat_type" not in df.columns

    def test_output_length_equals_input(self):
        df = self._two_bar_df()
        result = classify_candles(df)
        assert len(result) == len(df)


# ============================================================================
# classify_candles — bar 0 handling
# ============================================================================

class TestClassifyCandlesFirstBar:

    def _df(self) -> pd.DataFrame:
        return make_df([
            make_bar(high=105, low=95, open_=100, close=103),
            make_bar(high=106, low=96, open_=103, close=104),
        ])

    def test_bar_0_strat_type_is_nan(self):
        result = classify_candles(self._df())
        assert math.isnan(float(result.iloc[0]["strat_type"])) or \
               pd.isna(result.iloc[0]["strat_type"])

    def test_bar_0_is_not_actionable(self):
        result = classify_candles(self._df())
        assert result.iloc[0]["strat_is_actionable"] is False or \
               result.iloc[0]["strat_is_actionable"] == False

    def test_bar_0_has_direction(self):
        # Direction is based on open/close of the bar itself — always available
        result = classify_candles(self._df())
        assert result.iloc[0]["strat_direction"] in ("bullish", "bearish", "neutral")


# ============================================================================
# classify_candles — actionable flag
# ============================================================================

class TestClassifyCandlesActionable:

    def test_type_1_is_not_actionable(self):
        df = make_df([
            make_bar(high=105, low=95),    # bar 0
            make_bar(high=104, low=96),    # bar 1 → Type 1 (inside)
        ])
        result = classify_candles(df)
        assert result.iloc[1]["strat_type"] == T1
        assert result.iloc[1]["strat_is_actionable"] == False

    def test_type_2u_is_actionable(self):
        df = make_df([
            make_bar(high=105, low=95),
            make_bar(high=106, low=96),    # 2U: took high, inside on low
        ])
        result = classify_candles(df)
        assert result.iloc[1]["strat_type"] == T2U
        assert result.iloc[1]["strat_is_actionable"] == True

    def test_type_2d_is_actionable(self):
        df = make_df([
            make_bar(high=105, low=95),
            make_bar(high=104, low=94),    # 2D: took low, inside on high
        ])
        result = classify_candles(df)
        assert result.iloc[1]["strat_type"] == T2D
        assert result.iloc[1]["strat_is_actionable"] == True

    def test_type_3_is_actionable(self):
        df = make_df([
            make_bar(high=105, low=95),
            make_bar(high=106, low=94),    # Type 3: took both sides
        ])
        result = classify_candles(df)
        assert result.iloc[1]["strat_type"] == T3
        assert result.iloc[1]["strat_is_actionable"] == True


# ============================================================================
# classify_candles — strat_direction independence
# ============================================================================

class TestClassifyCandlesDirection:
    """Direction is determined by open vs close — independent of strat_type."""

    def test_2u_can_be_bearish(self):
        # Bar takes out prior high but closes below open (red 2U)
        df = make_df([
            make_bar(high=105, low=95, open_=100, close=100),
            make_bar(high=106, low=96, open_=105, close=97),  # red candle, but 2U
        ])
        result = classify_candles(df)
        assert result.iloc[1]["strat_type"] == T2U
        assert result.iloc[1]["strat_direction"] == "bearish"

    def test_2d_can_be_bullish(self):
        # Bar takes out prior low but closes above open (green 2D)
        df = make_df([
            make_bar(high=105, low=95, open_=100, close=100),
            make_bar(high=104, low=94, open_=95, close=103),  # green candle, but 2D
        ])
        result = classify_candles(df)
        assert result.iloc[1]["strat_type"] == T2D
        assert result.iloc[1]["strat_direction"] == "bullish"

    def test_neutral_direction_doji(self):
        df = make_df([
            make_bar(high=105, low=95, open_=100, close=100),
            make_bar(high=104, low=96, open_=101, close=101),  # doji inside bar
        ])
        result = classify_candles(df)
        assert result.iloc[1]["strat_direction"] == "neutral"


# ============================================================================
# classify_candles — error handling
# ============================================================================

class TestClassifyCandlesErrors:

    def test_missing_open_column_raises(self):
        df = pd.DataFrame({"high": [105.0], "low": [95.0], "close": [102.0]})
        with pytest.raises(ValueError, match="missing required columns"):
            classify_candles(df)

    def test_missing_high_column_raises(self):
        df = pd.DataFrame({"open": [100.0], "low": [95.0], "close": [102.0]})
        with pytest.raises(ValueError, match="missing required columns"):
            classify_candles(df)

    def test_empty_dataframe_raises(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close"])
        with pytest.raises(ValueError, match="empty"):
            classify_candles(df)

    def test_extra_columns_preserved(self):
        # Columns beyond OHLC should pass through untouched
        df = make_df([
            make_bar(high=105, low=95),
            make_bar(high=106, low=96),
        ])
        df["my_indicator"] = [1.0, 2.0]
        result = classify_candles(df)
        assert "my_indicator" in result.columns
        assert list(result["my_indicator"]) == [1.0, 2.0]


# ============================================================================
# 10-candle sequence — fully specified expected output
# ============================================================================

class TestTenCandleSequence:
    """
    A hand-crafted 10-bar sequence where every strat_type, strat_direction,
    and strat_is_actionable value is predetermined and verified.

    Bar design rationale
    ─────────────────────
    Bar 0: Seed bar — no prior, cannot be classified.
           OHLC: O=100  H=105  L=95   C=102   → direction: bullish

    Bar 1: high(108) > prev_high(105), low(96) > prev_low(95)
           → 2U | close(104) > open(103) → bullish | actionable

    Bar 2: high(107) < prev_high(108), low(97) > prev_low(96)
           → 1  | close(105) > open(104) → bullish | NOT actionable

    Bar 3: high(115) > prev_high(107), low(90) < prev_low(97)
           → 3  | close(91)  < open(110) → bearish | actionable

    Bar 4: high(113) < prev_high(115), low(88) < prev_low(90)
           → 2D | close(89)  < open(110) → bearish | actionable

    Bar 5: high(113) == prev_high(113), low(89) > prev_low(88)
           → 2U (edge: eq_high, low is higher) | close(112) > open(90) → bullish | actionable

    Bar 6: high(112) < prev_high(113), low(89) == prev_low(89)
           → 1  (edge: inside_high, eq_low → conservative 1) | close(110) > open(90) → bullish | NOT actionable

    Bar 7: high(112) == prev_high(112), low(89) == prev_low(89)
           → 1  (edge: equal-both) | close(111) > open(90) → bullish | NOT actionable

    Bar 8: high(120) > prev_high(112), low(85) < prev_low(89)
           → 3  | close(118) > open(90) → bullish | actionable

    Bar 9: high(122) > prev_high(120), low(86) > prev_low(85)
           → 2U | close(120) > open(119) → bullish | actionable
    """

    BARS = [
        # open    high    low     close
        (100.0,  105.0,  95.0,  102.0),   # 0: seed
        (103.0,  108.0,  96.0,  104.0),   # 1: 2U  bullish
        (104.0,  107.0,  97.0,  105.0),   # 2: 1   bullish
        (110.0,  115.0,  90.0,   91.0),   # 3: 3   bearish
        (110.0,  113.0,  88.0,   89.0),   # 4: 2D  bearish
        ( 90.0,  113.0,  89.0,  112.0),   # 5: 2U  bullish  (eq_high edge)
        ( 90.0,  112.0,  89.0,  110.0),   # 6: 1   bullish  (eq_low edge)
        ( 90.0,  112.0,  89.0,  111.0),   # 7: 1   bullish  (eq_both edge)
        ( 90.0,  120.0,  85.0,  118.0),   # 8: 3   bullish
        (119.0,  122.0,  86.0,  120.0),   # 9: 2U  bullish
    ]

    EXPECTED_TYPES = [
        None,   # 0: no prior bar
        T2U,    # 1
        T1,     # 2
        T3,     # 3
        T2D,    # 4
        T2U,    # 5  edge: eq_high + inside_low
        T1,     # 6  edge: inside_high + eq_low
        T1,     # 7  edge: eq_high + eq_low
        T3,     # 8
        T2U,    # 9
    ]

    EXPECTED_DIRECTIONS = [
        "bullish",  # 0: close(102) > open(100)
        "bullish",  # 1: close(104) > open(103)
        "bullish",  # 2: close(105) > open(104)
        "bearish",  # 3: close(91)  < open(110)
        "bearish",  # 4: close(89)  < open(110)
        "bullish",  # 5: close(112) > open(90)
        "bullish",  # 6: close(110) > open(90)
        "bullish",  # 7: close(111) > open(90)
        "bullish",  # 8: close(118) > open(90)
        "bullish",  # 9: close(120) > open(119)
    ]

    EXPECTED_ACTIONABLE = [
        False,  # 0: NaN type
        True,   # 1: 2U
        False,  # 2: 1
        True,   # 3: 3
        True,   # 4: 2D
        True,   # 5: 2U
        False,  # 6: 1
        False,  # 7: 1
        True,   # 8: 3
        True,   # 9: 2U
    ]

    @pytest.fixture
    def result(self) -> pd.DataFrame:
        rows = [
            {"open": o, "high": h, "low": l, "close": c}
            for o, h, l, c in self.BARS
        ]
        df = make_df(rows)
        return classify_candles(df)

    def test_output_length(self, result):
        assert len(result) == 10

    def test_strat_type_bar0_is_nan(self, result):
        assert pd.isna(result.iloc[0]["strat_type"])

    @pytest.mark.parametrize("bar_idx, expected_type", [
        (1, T2U),
        (2, T1),
        (3, T3),
        (4, T2D),
        (5, T2U),   # eq_high edge case
        (6, T1),    # eq_low edge case (conservative)
        (7, T1),    # equal-both edge case
        (8, T3),
        (9, T2U),
    ])
    def test_strat_types(self, result, bar_idx, expected_type):
        actual = result.iloc[bar_idx]["strat_type"]
        assert actual == expected_type, (
            f"Bar {bar_idx}: expected {expected_type!r}, got {actual!r}"
        )

    @pytest.mark.parametrize("bar_idx, expected_dir", enumerate([
        "bullish", "bullish", "bullish", "bearish", "bearish",
        "bullish", "bullish", "bullish", "bullish", "bullish",
    ]))
    def test_strat_directions(self, result, bar_idx, expected_dir):
        actual = result.iloc[bar_idx]["strat_direction"]
        assert actual == expected_dir, (
            f"Bar {bar_idx}: expected direction {expected_dir!r}, got {actual!r}"
        )

    @pytest.mark.parametrize("bar_idx, expected_actionable", enumerate([
        False, True, False, True, True,
        True, False, False, True, True,
    ]))
    def test_strat_is_actionable(self, result, bar_idx, expected_actionable):
        actual = result.iloc[bar_idx]["strat_is_actionable"]
        assert bool(actual) == expected_actionable, (
            f"Bar {bar_idx}: expected actionable={expected_actionable}, got {actual}"
        )


# ============================================================================
# Regression: repeated equal bars
# ============================================================================

class TestRegressionRepeatedEqual:
    """Edge case: multiple consecutive bars with identical OHLC values."""

    def test_flat_market_all_type_1(self):
        # Every bar is identical — all should be Type 1 (eq_high + eq_low)
        rows = [{"open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0}] * 5
        result = classify_candles(make_df(rows))
        # Bar 0 is NaN; bars 1-4 should all be Type 1
        for i in range(1, 5):
            assert result.iloc[i]["strat_type"] == T1, f"Bar {i} should be T1"

    def test_flat_market_none_actionable(self):
        rows = [{"open": 100.0, "high": 105.0, "low": 95.0, "close": 102.0}] * 5
        result = classify_candles(make_df(rows))
        # Bar 0 is NaN (False), bars 1-4 are T1 (False)
        assert result["strat_is_actionable"].sum() == 0
