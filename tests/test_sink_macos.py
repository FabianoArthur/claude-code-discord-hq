from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from discord_hq.notify import events
from discord_hq.notify.sinks import macos

NOTIFIER = "/opt/homebrew/bin/terminal-notifier"


def _event(**over):
    base = dict(
        kind="permission",
        project="demo",
        slug="my-task",
        title="🔐 demo needs approval",
        message="Bash wants to run",
        worktree=Path("/tmp/wt"),
        urgent=True,
    )
    base.update(over)
    return events.Event(**base)


@pytest.fixture(autouse=True)
def _on_macos():
    with patch.object(macos.sys, "platform", "darwin"):
        yield


def _calls(settings, event, notifier=NOTIFIER, run_side_effect=None):
    with (
        patch.object(macos.shutil, "which", return_value=notifier),
        patch.object(macos.subprocess, "run", side_effect=run_side_effect) as run,
    ):
        macos.notify(event, settings)
    return run.call_args_list


def _notifier_args(calls):
    return next(c for c in calls if c.args[0][0] == "terminal-notifier").args[0]


def test_always_copies_the_attach_command(settings):
    copies = [c for c in _calls(settings, _event()) if c.args[0][0] == "pbcopy"]
    assert len(copies) == 1
    assert "tmux attach -t '=kitchen-my-task'" in copies[0].kwargs["input"]


def test_message_ends_with_copied_hint(settings):
    args = _notifier_args(_calls(settings, _event()))
    assert args[args.index("-message") + 1].endswith("(attach command copied)")


def test_uses_terminal_notifier_when_available(settings):
    commands = [c.args[0][0] for c in _calls(settings, _event())]
    assert "terminal-notifier" in commands
    assert "osascript" not in commands


def test_sound_only_when_urgent(settings):
    assert "-sound" in _notifier_args(_calls(settings, _event(urgent=True)))
    assert "-sound" not in _notifier_args(_calls(settings, _event(urgent=False)))


def test_click_runs_the_configured_command_with_the_attach(settings):
    custom = replace(settings, click_command="open -na Ghostty --args -e {attach}")
    args = _notifier_args(_calls(custom, _event(slug="other")))
    click = args[args.index("-execute") + 1]
    assert click == "open -na Ghostty --args -e tmux attach -t '=kitchen-other'"


def test_default_click_just_opens_terminal(settings):
    args = _notifier_args(_calls(settings, _event()))
    assert args[args.index("-execute") + 1] == "open -a Terminal"


def test_group_per_slug_replaces_the_previous_notification(settings):
    args = _notifier_args(_calls(settings, _event(slug="someone")))
    assert args[args.index("-group") + 1] == "discord-hq-someone"


def test_falls_back_to_osascript(settings):
    commands = [c.args[0][0] for c in _calls(settings, _event(), notifier=None)]
    assert "osascript" in commands
    assert "terminal-notifier" not in commands


def test_osascript_escapes_quotes(settings):
    calls = _calls(settings, _event(message='say "hi"'), notifier=None)
    script = next(c for c in calls if c.args[0][0] == "osascript").args[0][2]
    assert '\\"hi\\"' in script


def test_subprocess_error_does_not_raise(settings):
    _calls(settings, _event(), run_side_effect=Exception("boom"))


def test_clipboard_failure_does_not_block_the_notification(settings):
    count = {"n": 0}

    def run(args, **kwargs):
        count["n"] += 1
        if args[0] == "pbcopy":
            raise Exception("no clipboard")

    _calls(settings, _event(), run_side_effect=run)
    assert count["n"] == 2


def test_does_nothing_off_macos(settings):
    with patch.object(macos.sys, "platform", "linux"), patch.object(macos.subprocess, "run") as run:
        macos.notify(_event(), settings)
    run.assert_not_called()
