from pathlib import Path
from unittest.mock import patch

import pytest

from discord_hq import __version__, cli

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DISCORD_HQ_CONFIG_DIR", str(tmp_path / "cfg"))
    for name in ("DISCORD_HQ_DESIGN", "DISCORD_HQ_STATE", "DISCORD_HQ_ADMIN_TOKEN", "DISCORD_HQ_GUILD_ID"):
        monkeypatch.delenv(name, raising=False)


def test_no_command_prints_usage_and_fails(capsys):
    assert cli.main([]) == 2
    assert "usage" in capsys.readouterr().err.lower()


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_plan_passes_the_design_and_mode(tmp_path):
    with patch.object(cli.apply, "run", return_value=0) as run:
        assert cli.main(["plan", "--design", str(EXAMPLES / "minimal.toml")]) == 0
    _, design_path = run.call_args.args
    assert design_path == EXAMPLES / "minimal.toml"
    assert run.call_args.kwargs["mode"] == "plan"


def test_apply_flags(tmp_path):
    with patch.object(cli.apply, "run", return_value=0) as run:
        cli.main(["apply", "--design", "d.toml", "--yes", "--allow-delete"])
    kwargs = run.call_args.kwargs
    assert kwargs["mode"] == "apply"
    assert kwargs["yes"] is True
    assert kwargs["allow_delete"] is True


def test_design_defaults_to_env_then_cwd(tmp_path, monkeypatch):
    with patch.object(cli.apply, "run", return_value=0) as run:
        cli.main(["plan"])
    assert run.call_args.args[1] == Path("design.toml")
    monkeypatch.setenv("DISCORD_HQ_DESIGN", str(tmp_path / "mine.toml"))
    with patch.object(cli.apply, "run", return_value=0) as run:
        cli.main(["plan"])
    assert run.call_args.args[1] == tmp_path / "mine.toml"


def test_bad_config_is_a_clean_error(monkeypatch, capsys):
    monkeypatch.setenv("DISCORD_HQ_GUILD_ID", "not-a-number")
    assert cli.main(["plan"]) == 2
    assert "DISCORD_HQ_GUILD_ID" in capsys.readouterr().err


def test_access_prints_plugin_commands(tmp_path, capsys):
    design = tmp_path / "design.toml"
    design.write_text((EXAMPLES / "minimal.toml").read_text())
    (tmp_path / "state.json").write_text('{"channels": {"table (🛎️ COUNTER)": "200000000000000001"}}')
    assert cli.main(["access", "--bot", "waiter", "--design", str(design)]) == 0
    out = capsys.readouterr().out
    assert "/discord:access group add 200000000000000001 --no-mention" in out


def test_access_unknown_bot_lists_the_known_ones(tmp_path, capsys):
    assert cli.main(["access", "--bot", "nobody", "--design", str(EXAMPLES / "restaurant.toml")]) == 2
    err = capsys.readouterr().err
    assert "waiter" in err and "station" in err


def test_access_without_state_explains_what_to_do(tmp_path, capsys):
    design = tmp_path / "design.toml"
    design.write_text((EXAMPLES / "minimal.toml").read_text())
    assert cli.main(["access", "--bot", "waiter", "--design", str(design)]) == 1
    assert "discord-hq apply" in capsys.readouterr().err


def test_hook_delegates_and_always_exits_zero():
    with patch.object(cli.events, "hook_main", return_value=0) as hook:
        assert cli.main(["hook"]) == 0
    hook.assert_called_once()


def test_watch_delegates():
    with patch.object(cli.watchdog, "main", return_value=0) as watch:
        assert cli.main(["watch"]) == 0
    watch.assert_called_once()


def test_audit_forum_is_read_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCORD_HQ_ADMIN_TOKEN", "secret-token-x")
    monkeypatch.setenv("DISCORD_HQ_GUILD_ID", "100000000000000001")
    with (
        patch.object(cli.apply, "DiscordClient") as client_class,
        patch.object(cli.apply, "audit_forum", return_value={"total": 1, "names": ["abc"]}),
    ):
        assert cli.main(["audit-forum", "200000000000000009"]) == 0
    api = client_class.return_value
    api.post.assert_not_called()
    api.patch.assert_not_called()
    api.put.assert_not_called()
    api.delete.assert_not_called()
    out = capsys.readouterr().out
    assert "abc" in out
    assert "secret-token-x" not in out


def test_audit_forum_strips_control_characters_from_post_names(monkeypatch, capsys):
    # Post names are typed by any server member; a terminal escape in one
    # must not reach the chef's terminal.
    monkeypatch.setenv("DISCORD_HQ_ADMIN_TOKEN", "secret-token-x")
    monkeypatch.setenv("DISCORD_HQ_GUILD_ID", "100000000000000001")
    with (
        patch.object(cli.apply, "DiscordClient"),
        patch.object(cli.apply, "audit_forum", return_value={"total": 1, "names": ["ok\x1b]0;pwned\x07\nfake line"]}),
    ):
        assert cli.main(["audit-forum", "200000000000000009"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "fake line" in out
    assert "\nfake line" not in out
