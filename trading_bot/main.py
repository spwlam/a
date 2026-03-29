"""
main.py — ICT + Strat Trading Bot Entry Point

Modes:
    backtest   : Run walk-forward backtest on historical data
    paper      : Run paper trading session (live data, simulated orders)
    signals    : Scan historical data and print signals without executing trades

Usage:
    python main.py backtest --symbol NQ=F --start 2024-01-01 --end 2024-12-31
    python main.py paper    --symbol NQ=F
    python main.py signals  --symbol NQ=F --start 2024-01-01 --end 2024-12-31

Configuration:
    All parameters are loaded from trading_bot/config/settings.yaml and risk_config.yaml.
    Do not hardcode values here — modify the YAML files instead.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml
from loguru import logger


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(config: dict) -> None:
    log_cfg = config.get("logging", {})
    log_dir = Path(log_cfg.get("log_dir", "logs/"))
    log_dir.mkdir(parents=True, exist_ok=True)

    level = log_cfg.get("level", "INFO")
    fmt = log_cfg.get("format", "text")

    # Remove default loguru handler
    logger.remove()

    if fmt == "json":
        logger.add(
            log_dir / "trading_bot_{time:YYYY-MM-DD}.log",
            level=level,
            rotation=log_cfg.get("rotate_size", "10 MB"),
            retention=log_cfg.get("retention", "30 days"),
            serialize=True,
        )
    else:
        logger.add(
            log_dir / "trading_bot_{time:YYYY-MM-DD}.log",
            level=level,
            rotation=log_cfg.get("rotate_size", "10 MB"),
            retention=log_cfg.get("retention", "30 days"),
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}",
        )

    # Also log to stderr at INFO level
    logger.add(sys.stderr, level="INFO", colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_configs() -> tuple[dict, dict]:
    config_dir = Path(__file__).parent / "config"
    with open(config_dir / "settings.yaml") as f:
        settings = yaml.safe_load(f)
    with open(config_dir / "risk_config.yaml") as f:
        risk_config = yaml.safe_load(f)
    return settings, risk_config


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------

def run_backtest(symbol: str, start: str, end: str, settings: dict, risk_config: dict) -> None:
    """Run a full walk-forward backtest and print results."""
    from data.ingestion import fetch_ohlcv
    from strategy.strat_classifier import classify_dataframe
    from strategy.strat_patterns import detect_patterns
    from strategy.ict_structure import find_swing_highs_lows, annotate_structure
    from strategy.ict_fvg import detect_fvgs, update_mitigation, annotate_fvgs
    from strategy.ict_levels import annotate_all_levels
    from strategy.ict_context import compute_bias, align_htf_bias_to_ltf
    from strategy.filters import apply_all_filters
    from backtesting.backtest_engine import BacktestEngine
    from backtesting.results_analyzer import ResultsAnalyzer

    tf = settings["trading"]["primary_timeframe"]
    htf = settings["trading"]["htf_timeframe"]

    logger.info("Fetching LTF data: {} {} {} → {}", symbol, tf, start, end)
    df_ltf = fetch_ohlcv(symbol, tf, start, end)

    logger.info("Fetching HTF data: {} {}", symbol, htf)
    df_htf = fetch_ohlcv(symbol, htf, start, end)

    # Annotate HTF
    df_htf = find_swing_highs_lows(df_htf, lookback=settings["ict"]["structure"]["swing_lookback"])
    df_htf = annotate_structure(
        df_htf,
        displacement_atr_mult=settings["ict"]["structure"]["displacement_atr_mult"],
        bos_confirmation=settings["ict"]["structure"]["bos_confirmation"],
    )
    df_htf = compute_bias(df_htf)

    # Annotate LTF
    df_ltf = classify_dataframe(df_ltf)
    df_ltf = detect_patterns(df_ltf)
    df_ltf = find_swing_highs_lows(df_ltf, lookback=settings["ict"]["structure"]["swing_lookback"])
    df_ltf = annotate_structure(df_ltf)
    fvgs = detect_fvgs(df_ltf, min_gap_pct=settings["ict"]["fvg"]["min_gap_pct"])
    fvgs = update_mitigation(fvgs, df_ltf)
    df_ltf = annotate_fvgs(df_ltf, fvgs)
    df_ltf = annotate_all_levels(df_ltf)
    df_ltf = align_htf_bias_to_ltf(df_ltf, df_htf)
    df_ltf = apply_all_filters(df_ltf, settings)

    engine = BacktestEngine(settings=settings, risk_config=risk_config)
    result = engine.run(df_ltf, symbol=symbol, timeframe=tf, start_date=start, end_date=end)

    analyzer = ResultsAnalyzer(result)
    report = analyzer.compute_report()
    analyzer.print_summary(report)


def run_signals(symbol: str, start: str, end: str, settings: dict, risk_config: dict) -> None:
    """Print all generated signals without executing trades."""
    logger.info("Signal scan mode — no orders will be placed")
    # Reuse backtest annotation pipeline but skip execution
    # (Deferred to next implementation stage)
    logger.warning("Signal scan mode not yet fully implemented. Run backtest mode instead.")


def run_paper(symbol: str, settings: dict, risk_config: dict) -> None:
    """Start a live paper trading session."""
    logger.info("Paper trading mode — simulated orders only")
    logger.warning("Paper trading live mode not yet implemented. Use backtest mode first.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="ICT + Strat Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)

    # Backtest
    bt = subparsers.add_parser("backtest", help="Run walk-forward backtest")
    bt.add_argument("--symbol", required=True, help="Symbol, e.g. NQ=F")
    bt.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    bt.add_argument("--end", required=True, help="End date YYYY-MM-DD")

    # Paper
    paper = subparsers.add_parser("paper", help="Run paper trading session")
    paper.add_argument("--symbol", required=True, help="Symbol, e.g. NQ=F")

    # Signals
    sig = subparsers.add_parser("signals", help="Scan and print signals only")
    sig.add_argument("--symbol", required=True, help="Symbol, e.g. NQ=F")
    sig.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    sig.add_argument("--end", required=True, help="End date YYYY-MM-DD")

    args = parser.parse_args()
    settings, risk_config = load_configs()
    setup_logging(settings)

    logger.info("ICT+Strat Trading Bot starting | mode={} | symbol={}", args.mode, args.symbol)

    if args.mode == "backtest":
        run_backtest(args.symbol, args.start, args.end, settings, risk_config)
    elif args.mode == "paper":
        run_paper(args.symbol, settings, risk_config)
    elif args.mode == "signals":
        run_signals(args.symbol, args.start, args.end, settings, risk_config)


if __name__ == "__main__":
    main()
