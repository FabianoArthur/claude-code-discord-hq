#!/usr/bin/env bash
# Install claude-code-discord-hq for the current user.
#
#   ./install.sh               install (asks before every write)
#   ./install.sh --dry-run     show what would happen, write nothing
#   ./install.sh --uninstall   remove what install.sh created
#
# Options: --yes (no questions), --no-venv (skip the Python environment),
#          --no-load (write the LaunchAgent but do not load/unload it).
#
# What it may write (each one only after you confirm):
#   <repo>/.venv                                   Python environment
#   ~/.config/claude-code-discord-hq/.env          settings, mode 0600
#   ~/Library/LaunchAgents/com.claude-code-discord-hq.watch.plist   (macOS)
#
# What it NEVER writes: ~/.claude/settings.json and your shell rc file. It
# prints the exact snippets to paste there instead, so you see every change to
# how Claude Code and your shell behave. Safe to run again at any time.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.claude-code-discord-hq.watch"
VENV="$REPO/.venv"
PYTHON_IN_VENV="$VENV/bin/python"
CONFIG_DIR="${DISCORD_HQ_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/claude-code-discord-hq}"
AGENT_DIR="$HOME/Library/LaunchAgents"
AGENT="$AGENT_DIR/$LABEL.plist"

DRY_RUN=0
YES=0
UNINSTALL=0
NO_VENV=0
NO_LOAD=0

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes | -y) YES=1 ;;
    --uninstall) UNINSTALL=1 ;;
    --no-venv) NO_VENV=1 ;;
    --no-load) NO_LOAD=1 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }

# A dangling symlink where we would create a file could point anywhere
# (another file of yours, a system file), so it is refused, never followed.
# A link to something that exists (stow, chezmoi) is left alone by the
# "already exists" checks, which never write.
refuse_dangling_symlink() {
  if [ -L "$1" ] && [ ! -e "$1" ]; then
    printf 'error: %s is a symlink to nothing; refusing to write through it. Remove it and rerun.\n' "$1" >&2
    exit 1
  fi
}

# The LaunchAgent is rewritten in place when it changes, so any symlink there
# is refused.
refuse_symlink() {
  if [ -L "$1" ]; then
    printf 'error: %s is a symlink; refusing to write through it. Remove it and rerun.\n' "$1" >&2
    exit 1
  fi
}

# These paths are pasted into sed, the plist (XML), the hook JSON snippet and
# two lines a shell runs (the hook command, `source`). A quote, backslash, &,
# <, >, #, $, backtick or newline there would break that quoting, so refuse up
# front instead of escaping for four syntaxes at once.
check_safe_path() {
  case "$2" in
    *[\"\\\&\<\>\#\$\`]* | *$'\n'*)
      printf 'error: %s (%s) contains an unsafe character (" \\ & < > # $ ` or newline); move it and rerun.\n' "$1" "$2" >&2
      exit 2
      ;;
  esac
}

# confirm "question": 0 = go ahead, 1 = skip. Dry runs never go ahead.
confirm() {
  if [ "$DRY_RUN" -eq 1 ]; then
    say "[dry-run] would: $1"
    return 1
  fi
  if [ "$YES" -eq 1 ]; then
    return 0
  fi
  if [ ! -r /dev/tty ]; then
    say "skipped (no terminal to ask; rerun with --yes): $1"
    return 1
  fi
  local reply
  printf '%s [y/N] ' "$1"
  read -r reply </dev/tty || reply=""
  case "$reply" in y | Y | yes | YES) return 0 ;; *) say "skipped."; return 1 ;; esac
}

find_python() {
  local candidate
  for candidate in "${DISCORD_HQ_PYTHON:-}" python3.13 python3.12 python3.11 python3; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

install_venv() {
  step "Python environment ($VENV)"
  if [ "$NO_VENV" -eq 1 ]; then
    say "skipped (--no-venv)."
    return
  fi
  if [ -x "$PYTHON_IN_VENV" ] && "$PYTHON_IN_VENV" -c 'import discord_hq' 2>/dev/null; then
    say "already installed."
    return
  fi
  local python
  if ! python="$(find_python)"; then
    say "error: Python 3.11+ not found (set DISCORD_HQ_PYTHON=/path/to/python3.11+)." >&2
    exit 1
  fi
  if confirm "create $VENV with $python and install the package (pip install -e '.[icon]')"; then
    "$python" -m venv "$VENV"
    "$PYTHON_IN_VENV" -m pip install --quiet --upgrade pip
    "$PYTHON_IN_VENV" -m pip install --quiet -e "${REPO}[icon]"
    say "installed."
  fi
}

install_config() {
  step "Settings ($CONFIG_DIR/.env)"
  refuse_dangling_symlink "$CONFIG_DIR"
  refuse_dangling_symlink "$CONFIG_DIR/.env"
  if [ -f "$CONFIG_DIR/.env" ]; then
    say "already exists; left untouched."
    return
  fi
  if confirm "create $CONFIG_DIR/.env from .env.example (mode 0600)"; then
    mkdir -p "$CONFIG_DIR"
    chmod 700 "$CONFIG_DIR"
    (umask 077 && cp "$REPO/.env.example" "$CONFIG_DIR/.env")
    chmod 600 "$CONFIG_DIR/.env"
    say "created. Edit it before running discord-hq."
  fi
}

render_agent() {
  local logs="$HOME/Library/Logs"
  sed -e "s#__PYTHON__#$PYTHON_IN_VENV#g" -e "s#__LOG_DIR__#$logs#g" \
    "$REPO/launchd/$LABEL.plist.template"
}

install_watchdog() {
  step "Watchdog (every 2 minutes)"
  if [ "$(uname -s)" != "Darwin" ]; then
    say "Not macOS: add this line with 'crontab -e' (or use a systemd user timer, see docs/notifications.md):"
    say "*/2 * * * * $PYTHON_IN_VENV -m discord_hq watch >/dev/null 2>&1"
    return
  fi
  local rendered backup
  refuse_symlink "$AGENT"
  rendered="$(render_agent)"
  if [ -f "$AGENT" ] && [ "$(cat "$AGENT")" = "$rendered" ]; then
    say "LaunchAgent already up to date ($AGENT)."
  elif confirm "write the LaunchAgent to $AGENT"; then
    mkdir -p "$AGENT_DIR"
    if [ -f "$AGENT" ]; then
      # Someone (maybe you) changed it: keep their version next to it.
      backup="$AGENT.bak.$(date +%Y%m%d%H%M%S)"
      cp -p "$AGENT" "$backup"
      say "previous LaunchAgent saved as $backup"
    fi
    printf '%s\n' "$rendered" >"$AGENT"
    say "written."
  else
    return 0
  fi
  if [ "$NO_LOAD" -eq 1 ] || [ "$DRY_RUN" -eq 1 ]; then
    say "not loaded (--no-load / --dry-run). Load it with: launchctl bootstrap gui/$(id -u) $AGENT"
    return 0
  fi
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENT"
  say "loaded."
}

print_snippets() {
  step "Claude Code hooks (paste into ~/.claude/settings.json yourself)"
  local command="\\\"$PYTHON_IN_VENV\\\" -m discord_hq hook"
  cat <<JSON
{
  "hooks": {
    "Notification": [{ "hooks": [{ "type": "command", "command": "$command" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "$command" }] }]
  }
}
JSON
  say "Merge these keys with any hooks you already have. The hook never prints, never fails and always exits 0."

  step "The waiter shortcut (add to ~/.zshrc yourself)"
  say "source \"$REPO/shell/waiter.zsh\""

  step "Next"
  say "1. Fill in $CONFIG_DIR/.env (see docs/bot-setup.md)."
  say "2. Copy examples/minimal.toml or examples/restaurant.toml to your design file."
  say "3. $VENV/bin/discord-hq plan   then   $VENV/bin/discord-hq apply"
}

uninstall() {
  step "Uninstall"
  if [ -f "$AGENT" ]; then
    if confirm "unload and remove $AGENT"; then
      if [ "$NO_LOAD" -eq 0 ]; then
        launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
      fi
      rm -f "$AGENT"
      say "LaunchAgent removed."
    fi
  else
    say "no LaunchAgent installed."
  fi
  if [ "$NO_VENV" -eq 1 ]; then
    say "Python environment kept (--no-venv)."
  elif [ -d "$VENV" ]; then
    if confirm "remove the Python environment $VENV"; then
      rm -rf "$VENV"
      say "environment removed."
    fi
  fi
  say ""
  say "Left in place on purpose (remove them yourself, see docs/uninstall.md):"
  say "- $CONFIG_DIR (your settings and webhook URLs)"
  say "- the hooks in ~/.claude/settings.json and the 'source' line in ~/.zshrc"
  say "- the Discord side: delete the webhooks and reset or delete the bot tokens"
}

check_safe_path "repo path" "$REPO"
check_safe_path "HOME" "$HOME"

if [ "$UNINSTALL" -eq 1 ]; then
  uninstall
  exit 0
fi

say "claude-code-discord-hq installer (repo: $REPO)"
[ "$DRY_RUN" -eq 1 ] && say "Dry run: nothing will be written."
install_venv
install_config
install_watchdog
print_snippets
