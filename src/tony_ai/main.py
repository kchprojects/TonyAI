from __future__ import annotations

import sys

from tony_ai.slack.bot import start


def main() -> None:
    """Entry point for the Tony AI application.

    Subcommands
    -----------
    tony_ai                 Start the bot (default).
    tony_ai start           Start the bot (explicit).
    tony_ai status          Print current bot state from ~/.tony_ai/status.json.
    tony_ai watch           List available stream log files.
    tony_ai watch --log F   Tail-follow stream log file F in real-time.
    tony_ai streams         List all stream log files with size / mtime.
    """
    args = sys.argv[1:]

    if not args or args[0] == "start":
        start()
        return

    subcommand = args[0]

    if subcommand == "status":
        from tony_ai.monitoring_cli import cmd_status
        cmd_status()

    elif subcommand == "watch":
        from tony_ai.monitoring_cli import cmd_watch
        cmd_watch(args[1:])

    elif subcommand == "streams":
        from tony_ai.monitoring_cli import cmd_streams
        cmd_streams()

    else:
        print(f"Unknown subcommand: {subcommand!r}", file=sys.stderr)
        print(
            "Usage: tony_ai [start|status|watch [--log FILE]|streams]",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

