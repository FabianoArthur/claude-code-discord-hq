# `waiter`: open (or re-attach to) the tmux session that runs your main
# Claude Code session, connected to Discord through the official plugin.
#
#   source /path/to/claude-code-discord-hq/shell/waiter.zsh   # in ~/.zshrc
#
# It never starts a second session: a Discord bot token serves one connected
# client at a time, so a duplicate would fight the first one.
#
# Optional settings (export before sourcing, or in ~/.zshrc):
#   WAITER_SESSION  tmux session name        (default: waiter)
#   WAITER_DIR      working directory        (default: $HOME)
#
# Some terminals' shell integrations (for example Ghostty with ghost-complete)
# take over the PTY inside tmux and hang every shell command a tool runs. The
# variables that trigger them are removed before claude starts; this is
# harmless everywhere else. `caffeinate` (macOS) keeps the Mac awake while the
# session runs; it is skipped where it does not exist.
waiter() {
  local session="${WAITER_SESSION:-waiter}"
  local dir="${WAITER_DIR:-$HOME}"
  local keep_awake=""
  command -v caffeinate >/dev/null 2>&1 && keep_awake="caffeinate -i "

  tmux has-session -t "=$session" 2>/dev/null && { tmux attach -t "=$session"; return; }
  tmux new -s "$session" -c "$dir" \
    "env -u TERM_PROGRAM -u GHOSTTY_RESOURCES_DIR -u GHOSTTY_BIN_DIR -u GHOSTTY_SHELL_FEATURES -u GHOST_COMPLETE_ACTIVE ${keep_awake}claude --channels plugin:discord@claude-plugins-official"
}
