"""
State tracking for Tony AI.

Writes runtime state to ~/.tony_ai/status.json so that external tools can
inspect the bot without interfering with its operation.  All file I/O is
best-effort: if a write fails the bot continues running normally.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_STATE_DIR = Path.home() / ".tony_ai"
_STATE_FILE = _STATE_DIR / "status.json"


class StateTracker:
    """Thread-safe, fault-tolerant bot-state writer.

    Maintains an in-memory snapshot of the current bot state and persists it
    to ``~/.tony_ai/status.json`` after every mutation.  Disk errors are
    swallowed with a ``WARNING`` log so they can never crash the bot.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "started_at": None,
            "pid": None,
            "sessions": {},
            "ops_count": 0,
        }

    # ------------------------------------------------------------------
    # Public mutators
    # ------------------------------------------------------------------

    def mark_started(self) -> None:
        """Record startup time and PID, reset session map and op counter."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._state["started_at"] = now
            self._state["pid"] = os.getpid()
            self._state["sessions"] = {}
            self._state["ops_count"] = 0
        self.write()

    def session_created(self, thread_ts: str, model: str, is_pro: bool) -> None:
        """Register a newly-created Copilot session."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._state["sessions"][thread_ts] = {
                "model": model,
                "created_at": now,
                "last_activity": now,
                "is_pro": is_pro,
                "status": "idle",
                "current_task": None,
            }
        self.write()

    def session_busy(self, thread_ts: str, task_preview: str) -> None:
        """Mark a session as actively processing a task."""
        with self._lock:
            sess = self._state["sessions"].get(thread_ts)
            if sess is not None:
                sess["status"] = "busy"
                sess["current_task"] = task_preview
        self.write()

    def session_idle(self, thread_ts: str) -> None:
        """Mark a session as idle, refresh last_activity, bump global op count."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            sess = self._state["sessions"].get(thread_ts)
            if sess is not None:
                sess["status"] = "idle"
                sess["current_task"] = None
                sess["last_activity"] = now
            self._state["ops_count"] = self._state.get("ops_count", 0) + 1
        self.write()

    def session_removed(self, thread_ts: str) -> None:
        """Remove a session from the state map."""
        with self._lock:
            self._state["sessions"].pop(thread_ts, None)
        self.write()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def write(self) -> None:
        """Serialise current state to disk (best-effort; never raises)."""
        try:
            _STATE_DIR.mkdir(parents=True, exist_ok=True)
            with self._lock:
                payload = json.dumps(self._state, indent=2)
            _STATE_FILE.write_text(payload, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tony AI state write failed: %s", exc)
