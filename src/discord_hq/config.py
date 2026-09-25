"""Runtime settings: process environment first, then a `.env` file in the
config directory, then built-in defaults.

Nothing personal is hardcoded anywhere else in the package: every id, path,
token and naming convention flows through `Settings`. Error messages name the
offending variable but never echo its value (it may be a secret).
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "claude-code-discord-hq"

# Settings field -> environment variable. `.env.example` must document all of
# them (enforced by a test).
ENV_VARS = {
    "admin_token": "DISCORD_HQ_ADMIN_TOKEN",
    "guild_id": "DISCORD_HQ_GUILD_ID",
    "design_path": "DISCORD_HQ_DESIGN",
    "state_path": "DISCORD_HQ_STATE",
    "mention_user_id": "DISCORD_HQ_MENTION_USER_ID",
    "webhook_ready": "DISCORD_HQ_WEBHOOK_READY",
    "webhook_alert": "DISCORD_HQ_WEBHOOK_ALERT",
    "webhook_panel": "DISCORD_HQ_WEBHOOK_PANEL",
    "session_prefix": "DISCORD_HQ_SESSION_PREFIX",
    "worktrees_dir_name": "DISCORD_HQ_WORKTREES_DIR",
    "marker_dir_name": "DISCORD_HQ_MARKER_DIR",
    "manifest_glob": "DISCORD_HQ_MANIFEST_GLOB",
    "stall_minutes": "DISCORD_HQ_STALL_MINUTES",
    "gh_command": "DISCORD_HQ_GH",
    "click_command": "DISCORD_HQ_CLICK_COMMAND",
    "config_dir": "DISCORD_HQ_CONFIG_DIR",
}

DEFAULT_STALL_MINUTES = 10


class ConfigError(ValueError):
    """A required setting is missing or malformed."""


@dataclass(frozen=True)
class Settings:
    config_dir: Path
    claude_projects_dir: Path
    admin_token: str | None = None
    guild_id: str | None = None
    design_path: Path | None = None
    state_path: Path | None = None
    mention_user_id: str | None = None
    webhook_ready: str = "Pass"
    webhook_alert: str = "Bell"
    webhook_panel: str = "Panel"
    session_prefix: str = "kitchen-"
    worktrees_dir_name: str = ".worktrees"
    marker_dir_name: str = ".kitchen"
    manifest_glob: str = "docs/plans/*-manifest.md"
    stall_minutes: int = DEFAULT_STALL_MINUTES
    gh_command: tuple[str, ...] = ("gh",)
    click_command: str = "open -a Terminal"

    @property
    def webhooks_path(self) -> Path:
        return self.config_dir / "webhooks.json"

    @property
    def panel_path(self) -> Path:
        return self.config_dir / "panel.json"

    @property
    def finished_sessions_path(self) -> Path:
        return self.config_dir / "panel-finished.json"

    def attach_command(self, slug: str) -> str:
        return f"tmux attach -t '={self.session_prefix}{slug}'"

    def require(self, field: str):
        value = getattr(self, field)
        if value in (None, ""):
            raise ConfigError(f"{ENV_VARS[field]} is not set (environment or {self.config_dir / '.env'})")
        return value


def parse_dotenv(text: str) -> dict[str, str]:
    """Minimal KEY=VALUE parser: comments, blank lines, `export ` prefixes and
    matching quotes. Anything else is ignored rather than guessed at."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _config_dir(environ: Mapping[str, str]) -> Path:
    explicit = environ.get(ENV_VARS["config_dir"])
    if explicit:
        return Path(explicit).expanduser()
    home = Path(environ.get("HOME") or Path.home())
    xdg = environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else home / ".config"
    return base / APP_NAME


def _snowflake(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not value.isdigit():
        raise ConfigError(f"{name} must be a numeric Discord id")
    return value


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    environ = dict(os.environ if environ is None else environ)
    config_dir = _config_dir(environ)

    merged: dict[str, str] = {}
    dotenv = config_dir / ".env"
    try:
        merged.update(parse_dotenv(dotenv.read_text()))
    except OSError:
        pass
    merged.update(environ)

    def get(field: str) -> str | None:
        value = merged.get(ENV_VARS[field])
        if value is None:
            return None
        value = value.strip()
        return value or None

    home = Path(environ.get("HOME") or Path.home())
    claude_dir = (
        Path(environ["CLAUDE_CONFIG_DIR"]).expanduser() if environ.get("CLAUDE_CONFIG_DIR") else home / ".claude"
    )

    kwargs: dict = {}
    for field in (
        "webhook_ready",
        "webhook_alert",
        "webhook_panel",
        "worktrees_dir_name",
        "marker_dir_name",
        "manifest_glob",
        "click_command",
        "admin_token",
    ):
        value = get(field)
        if value is not None:
            kwargs[field] = value

    prefix = merged.get(ENV_VARS["session_prefix"])
    if prefix is not None:
        if not prefix.strip():
            raise ConfigError(f"{ENV_VARS['session_prefix']} must not be empty")
        kwargs["session_prefix"] = prefix.strip()

    for field in ("design_path", "state_path"):
        value = get(field)
        if value is not None:
            kwargs[field] = Path(value).expanduser()

    stall = get("stall_minutes")
    if stall is not None:
        try:
            kwargs["stall_minutes"] = max(1, int(stall))
        except ValueError:
            kwargs["stall_minutes"] = DEFAULT_STALL_MINUTES

    gh = get("gh_command")
    if gh is not None:
        kwargs["gh_command"] = tuple(shlex.split(gh))

    return Settings(
        config_dir=config_dir,
        claude_projects_dir=claude_dir / "projects",
        guild_id=_snowflake(ENV_VARS["guild_id"], get("guild_id")),
        mention_user_id=_snowflake(ENV_VARS["mention_user_id"], get("mention_user_id")),
        **kwargs,
    )
