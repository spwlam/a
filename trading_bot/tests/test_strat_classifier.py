"""
tests/test_strat_classifier.py — Unit Tests for Strat Candle Classifier

Tests cover:
- Individual bar classification for all four types (1, 2u, 2d, 3)
- Edge cases: exact equality at prior high/low (should be Type 1)
- DataFrame-level classification with correct 'unknown' first bar
- Tolerance parameter behavior
- Type count summary helper
"""

import pandas as pd
import pytest

from strategy.strat_classifier import (
    INSIDE, OUTSIDE_BAR, OUTSIDE_DOWN, OUTSIDE_UP, UNKNOWN,
    classify_bar, classify_dataframe, get_type_counts,
)


# ---------------------------------------------------------------------------
# classify_bar unit tests
# ---------------------------------------------------------------------------

class TestClassifyBar:
    def test_inside_bar(self):
        # High and low both inside prior range
        assert classify_bar(high=10, low=8, prior_high=12, prior_low=7) == INSIDE

    def test_outside_up(self):
        # Only high was taken out
        assert classify_bar(high=13, low=8, prior_high=12, prior_low=7) == OUTSIDE_UP

    def test_outside_down(self):
        # Only low was taken out
        assert classify_bar(high=11, low=6, prior_high=12, prior_low=7) == OUTSIDE_DOWN

    def test_outside_bar(self):
        # Both high and low taken out
        assert classify_bar(high=13, low=6, prior_high=12, prior_low=7) == OUTSIDE_BAR

    def test_exact_equality_is_inside(self):
        # Exact match on prior high/low with zero tolerance = Type 1
        assert classify_bar(high=12, low=7, prior_high=12, prior_low=7) == INSIDE

    def test_tolerance_converts_outside_to_inside(self):
        # Bar only slightly breaks prior high — tolerance makes it inside
        assert classify_bar(high=12.05, low=7, prior_high=12, prior_low=7, tolerance=0.1) == INSIDE

    def test_tolerance_still_outside_when_exceeds(self):
        # Bar breaks prior high by more than tolerance — still Type 2u
        assert classify_bar(high=12.2, low=7, prior_high=12, prior_low=7, tolerance=0.1) == OUTSIDE_UP


# ---------------------------------------------------------------------------
# classify_dataframe unit tests
# ---------------------------------------------------------------------------

class TestClassifyDataframe:
    def _make_df(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_first_bar_is_unknown(self):
        df = self._make_df([
            {"high": 10, "low": 8},
            {"high": 11, "low": 7},
        ])
        result = classify_dataframe(df)
        assert result.iloc[0]["strat_type"] == UNKNOWN

    def test_second_bar_classified(self):
        df = self._make_df([
            {"high": 10, "low": 8},
            {"high": 11, "low": 9},  # 2u: took out prior high, didn't take low
        ])
        result = classify_dataframe(df)
        assert result.iloc[1]["strat_type"] == OUTSIDE_UP

    def test_full_sequence(self):
        df = self._make_df([
            {"high": 10, "low": 8},   # [0] unknown
            {"high": 11, "low": 9},   # [1] 2u
            {"high": 10, "low": 9},   # [2] 1 (inside prior 2u bar)
            {"high": 12, "low": 7},   # [3] 3 (outside bar)
            {"high": 11, "low": 8},   # [4] 1 (inside prior 3 bar)
        ])
        result = classify_dataframe(df)
        expected = [UNKNOWN, OUTSIDE_UP, INSIDE, OUTSIDE_BAR, INSIDE]
        assert result["strat_type"].tolist() == expected

    def test_missing_column_raises(self):
        df = pd.DataFrame({"high": [10, 11]})  # Missing 'low'
        with pytest.raises(ValueError, match="missing required columns"):
            classify_dataframe(df)

    def test_no_modification_of_original(self):
        df = pd.DataFrame({"high": [10, 11], "low": [8, 9]})
        original_cols = set(df.columns)
        classify_dataframe(df)
        assert set(df.columns) == original_cols  # Original unchanged

    def test_strat_type_column_added(self):
        df = pd.DataFrame({"high": [10, 11], "low": [8, 9]})
        result = classify_dataframe(df)
        assert "strat_type" in result.columns


# ---------------------------------------------------------------------------
# get_type_counts
# ---------------------------------------------------------------------------

class TestGetTypeCounts:
    def test_counts_correct(self):
        df = pd.DataFrame({
            "high": [10, 11, 10, 12, 10],
            "low":  [8,  9,  9,  7,  9],
        })
        df = classify_dataframe(df)
        counts = get_type_counts(df)
        assert isinstance(counts, dict)
        assert sum(counts.values()) == len(df)

    def test_raises_without_classification(self):
        df = pd.DataFrame({"high": [10, 11], "low": [8, 9]})
        with pytest.raises(ValueError, match="not been classified"):
            get_type_counts(df)
