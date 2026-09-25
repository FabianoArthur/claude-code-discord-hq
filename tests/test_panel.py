import json
import os
import time
from dataclasses import replace
from unittest.mock import patch

from discord_hq.notify import events, panel, watchdog

PANEL_URL = "https://discord.com/api/webhooks/1/tok"


def _info(**over):
    base = dict(slug="my-task", project="demo", state="working", reason="", pr_url=None, minutes=0)
    base.update(over)
    return panel.SessionInfo(**base)


class TestFormatLine:
    def test_working(self, settings):
        line = panel.format_line(_info(state="working", minutes=3), settings)
        assert "🔄" in line
        assert "demo/my-task" in line
        assert "tmux attach -t '=kitchen-my-task'" in line

    def test_waiting_shows_the_reason(self, settings):
        line = panel.format_line(_info(state="waiting", reason="needs the dev server"), settings)
        assert "⏳" in line
        assert "needs the dev server" in line

    def test_reason_with_masked_link_is_defused(self, settings):
        # `reason` comes from the manifest: free text written by an agent.
        line = panel.format_line(_info(state="waiting", reason="[click here](https://evil.example)"), settings)
        assert "[click here](https://evil.example)" not in line
        assert "click here" in line

    def test_stalled_shows_minutes(self, settings):
        line = panel.format_line(_info(state="stalled", minutes=22), settings)
        assert "🧊" in line
        assert "22" in line

    def test_ready_with_pr_shows_the_link(self, settings):
        line = panel.format_line(_info(state="ready", pr_url="https://github.com/x/y/pull/9"), settings)
        assert "✅" in line
        assert "https://github.com/x/y/pull/9" in line

    def test_ready_without_pr_does_not_break(self, settings):
        assert "PR: ?" in panel.format_line(_info(state="ready", pr_url=None), settings)

    def test_idle(self, settings):
        assert "💤" in panel.format_line(_info(state="idle"), settings)


class TestBuildText:
    def test_four_states_in_one_text(self, settings):
        infos = [
            _info(slug="a", state="working"),
            _info(slug="b", state="waiting", reason="needs the dev server"),
            _info(slug="c", state="stalled", minutes=15),
            _info(slug="d", state="ready", pr_url="https://github.com/x/y/pull/9"),
        ]
        text = panel.build_text(infos, "updated at 12:00", settings)
        assert "🔄" in text and "`demo/a`" in text
        assert "⏳" in text and "needs the dev server" in text
        assert "🧊" in text and "15 min" in text
        assert "✅" in text and "https://github.com/x/y/pull/9" in text
        assert "updated at 12:00" in text
        assert len(text) <= 2000

    def test_empty_list_says_no_sessions(self, settings):
        text = panel.build_text([], "updated at 10:00", settings)
        assert "no live sessions" in text.lower()
        assert "updated at 10:00" in text

    def test_one_line_per_session(self, settings):
        assert panel.build_text([_info(slug="a"), _info(slug="b")], "r", settings).count("tmux attach") == 2

    def test_never_exceeds_2000_characters(self, settings):
        infos = [_info(slug=f"task-{i:03d}", reason="x" * 50) for i in range(200)]
        assert len(panel.build_text(infos, "updated at 10:00", settings)) <= 2000

    def test_truncated_text_says_how_many_are_missing(self, settings):
        infos = [_info(slug=f"task-{i:03d}", reason="x" * 50) for i in range(200)]
        assert "more sessions" in panel.build_text(infos, "updated at 10:00", settings)

    def test_short_text_is_not_truncated(self, settings):
        assert "more sessions" not in panel.build_text([_info(slug="a")], "r", settings)


def _collect(settings, **patches):
    defaults = {
        (watchdog, "list_kitchen_sessions"): ["kitchen-a"],
        (panel, "_recent_finished"): [],
        (events, "project_name"): "demo",
    }
    for key, value in patches.items():
        module_name, attr = key.split("__")
        module = {"watchdog": watchdog, "panel": panel, "events": events}[module_name]
        defaults[(module, attr)] = value
    patchers = [patch.object(m, a, return_value=v) for (m, a), v in defaults.items()]
    for p in patchers:
        p.start()
    try:
        return panel.collect_sessions(settings)
    finally:
        for p in patchers:
            p.stop()


def _stale_transcript(tmp_path, minutes=20):
    folder = tmp_path / "claude-projects" / "sess"
    folder.mkdir(parents=True)
    transcript = folder / "t.jsonl"
    transcript.write_text("{}")
    if minutes:
        old = time.time() - minutes * 60
        os.utime(transcript, (old, old))
    return folder


class TestCollectSessions:
    def test_working_session(self, tmp_path, settings):
        infos = _collect(settings, watchdog__session_cwd=str(tmp_path), watchdog__capture_screen="esc to interrupt")
        assert len(infos) == 1
        assert infos[0].state == "working"
        assert infos[0].slug == "a"

    def test_ready_session_is_recorded_as_finished(self, tmp_path, settings):
        (tmp_path / settings.marker_dir_name).mkdir()
        (tmp_path / settings.marker_dir_name / "done").touch()
        with patch.object(events, "pr_url", return_value="https://github.com/x/y/pull/1"):
            with patch.object(panel, "_recent_finished", side_effect=lambda live, cfg: []):
                infos = _collect(settings, watchdog__session_cwd=str(tmp_path))
        assert infos[0].state == "ready"
        assert infos[0].pr_url == "https://github.com/x/y/pull/1"
        assert json.loads(settings.finished_sessions_path.read_text())["a"]["pr_url"] == "https://github.com/x/y/pull/1"

    def test_waiting_in_the_manifest(self, tmp_path, settings):
        infos = _collect(
            settings,
            watchdog__session_cwd=str(tmp_path),
            watchdog__capture_screen="",
            events__repo_root=tmp_path,
            watchdog__manifest_state=("waiting", "needs you"),
        )
        assert infos[0].state == "waiting"
        assert infos[0].reason == "needs you"

    def test_stalled_by_old_transcript(self, tmp_path, settings):
        # Same meaning as the watchdog: "esc to interrupt" on screen but the
        # transcript has not moved; otherwise a hung session shows as 🔄.
        infos = _collect(
            settings,
            watchdog__session_cwd=str(tmp_path),
            watchdog__capture_screen="esc to interrupt",
            watchdog__claude_project_dir=_stale_transcript(tmp_path),
        )
        assert infos[0].state == "stalled"
        assert infos[0].minutes >= 19

    def test_working_with_recent_transcript_is_not_stalled(self, tmp_path, settings):
        infos = _collect(
            settings,
            watchdog__session_cwd=str(tmp_path),
            watchdog__capture_screen="esc to interrupt",
            watchdog__claude_project_dir=_stale_transcript(tmp_path, minutes=0),
        )
        assert infos[0].state == "working"

    def test_stopped_session_is_idle_even_with_an_old_transcript(self, tmp_path, settings):
        # A session that just stopped has no "esc to interrupt" on screen: it
        # must not become 🧊 only because its transcript is old.
        infos = _collect(
            settings,
            watchdog__session_cwd=str(tmp_path),
            watchdog__capture_screen="Finished.\n\n❯",
            events__repo_root=tmp_path,
            watchdog__manifest_state=None,
            watchdog__claude_project_dir=_stale_transcript(tmp_path),
        )
        assert infos[0].state == "idle"

    def test_session_without_cwd_is_skipped(self, settings):
        assert _collect(settings, watchdog__session_cwd="") == []

    def test_includes_recently_finished_sessions_that_left_tmux(self, settings):
        finished = panel.SessionInfo(slug="gone", project="demo", state="ready", pr_url="https://x/pull/2")
        assert _collect(settings, watchdog__list_kitchen_sessions=[], panel___recent_finished=[finished]) == [finished]


class TestRecentFinished:
    def _write(self, settings, data):
        settings.finished_sessions_path.parent.mkdir(parents=True, exist_ok=True)
        settings.finished_sessions_path.write_text(json.dumps(data))

    def test_recent_record_shows(self, settings):
        self._write(settings, {"a": {"project": "demo", "pr_url": "https://x/pull/1", "when": time.time()}})
        infos = panel._recent_finished(set(), settings)
        assert len(infos) == 1
        assert infos[0].slug == "a"

    def test_live_record_is_not_duplicated(self, settings):
        self._write(settings, {"a": {"project": "demo", "pr_url": "https://x/pull/1", "when": time.time()}})
        assert panel._recent_finished({"a"}, settings) == []

    def test_old_record_is_dropped(self, settings):
        self._write(
            settings,
            {"a": {"project": "demo", "pr_url": "x", "when": time.time() - panel.FINISHED_WINDOW_SECONDS - 60}},
        )
        assert panel._recent_finished(set(), settings) == []
        assert json.loads(settings.finished_sessions_path.read_text()) == {}

    def test_missing_file_gives_empty(self, settings):
        assert panel._recent_finished(set(), settings) == []

    def test_corrupted_file_does_not_break(self, settings):
        settings.finished_sessions_path.parent.mkdir(parents=True, exist_ok=True)
        settings.finished_sessions_path.write_text("{ not json")
        assert panel._recent_finished(set(), settings) == []


def _response(status=200, body=None):
    return type("R", (), {"status_code": status, "ok": status < 400, "json": lambda self: body or {}})()


def _webhooks(settings, url=PANEL_URL):
    settings.webhooks_path.parent.mkdir(parents=True, exist_ok=True)
    settings.webhooks_path.write_text(json.dumps({"Panel": url}))


def _panel_state(settings, data):
    settings.panel_path.parent.mkdir(parents=True, exist_ok=True)
    settings.panel_path.write_text(json.dumps(data))


class TestEditPanel:
    def test_without_panel_webhook_does_nothing(self, settings):
        with patch.object(panel.requests, "post") as post, patch.object(panel.requests, "patch") as patch_:
            panel.edit_panel("new text", "key-a", settings)
        post.assert_not_called()
        patch_.assert_not_called()

    def test_first_time_creates_the_message_with_wait(self, settings):
        _webhooks(settings)
        with patch.object(panel.requests, "post", return_value=_response(200, {"id": "999"})) as post:
            panel.edit_panel("new text", "key-a", settings)
        assert post.call_args.kwargs["params"] == {"wait": "true"}
        assert post.call_args.kwargs["json"]["allowed_mentions"] == {"parse": []}
        assert json.loads(settings.panel_path.read_text())["message_id"] == "999"
        assert settings.panel_path.stat().st_mode & 0o777 == 0o600

    def test_existing_message_is_patched(self, settings):
        _webhooks(settings)
        _panel_state(settings, {"message_id": "999", "state_hash": "other"})
        with (
            patch.object(panel.requests, "post") as post,
            patch.object(panel.requests, "patch", return_value=_response(200)) as patch_,
        ):
            panel.edit_panel("new text", "key-b", settings)
        patch_.assert_called_once()
        post.assert_not_called()
        assert "/messages/999" in patch_.call_args.args[0]
        assert json.loads(settings.panel_path.read_text())["state_hash"] == panel._hash("key-b")

    def test_same_state_key_makes_no_call(self, settings):
        _webhooks(settings)
        key = "a|project|working||None"
        _panel_state(settings, {"message_id": "999", "state_hash": panel._hash(key)})
        with patch.object(panel.requests, "post") as post, patch.object(panel.requests, "patch") as patch_:
            panel.edit_panel("text with a different footer", key, settings)
        post.assert_not_called()
        patch_.assert_not_called()

    def test_footer_and_minutes_are_not_part_of_the_state_key(self):
        # Hashing the rendered text (with "updated at HH:MM") made the PATCH
        # fire on every pass with no real change.
        infos = [panel.SessionInfo(slug="a", project="p", state="stalled", minutes=10)]
        first = panel._state_key(infos)
        infos[0].minutes = 12
        assert panel._state_key(infos) == first

    def test_404_recreates_the_message(self, settings):
        _webhooks(settings)
        _panel_state(settings, {"message_id": "999", "state_hash": "other"})
        with (
            patch.object(panel.requests, "patch", return_value=_response(404)) as patch_,
            patch.object(panel.requests, "post", return_value=_response(200, {"id": "1000"})) as post,
        ):
            panel.edit_panel("new text", "key-c", settings)
        patch_.assert_called_once()
        post.assert_called_once()
        assert json.loads(settings.panel_path.read_text())["message_id"] == "1000"

    def test_429_keeps_state_and_retries_next_pass(self, settings):
        _webhooks(settings)
        _panel_state(settings, {"message_id": "999", "state_hash": "other"})
        with (
            patch.object(panel.requests, "patch", return_value=_response(429)),
            patch.object(panel.requests, "post") as post,
        ):
            panel.edit_panel("new text", "key-d", settings)
        post.assert_not_called()
        assert json.loads(settings.panel_path.read_text())["state_hash"] == "other"

    def test_failed_post_does_not_save_state(self, settings):
        _webhooks(settings)
        with patch.object(panel.requests, "post", return_value=_response(500)):
            panel.edit_panel("new text", "key-e", settings)
        assert not settings.panel_path.exists()

    def test_network_error_does_not_raise(self, settings):
        _webhooks(settings)
        with patch.object(panel.requests, "post", side_effect=Exception("boom")):
            panel.edit_panel("new text", "key-f", settings)

    def test_webhook_url_never_reaches_output(self, settings, capsys):
        _webhooks(settings, "https://discord.com/api/webhooks/1/tok-very-secret")
        with patch.object(
            panel.requests, "post", side_effect=Exception("https://discord.com/api/webhooks/1/tok-very-secret")
        ):
            panel.edit_panel("new text", "key-g", settings)
        captured = capsys.readouterr()
        assert "tok-very-secret" not in captured.out + captured.err

    def test_panel_webhook_name_is_configurable(self, settings):
        settings.webhooks_path.parent.mkdir(parents=True, exist_ok=True)
        settings.webhooks_path.write_text(json.dumps({"Board": PANEL_URL}))
        with patch.object(panel.requests, "post", return_value=_response(200, {"id": "1"})) as post:
            panel.edit_panel("x", "k", replace(settings, webhook_panel="Board"))
        post.assert_called_once()


class TestUpdate:
    def test_collects_and_edits(self, settings):
        infos = [panel.SessionInfo(slug="a", project="p", state="working")]
        with patch.object(panel, "collect_sessions", return_value=infos), patch.object(panel, "edit_panel") as edit:
            panel.update(settings)
        text, key, _ = edit.call_args.args
        assert "a" in text
        assert key == panel._state_key(infos)

    def test_collect_error_does_not_raise(self, settings):
        with patch.object(panel, "collect_sessions", side_effect=Exception("boom")):
            panel.update(settings)
