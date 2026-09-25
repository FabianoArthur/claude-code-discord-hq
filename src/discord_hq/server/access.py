"""`discord-hq access --bot <name>`: turn each channel's `answered_by` into the
commands the official Claude Code Discord plugin understands.

It only PRINTS `/discord:access group add ...` lines for you to type in the
bot's own Claude Code terminal. It never edits the plugin's access.json: access
changes must come from you, never from anything a channel message could
influence.
"""

from __future__ import annotations

from discord_hq.server.design import Design


def bots_in(design: Design) -> list[str]:
    return sorted({bot for bots in design.answered_by.values() for bot in bots})


def access_commands(design: Design, state: dict, bot: str) -> tuple[list[str], list[str]]:
    """Returns (commands, channel keys whose id is unknown yet)."""
    channel_ids = state.get("channels", {})
    commands: list[str] = []
    missing: list[str] = []
    for (name, category), bots in design.answered_by.items():
        mode = bots.get(bot)
        if mode is None:
            continue
        key = f"{name} ({category})"
        channel_id = channel_ids.get(key)
        if not channel_id:
            missing.append(key)
            continue
        suffix = " --no-mention" if mode == "always" else ""
        commands.append(f"/discord:access group add {channel_id}{suffix}")
    return commands, missing
