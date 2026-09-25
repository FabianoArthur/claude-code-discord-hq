"""macOS notification sink.

Always copies the tmux attach command to the clipboard (plan B), then uses
terminal-notifier when installed (clicking runs DISCORD_HQ_CLICK_COMMAND),
falling back to osascript (no click action). Does nothing off macOS."""

from __future__ import annotations

import shutil
import subprocess
import sys

SUBPROCESS_TIMEOUT = 5
URGENT_SOUND = "Pop"


def _copy_to_clipboard(text: str) -> None:
    try:
        subprocess.run(["pbcopy"], input=text, text=True, timeout=SUBPROCESS_TIMEOUT)
    except Exception:
        pass


def _applescript_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _via_terminal_notifier(event, message: str, click: str) -> None:
    args = [
        "terminal-notifier",
        "-title", event.title,
        "-subtitle", event.slug,
        "-message", message,
        "-group", f"discord-hq-{event.slug}",
        "-execute", click,
    ]  # fmt: skip
    if event.urgent:
        args += ["-sound", URGENT_SOUND]
    try:
        subprocess.run(args, capture_output=True, timeout=SUBPROCESS_TIMEOUT)
    except Exception:
        pass


def _via_osascript(event, message: str) -> None:
    script = (
        f'display notification "{_applescript_string(message)}" '
        f'with title "{_applescript_string(event.title)}" '
        f'subtitle "{_applescript_string(event.slug)}"'
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=SUBPROCESS_TIMEOUT)
    except Exception:
        pass


def notify(event, settings) -> None:
    if sys.platform != "darwin":
        return
    attach = settings.attach_command(event.slug)
    _copy_to_clipboard(attach)

    body = event.message.strip() if event.message else ""
    message = f"{body}\n(attach command copied)" if body else "(attach command copied)"
    if shutil.which("terminal-notifier"):
        _via_terminal_notifier(event, message, settings.click_command.replace("{attach}", attach))
    else:
        _via_osascript(event, message)
