"""
CLI subcommands for monitoring Tony AI.

Provides three subcommands (invoked from main.py / the tony_ai entry-point):
  tony_ai status           — pretty-print current bot state
  tony_ai watch [--log F]  — tail-follow a stream log file
  tony_ai streams          — list all stream log files
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_STATE_DIR = Path.home() / ".tony_ai"
_STATE_FILE = _STATE_DIR / "status.json"
_STREAMS_DIR = _STATE_DIR / "streams"

# ---------------------------------------------------------------------------
# ANSI escape codes  (raw strings, no external library needed)
# ---------------------------------------------------------------------------
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_RED = "\033[31m"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_uptime(started_at: str) -> str:
    """Return a human-readable uptime string like '2h 34m'."""
    try:
        started = datetime.fromisoformat(started_at)
        # If the timestamp is timezone-naive treat it as UTC for comparison.
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = int((now - started).total_seconds())
    except (ValueError, OverflowError):
        return "?"
    h = delta // 3600
    m = (delta % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def _fmt_ago(ts_str: str) -> str:
    """Return a human-readable 'X ago' string."""
    try:
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = int((now - ts).total_seconds())
    except (ValueError, OverflowError):
        return "?"
    h = delta // 3600
    m = (delta % 3600) // 60
    if h > 0:
        return f"{h}h {m}m ago"
    return f"{m}m ago"


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------

def cmd_status() -> None:
    """Read ~/.tony_ai/status.json and pretty-print the bot state."""
    if not _STATE_FILE.exists():
        print(f"{_YELLOW}⚠  Tony AI is not running (no status file found){_RESET}")
        return

    try:
        state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"{_RED}Error reading status file: {exc}{_RESET}")
        return

    pid = state.get("pid", "?")
    started_at = state.get("started_at")
    uptime = _fmt_uptime(started_at) if started_at else "?"
    sessions: dict = state.get("sessions", {})
    ops_count = state.get("ops_count", 0)

    print(f"{_BOLD}{_GREEN}🤖 Tony AI — running (pid {pid}, up {uptime}){_RESET}")
    print("─" * 42)
    print(f"Sessions: {len(sessions)} active")
    print()

    for i, (thread_ts, sess) in enumerate(sessions.items(), start=1):
        model = sess.get("model", "?")
        is_pro: bool = sess.get("is_pro", False)
        status = sess.get("status", "idle")
        current_task: str | None = sess.get("current_task")
        last_activity: str | None = sess.get("last_activity")

        pro_tag = f"  {_CYAN}PRO{_RESET}" if is_pro else ""

        if status == "busy" and current_task:
            status_str = f'{_YELLOW}busy — "{current_task}"{_RESET}'
        elif status == "busy":
            status_str = f"{_YELLOW}busy{_RESET}"
        else:
            ago = _fmt_ago(last_activity) if last_activity else "?"
            status_str = f"{_DIM}idle, last: {ago}{_RESET}"

        print(
            f"  [{i}] Thread: {thread_ts}  "
            f"model={_CYAN}{model}{_RESET}{pro_tag}  "
            f"({status_str})"
        )

    print()
    print(f"Total ops: {_BOLD}{ops_count}{_RESET}")


# ---------------------------------------------------------------------------
# Subcommand: watch
# ---------------------------------------------------------------------------

def cmd_watch(args: list[str]) -> None:
    """Tail-follow a stream log file, or list available logs."""
    log_file: str | None = None
    i = 0
    while i < len(args):
        if args[i] == "--log" and i + 1 < len(args):
            log_file = args[i + 1]
            i += 2
        else:
            i += 1

    if log_file is None:
        # List available log files and exit.
        if not _STREAMS_DIR.exists():
            print(
                f"{_YELLOW}No streams directory found at {_STREAMS_DIR}{_RESET}"
            )
            return
        logs = sorted(_STREAMS_DIR.glob("*.log"))
        if not logs:
            print(f"{_DIM}No stream log files found in {_STREAMS_DIR}{_RESET}")
            return
        print(f"Stream logs in {_STREAMS_DIR}:")
        for log in logs:
            print(f"  {log.name}")
        return

    path = _STREAMS_DIR / log_file
    if not path.exists():
        print(f"{_RED}Log file not found: {path}{_RESET}")
        sys.exit(1)

    print(f"{_DIM}Watching: {path}  (Ctrl+C to exit){_RESET}")
    try:
        with open(path, encoding="utf-8") as fh:
            fh.seek(0)
            while True:
                line = fh.readline()
                if line:
                    print(line, end="", flush=True)
                else:
                    time.sleep(0.2)
    except KeyboardInterrupt:
        print(f"\n{_DIM}Stopped.{_RESET}")


# ---------------------------------------------------------------------------
# Subcommand: streams
# ---------------------------------------------------------------------------

def cmd_streams() -> None:
    """List all stream log files with size and last-modified time."""
    if not _STREAMS_DIR.exists():
        print(
            f"{_YELLOW}No streams directory found at {_STREAMS_DIR}{_RESET}"
        )
        return

    logs = sorted(_STREAMS_DIR.glob("*.log"))
    if not logs:
        print(f"{_DIM}No stream log files found.{_RESET}")
        return

    print(f"Stream logs in {_STREAMS_DIR}:")
    print()
    for log in logs:
        stat = log.stat()
        size_str = f"{stat.st_size:,} bytes"
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        print(
            f"  {_CYAN}{log.name}{_RESET}  "
            f"{_DIM}{size_str}  last modified {mtime}{_RESET}"
        )
