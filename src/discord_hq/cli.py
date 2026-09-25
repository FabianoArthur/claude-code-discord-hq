"""`discord-hq` command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from discord_hq import __version__
from discord_hq.config import ConfigError, Settings, load_settings
from discord_hq.notify import events, watchdog
from discord_hq.server import access, apply
from discord_hq.server.design import DesignError, load_design
from discord_hq.server.state import load_state


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="discord-hq",
        description="Discord server as code, plus Claude Code notifications.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    design_help = "design file (default: $DISCORD_HQ_DESIGN or ./design.toml)"
    plan = sub.add_parser("plan", help="show what apply would change (read-only)")
    plan.add_argument("--design", type=Path, help=design_help)

    run = sub.add_parser("apply", help="apply the design to the server")
    run.add_argument("--design", type=Path, help=design_help)
    run.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    run.add_argument("--allow-delete", action="store_true", help="also run the deletions listed in [cleanup]")

    audit = sub.add_parser("audit-forum", help="list the posts of a forum (read-only), before moving it")
    audit.add_argument("channel_id")

    acc = sub.add_parser("access", help="print the Discord plugin commands for one bot (never edits anything)")
    acc.add_argument("--bot", required=True, help="bot name as used in answered_by")
    acc.add_argument("--design", type=Path, help=design_help)

    sub.add_parser("hook", help="Claude Code Notification/Stop hook (reads the event on stdin)")
    sub.add_parser("watch", help="one watchdog pass: stalled sessions, paused units, live panel")
    return parser


def _printable(text: str) -> str:
    """Post names are typed by any server member: drop control characters
    (terminal escapes, newlines) before they reach the terminal."""
    return "".join(ch if ch.isprintable() else " " for ch in text)


def _design_path(args, settings: Settings) -> Path:
    return args.design or settings.design_path or Path("design.toml")


def _access(args, settings: Settings) -> int:
    design_path = _design_path(args, settings)
    try:
        design = load_design(design_path)
    except DesignError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    known = access.bots_in(design)
    if args.bot not in known:
        print(
            f"error: no channel is answered_by {args.bot!r}; bots in this design: {', '.join(known) or 'none'}",
            file=sys.stderr,
        )
        return 2
    state = load_state(apply.state_path_for(settings, design_path))
    commands, missing = access.access_commands(design, state, args.bot)
    if missing:
        print(f"warning: channel ids unknown for {', '.join(missing)}; run `discord-hq apply` first.", file=sys.stderr)
    if not commands:
        return 1
    print(f"# Type these in the Claude Code session that runs the {args.bot!r} bot (never from a Discord message):")
    for command in commands:
        print(command)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    # The hook and the watchdog load settings themselves and never fail loudly.
    if args.command == "hook":
        return events.hook_main()
    if args.command == "watch":
        return watchdog.main()
    if args.command is None:
        parser.print_usage(sys.stderr)
        return 2

    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "plan":
        return apply.run(settings, _design_path(args, settings), mode="plan")
    if args.command == "apply":
        return apply.run(
            settings, _design_path(args, settings), mode="apply", yes=args.yes, allow_delete=args.allow_delete
        )
    if args.command == "access":
        return _access(args, settings)
    if args.command == "audit-forum":
        try:
            client = apply.DiscordClient(settings.require("admin_token"))
            result = apply.audit_forum(client, settings.require("guild_id"), args.channel_id)
        except ConfigError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"{result['total']} post(s) in {args.channel_id}:")
        for name in result["names"]:
            print(f"- {_printable(name)}")
        return 0
    return 2
