# ICT + Strat Automated Trading Bot

A modular, production-minded trading system combining **ICT (Inner Circle Trader)** concepts with **The Strat** methodology.

Built for paper trading first. No live trading until backtested results justify it.

---

## Architecture Overview

```
trading_bot/
├── config/          # All tunable parameters (YAML — no magic numbers in code)
├── data/            # OHLCV ingestion and normalization
├── strategy/        # Signal generation pipeline (ICT + Strat)
├── risk/            # Position sizing and hard risk limits
├── execution/       # Paper and live order management
├── backtesting/     # Walk-forward backtest engine + metrics
├── monitoring/      # Trade journal, dashboard, alerts
└── tests/           # Unit tests for every module
```

### Signal Pipeline

Each bar passes through 7 gates before a signal is emitted:

| Gate | Check |
|------|-------|
| 1 | Active ICT kill zone (session filter) |
| 2 | HTF bias alignment (bullish/bearish) |
| 3 | Valid Strat pattern present (2-1-2, 3-1-2, etc.) |
| 4 | ICT structure event (BOS or CHoCH in signal direction) |
| 5 | Price inside an unmitigated Fair Value Gap |
| 6 | Liquidity sweep of PDH/PDL/PWH/PWL (optimal entry) |
| 7 | Minimum R:R ratio met (default 2.0) |

All 7 must pass. Any failure → no trade.

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo>
cd trading_bot
pip install -r requirements.txt
```

### 2. Environment

```bash
cp ../.env.example .env
# Add API keys if needed (not required for yfinance paper trading)
```

### 3. Configure

Edit `config/settings.yaml` to set your symbols, timeframes, and kill zones.
Edit `config/risk_config.yaml` to set your account size and risk limits.

---

## Usage

### Run a backtest

```bash
python main.py backtest --symbol NQ=F --start 2024-01-01 --end 2024-12-31
```

### Scan for signals (no execution)

```bash
python main.py signals --symbol NQ=F --start 2024-01-01 --end 2024-03-31
```

### Paper trading session

```bash
python main.py paper --symbol NQ=F
```

### Run tests

```bash
pytest trading_bot/tests/ -v
pytest trading_bot/tests/ --cov=trading_bot --cov-report=term-missing
```

---

## Key Design Principles

- **No lookahead bias**: every signal uses only `df.iloc[:i+1]`
- **Paper first**: risk rules are enforced identically in paper and live mode
- **Modular**: swap the broker adapter to go live — nothing else changes
- **Logged**: every signal, fill, rejection, and halt is written to JSONL
- **Testable**: every module has a corresponding unit test file

---

## ICT Concepts Implemented

| Concept | Module | Approximation Notes |
|---------|--------|---------------------|
| Fair Value Gap | `ict_fvg.py` | 3-bar imbalance; mitigation tracked bar-by-bar |
| BOS / CHoCH | `ict_structure.py` | Close-confirmation; swing pivots with configurable lookback |
| PDH/PDL, PWH/PWL | `ict_levels.py` | UTC midnight reset; daily/weekly aggregation |
| Equal Highs/Lows | `ict_levels.py` | Proximity % tolerance |
| Liquidity Sweeps | `ict_levels.py` | Wick-through + close-back detection |
| HTF Bias | `ict_context.py` | Structure-based; no COT or intermarket (approximation) |
| Kill Zones | `filters.py` | Time-window based; London + NY Open enabled by default |
| Displacement | `ict_structure.py` | ATR-multiple threshold |

## The Strat Concepts Implemented

| Concept | Module |
|---------|--------|
| Candle types (1, 2u, 2d, 3) | `strat_classifier.py` |
| 2-1-2 pattern (bull/bear) | `strat_patterns.py` |
| 3-1-2 pattern (reversal) | `strat_patterns.py` |
| 2-2 broadening pattern | `strat_patterns.py` |
| Trigger levels | `strat_patterns.py` |

---

## Risk Management

All limits defined in `config/risk_config.yaml`:

- Max risk per trade: 1% (hard ceiling 2%)
- Max daily loss: 3% or $3,000 (whichever first)
- Max trades per day: 6
- Consecutive loss halt: 3 losses
- Max drawdown: 10% (pause trading)
- Position size reduction at 5% drawdown
- Max open positions: 2

**These limits are enforced in paper mode too. No exceptions.**

---

## Roadmap

- [ ] Stage 1: Project structure (this file)
- [ ] Stage 2: Strat classifier + pattern tests
- [ ] Stage 3: ICT structure + FVG implementation
- [ ] Stage 4: Signal engine integration tests
- [ ] Stage 5: Backtesting with real data
- [ ] Stage 6: Paper trading loop
- [ ] Stage 7: Live broker adapter
