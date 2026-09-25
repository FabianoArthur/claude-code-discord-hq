# Notifications: hook, watchdog and live panel

## What you get

| Event | When | macOS | Discord |
|---|---|---|---|
| 🔐 needs approval | Claude Code shows a permission prompt | ✅ with sound | alert webhook |
| 💬 waiting | Claude Code has been idle waiting for input | ✅ | (no, too noisy) |
| ⏸️ stopped | the session stopped without finishing | ✅ | alert webhook |
| ✅ ready | the session stopped after writing its "done" marker | ✅ | ready webhook, with the PR link |
| 🧊 stalled | the screen says "esc to interrupt" but the transcript hasn't moved for N minutes | ✅ | alert webhook |
| ⏳ paused | the unit's row in a batch manifest starts with ⏳ | ✅ with sound | alert webhook |

Every Discord alert includes the tmux attach command (`tmux attach -t '=kitchen-<slug>'`). On macOS that command is also copied to your clipboard. The Discord post mentions only `DISCORD_HQ_MENTION_USER_ID`, or no one if it is unset.

The **live panel** is a single message in the panel channel, edited in place. It has one line per live kitchen session, 🔄 working · ⏳ needs you · 🧊 stalled · ✅ ready · 💤 idle, plus the sessions that finished in the last 24 hours. It is only edited when something a human cares about changed.

## Which sessions count as "kitchen"

The hook runs in every Claude Code session, but it only acts inside kitchen sessions. A session counts when either:

- its working directory is inside `<something>/.worktrees/<slug>/...` (`DISCORD_HQ_WORKTREES_DIR`), or
- it runs in a tmux session named `kitchen-<slug>` (`DISCORD_HQ_SESSION_PREFIX`).

Your main (waiter) session matches neither, so it never alerts itself.

Two conventions let the tools know more. Both are optional.

- **Done marker.** When a unit has opened its PR, it creates `<worktree>/.kitchen/done` (`DISCORD_HQ_MARKER_DIR`). The next `Stop` becomes ✅ ready, and the PR link comes from `gh pr view` (`DISCORD_HQ_GH`).
- **Batch manifests.** Markdown tables in `docs/plans/*-manifest.md` (`DISCORD_HQ_MANIFEST_GLOB`) in the main checkout, one row per unit. The first cell is the slug, and the first later cell that starts with a state emoji is the state:

  ```markdown
  | unit | route | state | PR |
  |---|---|---|---|
  | add-login | kitchen | ⏳ waiting for you — needs the dev server | |
  ```

  States: ⏸ queued · 🔄 working · ⏳ waiting · ✅ ready · 🚫 aborted · 🧊 stalled. When the same slug appears in several manifests, the newest file name wins.

## Installing the hook

`install.sh` prints the snippet with the right interpreter path. Merge it into `~/.claude/settings.json` yourself:

```json
{
  "hooks": {
    "Notification": [{ "hooks": [{ "type": "command", "command": "\"/path/to/claude-code-discord-hq/.venv/bin/python\" -m discord_hq hook" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "\"/path/to/claude-code-discord-hq/.venv/bin/python\" -m discord_hq hook" }] }]
  }
}
```

The installer never edits that file, because hooks change how every Claude Code session behaves. You should see and own that change.

**The hook's contract** (covered by tests):

- no output on stdout;
- never raises;
- always exits 0;
- short timeouts on every subprocess and HTTP call (3 to 10 seconds);
- the same alert isn't repeated within 60 seconds.

A broken config, a missing webhook or a network error just means no alert. Your session is never affected.

## Installing the watchdog

- **macOS:** `install.sh` writes `~/Library/LaunchAgents/com.claude-code-discord-hq.watch.plist` and loads it. It runs `discord-hq watch` every 120 seconds, with Homebrew on `PATH`. Logs go to `~/Library/Logs/claude-code-discord-hq.watch.*.log`.
- **Linux:** add a cron line (`crontab -e`):

  ```
  */2 * * * * /path/to/claude-code-discord-hq/.venv/bin/python -m discord_hq watch >/dev/null 2>&1
  ```

  Or use a systemd user timer that runs the same command.

The watchdog only reads tmux. It lists sessions, captures the screen and reads the pane's directory; it never sends keys and never kills a session. It finds transcripts under `~/.claude/projects` (or `$CLAUDE_CONFIG_DIR/projects`), including subagent transcripts, so a busy subagent doesn't look like a hang.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `DISCORD_HQ_MENTION_USER_ID` | *(none)* | who gets pinged |
| `DISCORD_HQ_WEBHOOK_READY` / `_ALERT` / `_PANEL` | `Pass` / `Bell` / `Panel` | webhook names from the design |
| `DISCORD_HQ_SESSION_PREFIX` | `kitchen-` | tmux prefix of kitchen sessions |
| `DISCORD_HQ_WORKTREES_DIR` | `.worktrees` | folder that holds the worktrees |
| `DISCORD_HQ_MARKER_DIR` | `.kitchen` | per-worktree marker folder (`done`, dedup files) |
| `DISCORD_HQ_MANIFEST_GLOB` | `docs/plans/*-manifest.md` | batch manifests, relative to the main checkout |
| `DISCORD_HQ_STALL_MINUTES` | `10` | minutes without progress before 🧊 |
| `DISCORD_HQ_GH` | `gh` | how to call the GitHub CLI |
| `DISCORD_HQ_CLICK_COMMAND` | `open -a Terminal` | macOS: what clicking a notification runs; `{attach}` is replaced by the attach command |

For clickable notifications on macOS, install `terminal-notifier` (`brew install terminal-notifier`). Without it, the tool falls back to `osascript` (no click action).

## Troubleshooting

- **No alerts at all.**
  - Run `echo '{"hook_event_name":"Notification","notification_type":"permission_prompt","cwd":"'$PWD'","message":"test"}' | .venv/bin/python -m discord_hq hook` from inside a worktree folder.
  - Check that `webhooks.json` has the webhook names you configured.
- **Everything is 🧊 in the panel.** Your tmux screen probably isn't showing Claude Code's "esc to interrupt" line in the active pane. Check `tmux capture-pane -p -t '=kitchen-x:'`.
- **The LaunchAgent does nothing.** Check `~/Library/Logs/claude-code-discord-hq.watch.err.log` and `launchctl print gui/$(id -u)/com.claude-code-discord-hq.watch`.
