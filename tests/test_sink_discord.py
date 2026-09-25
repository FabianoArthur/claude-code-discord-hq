import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from conftest import MENTION_ID
from discord_hq.notify import events
from discord_hq.notify.sinks import discord

BELL = "https://discord.com/api/webhooks/1/tok-bell"
PASS = "https://discord.com/api/webhooks/2/tok-pass"


def _event(**over):
    base = dict(
        kind="permission",
        project="demo",
        slug="my-task",
        title="🔐 demo needs approval",
        message="Bash wants to run something",
        worktree=Path("/tmp/wt"),
        urgent=True,
    )
    base.update(over)
    return events.Event(**base)


def _webhooks(settings, **urls):
    settings.webhooks_path.parent.mkdir(parents=True, exist_ok=True)
    settings.webhooks_path.write_text(json.dumps(urls))


def _post(settings, event):
    with patch.object(discord.requests, "post") as post:
        discord.notify(event, settings)
    return post


def test_permission_goes_to_the_alert_webhook(settings):
    _webhooks(settings, Bell=BELL, Pass=PASS)
    post = _post(settings, _event(kind="permission"))
    post.assert_called_once()
    assert post.call_args.args[0] == BELL


def test_ready_goes_to_the_ready_webhook(settings):
    _webhooks(settings, Bell=BELL, Pass=PASS)
    assert (
        _post(settings, _event(kind="ready", message="https://github.com/x/y/pull/9", urgent=False)).call_args.args[0]
        == PASS
    )


def test_stopped_stalled_and_paused_go_to_the_alert_webhook(settings):
    _webhooks(settings, Bell=BELL, Pass=PASS)
    for kind in ("stopped", "stalled", "paused"):
        assert _post(settings, _event(kind=kind, urgent=False)).call_args.args[0] == BELL


def test_idle_is_not_posted(settings):
    _webhooks(settings, Bell=BELL)
    _post(settings, _event(kind="idle", urgent=False)).assert_not_called()


def test_webhook_names_are_configurable(settings):
    _webhooks(settings, Alarm=BELL)
    post = _post(replace(settings, webhook_alert="Alarm"), _event(kind="permission"))
    assert post.call_args.args[0] == BELL


def test_only_the_configured_user_is_mentioned(settings):
    _webhooks(settings, Bell=BELL)
    payload = _post(settings, _event(kind="permission")).call_args.kwargs["json"]
    assert f"<@{MENTION_ID}>" in payload["content"]
    assert payload["allowed_mentions"] == {"users": [MENTION_ID]}
    assert "@everyone" not in payload["content"]


def test_without_a_mention_id_nobody_is_pinged(settings):
    _webhooks(settings, Bell=BELL)
    payload = _post(replace(settings, mention_user_id=None), _event(kind="permission")).call_args.kwargs["json"]
    assert "<@" not in payload["content"]
    assert payload["allowed_mentions"] == {"parse": []}


def test_ready_content_carries_the_pr_link(settings):
    _webhooks(settings, Pass=PASS)
    payload = _post(
        settings, _event(kind="ready", message="https://github.com/x/y/pull/9", urgent=False)
    ).call_args.kwargs["json"]
    assert "https://github.com/x/y/pull/9" in payload["content"]


def test_alert_content_carries_the_attach_command(settings):
    _webhooks(settings, Bell=BELL)
    payload = _post(settings, _event(kind="stopped", urgent=False)).call_args.kwargs["json"]
    assert "tmux attach -t '=kitchen-my-task'" in payload["content"]


def test_short_timeout(settings):
    _webhooks(settings, Bell=BELL)
    assert _post(settings, _event()).call_args.kwargs["timeout"] <= 5


def test_missing_webhooks_file_posts_nothing(settings):
    _post(settings, _event()).assert_not_called()


def test_webhook_for_the_kind_missing_posts_nothing(settings):
    _webhooks(settings, Pass=PASS)
    _post(settings, _event(kind="permission")).assert_not_called()


def test_network_error_does_not_raise(settings):
    _webhooks(settings, Bell=BELL)
    with patch.object(discord.requests, "post", side_effect=Exception(f"boom {BELL}")):
        discord.notify(_event(), settings)


def test_webhook_url_never_reaches_stdout_or_stderr(settings, capsys):
    _webhooks(settings, Bell="https://discord.com/api/webhooks/1/tok-very-secret")
    with patch.object(
        discord.requests, "post", side_effect=Exception("https://discord.com/api/webhooks/1/tok-very-secret")
    ):
        discord.notify(_event(), settings)
    captured = capsys.readouterr()
    assert "tok-very-secret" not in captured.out
    assert "tok-very-secret" not in captured.err


def test_masked_markdown_links_in_free_text_are_defused(settings):
    # event.message is free text (the assistant's last message, the hook's
    # message); `[click here](https://evil.example)` must not become a link
    # hiding its real target.
    _webhooks(settings, Bell=BELL)
    content = _post(
        settings, _event(kind="stopped", message="[click here](https://evil.example)", urgent=False)
    ).call_args.kwargs["json"]["content"]
    assert "[click here](https://evil.example)" not in content
    assert "click here" in content


def test_pr_link_in_ready_stays_intact(settings):
    _webhooks(settings, Pass=PASS)
    content = _post(
        settings, _event(kind="ready", message="https://github.com/x/y/pull/9", urgent=False)
    ).call_args.kwargs["json"]["content"]
    assert "https://github.com/x/y/pull/9" in content


def test_corrupted_webhooks_file_does_not_break(settings):
    settings.webhooks_path.parent.mkdir(parents=True, exist_ok=True)
    settings.webhooks_path.write_text("{ not json")
    _post(settings, _event()).assert_not_called()


def test_content_is_capped_at_discord_limit(settings):
    _webhooks(settings, Bell=BELL)
    content = _post(settings, _event(kind="stopped", message="x" * 5000, urgent=False)).call_args.kwargs["json"][
        "content"
    ]
    assert len(content) <= 2000
