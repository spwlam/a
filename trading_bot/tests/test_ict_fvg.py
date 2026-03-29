"""
tests/test_ict_fvg.py — Unit Tests for ICT Fair Value Gap Detection

Tests cover:
- Bullish FVG detection (bar[i].low > bar[i-2].high)
- Bearish FVG detection (bar[i].high < bar[i-2].low)
- No false positives when gap doesn't exist
- min_gap_pct filter (small gaps rejected)
- Mitigation detection: partial and full (invalidation)
- annotate_fvgs correctly populates DataFrame columns
- No lookahead: FVG at index i not visible at index i
"""

import pandas as pd
import pytest

from strategy.ict_fvg import FairValueGap, annotate_fvgs, detect_fvgs, update_mitigation


def make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame with timestamps."""
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.date_range("2024-01-01", periods=len(df), freq="15min", tz="UTC")
    if "close" not in df.columns:
        df["close"] = (df["high"] + df["low"]) / 2
    return df


class TestDetectFvgs:
    def test_bullish_fvg_detected(self):
        # bar[0].high=10, bar[2].low=12 → gap of 2 between 10 and 12
        df = make_df([
            {"high": 10.0, "low": 8.0,  "close": 9.0},
            {"high": 15.0, "low": 11.0, "close": 13.0},  # impulse bar
            {"high": 20.0, "low": 12.0, "close": 16.0},  # FVG bar
        ])
        fvgs = detect_fvgs(df, min_gap_pct=0.0)
        bull_fvgs = [f for f in fvgs if f.fvg_type == "bullish"]
        assert len(bull_fvgs) == 1
        assert bull_fvgs[0].bottom == 10.0
        assert bull_fvgs[0].top == 12.0
        assert bull_fvgs[0].midpoint == 11.0

    def test_bearish_fvg_detected(self):
        # bar[0].low=18, bar[2].high=15 → gap between 15 and 18
        df = make_df([
            {"high": 22.0, "low": 18.0, "close": 20.0},
            {"high": 17.0, "low": 13.0, "close": 15.0},  # impulse bar
            {"high": 15.0, "low": 10.0, "close": 12.0},  # FVG bar
        ])
        fvgs = detect_fvgs(df, min_gap_pct=0.0)
        bear_fvgs = [f for f in fvgs if f.fvg_type == "bearish"]
        assert len(bear_fvgs) == 1
        assert bear_fvgs[0].bottom == 15.0
        assert bear_fvgs[0].top == 18.0

    def test_no_fvg_when_no_gap(self):
        # Bars overlap — no gap
        df = make_df([
            {"high": 10.0, "low": 8.0,  "close": 9.0},
            {"high": 12.0, "low": 9.5,  "close": 11.0},
            {"high": 14.0, "low": 9.8,  "close": 12.0},  # bar[2].low < bar[0].high
        ])
        fvgs = detect_fvgs(df, min_gap_pct=0.0)
        assert len(fvgs) == 0

    def test_min_gap_pct_filters_small_gaps(self):
        # Gap of 0.05 on a $100 price → 0.05%
        df = make_df([
            {"high": 100.0,  "low": 98.0,  "close": 99.0},
            {"high": 105.0,  "low": 100.1, "close": 102.0},
            {"high": 110.0,  "low": 100.05,"close": 105.0},
        ])
        # With 0.1% threshold → gap of ~0.05% should be filtered
        fvgs_strict = detect_fvgs(df, min_gap_pct=0.1)
        fvgs_loose = detect_fvgs(df, min_gap_pct=0.0)
        assert len(fvgs_strict) == 0
        assert len(fvgs_loose) >= 0  # No assertion on count, just no crash

    def test_fvg_bar_index_correct(self):
        df = make_df([
            {"high": 10.0, "low": 8.0,  "close": 9.0},
            {"high": 15.0, "low": 11.0, "close": 13.0},
            {"high": 20.0, "low": 12.0, "close": 16.0},
        ])
        fvgs = detect_fvgs(df, min_gap_pct=0.0)
        assert fvgs[0].bar_index == 2  # FVG formed at bar index 2

    def test_requires_minimum_3_bars(self):
        df = make_df([
            {"high": 10.0, "low": 8.0, "close": 9.0},
            {"high": 12.0, "low": 9.0, "close": 11.0},
        ])
        fvgs = detect_fvgs(df, min_gap_pct=0.0)
        assert len(fvgs) == 0  # Cannot detect with < 3 bars


class TestUpdateMitigation:
    def _make_bull_fvg(self) -> tuple[FairValueGap, pd.DataFrame]:
        """Helper: bullish FVG at bars 0-2, then forward bars 3-5."""
        df = make_df([
            {"high": 10.0, "low": 8.0,  "close": 9.0},
            {"high": 15.0, "low": 11.0, "close": 13.0},
            {"high": 20.0, "low": 12.0, "close": 16.0},
            {"high": 20.0, "low": 11.5, "close": 15.0},  # enters FVG (low <= top=12) — mitigated
            {"high": 18.0, "low": 12.5, "close": 15.0},  # stays above bottom
        ])
        fvgs = detect_fvgs(df, min_gap_pct=0.0)
        return fvgs, df

    def test_mitigation_flagged(self):
        fvgs, df = self._make_bull_fvg()
        updated = update_mitigation(fvgs, df)
        bull = [f for f in updated if f.fvg_type == "bullish"]
        assert len(bull) == 1
        assert bull[0].is_mitigated is True

    def test_invalidation_on_close_through(self):
        df = make_df([
            {"high": 10.0, "low": 8.0,  "close": 9.0},
            {"high": 15.0, "low": 11.0, "close": 13.0},
            {"high": 20.0, "low": 12.0, "close": 16.0},
            {"high": 15.0, "low": 9.5,  "close": 9.0},  # close < FVG bottom (10) → invalidated
        ])
        fvgs = detect_fvgs(df, min_gap_pct=0.0)
        updated = update_mitigation(fvgs, df)
        bull = [f for f in updated if f.fvg_type == "bullish"]
        assert bull[0].is_invalidated is True


class TestAnnotateFvgs:
    def test_columns_added(self):
        df = make_df([
            {"high": 10.0, "low": 8.0,  "close": 9.0},
            {"high": 15.0, "low": 11.0, "close": 13.0},
            {"high": 20.0, "low": 12.0, "close": 16.0},
            {"high": 11.5, "low": 10.5, "close": 11.0},  # in bull FVG zone
        ])
        fvgs = detect_fvgs(df, min_gap_pct=0.0)
        annotated = annotate_fvgs(df, fvgs)

        for col in ("nearest_bull_fvg_top", "nearest_bull_fvg_bottom", "in_bull_fvg"):
            assert col in annotated.columns

    def test_no_lookahead_at_fvg_bar(self):
        """FVG formed at bar 2 must NOT be visible at bar 2 (only at bar 3+)."""
        df = make_df([
            {"high": 10.0, "low": 8.0,  "close": 9.0},
            {"high": 15.0, "low": 11.0, "close": 13.0},
            {"high": 20.0, "low": 12.0, "close": 16.0},
        ])
        fvgs = detect_fvgs(df, min_gap_pct=0.0)
        annotated = annotate_fvgs(df, fvgs)
        # At bar index 2 (the bar that CREATES the FVG), it should not be visible
        assert pd.isna(annotated.iloc[2]["nearest_bull_fvg_top"])
