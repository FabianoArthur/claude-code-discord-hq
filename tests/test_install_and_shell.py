"""The shell pieces: install.sh (always against a temporary HOME), the
LaunchAgent template, and the waiter shortcut (isolated tmux socket)."""

import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "launchd" / "com.claude-code-discord-hq.watch.plist.template"


def _install(tmp_path, *args):
    env = {"HOME": str(tmp_path), "PATH": os.environ["PATH"]}
    return subprocess.run(
        ["bash", str(REPO / "install.sh"), *args], capture_output=True, text=True, env=env, timeout=60
    )


def _files(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_dry_run_writes_nothing(tmp_path):
    result = _install(tmp_path, "--dry-run", "--yes", "--no-venv")
    assert result.returncode == 0, result.stderr
    assert _files(tmp_path) == []
    assert "[dry-run] would:" in result.stdout


def test_prints_valid_hook_json_and_never_touches_claude_or_shell_rc(tmp_path):
    result = _install(tmp_path, "--yes", "--no-venv", "--no-load")
    assert result.returncode == 0, result.stderr
    snippet = result.stdout[result.stdout.index("{\n") : result.stdout.index("\n}\n") + 2]
    hooks = json.loads(snippet)["hooks"]
    assert set(hooks) == {"Notification", "Stop"}
    assert hooks["Stop"][0]["hooks"][0]["command"].endswith("-m discord_hq hook")
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".zshrc").exists()


def test_creates_private_settings_once_and_never_overwrites(tmp_path):
    assert _install(tmp_path, "--yes", "--no-venv", "--no-load").returncode == 0
    env_file = tmp_path / ".config" / "claude-code-discord-hq" / ".env"
    assert env_file.stat().st_mode & 0o777 == 0o600
    assert env_file.parent.stat().st_mode & 0o777 == 0o700
    env_file.write_text("DISCORD_HQ_GUILD_ID=100000000000000001\n")
    second = _install(tmp_path, "--yes", "--no-venv", "--no-load")
    assert second.returncode == 0
    assert "already exists" in second.stdout
    assert env_file.read_text() == "DISCORD_HQ_GUILD_ID=100000000000000001\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="LaunchAgent is macOS only")
def test_launch_agent_is_written_idempotently_and_removed_on_uninstall(tmp_path):
    assert _install(tmp_path, "--yes", "--no-venv", "--no-load").returncode == 0
    agent = tmp_path / "Library" / "LaunchAgents" / "com.claude-code-discord-hq.watch.plist"
    data = plistlib.loads(agent.read_bytes())
    assert data["ProgramArguments"][0] == str(REPO / ".venv" / "bin" / "python")
    assert "__" not in agent.read_text()
    assert "up to date" in _install(tmp_path, "--yes", "--no-venv", "--no-load").stdout
    had_repo_venv = (REPO / ".venv").exists()
    result = _install(tmp_path, "--uninstall", "--yes", "--no-load", "--no-venv")
    assert result.returncode == 0
    # --no-venv must keep the repo's environment (a test once deleted it).
    assert (REPO / ".venv").exists() == had_repo_venv
    assert not agent.exists()
    assert (tmp_path / ".config" / "claude-code-discord-hq" / ".env").exists()


@pytest.mark.skipif(sys.platform == "darwin", reason="cron hint is for non-macOS")
def test_non_macos_prints_a_cron_line(tmp_path):
    result = _install(tmp_path, "--yes", "--no-venv", "--no-load")
    assert "-m discord_hq watch" in result.stdout
    assert not (tmp_path / "Library").exists()


def test_unknown_option_fails(tmp_path):
    assert _install(tmp_path, "--frobnicate").returncode == 2


class TestLaunchAgentTemplate:
    def _render(self):
        text = (
            TEMPLATE.read_text().replace("__PYTHON__", "/opt/app/.venv/bin/python").replace("__LOG_DIR__", "/tmp/logs")
        )
        return plistlib.loads(text.encode())

    def test_label(self):
        assert self._render()["Label"] == "com.claude-code-discord-hq.watch"

    def test_runs_the_watchdog_every_2_minutes(self):
        data = self._render()
        assert data["StartInterval"] == 120
        assert data["ProgramArguments"][1:] == ["-m", "discord_hq", "watch"]

    def test_path_includes_homebrew(self):
        # launchd's minimal PATH hides Homebrew's tmux and terminal-notifier.
        assert "/opt/homebrew/bin" in self._render()["EnvironmentVariables"]["PATH"].split(":")


@pytest.mark.skipif(
    not (shutil.which("zsh") and shutil.which("tmux") and shutil.which("script")), reason="needs zsh, tmux, script"
)
def test_waiter_shortcut_on_an_isolated_tmux_socket():
    result = subprocess.run(
        ["zsh", str(REPO / "shell" / "waiter.test.zsh")], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all waiter tests passed" in result.stdout


def test_never_writes_settings_through_a_symlink(tmp_path):
    # A dangling symlink at the .env path must not be followed: cp would
    # otherwise create (or clobber) whatever file it points at.
    config = tmp_path / ".config" / "claude-code-discord-hq"
    config.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    (config / ".env").symlink_to(outside)
    result = _install(tmp_path, "--yes", "--no-venv", "--no-load")
    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert not outside.exists()


def test_refuses_a_repo_path_that_would_break_quoting(tmp_path):
    # The repo path is pasted into sed, the plist (XML) and the hook JSON.
    repo = tmp_path / 'we"ird&dir'
    (repo / "launchd").mkdir(parents=True)
    shutil.copy(REPO / "install.sh", repo / "install.sh")
    shutil.copy(REPO / ".env.example", repo / ".env.example")
    shutil.copy(TEMPLATE, repo / "launchd" / TEMPLATE.name)
    home = tmp_path / "home"
    home.mkdir()
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    result = subprocess.run(
        ["bash", str(repo / "install.sh"), "--yes", "--no-venv", "--no-load"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 2
    assert "unsafe character" in result.stderr
    assert _files(home) == []


@pytest.mark.skipif(sys.platform != "darwin", reason="LaunchAgent is macOS only")
def test_backs_up_a_different_launch_agent_before_replacing_it(tmp_path):
    agent = tmp_path / "Library" / "LaunchAgents" / "com.claude-code-discord-hq.watch.plist"
    agent.parent.mkdir(parents=True)
    agent.write_text("<plist>edited by hand</plist>\n")
    result = _install(tmp_path, "--yes", "--no-venv", "--no-load")
    assert result.returncode == 0, result.stderr
    backups = list(agent.parent.glob(agent.name + ".bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "<plist>edited by hand</plist>\n"
    assert "__" not in agent.read_text()


@pytest.mark.skipif(sys.platform != "darwin", reason="LaunchAgent is macOS only")
def test_never_writes_the_launch_agent_through_a_symlink(tmp_path):
    agent = tmp_path / "Library" / "LaunchAgents" / "com.claude-code-discord-hq.watch.plist"
    agent.parent.mkdir(parents=True)
    outside = tmp_path / "outside.plist"
    outside.write_text("keep me\n")
    agent.symlink_to(outside)
    result = _install(tmp_path, "--yes", "--no-venv", "--no-load")
    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert outside.read_text() == "keep me\n"


def test_keeps_a_symlinked_settings_file_that_exists(tmp_path):
    # dotfiles managers (stow, chezmoi) link real files: that's "already exists".
    config = tmp_path / ".config" / "claude-code-discord-hq"
    config.mkdir(parents=True)
    real = tmp_path / "dotfiles.env"
    real.write_text("DISCORD_HQ_GUILD_ID=100000000000000001\n")
    (config / ".env").symlink_to(real)
    result = _install(tmp_path, "--yes", "--no-venv", "--no-load")
    assert result.returncode == 0, result.stderr
    assert "already exists" in result.stdout
    assert real.read_text() == "DISCORD_HQ_GUILD_ID=100000000000000001\n"


@pytest.mark.parametrize("char", ["$", "`"])
def test_refuses_a_repo_path_with_shell_expansion_characters(tmp_path, char):
    # The hook command and the `source` line are run by a shell.
    repo = tmp_path / f"a{char}b"
    (repo / "launchd").mkdir(parents=True)
    shutil.copy(REPO / "install.sh", repo / "install.sh")
    shutil.copy(REPO / ".env.example", repo / ".env.example")
    shutil.copy(TEMPLATE, repo / "launchd" / TEMPLATE.name)
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        ["bash", str(repo / "install.sh"), "--yes", "--no-venv", "--no-load"],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": os.environ["PATH"]},
        timeout=60,
    )
    assert result.returncode == 2
    assert "unsafe character" in result.stderr
