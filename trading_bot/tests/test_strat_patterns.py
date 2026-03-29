"""
tests/test_strat_patterns.py — Unit Tests for Strat Pattern Recognition

Tests cover:
- 2u-1-2u (bullish continuation) detection
- 2d-1-2d (bearish continuation) detection
- 3-1-2u (bullish reversal) detection
- 3-1-2d (bearish reversal) detection
- 2u-2u and 2d-2d broadening patterns
- 'none' returned when no pattern present
- Trigger price assignment
- Correct direction labels
"""

import pandas as pd
import pytest

from strategy.strat_classifier import classify_dataframe
from strategy.strat_patterns import detect_patterns


def make_classified_df(type_sequence: list[str]) -> pd.DataFrame:
    """
    Build a minimal DataFrame with a specific strat_type sequence.
    High/low values are synthetic — just enough to produce the desired types.
    """
    rows = []
    # Seed the first bar
    rows.append({"high": 100.0, "low": 98.0})

    # For each desired type after the first, construct high/low that produce it
    for t in type_sequence[1:]:
        prev = rows[-1]
        if t == "2u":
            rows.append({"high": prev["high"] + 1.0, "low": prev["low"]})
        elif t == "2d":
            rows.append({"high": prev["high"], "low": prev["low"] - 1.0})
        elif t == "1":
            rows.append({"high": prev["high"] - 0.5, "low": prev["low"] + 0.5})
        elif t == "3":
            rows.append({"high": prev["high"] + 1.0, "low": prev["low"] - 1.0})
        else:
            rows.append({"high": prev["high"], "low": prev["low"]})

    df = pd.DataFrame(rows)
    # Manually assign strat_type to avoid dependency on classifier correctness
    df["strat_type"] = ["unknown"] + type_sequence[1:]
    df["strat_type"].iloc[0] = "unknown"
    return df


class TestDetectPatterns:
    def test_bullish_2u_1_2u(self):
        # Seed + 3 bars to form a 3-bar pattern
        df = make_classified_df(["unknown", "2u", "1", "2u"])
        result = detect_patterns(df)
        assert result.iloc[-1]["strat_pattern"] == "2u-1-2u"
        assert result.iloc[-1]["pattern_dir"] == "long"

    def test_bearish_2d_1_2d(self):
        df = make_classified_df(["unknown", "2d", "1", "2d"])
        result = detect_patterns(df)
        assert result.iloc[-1]["strat_pattern"] == "2d-1-2d"
        assert result.iloc[-1]["pattern_dir"] == "short"

    def test_bullish_reversal_3_1_2u(self):
        df = make_classified_df(["unknown", "3", "1", "2u"])
        result = detect_patterns(df)
        assert result.iloc[-1]["strat_pattern"] == "3-1-2u"
        assert result.iloc[-1]["pattern_dir"] == "long"

    def test_bearish_reversal_3_1_2d(self):
        df = make_classified_df(["unknown", "3", "1", "2d"])
        result = detect_patterns(df)
        assert result.iloc[-1]["strat_pattern"] == "3-1-2d"
        assert result.iloc[-1]["pattern_dir"] == "short"

    def test_broadening_2u_2u(self):
        df = make_classified_df(["unknown", "2u", "2u"])
        result = detect_patterns(df)
        assert result.iloc[-1]["strat_pattern"] == "2u-2u"
        assert result.iloc[-1]["pattern_dir"] == "long"

    def test_broadening_2d_2d(self):
        df = make_classified_df(["unknown", "2d", "2d"])
        result = detect_patterns(df)
        assert result.iloc[-1]["strat_pattern"] == "2d-2d"
        assert result.iloc[-1]["pattern_dir"] == "short"

    def test_no_pattern_returns_none(self):
        df = make_classified_df(["unknown", "1", "1", "1"])
        result = detect_patterns(df)
        assert all(result["strat_pattern"] == "none")

    def test_trigger_prices_set(self):
        df = make_classified_df(["unknown", "2u", "1", "2u"])
        result = detect_patterns(df)
        last = result.iloc[-1]
        assert not pd.isna(last["trigger_high"])
        assert not pd.isna(last["trigger_low"])
        assert last["trigger_high"] == last["high"]
        assert last["trigger_low"] == last["low"]

    def test_non_pattern_bars_have_none_pattern(self):
        df = make_classified_df(["unknown", "2u", "1", "2u", "1"])
        result = detect_patterns(df)
        # Bar index 4 (type "1") should not complete a new pattern
        assert result.iloc[4]["strat_pattern"] == "none"

    def test_required_columns_missing_raises(self):
        df = pd.DataFrame({"strat_type": ["unknown", "2u", "1", "2u"]})
        # Missing 'high' and 'low'
        with pytest.raises(ValueError, match="missing required columns"):
            detect_patterns(df)
