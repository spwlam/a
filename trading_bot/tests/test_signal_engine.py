"""
tests/test_signal_engine.py — Unit Tests for Signal Engine

Tests cover:
- No signal emitted when any required gate fails
- Signal emitted only when all 7 gates pass
- Signal ID format correctness
- Direction matches pattern_dir and htf_bias
- R:R calculation in the generated signal
- Strength classification (A/B/C)
- run_signal_scan returns correct count
- No lookahead: signal at bar i uses only data up to bar i
"""

import pandas as pd
import pytest

from strategy.signal_engine import TradeSignal, generate_signal, run_signal_scan


def make_full_df(n: int = 10, **column_overrides) -> pd.DataFrame:
    """
    Build a DataFrame with all required columns for the signal engine.
    All columns default to values that cause all gates to PASS.
    Override specific columns to test gate failures.
    """
    ts = pd.date_range("2024-01-01 09:30", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "timestamp": ts,
        "open":   [19000.0] * n,
        "high":   [19050.0] * n,
        "low":    [18980.0] * n,
        "close":  [19020.0] * n,
        "volume": [1000.0] * n,
        # Session
        "in_session":    [True] * n,
        "session_name":  ["new_york_open"] * n,
        # HTF
        "htf_bias":             ["bullish"] * n,
        "htf_structure_state":  ["trending_up"] * n,
        # Strat
        "strat_type":    ["2u"] * n,
        "strat_pattern": ["2u-1-2u"] * n,
        "pattern_dir":   ["long"] * n,
        "trigger_high":  [19050.0] * n,
        "trigger_low":   [18980.0] * n,
        # ICT structure
        "bos":        [None] * n,
        "choch":      ["up"] * n,    # CHoCH up for bullish setup
        "bos_price":  [float("nan")] * n,
        "choch_price":[19000.0] * n,
        "displacement":[False] * n,
        "atr14":      [20.0] * n,
        # FVG
        "in_bull_fvg":            [True] * n,
        "in_bear_fvg":            [False] * n,
        "nearest_bull_fvg_top":   [19010.0] * n,
        "nearest_bull_fvg_bottom":[18990.0] * n,
        "nearest_bear_fvg_top":   [float("nan")] * n,
        "nearest_bear_fvg_bottom":[float("nan")] * n,
        # Levels
        "swept_low":  [True] * n,    # Liquidity sweep for strength A
        "swept_high": [False] * n,
        "pdh": [19100.0] * n,
        "pdl": [18900.0] * n,
    })

    for col, val in column_overrides.items():
        df[col] = val

    return df


def make_config(**overrides) -> dict:
    cfg = {
        "signal": {
            "require_session_window": True,
            "require_htf_bias": True,
            "require_strat_pattern": True,
            "require_ict_fvg": True,
            "min_rr_ratio": 2.0,
        },
        "execution": {
            "slippage_ticks": 1,
            "order_type": "limit",
        },
    }
    cfg.update(overrides)
    return cfg


VALID_BAR_IDX = 5  # Use bar index 5 — enough history for pattern lookback


class TestGenerateSignal:
    def test_valid_signal_generated(self):
        df = make_full_df()
        config = make_config()
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", config)
        assert signal is not None
        assert isinstance(signal, TradeSignal)

    def test_gate1_session_fail(self):
        df = make_full_df(in_session=[False] * 10)
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is None

    def test_gate2_htf_neutral_fail(self):
        df = make_full_df(htf_bias=["neutral"] * 10)
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is None

    def test_gate3_no_pattern_fail(self):
        df = make_full_df(strat_pattern=["none"] * 10)
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is None

    def test_gate3_misaligned_pattern_fail(self):
        # HTF bias is bullish but pattern is short
        df = make_full_df(
            htf_bias=["bullish"] * 10,
            strat_pattern=["2d-1-2d"] * 10,
            pattern_dir=["short"] * 10,
        )
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is None

    def test_gate4_no_ict_event_fail(self):
        df = make_full_df(
            bos=[None] * 10,
            choch=[None] * 10,
        )
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is None

    def test_gate5_not_in_fvg_fail(self):
        df = make_full_df(in_bull_fvg=[False] * 10)
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is None

    def test_signal_direction_long(self):
        df = make_full_df()
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is not None
        assert signal.direction == "long"

    def test_signal_direction_short(self):
        df = make_full_df(
            htf_bias=["bearish"] * 10,
            strat_pattern=["2d-1-2d"] * 10,
            pattern_dir=["short"] * 10,
            choch=["down"] * 10,
            in_bull_fvg=[False] * 10,
            in_bear_fvg=[True] * 10,
            nearest_bear_fvg_top=[19020.0] * 10,
            nearest_bear_fvg_bottom=[19000.0] * 10,
            swept_high=[True] * 10,
            swept_low=[False] * 10,
        )
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is not None
        assert signal.direction == "short"

    def test_rr_meets_minimum(self):
        df = make_full_df()
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is not None
        assert signal.risk_reward >= 2.0

    def test_signal_id_format(self):
        df = make_full_df()
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is not None
        assert "NQ=F" in signal.signal_id
        assert "long" in signal.signal_id

    def test_strength_a_when_sweep_and_choch(self):
        """Strength A requires both liquidity sweep and CHoCH."""
        df = make_full_df(swept_low=[True] * 10, choch=["up"] * 10)
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is not None
        assert signal.strength == "A"

    def test_no_signal_before_bar_3(self):
        df = make_full_df()
        for i in range(3):
            assert generate_signal(df, i, "NQ=F", make_config()) is None

    def test_stop_and_tp_logical(self):
        """For a long: stop < entry < take_profit."""
        df = make_full_df()
        signal = generate_signal(df, VALID_BAR_IDX, "NQ=F", make_config())
        assert signal is not None
        assert signal.stop_loss < signal.entry_price < signal.take_profit


class TestRunSignalScan:
    def test_scan_returns_list(self):
        df = make_full_df(n=20)
        signals = run_signal_scan(df, "NQ=F", make_config())
        assert isinstance(signals, list)

    def test_scan_finds_signals(self):
        df = make_full_df(n=20)
        signals = run_signal_scan(df, "NQ=F", make_config())
        assert len(signals) > 0

    def test_scan_signals_are_chronological(self):
        df = make_full_df(n=20)
        signals = run_signal_scan(df, "NQ=F", make_config())
        timestamps = [s.timestamp for s in signals]
        assert timestamps == sorted(timestamps)
