"""
data/ingestion.py — Data Fetching and Normalization

Responsibilities:
- Fetch OHLCV data from external sources (CCXT for crypto, yfinance/polygon for equities/futures)
- Normalize all data into a canonical DataFrame schema used throughout the system
- Write raw data to data/raw/ and processed data to data/processed/
- No strategy logic here — pure data plumbing

Canonical schema (column names must match exactly downstream):
    timestamp   : datetime64[ns, UTC]  — bar open time
    open        : float64
    high        : float64
    low         : float64
    close       : float64
    volume      : float64
    symbol      : str
    timeframe   : str

Approximation notes:
- Futures continuous contracts (NQ=F) may have roll gaps — flag but do not remove
- Volume data from some brokers is tick count, not true volume — document source
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).parent / "raw"
PROCESSED_DIR = Path(__file__).parent / "processed"

# Canonical column order enforced on every DataFrame leaving this module
CANONICAL_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]


class DataIngestionError(Exception):
    """Raised when data fetching or normalization fails."""


def fetch_ohlcv(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    source: str = "yfinance",
) -> pd.DataFrame:
    """
    Fetch OHLCV bars for a symbol from the specified source.

    Parameters
    ----------
    symbol    : Ticker string, e.g. "NQ=F", "SPY", "BTC/USDT"
    timeframe : Bar size string, e.g. "1m", "5m", "15m", "1h", "1d"
    start     : ISO date string, e.g. "2024-01-01"
    end       : ISO date string, e.g. "2024-12-31"
    source    : "yfinance" | "ccxt" | "polygon"

    Returns
    -------
    pd.DataFrame with canonical schema, sorted ascending by timestamp.
    """
    logger.info("Fetching %s %s from %s to %s via %s", symbol, timeframe, start, end, source)

    if source == "yfinance":
        return _fetch_yfinance(symbol, timeframe, start, end)
    elif source == "ccxt":
        return _fetch_ccxt(symbol, timeframe, start, end)
    else:
        raise DataIngestionError(f"Unsupported source: {source!r}")


def _fetch_yfinance(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
    """Fetch via yfinance (equities, ETFs, futures continuous contracts)."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise DataIngestionError("yfinance not installed. Run: pip install yfinance") from exc

    interval_map = {
        "1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m",
        "30m": "30m", "1h": "60m", "1d": "1d", "1w": "1wk",
    }
    interval = interval_map.get(timeframe)
    if interval is None:
        raise DataIngestionError(f"Unsupported timeframe for yfinance: {timeframe!r}")

    ticker = yf.Ticker(symbol)
    raw = ticker.history(interval=interval, start=start, end=end, auto_adjust=True)

    if raw.empty:
        raise DataIngestionError(f"No data returned for {symbol} [{timeframe}] {start}–{end}")

    return _normalize(raw, symbol, timeframe, source="yfinance")


def _fetch_ccxt(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
    """
    Fetch via CCXT (crypto exchanges).
    Placeholder — exchange config loaded from settings.yaml in future iteration.
    """
    raise NotImplementedError("CCXT ingestion not yet implemented. Use yfinance for now.")


def _normalize(raw: pd.DataFrame, symbol: str, timeframe: str, source: str) -> pd.DataFrame:
    """
    Convert a raw broker DataFrame into the canonical schema.
    Enforces types, UTC timezone, and column order.
    """
    df = raw.copy()

    # Standardize column names from different sources
    rename_map = {
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    }
    df.rename(columns=rename_map, inplace=True)

    # Ensure timestamp is the index converted to a column
    if df.index.name in ("Datetime", "Date", None):
        df = df.reset_index()
        df.rename(columns={"Datetime": "timestamp", "Date": "timestamp", "index": "timestamp"}, inplace=True)

    # UTC-normalize timestamps
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")

    df["symbol"] = symbol
    df["timeframe"] = timeframe

    # Drop any extra columns, keep only canonical
    available = [c for c in CANONICAL_COLUMNS if c in df.columns]
    missing = [c for c in CANONICAL_COLUMNS if c not in df.columns]
    if missing:
        raise DataIngestionError(f"Missing canonical columns after normalization: {missing}")

    df = df[CANONICAL_COLUMNS].sort_values("timestamp").reset_index(drop=True)

    # Type enforcement
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype("float64")

    _validate(df, symbol, source)
    return df


def _validate(df: pd.DataFrame, symbol: str, source: str) -> None:
    """Run basic sanity checks on normalized data. Logs warnings; does not drop rows."""
    # High >= Low
    bad_hl = df[df["high"] < df["low"]]
    if not bad_hl.empty:
        logger.warning("[%s] %d bars with high < low from %s", symbol, len(bad_hl), source)

    # No negative prices
    for col in ("open", "high", "low", "close"):
        bad = df[df[col] <= 0]
        if not bad.empty:
            logger.warning("[%s] %d bars with %s <= 0 from %s", symbol, len(bad), col, source)

    # Duplicate timestamps
    dupes = df[df["timestamp"].duplicated()]
    if not dupes.empty:
        logger.warning("[%s] %d duplicate timestamps from %s", symbol, len(dupes), source)

    # NaN check
    nulls = df.isnull().sum()
    if nulls.any():
        logger.warning("[%s] NaN values detected from %s: %s", symbol, source, nulls[nulls > 0].to_dict())


def save_raw(df: pd.DataFrame, symbol: str, timeframe: str) -> Path:
    """Persist raw normalized data to data/raw/ as Parquet."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{symbol.replace('/', '_')}_{timeframe}_raw.parquet"
    df.to_parquet(path, index=False)
    logger.info("Saved raw data to %s (%d bars)", path, len(df))
    return path


def save_processed(df: pd.DataFrame, symbol: str, timeframe: str) -> Path:
    """Persist processed/labeled data to data/processed/ as Parquet."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = PROCESSED_DIR / f"{symbol.replace('/', '_')}_{timeframe}_processed.parquet"
    df.to_parquet(path, index=False)
    logger.info("Saved processed data to %s (%d bars)", path, len(df))
    return path


def load_processed(symbol: str, timeframe: str) -> pd.DataFrame:
    """Load processed data from disk. Raises FileNotFoundError if not present."""
    path = PROCESSED_DIR / f"{symbol.replace('/', '_')}_{timeframe}_processed.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No processed data found at {path}. Run ingestion first.")
    df = pd.read_parquet(path)
    logger.info("Loaded processed data from %s (%d bars)", path, len(df))
    return df
