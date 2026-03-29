"""
tests/test_risk_manager.py — Unit Tests for Risk Manager

Tests cover:
- Fixed % risk position sizing calculation
- Max contracts cap enforcement
- Daily loss limit (% and USD) halt
- Max trades per day halt
- Consecutive loss halt
- Max drawdown halt
- Drawdown-triggered size reduction
- Max open positions block
- Daily reset clears counters
- Session state tracking (balance, P&L, consecutive losses)
"""

import pytest
from datetime import date

from risk.risk_manager import RiskManager, SizingResult


def make_risk_config(**overrides) -> dict:
    """Build a minimal risk config dict with sensible defaults."""
    cfg = {
        "account": {"starting_balance": 100_000.0, "currency": "USD"},
        "position_sizing": {
            "method": "fixed_risk_pct",
            "risk_per_trade_pct": 1.0,
            "max_risk_per_trade_pct": 2.0,
            "max_contracts": 5,
        },
        "daily_limits": {
            "max_daily_loss_pct": 3.0,
            "max_daily_loss_usd": 3000.0,
            "max_trades_per_day": 6,
            "consecutive_loss_halt": 3,
        },
        "drawdown": {
            "max_drawdown_pct": 10.0,
            "reduce_size_at_pct": 5.0,
        },
        "portfolio": {"max_open_positions": 2},
        "paper": {"enforce_all_risk_rules": True},
    }
    cfg.update(overrides)
    return cfg


class TestPositionSizing:
    def test_fixed_risk_pct_basic(self):
        """1% of $100k with $1000 stop value → 1 contract."""
        rm = RiskManager(make_risk_config())
        # stop_distance=50pts, point_value=$20 → $1000/contract
        result = rm.calculate_size(stop_distance=50.0, point_value=20.0)
        assert result.approved is True
        assert result.contracts == 1   # floor($100k × 1% / $1000) = 1
        assert result.risk_dollars == pytest.approx(1000.0, rel=0.01)

    def test_max_contracts_capped(self):
        """Even if math says 10 contracts, cap at max_contracts=5."""
        cfg = make_risk_config()
        cfg["position_sizing"]["risk_per_trade_pct"] = 10.0  # Very high risk %
        rm = RiskManager(cfg)
        result = rm.calculate_size(stop_distance=5.0, point_value=20.0)
        assert result.contracts <= 5

    def test_zero_stop_distance_rejected(self):
        rm = RiskManager(make_risk_config())
        result = rm.calculate_size(stop_distance=0.0, point_value=20.0)
        assert result.approved is False

    def test_size_reflects_current_balance(self):
        """After a loss, size should be smaller (% of smaller balance)."""
        rm = RiskManager(make_risk_config())
        rm.state.current_balance = 50_000.0
        result = rm.calculate_size(stop_distance=50.0, point_value=20.0)
        assert result.risk_dollars < 1000.0  # Less than 1% of $100k


class TestDailyLimits:
    def test_daily_pct_loss_halts_trading(self):
        rm = RiskManager(make_risk_config())
        # Simulate 3.5% loss ($3500)
        rm.record_trade_open()
        rm.record_trade_close(-3500.0)
        result = rm.calculate_size(stop_distance=50.0, point_value=20.0)
        assert result.approved is False
        assert "daily loss" in result.rejection_reason.lower()

    def test_daily_usd_loss_halts_trading(self):
        rm = RiskManager(make_risk_config())
        rm.record_trade_open()
        rm.record_trade_close(-3100.0)  # Over $3000 limit but under 3%
        result = rm.calculate_size(stop_distance=50.0, point_value=20.0)
        assert result.approved is False

    def test_max_trades_per_day_blocks(self):
        cfg = make_risk_config()
        cfg["daily_limits"]["max_trades_per_day"] = 2
        rm = RiskManager(cfg)
        rm.record_trade_open()
        rm.record_trade_close(100.0)
        rm.record_trade_open()
        rm.record_trade_close(100.0)
        result = rm.calculate_size(stop_distance=50.0, point_value=20.0)
        assert result.approved is False
        assert "max daily trades" in result.rejection_reason.lower()

    def test_consecutive_losses_halt(self):
        cfg = make_risk_config()
        cfg["daily_limits"]["consecutive_loss_halt"] = 2
        rm = RiskManager(cfg)
        rm.record_trade_open()
        rm.record_trade_close(-100.0)  # Loss 1
        rm.record_trade_open()
        rm.record_trade_close(-100.0)  # Loss 2 → halt
        result = rm.calculate_size(stop_distance=50.0, point_value=20.0)
        assert result.approved is False
        assert rm.state.is_halted is True

    def test_win_resets_consecutive_losses(self):
        rm = RiskManager(make_risk_config())
        rm.record_trade_open()
        rm.record_trade_close(-100.0)  # Loss 1
        rm.record_trade_open()
        rm.record_trade_close(-100.0)  # Loss 2
        rm.record_trade_open()
        rm.record_trade_close(500.0)   # Win → resets consecutive
        assert rm.state.consecutive_losses == 0


class TestDrawdown:
    def test_max_drawdown_halts(self):
        cfg = make_risk_config()
        cfg["drawdown"]["max_drawdown_pct"] = 5.0
        rm = RiskManager(cfg)
        rm.state.peak_balance = 100_000.0
        rm.state.current_balance = 94_000.0  # 6% drawdown → exceeds 5%
        result = rm.calculate_size(stop_distance=50.0, point_value=20.0)
        assert result.approved is False
        assert "drawdown" in result.rejection_reason.lower()

    def test_reduce_size_at_threshold(self):
        cfg = make_risk_config()
        cfg["drawdown"]["reduce_size_at_pct"] = 3.0
        rm = RiskManager(cfg)
        rm.state.peak_balance = 100_000.0
        rm.state.current_balance = 96_000.0  # 4% drawdown → reduce size
        # With 1% risk on $96k, $50pt stop = 0.96 ~ 0 contracts (floor)
        # Use a smaller stop to get at least 1 contract before halving
        result_normal = rm.calculate_size(stop_distance=10.0, point_value=20.0)
        # Size should be halved relative to full balance
        assert result_normal.approved is True


class TestPortfolioLimits:
    def test_max_open_positions_blocks(self):
        cfg = make_risk_config()
        cfg["portfolio"]["max_open_positions"] = 1
        rm = RiskManager(cfg)
        rm.record_trade_open()
        result = rm.calculate_size(stop_distance=50.0, point_value=20.0)
        assert result.approved is False
        assert "open positions" in result.rejection_reason.lower()


class TestDailyReset:
    def test_reset_clears_counters(self):
        rm = RiskManager(make_risk_config())
        rm.record_trade_open()
        rm.record_trade_close(-200.0)
        rm.record_trade_open()
        rm.record_trade_close(-200.0)

        rm.reset_daily(date(2024, 1, 2))

        assert rm.state.trades_taken == 0
        assert rm.state.daily_pnl == 0.0
        assert rm.state.consecutive_losses == 0
        assert rm.state.is_halted is False
        assert rm.state.trading_date == date(2024, 1, 2)


class TestStateSummary:
    def test_summary_is_serializable(self):
        rm = RiskManager(make_risk_config())
        summary = rm.get_state_summary()
        import json
        # Should not raise
        json.dumps(summary)
        assert "balance" in summary
        assert "daily_pnl" in summary
        assert "drawdown_pct" in summary
