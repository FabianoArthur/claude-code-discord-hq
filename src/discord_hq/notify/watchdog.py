"""`discord-hq watch`: one watchdog pass, meant to run every 2 minutes
(LaunchAgent on macOS, cron or a systemd timer on Linux).

A session can hang with the screen saying "esc to interrupt" (the agent thinks
it is working) while its transcript stops moving. That fires no Claude Code
hook, so nothing else would notice. This pass also turns a ⏳ row in a batch
manifest into a "paused" alert, and refreshes the live panel.

Read-only on tmux (`list-sessions`, `capture-pane`, `display-message`): it
never sends keys and never kills a session. `main` never raises and always
returns 0.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from discord_hq.config import Settings, load_settings
from discord_hq.notify import events

WORKING_MARKER = "esc to interrupt"
STALL_MARKER = "stall-alert"
PAUSE_MARKER = "pause-alert"

# Manifest state emoji -> state name. The state cell is the first cell after
# the unit name that starts with one of these.
STATE_EMOJI = [
    ("⏳", "waiting"),
    ("🧊", "stalled"),
    ("✅", "ready"),
    ("🚫", "aborted"),
    ("🔄", "working"),
    ("⏸", "queued"),
]

# launchd runs agents with a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin), so
# Homebrew's tmux and terminal-notifier would silently vanish. The plist sets
# PATH too; this is the second layer.
for _bin in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _bin not in os.environ.get("PATH", "").split(":"):
        os.environ["PATH"] = _bin + ":" + os.environ.get("PATH", "")


def _tmux(*args: str) -> str | None:
    try:
        result = subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=events.SUBPROCESS_TIMEOUT)
    except Exception:
        return None
    return result.stdout if result.returncode == 0 else None


def list_kitchen_sessions(settings: Settings) -> list[str]:
    output = _tmux("list-sessions", "-F", "#{session_name}")
    if not output:
        return []
    return [name for name in output.splitlines() if name.startswith(settings.session_prefix)]


def capture_screen(session: str) -> str:
    # "=name:" is an exact match on the session's active pane; a bare name
    # would prefix-match ("kitchen-a" hitting "kitchen-ab").
    return _tmux("capture-pane", "-p", "-t", f"={session}:") or ""


def session_cwd(session: str) -> str:
    return (_tmux("display-message", "-p", "-t", f"={session}:", "#{pane_current_path}") or "").strip()


def is_working(screen: str) -> bool:
    return WORKING_MARKER in screen


def last_tool_line(screen: str, limit: int = 200) -> str:
    lines = [line.strip() for line in screen.splitlines() if line.strip() and WORKING_MARKER not in line]
    return lines[-1][:limit] if lines else ""


def claude_project_dir(cwd: str, settings: Settings) -> Path:
    """Claude Code stores transcripts under a folder named after the cwd with
    `/` and `.` replaced by `-`."""
    return settings.claude_projects_dir / re.sub(r"[/.]", "-", cwd)


def latest_transcript(cwd: str, settings: Settings) -> Path | None:
    folder = claude_project_dir(cwd, settings)
    if not folder.exists():
        return None
    # A foreground subagent writes to <session>/subagents/*.jsonl and leaves
    # the main transcript untouched: look at both or a busy session looks hung.
    files = list(folder.glob("*.jsonl")) + list(folder.glob("*/subagents/*.jsonl"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _read_marker(worktree: Path, name: str, settings: Settings) -> dict:
    try:
        return json.loads((worktree / settings.marker_dir_name / name).read_text())
    except Exception:
        return {}


def _write_marker(worktree: Path, name: str, data: dict, settings: Settings) -> None:
    marker = worktree / settings.marker_dir_name / name
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(data))
    except Exception:
        pass


def already_alerted_stall(worktree: Path, transcript_mtime: float, settings: Settings) -> bool:
    return _read_marker(worktree, STALL_MARKER, settings).get("transcript_mtime") == transcript_mtime


def record_stall_alert(worktree: Path, transcript_mtime: float, settings: Settings) -> None:
    _write_marker(worktree, STALL_MARKER, {"transcript_mtime": transcript_mtime}, settings)


def check_session(session: str, limit_minutes: int, settings: Settings) -> None:
    screen = capture_screen(session)
    if not is_working(screen):
        return
    cwd = session_cwd(session)
    if not cwd:
        return
    transcript = latest_transcript(cwd, settings)
    if transcript is None:
        return
    mtime = transcript.stat().st_mtime
    minutes = (time.time() - mtime) / 60
    if minutes < limit_minutes:
        return
    worktree = Path(cwd)
    if already_alerted_stall(worktree, mtime, settings):
        return
    slug = events.safe_slug(session[len(settings.session_prefix) :])
    project = events.project_name(cwd)
    event = events.Event(
        kind="stalled",
        project=project,
        slug=slug,
        title=f"🧊 {project}: no progress for {int(minutes)} min",
        message=last_tool_line(screen),
        worktree=worktree,
    )
    events.dispatch(event, settings)
    record_stall_alert(worktree, mtime, settings)


def _manifest_lines(root: Path, settings: Settings) -> list[str]:
    lines: list[str] = []
    # Newest first (manifest names start with a date): if a slug appears in
    # two batches, the first match must be the newest batch.
    for path in sorted(root.glob(settings.manifest_glob), reverse=True):
        try:
            lines += path.read_text().splitlines()
        except Exception:
            continue
    return lines


def manifest_state(root: Path, slug: str, settings: Settings) -> tuple[str, str] | None:
    """(state, reason) of `slug`'s row in the batch manifests, where reason is
    the state cell without its emoji. None when the unit is not listed."""
    for line in _manifest_lines(root, settings):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not cells or cells[0] != slug:
            continue
        for cell in cells[1:]:
            for emoji, name in STATE_EMOJI:
                if cell.startswith(emoji):
                    return (name, cell[len(emoji) :].strip())
        return None
    return None


def already_alerted_pause(worktree: Path, reason: str, settings: Settings) -> bool:
    return _read_marker(worktree, PAUSE_MARKER, settings).get("reason") == reason


def record_pause_alert(worktree: Path, reason: str, settings: Settings) -> None:
    _write_marker(worktree, PAUSE_MARKER, {"reason": reason}, settings)


def clear_pause_alert(worktree: Path, settings: Settings) -> None:
    """Without this, a unit that pauses, resumes and pauses again with the same
    reason (common: "waiting for you") would never alert a second time."""
    try:
        (worktree / settings.marker_dir_name / PAUSE_MARKER).unlink(missing_ok=True)
    except Exception:
        pass


def check_pause(session: str, cwd: str, settings: Settings) -> None:
    """A unit that paused itself (⏳ in its manifest row) alerts even though no
    Claude Code hook fired: nobody asked anything, the file changed."""
    root = events.repo_root(cwd)
    if root is None:
        return
    slug = events.safe_slug(session[len(settings.session_prefix) :])
    worktree = Path(cwd)
    result = manifest_state(root, slug, settings)
    if result is None:
        return
    state, reason = result
    if state != "waiting":
        clear_pause_alert(worktree, settings)
        return
    if already_alerted_pause(worktree, reason, settings):
        return
    project = events.project_name(cwd)
    event = events.Event(
        kind="paused",
        project=project,
        slug=slug,
        title=f"⏳ {project} is waiting for you",
        message=reason,
        worktree=worktree,
        urgent=True,
    )
    events.dispatch(event, settings)
    record_pause_alert(worktree, reason, settings)


def update_panel(settings: Settings) -> None:
    from discord_hq.notify import panel

    panel.update(settings)


def main(settings: Settings | None = None) -> int:
    try:
        if settings is None:
            settings = load_settings()
        for session in list_kitchen_sessions(settings):
            # Independent on purpose: a failing stall check must not skip the
            # pause check of the same session.
            try:
                check_session(session, settings.stall_minutes, settings)
            except Exception:
                pass
            try:
                cwd = session_cwd(session)
                if cwd:
                    check_pause(session, cwd, settings)
            except Exception:
                pass
        try:
            update_panel(settings)
        except Exception:
            pass
    except Exception:
        pass
    return 0
