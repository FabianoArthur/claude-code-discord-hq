"""Live panel: ONE message in the panel channel, edited on every watchdog pass,
with one line per live kitchen session plus the ones finished in the last 24h.

Reuses the watchdog (tmux, transcript, manifest) and the hook helpers
(project name, repo root, PR link), and talks to Discord only through the
panel webhook. Never raises out of `update`; the webhook URL never reaches
output or exceptions.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from discord_hq.config import Settings
from discord_hq.notify import events, watchdog
from discord_hq.notify.sinks.discord import read_webhooks, safe_text

FINISHED_WINDOW_SECONDS = 24 * 3600
DISCORD_LIMIT = 2000
TIMEOUT_SECONDS = 5

EMOJI = {"working": "🔄", "waiting": "⏳", "stalled": "🧊", "ready": "✅", "idle": "💤"}


@dataclass
class SessionInfo:
    slug: str
    project: str
    state: str  # working | waiting | stalled | ready | idle
    reason: str = ""
    pr_url: str | None = None
    minutes: int = 0


def format_line(info: SessionInfo, settings: Settings) -> str:
    if info.state == "waiting":
        reason = safe_text(info.reason)
        text = f"needs you — {reason}" if reason else "needs you"
    elif info.state == "stalled":
        text = f"stalled for {info.minutes} min"
    elif info.state == "ready":
        text = f"ready → {info.pr_url or 'PR: ?'}"
    else:
        text = info.state
    return (
        f"{EMOJI.get(info.state, '❔')} `{info.project}/{info.slug}` — {text} · `{settings.attach_command(info.slug)}`"
    )


def build_text(infos: list[SessionInfo], footer: str, settings: Settings) -> str:
    if not infos:
        return f"_no live sessions._\n\n{footer}"
    lines = [format_line(i, settings) for i in infos]
    full = "\n".join(lines) + f"\n\n{footer}"
    if len(full) <= DISCORD_LIMIT:
        return full

    def render(kept: list[str]) -> str:
        rest = len(lines) - len(kept)
        more = f"\n+{rest} more sessions" if rest > 0 else ""
        return "\n".join(kept) + more + f"\n\n{footer}"

    kept: list[str] = []
    for line in lines:
        if len(render(kept + [line])) > DISCORD_LIMIT:
            break
        kept.append(line)
    return render(kept)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(json.dumps(data))


def _record_finished(slug: str, project: str, pr_url: str | None, settings: Settings) -> None:
    data = _read_json(settings.finished_sessions_path)
    data[slug] = {"project": project, "pr_url": pr_url, "when": time.time()}
    try:
        _write_private(settings.finished_sessions_path, data)
    except Exception:
        pass


def _recent_finished(live_slugs: set, settings: Settings) -> list[SessionInfo]:
    data = _read_json(settings.finished_sessions_path)
    if not data:
        return []
    now = time.time()
    kept: dict = {}
    infos: list[SessionInfo] = []
    for slug, record in data.items():
        if now - record.get("when", 0) > FINISHED_WINDOW_SECONDS:
            continue
        kept[slug] = record
        if slug not in live_slugs:
            infos.append(
                SessionInfo(
                    slug=slug, project=record.get("project", "project"), state="ready", pr_url=record.get("pr_url")
                )
            )
    if len(kept) != len(data):
        try:
            _write_private(settings.finished_sessions_path, kept)
        except Exception:
            pass
    return infos


def collect_sessions(settings: Settings) -> list[SessionInfo]:
    infos: list[SessionInfo] = []
    live: set = set()
    limit = settings.stall_minutes

    for session in watchdog.list_kitchen_sessions(settings):
        slug = events.safe_slug(session[len(settings.session_prefix) :])
        cwd = watchdog.session_cwd(session)
        if not cwd:
            continue
        live.add(slug)
        worktree = Path(cwd)
        project = events.project_name(cwd)

        if (worktree / settings.marker_dir_name / "done").exists():
            pr = events.pr_url(worktree, settings)
            infos.append(SessionInfo(slug=slug, project=project, state="ready", pr_url=pr))
            _record_finished(slug, project, pr, settings)
            continue

        # "stalled" means the same as in the watchdog: working on screen, but
        # the transcript has not moved for `limit` minutes.
        if watchdog.is_working(watchdog.capture_screen(session)):
            transcript = watchdog.latest_transcript(cwd, settings)
            if transcript is not None:
                minutes = int((time.time() - transcript.stat().st_mtime) / 60)
                if minutes >= limit:
                    infos.append(SessionInfo(slug=slug, project=project, state="stalled", minutes=minutes))
                    continue
            infos.append(SessionInfo(slug=slug, project=project, state="working"))
            continue

        root = events.repo_root(cwd)
        result = watchdog.manifest_state(root, slug, settings) if root else None
        if result is not None and result[0] == "waiting":
            infos.append(SessionInfo(slug=slug, project=project, state="waiting", reason=result[1]))
            continue
        infos.append(SessionInfo(slug=slug, project=project, state="idle"))

    return infos + _recent_finished(live, settings)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _state_key(infos: list[SessionInfo]) -> str:
    """Only what a human needs to see change: never the minutes counter (it
    grows every pass) nor the footer clock."""
    return "\n".join(f"{i.slug}|{i.project}|{i.state}|{i.reason}|{i.pr_url}" for i in infos)


def edit_panel(text: str, state_key: str, settings: Settings) -> None:
    url = read_webhooks(settings).get(settings.webhook_panel)
    if not url:
        return
    state_hash = _hash(state_key)
    saved = _read_json(settings.panel_path)
    message_id = saved.get("message_id")
    if message_id and saved.get("state_hash") == state_hash:
        return

    payload = {"content": text, "allowed_mentions": {"parse": []}}
    try:
        if message_id:
            response = requests.patch(f"{url}/messages/{message_id}", json=payload, timeout=TIMEOUT_SECONDS)
            if response.status_code == 404:
                message_id = None  # someone deleted it: post a new one below
            elif not response.ok:
                return  # 429/5xx: keep the old hash, retry next pass
        if not message_id:
            response = requests.post(url, params={"wait": "true"}, json=payload, timeout=TIMEOUT_SECONDS)
            if not response.ok:
                return
            message_id = response.json().get("id")
    except Exception:
        return
    if message_id:
        try:
            _write_private(settings.panel_path, {"message_id": message_id, "state_hash": state_hash})
        except Exception:
            pass


def update(settings: Settings) -> None:
    try:
        infos = collect_sessions(settings)
        edit_panel(build_text(infos, f"updated at {time.strftime('%H:%M')}", settings), _state_key(infos), settings)
    except Exception:
        pass
