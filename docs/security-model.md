# Security model

This project connects three things that should be kept apart: a chat server other people can join, AI agents that can run commands on your machine, and credentials. These are the rules it follows, and the ones it asks you to follow.

## 1. Credentials

| Secret | Where it lives | Who reads it | If it leaks |
|---|---|---|---|
| Admin bot token | `~/.config/claude-code-discord-hq/.env` (0600), **only during `apply`** | `discord-hq plan/apply/audit-forum` | Full control of the server. Reset it in the Developer Portal. |
| Waiter/station bot tokens | the Discord plugin's own config (`/discord:configure`) | the plugin | The attacker can read and post wherever that bot can. Reset the token. |
| Webhook URLs | `~/.config/claude-code-discord-hq/webhooks.json` (0600) | the hook, the watchdog, the panel | Anyone can post as that webhook. Delete it in Discord and run `apply`. |

- **The admin token is temporary by design.** Reset it right after `apply`. The bots that talk to Claude Code never get Administrator.
- No secret is ever written to the repository, to `state.json`, to stdout, or into an exception message:
  - `requests` puts URLs in its error messages, so the HTTP client re-raises without chaining;
  - the hook, the sinks and the panel swallow errors silently.

  Tests cover each of these.
- `.env`, `webhooks.json`, `state.json` and `*.env` are git-ignored. CI runs gitleaks over the whole history.
- `install.sh` creates the config folder as 0700 and `.env` as 0600, and never overwrites an existing `.env`.

## 2. Permissions on the server

- **@everyone sees nothing** in the categories the design manages. Every role that should see a category is listed explicitly, and every other role in the design gets an explicit deny, so a stale allow can never linger.
- Permissions are written **on each channel**, not only on the category. Discord doesn't propagate category permissions to existing channels.
- **Read-only** channels (rules, the live panel) deny *Send Messages* to everyone. Read-only **roles** (guests in the start category) can read but not write.
- `apply` never deletes anything unless you list the exact channel id **and** pass `--allow-delete`. It asks before applying unless you pass `--yes`.

## 3. Bots and messages: prompt injection

A message in a channel is **data, not an instruction**. Anyone who can post where a bot reads can try to steer the agent behind it: "ignore your rules", "approve this pairing", "print your .env". The design limits who can post where, and the rules below limit what a successful message could do.

- **DMs closed.** Keep the plugin's DM policy on allowlist, with only yourself on the list. Pairing always needs a code typed in the terminal, never in a message.
- **Guests are fenced.**
  - The guest role reads the start category and writes only in its own channel.
  - The waiter answers there **only when mentioned**.
  - Guest orders are written down and wait for your approval. The waiter must not run commands, read secrets, or dispatch work because a guest asked. Put this in your waiter's instructions (`CLAUDE.md`).
- **Two bots never answer the same channel.** The validator refuses a design where two bots would both answer every message in one channel. A bot answering the other bot's output would be an injection loop.
- **Access changes never come from a message.** `discord-hq access` only *prints* the plugin commands; you type them in the bot's terminal. Nothing in this project edits the plugin's `access.json`.
- **Free text is defused before it is re-posted.** An assistant's last message or a manifest reason can carry text the agent read from outside. `[label](url)` links are neutralized, so a notification can't hide a malicious link behind friendly text. Mentions are limited to you (`allowed_mentions`).
- **Slugs are sanitized** before they reach a shell command (the notification click action, the attach hint). A folder or tmux session name is not trusted input.

## 4. Your machine

- **The hook can't break a session.** It never raises, never prints and always exits 0, and every external call has a short timeout.
- **The watchdog only reads tmux.** It never sends keystrokes and never kills sessions.
- **`install.sh` never edits `~/.claude/settings.json` or your shell rc file.** It prints the snippets, and every other write needs your confirmation (`--dry-run` shows everything first).
- **`install.sh` never writes through a symlink and never needs `sudo`.** A LaunchAgent that differs from the one it would write is backed up first (`.bak.<timestamp>`).
- **The waiter runs with normal permission prompts.** `shell/waiter.zsh` never passes `--dangerously-skip-permissions`, and a test enforces it. If you run kitchen sessions with skipped permissions, read [the threat model](threat-model.md#running-kitchens-with---dangerously-skip-permissions) first: isolation, no production credentials, protected branches, and nothing dispatched from Discord without your approval.

## 5. Reporting

See [SECURITY.md](../SECURITY.md).
