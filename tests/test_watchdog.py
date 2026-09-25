import os
import time
from unittest.mock import patch

from discord_hq.notify import events, watchdog

STALLED_SCREEN = "\n> Running find / -name '*.py'\n\n  esc to interrupt\n"
IDLE_SCREEN = "\nFinished the task.\n\n❯\n"
ACTIVE_SCREEN = "\n> Editing file X\n\n  esc to interrupt\n"


def _worktree(tmp_path, slug="my-task"):
    wt = tmp_path / ".worktrees" / slug
    wt.mkdir(parents=True)
    return wt


def _transcript_dir(tmp_path, name="sess", age_minutes=0):
    folder = tmp_path / "claude-projects" / name
    folder.mkdir(parents=True)
    transcript = folder / "t.jsonl"
    transcript.write_text("{}")
    if age_minutes:
        old = time.time() - age_minutes * 60
        os.utime(transcript, (old, old))
    return folder


class TestIsWorking:
    def test_screen_with_esc_to_interrupt_is_working(self):
        assert watchdog.is_working(STALLED_SCREEN) is True

    def test_idle_screen_is_not_working(self):
        assert watchdog.is_working(IDLE_SCREEN) is False

    def test_empty_screen_is_not_working(self):
        assert watchdog.is_working("") is False


class TestLastToolLine:
    def test_skips_the_marker_line(self):
        summary = watchdog.last_tool_line(STALLED_SCREEN)
        assert "esc to interrupt" not in summary
        assert "find" in summary

    def test_truncates_at_200(self):
        assert len(watchdog.last_tool_line(("x" * 300) + "\nesc to interrupt\n")) <= 200

    def test_marker_only_gives_empty(self):
        assert watchdog.last_tool_line("esc to interrupt\n") == ""


class TestStallDedupe:
    def test_first_alert_is_not_recorded(self, tmp_path, settings):
        assert watchdog.already_alerted_stall(_worktree(tmp_path), 123.0, settings) is False

    def test_same_mtime_is_not_alerted_twice(self, tmp_path, settings):
        wt = _worktree(tmp_path)
        watchdog.record_stall_alert(wt, 123.0, settings)
        assert watchdog.already_alerted_stall(wt, 123.0, settings) is True

    def test_new_mtime_releases_the_alert(self, tmp_path, settings):
        wt = _worktree(tmp_path)
        watchdog.record_stall_alert(wt, 123.0, settings)
        assert watchdog.already_alerted_stall(wt, 456.0, settings) is False


class TestCheckSession:
    def test_long_stall_sends_an_alert(self, tmp_path, settings):
        wt = _worktree(tmp_path, slug="stuck")
        folder = _transcript_dir(tmp_path, age_minutes=15)
        with (
            patch.object(watchdog, "capture_screen", return_value=STALLED_SCREEN),
            patch.object(watchdog, "session_cwd", return_value=str(wt)),
            patch.object(watchdog, "claude_project_dir", return_value=folder),
            patch.object(events, "project_name", return_value="demo"),
            patch.object(events, "dispatch") as dispatch,
        ):
            watchdog.check_session("kitchen-stuck", 10, settings)
        dispatch.assert_called_once()
        event = dispatch.call_args.args[0]
        assert event.kind == "stalled"
        assert event.slug == "stuck"
        assert "no progress" in event.title
        assert "find" in event.message

    def test_recent_activity_sends_nothing(self, tmp_path, settings):
        wt = _worktree(tmp_path, slug="busy")
        folder = _transcript_dir(tmp_path)
        with (
            patch.object(watchdog, "capture_screen", return_value=ACTIVE_SCREEN),
            patch.object(watchdog, "session_cwd", return_value=str(wt)),
            patch.object(watchdog, "claude_project_dir", return_value=folder),
            patch.object(events, "dispatch") as dispatch,
        ):
            watchdog.check_session("kitchen-busy", 10, settings)
        dispatch.assert_not_called()

    def test_idle_session_sends_nothing(self, tmp_path, settings):
        wt = _worktree(tmp_path, slug="idle")
        with (
            patch.object(watchdog, "capture_screen", return_value=IDLE_SCREEN),
            patch.object(watchdog, "session_cwd", return_value=str(wt)),
            patch.object(events, "dispatch") as dispatch,
        ):
            watchdog.check_session("kitchen-idle", 10, settings)
        dispatch.assert_not_called()

    def test_same_stall_is_alerted_once(self, tmp_path, settings):
        wt = _worktree(tmp_path, slug="stuck2")
        folder = _transcript_dir(tmp_path, age_minutes=15)
        with (
            patch.object(watchdog, "capture_screen", return_value=STALLED_SCREEN),
            patch.object(watchdog, "session_cwd", return_value=str(wt)),
            patch.object(watchdog, "claude_project_dir", return_value=folder),
            patch.object(events, "project_name", return_value="demo"),
            patch.object(events, "dispatch") as dispatch,
        ):
            watchdog.check_session("kitchen-stuck2", 10, settings)
            watchdog.check_session("kitchen-stuck2", 10, settings)
        dispatch.assert_called_once()

    def test_no_cwd_does_not_break(self, settings):
        with (
            patch.object(watchdog, "capture_screen", return_value=STALLED_SCREEN),
            patch.object(watchdog, "session_cwd", return_value=""),
            patch.object(events, "dispatch") as dispatch,
        ):
            watchdog.check_session("kitchen-x", 10, settings)
        dispatch.assert_not_called()

    def test_progress_inside_a_subagent_is_not_a_false_stall(self, tmp_path, settings):
        # A foreground subagent writes to <project>/<session>/subagents/*.jsonl
        # and does not touch the main transcript.
        wt = _worktree(tmp_path, slug="with-subagent")
        folder = tmp_path / "claude-projects" / "sess4"
        folder.mkdir(parents=True)
        main = folder / "sess4.jsonl"
        main.write_text("{}")
        old = time.time() - 15 * 60
        os.utime(main, (old, old))
        (folder / "sess4" / "subagents").mkdir(parents=True)
        (folder / "sess4" / "subagents" / "agent-x.jsonl").write_text("{}")
        with (
            patch.object(watchdog, "capture_screen", return_value=STALLED_SCREEN),
            patch.object(watchdog, "session_cwd", return_value=str(wt)),
            patch.object(watchdog, "claude_project_dir", return_value=folder),
            patch.object(events, "dispatch") as dispatch,
        ):
            watchdog.check_session("kitchen-with-subagent", 10, settings)
        dispatch.assert_not_called()

    def test_latest_transcript_includes_subagents(self, tmp_path, settings):
        folder = tmp_path / "claude-projects" / "sess5"
        folder.mkdir(parents=True)
        main = folder / "sess5.jsonl"
        main.write_text("{}")
        old = time.time() - 3600
        os.utime(main, (old, old))
        (folder / "sess5" / "subagents").mkdir(parents=True)
        sub = folder / "sess5" / "subagents" / "agent-y.jsonl"
        sub.write_text("{}")
        with patch.object(watchdog, "claude_project_dir", return_value=folder):
            assert watchdog.latest_transcript("any/cwd", settings) == sub

    def test_no_transcript_does_not_break(self, tmp_path, settings):
        wt = _worktree(tmp_path, slug="no-transcript")
        with (
            patch.object(watchdog, "capture_screen", return_value=STALLED_SCREEN),
            patch.object(watchdog, "session_cwd", return_value=str(wt)),
            patch.object(watchdog, "claude_project_dir", return_value=tmp_path / "missing"),
            patch.object(events, "dispatch") as dispatch,
        ):
            watchdog.check_session("kitchen-no-transcript", 10, settings)
        dispatch.assert_not_called()

    def test_claude_project_dir_follows_claude_code_naming(self, settings):
        assert watchdog.claude_project_dir("/home/dev/code/demo/.worktrees/x", settings) == (
            settings.claude_projects_dir / "-home-dev-code-demo--worktrees-x"
        )


class TestListKitchenSessions:
    def test_keeps_only_prefixed_sessions(self, settings):
        with patch.object(watchdog.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "kitchen-a\nwaiter\nkitchen-b\nsomething-else\n"
            assert watchdog.list_kitchen_sessions(settings) == ["kitchen-a", "kitchen-b"]

    def test_tmux_missing_gives_empty(self, settings):
        with patch.object(watchdog.subprocess, "run", side_effect=Exception("no tmux")):
            assert watchdog.list_kitchen_sessions(settings) == []


class TestMain:
    def test_never_raises_and_always_zero(self, settings):
        with patch.object(watchdog, "list_kitchen_sessions", side_effect=Exception("boom")):
            assert watchdog.main(settings) == 0

    def test_broken_settings_still_zero(self):
        with patch.object(watchdog, "load_settings", side_effect=Exception("bad config")):
            assert watchdog.main() == 0

    def test_checks_every_session_and_updates_the_panel(self, settings):
        with (
            patch.object(watchdog, "list_kitchen_sessions", return_value=["kitchen-a", "kitchen-b"]),
            patch.object(watchdog, "check_session") as check,
            patch.object(watchdog, "session_cwd", return_value="/tmp/wt"),
            patch.object(watchdog, "check_pause") as pause,
            patch.object(watchdog, "update_panel") as panel,
        ):
            assert watchdog.main(settings) == 0
        assert check.call_count == 2
        assert pause.call_count == 2
        panel.assert_called_once()

    def test_an_error_in_one_session_does_not_skip_the_others(self, settings):
        # The two try blocks are independent on purpose: a failing stall
        # check must not skip the pause check of the SAME session.
        with (
            patch.object(watchdog, "list_kitchen_sessions", return_value=["kitchen-a", "kitchen-b"]),
            patch.object(watchdog, "check_session", side_effect=[Exception("boom"), None]) as check,
            patch.object(watchdog, "session_cwd", return_value="/tmp/wt"),
            patch.object(watchdog, "check_pause") as pause,
            patch.object(watchdog, "update_panel"),
        ):
            assert watchdog.main(settings) == 0
        assert check.call_count == 2
        assert pause.call_count == 2

    def test_an_error_in_a_pause_check_does_not_skip_the_others(self, settings):
        with (
            patch.object(watchdog, "list_kitchen_sessions", return_value=["kitchen-a", "kitchen-b"]),
            patch.object(watchdog, "check_session"),
            patch.object(watchdog, "session_cwd", return_value="/tmp/wt"),
            patch.object(watchdog, "check_pause", side_effect=[Exception("boom"), None]) as pause,
            patch.object(watchdog, "update_panel") as panel,
        ):
            assert watchdog.main(settings) == 0
        assert pause.call_count == 2
        panel.assert_called_once()

    def test_panel_error_does_not_break_main(self, settings):
        with (
            patch.object(watchdog, "list_kitchen_sessions", return_value=[]),
            patch.object(watchdog, "update_panel", side_effect=Exception("boom")),
        ):
            assert watchdog.main(settings) == 0

    def test_no_cwd_skips_the_pause_check(self, settings):
        with (
            patch.object(watchdog, "list_kitchen_sessions", return_value=["kitchen-a"]),
            patch.object(watchdog, "check_session"),
            patch.object(watchdog, "session_cwd", return_value=""),
            patch.object(watchdog, "check_pause") as pause,
            patch.object(watchdog, "update_panel"),
        ):
            watchdog.main(settings)
        pause.assert_not_called()


HEADER = "| unit | size | route | state | branch/worktree | PR | session |\n|---|---|---|---|---|---|---|\n"


class TestManifestState:
    def _manifest(self, tmp_path, state_cell, slug="my-task"):
        root = tmp_path / "repo"
        folder = root / "docs" / "plans"
        folder.mkdir(parents=True)
        (folder / "2026-01-10-batch-manifest.md").write_text(
            HEADER + f"| {slug} | M | kitchen | {state_cell} | feat/x | | |\n"
        )
        return root

    def test_waiting(self, tmp_path, settings):
        root = self._manifest(tmp_path, "⏳ waiting for you — needs the dev server")
        assert watchdog.manifest_state(root, "my-task", settings) == (
            "waiting",
            "waiting for you — needs the dev server",
        )

    def test_working(self, tmp_path, settings):
        assert watchdog.manifest_state(self._manifest(tmp_path, "🔄 cooking"), "my-task", settings) == (
            "working",
            "cooking",
        )

    def test_ready(self, tmp_path, settings):
        assert watchdog.manifest_state(self._manifest(tmp_path, "✅ PR #12"), "my-task", settings) == (
            "ready",
            "PR #12",
        )

    def test_stalled(self, tmp_path, settings):
        assert watchdog.manifest_state(self._manifest(tmp_path, "🧊 stalled 20 min"), "my-task", settings) == (
            "stalled",
            "stalled 20 min",
        )

    def test_aborted(self, tmp_path, settings):
        result = watchdog.manifest_state(self._manifest(tmp_path, "🚫 aborted — dependency broke"), "my-task", settings)
        assert result == ("aborted", "aborted — dependency broke")

    def test_queued(self, tmp_path, settings):
        assert watchdog.manifest_state(self._manifest(tmp_path, "⏸ queued"), "my-task", settings) == (
            "queued",
            "queued",
        )

    def test_unknown_slug_gives_none(self, tmp_path, settings):
        assert watchdog.manifest_state(self._manifest(tmp_path, "⏳ x", slug="other"), "my-task", settings) is None

    def test_no_plans_folder_gives_none(self, tmp_path, settings):
        (tmp_path / "bare").mkdir()
        assert watchdog.manifest_state(tmp_path / "bare", "my-task", settings) is None

    def test_state_column_position_does_not_matter(self, tmp_path, settings):
        # New: manifests with other column layouts work, the state is the
        # first cell after the unit that starts with a state emoji.
        root = tmp_path / "repo"
        (root / "docs" / "plans").mkdir(parents=True)
        (root / "docs" / "plans" / "2026-01-10-x-manifest.md").write_text(
            "| my-task | kitchen | .worktrees/x | feat/x | ⏳ waiting — X | | |\n"
        )
        assert watchdog.manifest_state(root, "my-task", settings) == ("waiting", "waiting — X")

    def test_manifest_glob_is_configurable(self, tmp_path, settings):
        from dataclasses import replace

        root = tmp_path / "repo"
        (root / "notes").mkdir(parents=True)
        (root / "notes" / "batch.md").write_text("| my-task | ⏳ waiting |\n")
        assert watchdog.manifest_state(root, "my-task", replace(settings, manifest_glob="notes/*.md")) == (
            "waiting",
            "waiting",
        )

    def test_finds_the_right_manifest_among_many(self, tmp_path, settings):
        root = tmp_path / "repo"
        folder = root / "docs" / "plans"
        folder.mkdir(parents=True)
        (folder / "2026-01-05-other-manifest.md").write_text("| old-task | M | inline | ✅ PR #1 | | | |\n")
        (folder / "2026-01-10-batch-manifest.md").write_text("| my-task | M | kitchen | ⏳ waiting — X | | | |\n")
        assert watchdog.manifest_state(root, "my-task", settings) == ("waiting", "waiting — X")

    def test_same_slug_in_two_batches_the_newest_wins(self, tmp_path, settings):
        # Re-dispatching a slug in a new batch (after aborting it in an old
        # one) must show the new ⏳, not the old 🚫 that sorts first by name.
        root = tmp_path / "repo"
        folder = root / "docs" / "plans"
        folder.mkdir(parents=True)
        (folder / "2026-01-05-old-manifest.md").write_text("| my-task | M | inline | 🚫 aborted — broke | | | |\n")
        (folder / "2026-01-10-new-manifest.md").write_text(
            "| my-task | M | kitchen | ⏳ waiting — redispatched | | | |\n"
        )
        assert watchdog.manifest_state(root, "my-task", settings) == ("waiting", "waiting — redispatched")


class TestCheckPause:
    def _run(self, tmp_path, settings, state, times=1):
        wt = tmp_path / ".worktrees" / "my-task"
        wt.mkdir(parents=True, exist_ok=True)
        with (
            patch.object(events, "repo_root", return_value=tmp_path / "repo"),
            patch.object(watchdog, "manifest_state", return_value=state),
            patch.object(events, "project_name", return_value="demo"),
            patch.object(events, "dispatch") as dispatch,
        ):
            for _ in range(times):
                watchdog.check_pause("kitchen-my-task", str(wt), settings)
        return dispatch

    def test_waiting_row_sends_a_paused_event(self, tmp_path, settings):
        dispatch = self._run(tmp_path, settings, ("waiting", "needs the dev server"))
        dispatch.assert_called_once()
        event = dispatch.call_args.args[0]
        assert event.kind == "paused"
        assert event.slug == "my-task"
        assert "dev server" in event.message

    def test_working_row_sends_nothing(self, tmp_path, settings):
        self._run(tmp_path, settings, ("working", "cooking")).assert_not_called()

    def test_no_row_sends_nothing(self, tmp_path, settings):
        self._run(tmp_path, settings, None).assert_not_called()

    def test_no_repo_root_sends_nothing(self, tmp_path, settings):
        wt = tmp_path / ".worktrees" / "my-task"
        wt.mkdir(parents=True)
        with patch.object(events, "repo_root", return_value=None), patch.object(events, "dispatch") as dispatch:
            watchdog.check_pause("kitchen-my-task", str(wt), settings)
        dispatch.assert_not_called()

    def test_same_pause_is_alerted_once(self, tmp_path, settings):
        self._run(tmp_path, settings, ("waiting", "X"), times=2).assert_called_once()

    def test_new_reason_alerts_again(self, tmp_path, settings):
        assert self._run(tmp_path, settings, ("waiting", "reason A")).call_count == 1
        assert self._run(tmp_path, settings, ("waiting", "reason B")).call_count == 1

    def test_resume_then_pause_with_same_reason_alerts_again(self, tmp_path, settings):
        # "waiting for you" is a common default reason: without clearing the
        # marker when the unit leaves ⏳, a second pause would never alert.
        assert self._run(tmp_path, settings, ("waiting", "waiting for you")).call_count == 1
        assert self._run(tmp_path, settings, ("working", "cooking")).call_count == 0
        assert self._run(tmp_path, settings, ("waiting", "waiting for you")).call_count == 1

    def test_clear_removes_the_marker(self, tmp_path, settings):
        wt = tmp_path / "wt"
        watchdog.record_pause_alert(wt, "some reason", settings)
        assert watchdog.already_alerted_pause(wt, "some reason", settings) is True
        watchdog.clear_pause_alert(wt, settings)
        assert watchdog.already_alerted_pause(wt, "some reason", settings) is False

    def test_clear_without_marker_does_not_break(self, tmp_path, settings):
        watchdog.clear_pause_alert(tmp_path / "wt", settings)
