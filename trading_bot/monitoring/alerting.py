"""
monitoring/alerting.py — Alert Dispatch System

Responsibilities:
- Dispatch structured alerts when significant trading events occur
- Support multiple alert channels: terminal print, file log, future: Slack/email
- Provide a simple event-type filter so only relevant alerts are dispatched

Alert event types:
    NEW_SIGNAL     : A trade signal was generated
    TRADE_FILLED   : A position was opened
    TRADE_CLOSED   : A position was closed (with P&L)
    TRADE_REJECTED : A signal was rejected (with reason)
    DAILY_LIMIT    : Daily loss or trade limit hit
    SESSION_HALT   : Trading halted for the session
    DRAWDOWN_ALERT : Drawdown threshold crossed

Usage:
    alerter = Alerter(channels=["terminal", "file"], log_path="logs/alerts.log")
    alerter.send(AlertEvent.NEW_SIGNAL, "Long NQ @ 19250 | R:R 3.1 | Strength A")
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AlertEvent(str, Enum):
    NEW_SIGNAL = "NEW_SIGNAL"
    TRADE_FILLED = "TRADE_FILLED"
    TRADE_CLOSED = "TRADE_CLOSED"
    TRADE_REJECTED = "TRADE_REJECTED"
    DAILY_LIMIT = "DAILY_LIMIT"
    SESSION_HALT = "SESSION_HALT"
    DRAWDOWN_ALERT = "DRAWDOWN_ALERT"
    INFO = "INFO"


# Severity mapping for terminal color coding
_EVENT_COLORS = {
    AlertEvent.NEW_SIGNAL:     "cyan",
    AlertEvent.TRADE_FILLED:   "green",
    AlertEvent.TRADE_CLOSED:   "bold green",
    AlertEvent.TRADE_REJECTED: "yellow",
    AlertEvent.DAILY_LIMIT:    "bold red",
    AlertEvent.SESSION_HALT:   "bold red",
    AlertEvent.DRAWDOWN_ALERT: "red",
    AlertEvent.INFO:           "white",
}


class Alerter:
    """
    Dispatches structured alerts to configured channels.

    Supported channels:
        "terminal" : Print to stdout using Rich (or plain print as fallback)
        "file"     : Append to a plain-text log file
        (future)   : "slack", "email", "webhook"
    """

    def __init__(
        self,
        channels: Optional[list[str]] = None,
        log_path: str = "logs/alerts.log",
        enabled_events: Optional[list[AlertEvent]] = None,
    ) -> None:
        self.channels = channels or ["terminal"]
        self.log_path = log_path
        # If None, all event types are enabled
        self.enabled_events = set(enabled_events) if enabled_events else None
        self._history: list[dict] = []

    def send(
        self,
        event: AlertEvent,
        message: str,
        context: Optional[dict] = None,
    ) -> None:
        """
        Dispatch an alert to all configured channels.

        Parameters
        ----------
        event   : AlertEvent type
        message : Human-readable alert message
        context : Optional dict of structured data for programmatic consumers
        """
        if self.enabled_events and event not in self.enabled_events:
            return

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        formatted = f"[{timestamp}] [{event.value}] {message}"

        entry = {
            "timestamp": timestamp,
            "event": event.value,
            "message": message,
            "context": context or {},
        }
        self._history.append(entry)

        for channel in self.channels:
            if channel == "terminal":
                self._send_terminal(event, formatted)
            elif channel == "file":
                self._send_file(formatted)
            else:
                logger.warning("Unknown alert channel: %s", channel)

    def get_history(self, event_type: Optional[AlertEvent] = None) -> list[dict]:
        """Return alert history, optionally filtered by event type."""
        if event_type:
            return [e for e in self._history if e["event"] == event_type.value]
        return list(self._history)

    # ------------------------------------------------------------------
    # Channel implementations
    # ------------------------------------------------------------------

    def _send_terminal(self, event: AlertEvent, formatted: str) -> None:
        try:
            from rich.console import Console
            console = Console()
            color = _EVENT_COLORS.get(event, "white")
            console.print(f"[{color}]{formatted}[/{color}]")
        except ImportError:
            print(formatted)

    def _send_file(self, formatted: str) -> None:
        try:
            Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(formatted + "\n")
        except OSError as e:
            logger.error("Failed to write alert to file %s: %s", self.log_path, e)
