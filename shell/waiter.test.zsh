#!/usr/bin/env zsh
# Tests for the `waiter` shortcut, on an ISOLATED tmux socket: it never touches
# your real `waiter` session or any other session. Real tmux (not a mock), but
# every `tmux` call is forced onto a throwaway `-L` socket by a shim on PATH;
# `claude` and `caffeinate` are fakes, so no real CLI ever starts.
#
# Usage: zsh shell/waiter.test.zsh
set -uo pipefail

SCRIPT_DIR="${0:A:h}"
REAL_TMUX="$(command -v tmux)"
SOCKET="waiter-test-$$"
FAKE_BIN_DIR="$(mktemp -d)"
LOG_DIR="$(mktemp -d)"
FAIL=0

rtmux() { "$REAL_TMUX" -L "$SOCKET" "$@"; }

cleanup() {
  rtmux kill-server >/dev/null 2>&1 || true
  rm -rf "$FAKE_BIN_DIR" "$LOG_DIR"
}
trap cleanup EXIT

fail() { echo "FAIL: $1"; FAIL=1; }
pass() { echo "ok: $1"; }

# Run a command inside a pseudo-terminal (tmux attach needs one). BSD and
# util-linux `script` take different arguments.
in_pty() {
  if script --version 2>/dev/null | grep -q util-linux; then
    script -q -c "$1" /dev/null </dev/null
  else
    script -q /dev/null zsh -c "$1" </dev/null
  fi
}

# --- 1. Syntax ------------------------------------------------------------
if zsh -n "$SCRIPT_DIR/waiter.zsh" 2>/dev/null; then
  pass "zsh -n waiter.zsh"
else
  fail "zsh -n waiter.zsh"
  exit 1
fi

# --- 2. Static checks --------------------------------------------------------
if grep -q -- '--dangerously-skip-permissions' "$SCRIPT_DIR/waiter.zsh"; then
  fail "waiter.zsh must not skip permissions (the waiter talks to Discord)"
else
  pass "no --dangerously-skip-permissions"
fi

if grep -q 'has-session -t "=' "$SCRIPT_DIR/waiter.zsh" && grep -q 'attach -t "=' "$SCRIPT_DIR/waiter.zsh"; then
  pass "exact-match targets (-t \"=name\") on has-session and attach"
else
  fail "expected exact-match -t \"=...\" on has-session and attach (a bare name prefix-matches)"
fi

GHOST_VARS=(TERM_PROGRAM GHOSTTY_RESOURCES_DIR GHOSTTY_BIN_DIR GHOSTTY_SHELL_FEATURES GHOST_COMPLETE_ACTIVE)
missing=()
for v in "${GHOST_VARS[@]}"; do grep -q -- "-u $v" "$SCRIPT_DIR/waiter.zsh" || missing+=("$v"); done
(( ${#missing[@]} == 0 )) && pass "unsets the terminal-integration variables" || fail "does not unset: ${missing[*]}"

# --- 3. Fakes -------------------------------------------------------------------
cat > "$FAKE_BIN_DIR/tmux" <<SHIM
#!/usr/bin/env zsh
exec "$REAL_TMUX" -L "$SOCKET" "\$@"
SHIM
cat > "$FAKE_BIN_DIR/caffeinate" <<'SHIM'
#!/usr/bin/env zsh
shift
exec "$@"
SHIM
cat > "$FAKE_BIN_DIR/claude" <<'SHIM'
#!/usr/bin/env zsh
exec sleep 600
SHIM
chmod +x "$FAKE_BIN_DIR"/*
export PATH="$FAKE_BIN_DIR:$PATH"
export WAITER_DIR="$LOG_DIR"
# CI runners have TERM unset or "dumb", and tmux refuses to attach to that.
# The pty created by `script` is a real terminal, so name one.
export TERM=xterm-256color

wait_for() {
  local tries=0
  while (( tries < 50 )); do
    eval "$1" >/dev/null 2>&1 && return 0
    sleep 0.1
    (( tries++ ))
  done
  return 1
}

# --- 4. First call creates the session --------------------------------------------
in_pty "source '$SCRIPT_DIR/waiter.zsh'; waiter" >"$LOG_DIR/call1.log" 2>&1 &
CALL1=$!
if wait_for "rtmux has-session -t '=waiter'"; then
  pass "first call creates the waiter session"
else
  fail "first call did not create the session"
  cat "$LOG_DIR/call1.log"
fi

pane_cmd=$(rtmux list-panes -t '=waiter:' -F '#{pane_start_command}' 2>/dev/null)
[[ "$pane_cmd" == *"--channels plugin:discord@claude-plugins-official"* ]] && pass "starts claude with the Discord channel" || fail "unexpected start command: $pane_cmd"
missing=()
for v in "${GHOST_VARS[@]}"; do [[ "$pane_cmd" == *"-u $v"* ]] || missing+=("$v"); done
(( ${#missing[@]} == 0 )) && pass "real start command unsets the variables" || fail "start command keeps: ${missing[*]}"

rtmux detach-client -s waiter >/dev/null 2>&1 || true
wait "$CALL1" 2>/dev/null
count=$(rtmux ls 2>/dev/null | grep -c '^waiter:')
[[ "$count" == "1" ]] && pass "one session after the first call" || fail "expected 1 session, found $count"

# --- 5. Second call re-attaches, never duplicates ------------------------------------
in_pty "source '$SCRIPT_DIR/waiter.zsh'; waiter" >"$LOG_DIR/call2.log" 2>&1 &
CALL2=$!
sleep 0.5
rtmux detach-client -s waiter >/dev/null 2>&1 || true
wait "$CALL2" 2>/dev/null
grep -qi 'duplicate session' "$LOG_DIR/call2.log" && fail "second call tried to create a duplicate" || pass "second call did not try to duplicate"
count=$(rtmux ls 2>/dev/null | grep -c '^waiter:')
[[ "$count" == "1" ]] && pass "two calls -> still one session" || fail "two calls -> expected 1 session, found $count"

(( FAIL == 0 )) && echo "--- all waiter tests passed ---" || echo "--- failures above ---"
exit $FAIL
