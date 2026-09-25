"""`discord-hq hook`: the Claude Code `Notification` / `Stop` hook.

It decides whether the session is a kitchen session and what happened
(approval needed, idle, stopped, ready with a PR), then hands the event to
the sinks (macOS notification, Discord webhook).

Hook contract, tested: it never raises out of `hook_main`, never writes to
stdout, always exits 0, and every subprocess or HTTP call has a short timeout.
A bug here must never break the user's Claude Code session.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from discord_hq.config import Settings, load_settings
from discord_hq.notify.sinks import discord as discord_sink
from discord_hq.notify.sinks import macos as macos_sink

SUBPROCESS_TIMEOUT = 3
DEDUP_WINDOW_SECONDS = 60
SUMMARY_LIMIT = 200

NOTIFICATION_TITLES = {
    "permission": "🔐 {project} needs approval",
    "idle": "💬 {project} is waiting for you",
}
STOPPED_TITLE = "⏸️ {project} stopped"
READY_TITLE = "✅ {project} ready"

SINKS = [macos_sink, discord_sink]

_UNSAFE_SLUG_CHARS = re.compile(r"[^A-Za-z0-9._-]")


@dataclass(frozen=True)
class Session:
    slug: str
    worktree: Path


@dataclass(frozen=True)
class Event:
    kind: str  # permission | idle | stopped | ready | stalled | paused
    project: str
    slug: str
    title: str
    message: str
    worktree: Path
    urgent: bool = False


def safe_slug(raw: str) -> str:
    """Slugs end up inside shell commands (attach hint, notification click).
    Folder and tmux session names are not trusted input."""
    return _UNSAFE_SLUG_CHARS.sub("-", raw)[:80] or "session"


def tmux_session_name() -> str | None:
    import os

    if not os.environ.get("TMUX"):
        return None
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"], capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def identify_session(cwd: str, settings: Settings) -> Session | None:
    match = re.search(rf"{re.escape(settings.worktrees_dir_name)}/([^/]+)", cwd)
    if match:
        return Session(slug=safe_slug(match.group(1)), worktree=Path(cwd[: match.end()]))

    name = tmux_session_name()
    if name and name.startswith(settings.session_prefix):
        return Session(slug=safe_slug(name[len(settings.session_prefix) :]), worktree=Path(cwd))
    return None


def repo_root(cwd: str) -> Path | None:
    """The main checkout of the project, also from inside a worktree:
    `--git-common-dir` points at the shared .git, whose parent is the main
    checkout (where the batch manifests live)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT,
            cwd=cwd,
        )
        if result.returncode != 0:
            return None
        git_dir = Path(result.stdout.strip())
        # A real worktree returns an absolute path; a plain subfolder returns
        # one relative to the GIT process cwd, not to this Python process.
        if not git_dir.is_absolute():
            git_dir = Path(cwd) / git_dir
        git_dir = git_dir.resolve()
        return git_dir.parent if git_dir.name == ".git" else git_dir
    except Exception:
        return None


def project_name(cwd: str) -> str:
    root = repo_root(cwd)
    return root.name if root else "project"


def pr_url(worktree: Path, settings: Settings) -> str | None:
    try:
        result = subprocess.run(
            [*settings.gh_command, "pr", "view", "--json", "url", "-q", ".url"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(worktree),
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def last_message_summary(payload: dict, transcript_path: str, limit: int = SUMMARY_LIMIT) -> str:
    direct = payload.get("last_assistant_message")
    if direct:
        return direct[:limit]

    path = Path(transcript_path)
    if not path.exists():
        return ""
    last = ""
    try:
        with path.open() as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") != "assistant":
                    continue
                content = record.get("message", {}).get("content", [])
                if isinstance(content, str):
                    if content.strip():
                        last = content.strip()
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                        last = block["text"].strip()
    except Exception:
        return last[:limit]
    return last[:limit]


def _notification_event(payload: dict, session: Session, project: str) -> Event | None:
    notification_type = payload.get("notification_type")
    raw = payload.get("message", "")
    if notification_type == "permission_prompt":
        kind = "permission"
    elif notification_type == "idle_prompt":
        kind = "idle"
    elif notification_type:
        return None
    elif "permission" in raw.lower() or "approval" in raw.lower():
        kind = "permission"
    elif raw:
        kind = "idle"
    else:
        return None
    return Event(
        kind=kind,
        project=project,
        slug=session.slug,
        title=NOTIFICATION_TITLES[kind].format(project=project),
        message=raw,
        worktree=session.worktree,
        urgent=kind == "permission",
    )


def _stop_event(payload: dict, session: Session, project: str, settings: Settings) -> Event | None:
    if payload.get("stop_hook_active"):
        return None
    if (session.worktree / settings.marker_dir_name / "done").exists():
        return Event(
            kind="ready",
            project=project,
            slug=session.slug,
            title=READY_TITLE.format(project=project),
            message=pr_url(session.worktree, settings) or "PR not found",
            worktree=session.worktree,
        )
    return Event(
        kind="stopped",
        project=project,
        slug=session.slug,
        title=STOPPED_TITLE.format(project=project),
        message=last_message_summary(payload, payload.get("transcript_path", "")),
        worktree=session.worktree,
    )


def build_event(payload: dict, session: Session, project: str, settings: Settings) -> Event | None:
    name = payload.get("hook_event_name")
    if name == "Notification":
        return _notification_event(payload, session, project)
    if name == "Stop":
        return _stop_event(payload, session, project, settings)
    return None


def dedupe(worktree: Path, kind: str, settings: Settings) -> bool:
    """True when this alert should go out (not sent in the last minute)."""
    marker = worktree / settings.marker_dir_name / "last-alert"
    now = time.time()
    records = {}
    if marker.exists():
        try:
            records = json.loads(marker.read_text())
        except Exception:
            records = {}
    last = records.get(kind)
    if last is not None and (now - last) < DEDUP_WINDOW_SECONDS:
        return False
    records[kind] = now
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(records))
    except Exception:
        pass
    return True


def dispatch(event: Event, settings: Settings) -> None:
    for sink in SINKS:
        try:
            sink.notify(event, settings)
        except Exception:
            pass


def hook_main(settings: Settings | None = None) -> int:
    try:
        if settings is None:
            settings = load_settings()
        payload = json.loads(sys.stdin.read())
        cwd = payload.get("cwd", "")
        session = identify_session(cwd, settings)
        if session is None:
            return 0
        event = build_event(payload, session, project_name(cwd), settings)
        if event is None or not dedupe(session.worktree, event.kind, settings):
            return 0
        dispatch(event, settings)
    except Exception:
        pass
    return 0
