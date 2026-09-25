import json
from unittest.mock import patch

from discord_hq.notify import events


def _worktree(tmp_path, slug="my-task"):
    wt = tmp_path / ".worktrees" / slug
    wt.mkdir(parents=True)
    return wt


def _payload(**over):
    base = {
        "session_id": "sess-1",
        "cwd": "/tmp/x",
        "transcript_path": "/tmp/transcript.jsonl",
        "hook_event_name": "Notification",
    }
    base.update(over)
    return base


def _done(wt, settings):
    (wt / settings.marker_dir_name).mkdir()
    (wt / settings.marker_dir_name / "done").touch()


class TestIdentifySession:
    def test_cwd_inside_a_worktree_is_a_kitchen_session(self, tmp_path, settings):
        wt = _worktree(tmp_path)
        with patch.object(events, "tmux_session_name", return_value=None):
            session = events.identify_session(str(wt / "sub"), settings)
        assert session == events.Session(slug="my-task", worktree=wt)

    def test_tmux_session_with_the_prefix_is_a_kitchen_session(self, tmp_path, settings):
        with patch.object(events, "tmux_session_name", return_value="kitchen-other-task"):
            session = events.identify_session(str(tmp_path / "elsewhere"), settings)
        assert session is not None
        assert session.slug == "other-task"

    def test_the_waiter_session_is_not_the_kitchen(self, tmp_path, settings):
        with patch.object(events, "tmux_session_name", return_value="waiter"):
            assert events.identify_session(str(tmp_path / "elsewhere"), settings) is None

    def test_no_tmux_and_no_worktree_is_not_the_kitchen(self, tmp_path, settings):
        with patch.object(events, "tmux_session_name", return_value=None):
            assert events.identify_session(str(tmp_path / "elsewhere"), settings) is None

    def test_worktree_folder_name_is_configurable(self, tmp_path, settings):
        from dataclasses import replace

        wt = tmp_path / "trees" / "abc"
        wt.mkdir(parents=True)
        with patch.object(events, "tmux_session_name", return_value=None):
            session = events.identify_session(str(wt), replace(settings, worktrees_dir_name="trees"))
        assert session.slug == "abc"

    def test_slug_is_sanitized_for_shell_use(self, tmp_path, settings):
        # The slug ends up in a shell command (the notification click action
        # and the attach hint). A folder or tmux name is not trusted input.
        with patch.object(events, "tmux_session_name", return_value="kitchen-x';touch /tmp/pwned;'"):
            session = events.identify_session(str(tmp_path), settings)
        assert set(session.slug) <= set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


class TestBuildEvent:
    def test_permission_prompt(self, tmp_path, settings):
        session = events.Session(slug="my-task", worktree=_worktree(tmp_path))
        payload = _payload(notification_type="permission_prompt", message="Bash wants to run `rm -rf`")
        event = events.build_event(payload, session, "demo", settings)
        assert event.kind == "permission"
        assert event.title == "🔐 demo needs approval"
        assert "rm -rf" in event.message
        assert event.urgent is True

    def test_idle_prompt(self, tmp_path, settings):
        session = events.Session(slug="my-task", worktree=_worktree(tmp_path))
        event = events.build_event(
            _payload(notification_type="idle_prompt", message="waiting"), session, "demo", settings
        )
        assert event.kind == "idle"
        assert event.title == "💬 demo is waiting for you"
        assert event.urgent is False

    def test_unknown_notification_type_is_ignored(self, tmp_path, settings):
        session = events.Session(slug="my-task", worktree=_worktree(tmp_path))
        assert (
            events.build_event(_payload(notification_type="auth_success", message="ok"), session, "demo", settings)
            is None
        )

    def test_legacy_payload_without_type_is_classified_by_text(self, tmp_path, settings):
        session = events.Session(slug="my-task", worktree=_worktree(tmp_path))
        event = events.build_event(
            _payload(message="Claude needs your permission to use Bash"), session, "demo", settings
        )
        assert event.kind == "permission"

    def test_stop_without_done_marker_is_stopped(self, tmp_path, settings):
        session = events.Session(slug="my-task", worktree=_worktree(tmp_path))
        payload = _payload(
            hook_event_name="Stop", stop_hook_active=False, last_assistant_message="Adjusted test X, moving to Y."
        )
        event = events.build_event(payload, session, "demo", settings)
        assert event.kind == "stopped"
        assert event.title == "⏸️ demo stopped"
        assert "Adjusted test X" in event.message

    def test_stop_with_done_marker_is_ready_with_the_pr(self, tmp_path, settings):
        wt = _worktree(tmp_path)
        _done(wt, settings)
        session = events.Session(slug="my-task", worktree=wt)
        with patch.object(events, "pr_url", return_value="https://github.com/x/y/pull/9"):
            event = events.build_event(
                _payload(hook_event_name="Stop", stop_hook_active=False), session, "demo", settings
            )
        assert event.kind == "ready"
        assert event.title == "✅ demo ready"
        assert "https://github.com/x/y/pull/9" in event.message

    def test_ready_without_pr_does_not_break(self, tmp_path, settings):
        wt = _worktree(tmp_path)
        _done(wt, settings)
        session = events.Session(slug="my-task", worktree=wt)
        with patch.object(events, "pr_url", return_value=None):
            event = events.build_event(
                _payload(hook_event_name="Stop", stop_hook_active=False), session, "demo", settings
            )
        assert event.kind == "ready"

    def test_stop_hook_active_is_ignored(self, tmp_path, settings):
        session = events.Session(slug="my-task", worktree=_worktree(tmp_path))
        assert (
            events.build_event(_payload(hook_event_name="Stop", stop_hook_active=True), session, "demo", settings)
            is None
        )


class TestPrUrl:
    def test_uses_the_configured_gh_command(self, tmp_path, settings):
        from dataclasses import replace

        custom = replace(settings, gh_command=("env", "-u", "GH_TOKEN", "gh"))
        with patch.object(events.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "https://github.com/x/y/pull/1\n"
            assert events.pr_url(tmp_path, custom) == "https://github.com/x/y/pull/1"
        assert run.call_args.args[0][:4] == ["env", "-u", "GH_TOKEN", "gh"]

    def test_failure_gives_none(self, tmp_path, settings):
        with patch.object(events.subprocess, "run", side_effect=Exception("no gh")):
            assert events.pr_url(tmp_path, settings) is None


class TestLastMessageSummary:
    def test_prefers_the_payload_field(self):
        assert events.last_message_summary({"last_assistant_message": "short"}, "/missing.jsonl") == "short"

    def test_reads_the_transcript_when_the_field_is_missing(self, tmp_path):
        transcript = tmp_path / "t.jsonl"
        lines = [
            {"type": "user", "message": {"role": "user", "content": "hi"}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "first"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash"}]}},
            {
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "last real message"}]},
            },
        ]
        transcript.write_text("\n".join(json.dumps(line) for line in lines))
        assert events.last_message_summary({}, str(transcript)) == "last real message"

    def test_truncates_at_200_characters(self, tmp_path):
        transcript = tmp_path / "t.jsonl"
        transcript.write_text(
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "a" * 300}]}})
        )
        assert len(events.last_message_summary({}, str(transcript))) <= 200

    def test_missing_transcript_gives_empty(self):
        assert events.last_message_summary({}, "/no/such/file.jsonl") == ""


class TestDedupe:
    def test_first_alert_passes(self, tmp_path, settings):
        assert events.dedupe(_worktree(tmp_path), "permission", settings) is True

    def test_immediate_repeat_is_blocked(self, tmp_path, settings):
        wt = _worktree(tmp_path)
        assert events.dedupe(wt, "permission", settings) is True
        assert events.dedupe(wt, "permission", settings) is False

    def test_different_kinds_do_not_block_each_other(self, tmp_path, settings):
        wt = _worktree(tmp_path)
        assert events.dedupe(wt, "permission", settings) is True
        assert events.dedupe(wt, "idle", settings) is True

    def test_old_alert_releases_again(self, tmp_path, settings):
        wt = _worktree(tmp_path)
        marker = wt / settings.marker_dir_name / "last-alert"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"permission": 0}))
        assert events.dedupe(wt, "permission", settings) is True


class TestProject:
    def test_name_comes_from_the_git_common_dir(self):
        with patch.object(events.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "/home/dev/code/demo/.git\n"
            assert events.project_name("/any/cwd") == "demo"

    def test_git_failure_falls_back(self):
        with patch.object(events.subprocess, "run", side_effect=Exception("boom")):
            assert events.project_name("/any/cwd") == "project"

    def test_absolute_common_dir(self, tmp_path):
        root = (tmp_path / "demo").resolve()
        with patch.object(events.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = f"{root}/.git\n"
            assert events.repo_root("/any/cwd") == root

    def test_relative_common_dir_resolves_against_the_git_cwd(self, tmp_path):
        # Found running for real: from a plain subfolder git returns a path
        # relative to ITS cwd (the one passed to subprocess), not to the
        # Python process cwd.
        real_root = tmp_path / "project"
        (real_root / ".worktrees" / "slug").mkdir(parents=True)
        with patch.object(events.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "../../.git\n"
            assert events.repo_root(str(real_root / ".worktrees" / "slug")) == real_root.resolve()

    def test_git_failure_gives_none(self):
        with patch.object(events.subprocess, "run", side_effect=Exception("boom")):
            assert events.repo_root("/any/cwd") is None


class TestDispatch:
    def test_every_sink_is_called_and_one_failing_does_not_stop_the_other(self, tmp_path, settings):
        event = events.Event("permission", "demo", "s", "t", "m", tmp_path, True)
        calls = []

        class Broken:
            @staticmethod
            def notify(evt, cfg):
                calls.append("broken")
                raise RuntimeError("boom")

        class Fine:
            @staticmethod
            def notify(evt, cfg):
                calls.append("fine")

        with patch.object(events, "SINKS", [Broken, Fine]):
            events.dispatch(event, settings)
        assert calls == ["broken", "fine"]


class TestHookMain:
    def test_never_raises_and_always_exits_zero_silently(self, capsys, settings):
        with patch.object(events.sys, "stdin") as stdin:
            stdin.read.side_effect = Exception("broken stdin")
            assert events.hook_main(settings=settings) == 0
        assert capsys.readouterr().out == ""

    def test_broken_settings_still_exit_zero(self, capsys):
        with (
            patch.object(events, "load_settings", side_effect=Exception("bad config")),
            patch.object(events.sys, "stdin") as stdin,
        ):
            stdin.read.return_value = "{}"
            assert events.hook_main() == 0
        assert capsys.readouterr().out == ""

    def test_waiter_session_dispatches_nothing(self, tmp_path, settings):
        payload = _payload(cwd=str(tmp_path), notification_type="permission_prompt")
        with (
            patch.object(events.sys, "stdin") as stdin,
            patch.object(events, "tmux_session_name", return_value=None),
            patch.object(events, "dispatch") as dispatch,
        ):
            stdin.read.return_value = json.dumps(payload)
            assert events.hook_main(settings=settings) == 0
        dispatch.assert_not_called()

    def test_kitchen_session_dispatches(self, tmp_path, settings):
        wt = _worktree(tmp_path)
        payload = _payload(cwd=str(wt), notification_type="permission_prompt", message="needs approval")
        with (
            patch.object(events.sys, "stdin") as stdin,
            patch.object(events, "tmux_session_name", return_value=None),
            patch.object(events, "project_name", return_value="demo"),
            patch.object(events, "dispatch") as dispatch,
        ):
            stdin.read.return_value = json.dumps(payload)
            assert events.hook_main(settings=settings) == 0
        dispatch.assert_called_once()
        assert dispatch.call_args.args[0].kind == "permission"
