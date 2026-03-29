"""
conftest.py — pytest configuration for the trading_bot package.

Adds the trading_bot/ directory to sys.path so that all test files can
import strategy, risk, execution, etc. as top-level packages regardless
of the working directory pytest is invoked from.
"""
import sys
from pathlib import Path

# Ensure trading_bot/ is on the path (idempotent)
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
