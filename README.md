# claude-code-discord-hq

**Run your Claude Code sessions from your phone.** A Discord server defined as code, plus notifications that tell you when an AI coding session needs you.

[Português (Brasil)](README.pt-BR.md) · [Design format](docs/design-format.md) · [Security model](docs/security-model.md) · [Threat model](docs/threat-model.md)

[![CI](https://github.com/Fabiano-Arthur/claude-code-discord-hq/actions/workflows/ci.yml/badge.svg)](https://github.com/Fabiano-Arthur/claude-code-discord-hq/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

---

## What it is

Two tools that work well together, and also work on their own:

1. **Server as code.** You describe your Discord server in one TOML file: roles, categories, channels, who sees what, which channels are read-only, forum tags, webhooks, Community settings and pinned messages. `discord-hq plan` shows the difference with the live server. `discord-hq apply` makes the server match, idempotently: a second run changes nothing.
2. **Claude Code notifications.** A `Notification`/`Stop` hook and a small watchdog tell you, on your Mac and in Discord, when a session:
   - needs approval,
   - stopped,
   - hung without progress,
   - is waiting for you,
   - opened its pull request.

   A live panel message shows every session at a glance.

Combined with the official Claude Code Discord plugin (`/plugin install discord@claude-plugins-official`), you can talk to your main session from your phone and get pinged when the work is ready to review.

## Why: the waiter and the kitchen

This project came out of a way of working with Claude Code that uses a restaurant as the metaphor:

| Role | What it is | What it does |
|---|---|---|
| **Waiter** | your main Claude Code session | Talks to you, takes orders, sends them to the kitchen and serves the results. It **never cooks**: it doesn't edit code itself. |
| **Kitchen** | one tmux session per order, each in its own git worktree | Works on a single order until a pull request is open. Many orders cook in parallel. |
| **Chef** | you | You taste (review) and merge. |
| **Guest** | someone you invite | Places orders that wait for the chef's approval. |

The waiter stays available because it never gets buried in one task. The kitchen can cook many dishes at once because each order is isolated. What you need is a **counter**: a place to talk to the waiter from anywhere, and to be told when a dish is ready or a cook is stuck. That counter is this Discord server. More in [docs/waiter-kitchen.md](docs/waiter-kitchen.md).

You don't need the whole workflow. The server-as-code part works for any Discord server, and the notifications work for any Claude Code session running in a git worktree or a tmux session.

## How it works

```
                 you (phone / desktop)
                          │
                   Discord server  ◄──────────── discord-hq apply
     ┌────────────────────┼─────────────────────┐   (design.toml → roles,
     │ #table   #orders   │ #served  #alerts    │    channels, permissions,
     │ (talk)   (forums)  │ #panel (live board) │    webhooks)
     └────────┬───────────┴──────────▲──────────┘
              │ bot (official         │ webhooks (no bot token)
              │ Discord plugin)       │
      ┌───────▼────────┐     ┌────────┴─────────────────────────────┐
      │ waiter session │     │ discord-hq hook   (Notification/Stop)│
      │ (tmux: waiter) │     │ discord-hq watch  (every 2 minutes)  │
      └───────┬────────┘     └────────▲─────────────────────────────┘
              │ dispatches            │ reads: hook events, tmux screens,
      ┌───────▼─────────────────┐     │ transcripts, batch manifests
      │ kitchen-a  kitchen-b ...│─────┘
      │ (tmux + git worktrees)  │   also: macOS notification with the
      └─────────────────────────┘   tmux attach command on the clipboard
```

- **`discord-hq plan` / `apply`** use a temporary admin bot token. They read the server, compute a diff and apply it. Channels are matched by (name, type, category), never by name alone. Permission overwrites are written on every channel, because Discord doesn't propagate category permissions to existing channels. See [docs/design-format.md](docs/design-format.md).
- **`discord-hq hook`** runs on Claude Code's `Notification` and `Stop` events. It only acts inside kitchen sessions, which it recognises by a git worktree folder or a tmux session prefix.
- **`discord-hq watch`** runs every 2 minutes (LaunchAgent on macOS, cron on Linux). It does three things:
  - flags sessions whose screen says "esc to interrupt" but whose transcript stopped moving;
  - raises units marked ⏳ in a batch manifest;
  - edits one live panel message.
- Alerts reach Discord through **webhooks**, not a bot token, and mention only you.

## Quickstart

Requirements: Python 3.11+, git, tmux, a Discord account. macOS gets native notifications. Linux works too, with Discord alerts only.

1. **Clone and install:**
   ```sh
   git clone https://github.com/Fabiano-Arthur/claude-code-discord-hq.git
   cd claude-code-discord-hq
   ./install.sh --dry-run   # see what it would do
   ./install.sh             # asks before every write
   ```
2. **Create a server** in Discord and turn on Developer Mode (Settings → Advanced).
3. **Create a temporary admin bot** and invite it: [docs/bot-setup.md](docs/bot-setup.md). Put its token and your server id in `~/.config/claude-code-discord-hq/.env`.
4. **Pick a design:** `cp examples/restaurant.toml design.toml`, or start from `examples/minimal.toml`, then edit it.
5. **Preview:** `.venv/bin/discord-hq plan`
6. **Apply:** `.venv/bin/discord-hq apply`. Then **reset the admin bot's token** in the Developer Portal. You only need it again to change the server.
7. **Turn on notifications:** paste the hook snippet printed by `install.sh` into `~/.claude/settings.json`, and set `DISCORD_HQ_MENTION_USER_ID` in the `.env`.
8. **Connect your waiter:** install the official Discord plugin in Claude Code, add `source .../shell/waiter.zsh` to `~/.zshrc`, and run `waiter`. Then run `.venv/bin/discord-hq access --bot waiter` and type the printed commands in that session.

## Commands

| Command | What it does |
|---|---|
| `discord-hq plan [--design FILE]` | Shows what `apply` would change. Read-only. |
| `discord-hq apply [--design FILE] [--yes] [--allow-delete]` | Makes the server match the design. It asks first, and holds deletions back unless `--allow-delete`. |
| `discord-hq audit-forum CHANNEL_ID` | Lists a forum's posts before you move or rename it. Read-only. |
| `discord-hq access --bot NAME` | Prints the `/discord:access` commands for one bot's channels. It never edits anything. |
| `discord-hq hook` | The Claude Code hook. Reads the event on stdin, prints nothing, always exits 0. |
| `discord-hq watch` | One watchdog pass: stalled sessions, paused units, live panel. |

All settings are environment variables, or lines in `~/.config/claude-code-discord-hq/.env`. [`.env.example`](.env.example) documents every one.

## Security

Short version, with the full story in [docs/security-model.md](docs/security-model.md) and [docs/threat-model.md](docs/threat-model.md):

- **The admin token is temporary.** Use it for `apply`, then reset it. The bots that talk to Claude Code never need admin rights.
- **Secrets stay outside the repo.** Tokens live in `~/.config/claude-code-discord-hq/.env` and webhook URLs in `webhooks.json`, both mode 0600. `state.json` holds ids only and is git-ignored. Tokens and webhook URLs never reach stdout, logs or exceptions.
- **Messages are data, not instructions.** Anything a bot reads in a channel can be a prompt injection. The design keeps DMs closed (the plugin's allowlist), gives guests their own channel with mention-only replies, and never lets two bots answer the same channel. `discord-hq access` prints commands instead of editing the plugin's `access.json`.
- **The hook can't break your session.** It has short timeouts, never raises, never prints, and always exits 0.
- **The installer asks first.** `install.sh` confirms before every write. It never edits `~/.claude/settings.json` or your shell rc file; it prints what to paste.

Found a vulnerability? See [SECURITY.md](SECURITY.md).

## FAQ

**Does this call the Discord API on its own?**
Only `plan`, `apply` and `audit-forum` use the bot API, and only when you run them. The hook and the watchdog only post through the webhooks you created.

**Will `apply` wipe my existing server?**
No. It only manages what the design declares. Channels in other categories and permission overwrites for other users or roles are left alone. Deletions happen only for channel ids you list under `[cleanup]`, and only with `--allow-delete`.

**What if I lose `state.json`?**
Roles, categories, channels and webhooks are never duplicated: the live server is the source of truth, and the next `apply` rebuilds the file (even when nothing else changed). The one thing tracked only in `state.json` is which `[[pinned_messages]]` were already posted, so those would be posted again. `discord-hq access` needs the file, so run `apply` first.

**I renamed a channel's category in the design and got a new channel. Why?**
A channel's identity is (name, type, category). Moving channels automatically once corrupted a real server, so a moved channel is created fresh and the old one is left for you. Use `rename_from` on the category to rename it in place: the same id keeps its channels and forum posts.

**Can I use it without tmux or worktrees?**
The server-as-code part, yes. The notifications need a way to tell kitchen sessions apart. They look for a `.worktrees/<name>` folder (configurable) or a tmux session prefix (`kitchen-` by default).

**Linux? Windows?**
Linux: yes, with Discord alerts only (no native notification) and a cron line instead of the LaunchAgent. Windows: the server-as-code part should work under Python; the rest is untested.

**Is this affiliated with Anthropic or Discord?**
No. It's an independent open source project.

## Contributing

Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). The test suite never talks to Discord and never touches your real tmux sessions.

## License

[MIT](LICENSE) © 2026 Fabiano Arthur
