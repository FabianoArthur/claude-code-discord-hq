from pathlib import Path

import pytest

from discord_hq import config


def _load(tmp_path, env=None, dotenv=None):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir(exist_ok=True)
    if dotenv is not None:
        (config_dir / ".env").write_text(dotenv)
    environ = {"DISCORD_HQ_CONFIG_DIR": str(config_dir), "HOME": str(tmp_path)}
    environ.update(env or {})
    return config.load_settings(environ)


class TestConfigDir:
    def test_explicit_config_dir_wins(self, tmp_path):
        settings = _load(tmp_path)
        assert settings.config_dir == tmp_path / "cfg"

    def test_xdg_config_home_is_respected(self, tmp_path):
        settings = config.load_settings({"XDG_CONFIG_HOME": str(tmp_path / "xdg"), "HOME": str(tmp_path)})
        assert settings.config_dir == tmp_path / "xdg" / "claude-code-discord-hq"

    def test_falls_back_to_home_dot_config(self, tmp_path):
        settings = config.load_settings({"HOME": str(tmp_path)})
        assert settings.config_dir == tmp_path / ".config" / "claude-code-discord-hq"

    def test_derived_paths_live_in_config_dir(self, tmp_path):
        settings = _load(tmp_path)
        assert settings.webhooks_path == tmp_path / "cfg" / "webhooks.json"
        assert settings.panel_path == tmp_path / "cfg" / "panel.json"
        assert settings.finished_sessions_path == tmp_path / "cfg" / "panel-finished.json"


class TestDefaults:
    def test_defaults_are_generic_and_english(self, tmp_path):
        settings = _load(tmp_path)
        assert settings.admin_token is None
        assert settings.guild_id is None
        assert settings.mention_user_id is None
        assert settings.session_prefix == "kitchen-"
        assert settings.worktrees_dir_name == ".worktrees"
        assert settings.marker_dir_name == ".kitchen"
        assert settings.manifest_glob == "docs/plans/*-manifest.md"
        assert settings.stall_minutes == 10
        assert settings.gh_command == ("gh",)
        assert settings.webhook_ready == "Pass"
        assert settings.webhook_alert == "Bell"
        assert settings.webhook_panel == "Panel"

    def test_claude_projects_dir_defaults_to_home(self, tmp_path):
        settings = _load(tmp_path)
        assert settings.claude_projects_dir == tmp_path / ".claude" / "projects"

    def test_claude_config_dir_env_is_respected(self, tmp_path):
        settings = _load(tmp_path, env={"CLAUDE_CONFIG_DIR": str(tmp_path / "alt")})
        assert settings.claude_projects_dir == tmp_path / "alt" / "projects"


class TestDotenv:
    def test_reads_values_from_dotenv_file(self, tmp_path):
        settings = _load(
            tmp_path,
            dotenv=(
                "# comment\n"
                "\n"
                "DISCORD_HQ_ADMIN_TOKEN=abc.def\n"
                'DISCORD_HQ_GUILD_ID="100000000000000001"\n'
                "export DISCORD_HQ_SESSION_PREFIX='orq-'\n"
            ),
        )
        assert settings.admin_token == "abc.def"
        assert settings.guild_id == "100000000000000001"
        assert settings.session_prefix == "orq-"

    def test_process_environment_overrides_dotenv(self, tmp_path):
        settings = _load(
            tmp_path,
            env={"DISCORD_HQ_SESSION_PREFIX": "env-"},
            dotenv="DISCORD_HQ_SESSION_PREFIX=file-\n",
        )
        assert settings.session_prefix == "env-"

    def test_empty_value_means_unset(self, tmp_path):
        settings = _load(tmp_path, dotenv="DISCORD_HQ_MENTION_USER_ID=\n")
        assert settings.mention_user_id is None

    def test_malformed_lines_are_ignored(self, tmp_path):
        settings = _load(tmp_path, dotenv="this is not a pair\nDISCORD_HQ_GUILD_ID=100000000000000001\n")
        assert settings.guild_id == "100000000000000001"


class TestValidation:
    def test_non_numeric_guild_id_is_rejected_without_echoing_it(self, tmp_path):
        with pytest.raises(config.ConfigError) as exc:
            _load(tmp_path, env={"DISCORD_HQ_GUILD_ID": "my-secret-guild"})
        assert "DISCORD_HQ_GUILD_ID" in str(exc.value)
        assert "my-secret-guild" not in str(exc.value)

    def test_non_numeric_mention_user_id_is_rejected(self, tmp_path):
        with pytest.raises(config.ConfigError):
            _load(tmp_path, env={"DISCORD_HQ_MENTION_USER_ID": "@everyone"})

    def test_invalid_stall_minutes_falls_back_to_default(self, tmp_path):
        settings = _load(tmp_path, env={"DISCORD_HQ_STALL_MINUTES": "abc"})
        assert settings.stall_minutes == 10

    def test_stall_minutes_from_env(self, tmp_path):
        settings = _load(tmp_path, env={"DISCORD_HQ_STALL_MINUTES": "5"})
        assert settings.stall_minutes == 5

    def test_gh_command_is_split_like_a_shell_word_list(self, tmp_path):
        settings = _load(tmp_path, env={"DISCORD_HQ_GH": "env -u GH_TOKEN gh"})
        assert settings.gh_command == ("env", "-u", "GH_TOKEN", "gh")

    def test_empty_session_prefix_is_rejected(self, tmp_path):
        # An empty prefix would make the watchdog treat EVERY tmux session
        # (including the waiter) as a kitchen session.
        with pytest.raises(config.ConfigError):
            _load(tmp_path, env={"DISCORD_HQ_SESSION_PREFIX": " "})


class TestRequire:
    def test_require_returns_value(self, tmp_path):
        settings = _load(tmp_path, env={"DISCORD_HQ_ADMIN_TOKEN": "tok"})
        assert settings.require("admin_token") == "tok"

    def test_require_missing_names_the_variable(self, tmp_path):
        settings = _load(tmp_path)
        with pytest.raises(config.ConfigError) as exc:
            settings.require("admin_token")
        assert "DISCORD_HQ_ADMIN_TOKEN" in str(exc.value)


def test_env_example_documents_every_setting():
    example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    for variable in config.ENV_VARS.values():
        assert variable in example, f"{variable} is not documented in .env.example"


def test_repr_never_shows_the_admin_token(tmp_path):
    # A traceback, a debugger or a stray print(settings) must not leak it.
    settings = config.load_settings({"HOME": str(tmp_path), "DISCORD_HQ_ADMIN_TOKEN": "secret-token-x"})
    assert settings.admin_token == "secret-token-x"
    assert "secret-token-x" not in repr(settings)
    assert "secret-token-x" not in str(settings)
